"""策略脚本集合

存放可复用的策略回测。当前包含：

- ``run_daily_momentum_strategy`` —— 5 宽基指数日频动量轮动（每日选过去 N 日最强者）
- ``run_signal_strategy`` —— 通用 tag 信号驱动回测（买入/卖出各为一个 Signal，不对称）
"""
from __future__ import annotations

from pathlib import Path

import polars as pl


MOMENTUM_INDICES = {
    "000300": "CSI300",
    "000905": "CSI500",
    "399673": "ChiNext50",
    "000016": "SSE50",
    "000688": "STAR50",
}


def run_daily_momentum_strategy(
    input_dir: str,
    output_csv: str,
    output_png: str | None = None,
    lookback_days: int = 20,
    cost_rate: float = 0.0003,
    indices: dict[str, str] | None = None,
) -> dict:
    """日频动量轮动策略：每日选过去 lookback_days 日收益最强指数持有

    策略逻辑：
      - 每个交易日，比较有数据的指数过去 lookback_days 个交易日收益（close[T]/close[T-L]-1），选最强者
      - 用 T-1 日信号决定 T 日持仓（避免未来函数）
      - 上市时间不同的指数按日动态加入比较池（full join），不截断整体回测
      - 换仓按成本扣减：每次卖/买各扣 cost_rate，换仓=2 次，建仓=1 次，持有不变=0 次
      - 年化（CAGR）按实际日历跨度计算，波动/Sharpe 按数据推得的年交易日数
      - 纯数学模拟

    Returns:
        统计指标字典（总收益、最终倍数、年化、波动、Sharpe、最大回撤、换仓次数、平均持仓天数）
    """
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    indices = indices or MOMENTUM_INDICES
    names = list(indices.values())
    colors = {n: c for n, c in zip(names, ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd"])}

    # 1. 读各指数日线，full join 对齐（不同上市时间留 null）
    frames = []
    for code, name in indices.items():
        fp = Path(input_dir) / f"{code}.parquet"
        df = pl.read_parquet(fp, columns=["date", "close"])
        df = df.with_columns(pl.col("date").cast(pl.Date)).sort("date").rename({"close": name})
        frames.append(df)
    merged = frames[0]
    for f in frames[1:]:
        merged = merged.join(f, on="date", how="full", coalesce=True)
    df = merged.sort("date")

    # 2. 日收益 + 过去 lookback_days 日收益（动量信号）
    for n in names:
        df = df.with_columns(
            (pl.col(n) / pl.col(n).shift(1) - 1.0).alias(f"{n}_ret"),
            (pl.col(n) / pl.col(n).shift(lookback_days) - 1.0).alias(f"{n}_mom"),
        )

    # 3. 每日选最强（只比有 mom 的指数）
    mom_cols = [f"{n}_mom" for n in names]
    long = (
        df.unpivot(index="date", on=mom_cols, variable_name="idx", value_name="mom")
        .with_columns(pl.col("idx").str.replace("_mom", "").alias("idx"))
        .drop_nulls("mom")
    )
    winner = (
        long.sort("mom", descending=True)
        .group_by("date", maintain_order=True)
        .agg(pl.col("idx").first().alias("winner_idx"))
    )
    df = df.join(winner, on="date", how="left")
    df = df.with_columns(pl.col("winner_idx").shift(1).alias("held_idx"))  # T-1 信号 → T 持仓

    # 4. 查表得策略日收益（已扣换仓成本）
    records = df.to_dicts()
    strat_ret = []
    prev_held = None
    for r in records:
        h = r.get("held_idx")
        if h is None:
            strat_ret.append(None)
        else:
            gross = r.get(f"{h}_ret")
            if gross is None:
                strat_ret.append(None)
            else:
                if prev_held is None:
                    k = 1  # 建仓：买入 1 次
                elif prev_held != h:
                    k = 2  # 换仓：卖旧 + 买新
                else:
                    k = 0  # 持有不变
                strat_ret.append((1 - cost_rate) ** k * (1 + gross) - 1)
        prev_held = h
    df = df.with_columns(pl.Series(name="strat_ret", values=strat_ret))

    # 5. 净值 + 统计
    df_eval = df.filter(pl.col("strat_ret").is_not_null()).sort("date")
    bnh_cols = {n: f"{n}_BnH" for n in names}
    df_eval = df_eval.with_columns(
        (1.0 + pl.col("strat_ret")).cum_prod().alias("Strategy"),
        *[(1.0 + pl.col(f"{n}_ret")).cum_prod().alias(bnh_cols[n]) for n in names],
    )

    n_days = df_eval.height
    d0 = df_eval["date"].min()
    d1 = df_eval["date"].max()
    n_years = (d1 - d0).days / 365.25  # 实际日历跨度，避免 n_days/252 高估年化
    dpy = n_days / n_years  # 数据推得的年交易日数

    def _stats(col: str) -> tuple[float, float, float, float, float]:
        v = df_eval[col].drop_nulls()
        total = v[-1]
        cagr = total ** (1 / n_years) - 1
        daily = (v / v.shift(1) - 1).drop_nulls()
        vol = daily.std() * (dpy ** 0.5)
        sharpe = (daily.mean() * dpy) / vol if vol > 0 else 0
        dd = (v / v.cum_max() - 1).min()
        return float(total), float(cagr), float(vol), float(sharpe), float(dd)

    s_total, s_cagr, s_vol, s_sharpe, s_dd = _stats("Strategy")

    held = df_eval["held_idx"].to_list()
    n_trades = sum(1 for i in range(1, len(held)) if held[i] != held[i - 1])
    avg_hold = n_days / (n_trades + 1) if n_trades else n_days

    df_eval.select(
        ["date", "held_idx", "strat_ret", "Strategy"] + list(bnh_cols.values())
    ).write_csv(output_csv)

    stats = {
        "total_return": s_total - 1,
        "final_multiple": s_total,
        "cagr": s_cagr,
        "annual_vol": s_vol,
        "sharpe": s_sharpe,
        "max_drawdown": s_dd,
        "n_days": n_days,
        "n_trades": n_trades,
        "avg_hold_days": avg_hold,
        "start_date": str(d0),
        "end_date": str(d1),
    }

    if output_png:
        fig, ax = plt.subplots(figsize=(14, 6))
        dates = df_eval["date"].to_numpy()
        ax.plot(dates, df_eval["Strategy"].to_numpy(), color="black", linewidth=1.8,
                label=f"Daily Momentum ({lookback_days}d, cost {cost_rate:.2%}/side)")
        for n in names:
            ax.plot(dates, df_eval[bnh_cols[n]].to_numpy(), color=colors[n],
                    linewidth=0.8, alpha=0.7, label=f"{n} B&H")
        # 策略曲线末端标记最终收益倍数
        final_nav = float(df_eval["Strategy"].to_list()[-1])
        last_date = df_eval["date"].to_list()[-1]
        ax.scatter([last_date], [final_nav], color="black", s=45, zorder=5)
        ax.annotate(f"{final_nav:.1f}x", xy=(last_date, final_nav),
                    xytext=(8, 0), textcoords="offset points",
                    fontsize=12, fontweight="bold", color="black",
                    va="center", ha="left")
        ax.set_yscale("log")
        ax.set_xlabel("date")
        ax.set_ylabel("NAV (log scale)")
        ax.grid(True, which="both", alpha=0.3)
        ax.xaxis.set_major_locator(mdates.YearLocator(2))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        ax.legend(loc="upper left", ncol=2, fontsize=8)
        plt.title(f"Daily Momentum Rotation ({lookback_days}-day): " + " / ".join(names))
        fig.tight_layout()
        plt.savefig(output_png, dpi=120)
        plt.close(fig)

    return stats


def run_ma_crossover_strategy(
    input_dir: str,
    output_csv: str,
    output_png: str | None = None,
    index_code: str = "000300",
    fast_window: int = 5,
    slow_window: int = 60,
) -> dict:
    """双均线突破策略：快线上穿慢线买入，跌破卖出

    策略逻辑：
      - 计算 fast_window / slow_window 日均线
      - 当 fast_ma > slow_ma 时持仓指数，否则空仓
      - 使用 T-1 日信号决定 T 日持仓（避免未来函数）
      - 纯数学模拟，不考虑交易成本

    Returns:
        统计指标字典（总收益、年化、波动、Sharpe、最大回撤、持仓占比、交易次数）
    """
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    fp = Path(input_dir) / f"{index_code}.parquet"
    df = pl.read_parquet(fp, columns=["date", "close"])
    df = df.with_columns(pl.col("date").cast(pl.Date)).sort("date")

    df = df.with_columns(
        pl.col("close").rolling_mean(fast_window).alias("ma_fast"),
        pl.col("close").rolling_mean(slow_window).alias("ma_slow"),
        (pl.col("close") / pl.col("close").shift(1) - 1.0).alias("idx_ret"),
    )

    # 持仓信号：fast_ma > slow_ma；用 T-1 日信号决定 T 日持仓
    df = df.with_columns((pl.col("ma_fast") > pl.col("ma_slow")).alias("raw_signal"))
    df = df.with_columns(pl.col("raw_signal").shift(1).alias("position"))

    df_eval = df.filter(pl.col("position").is_not_null()).sort("date")
    df_eval = df_eval.with_columns(
        pl.when(pl.col("position")).then(pl.col("idx_ret")).otherwise(0.0).alias("strat_ret"),
    )
    df_eval = df_eval.with_columns(
        (1.0 + pl.col("strat_ret")).cum_prod().alias("Strategy"),
        (1.0 + pl.col("idx_ret")).cum_prod().alias("Index_BnH"),
    )

    n_days = df_eval.height
    n_years = n_days / 252

    def _stats(col: str) -> tuple[float, float, float, float, float]:
        v = df_eval[col].drop_nulls()
        total = v[-1]
        cagr = total ** (1 / n_years) - 1
        daily = (v / v.shift(1) - 1).drop_nulls()
        vol = daily.std() * (252 ** 0.5)
        sharpe = (daily.mean() * 252) / vol if vol > 0 else 0
        dd = (v / v.cum_max() - 1).min()
        return float(total), float(cagr), float(vol), float(sharpe), float(dd)

    s_total, s_cagr, s_vol, s_sharpe, s_dd = _stats("Strategy")

    # 交易统计
    pos_list = df_eval["position"].to_list()
    time_in_market = sum(1 for p in pos_list if p) / n_days
    # 完整一轮 = position 从 False→True 直到下一次 True→False
    n_trades = sum(1 for i in range(1, len(pos_list)) if pos_list[i] and not pos_list[i - 1])

    df_eval.select(
        ["date", "close", "ma_fast", "ma_slow", "position", "idx_ret", "strat_ret",
         "Strategy", "Index_BnH"]
    ).write_csv(output_csv)

    stats = {
        "total_return": s_total - 1,
        "cagr": s_cagr,
        "annual_vol": s_vol,
        "sharpe": s_sharpe,
        "max_drawdown": s_dd,
        "n_days": n_days,
        "time_in_market": time_in_market,
        "n_trades": n_trades,
        "start_date": str(df_eval["date"].min()),
        "end_date": str(df_eval["date"].max()),
    }

    if output_png:
        fig, ax = plt.subplots(figsize=(14, 6))
        dates = df_eval["date"].to_numpy()
        ax.plot(dates, df_eval["Strategy"].to_numpy(), color="black", linewidth=1.2,
                label=f"MA({fast_window}/{slow_window}) Strategy")
        ax.plot(dates, df_eval["Index_BnH"].to_numpy(), color="#1f77b4", linewidth=0.8,
                alpha=0.7, label=f"{index_code} B&H")
        # 持仓区间阴影
        in_pos = False
        seg_start = None
        d_arr = df_eval["date"].to_list()
        p_arr = pos_list
        for i, p in enumerate(p_arr):
            if p and not in_pos:
                seg_start = d_arr[i]
                in_pos = True
            elif not p and in_pos:
                ax.axvspan(seg_start, d_arr[i], color="#2ca02c", alpha=0.15, lw=0)
                in_pos = False
        if in_pos:
            ax.axvspan(seg_start, d_arr[-1], color="#2ca02c", alpha=0.15, lw=0)
        ax.set_yscale("log")
        ax.set_xlabel("date")
        ax.set_ylabel("NAV (log scale)")
        ax.grid(True, which="both", alpha=0.3)
        ax.xaxis.set_major_locator(mdates.YearLocator(2))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        ax.legend(loc="upper left")
        plt.title(f"MA Crossover Strategy ({index_code}, {fast_window}/{slow_window})")
        fig.tight_layout()
        plt.savefig(output_png, dpi=120)
        plt.close(fig)

    return stats


def run_signal_strategy(
    df: pl.DataFrame,
    buy: "Signal",
    sell: "Signal",
    stop: "Stop | None" = None,
) -> tuple[pl.DataFrame, list, list]:
    """通用 tag 信号驱动回测。

    - ``buy`` / ``sell``：各自一个 ``Signal``（多个 tag 经 combiner 合成），互相独立、不对称。
    - ``stop``：可选的有状态离场（``Stop`` trail/breakdown），与 ``sell`` 成 OR。
    - 所有信号 T-1 决定 T 持仓，避免未来函数；纯数学模拟，无交易成本。

    Returns:
        (out, entries, exits)
        - out: 含 position / strategy_nav / bnh_nav 列的 df（保留传入列 + 通道带列）
        - entries: [(date, price, tag), ...]
        - exits: [(date, price), ...]
    """
    from quant.signals import Stop, eval_signal

    df = df.sort("date")
    buy_col = eval_signal(df, buy)
    sell_col = (
        eval_signal(df, sell)
        if (sell is not None and sell.tags)
        else pl.Series("_sell", [False] * df.height)
    )
    df = df.with_columns(buy_col.alias("_buy"), sell_col.alias("_sell"))

    if stop is not None and stop.kind == "trail":
        df = df.with_columns(pl.col("close").rolling_std(stop.window).alias("_sigma"))
    if stop is not None and stop.kind == "breakdown":
        df = df.with_columns(
            pl.col("close").rolling_mean(stop.window).alias("_ma"),
            pl.col("close").rolling_std(stop.window).alias("_sigma"),
        ).with_columns(
            (pl.col("_ma") + stop.k * pl.col("_sigma")).alias("_upper")
        )

    dates = df["date"].to_list()
    closes = df["close"].to_list()
    highs = df["high"].to_list()
    buy_l = df["_buy"].to_list()
    sell_l = df["_sell"].to_list()
    sigma_l = df["_sigma"].to_list() if "_sigma" in df.columns else [None] * df.height
    upper_l = df["_upper"].to_list() if "_upper" in df.columns else [None] * df.height
    n = df.height

    pos = [0.0] * n
    entries: list[tuple] = []
    exits: list[tuple] = []
    in_pos = False
    peak = 0.0
    above_upper = False
    below_count = 0
    for t in range(1, n):
        b = buy_l[t - 1]
        s = sell_l[t - 1]
        cp = closes[t - 1]
        hp = highs[t - 1]
        sg = sigma_l[t - 1]
        ub = upper_l[t - 1]

        if in_pos and stop is not None and stop.kind == "trail":
            peak = max(peak, hp)

        exit_now = False
        if in_pos:
            if s:
                exit_now = True  # tag 卖出信号
            elif stop is not None:
                if stop.kind == "trail":
                    if sg is not None and cp < peak - stop.m * sg:
                        exit_now = True
                elif stop.kind == "breakdown":
                    if ub is not None:
                        if cp >= ub:
                            above_upper = True
                            below_count = 0
                        elif above_upper:
                            below_count += 1
                            if below_count >= stop.confirm:
                                exit_now = True

        if exit_now:
            in_pos = False
            above_upper = False
            below_count = 0
            exits.append((dates[t - 1], cp))
        elif not in_pos:
            if b:
                in_pos = True
                peak = hp
                above_upper = False
                below_count = 0
                entries.append((dates[t - 1], cp, "buy"))
        pos[t] = 1.0 if in_pos else 0.0

    nav = [1.0] * n
    bh = [1.0] * n
    for t in range(1, n):
        r = closes[t] / closes[t - 1] - 1.0
        nav[t] = nav[t - 1] * (1.0 + pos[t] * r)
        bh[t] = bh[t - 1] * (1.0 + r)

    out = df.with_columns(
        pl.Series("position", pos),
        pl.Series("strategy_nav", nav),
        pl.Series("bnh_nav", bh),
    )
    return out, entries, exits
