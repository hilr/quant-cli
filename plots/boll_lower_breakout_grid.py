"""Boll 下轨破位 × 当日破位深度 / N 日位置 双维网格 → 未来 M 日极值收益分布。

筛选 close < boll_lower（破下轨）的所有交易日，按两个当日状态维度分桶：

1. **pct_win**：当日 close 在过去 `--pct-window`（默认 250 ≈ 1 年）日 close
   范围内的位置
   `(close − rolling_min) / (rolling_max − rolling_min)`。
   0 = N 日新低、1 = N 日新高。
2. **penetration**：当日破位深度
   `(lower − close) / lower`，close 跌破下轨的幅度占下轨的百分比。
   仅在 close < lower 时为正，本图样本已 filter close<lower，所以恒 > 0。

对每个网格桶，统计**未来 N 日内**：
- **max_return**：`max(high[t+1..t+N]) / close[t] − 1`（持有期内最大潜在涨幅）
- **min_return**：`min(low[t+1..t+N]) / close[t] − 1`（持有期内最大潜在跌幅）

⚠️ **不是到期收益**：是路径极值，反映"挂单止盈能拿到的最好价"与
"持有期间承受的最深回撤"。

输出：
- PNG：两块热力图（max / min），每格注释 N / μ / M / [P1, P5, P95, P99]
- 控制台：每格完整统计 + 全局基线
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import polars as pl


def load_quote(adjusted_dir: Path, code: str) -> pl.DataFrame:
    return (
        pl.read_parquet(adjusted_dir / f"{code}.parquet",
                        columns=["date", "high", "low", "close"])
        .with_columns(pl.col("date").str.to_date("%Y-%m-%d"))
        .sort("date")
    )


def compute_features(
    df: pl.DataFrame, boll_window: int, k: float, pct_window: int
) -> pl.DataFrame:
    df = df.with_columns(
        pl.col("close").rolling_mean(boll_window).alias("ma"),
        pl.col("close").rolling_std(boll_window).alias("sigma"),
    ).with_columns(
        (pl.col("ma") + k * pl.col("sigma")).alias("upper"),
        (pl.col("ma") - k * pl.col("sigma")).alias("lower"),
    )
    df = df.with_columns(
        (pl.col("close") < pl.col("lower")).cast(pl.Int32).alias("below_flag"),
        # 破位深度 = (下轨 - close) / 下轨，未破位记 0；逐日幅度
        pl.when(pl.col("close") < pl.col("lower"))
          .then((pl.col("lower") - pl.col("close")) / pl.col("lower"))
          .otherwise(0.0)
          .alias("penetration"),
        pl.col("close").rolling_min(pct_window).alias("min_win"),
        pl.col("close").rolling_max(pct_window).alias("max_win"),
    )
    df = df.with_columns(
        ((pl.col("close") - pl.col("min_win"))
         / (pl.col("max_win") - pl.col("min_win"))).alias("pct_win"),
    )
    return df


def add_forward_extremes(df: pl.DataFrame, horizon: int) -> pl.DataFrame:
    """未来 horizon 日内的 max(high)/close-1 和 min(low)/close-1。"""
    max_exprs = []
    min_exprs = []
    for off in range(1, horizon + 1):
        max_exprs.append(pl.col("high").shift(-off) / pl.col("close") - 1)
        min_exprs.append(pl.col("low").shift(-off) / pl.col("close") - 1)
    df = df.with_columns(
        pl.max_horizontal(max_exprs).alias(f"max_ret_{horizon}"),
        pl.min_horizontal(min_exprs).alias(f"min_ret_{horizon}"),
    )
    return df


def rank_buckets(values: np.ndarray, n: int) -> tuple[np.ndarray, list[tuple[float, float]]]:
    """按 rank 切 n 个等样本量的桶（解决 pct_win 在 0 处大量打结导致 quantile 切点
    塌缩的问题）。返回每个样本的桶索引 + 每个桶实际的数值范围 [lo, hi]
    用于坐标轴标签。"""
    order = np.argsort(values, kind="stable")
    ranks = np.empty_like(order)
    ranks[order] = np.arange(len(values))
    bucket_size = len(values) // n
    idx = np.clip(ranks // bucket_size, 0, n - 1)
    edges = np.linspace(0, len(values), n + 1).astype(int)
    bucket_ranges = []
    for i in range(n):
        lo = edges[i]
        hi = edges[i + 1]
        if hi > lo:
            v_slice = values[order[lo:hi]]
            bucket_ranges.append((float(v_slice.min()), float(v_slice.max())))
        else:
            bucket_ranges.append((float("nan"), float("nan")))
    return idx, bucket_ranges


def stats_full(r: np.ndarray) -> dict:
    if len(r) == 0:
        return {"n": 0}
    return {
        "n": len(r),
        "mean": float(np.mean(r)),
        "median": float(np.median(r)),
        "p1": float(np.percentile(r, 1)),
        "p5": float(np.percentile(r, 5)),
        "p25": float(np.percentile(r, 25)),
        "p75": float(np.percentile(r, 75)),
        "p95": float(np.percentile(r, 95)),
        "p99": float(np.percentile(r, 99)),
    }


def draw_heatmap(
    ax, grid_stats: dict, col_ranges: list, row_ranges: list,
    value_key: str, title: str, pct_window: int = 250,
) -> None:
    n_cols = len(col_ranges)
    n_rows = len(row_ranges)
    Z = np.full((n_rows, n_cols), np.nan)
    for (r, c), s in grid_stats.items():
        if s.get("n", 0) > 0:
            Z[r, c] = s[value_key] * 100

    im = ax.imshow(Z, cmap="RdYlGn" if "max" in value_key else "RdYlGn_r",
                   aspect="auto", origin="lower")

    col_labels = [f"[{col_ranges[i][0]*100:.0f}%,{col_ranges[i][1]*100:.0f}%]"
                  for i in range(n_cols)]
    row_labels = [f"[{row_ranges[i][0]*100:.3f}%,{row_ranges[i][1]*100:.3f}%]"
                  for i in range(n_rows)]
    ax.set_xticks(range(n_cols))
    ax.set_xticklabels(col_labels, rotation=30, ha="right", fontsize=8)
    ax.set_yticks(range(n_rows))
    ax.set_yticklabels(row_labels, fontsize=8)
    ax.set_xlabel(f"{pct_window} 日位置 pct_win", fontsize=9)
    ax.set_ylabel("当日破位深度 penetration", fontsize=9)
    ax.set_title(title, fontsize=11, fontweight="bold")

    for r in range(n_rows):
        for c in range(n_cols):
            s = grid_stats.get((r, c), {})
            if s.get("n", 0) == 0:
                ax.text(c, r, "—", ha="center", va="center", fontsize=9,
                        color="#999")
                continue
            txt = (
                f"N={s['n']}\n"
                f"μ {s[value_key]*100:+.2f}%\n"
                f"M {s['median']*100:+.2f}%\n"
                f"[{s['p1']*100:+.1f}%,{s['p5']*100:+.1f}%,"
                f"{s['p95']*100:+.1f}%,{s['p99']*100:+.1f}%]"
            )
            ax.text(c, r, txt, ha="center", va="center", fontsize=7.0,
                    color="black")

    # 图例：说明每格数字含义
    legend_txt = (
        "每格字段：\n"
        "N = 样本数\n"
        "μ = 均值\n"
        "M = 中位数\n"
        "[P1, P5, P95, P99] = 尾部分位"
    )
    ax.text(
        1.02, 0.5, legend_txt, transform=ax.transAxes,
        ha="left", va="center", fontsize=8,
        bbox=dict(boxstyle="round,pad=0.4", fc="#fffbe6", ec="#999", alpha=0.95),
    )

    plt.colorbar(im, ax=ax, shrink=0.85)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--code", default="000300")
    p.add_argument("--adjusted-dir", type=Path,
                   default=Path("/mnt/dataset/index_quote_history"))
    p.add_argument("--boll-window", type=int, default=20)
    p.add_argument("--k", type=float, default=2.0)
    p.add_argument("--pct-window", type=int, default=250,
                   help="位置窗口（默认 250 ≈ 1 年交易日）")
    p.add_argument("--horizon", type=int, default=5)
    p.add_argument("--n-buckets", type=int, default=3,
                   help="每个维度的分桶数（默认 3×3 网格）")
    p.add_argument("--output", type=Path, default=None)
    args = p.parse_args()

    df = compute_features(
        load_quote(args.adjusted_dir, args.code),
        args.boll_window, args.k, args.pct_window,
    )
    df = add_forward_extremes(df, args.horizon)
    below_df = df.filter(
        pl.col("below_flag") == 1
    ).drop_nulls(["pct_win", "penetration",
                  f"max_ret_{args.horizon}", f"min_ret_{args.horizon}"])

    print(f"\n=== {args.code} close < {args.boll_window}d Boll ±{args.k}σ 下轨 "
          f"→ 未来 {args.horizon} 日极值 ===")
    print(f"区间 {df['date'].min()} ~ {df['date'].max()}")
    print(f"破下轨样本数: {below_df.height}")
    if below_df.height == 0:
        return

    pct = below_df["pct_win"].to_numpy()
    pen = below_df["penetration"].to_numpy()
    col_idx, col_ranges = rank_buckets(pct, args.n_buckets)
    row_idx, row_ranges = rank_buckets(pen, args.n_buckets)

    grid: dict[tuple[int, int], dict] = {}
    max_arr = below_df[f"max_ret_{args.horizon}"].to_numpy()
    min_arr = below_df[f"min_ret_{args.horizon}"].to_numpy()
    for i in range(len(pct)):
        key = (int(row_idx[i]), int(col_idx[i]))
        grid.setdefault(key, {"max": [], "min": []})
        grid[key]["max"].append(max_arr[i])
        grid[key]["min"].append(min_arr[i])

    grid_stats: dict[tuple[int, int], dict] = {}
    for key, vals in grid.items():
        sm = stats_full(np.array(vals["max"]))
        sn = stats_full(np.array(vals["min"]))
        grid_stats[key] = {
            "n": sm["n"],
            "max_mean": sm["mean"], "max_median": sm["median"],
            "max_p1": sm["p1"], "max_p5": sm["p5"],
            "max_p25": sm["p25"], "max_p75": sm["p75"],
            "max_p95": sm["p95"], "max_p99": sm["p99"],
            "min_mean": sn["mean"], "min_median": sn["median"],
            "min_p1": sn["p1"], "min_p5": sn["p5"],
            "min_p25": sn["p25"], "min_p75": sn["p75"],
            "min_p95": sn["p95"], "min_p99": sn["p99"],
        }

    # 控制台输出
    print(f"\n网格 {args.n_buckets}×{args.n_buckets}（按 rank 等样本量切，避免打结）")
    print(f"  pct_win ({args.pct_window}日位置) 桶范围: " + " / ".join(
        f"[{lo*100:.1f}%,{hi*100:.1f}%]" for lo, hi in col_ranges))
    print(f"  penetration 桶范围（当日破位深度）: " + " / ".join(
        f"[{lo*100:.3f}%,{hi*100:.3f}%]" for lo, hi in row_ranges))

    print(f"\n各格详细统计（row=penetration 桶, col=pct_win 桶）:")
    for r in range(args.n_buckets):
        for c in range(args.n_buckets):
            s = grid_stats.get((r, c))
            if not s or s["n"] == 0:
                print(f"  [r{r},c{c}] —")
                continue
            print(f"  [r{r},c{c}] N={s['n']:>3}  "
                  f"max μ {s['max_mean']*100:+.2f}% M {s['max_median']*100:+.2f}% "
                  f"[P1 {s['max_p1']*100:+.1f}%, P5 {s['max_p5']*100:+.1f}%, "
                  f"P95 {s['max_p95']*100:+.1f}%, P99 {s['max_p99']*100:+.1f}%]  ||  "
                  f"min μ {s['min_mean']*100:+.2f}% M {s['min_median']*100:+.2f}% "
                  f"[P1 {s['min_p1']*100:+.1f}%, P5 {s['min_p5']*100:+.1f}%, "
                  f"P95 {s['min_p95']*100:+.1f}%, P99 {s['min_p99']*100:+.1f}%]")

    # 全局基线
    print(f"\n全局基线（所有破下轨样本，N={len(max_arr)})")
    print(f"  max_return:  μ {np.mean(max_arr)*100:+.2f}%  "
          f"M {np.median(max_arr)*100:+.2f}%  "
          f"[P1 {np.percentile(max_arr,1)*100:+.1f}%, "
          f"P5 {np.percentile(max_arr,5)*100:+.1f}%, "
          f"P95 {np.percentile(max_arr,95)*100:+.1f}%, "
          f"P99 {np.percentile(max_arr,99)*100:+.1f}%]")
    print(f"  min_return:  μ {np.mean(min_arr)*100:+.2f}%  "
          f"M {np.median(min_arr)*100:+.2f}%  "
          f"[P1 {np.percentile(min_arr,1)*100:+.1f}%, "
          f"P5 {np.percentile(min_arr,5)*100:+.1f}%, "
          f"P95 {np.percentile(min_arr,95)*100:+.1f}%, "
          f"P99 {np.percentile(min_arr,99)*100:+.1f}%]")

    # 画图
    plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "WenQuanYi Zen Hei"]
    plt.rcParams["axes.unicode_minus"] = False
    fig, axes = plt.subplots(1, 2, figsize=(18, 7), constrained_layout=True)

    # 为了 heatmap 统一字段名
    plot_stats_max = {
        k: {"n": v["n"], "mean": v["max_mean"], "median": v["max_median"],
            "p1": v["max_p1"], "p5": v["max_p5"],
            "p95": v["max_p95"], "p99": v["max_p99"]}
        for k, v in grid_stats.items()
    }
    plot_stats_min = {
        k: {"n": v["n"], "mean": v["min_mean"], "median": v["min_median"],
            "p1": v["min_p1"], "p5": v["min_p5"],
            "p95": v["min_p95"], "p99": v["min_p99"]}
        for k, v in grid_stats.items()
    }

    draw_heatmap(axes[0], plot_stats_max, col_ranges, row_ranges, "mean",
                 f"未来 {args.horizon} 日最大涨幅（max high / entry close − 1）",
                 args.pct_window)
    draw_heatmap(axes[1], plot_stats_min, col_ranges, row_ranges, "mean",
                 f"未来 {args.horizon} 日最大跌幅（min low / entry close − 1）",
                 args.pct_window)

    fig.suptitle(
        f"{args.code} close < {args.boll_window}d Boll ±{args.k}σ 下轨 "
        f"× 当日破位深度 / {args.pct_window}日位置 网格"
        f"（{args.n_buckets}×{args.n_buckets}，N={below_df.height}，"
        f"{df['date'].min()} ~ {df['date'].max()}）",
        fontsize=12, fontweight="bold",
    )

    output = args.output or Path(
        f"/mnt/dataset/boll_lower_grid_{args.code}_h{args.horizon}_w{args.pct_window}.png"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output, dpi=130, bbox_inches="tight")
    plt.close(fig)
    print(f"\nSaved to {output}")


if __name__ == "__main__":
    main()
