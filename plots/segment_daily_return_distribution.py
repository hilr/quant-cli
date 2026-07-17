"""沪深300 大级别牛熊分段内日收益率分布（ZigZag 大尺度分段）。

读取 `csi300_regime_segments/large_segments.csv` 中的大级别分段，
对每一段在区间内统计沪深300 日收益率 `(close - prev_close) / prev_close`
的分布，输出 4×3 直方图网格。

适合回答：「牛市区间里的每一天长什么样？熊市里日跌幅度有多大、
波动率比牛市高多少？大级别牛熊的日收益分布形态有何差异？」

口径与提醒：
- **日收益率**：相邻交易日 close 之比 - 1，前复权 close。
- **分段区间**：相邻段共用枢轴日，采用半开 `[start, end)` 避免重复计数
  （最后一段尾段用闭区间，因为后面没有下一段抢这个端点）。
- **桶宽**：0.5%（daily return 范围紧，用更细的桶）。
- **颜色**：中国市场习惯——红涨绿跌；牛市面板边框偏红、熊市偏绿做视觉分组。
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import polars as pl

NEG_COLOR = "#2ca02c"   # 绿：负收益（中国市场绿=跌）
POS_COLOR = "#d62728"   # 红：正收益（中国市场红=涨）
ZERO_COLOR = "#7f7f7f"  # 灰：恰好 0 的桶
MEAN_COLOR = "#ff7f0e"  # 橙：均值线
MEDIAN_COLOR = "#1f77b4"  # 蓝：中位数线
BULL_EDGE = "#d62728"
BEAR_EDGE = "#2ca02c"

DIR_CN = {"bull": "牛", "bear": "熊"}


def load_segments(segments_csv: Path) -> pl.DataFrame:
    return pl.read_csv(segments_csv).with_columns(
        pl.col("start_date").str.to_date("%Y-%m-%d"),
        pl.col("end_date").str.to_date("%Y-%m-%d"),
    )


def load_daily_returns(quote_path: Path) -> pl.DataFrame:
    return (
        pl.read_parquet(quote_path, columns=["date", "close"])
        .with_columns(pl.col("date").str.to_date("%Y-%m-%d"))
        .sort("date")
        .with_columns(
            (pl.col("close") / pl.col("close").shift(1) - 1).alias("ret")
        )
    )


def segment_returns(
    quotes: pl.DataFrame, start: date, end: date, is_last: bool
) -> np.ndarray:
    """[start, end) 普通段；最后一段用 [start, end]。"""
    upper = pl.col("date") <= end if is_last else pl.col("date") < end
    sub = quotes.filter((pl.col("date") >= start) & upper)
    return sub.drop_nulls("ret")["ret"].to_numpy()


def bin_edges(returns: np.ndarray, bucket_width: float) -> np.ndarray:
    lo = np.floor(returns.min() / bucket_width) * bucket_width
    hi = np.ceil(returns.max() / bucket_width) * bucket_width
    n = int(round((hi - lo) / bucket_width)) + 1
    return np.linspace(lo, hi, n)


def bar_colors(edges: np.ndarray) -> list[str]:
    out = []
    for i in range(len(edges) - 1):
        left = edges[i]
        if left < 0:
            out.append(NEG_COLOR)
        elif left > 0:
            out.append(POS_COLOR)
        else:
            out.append(ZERO_COLOR)
    return out


def stats(r: np.ndarray) -> dict:
    return {
        "n": len(r),
        "mean": float(np.mean(r)),
        "median": float(np.median(r)),
        "std": float(np.std(r, ddof=1)),
        "min": float(np.min(r)),
        "max": float(np.max(r)),
        "p1": float(np.percentile(r, 1)),
        "p5": float(np.percentile(r, 5)),
        "p95": float(np.percentile(r, 95)),
        "p99": float(np.percentile(r, 99)),
        "pct_pos": float(np.mean(r > 0) * 100),
        "pct_neg": float(np.mean(r < 0) * 100),
        "pct_flat": float(np.mean(r == 0) * 100),
    }


def plot_grid(
    panels: list[dict],
    bucket_width: float,
    code: str,
    output_png: Path,
) -> None:
    plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "WenQuanYi Zen Hei"]
    plt.rcParams["axes.unicode_minus"] = False

    n = len(panels)
    ncols = 3
    nrows = int(np.ceil(n / ncols))
    fig, axes = plt.subplots(
        nrows, ncols, figsize=(6.2 * ncols, 3.6 * nrows), sharey=False
    )
    axes = np.atleast_1d(axes).ravel()

    for ax, p in zip(axes, panels):
        r = p["ret"]
        s = stats(r)
        edges = bin_edges(r, bucket_width)
        counts, _ = np.histogram(r, bins=edges)
        total = counts.sum()
        pct = counts / total * 100 if total else counts
        centers = (edges[:-1] + edges[1:]) / 2
        colors = bar_colors(edges)

        ax.bar(
            centers * 100, pct,
            width=bucket_width * 100 * 0.9,
            color=colors, edgecolor="white", linewidth=0.3,
        )
        ax.axvline(0, color="black", lw=0.7)
        ax.axvline(s["mean"] * 100, color=MEAN_COLOR, lw=1.0, ls="--")
        ax.axvline(s["median"] * 100, color=MEDIAN_COLOR, lw=1.0, ls=":")

        edge_color = BULL_EDGE if p["dir"] == "bull" else BEAR_EDGE
        for spine in ax.spines.values():
            spine.set_edgecolor(edge_color)
            spine.set_linewidth(1.5)

        tail_tag = "(未完)" if p["tail"] else ""
        sep = "  " if tail_tag else "  "
        title = (
            f"#{p['seg']} {DIR_CN[p['dir']]}{tail_tag}{sep}"
            f"{p['start'].strftime('%Y-%m-%d')}~{p['end'].strftime('%Y-%m-%d')}\n"
            f"{p['trade_days']}d  整段 {p['return_pct']:+.1f}%  "
            f"日均值 {s['mean']*100:+.3f}%"
        )
        ax.set_title(title, fontsize=10, fontweight="bold", color=edge_color)

        txt = (
            f"N={s['n']}  均值 {s['mean']*100:+.3f}%  中位 {s['median']*100:+.3f}%\n"
            f"标准差 {s['std']*100:.3f}%  涨 {s['pct_pos']:.1f}%  跌 {s['pct_neg']:.1f}%\n"
            f"P1/P5/P95/P99: {s['p1']*100:+.2f}/{s['p5']*100:+.2f}/"
            f"{s['p95']*100:+.2f}/{s['p99']*100:+.2f}"
        )
        ax.text(
            0.99, 0.97, txt, transform=ax.transAxes,
            ha="right", va="top", fontsize=8,
            bbox=dict(boxstyle="round,pad=0.35", fc="white", ec="#bbb", alpha=0.9),
        )

        ax.set_xlabel("日收益率（%）", fontsize=8)
        ax.set_ylabel("占比（%）", fontsize=8)
        ax.grid(True, axis="y", alpha=0.25)
        ax.tick_params(labelsize=7.5)

    for ax in axes[len(panels):]:
        ax.axis("off")

    fig.suptitle(
        f"{code} 大级别牛熊分段内 日收益率分布（ZigZag 大尺度，桶宽 {bucket_width*100:.1f}%）",
        fontsize=14, fontweight="bold", y=0.995,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.985))
    output_png.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_png, dpi=130, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved to {output_png}")


def print_table(panels: list[dict]) -> None:
    print("\n=== 各段日收益率明细 ===")
    hdr = (
        f"{'#':>2} {'类型':<4} {'起止':<24} {'天数':>5} "
        f"{'整段%':>8} {'日均%':>8} {'中位%':>8} {'标准差%':>8} "
        f"{'涨%':>6} {'跌%':>6} {'P1%':>7} {'P99%':>7}"
    )
    print(hdr)
    print("-" * len(hdr))
    for p in panels:
        s = stats(p["ret"])
        rng = f"{p['start'].strftime('%Y-%m-%d')}~{p['end'].strftime('%Y-%m-%d')}"
        print(
            f"{p['seg']:>2} {DIR_CN[p['dir']]:<4} {rng:<24} {s['n']:>5} "
            f"{p['return_pct']:>+8.1f} {s['mean']*100:>+8.3f} "
            f"{s['median']*100:>+8.3f} {s['std']*100:>8.3f} "
            f"{s['pct_pos']:>6.1f} {s['pct_neg']:>6.1f} "
            f"{s['p1']*100:>+7.2f} {s['p99']*100:>+7.2f}"
        )

    print("\n=== 牛 vs 熊 聚合（按段内日收益扁平合并）===")
    for d, name in [("bull", "牛市"), ("bear", "熊市")]:
        rs = np.concatenate([p["ret"] for p in panels if p["dir"] == d])
        s = stats(rs)
        print(
            f"  {name}：N={s['n']:>5}  均值 {s['mean']*100:+.3f}%  "
            f"中位 {s['median']*100:+.3f}%  标准差 {s['std']*100:.3f}%  "
            f"涨 {s['pct_pos']:.1f}%  跌 {s['pct_neg']:.1f}%  "
            f"P1/P99 {s['p1']*100:+.2f}%/{s['p99']*100:+.2f}%"
        )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--segments-csv", type=Path,
        default=Path("/mnt/dataset/csi300_regime_segments/large_segments.csv"),
        help="分段 CSV（默认 large_segments.csv）",
    )
    p.add_argument(
        "--quote-path", type=Path,
        default=Path("/mnt/dataset/index_quote_history/000300.parquet"),
        help="指数日行情 parquet",
    )
    p.add_argument("--code", default="000300", help="指数代码（标题用）")
    p.add_argument(
        "--bucket-width", type=float, default=0.005,
        help="直方图桶宽（小数，0.005 = 0.5%）",
    )
    p.add_argument(
        "--output", type=Path, default=None,
        help="输出 PNG 路径",
    )
    args = p.parse_args()

    segments = load_segments(args.segments_csv).sort("seg")
    quotes = load_daily_returns(args.quote_path)

    panels: list[dict] = []
    last_idx = segments.height - 1
    for row, seg in enumerate(segments.iter_rows(named=True)):
        is_last = row == last_idx
        r = segment_returns(
            quotes, seg["start_date"], seg["end_date"], is_last
        )
        if r.size == 0:
            print(f"[warn] 段 {seg['seg']} 在行情数据中无样本，跳过")
            continue
        panels.append({
            "seg": seg["seg"], "dir": seg["dir"], "tail": seg["tail"],
            "start": seg["start_date"], "end": seg["end_date"],
            "trade_days": seg["trade_days"],
            "return_pct": float(seg["return_pct"]),
            "ret": r,
        })

    output = args.output or Path(
        f"/mnt/dataset/segment_daily_return_dist_{args.code}.png"
    )
    plot_grid(panels, args.bucket_width, args.code, output)
    print_table(panels)


if __name__ == "__main__":
    main()
