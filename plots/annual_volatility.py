"""沪深300 每年年化波动率 + 与指数走势对照。

年化波动率（close-to-close realized vol）= 每日对数收益率 std × √(trading_days)，
按日历年分组。附滚动 N 日年化波动率，对照价格走势。
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import polars as pl


def load_index(index_dir: Path, code: str) -> pl.DataFrame:
    return (
        pl.read_parquet(
            index_dir / f"{code}.parquet", columns=["date", "close"]
        )
        .with_columns(pl.col("date").str.to_date("%Y-%m-%d"))
        .sort("date")
    )


def annual_vol(df: pl.DataFrame, trading_days: int) -> pl.DataFrame:
    """按日历年分组的年化波动率。"""
    d = df.with_columns(
        pl.col("close").log().diff().alias("log_ret"),
        pl.col("date").dt.year().alias("year"),
    )
    return (
        d.group_by("year")
        .agg(
            pl.col("log_ret").std(ddof=1).alias("daily_std"),
            pl.col("date").count().alias("n_days"),
            pl.col("date").min().alias("first"),
            pl.col("date").max().alias("last"),
        )
        .sort("year")
        .with_columns(
            (pl.col("daily_std") * (trading_days**0.5)).alias("ann_vol"),
        )
    )


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--index-dir", type=Path,
                   default=Path("/mnt/dataset/index_quote_history"))
    p.add_argument("--code", default="000300")
    p.add_argument("--trading-days", type=int, default=252,
                   help="年化因子（每年交易日数）")
    p.add_argument("--roll-window", type=int, default=20,
                   help="滚动波动率窗口（交易日）")
    p.add_argument("--output", type=Path, default=None,
                   help="输出 PNG 路径（不指定则只打印表格）")
    args = p.parse_args()

    df = load_index(args.index_dir, args.code)
    dates = df["date"].to_list()
    closes = df["close"].to_list()

    per_year = annual_vol(df, args.trading_days)

    # 滚动年化波动率
    daily = df.with_columns(pl.col("close").log().diff().alias("log_ret"))
    daily = daily.with_columns(
        (pl.col("log_ret").rolling_std(window_size=args.roll_window)
         * (args.trading_days**0.5)).alias("roll_vol")
    )
    roll_dates = daily["date"].to_list()
    roll_vols = daily["roll_vol"].to_list()

    print(f"\n=== 沪深300 每年年化波动率（√{args.trading_days}）===")
    print(f"数据区间: {dates[0]} ~ {dates[-1]}（{len(dates)} 个交易日）")
    print(f"\n{'年':>6} {'年化波动率':>10} {'日均波动':>9} {'交易日':>6}  {'区间'}")
    print("-" * 62)
    for r in per_year.iter_rows(named=True):
        print(f"{r['year']:>6} {r['ann_vol']*100:>9.2f}% "
              f"{r['daily_std']*100:>8.3f}% {r['n_days']:>6}  "
              f"{r['first']}~{r['last']}")

    vols = per_year["ann_vol"].to_numpy() * 100
    full_years = per_year.filter(pl.col("n_days") >= 200)
    full_vols = full_years["ann_vol"].to_numpy() * 100
    print(f"\n统计（全部 {len(per_year)} 年）:")
    print(f"  均值: {vols.mean():.2f}%  中位: {np.median(vols):.2f}%")
    print(f"  最高: {per_year.row(per_year['ann_vol'].arg_max(), named=True)['year']}年 "
          f"{vols.max():.2f}%")
    print(f"  最低: {per_year.row(per_year['ann_vol'].arg_min(), named=True)['year']}年 "
          f"{vols.min():.2f}%")
    print(f"  完整年份（≥200 交易日，{len(full_years)} 年）均值: "
          f"{full_vols.mean():.2f}%  中位: {np.median(full_vols):.2f}%")

    if not args.output:
        return

    plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "WenQuanYi Zen Hei"]
    plt.rcParams["axes.unicode_minus"] = False

    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(14, 8), sharex=True,
        gridspec_kw={"height_ratios": [1.0, 0.8]},
        constrained_layout=True,
    )

    # 上：价格
    ax1.plot(dates, closes, color="#444", lw=0.7, label="沪深300收盘")
    ax1.set_ylabel("收盘价")
    ax1.set_title(f"沪深300 收盘价 vs 年化波动率（√{args.trading_days}）",
                  fontsize=11, fontweight="bold", loc="left")
    ax1.grid(True, alpha=0.3)
    ax1.legend(loc="upper left", fontsize=8)

    # 下：年化波动率（每年阶梯）+ 滚动波动率 + 均值线
    nan = float("nan")
    roll_v = [v if v is not None else nan for v in roll_vols]
    ax2.plot(roll_dates, [v * 100 for v in roll_v],
             color="#ff7f0e", lw=0.5, alpha=0.45,
             label=f"滚动{args.roll_window}日年化波动率")

    daily_vol = (
        daily.with_columns(pl.col("date").dt.year().alias("year"))
        .join(per_year.select("year", "ann_vol"), on="year")
    )
    ax2.step(daily_vol["date"].to_list(),
             (daily_vol["ann_vol"].to_numpy() * 100),
             where="post", color="#1f77b4", lw=2.0,
             label="每年年化波动率")

    mean_line = float(vols.mean())
    ax2.axhline(mean_line, color="#d62728", lw=1.0, ls="--", alpha=0.7,
                label=f"全期均值 {mean_line:.1f}%")

    ax2.set_ylabel("年化波动率 (%)")
    ax2.set_xlabel("年份")
    ax2.set_title("年化波动率（阶梯=每年，橙线=滚动，红虚=均值）",
                  fontsize=11, fontweight="bold", loc="left")
    ax2.grid(True, alpha=0.3)
    ax2.legend(loc="upper left", fontsize=8)
    ax2.xaxis.set_major_locator(plt.matplotlib.dates.YearLocator())
    ax2.xaxis.set_major_formatter(plt.matplotlib.dates.DateFormatter("%Y"))

    output = args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"\n图: {output}")


if __name__ == "__main__":
    main()
