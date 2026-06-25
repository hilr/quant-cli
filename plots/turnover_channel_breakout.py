"""沪市成交额通道（log Bollinger）+ 上证综指 + 通道重入信号。

通道定义：对 log(turnover) 做 Bollinger——
  中轨 = MA(window)
  上下轨 = MA ± k·σ（在 log 空间）
等价于成交额的乘法通道（exp 还原后）。log 空间算 Bollinger 是因为成交额跨 50 倍，
线性 Bollinger 会被近年大值主导，早期带子看不见；log 空间在 log y 轴上是平行带。

「通道外」= 当日 turnover > 上轨（放量外溢）或 < 下轨（缩量外溢）。
  下图所有「外」的日子都画小标记，可视化「外溢段」。

「重入信号」（=买卖信号）：
  sell = 成交额先突破上轨（外溢），再回落到上轨以内（重入通道从上方）
  buy  = 成交额先跌破下轨（外溢），再回升到下轨以内（重入通道从下方）
重入日自然唯一（每段外溢只产生一次重入），无需冷却。

上图：价格 + ZigZag 阶段高/低点（短竖线 + 偏移 ◆）+ 重入信号跨面板竖线。
下图：成交额 + 通道 + 所有外溢日小标记 + 重入信号 ★（竖线连接上图）。

评估：用 ZigZag 在价格上找「正确答案」（阶段高/低点），对每个重入信号找最近的 pivot，
报告「天数差距」（+ = pivot 在信号之后，− = 在之前）和「价格差距」
（pivot_close / signal_close − 1）。
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
from pivot_eval import find_nearest_pivot, zigzag_pivots

INDEX_CODE = "000300"


def load_index(index_dir: Path, code: str) -> pl.DataFrame:
    return (
        pl.read_parquet(
            index_dir / f"{code}.parquet",
            columns=["date", "close", "turnover", "high", "low"],
        )
        .with_columns(pl.col("date").str.to_date("%Y-%m-%d"))
        .sort("date")
    )


def build_channel(df: pl.DataFrame, window: int, k: float) -> pl.DataFrame:
    """log 空间 Bollinger 通道（乘法通道）。rolling_std 用 ddof=1（Polars 默认）。

    成交额跨 50 倍，线性 Bollinger 会被近年大值主导；log 空间算 Bollinger，
    exp 还原后是乘法通道，在 log y 轴上是平行带。
    """
    log_to_expr = pl.col("turnover").log()
    return (
        df.with_columns(
            log_to_expr.rolling_mean(window_size=window, min_samples=window).alias("_log_ma"),
            log_to_expr.rolling_std(window_size=window, min_samples=window).alias("_log_std"),
        )
        .with_columns(
            pl.col("_log_ma").exp().alias("channel_mid"),
            (pl.col("_log_ma") + k * pl.col("_log_std")).exp().alias("channel_upper"),
            (pl.col("_log_ma") - k * pl.col("_log_std")).exp().alias("channel_lower"),
        )
        .with_columns(
            (pl.col("turnover") > pl.col("channel_upper")).alias("outside_up"),
            (pl.col("turnover") < pl.col("channel_lower")).alias("outside_dn"),
        )
        .drop(["_log_ma", "_log_std"])
    )


def find_reentries(flags_outside: list[bool]) -> list[int]:
    """从「外溢」标志列表找重入日：昨日在外、今日回到通道内。
    每段外溢期生成一个重入信号（结束日）。"""
    events: list[int] = []
    for i in range(1, len(flags_outside)):
        if flags_outside[i - 1] and not flags_outside[i]:
            events.append(i)
    return events


def evaluate_vs_pivots(
    signal_idxs: list[int], pivot_idxs: list[int],
    dates: list, closes: list, turnovers: list,
    signal_kind: str, pivot_kind: str, max_look: int,
) -> None:
    """对每个信号找最近 pivot，报告天数差距 + 价格差距。"""
    print(f"\n=== {signal_kind} → 最近价格 {pivot_kind}（搜索半径 {max_look} 交易日）===")
    if not signal_idxs:
        print("  无信号")
        return
    sorted_pivots = sorted(pivot_idxs)
    print(f"  {'信号日':<12}{'成交额(亿)':>12}{'信号价':>10}"
          f"{'pivot日':>13}{'pivot价':>10}{'天数差':>8}{'价格差':>10}")
    day_gaps: list[int] = []
    price_gaps: list[float] = []
    no_match = 0
    for bi in signal_idxs:
        match = find_nearest_pivot(bi, sorted_pivots, max_look)
        if match is None:
            print(f"  {str(dates[bi]):<12}{turnovers[bi]/1e8:>12.0f}{closes[bi]:>10.0f}"
                  f"{'—(无pivot)':>13}{'—':>10}{'—':>8}{'—':>10}")
            no_match += 1
            continue
        pi, gap = match
        price_gap = closes[pi] / closes[bi] - 1
        day_gaps.append(gap)
        price_gaps.append(price_gap)
        print(f"  {str(dates[bi]):<12}{turnovers[bi]/1e8:>12.0f}{closes[bi]:>10.0f}"
              f"{str(dates[pi]):>13}{closes[pi]:>10.0f}{gap:>+8d}{price_gap*100:>+9.2f}%")

    matched = len(day_gaps)
    total = len(signal_idxs)
    print(f"\n  汇总（{matched}/{total} 个信号在半径内有 pivot，{no_match} 个无）:")
    if not day_gaps:
        return
    day_arr = np.array(day_gaps)
    price_arr = np.array(price_gaps)
    print(f"  天数差距: 中位 {int(np.median(day_arr)):+d}, 均值 {day_arr.mean():+.1f}, "
          f"范围 [{day_arr.min():+d}, {day_arr.max():+d}]")
    print(f"  价格差距: 中位 {np.median(price_arr)*100:+.2f}%, 均值 {price_arr.mean()*100:+.2f}%, "
          f"范围 [{price_arr.min()*100:+.2f}%, {price_arr.max()*100:+.2f}%]")
    lead = sum(1 for g in day_gaps if g > 0)
    lag = sum(1 for g in day_gaps if g < 0)
    same = sum(1 for g in day_gaps if g == 0)
    within_5d = sum(1 for g in day_gaps if abs(g) <= 5)
    within_15d = sum(1 for g in day_gaps if abs(g) <= 15)
    within_30d = sum(1 for g in day_gaps if abs(g) <= 30)
    print(f"  天数方向: pivot 在未来(领先) {lead}, 在过去(滞后) {lag}, 同日 {same}")
    print(f"  时间吻合度: ≤5日 {within_5d}/{matched} ({within_5d/matched:.0%}), "
          f"≤15日 {within_15d}/{matched} ({within_15d/matched:.0%}), "
          f"≤30日 {within_30d}/{matched} ({within_30d/matched:.0%})")
    price_within_2pct = sum(1 for g in price_gaps if abs(g) <= 0.02)
    price_within_5pct = sum(1 for g in price_gaps if abs(g) <= 0.05)
    print(f"  价格吻合度: ≤2% {price_within_2pct}/{matched} ({price_within_2pct/matched:.0%}), "
          f"≤5% {price_within_5pct}/{matched} ({price_within_5pct/matched:.0%})")


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--index-dir", type=Path,
                   default=Path("/mnt/dataset/index_quote_history"))
    p.add_argument("--code", default=INDEX_CODE)
    p.add_argument("--start-date", type=str, default="2010-01-01")
    p.add_argument("--window", type=int, default=60, help="通道 MA 窗口")
    p.add_argument("--k", type=float, default=2.0, help="通道宽度（log 空间 σ 倍数）")
    p.add_argument("--zigzag", type=float, default=0.08,
                   help="价格 ZigZag 反转阈值（找「正确答案」阶段高/低点，如 0.08=8%%）")
    p.add_argument("--max-look", type=int, default=120,
                   help="评估时找最近 pivot 的最大搜索半径（交易日）")
    p.add_argument("--output", type=Path, default=None)
    args = p.parse_args()

    start = date.fromisoformat(args.start_date)
    df = load_index(args.index_dir, args.code)
    df = build_channel(df, args.window, args.k)
    df = df.filter(pl.col("date") >= start)
    n = df.height
    if n == 0:
        raise SystemExit(f"--start-date {start} 后无数据")

    dates = df["date"].to_list()
    turnovers = df["turnover"].to_list()
    closes = df["close"].to_list()
    upper = df["channel_upper"].to_list()
    lower = df["channel_lower"].to_list()
    mid = df["channel_mid"].to_list()
    highs = df["high"].to_list()
    lows = df["low"].to_list()
    flags_up = [bool(x) if x is not None else False for x in df["outside_up"].to_list()]
    flags_dn = [bool(x) if x is not None else False for x in df["outside_dn"].to_list()]

    # 所有外溢日（无冷却，全画出来）
    days_out_up = [i for i, f in enumerate(flags_up) if f]
    days_out_dn = [i for i, f in enumerate(flags_dn) if f]
    # 重入信号
    sell_signals = find_reentries(flags_up)   # 从上轨外跌回通道内
    buy_signals = find_reentries(flags_dn)    # 从下轨外升回通道内

    zz_pivots = zigzag_pivots(highs, lows, args.zigzag)
    zz_high_idxs = [p[0] for p in zz_pivots if p[2] == "H"]
    zz_low_idxs = [p[0] for p in zz_pivots if p[2] == "L"]
    print(f"区间: {dates[0]} ~ {dates[-1]}（{n} 个交易日）")
    print(f"通道 MA{args.window}±{args.k}σ（log）：外溢上轨 {sum(flags_up)} 日 / 外溢下轨 {sum(flags_dn)} 日")
    print(f"重入信号：sell {len(sell_signals)} 次（从上轨外跌回），buy {len(buy_signals)} 次（从下轨外升回）")
    print(f"价格 ZigZag（阈值 {args.zigzag:.0%}）：{len(zz_high_idxs)} H / {len(zz_low_idxs)} L")

    plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "WenQuanYi Zen Hei"]
    plt.rcParams["axes.unicode_minus"] = False

    fig, (ax_top, ax_bot) = plt.subplots(
        2, 1, figsize=(15, 9), sharex=True,
        gridspec_kw={"height_ratios": [1.2, 1.0]},
        constrained_layout=True,
    )

    nan = float("nan")
    upper_v = [v if v is not None else nan for v in upper]
    lower_v = [v if v is not None else nan for v in lower]
    mid_v = [v if v is not None else nan for v in mid]

    # === 上面板：价格 + ZigZag 枢轴（短竖线 + 偏移 ◆）+ 重入信号跨面板竖线 ===
    ax_top.plot(dates, closes, color="#444", lw=0.6, label="沪深300收盘")
    if zz_pivots:
        pv_h_idx = [p[0] for p in zz_pivots if p[2] == "H"]
        pv_l_idx = [p[0] for p in zz_pivots if p[2] == "L"]
        for i in pv_h_idx:
            ax_top.vlines(dates[i], closes[i], closes[i] * 1.015,
                          color="#d62728", lw=0.9, alpha=0.75, zorder=4)
        if pv_h_idx:
            ax_top.scatter([dates[i] for i in pv_h_idx],
                           [closes[i] * 1.015 for i in pv_h_idx],
                           marker="D", color="black", s=42, zorder=6,
                           edgecolors="#d62728", linewidths=0.9,
                           label=f"阶段高点 H（{len(pv_h_idx)}）")
        for i in pv_l_idx:
            ax_top.vlines(dates[i], closes[i] * 0.985, closes[i],
                          color="#2ca02c", lw=0.9, alpha=0.75, zorder=4)
        if pv_l_idx:
            ax_top.scatter([dates[i] for i in pv_l_idx],
                           [closes[i] * 0.985 for i in pv_l_idx],
                           marker="D", color="black", s=30, zorder=6,
                           edgecolors="#2ca02c", linewidths=0.9,
                           label=f"阶段低点 L（{len(pv_l_idx)}）")
    # 重入信号竖线（贯穿上图，虚线）
    for i in sell_signals:
        ax_top.axvline(dates[i], color="#d62728", lw=0.6, alpha=0.6,
                       linestyle="--", zorder=2)
    for i in buy_signals:
        ax_top.axvline(dates[i], color="#2ca02c", lw=0.6, alpha=0.6,
                       linestyle="--", zorder=2)
    ax_top.set_ylabel("沪深300收盘", fontsize=10)
    ax_top.grid(True, alpha=0.3)
    ax_top.legend(loc="upper left", fontsize=8, ncol=3)
    ax_top.set_title(
        f"沪深300价格 + ZigZag 枢轴（{args.zigzag:.0%}）+ 重入信号竖线\n"
        f"{dates[0]} ~ {dates[-1]}（{n} 个交易日）；"
        f"sell = 成交额从上轨外跌回通道内（{len(sell_signals)}），"
        f"buy = 从下轨外升回通道内（{len(buy_signals)}）",
        fontsize=11, fontweight="bold", loc="left",
    )

    # === 下面板：成交额 + 通道 + 所有外溢日小标记 + 重入信号 ★（竖线接续上图）===
    ax_bot.fill_between(dates, lower_v, upper_v, color="#1f77b4", alpha=0.13,
                        label=f"通道 MA{args.window}±{args.k}σ（log）")
    ax_bot.plot(dates, upper_v, "-", color="#1f77b4", lw=0.5, alpha=0.55)
    ax_bot.plot(dates, lower_v, "-", color="#1f77b4", lw=0.5, alpha=0.55)
    ax_bot.plot(dates, mid_v, "--", color="#1f77b4", lw=0.4, alpha=0.5)
    ax_bot.plot(dates, turnovers, color="#1f77b4", lw=0.7, label="沪深300成交额")
    ax_bot.set_yscale("log")
    ax_bot.set_ylabel("成交额（元，log）", color="#1f77b4", fontsize=10)
    ax_bot.tick_params(axis="y", labelcolor="#1f77b4")
    # 所有外溢日小标记（无冷却）
    if days_out_up:
        ax_bot.scatter([dates[i] for i in days_out_up], [turnovers[i] for i in days_out_up],
                       marker=".", color="#d62728", s=22, zorder=4, alpha=0.55,
                       label=f"外溢上轨（{len(days_out_up)} 日）")
    if days_out_dn:
        ax_bot.scatter([dates[i] for i in days_out_dn], [turnovers[i] for i in days_out_dn],
                       marker=".", color="#2ca02c", s=22, zorder=4, alpha=0.55,
                       label=f"外溢下轨（{len(days_out_dn)} 日）")
    # 重入信号竖线（虚线，贯穿下图）
    for i in sell_signals:
        ax_bot.axvline(dates[i], color="#d62728", lw=0.6, alpha=0.6,
                       linestyle="--", zorder=2)
    for i in buy_signals:
        ax_bot.axvline(dates[i], color="#2ca02c", lw=0.6, alpha=0.6,
                       linestyle="--", zorder=2)

    span = dates[-1] - dates[0]
    ax_bot.set_xlim(dates[0], dates[-1] + span * 0.02)
    ax_bot.text(0.99, 0.03, f"最新 {dates[-1]}", transform=ax_bot.transAxes,
                ha="right", va="bottom", fontsize=10, color="#222", fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#bbb", alpha=0.85))
    ax_bot.set_title(
        f"沪深300成交额 + 通道 MA{args.window}±{args.k}σ（log 空间）+ 所有外溢日 + 重入信号（虚线）",
        fontsize=11, fontweight="bold", loc="left",
    )
    ax_bot.grid(True, alpha=0.3)
    ax_bot.legend(loc="upper left", fontsize=8, ncol=3)
    ax_bot.xaxis.set_major_locator(mdates.YearLocator())
    ax_bot.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    output = args.output or Path(f"/mnt/dataset/turnover_channel_{args.code}.png")
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"图: {output}")

    evaluate_vs_pivots(sell_signals, zz_high_idxs, dates, closes, turnovers,
                       "sell信号", "阶段高点(H)", args.max_look)
    evaluate_vs_pivots(buy_signals, zz_low_idxs, dates, closes, turnovers,
                       "buy信号", "阶段低点(L)", args.max_look)


if __name__ == "__main__":
    main()
