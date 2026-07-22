"""港股通南向资金择时策略：恒生科技 ETF(513180) 回测。

入场：当日 net_yi > 0 **且** q60 ≥ 0.9（在过去 60 日的百分位进入前 10%）
出场：当日 net_yi < 0 **且** q60 ≤ 0.1（在过去 60 日的百分位跌入末尾 10%）

q60 用「过去 60 日不含当日」窗口计算，避免与当日信号触发条件产生循环依赖。
信号在 T 日收盘后生成，T+1 日以 open 成交，避免 look-ahead bias。

数据源：
  /mnt/dataset/exchange_hkex/southbound_flow.csv (net_yi)
  /mnt/dataset/fund_quote_adjusted/513180.parquet (open, close)

输出：
  /mnt/dataset/southbound_etf_strategy.png —— 3 子图（价格+信号点 / 净值曲线 / q60）
  控制台打印绩效统计 + 交易明细
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import polars as pl

Q_WINDOW = 60
Q_HIGH = 0.9    # 前 10% 分位阈值
Q_LOW = 0.1     # 末尾 10% 分位阈值
TRADING_DAYS = 252

COLOR_BUY = "#d62728"     # 红：买入（中国市场习惯）
COLOR_SELL = "#31a354"    # 绿：卖出
COLOR_STRAT = "#08519c"
COLOR_BH = "#969696"
COLOR_Q = "#6baed6"


def load_southbound(csv_path: Path) -> pl.DataFrame:
    float_cols = {c: pl.Float64 for c in
                  ("sse_buy_yi", "sse_sell_yi", "szse_buy_yi", "szse_sell_yi",
                   "buy_yi", "sell_yi", "net_yi")}
    df = (
        pl.read_csv(csv_path, try_parse_dates=True, schema_overrides=float_cols)
        .sort("date")
        .with_columns(pl.col("net_yi").fill_null(0))
    )
    # 60 日分位（不含当日）
    arr = df["net_yi"].to_numpy().astype(float)
    n = len(arr)
    q = np.full(n, np.nan)
    for i in range(Q_WINDOW, n):
        window = arr[i - Q_WINDOW:i]
        cur = arr[i]
        if np.isnan(cur) or np.isnan(window).any():
            continue
        q[i] = np.mean(window <= cur)
    return df.with_columns(pl.Series("q60", q))


def load_etf(fund_file: Path) -> pl.DataFrame:
    return (
        pl.read_parquet(fund_file, columns=["date", "open", "close"])
        .with_columns(pl.col("date").str.to_date("%Y-%m-%d"))
        .sort("date")
    )


def backtest(df: pl.DataFrame, q_high: float, q_low: float) -> dict:
    """状态机回测，T+1 open 成交，返回持仓序列 + 交易明细。"""
    n = df.height
    net = df["net_yi"].to_numpy()
    q60 = df["q60"].to_numpy()
    open_p = df["open"].to_numpy()
    close_p = df["close"].to_numpy()
    dates = df["date"].to_list()

    position = np.zeros(n)
    cur_state = 0  # 0 空仓，1 满仓
    enter_idx = None
    enter_price = None
    trades = []

    for i in range(n - 1):  # 留一日给 T+1 成交
        if np.isnan(q60[i]):
            continue
        sig_buy = (net[i] > 0) and (q60[i] >= q_high)
        sig_sell = (net[i] < 0) and (q60[i] <= q_low)

        if cur_state == 0 and sig_buy:
            enter_idx = i + 1
            enter_price = open_p[enter_idx]
            cur_state = 1
        elif cur_state == 1 and sig_sell:
            exit_idx = i + 1
            exit_price = open_p[exit_idx]
            trades.append({
                "enter_date": dates[enter_idx],
                "exit_date": dates[exit_idx],
                "enter_price": float(enter_price),
                "exit_price": float(exit_price),
                "return": float(exit_price / enter_price - 1.0),
                "holding_days": exit_idx - enter_idx,
                "unrealized": False,
            })
            position[enter_idx:exit_idx] = 1
            cur_state = 0
            enter_idx = None
            enter_price = None

    # 收尾未平仓（用最后一日 close 平盘）
    if cur_state == 1 and enter_idx is not None:
        exit_idx = n - 1
        exit_price = close_p[exit_idx]
        trades.append({
            "enter_date": dates[enter_idx],
            "exit_date": dates[exit_idx],
            "enter_price": float(enter_price),
            "exit_price": float(exit_price),
            "return": float(exit_price / enter_price - 1.0),
            "holding_days": exit_idx - enter_idx,
            "unrealized": True,
        })
        position[enter_idx:exit_idx + 1] = 1

    return {
        "position": position,
        "trades": trades,
        "close": close_p,
        "dates": dates,
    }


def perf_stats(df: pl.DataFrame, bt: dict) -> dict:
    """绩效指标：策略 vs buy&hold。"""
    n = df.height
    close = bt["close"]
    pos = bt["position"]
    dates = bt["dates"]
    d0, d1 = dates[0], dates[-1]
    years = (d1 - d0).days / 365.25

    # 每日 ret 与策略 ret（position=1 时跟随 ETF，position=0 时空仓 0 收益）
    daily_ret = np.diff(close) / close[:-1]
    strat_ret = pos[1:] * daily_ret   # align：pos[1:] 对应 daily_ret[0]
    bh_ret = daily_ret

    strat_nav = np.concatenate([[1.0], np.cumprod(1.0 + strat_ret)])
    bh_nav = np.concatenate([[1.0], np.cumprod(1.0 + bh_ret)])

    def _ann(cum):
        if cum <= -1:
            return -1.0
        return (1.0 + cum) ** (1.0 / years) - 1.0

    def _mdd(nav):
        peak = np.maximum.accumulate(nav)
        return float(np.min(nav / peak - 1.0))

    def _sharpe(r):
        s = np.std(r, ddof=1)
        return float(np.mean(r) / s * np.sqrt(TRADING_DAYS)) if s > 0 else float("nan")

    trades = bt["trades"]
    n_trades = len(trades)
    wins = [t for t in trades if t["return"] > 0]
    win_rate = len(wins) / n_trades if n_trades else 0.0
    avg_hold = np.mean([t["holding_days"] for t in trades]) if trades else 0.0
    avg_ret = np.mean([t["return"] for t in trades]) if trades else 0.0

    # 持仓时间占比
    in_market_ratio = float(pos.mean())

    return {
        "d0": d0, "d1": d1, "years": years, "n_days": n,
        "strat_cum": float(strat_nav[-1] - 1.0),
        "strat_ann": float(_ann(strat_nav[-1] - 1.0)),
        "strat_mdd": _mdd(strat_nav),
        "strat_sharpe": _sharpe(strat_ret),
        "bh_cum": float(bh_nav[-1] - 1.0),
        "bh_ann": float(_ann(bh_nav[-1] - 1.0)),
        "bh_mdd": _mdd(bh_nav),
        "bh_sharpe": _sharpe(bh_ret),
        "n_trades": n_trades,
        "win_rate": float(win_rate),
        "avg_hold_days": float(avg_hold),
        "avg_trade_ret": float(avg_ret),
        "in_market_ratio": in_market_ratio,
        "strat_nav": strat_nav,
        "bh_nav": bh_nav,
    }


def plot_strategy(
    df: pl.DataFrame, bt: dict, stats: dict, output_png: Path,
    q_high: float, q_low: float,
) -> None:
    for f in plt.rcParams.get("font.sans-serif", []):
        if "Noto" in f or "WenQuanYi" in f:
            break
    else:
        plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "WenQuanYi Zen Hei"]
        plt.rcParams["axes.unicode_minus"] = False

    dates = bt["dates"]
    close = bt["close"]
    pos = bt["position"]
    q60 = df["q60"].to_numpy()

    fig, (ax_p, ax_nav, ax_q) = plt.subplots(
        3, 1, figsize=(15, 12), sharex=True,
        gridspec_kw={"height_ratios": [1.2, 1.0, 0.8], "hspace": 0.06},
        constrained_layout=True,
    )

    # ===== 上图：ETF close + 买卖点 =====
    ax_p.plot(dates, close, "-", color="#444", linewidth=1.0, alpha=0.85,
              label="513180 前复权")
    for t in bt["trades"]:
        ax_p.scatter([t["enter_date"]], [t["enter_price"]], marker="^",
                     s=70, color=COLOR_BUY, edgecolors="white", linewidth=0.6,
                     zorder=5)
        ax_p.scatter([t["exit_date"]], [t["exit_price"]], marker="v",
                     s=70, color=COLOR_SELL, edgecolors="white", linewidth=0.6,
                     zorder=5)
        # 连接成交价水平短线，便于核对
        ax_p.plot([t["enter_date"], t["exit_date"]],
                  [t["enter_price"], t["exit_price"]],
                  ":", color="#999", linewidth=0.5, alpha=0.5)
    ax_p.set_ylabel("ETF 价格", fontsize=10)
    ax_p.set_title(
        f"① ETF 价格 + 信号成交点（▲ 买 {COLOR_BUY} / ▼ 卖 {COLOR_SELL}），"
        f"交易 {stats['n_trades']} 次",
        fontsize=11, loc="left",
    )
    ax_p.grid(True, alpha=0.3)
    ax_p.legend(loc="upper right", fontsize=9)

    # ===== 中图：策略净值 vs buy&hold =====
    ax_nav.plot(dates, stats["strat_nav"], "-", color=COLOR_STRAT,
                linewidth=1.3, label=f"策略（年化 {stats['strat_ann']*100:+.1f}%）")
    ax_nav.plot(dates, stats["bh_nav"], "-", color=COLOR_BH,
                linewidth=1.0, alpha=0.8,
                label=f"买入持有（年化 {stats['bh_ann']*100:+.1f}%）")
    # 持仓阴影
    in_market = pos > 0
    starts = []
    for i, v in enumerate(in_market):
        if v and (i == 0 or not in_market[i - 1]):
            starts.append(i)
        elif not v and i > 0 and in_market[i - 1]:
            ax_nav.axvspan(dates[starts[-1]], dates[i],
                           color=COLOR_STRAT, alpha=0.08)
    if in_market[-1] and starts:
        ax_nav.axvspan(dates[starts[-1]], dates[-1],
                       color=COLOR_STRAT, alpha=0.08)
    ax_nav.set_ylabel("净值（起点=1）", fontsize=10)
    ax_nav.set_title(
        f"② 策略净值 vs 买入持有 "
        f"（蓝阴影=持仓，仓位占比 {stats['in_market_ratio']*100:.0f}%）",
        fontsize=11, loc="left",
    )
    ax_nav.grid(True, alpha=0.3)
    ax_nav.legend(loc="upper left", fontsize=9)

    # ===== 下图：q60 时间序列 + 阈值线 =====
    ax_q.axhspan(q_high, 1.0, color=COLOR_BUY, alpha=0.08)
    ax_q.axhspan(0.0, q_low, color=COLOR_SELL, alpha=0.08)
    ax_q.axhline(q_high, color=COLOR_BUY, linestyle="--", linewidth=0.6,
                 alpha=0.6, label=f"买入阈 {q_high}")
    ax_q.axhline(q_low, color=COLOR_SELL, linestyle="--", linewidth=0.6,
                 alpha=0.6, label=f"卖出阈 {q_low}")
    ax_q.plot(dates, q60, "-", color=COLOR_Q, linewidth=0.9, alpha=0.85)
    # 信号触发点（无论是否成交，标出原始触发日）
    net = df["net_yi"].to_numpy()
    buy_trig = np.where((net > 0) & (q60 >= q_high))[0]
    sell_trig = np.where((net < 0) & (q60 <= q_low))[0]
    ax_q.scatter([dates[i] for i in buy_trig], [q60[i] for i in buy_trig],
                 marker="^", s=20, color=COLOR_BUY, alpha=0.7, edgecolors="none")
    ax_q.scatter([dates[i] for i in sell_trig], [q60[i] for i in sell_trig],
                 marker="v", s=20, color=COLOR_SELL, alpha=0.7, edgecolors="none")
    ax_q.set_ylabel("q60（60 日分位）")
    ax_q.set_xlabel("日期")
    ax_q.set_ylim(-0.05, 1.05)
    ax_q.set_title(
        f"③ 当日 net_yi 在过去 60 日的分位 "
        f"（触发：买入 {len(buy_trig)} 次，卖出 {len(sell_trig)} 次）",
        fontsize=11, loc="left",
    )
    ax_q.grid(True, alpha=0.3)
    ax_q.legend(loc="upper right", fontsize=8)

    ax_q.xaxis.set_major_locator(mdates.YearLocator(1))
    ax_q.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    fig.suptitle(
        f"港股通南向资金择时策略：恒生科技 ETF(513180) 回测  "
        f"({stats['d0']} ~ {stats['d1']}, {stats['years']:.1f} 年)",
        fontsize=13, fontweight="bold", x=0.01, ha="left",
    )

    output_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_png, dpi=120, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"Saved to {output_png}")


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--sb-csv", type=Path,
        default=Path("/mnt/dataset/exchange_hkex/southbound_flow.csv"),
    )
    p.add_argument(
        "--fund-file", type=Path,
        default=Path("/mnt/dataset/fund_quote_adjusted/513180.parquet"),
    )
    p.add_argument(
        "--output", type=Path,
        default=Path("/mnt/dataset/southbound_etf_strategy.png"),
    )
    p.add_argument("--q-high", type=float, default=Q_HIGH,
                   help="买入分位阈值（默认 0.9 = 前 10%）")
    p.add_argument("--q-low", type=float, default=Q_LOW,
                   help="卖出分位阈值（默认 0.1 = 末尾 10%）")
    args = p.parse_args()

    sb = load_southbound(args.sb_csv)
    etf = load_etf(args.fund_file)
    df = sb.join(etf, on="date", how="inner").sort("date")
    print(f"样本期: {df['date'].min()} ~ {df['date'].max()}, n = {df.height}")
    print(f"阈值: 买入 q60 ≥ {args.q_high}, 卖出 q60 ≤ {args.q_low}")

    bt = backtest(df, args.q_high, args.q_low)
    stats = perf_stats(df, bt)

    print("\n=== 绩效 ===")
    print(f"  策略：累计 {stats['strat_cum']*100:+.2f}%, "
          f"年化 {stats['strat_ann']*100:+.2f}%, "
          f"最大回撤 {stats['strat_mdd']*100:.2f}%, "
          f"夏普 {stats['strat_sharpe']:.2f}")
    print(f"  BH：  累计 {stats['bh_cum']*100:+.2f}%, "
          f"年化 {stats['bh_ann']*100:+.2f}%, "
          f"最大回撤 {stats['bh_mdd']*100:.2f}%, "
          f"夏普 {stats['bh_sharpe']:.2f}")
    print(f"  交易次数 {stats['n_trades']}, 胜率 {stats['win_rate']*100:.1f}%, "
          f"平均持有 {stats['avg_hold_days']:.0f} 天, "
          f"平均单笔 {stats['avg_trade_ret']*100:+.2f}%")
    print(f"  仓位占比 {stats['in_market_ratio']*100:.1f}%")

    if bt["trades"]:
        print("\n=== 交易明细 ===")
        print(f"{'#':>3}  {'enter':12}  {'exit':12}  "
              f"{'enter_p':>8}  {'exit_p':>8}  {'ret%':>7}  {'days':>5}")
        for i, t in enumerate(bt["trades"]):
            tag = "*" if t["unrealized"] else " "
            print(f"{i+1:>3}{tag} {t['enter_date']}  {t['exit_date']}  "
                  f"{t['enter_price']:>8.4f}  {t['exit_price']:>8.4f}  "
                  f"{t['return']*100:>+7.2f}  {t['holding_days']:>5}")

    plot_strategy(df, bt, stats, args.output, args.q_high, args.q_low)


if __name__ == "__main__":
    main()
