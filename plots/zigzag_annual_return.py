"""ZigZag 15% 枢轴 → 沪深300每年最大做多收益率。

使用 zigzag_pivots 在 HS300 day high/low 上标记阶段高/低点（15% 反转阈值），
提取所有 L→H 上升段（做多机会），并在日历年边界处切分——每段收益归到
该段所在的年份。跨年持仓的收益按日历年切分后分摊到各年。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
from pivot_eval import zigzag_pivots


def load_index(index_dir: Path, code: str) -> pl.DataFrame:
    return (
        pl.read_parquet(
            index_dir / f"{code}.parquet",
            columns=["date", "close", "high", "low"],
        )
        .with_columns(pl.col("date").str.to_date("%Y-%m-%d"))
        .sort("date")
    )


def _segment_leg(
    a_idx: int, b_idx: int, leg_no: int,
    dates: list, closes: list, *, is_open: bool = False,
) -> list[dict]:
    """把一个上升段在日历年边界处切开。

    年尾最后一天强制卖出、年头第一天重新买入，因此相邻年份不共享边界。
    每个年份段：[年初第一天（或买入日）, 年末最后一天（或卖出日）]。
    返回该段所属 year 的收益率（按收盘价）。

    各年段收益 × 跨年跳空 = 总收益（跨年跳空不归入任何一年）。
    """
    segments: list[dict] = []
    leg_total_pct = (closes[b_idx] / closes[a_idx] - 1) * 100
    leg_buy = dates[a_idx]
    leg_sell = dates[b_idx]

    cur_start = a_idx
    cur_year = dates[a_idx].year
    for t in range(a_idx, b_idx + 1):
        y = dates[t].year
        if y != cur_year:
            # cur_year segment: cur_start → t-1（该年最后一个交易日）
            if t - 1 >= cur_start:
                ret = closes[t - 1] / closes[cur_start] - 1
                segments.append(dict(
                    year=cur_year, return_pct=ret * 100, leg_no=leg_no,
                    start_date=dates[cur_start], end_date=dates[t - 1],
                    start_price=closes[cur_start], end_price=closes[t - 1],
                    leg_buy_date=leg_buy, leg_sell_date=leg_sell,
                    leg_total_pct=leg_total_pct,
                    leg_open=is_open,
                ))
            cur_start = t  # 年头第一个交易日重新买入
            cur_year = y
    # 最后一段：cur_start → b_idx
    if b_idx >= cur_start:
        ret = closes[b_idx] / closes[cur_start] - 1
        segments.append(dict(
            year=cur_year, return_pct=ret * 100, leg_no=leg_no,
            start_date=dates[cur_start], end_date=dates[b_idx],
            start_price=closes[cur_start], end_price=closes[b_idx],
            leg_buy_date=leg_buy, leg_sell_date=leg_sell,
            leg_total_pct=leg_total_pct,
            leg_open=is_open,
        ))
    return segments


def compute_year_segments(
    pivots: list[tuple[int, float, str]],
    dates: list,
    closes: list,
    n: int,
) -> list[dict]:
    """提取所有 L→H 上升段 + 最后一个未完结的 L→? 波段，按日历年切分。

    每年最后交易日强制卖出、次年第一交易日重新买入，跨年跳空不归入任何一年。
    """
    segments: list[dict] = []
    leg_no = 0
    for a, b in zip(pivots, pivots[1:]):
        _, _, a_kind = a
        _, _, b_kind = b
        if a_kind != "L" or b_kind != "H":
            continue
        leg_no += 1
        segments.extend(_segment_leg(a[0], b[0], leg_no, dates, closes))

    # 未完结的最后上升段：最后枢轴是 L，至今未反转到 H
    if pivots and pivots[-1][2] == "L":
        a_idx = pivots[-1][0]
        b_idx = n - 1
        if b_idx > a_idx:
            leg_no += 1
            segments.extend(
                _segment_leg(a_idx, b_idx, leg_no, dates, closes, is_open=True))
    return segments


def compute_year_drawdown_segments(
    pivots: list[tuple[int, float, str]],
    dates: list,
    closes: list,
    n: int,
) -> list[dict]:
    """提取所有 H→L 下降段 + 最后一个未完结的 H→? 波段，按日历年切分。

    与上升段对称：年末最后交易日强制「卖出」（结束当年回撤观察）、年初第一交易日
    重新「买入」（重启回撤基点）。跨年跳空不归入任何一年。
    """
    segments: list[dict] = []
    leg_no = 0
    for a, b in zip(pivots, pivots[1:]):
        _, _, a_kind = a
        _, _, b_kind = b
        if a_kind != "H" or b_kind != "L":
            continue
        leg_no += 1
        segments.extend(_segment_leg(a[0], b[0], leg_no, dates, closes))

    # 未完结的最后下降段：最后枢轴是 H，至今未反转到 L
    if pivots and pivots[-1][2] == "H":
        a_idx = pivots[-1][0]
        b_idx = n - 1
        if b_idx > a_idx:
            leg_no += 1
            segments.extend(
                _segment_leg(a_idx, b_idx, leg_no, dates, closes, is_open=True))
    return segments


def yearly_max(segments: list[dict]) -> list[dict]:
    """按年份分组，取每年最大段收益。年份升序。"""
    by_year: dict[int, list[dict]] = {}
    for seg in segments:
        by_year.setdefault(seg["year"], []).append(seg)
    out = []
    for year in sorted(by_year.keys()):
        best = max(by_year[year], key=lambda x: x["return_pct"])
        out.append(dict(
            year=year,
            max_return_pct=round(best["return_pct"], 2),
            seg_start_date=str(best["start_date"]),
            seg_end_date=str(best["end_date"]),
            seg_start_price=round(best["start_price"], 2),
            seg_end_price=round(best["end_price"], 2),
            leg_no=best["leg_no"],
            leg_total_pct=round(best["leg_total_pct"], 2),
            leg_buy_date=str(best["leg_buy_date"]),
            leg_sell_date=str(best["leg_sell_date"]),
            leg_open=best.get("leg_open", False),
            n_segments=len(by_year[year]),
        ))
    return out


def yearly_max_drawdown(segments: list[dict]) -> list[dict]:
    """按年份分组，取每年最大回撤（最负的段收益）。年份升序。"""
    by_year: dict[int, list[dict]] = {}
    for seg in segments:
        by_year.setdefault(seg["year"], []).append(seg)
    out = []
    for year in sorted(by_year.keys()):
        worst = min(by_year[year], key=lambda x: x["return_pct"])
        out.append(dict(
            year=year,
            max_drawdown_pct=round(worst["return_pct"], 2),
            seg_start_date=str(worst["start_date"]),
            seg_end_date=str(worst["end_date"]),
            seg_start_price=round(worst["start_price"], 2),
            seg_end_price=round(worst["end_price"], 2),
            leg_no=worst["leg_no"],
            leg_total_pct=round(worst["leg_total_pct"], 2),
            leg_buy_date=str(worst["leg_buy_date"]),
            leg_sell_date=str(worst["leg_sell_date"]),
            leg_open=worst.get("leg_open", False),
            n_segments=len(by_year[year]),
        ))
    return out


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--index-dir", type=Path,
                   default=Path("/mnt/dataset/index_quote_history"))
    p.add_argument("--code", default="000300")
    p.add_argument("--pct", type=float, default=0.15, help="ZigZag 反转阈值")
    p.add_argument("--output", type=Path, default=None,
                   help="输出 PNG（不指定则只打印表格）")
    args = p.parse_args()

    df = load_index(args.index_dir, args.code)
    dates = df["date"].to_list()
    closes = df["close"].to_list()
    highs = df["high"].to_list()
    lows = df["low"].to_list()

    pivots = zigzag_pivots(highs, lows, args.pct)
    n_h = sum(1 for p in pivots if p[2] == "H")
    n_l = sum(1 for p in pivots if p[2] == "L")
    print(f"\n=== 沪深300 ZigZag（{args.pct:.0%} 阈值）枢轴统计 ===")
    print(f"数据区间: {dates[0]} ~ {dates[-1]}（{len(dates)} 个交易日）")
    print(f"枢轴总数: {len(pivots)}（H={n_h}, L={n_l}）")
    print()

    segments = compute_year_segments(pivots, dates, closes, len(dates))
    yearly = yearly_max(segments)

    print(f"{'年份':>6}  {'最大做多收益':>12}  {'段起日→段止日':>26}  {'段起价→段止价':>22}  {'交易#':>5}  {'交易总收益':>10}  {'年段数':>6}")
    print("-" * 100)
    for row in yearly:
        open_mark = "⚡" if row["leg_open"] else " "
        print(f"{row['year']:>6}  {row['max_return_pct']:>10.2f}%  "
              f"{row['seg_start_date']}→{row['seg_end_date']}  "
              f"{row['seg_start_price']:>8.2f}→{row['seg_end_price']:>8.2f}  "
              f"#{row['leg_no']:>3}{open_mark}   {row['leg_total_pct']:>7.2f}%  "
              f"{row['n_segments']:>6}")

    years_with_data = [r["year"] for r in yearly]
    print(f"\n有效年份: {years_with_data[0]} ~ {years_with_data[-1]}（共 {len(yearly)} 年）")
    print("注: ⚡ = 未完结持仓（最后枢轴为 L，至今未反转）")

    all_max = np.array([r["max_return_pct"] for r in yearly])
    best = max(yearly, key=lambda x: x["max_return_pct"])
    worst = min(yearly, key=lambda x: x["max_return_pct"])
    print(f"\n每年最大做多收益率统计:")
    print(f"  均值: {all_max.mean():.2f}% 中位: {np.median(all_max):.2f}%")
    print(f"  最高: {best['year']}年 {best['max_return_pct']:.2f}%")
    print(f"  最低: {worst['year']}年 {worst['max_return_pct']:.2f}%")

    # 回撤分析（H→L 下降段，对称逻辑）
    dd_segments = compute_year_drawdown_segments(pivots, dates, closes, len(dates))
    yearly_dd = yearly_max_drawdown(dd_segments)

    print(f"\n{'年份':>6}  {'最大回撤':>10}  {'段起日→段止日':>26}  {'段起价→段止价':>22}  {'交易#':>5}  {'交易总收益':>10}  {'年段数':>6}")
    print("-" * 100)
    for row in yearly_dd:
        open_mark = "⚡" if row["leg_open"] else " "
        print(f"{row['year']:>6}  {row['max_drawdown_pct']:>8.2f}%  "
              f"{row['seg_start_date']}→{row['seg_end_date']}  "
              f"{row['seg_start_price']:>8.2f}→{row['seg_end_price']:>8.2f}  "
              f"#{row['leg_no']:>3}{open_mark}   {row['leg_total_pct']:>7.2f}%  "
              f"{row['n_segments']:>6}")

    all_dd = np.array([r["max_drawdown_pct"] for r in yearly_dd])
    worst_dd = min(yearly_dd, key=lambda x: x["max_drawdown_pct"])
    mildest_dd = max(yearly_dd, key=lambda x: x["max_drawdown_pct"])
    print(f"\n每年最大回撤统计:")
    print(f"  均值: {all_dd.mean():.2f}% 中位: {np.median(all_dd):.2f}%")
    print(f"  最深: {worst_dd['year']}年 {worst_dd['max_drawdown_pct']:.2f}%")
    print(f"  最浅: {mildest_dd['year']}年 {mildest_dd['max_drawdown_pct']:.2f}%")

    if args.output:
        plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "WenQuanYi Zen Hei"]
        plt.rcParams["axes.unicode_minus"] = False

        fig, (ax1, ax2, ax3) = plt.subplots(
            3, 1, figsize=(14, 11),
            gridspec_kw={"height_ratios": [1.2, 0.8, 0.8]},
            constrained_layout=True,
        )

        # 上面板：价格 + ZigZag 枢轴 + up-leg 高亮
        ax1.plot(dates, closes, color="#444", lw=0.6, label="沪深300收盘")
        h_idxs = [p[0] for p in pivots if p[2] == "H"]
        l_idxs = [p[0] for p in pivots if p[2] == "L"]
        for i in h_idxs:
            ax1.scatter(dates[i], closes[i], marker="v", color="#d62728",
                        s=40, zorder=5, alpha=0.8)
        for i in l_idxs:
            ax1.scatter(dates[i], closes[i], marker="^", color="#2ca02c",
                        s=40, zorder=5, alpha=0.8)
        # 高亮 up-leg（L→H）+ 未完结 L→?
        for a, b in zip(pivots, pivots[1:]):
            a_idx, _, a_kind = a
            b_idx, _, b_kind = b
            if a_kind == "L" and b_kind == "H":
                ax1.plot(
                    [dates[a_idx], dates[b_idx]],
                    [closes[a_idx], closes[b_idx]],
                    color="#1f77b4", lw=2.5, alpha=0.45, zorder=3,
                )
        # 最后一段未完结的 L→?（虚线）
        if pivots and pivots[-1][2] == "L":
            ax1.plot(
                [dates[pivots[-1][0]], dates[-1]],
                [closes[pivots[-1][0]], closes[-1]],
                color="#1f77b4", lw=2.5, alpha=0.45, zorder=3, ls="--",
            )

        ax1.set_ylabel("收盘价")
        ax1.set_title(f"沪深300 ZigZag 枢轴（{args.pct:.0%}）+ L→H 上升段高亮")
        ax1.grid(True, alpha=0.3)
        ax1.legend(loc="upper left", fontsize=8)

        # 中面板：每年最大做多收益柱形图
        years_disp = [r["year"] for r in yearly]
        returns_disp = [r["max_return_pct"] for r in yearly]
        colors = ["#d62728" if v < 0 else "#2ca02c" for v in returns_disp]
        ax2.bar(years_disp, returns_disp, color=colors, width=0.7)
        ax2.axhline(0, color="#444", lw=0.5)
        ax2.set_ylabel("最大做多收益 (%)")
        ax2.set_title(
            f"每年最大做多收益率（ZigZag {args.pct:.0%}，跨年持仓按日历年切分）")
        ax2.grid(True, alpha=0.3, axis="y")

        # 下面板：每年最大回撤柱形图（红色向下）
        dd_years_disp = [r["year"] for r in yearly_dd]
        dd_disp = [r["max_drawdown_pct"] for r in yearly_dd]
        ax3.bar(dd_years_disp, dd_disp, color="#d62728", width=0.7, alpha=0.85)
        ax3.axhline(0, color="#444", lw=0.5)
        ax3.set_ylabel("最大回撤 (%)")
        ax3.set_xlabel("年份")
        ax3.set_title(
            f"每年最大回撤（H→L 下降段，ZigZag {args.pct:.0%}，跨年同样切分）")
        ax3.grid(True, alpha=0.3, axis="y")

        output = args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output, dpi=200, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        print(f"\n图: {output}")


if __name__ == "__main__":
    main()
