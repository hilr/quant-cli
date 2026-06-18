"""对比三种阈值配置在 CSI300 上的入场信号质量。

配置：
1. fixed_k15    : 固定 k=1.5（当前默认）
2. fixed_emp    : 固定 k=2.57（全历史经验 α=1%）
3. per_regime   : 按 regime 分（bull 2.25 / bear 2.87，各自经验 α=1%）

regime 标签来自 zigzag 切分（hindsight，结果为上界估计）。
入场：z_obs = (close-MA120)/σ120 ≤ -k
评价：60 日前瞻收益、相对入场价的最大跌幅。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl

SEG_CSV = Path("/mnt/dataset/csi300_regime/zigzag_t15_segments.csv")
PRICE_PARQUET = Path("/mnt/dataset/index_quote_history/000300.parquet")
WINDOW = 120
FWD = 60

K_FIXED_15 = 1.5
K_FIXED_EMP = 2.57  # 全历史经验 α=1%
K_BULL = 2.25       # bull 段合并经验 α=1%
K_BEAR = 2.87       # bear 段合并经验 α=1%


def load_data() -> pl.DataFrame:
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
    seg = pl.read_csv(SEG_CSV, try_parse_dates=True)
    # 给每一天打 regime 标签（用 segment 区间 join）
    df = df.with_columns(pl.lit(None).cast(pl.Utf8).alias("regime"))
    dates = df["date"].to_list()
    date_to_idx = {d: i for i, d in enumerate(dates)}
    regimes: list[str | None] = [None] * len(dates)
    for r in seg.iter_rows(named=True):
        i1 = date_to_idx[r["start_date"]]
        i2 = date_to_idx[r["end_date"]]
        for i in range(i1, i2 + 1):
            regimes[i] = r["label"]
    df = df.with_columns(pl.Series("regime", regimes))
    return df


def eval_entries(df: pl.DataFrame, k_per_row: list[float], name: str) -> dict:
    """k_per_row[i] 是第 i 行使用的 k（正数）。入场 = z_obs <= -k。"""
    closes = df["close"].to_list()
    z_obs = df["z_obs"].to_list()
    n = len(df)
    entries = []
    for i in range(n):
        z = z_obs[i]
        k = k_per_row[i]
        if z is None or k is None:
            continue
        if z <= -k:
            j_end = min(i + FWD, n - 1)
            if i + FWD >= n:
                continue
            r = closes[j_end] / closes[i] - 1
            seg = closes[i : j_end + 1]
            mdd = 0.0
            for c in seg:
                dd = c / closes[i] - 1
                if dd < mdd:
                    mdd = dd
            entries.append({"date": df["date"][i], "price": closes[i], "ret": r, "mdd": mdd})

    if not entries:
        return {"name": name, "n": 0}
    rets = np.array([e["ret"] for e in entries])
    mdds = np.array([e["mdd"] for e in entries])
    win = (rets > 0).sum()
    return {
        "name": name,
        "n": len(entries),
        "win": win,
        "win_rate": win / len(entries),
        "mean_ret": float(rets.mean()),
        "med_ret": float(np.median(rets)),
        "mean_mdd": float(mdds.mean()),
        "worst_mdd": float(mdds.min()),
    }


def main() -> None:
    df = load_data()
    df = df.filter(pl.col("z_obs").is_not_null() & pl.col("regime").is_not_null())
    regimes = df["regime"].to_list()

    # 三个方法的 per-row k
    k_fixed_15 = [K_FIXED_15] * len(df)
    k_fixed_emp = [K_FIXED_EMP] * len(df)
    k_per_regime = [K_BULL if r == "bull" else K_BEAR for r in regimes]

    results = [
        eval_entries(df, k_fixed_15, "fixed_k15 (current)"),
        eval_entries(df, k_fixed_emp, "fixed_emp (whole-history 1%)"),
        eval_entries(df, k_per_regime, "per_regime (bull 2.25 / bear 2.87)"),
    ]

    print(
        f"{'method':<32}{'signals':>9}{'win':>7}{'win%':>8}"
        f"{'mean ret':>11}{'med ret':>10}{'mean mdd':>10}{'worst':>9}"
    )
    print("-" * 96)
    for r in results:
        if r["n"] == 0:
            print(f"  {r['name']:<30}{'0':>9}")
            continue
        print(
            f"  {r['name']:<30}{r['n']:>9}{r['win']:>7}{r['win_rate']*100:>7.1f}%"
            f"{r['mean_ret']*100:>+10.2f}%{r['med_ret']*100:>+9.2f}%"
            f"{r['mean_mdd']*100:>+9.2f}%{r['worst_mdd']*100:>+8.2f}%"
        )

    # 进一步：per-regime 拆开看入场分布
    print("\n=== per_regime 方法在 bull / bear 段分别触发了多少 ===")
    bull_entries = sum(
        1
        for i, r in enumerate(regimes)
        if r == "bull"
        and df["z_obs"][i] is not None
        and df["z_obs"][i] <= -K_BULL
    )
    bear_entries = sum(
        1
        for i, r in enumerate(regimes)
        if r == "bear"
        and df["z_obs"][i] is not None
        and df["z_obs"][i] <= -K_BEAR
    )
    bull_days = sum(1 for r in regimes if r == "bull")
    bear_days = sum(1 for r in regimes if r == "bear")
    print(f"  bull: {bull_entries:>4} 信号 / {bull_days} 天 ({bull_entries/bull_days*100:.2f}%)")
    print(f"  bear: {bear_entries:>4} 信号 / {bear_days} 天 ({bear_entries/bear_days*100:.2f}%)")


if __name__ == "__main__":
    main()
