"""任意标的 N 日窗口收益率分布直方图（默认 512890 / 20 日 / 1% 桶宽）。

把每个交易日都视作一个 N 日持有期的起点，计算 close[t]/close[t-N] - 1，
得到历史上所有（重叠）N 日窗口的收益率序列，再以指定桶宽做直方图。

适合回答：「历史上任意 N 个交易日的持有期收益分布长什么样？
涨 / 跌超过 X% 的经验概率有多大？」

口径与提醒：
- **重叠滚动窗口**（step=1）：用足所有数据，但相邻样本高度自相关，
  不是独立同分布——做"经验概率"参考可以，做严格统计推断要谨慎。
- 桶边对齐到桶宽的整数倍（0 是桶边）：[-1%, 0%) 归负、[0%, +1%) 归正。
- 用前复权 close 算收益，避免分红除息制造假跌。
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import polars as pl
from matplotlib.transforms import blended_transform_factory

NEG_COLOR = "#2ca02c"    # 绿：负收益（中国市场绿=跌）
POS_COLOR = "#d62728"    # 红：正收益（中国市场红=涨）
ZERO_COLOR = "#7f7f7f"   # 灰：恰好 0 的桶
MEAN_COLOR = "#ff7f0e"   # 橙：均值线
MEDIAN_COLOR = "#1f77b4"  # 蓝：中位数线
PCT_COLOR = "#666666"    # 灰：分位线
CURRENT_COLOR = "#6a3d9a"  # 紫：当前值线
TAIL_PERCENTILES = [1, 5, 95, 99]


def load_close(adjusted_dir: Path, code: str, start_date: date | None) -> pl.DataFrame:
    """读前复权 close，按日升序。"""
    df = (
        pl.read_parquet(adjusted_dir / f"{code}.parquet", columns=["date", "close"])
        .with_columns(pl.col("date").str.to_date("%Y-%m-%d"))
        .sort("date")
    )
    if start_date is not None:
        df = df.filter(pl.col("date") >= start_date)
    return df


def compute_window_returns(df: pl.DataFrame, window: int) -> pl.Series:
    """close[t]/close[t-window] - 1，丢掉前 window 个 null。"""
    return (
        df.with_columns(
            (pl.col("close") / pl.col("close").shift(window) - 1).alias("ret")
        )
        .drop_nulls("ret")["ret"]
    )


def bin_edges(returns: np.ndarray, bucket_width: float) -> np.ndarray:
    """桶边对齐到 bucket_width 的整数倍，覆盖 [min, max]。"""
    lo = np.floor(returns.min() / bucket_width) * bucket_width
    hi = np.ceil(returns.max() / bucket_width) * bucket_width
    n = int(round((hi - lo) / bucket_width)) + 1
    return np.linspace(lo, hi, n)


def bar_colors(edges: np.ndarray) -> list[str]:
    """按桶符号染色：跨 0 或含 0 的桶算 0 附近，按起边判正负。"""
    colors = []
    for i in range(len(edges) - 1):
        left = edges[i]
        if left < 0:
            colors.append(NEG_COLOR)
        elif left > 0:
            colors.append(POS_COLOR)
        else:
            colors.append(ZERO_COLOR)
    return colors


def stats_dict(r: np.ndarray) -> dict:
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


def percentile_rank(sorted_r: np.ndarray, value: float) -> float:
    """value 在样本中的经验百分位（% of samples <= value）。"""
    return float(np.searchsorted(sorted_r, value, side="right") / len(sorted_r) * 100)


def plot(
    returns: np.ndarray,
    bucket_width: float,
    window: int,
    code: str,
    date_range: tuple[date, date],
    output_png: Path,
    current_ret: float,
) -> None:
    edges = bin_edges(returns, bucket_width)
    counts, _ = np.histogram(returns, bins=edges)
    total = counts.sum()
    pct = counts / total * 100 if total else counts
    centers = (edges[:-1] + edges[1:]) / 2
    colors = bar_colors(edges)
    s = stats_dict(returns)
    sorted_r = np.sort(returns)
    current_rank = percentile_rank(sorted_r, current_ret)

    plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "WenQuanYi Zen Hei"]
    plt.rcParams["axes.unicode_minus"] = False

    fig, ax = plt.subplots(figsize=(14, 7))
    ax.bar(centers * 100, pct, width=bucket_width * 100 * 0.9, color=colors,
           edgecolor="white", linewidth=0.4)

    ax.axvline(0, color="black", lw=0.8)
    ax.axvline(s["mean"] * 100, color=MEAN_COLOR, lw=1.0, ls="--",
               label=f"均值 {s['mean'] * 100:+.2f}%")
    ax.axvline(s["median"] * 100, color=MEDIAN_COLOR, lw=1.0, ls="--",
               label=f"中位数 {s['median'] * 100:+.2f}%")

    # 尾部分位线（1/5/95/99）+ 底部标注
    trans = blended_transform_factory(ax.transData, ax.transAxes)
    for q in TAIL_PERCENTILES:
        ls = ":" if q in (1, 99) else "--"
        ax.axvline(s[f"p{q}"] * 100, color=PCT_COLOR, lw=0.9, ls=ls, alpha=0.75)
        ax.text(s[f"p{q}"] * 100, 0.04, f"P{q}\n{s[f'p{q}'] * 100:+.1f}%",
                transform=trans, ha="center", va="bottom", fontsize=7.5,
                color=PCT_COLOR,
                bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="#ccc", alpha=0.9))

    # 当前值线
    ax.axvline(current_ret * 100, color=CURRENT_COLOR, lw=1.8,
               label=f"当前 {current_ret * 100:+.2f}%（p={current_rank:.0f}%）")

    stats_text = (
        f"样本数 N = {s['n']:,}（{window} 日窗口，重叠）\n"
        f"均值 {s['mean'] * 100:+.2f}%   中位数 {s['median'] * 100:+.2f}%\n"
        f"标准差 {s['std'] * 100:.2f}%\n"
        f"范围 [{s['min'] * 100:+.2f}%, {s['max'] * 100:+.2f}%]\n"
        f"1 / 5 / 95 / 99 分位: "
        f"{s['p1'] * 100:+.1f}% / {s['p5'] * 100:+.1f}% / "
        f"{s['p95'] * 100:+.1f}% / {s['p99'] * 100:+.1f}%\n"
        f"当前 {current_ret * 100:+.2f}%（p={current_rank:.0f}%）\n"
        f"涨 {s['pct_pos']:.1f}% ｜ 跌 {s['pct_neg']:.1f}% ｜ 持平 {s['pct_flat']:.1f}%"
    )
    ax.text(0.99, 0.97, stats_text, transform=ax.transAxes, ha="right", va="top",
            fontsize=9.5,
            bbox=dict(boxstyle="round,pad=0.5", fc="white", ec="#bbb", alpha=0.9))

    ax.set_title(
        f"{code} 历史上 {window} 日窗口收益率分布"
        f"（{date_range[0]} ~ {date_range[1]}，桶宽 {bucket_width * 100:.0f}%）",
        fontsize=13, fontweight="bold",
    )
    ax.set_xlabel(f"{window} 日窗口收益率（%）")
    ax.set_ylabel("占比（%）")
    ax.grid(True, axis="y", alpha=0.3)
    ax.legend(loc="upper left", fontsize=9)

    plt.tight_layout()
    output_png.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_png, dpi=130, bbox_inches="tight")
    plt.close(fig)

    print(f"Saved to {output_png}")
    print(f"\n=== {code} {window} 日窗口收益率统计（N={s['n']:,}，桶宽 {bucket_width*100:.0f}%）===")
    print(f"  均值 {s['mean']*100:+.2f}%   中位数 {s['median']*100:+.2f}%   标准差 {s['std']*100:.2f}%")
    print(f"  范围 [{s['min']*100:+.2f}%, {s['max']*100:+.2f}%]")
    print(f"  1/5/95/99 分位: {s['p1']*100:+.1f}% / {s['p5']*100:+.1f}% / "
          f"{s['p95']*100:+.1f}% / {s['p99']*100:+.1f}%")
    print(f"  当前 {current_ret*100:+.2f}%（p={current_rank:.0f}%）")
    print(f"  涨 {s['pct_pos']:.1f}% ｜ 跌 {s['pct_neg']:.1f}% ｜ 持平 {s['pct_flat']:.1f}%")

    print(f"\n各桶明细（{window} 日收益，桶宽 {bucket_width*100:.0f}%）：")
    print(f"  {'区间':<16}{'占比%':>8}{'累计%':>9}")
    cum = 0.0
    for i in range(len(counts)):
        if counts[i] == 0:
            continue
        lo = edges[i] * 100
        hi = edges[i + 1] * 100
        cum += pct[i]
        print(f"  [{lo:+6.1f}%, {hi:+6.1f}%){pct[i]:>9.2f}{cum:>9.2f}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--code", default="512890", help="标的代码（基金/指数/股票）")
    p.add_argument(
        "--adjusted-dir", type=Path,
        default=Path("/mnt/dataset/fund_quote_adjusted"),
        help="含 {code}.parquet 的前复权行情目录",
    )
    p.add_argument("--window", type=int, default=20, help="窗口长度（交易日）")
    p.add_argument("--bucket-width", type=float, default=0.01,
                   help="直方图桶宽（小数，0.01 = 1%）")
    p.add_argument(
        "--start-date", type=str, default=None,
        help="起始日期 YYYY-MM-DD（默认从最早数据起）",
    )
    p.add_argument(
        "--output", type=Path, default=None,
        help="输出 PNG 路径（默认 return_distribution_{code}_{window}d.png）",
    )
    args = p.parse_args()

    start = date.fromisoformat(args.start_date) if args.start_date else None
    df = load_close(args.adjusted_dir, args.code, start)
    if df.height <= args.window:
        raise SystemExit(f"[red]{args.code} 只有 {df.height} 行，不足 {args.window} 日窗口[/red]")

    returns = compute_window_returns(df, args.window).to_numpy()
    date_range = (df["date"].to_list()[0], df["date"].to_list()[-1])
    output = args.output or Path(
        f"/mnt/dataset/return_distribution_{args.code}_{args.window}d.png"
    )
    plot(returns, args.bucket_width, args.window, args.code, date_range, output,
         current_ret=float(returns[-1]))


if __name__ == "__main__":
    main()
