"""N 日窗口收益率 P 分位极端事件的时间分布分析。

对每个标的、每个窗口长度，把历史上所有「≤ Pq 分位」的窗口挑出来，
按"窗口结束日"所在月份聚合，回答：

> 「历史上极端的 N 日跌幅（或涨幅）都发生在什么时段？是否高度集中在
>   某几次危机？」
>
> 同时打印当前最新窗口收益对应的经验百分位，便于把当前行情放进历史坐标。

口径与 window_return_distribution 一致：
- 用前复权 close（或指数原始 close）算 close[t]/close[t-N] - 1。
- 滚动重叠窗口（step=1）：用足数据，但相邻样本高度自相关，
  统计推断要谨慎。
- Pq 用 numpy.percentile 线性插值；"≤ Pq" 用严格 ≤ 把约 N×q% 个窗口圈进来。
"""
from __future__ import annotations

import argparse
from pathlib import Path

import polars as pl


DEFAULT_INDICES = [
    ("000300", "沪深300"),
    ("000905", "中证500"),
    ("000852", "中证1000"),
    ("399006", "创业板指"),
    ("000688", "科创50"),
]


def load_close(adjusted_dir: Path, code: str) -> pl.DataFrame:
    return (
        pl.read_parquet(adjusted_dir / f"{code}.parquet", columns=["date", "close"])
        .with_columns(pl.col("date").str.to_date("%Y-%m-%d"))
        .sort("date")
    )


def window_returns(df: pl.DataFrame, window: int) -> pl.DataFrame:
    return df.with_columns(
        (pl.col("close") / pl.col("close").shift(window) - 1).alias("ret")
    ).drop_nulls("ret")


def analyse(
    adjusted_dir: Path,
    code: str,
    name: str,
    window: int,
    percentile: float,
    direction: str,
) -> dict:
    """返回一个标的在某窗口下的 P 分位极端事件分布。"""
    df = window_returns(load_close(adjusted_dir, code), window)
    r = df["ret"].to_numpy()
    q = float(percentile) if direction == "lower" else float(100 - percentile)

    if direction == "lower":
        threshold = float(__import__("numpy").percentile(r, percentile))
        extreme = df.filter(pl.col("ret") <= threshold)
    else:
        threshold = float(__import__("numpy").percentile(r, 100 - percentile))
        extreme = df.filter(pl.col("ret") >= threshold)

    by_month = (
        extreme.with_columns(pl.col("date").dt.strftime("%Y-%m").alias("ym"))
        .group_by("ym")
        .len()
        .sort("ym")
    )
    current_ret = float(df["ret"].tail(1)[0])
    current_rank = float(
        (df["ret"] <= current_ret).sum() / df.height * 100
    )
    return {
        "code": code,
        "name": name,
        "window": window,
        "threshold": threshold,
        "n_extreme": extreme.height,
        "n_total": df.height,
        "by_month": by_month,
        "current_ret": current_ret,
        "current_rank": current_rank,
        "first_date": df["date"].to_list()[0],
        "last_date": df["date"].to_list()[-1],
    }


def print_result(res: dict, percentile: float, direction: str) -> None:
    thr = res["threshold"] * 100
    cur = res["current_ret"] * 100
    q_label = f"P{percentile:g}（左尾）" if direction == "lower" else f"P{100 - percentile:g}（右尾）"
    print(f"\n[{res['name']} {res['code']}]  窗口 {res['window']} 日  "
          f"{q_label}阈值 = {thr:+.2f}%,  极端窗口数 = {res['n_extreme']}/{res['n_total']}")
    print(f"  当前 {res['window']}d 收益 {cur:+.2f}%（p={res['current_rank']:.1f}%），"
          f"区间 {res['first_date']} ~ {res['last_date']}")
    print(f"  按月聚集（按时间序）：")
    for row in res["by_month"].iter_rows(named=True):
        print(f"    {row['ym']}  {row['len']:>3} 个")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--adjusted-dir", type=Path,
        default=Path("/mnt/dataset/index_quote_history"),
        help="含 {code}.parquet 的行情目录",
    )
    p.add_argument(
        "--window", type=int, nargs="+", default=[5, 10, 20],
        help="窗口长度（交易日），可传多个，默认 5 10 20",
    )
    p.add_argument(
        "--percentile", type=float, default=1.0,
        help="分位阈值（0-100），默认 1，即 P1",
    )
    p.add_argument(
        "--direction", choices=["lower", "upper"], default="lower",
        help="lower=左尾（极端跌），upper=右尾（极端涨）",
    )
    p.add_argument(
        "--codes", nargs="*", default=None,
        help="覆盖默认 5 个指数，传 'code:name' 形式，如 '000300:沪深300'",
    )
    args = p.parse_args()

    if args.codes:
        indices = []
        for item in args.codes:
            if ":" in item:
                c, n = item.split(":", 1)
                indices.append((c, n))
            else:
                indices.append((item, item))
    else:
        indices = DEFAULT_INDICES

    label = "左尾（极端跌）" if args.direction == "lower" else "右尾（极端涨）"
    print(f"\n{'=' * 70}")
    print(f"{label} P{args.percentile:g} 极端事件的时间分布")
    print(f"窗口 = {args.window}，标的 = {[c for c, _ in indices]}")
    print('=' * 70)

    for window in args.window:
        print(f"\n{'─' * 70}\n窗口 = {window} 日\n{'─' * 70}")
        for code, name in indices:
            try:
                res = analyse(
                    args.adjusted_dir, code, name, window,
                    args.percentile, args.direction,
                )
                print_result(res, args.percentile, args.direction)
            except FileNotFoundError:
                print(f"\n[{name} {code}] 文件不存在：{args.adjusted_dir / f'{code}.parquet'}")


if __name__ == "__main__":
    main()
