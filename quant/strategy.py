"""策略脚本集合

存放可复用的策略回测。当前包含：

- ``run_momentum_strategy`` —— CSI300/CSI500/创业板50 月度动量轮动
"""
from __future__ import annotations

from pathlib import Path

import polars as pl


MOMENTUM_INDICES = {
    "000300": "CSI300",
    "000905": "CSI500",
    "399673": "ChiNext50",
}


def _load_monthly_close(input_dir: str, indices: dict[str, str]) -> pl.DataFrame:
    """读取多个指数月度收盘价并按月对齐"""
    frames = []
    for code, name in indices.items():
        fp = Path(input_dir) / f"{code}.parquet"
        df = pl.read_parquet(fp, columns=["date", "close"])
        df = df.with_columns(pl.col("date").cast(pl.Date)).sort("date")
        df = df.with_columns(pl.col("date").dt.strftime("%Y-%m").alias("ym"))
        df = (
            df.group_by("ym")
            .agg(
                pl.col("date").max().alias("date"),
                pl.col("close").last().alias(name),
            )
            .drop("ym")
            .sort("date")
        )
        frames.append(df)

    merged = frames[0]
    for f in frames[1:]:
        merged = merged.join(f, on="date", how="inner")
    return merged


def run_momentum_strategy(
    input_dir: str,
    output_csv: str,
    output_png: str | None = None,
    indices: dict[str, str] | None = None,
) -> dict:
    """月度动量轮动策略：每月末选当月最强指数持有

    策略逻辑：
      - 每月最后一个交易日，比较各指数本月收益（上月末→本月末）
      - 选最强者持有到下个月末
      - 纯数学模拟，不考虑交易成本

    Returns:
        统计指标字典（总收益、年化、波动、Sharpe、最大回撤）
    """
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    indices = indices or MOMENTUM_INDICES
    names = list(indices.values())
    colors = {n: c for n, c in zip(names, ["#1f77b4", "#ff7f0e", "#2ca02c"])}

    df_m = _load_monthly_close(input_dir, indices)
    for n in names:
        df_m = df_m.with_columns(
            (pl.col(n) / pl.col(n).shift(1) - 1.0).alias(f"{n}_ret")
        )

    ret_cols = [f"{n}_ret" for n in names]
    long = (
        df_m.unpivot(index="date", on=ret_cols, variable_name="idx", value_name="last_ret")
        .with_columns(pl.col("idx").str.replace("_ret", "").alias("idx"))
        .drop_nulls("last_ret")
    )
    winner = (
        long.sort("last_ret", descending=True)
        .group_by("date", maintain_order=True)
        .agg(pl.col("idx").first().alias("winner_idx"))
    )
    df_m = df_m.join(winner, on="date", how="left")
    df_m = df_m.with_columns(pl.col("winner_idx").shift(1).alias("held_idx"))

    # 查表得到策略本月收益（held_idx 决定本月持仓）
    records = df_m.to_dicts()
    strat_ret = [r.get(f"{r['held_idx']}_ret") if r.get("held_idx") else None for r in records]
    df_m = df_m.with_columns(pl.Series(name="strat_ret", values=strat_ret))

    df_eval = df_m.filter(pl.col("strat_ret").is_not_null()).sort("date")
    bnh_cols = {n: f"{n}_BnH" for n in names}
    df_eval = df_eval.with_columns(
        (1.0 + pl.col("strat_ret")).cum_prod().alias("Strategy"),
        *[(1.0 + pl.col(f"{n}_ret")).cum_prod().alias(bnh_cols[n]) for n in names],
    )

    n_months = df_eval.height
    n_years = n_months / 12

    def _stats(col: str) -> tuple[float, float, float, float, float]:
        v = df_eval[col].drop_nulls()
        total = v[-1]
        cagr = total ** (1 / n_years) - 1
        monthly = (v / v.shift(1) - 1).drop_nulls()
        vol = monthly.std() * (12 ** 0.5)
        sharpe = (monthly.mean() * 12) / vol if vol > 0 else 0
        dd = (v / v.cum_max() - 1).min()
        return float(total), float(cagr), float(vol), float(sharpe), float(dd)

    strategy_total, strategy_cagr, strategy_vol, strategy_sharpe, strategy_dd = _stats("Strategy")

    # 明细 CSV
    df_eval.select(
        ["date", "held_idx", "strat_ret", "Strategy"] + list(bnh_cols.values())
    ).write_csv(output_csv)

    # NAV 曲线
    stats = {
        "total_return": strategy_total - 1,
        "cagr": strategy_cagr,
        "annual_vol": strategy_vol,
        "sharpe": strategy_sharpe,
        "max_drawdown": strategy_dd,
        "n_months": n_months,
        "start_date": str(df_eval["date"].min()),
        "end_date": str(df_eval["date"].max()),
    }

    if output_png:
        fig, ax = plt.subplots(figsize=(14, 6))
        dates = df_eval["date"].to_numpy()
        ax.plot(dates, df_eval["Strategy"].to_numpy(), color="black", linewidth=1.6,
                label="Momentum Strategy")
        for n in names:
            ax.plot(dates, df_eval[bnh_cols[n]].to_numpy(), color=colors[n],
                    linewidth=0.9, alpha=0.7, label=f"{n} B&H")
        ax.set_yscale("log")
        ax.set_xlabel("date")
        ax.set_ylabel("NAV (log scale)")
        ax.grid(True, which="both", alpha=0.3)
        ax.xaxis.set_major_locator(mdates.YearLocator(2))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        ax.legend(loc="upper left")
        plt.title("Monthly Momentum Rotation: " + " / ".join(names))
        fig.tight_layout()
        plt.savefig(output_png, dpi=120)
        plt.close(fig)

    return stats
