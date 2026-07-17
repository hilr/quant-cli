"""扫描 N1=1..10 × N2=1..3，找厚尾可操作的桶，并把 top 模式画成 box plot。

复用 conditional_forward_return 的逻辑，对每个 (N1, N2) 组合跑一遍条件分布，
然后跨组合筛选：
- 桶样本 n >= 30（统计可靠）
- excess kurtosis >= 1.0（厚尾，正态=0）
- 均值偏移 95%CI 不含基线（可操作）

输出：
1. 控制台：总览计数 + 按 |均值偏移| 排序的 top 25 + 按 kurt 排序的 top 25
2. PNG：top N 模式的 box plot（须=P5/P95、点=均值、灰短横=基线均值），
       按可操作性排序，一眼看出哪些条件值得策略化。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conditional_forward_return import (  # noqa: E402
    DEFAULT_BUCKET_EDGES,
    compute_panel,
    label_regime,
    load_pair_returns,
    load_segments,
)

SEGMENTS_CSV = Path("/mnt/dataset/csi300_regime_segments/large_segments.csv")
QUOTE_PATH = Path("/mnt/dataset/index_quote_history/000300.parquet")
MIN_N = 30
KURT_THRESHOLD = 1.0

DIR_CN = {"bull": "牛", "bear": "熊"}
REGIME_COLOR = {"bull": "#d62728", "bear": "#2ca02c"}


def bucket_label(lo: float, hi: float) -> str:
    def fmt(x: float, lower: bool) -> str:
        if np.isneginf(x):
            return "(-∞"
        if np.isposinf(x):
            return "+∞)"
        return ("[" if lower else ")") + f"{x:+g}%"
    return f"{fmt(lo, True)}, {fmt(hi, False)}"


def short_bucket_label(lo: float, hi: float) -> str:
    if np.isneginf(lo):
        return f"≤{hi:+g}%"
    if np.isposinf(hi):
        return f"≥{lo:+g}%"
    return f"[{lo:+g}%,{hi:+g}%)"


def sweep(segments: pl.DataFrame, edges: list[float]) -> tuple[pl.DataFrame, dict]:
    """跑全部 (N1, N2, regime, bucket) 组合，返回 stats DataFrame + raw y 字典。"""
    bucket_names = [bucket_label(edges[i], edges[i + 1]) for i in range(len(edges) - 1)]
    rows = []
    raw_y: dict[tuple[int, int, str, int], np.ndarray] = {}

    for n1 in range(1, 11):
        for n2 in range(1, 4):
            pairs = load_pair_returns(QUOTE_PATH, n1, n2)
            pairs = label_regime(pairs, segments)
            for d in ("bull", "bear"):
                sub = pairs.filter(pl.col("regime") == d)
                x = sub["ret_today"].to_numpy() * 100
                y = sub["ret_next"].to_numpy() * 100
                panel = compute_panel(x, y, edges)
                bl = panel["baseline"]
                for i, b in enumerate(panel["buckets"]):
                    if b["n"] < MIN_N:
                        continue
                    ci_lo = b["mean"] - 1.96 * b["se_mean"]
                    ci_hi = b["mean"] + 1.96 * b["se_mean"]
                    sig = (ci_lo > bl["mean"]) or (ci_hi < bl["mean"])
                    rows.append({
                        "N1": n1, "N2": n2, "regime": d,
                        "bucket_idx": i,
                        "bucket": bucket_names[i],
                        "bucket_short": short_bucket_label(edges[i], edges[i + 1]),
                        "n": b["n"],
                        "mean": b["mean"],
                        "mean_shift": b["mean"] - bl["mean"],
                        "ci_lo": ci_lo, "ci_hi": ci_hi,
                        "sig": sig,
                        "base_mean": bl["mean"],
                        "std": b["std"], "std_ratio": b["std"] / bl["std"],
                        "skew": b["skew"], "kurt": b["kurt"],
                        "p5": b["p5"], "p50": b["p50"], "p95": b["p95"],
                        "p5_vs_base": b["p5"] - bl["p5"],
                        "p95_vs_base": b["p95"] - bl["p95"],
                    })
                    raw_y[(n1, n2, d, i)] = b["y"]

    df = pl.DataFrame(rows, schema_overrides={"sig": pl.Boolean})
    return df, raw_y


def print_tables(df: pl.DataFrame) -> None:
    fat = df.filter(pl.col("kurt") >= KURT_THRESHOLD)
    actionable = fat.filter(pl.col("sig"))
    print(f"\n总桶数（n>={MIN_N}）: {df.height}，"
          f"厚尾（kurt>={KURT_THRESHOLD}）: {fat.height}，"
          f"厚尾+显著偏移: {actionable.height}")

    print("\n=== TOP 25 厚尾+显著偏移 桶（按 |mean_shift| 降序） ===")
    top = actionable.with_columns(
        pl.col("mean_shift").abs().alias("abs_shift")
    ).sort("abs_shift", descending=True).head(25)
    with pl.Config(tbl_rows=30, tbl_cols=20, tbl_width_chars=220):
        print(top.select([
            "N1", "N2", "regime", "bucket", "n",
            pl.col("mean").round(3).alias("mean%"),
            pl.col("base_mean").round(3).alias("base%"),
            pl.col("mean_shift").round(3).alias("shift%"),
            pl.col("ci_lo").round(2).alias("CIlo"),
            pl.col("ci_hi").round(2).alias("CIhi"),
            pl.col("std").round(2).alias("std%"),
            pl.col("std_ratio").round(2).alias("std/基"),
            pl.col("skew").round(2).alias("skew"),
            pl.col("kurt").round(2).alias("kurt"),
            pl.col("p5").round(2).alias("P5"),
            pl.col("p95").round(2).alias("P95"),
        ]))

    print("\n=== TOP 25 厚尾+显著偏移 桶（按 kurt 降序，看最厚尾） ===")
    top_k = actionable.sort("kurt", descending=True).head(25)
    with pl.Config(tbl_rows=30, tbl_cols=20, tbl_width_chars=220):
        print(top_k.select([
            "N1", "N2", "regime", "bucket", "n",
            pl.col("mean").round(3).alias("mean%"),
            pl.col("mean_shift").round(3).alias("shift%"),
            pl.col("skew").round(2).alias("skew"),
            pl.col("kurt").round(2).alias("kurt"),
            pl.col("std").round(2).alias("std%"),
            pl.col("p5").round(2).alias("P5"),
            pl.col("p95").round(2).alias("P95"),
            pl.col("p5_vs_base").round(2).alias("P5-base"),
            pl.col("p95_vs_base").round(2).alias("P95-base"),
        ]))


def plot_top(
    df: pl.DataFrame,
    raw_y: dict,
    output_png: Path,
    top_n: int,
    segments: pl.DataFrame,
    edges: list[float],
) -> None:
    """画 top N 厚尾+显著偏移（双向：最负 + 最正）模式的 box plot。

    分布信息卡片（regime/N1→N2/桶/n/μ/Δ/P5/P95/kurt/skew）放在 x 轴下方。
    左半 = 显著负偏移、右半 = 显著正偏移，可视化偏移方向不对称。
    """
    actionable = df.filter(
        pl.col("sig") & (pl.col("kurt") >= KURT_THRESHOLD) & (pl.col("n") >= MIN_N)
    )
    half = max(1, top_n // 2)
    pos = (
        actionable.filter(pl.col("mean_shift") > 0)
        .with_columns(pl.col("mean_shift").abs().alias("abs_shift"))
        .sort("abs_shift", descending=True)
        .head(half)
    )
    neg = (
        actionable.filter(pl.col("mean_shift") < 0)
        .with_columns(pl.col("mean_shift").abs().alias("abs_shift"))
        .sort("abs_shift", descending=True)
        .head(half)
    )
    # 左→右：最负的 → 中间 → 最正的
    top = pl.concat([
        neg.sort("mean_shift"),
        pos.sort("mean_shift", descending=True),
    ])

    if top.height == 0:
        print("[warn] 无符合条件的模式")
        return

    plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "WenQuanYi Zen Hei"]
    plt.rcParams["axes.unicode_minus"] = False

    fig, ax = plt.subplots(figsize=(max(13, top.height * 1.35), 9.0))
    fig.subplots_adjust(bottom=0.34, top=0.86)

    box_data = []
    colors = []
    for row in top.iter_rows(named=True):
        key = (row["N1"], row["N2"], row["regime"], row["bucket_idx"])
        box_data.append(raw_y[key])
        colors.append(REGIME_COLOR[row["regime"]])

    positions = np.arange(1, len(box_data) + 1)
    bp = ax.boxplot(
        box_data, positions=positions, widths=0.55,
        whis=[5, 95], showfliers=False, patch_artist=True,
        medianprops=dict(color="black", lw=1.3),
        whiskerprops=dict(lw=1.0),
        capprops=dict(lw=1.0),
    )
    for patch, color in zip(bp["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.35)
        patch.set_edgecolor(color)

    for i, row in enumerate(top.iter_rows(named=True)):
        color = colors[i]
        ax.plot(positions[i], row["mean"], "o", color=color, ms=7, zorder=5)
        ax.plot(
            positions[i], row["base_mean"], "_",
            color="gray", ms=14, mew=2.2, zorder=4,
        )

    ax.set_xticks(positions)
    ax.set_xticklabels([])
    ax.tick_params(axis="x", length=0)
    ax.set_ylabel("未来 N2 日收益（%）", fontsize=11)
    ax.set_title(
        f"沪深300 厚尾+显著偏移（双向）TOP {len(box_data)} 条件分布\n"
        f"左 = 显著负偏移、右 = 显著正偏移；"
        f"须=P5/P95、箱=P25/P75、彩点=均值、灰短横=该 regime/N1/N2 基线均值",
        fontsize=12, fontweight="bold",
    )
    ax.axhline(0, color="black", lw=0.6, alpha=0.6)
    ax.grid(True, axis="y", alpha=0.3)

    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    legend = [
        Patch(facecolor=REGIME_COLOR["bull"], alpha=0.4, edgecolor=REGIME_COLOR["bull"], label="牛市桶"),
        Patch(facecolor=REGIME_COLOR["bear"], alpha=0.4, edgecolor=REGIME_COLOR["bear"], label="熊市桶"),
        Line2D([0], [0], marker="_", color="gray", linestyle="", markersize=12, markeredgewidth=2.2, label="基线均值"),
        Line2D([0], [0], marker="o", color="black", linestyle="", markersize=7, label="桶均值"),
    ]
    ax.legend(handles=legend, loc="upper left", fontsize=9)

    # 分布信息卡片放在 x 轴下方
    for i, row in enumerate(top.iter_rows(named=True)):
        color = colors[i]
        card = (
            f"{DIR_CN[row['regime']]} {row['N1']}d→{row['N2']}d\n"
            f"{row['bucket_short']}\n"
            f"──────\n"
            f"n = {row['n']}\n"
            f"μ = {row['mean']:+.2f}%\n"
            f"Δ = {row['mean_shift']:+.2f}pp\n"
            f"P5 = {row['p5']:+.1f}%\n"
            f"P95 = {row['p95']:+.1f}%\n"
            f"kurt = {row['kurt']:.1f}\n"
            f"skew = {row['skew']:+.2f}"
        )
        ax.text(
            positions[i], -0.03, card,
            transform=ax.get_xaxis_transform(),
            ha="center", va="top", fontsize=7.5,
            bbox=dict(
                boxstyle="round,pad=0.4", fc="white", ec=color,
                alpha=0.95, lw=1.3,
            ),
        )

    output_png.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_png, dpi=130, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved to {output_png}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--top", type=int, default=12, help="box plot 显示的模式数（默认 12）")
    p.add_argument("--output", type=Path, default=None, help="输出 PNG 路径")
    args = p.parse_args()

    segments = load_segments(SEGMENTS_CSV)
    edges = list(DEFAULT_BUCKET_EDGES)

    df, raw_y = sweep(segments, edges)
    print_tables(df)

    output = args.output or Path("/mnt/dataset/sweep_conditional_tail.png")
    plot_top(df, raw_y, output, args.top, segments, edges)


if __name__ == "__main__":
    main()
