"""多尺度牛熊分段金标准（沪深300）：ZigZag + 熊市豁免的周期要求合并。

流程：
  1. zigzag_pivots(highs, lows, pct) 拿原始枢轴 → 交替的 bear/bull 原始段。
  2. 按三种最小周期要求（大≥120 / 中≥60 / 小≥30 交易日）分别合并。
  3. 合并规则（熊市豁免）：熊市无论多短都保留；只过滤「短牛」——
     当一个 td<min_days 的 bull 夹在两个 bear 之间，且第二腿 bear 创新低
     （nxt.lo < prev.lo，说明中间是死猫跳），三段合一为 bear。
     短熊（夹在两 bull 之间）不触发合并，作为独立熊段保留。
  4. 打印三尺度分段明细 + 汇总，输出分段 CSV 和三联 PNG。

设计动机：固定百分比 ZigZag 会把"死猫跳+第二腿创新低"误切成
bear-bull-bear（如 2015 股灾 +33% 反弹 + 熔断）。bear-exempt 合并
让大尺度把它还原成一段熊，同时中尺度保留反弹作为中级牛市。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
from pivot_eval import zigzag_pivots

SCALES = [("large", 120, "大"), ("medium", 60, "中"), ("small", 30, "小")]


def tag_size(td: int) -> str:
    if td >= 120:
        return "大"
    if td >= 60:
        return "中"
    if td >= 30:
        return "小"
    return "波动"


def build_raw_segments(
    dates: list, highs: list, lows: list, closes: list, n: int, pct: float
) -> list[dict]:
    """相邻枢轴配段：L→H=bull、H→L=bear。含尾段（最后枢轴→最后一日，未确认）。"""
    pivots = zigzag_pivots(highs, lows, pct)
    segs: list[dict] = []
    for k in range(len(pivots) - 1):
        i0, _, t0 = pivots[k]
        i1, _, _ = pivots[k + 1]
        d = "bull" if t0 == "L" else "bear"
        segs.append(_seg(i0, i1, d, dates, highs, lows, closes))
    if pivots:
        i0, _, t0 = pivots[-1]
        seg = _seg(i0, n - 1, "bull" if t0 == "L" else "bear", dates, highs, lows, closes)
        seg["tail"] = True
        segs.append(seg)
    return segs


def _seg(i0, i1, direction, dates, highs, lows, closes) -> dict:
    return dict(
        i0=i0, i1=i1, dir=direction, td=i1 - i0,
        d0=dates[i0], d1=dates[i1],
        hi=max(highs[i0:i1 + 1]), lo=min(lows[i0:i1 + 1]),
        ret=closes[i1] / closes[i0] - 1,
        tail=False,
    )


def merge_segments(
    segs: list[dict], dates, highs, lows, closes, min_days: int
) -> tuple[list[dict], list[dict]]:
    """熊市豁免合并：只吞短牛（bear 确认→死猫跳）。返回 (合并后段, 合并日志)。"""
    segs = [dict(s) for s in segs]
    log = []
    while True:
        merged_any = False
        for j in range(1, len(segs) - 1):
            prev, cur, nxt = segs[j - 1], segs[j], segs[j + 1]
            if cur["dir"] != "bull" or cur["td"] >= min_days:
                continue
            if prev["dir"] == "bear" and nxt["dir"] == "bear" and nxt["lo"] < prev["lo"]:
                merged = _seg(prev["i0"], nxt["i1"], "bear", dates, highs, lows, closes)
                merged["tail"] = nxt.get("tail", False)
                log.append(dict(
                    d0=prev["d0"], bounce=cur["d0"], d1=nxt["d1"],
                    prev_lo=prev["lo"], nxt_lo=nxt["lo"],
                ))
                segs = segs[:j - 1] + [merged] + segs[j + 2:]
                merged_any = True
                break
        if not merged_any:
            break
    return segs, log


def segments_to_df(segs: list[dict]) -> pl.DataFrame:
    rows = []
    for k, s in enumerate(segs, 1):
        rows.append(dict(
            seg=k, dir=s["dir"], size=tag_size(s["td"]), trade_days=s["td"],
            start_date=s["d0"], end_date=s["d1"],
            high=round(s["hi"], 2), low=round(s["lo"], 2),
            return_pct=round(s["ret"] * 100, 2),
            tail=s.get("tail", False),
        ))
    return pl.DataFrame(rows, orient="row")


def print_table(title: str, segs: list[dict], min_days: int) -> None:
    n_bear = sum(1 for s in segs if s["dir"] == "bear")
    n_bull = sum(1 for s in segs if s["dir"] == "bull" and not s.get("tail"))
    tail = segs[-1]["dir"] if segs and segs[-1].get("tail") else None
    tail_s = f" + ⚡尾段({tail})" if tail else ""
    print(f"\n{'=' * 104}")
    print(f"{title}  →  {len(segs)} 段 ({n_bull} 牛 / {n_bear} 熊{tail_s})")
    print("-" * 104)
    print(f"{'#':>2} {'dir':>4} {'size':>4} {'td':>5} {'start':>10} → {'end':>10}   "
          f"{'ret':>9}   note")
    for k, s in enumerate(segs, 1):
        note = "⚡尾段" if s.get("tail") else ""
        if not note and s["dir"] == "bull" and s["td"] < min_days:
            note = f"★ 短牛<{min_days}td"
        print(f"{k:>2} {s['dir']:>4} {tag_size(s['td']):>4} {s['td']:>5} "
              f"{str(s['d0']):>10} → {str(s['d1']):>10}   {s['ret']:>+8.1%}   {note}")


def plot_multiscale(
    dates, highs, lows, closes, raw, out_png: Path, code: str, pct: float
) -> None:
    n = len(dates)
    fig, axes = plt.subplots(len(SCALES), 1, figsize=(16, 4.5 * len(SCALES)), sharex=True)
    d_np = pl.Series(dates).to_numpy()

    for ax, (key, thr, cn) in zip(axes, SCALES):
        segs, _ = merge_segments(raw, dates, highs, lows, closes, thr)
        for s in segs:
            color = "#2ca02c" if s["dir"] == "bull" else "#d62728"
            ax.axvspan(s["d0"], s["d1"], color=color, alpha=0.18, lw=0)
        ax.plot(d_np, pl.Series(closes).to_numpy(), color="black", linewidth=0.7)
        for k, s in enumerate(segs, 1):
            ax.axvline(s["d0"], color="gray", linewidth=0.5, linestyle="--", alpha=0.6)
            mid_i = (s["i0"] + s["i1"]) // 2
            tag_s = "尾*" if s.get("tail") else tag_size(s["td"])
            ax.annotate(
                f"#{k}\n{s['dir']}\n{tag_s} {s['td']}td\n{s['ret']:+.0%}",
                xy=(dates[mid_i], closes[mid_i]), fontsize=7, ha="center", va="center",
                bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="gray", alpha=0.75),
            )
        ax.axvline(segs[-1]["d1"], color="gray", linewidth=0.5, linestyle="--", alpha=0.6)
        ax.set_yscale("log")
        ax.set_ylabel("close (log)")
        n_bear = sum(1 for s in segs if s["dir"] == "bear")
        n_bull = sum(1 for s in segs if s["dir"] == "bull" and not s.get("tail"))
        ax.set_title(
            f"{cn}尺度 ≥{thr}td  →  {len(segs)} 段 ({n_bull} 牛 / {n_bear} 熊"
            f"{'+ *尾段' if segs[-1].get('tail') else ''})", fontsize=11)
        ax.grid(True, which="both", alpha=0.25)

    axes[-1].xaxis.set_major_locator(mdates.YearLocator(2))
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    fig.suptitle(
        f"{code} ZigZag {pct:.0%} + 熊市豁免合并 多尺度牛熊分段"
        f"（绿=bull 红=bear, *=未确认尾段）", fontsize=13, y=0.995)
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=120, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--index-dir", type=Path,
                   default=Path("/mnt/dataset/index_quote_history"))
    p.add_argument("--code", default="000300")
    p.add_argument("--pct", type=float, default=0.25, help="ZigZag 反转阈值")
    p.add_argument("--output-dir", type=Path,
                   default=Path("/mnt/dataset/csi300_regime_segments"),
                   help="分段 CSV 输出目录")
    p.add_argument("--output", type=Path, default=None,
                   help="三联 PNG 路径（默认 output-dir/multiscale_segments_{code}.png）")
    args = p.parse_args()

    df = (
        pl.read_parquet(args.index_dir / f"{args.code}.parquet",
                        columns=["date", "high", "low", "close"])
        .with_columns(pl.col("date").str.to_date("%Y-%m-%d"))
        .sort("date")
    )
    n = df.height
    dates = df["date"].to_list()
    highs = df["high"].to_list()
    lows = df["low"].to_list()
    closes = df["close"].to_list()

    raw = build_raw_segments(dates, highs, lows, closes, n, args.pct)
    print(f"=== {args.code} 多尺度牛熊分段（ZigZag {args.pct:.0%} + 熊市豁免合并）===")
    print(f"数据区间: {dates[0]} ~ {dates[-1]}（{n} 交易日）")
    print(f"原始枢轴段: {len(raw)}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    for key, thr, cn in SCALES:
        segs, log = merge_segments(raw, dates, highs, lows, closes, thr)
        print_table(f"{cn}尺度（≥{thr}td）", segs, thr)
        if log:
            print(f"  合并 {len(log)} 次短牛（死猫跳）:")
            for m in log:
                print(f"    {m['d0']}~{m['d1']} 合并为 bear "
                      f"(反弹 {m['bounce']}, 第二腿低 {m['nxt_lo']:.0f} "
                      f"< 第一腿低 {m['prev_lo']:.0f})")
        segments_to_df(segs).write_csv(args.output_dir / f"{key}_segments.csv")

    out_png = args.output or (args.output_dir / f"multiscale_segments_{args.code}.png")
    plot_multiscale(dates, highs, lows, closes, raw, out_png, args.code, args.pct)
    print(f"\n分段 CSV: {args.output_dir}/{{large,medium,small}}_segments.csv")
    print(f"三联图:   {out_png}")


if __name__ == "__main__":
    main()
