"""把 z_obs = (close-MA120)/σ120 按 zigzag 牛熊段切开，看分布差异。

输出：
1. 每段的 z_obs 分布统计（mean/std/skew/kurt/quantiles）
2. 按 bull/bear 汇总
3. 各 regime 的 α=1% 经验分位（看阈值差异有多大）
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl
from scipy import stats

SEG_CSV = Path("/mnt/dataset/csi300_regime/zigzag_t15_segments.csv")
PRICE_PARQUET = Path("/mnt/dataset/index_quote_history/000300.parquet")
WINDOW = 120


def main() -> None:
    seg = pl.read_csv(SEG_CSV, try_parse_dates=True)
    df = (
        pl.read_parquet(PRICE_PARQUET)
        .with_columns(pl.col("date").str.to_date("%Y-%m-%d"))
        .sort("date")
        .with_columns(
            pl.col("close").rolling_mean(WINDOW).alias("ma"),
            pl.col("close").rolling_std(WINDOW).alias("sigma"),
        )
        .with_columns(((pl.col("close") - pl.col("ma")) / pl.col("sigma")).alias("z_obs"))
    )
    date_to_idx = {d: i for i, d in enumerate(df["date"].to_list())}
    z_full = df["z_obs"].to_numpy()
    dates_full = df["date"].to_list()

    # 每段统计
    rows = []
    for r in seg.iter_rows(named=True):
        i1 = date_to_idx[r["start_date"]]
        i2 = date_to_idx[r["end_date"]]
        z = z_full[i1 : i2 + 1]
        z = z[~np.isnan(z)]
        if len(z) < 10:
            continue
        rows.append(
            {
                "seg_id": r["seg_id"],
                "start_date": r["start_date"],
                "end_date": r["end_date"],
                "label": r["label"],
                "n": len(z),
                "mean": float(z.mean()),
                "std": float(z.std(ddof=1)),
                "skew": float(stats.skew(z)),
                "kurt": float(stats.kurtosis(z)),
                "q01": float(np.quantile(z, 0.01)),
                "q05": float(np.quantile(z, 0.05)),
                "q50": float(np.quantile(z, 0.50)),
                "q95": float(np.quantile(z, 0.95)),
                "min": float(z.min()),
            }
        )
    out = pl.DataFrame(rows)
    csv_path = Path("/mnt/dataset/csi300_regime/zobs_by_segment.csv")
    out.write_csv(csv_path)
    print(f"Saved per-segment z_obs stats to {csv_path}  ({len(out)} rows)\n")

    print("=== 每段 z_obs 分布（按 label 排序） ===")
    header = (
        f"  {'seg':>3} {'start':<12}{'end':<12}{'lab':<5}{'n':>5}"
        f"{'mean':>7}{'std':>6}{'skew':>7}{'kurt':>7}"
        f"{'q01':>7}{'q05':>7}{'q50':>7}{'min':>7}"
    )
    print(header)
    print("  " + "-" * (len(header) - 2))
    for r in sorted(rows, key=lambda x: (x["label"], x["seg_id"])):
        print(
            f"  {r['seg_id']:>3} {str(r['start_date']):<12}{str(r['end_date']):<12}"
            f"{r['label']:<5}{r['n']:>5}"
            f"{r['mean']:>+7.2f}{r['std']:>6.2f}{r['skew']:>+7.2f}{r['kurt']:>+7.2f}"
            f"{r['q01']:>+7.2f}{r['q05']:>+7.2f}{r['q50']:>+7.2f}{r['min']:>+7.2f}"
        )

    print("\n=== 按 label 汇总 ===")
    agg = (
        out.group_by("label")
        .agg(
            pl.len().alias("n_seg"),
            pl.col("n").sum().alias("n_days"),
            pl.col("mean").mean().round(3).alias("avg_mean"),
            pl.col("std").mean().round(3).alias("avg_std"),
            pl.col("skew").mean().round(3).alias("avg_skew"),
            pl.col("kurt").mean().round(3).alias("avg_kurt"),
            pl.col("q01").mean().round(3).alias("avg_q01"),
            pl.col("q05").mean().round(3).alias("avg_q05"),
            pl.col("q50").mean().round(3).alias("avg_q50"),
        )
        .sort("label")
    )
    print(agg)

    # 直接合并所有 bull / bear 段的 z_obs，算"真"汇总分布
    print("\n=== 合并所有同 label 段的 z_obs（按整体分布算分位） ===")
    for label in ["bull", "bear"]:
        idxs = []
        for r in seg.iter_rows(named=True):
            if r["label"] != label:
                continue
            i1 = date_to_idx[r["start_date"]]
            i2 = date_to_idx[r["end_date"]]
            idxs.extend(range(i1, i2 + 1))
        z = z_full[idxs]
        z = z[~np.isnan(z)]
        print(
            f"\n  {label} (n={len(z)}): mean={z.mean():+.3f}  std={z.std(ddof=1):.3f}  "
            f"skew={stats.skew(z):+.3f}  kurt={stats.kurtosis(z):+.3f}"
        )
        print(
            f"    分位 q01/q05/q25/q50/q75/q95/q99 = "
            + " / ".join(f"{q:+.2f}" for q in np.quantile(z, [0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99]))
        )
        print(
            f"    α=1% 阈值（左尾）: {np.quantile(z, 0.01):+.3f}σ  "
            f"vs 全历史 {np.quantile(z_full[~np.isnan(z_full)], 0.01):+.3f}σ"
        )


if __name__ == "__main__":
    main()
