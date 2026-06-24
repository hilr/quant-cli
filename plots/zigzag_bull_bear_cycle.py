"""ZigZag 枢轴 → 沪深300 牛熊周期。

使用 zigzag_pivots 在 HS300 day high/low 上标记阶段高/低点（默认 20% 反转阈值），
相邻枢轴配成一段：L→H 为牛市（上涨段）、H→L 为熊市（下跌段）。
输出每段的起止日期/价格/涨跌幅/历时，并汇总牛熊各自的段数、平均涨跌、平均时长。
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


def build_legs(
    pivots: list[tuple[int, float, str]],
    dates: list,
    closes: list,
    n: int,
) -> list[dict]:
    """相邻枢轴配段：L→H=牛、H→L=熊。含最后一段未完结（最后枢轴→最后一日）。"""
    legs: list[dict] = []
    for a, b in zip(pivots, pivots[1:]):
        a_idx, a_price, a_kind = a
        b_idx, b_price, b_kind = b
        kind = "bull" if (a_kind == "L" and b_kind == "H") else "bear"
        legs.append(_leg_row(a_idx, b_idx, a_price, b_price, kind, dates, closes))
    # 最后一段未完结：最后枢轴 → 最后一日（实时不可知是否反转）
    if pivots:
        a_idx, a_price, a_kind = pivots[-1]
        b_idx = n - 1
        if b_idx > a_idx:
            kind = "bull" if a_kind == "L" else "bear"
            row = _leg_row(a_idx, b_idx, a_price, closes[b_idx], kind, dates, closes)
            row["open"] = True
            legs.append(row)
    return legs


def _leg_row(a_idx, b_idx, a_price, b_price, kind, dates, closes) -> dict:
    ret = (b_price / a_price - 1) * 100
    cal_days = (dates[b_idx] - dates[a_idx]).days
    return dict(
        kind=kind, start_date=dates[a_idx], end_date=dates[b_idx],
        start_price=a_price, end_price=b_price, return_pct=ret,
        cal_days=cal_days, years=round(cal_days / 365.25, 2),
        trade_days=b_idx - a_idx, open=False,
    )


def summarize(legs: list[dict], kind: str) -> dict:
    sub = [l for l in legs if l["kind"] == kind and not l["open"]]
    if not sub:
        return dict(kind=kind, n=0)
    rets = np.array([l["return_pct"] for l in sub])
    days = np.array([l["cal_days"] for l in sub])
    yrs = np.array([l["years"] for l in sub])
    return dict(
        kind=kind, n=len(sub),
        ret_mean=round(float(rets.mean()), 2),
        ret_median=round(float(np.median(rets)), 2),
        days_mean=round(float(days.mean())), days_median=round(float(np.median(days))),
        years_mean=round(float(yrs.mean()), 2),
        longest=max(sub, key=lambda x: x["cal_days"]),
    )


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--index-dir", type=Path,
                   default=Path("/mnt/dataset/index_quote_history"))
    p.add_argument("--code", default="000300")
    p.add_argument("--pct", type=float, default=0.30, help="ZigZag 反转阈值")
    p.add_argument("--output", type=Path, default=None,
                   help="输出 PNG（不指定则只打印表格）")
    args = p.parse_args()

    df = load_index(args.index_dir, args.code)
    dates = df["date"].to_list()
    closes = df["close"].to_list()
    highs = df["high"].to_list()
    lows = df["low"].to_list()

    pivots = zigzag_pivots(highs, lows, args.pct)
    legs = build_legs(pivots, dates, closes, len(dates))
    n_bull = sum(1 for l in legs if l["kind"] == "bull" and not l["open"])
    n_bear = sum(1 for l in legs if l["kind"] == "bear" and not l["open"])

    print(f"\n=== {args.code} ZigZag（{args.pct:.0%}）牛熊周期 ===")
    print(f"数据区间: {dates[0]} ~ {dates[-1]}（{len(dates)} 个交易日）")
    print(f"枢轴: {len(pivots)}（牛市段 {n_bull}，熊市段 {n_bear}）\n")

    print(f"{'#':>3}  {'类型':>4}  {'起日→止日':>26}  {'起价→止价':>22}  "
          f"{'涨跌%':>9}  {'日历天':>6}  {'年':>5}  {'交易日':>6}")
    print("-" * 100)
    for i, l in enumerate(legs, 1):
        mark = "⚡" if l["open"] else " "
        kind = "牛" if l["kind"] == "bull" else "熊"
        print(f"{i:>3}{mark} {kind:>4}  {l['start_date']}→{l['end_date']}  "
              f"{l['start_price']:>8.2f}→{l['end_price']:>8.2f}  "
              f"{l['return_pct']:>+8.2f}%  {l['cal_days']:>6}  {l['years']:>5.2f}  {l['trade_days']:>6}")
    print("\n⚡ = 未完结（最后枢轴→至今，未确认反转）")

    bull = summarize(legs, "bull")
    bear = summarize(legs, "bear")
    print(f"\n--- 牛市汇总 ---")
    print(f"  {bull['n']} 段 | 涨幅 均 {bull['ret_mean']:+.2f}% 中位 {bull['ret_median']:+.2f}% | "
          f"历时 均 {bull['days_mean']}天({bull['years_mean']}年) 中位 {bull['days_median']}天")
    print(f"  最长: {bull['longest']['start_date']}→{bull['longest']['end_date']} "
          f"{bull['longest']['cal_days']}天 {bull['longest']['return_pct']:+.2f}%")
    print(f"--- 熊市汇总 ---")
    print(f"  {bear['n']} 段 | 跌幅 均 {bear['ret_mean']:+.2f}% 中位 {bear['ret_median']:+.2f}% | "
          f"历时 均 {bear['days_mean']}天({bear['years_mean']}年) 中位 {bear['days_median']}天")
    print(f"  最长: {bear['longest']['start_date']}→{bear['longest']['end_date']} "
          f"{bear['longest']['cal_days']}天 {bear['longest']['return_pct']:+.2f}%")

    if args.output:
        plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "WenQuanYi Zen Hei"]
        plt.rcParams["axes.unicode_minus"] = False

        fig, (ax1, ax2) = plt.subplots(
            2, 1, figsize=(15, 9), gridspec_kw={"height_ratios": [2, 1]},
            constrained_layout=True)

        # 上面板：价格 + 枢轴 + 牛熊区间阴影
        ax1.plot(dates, closes, color="#444", lw=0.6, label=f"{args.code}收盘")
        for l in legs:
            color = "#2ca02c22" if l["kind"] == "bull" else "#d6272822"
            ax1.axvspan(l["start_date"], l["end_date"], color=color, lw=0)
        # zigzag 折线
        pv_idx = [p[0] for p in pivots]
        ax1.plot([dates[i] for i in pv_idx], [closes[i] for i in pv_idx],
                 color="#1f77b4", lw=1.2, alpha=0.8, zorder=3, label="ZigZag")
        for p in pivots:
            mk, col = ("v", "#d62728") if p[2] == "H" else ("^", "#2ca02c")
            ax1.scatter(dates[p[0]], closes[p[0]], marker=mk, color=col, s=45, zorder=5)
        ax1.set_ylabel("收盘价")
        ax1.set_title(f"{args.code} ZigZag（{args.pct:.0%}）牛熊周期（绿=牛 熊=红）")
        ax1.grid(True, alpha=0.3)
        ax1.legend(loc="upper left", fontsize=8)

        # 下面板：每段历时（横条），牛绿熊红
        closed = [l for l in legs if not l["open"]]
        ypos = list(range(len(closed)))
        colors = ["#2ca02c" if l["kind"] == "bull" else "#d62728" for l in closed]
        labels = [f"{l['start_date'].year}" for l in closed]
        ax2.barh(ypos, [l["years"] for l in closed], color=colors, alpha=0.85)
        for y, l in zip(ypos, closed):
            ax2.text(l["years"] + 0.03, y, f"{l['return_pct']:+.0f}%",
                     va="center", fontsize=7)
        ax2.set_yticks(ypos)
        ax2.set_yticklabels(labels, fontsize=7)
        ax2.invert_yaxis()
        ax2.set_xlabel("历时（年）")
        ax2.set_title("各周期历时与涨跌幅（绿=牛 熊=红）")
        ax2.grid(True, alpha=0.3, axis="x")

        args.output.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(args.output, dpi=200, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        print(f"\n图: {args.output}")


if __name__ == "__main__":
    main()
