"""对每个 zigzag 段统计日收益率分布（均值/标准差/年化波动率/偏度/峰度/夏普）。

输入：/mnt/dataset/csi300_regime/zigzag_t15_segments.csv
      /mnt/dataset/index_quote_history/000300.parquet
输出：每个段一行的统计表，并按 bull/bear 汇总。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl
from scipy import stats

SEG_CSV = Path("/mnt/dataset/csi300_regime/zigzag_t15_segments.csv")
PRICE_PARQUET = Path("/mnt/dataset/index_quote_history/000300.parquet")


def main() -> None:
    seg = pl.read_csv(SEG_CSV, try_parse_dates=True)
    px = (
        pl.read_parquet(PRICE_PARQUET)
        .with_columns(pl.col("date").str.to_date("%Y-%m-%d"))
        .sort("date")
        .with_columns((pl.col("close") / pl.col("close").shift(1) - 1).alias("ret"))
    )
    closes = px["close"].to_list()
    rets = px["ret"].to_list()
    dates = px["date"].to_list()
    date_idx = {d: i for i, d in enumerate(dates)}

    rows = []
    for r in seg.iter_rows(named=True):
        i1 = date_idx[r["start_date"]]
        i2 = date_idx[r["end_date"]]
        seg_rets = np.array(
            [x for x in rets[i1 + 1 : i2 + 1] if x is not None],
            dtype=float,
        )
        if len(seg_rets) < 5:
            continue
        n = len(seg_rets)
        mean = float(seg_rets.mean())
        std = float(seg_rets.std(ddof=1))
        ann_vol = std * np.sqrt(252)
        sharpe = mean / std * np.sqrt(252) if std > 0 else float("nan")
        rows.append(
            {
                "seg_id": r["seg_id"],
                "start_date": r["start_date"],
                "end_date": r["end_date"],
                "label": r["label"],
                "leg_return": r["leg_return"],
                "n_days": n,
                "daily_mean_pct": mean * 100,
                "daily_std_pct": std * 100,
                "ann_vol_pct": ann_vol * 100,
                "skew": float(stats.skew(seg_rets)),
                "kurt": float(stats.kurtosis(seg_rets)),
                "sharpe_ann": sharpe,
                "max_day_pct": float(seg_rets.max()) * 100,
                "min_day_pct": float(seg_rets.min()) * 100,
            }
        )

    out = pl.DataFrame(rows)
    out_csv = Path("/mnt/dataset/csi300_regime/zigzag_t15_segment_stats.csv")
    out.write_csv(out_csv)
    print(f"Saved per-segment stats to {out_csv}  ({len(out)} rows)\n")

    pl.Config.set_tbl_rows(60)
    pl.Config.set_tbl_cols(20)
    pl.Config.set_fmt_str_lengths(50)
    print("=== 每段日收益率分布 ===")
    header = (
        f"  {'seg':>3} {'start':<12}{'end':<12}{'lab':<5}{'leg':>8}"
        f"{'n':>5}{'mean%':>8}{'std%':>7}{'annV%':>7}{'skew':>7}{'kurt':>7}"
        f"{'Sharpe':>8}{'max%':>8}{'min%':>8}"
    )
    print(header)
    print("  " + "-" * (len(header) - 2))
    for r in out.iter_rows(named=True):
        print(
            f"  {r['seg_id']:>3} {str(r['start_date']):<12}{str(r['end_date']):<12}{r['label']:<5}"
            f"{r['leg_return']*100:+7.1f}%{r['n_days']:>5}"
            f"{r['daily_mean_pct']:>+8.3f}{r['daily_std_pct']:>7.2f}{r['ann_vol_pct']:>7.1f}"
            f"{r['skew']:>+7.2f}{r['kurt']:>+7.2f}{r['sharpe_ann']:>+8.2f}"
            f"{r['max_day_pct']:>+8.2f}{r['min_day_pct']:>+8.2f}"
        )

    print("\n=== 按 label 汇总（均值） ===")
    agg = (
        out.group_by("label")
        .agg(
            pl.len().alias("n_seg"),
            pl.col("n_days").mean().round(0).alias("avg_days"),
            pl.col("leg_return").mean().alias("avg_leg_ret"),
            pl.col("daily_mean_pct").mean().alias("avg_daily_mean"),
            pl.col("daily_std_pct").mean().alias("avg_daily_std"),
            pl.col("ann_vol_pct").mean().alias("avg_ann_vol"),
            pl.col("skew").mean().alias("avg_skew"),
            pl.col("kurt").mean().alias("avg_kurt"),
            pl.col("sharpe_ann").mean().alias("avg_sharpe"),
        )
        .sort("label")
    )
    print(agg)


if __name__ == "__main__":
    main()
