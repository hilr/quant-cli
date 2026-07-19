"""N 日 Bollinger 通道突破事件 → 未来 M 日收益分布。

回答：「沪深300 收盘价突破 N 日 Bollinger 上/下轨（±kσ）后，未来 5/10/20 日
的收益分布长什么样？是否有显著的均值偏移或动量/反转效应？」

口径：
- 通道：ma = close.rolling_mean(N)，sigma = close.rolling_std(N)，
  upper = ma + k·sigma，lower = ma − k·sigma
- 突破事件 = "首次穿越"：前一日仍在通道内、当日 close > upper（向上突破）
  或 close < lower（向下突破）；连续多日在通道外只算 1 个事件
- r_fwd_m(t) = close[t+m] / close[t] − 1
- 每个 (方向, horizon) 桶：N / 均值 / 中位 / 标准差 / P5/P25/P75/P95 / P(>0)
- 与全局基线（所有交易日的 r_fwd_m）对比

输出：
- PNG：2 行 × 3 列直方图网格。上行=向上突破、下行=向下突破；
  列=5/10/20 日。每面板含收益直方图 + 均值/中位/基线均值的竖虚线，
  标题与文本框给出 N、均值、alpha vs 基线、P(>0)
- 控制台：每方向 × horizon 一行统计 + 全局基线
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import polars as pl

NEG_COLOR = "#2ca02c"
POS_COLOR = "#d62728"
BASE_COLOR = "#7f7f7f"
MEAN_COLOR = "#ff7f0e"
MEDIAN_COLOR = "#1f77b4"


def load_close(adjusted_dir: Path, code: str) -> pl.DataFrame:
    return (
        pl.read_parquet(adjusted_dir / f"{code}.parquet", columns=["date", "close"])
        .with_columns(pl.col("date").str.to_date("%Y-%m-%d"))
        .sort("date")
    )


def compute_bands(df: pl.DataFrame, window: int, k: float) -> pl.DataFrame:
    return (
        df.with_columns(
            pl.col("close").rolling_mean(window).alias("ma"),
            pl.col("close").rolling_std(window).alias("sigma"),
        )
        .with_columns(
            (pl.col("ma") + k * pl.col("sigma")).alias("upper"),
            (pl.col("ma") - k * pl.col("sigma")).alias("lower"),
        )
        .drop_nulls("ma")
    )


def mark_breakouts(df: pl.DataFrame) -> pl.DataFrame:
    """标记向上/向下首次穿越日。"""
    df = df.with_columns(
        (pl.col("close") > pl.col("upper")).alias("above"),
        (pl.col("close") < pl.col("lower")).alias("below"),
    )
    return df.with_columns(
        (
            pl.col("above")
            & ~pl.col("above").shift(1).fill_null(False)
        ).alias("cross_up"),
        (
            pl.col("below")
            & ~pl.col("below").shift(1).fill_null(False)
        ).alias("cross_down"),
    )


def add_forward_returns(df: pl.DataFrame, horizons: list[int]) -> pl.DataFrame:
    for m in horizons:
        df = df.with_columns(
            (pl.col("close").shift(-m) / pl.col("close") - 1).alias(f"fwd_{m}")
        )
    return df


def stats(r: np.ndarray) -> dict:
    if len(r) == 0:
        return {}
    return {
        "n": len(r),
        "mean": float(np.mean(r)),
        "median": float(np.median(r)),
        "std": float(np.std(r, ddof=1)) if len(r) > 1 else 0.0,
        "p5": float(np.percentile(r, 5)),
        "p25": float(np.percentile(r, 25)),
        "p75": float(np.percentile(r, 75)),
        "p95": float(np.percentile(r, 95)),
        "p_pos": float(np.mean(r > 0) * 100),
    }


def plot_panel(
    ax,
    r: np.ndarray,
    baseline_mean: float,
    bucket_width: float,
    title: str,
) -> None:
    s = stats(r)
    edges = np.arange(
        np.floor(s["p5"] * 100 / (bucket_width * 100)) * bucket_width,
        np.ceil(s["p95"] * 100 / (bucket_width * 100)) * bucket_width + bucket_width,
        bucket_width,
    )
    edges = edges[(edges >= s["p5"] - bucket_width) & (edges <= s["p95"] + bucket_width)]
    if len(edges) < 2:
        edges = np.linspace(s["p5"], s["p95"], 20)
    centers = (edges[:-1] + edges[1:]) / 2
    counts, _ = np.histogram(r, bins=edges)
    pct = counts / counts.sum() * 100 if counts.sum() else counts
    colors = [
        POS_COLOR if c >= 0 else NEG_COLOR for c in centers
    ]
    ax.bar(centers * 100, pct, width=bucket_width * 100 * 0.9, color=colors,
           edgecolor="white", linewidth=0.4, alpha=0.75)

    ax.axvline(0, color="black", lw=0.6)
    ax.axvline(s["mean"] * 100, color=MEAN_COLOR, lw=1.4, ls="--",
               label=f"均值 {s['mean']*100:+.2f}%")
    ax.axvline(s["median"] * 100, color=MEDIAN_COLOR, lw=1.2, ls=":",
               label=f"中位 {s['median']*100:+.2f}%")
    ax.axvline(baseline_mean * 100, color=BASE_COLOR, lw=1.4, ls="-.",
               label=f"基线 {baseline_mean*100:+.2f}%")

    alpha = s["mean"] - baseline_mean
    text = (
        f"N = {s['n']}\n"
        f"均值 {s['mean']*100:+.2f}%  α {alpha*100:+.2f}%\n"
        f"中位 {s['median']*100:+.2f}%  σ {s['std']*100:.2f}%\n"
        f"P(>0) {s['p_pos']:.1f}%\n"
        f"P5/95  {s['p5']*100:+.1f}% / {s['p95']*100:+.1f}%"
    )
    ax.text(0.97, 0.97, text, transform=ax.transAxes, ha="right", va="top",
            fontsize=8.5,
            bbox=dict(boxstyle="round,pad=0.4", fc="white", ec="#bbb", alpha=0.9))

    ax.set_title(title, fontsize=11, fontweight="bold")
    ax.set_xlabel("未来收益（%）")
    ax.set_ylabel("占比（%）")
    ax.grid(True, axis="y", alpha=0.3)
    ax.legend(loc="upper left", fontsize=7.5)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--code", default="000300")
    p.add_argument("--adjusted-dir", type=Path,
                   default=Path("/mnt/dataset/index_quote_history"))
    p.add_argument("--window", type=int, default=20, help="Bollinger 通道窗口（日）")
    p.add_argument("--k", type=float, default=2.0, help="σ 倍数")
    p.add_argument("--horizons", type=int, nargs="+", default=[5, 10, 20],
                   help="未来持有期（日），默认 5 10 20")
    p.add_argument("--bucket-width", type=float, default=0.01,
                   help="直方图桶宽（小数，0.01 = 1%）")
    p.add_argument("--output", type=Path, default=None)
    args = p.parse_args()

    df = mark_breakouts(compute_bands(load_close(args.adjusted_dir, args.code),
                                      args.window, args.k))
    df = add_forward_returns(df, args.horizons)

    # 基线：所有交易日的 fwd 收益
    baseline = {m: stats(df[f"fwd_{m}"].drop_nulls().to_numpy())
                for m in args.horizons}

    rows = [
        ("cross_up", "向上突破（收 > 上轨）", POS_COLOR),
        ("cross_down", "向下突破（收 < 下轨）", NEG_COLOR),
    ]

    fig, axes = plt.subplots(len(rows), len(args.horizons),
                             figsize=(6 * len(args.horizons), 5 * len(rows)),
                             constrained_layout=True)
    plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "WenQuanYi Zen Hei"]
    plt.rcParams["axes.unicode_minus"] = False

    print(f"\n=== {args.code} {args.window}d Bollinger ±{args.k}σ 突破 → 未来收益 ===")
    print(f"区间 {df['date'].min()} ~ {df['date'].max()}, 总 {df.height} 行\n")
    print(f"{'方向':<22}{'horizon':<10}{'N':>5}{'均值':>10}{'中位':>10}"
          f"{'σ':>9}{'P(>0)':>9}{'α vs 基线':>13}")

    for ri, (col, label, _) in enumerate(rows):
        sub = df.filter(pl.col(col))
        for ci, m in enumerate(args.horizons):
            r = sub[f"fwd_{m}"].drop_nulls().to_numpy()
            s = stats(r)
            bl = baseline[m]
            alpha = s["mean"] - bl["mean"]
            print(f"{label:<22}fwd_{m:<5}{s['n']:>5}"
                  f"{s['mean']*100:>+9.2f}%{s['median']*100:>+9.2f}%"
                  f"{s['std']*100:>8.2f}%{s['p_pos']:>8.1f}%"
                  f"{alpha*100:>+12.2f}%")
            ax = axes[ri, ci] if len(rows) > 1 else axes[ci]
            plot_panel(ax, r, bl["mean"], args.bucket_width,
                       f"{label}  fwd {m}d")
        print()

    print(f"{'全局基线':<22}", end="")
    for m in args.horizons:
        bl = baseline[m]
        print(f"  fwd_{m}: N={bl['n']} 均值 {bl['mean']*100:+.2f}% "
              f"中位 {bl['median']*100:+.2f}% σ {bl['std']*100:.2f}% "
              f"P(>0) {bl['p_pos']:.1f}%")
    print()

    fig.suptitle(
        f"{args.code} {args.window}日 Bollinger ±{args.k}σ 突破事件 → 未来收益分布"
        f"（{df['date'].min()} ~ {df['date'].max()}）",
        fontsize=13, fontweight="bold",
    )
    output = args.output or Path(
        f"/mnt/dataset/boll_breakout_fwd_{args.code}_w{args.window}_k{args.k}.png"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output, dpi=130, bbox_inches="tight")
    plt.close(fig)
    print(f"\nSaved to {output}")


if __name__ == "__main__":
    main()
