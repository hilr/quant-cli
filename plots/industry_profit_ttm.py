"""工业企业利润 TTM 环比 vs 沪深300 双轴图。

TTM[M] / TTM[M-1] - 1 等价于 (profit[M] - profit[M-12]) / TTM[M-1]：
本月利润比一年前同月多/少了多少，相对整个滚动 12 个月和的占比。

2007/2008/2009 的 12 月源数据缺失，用同年 11 月的当月值补上（仅用于本图连续性），
原始数据集 gov_stat/industry_profit 的对应月份仍为 null。
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import polars as pl
from matplotlib.transforms import blended_transform_factory


def load_ttm_mom(profit_dir: Path) -> pl.DataFrame:
    """读入 industry_profit 月度数据，填充 2007-2009 的 12 月，计算 TTM 及其环比."""
    dfs = [pl.read_csv(f) for f in sorted(profit_dir.glob("*.csv"))]
    return (
        pl.concat(dfs)
        .with_columns(
            pl.col("year").cast(pl.Int32),
            pl.col("month").cast(pl.Int32),
            pl.date("year", "month", pl.lit(1)).alias("date"),
        )
        .sort("date")
        .with_columns(
            pl.when(
                pl.col("year").is_in([2007, 2008, 2009])
                & (pl.col("month") == 12)
                & pl.col("profit").is_null()
            )
            .then(pl.col("profit").shift(1))
            .otherwise(pl.col("profit"))
            .alias("profit")
        )
        .with_columns(
            pl.col("profit").rolling_sum(window_size=12, min_samples=12).alias("ttm")
        )
        .with_columns(
            (pl.col("ttm") / pl.col("ttm").shift(1) - 1).alias("ttm_mom")
        )
    )


def load_hs300(index_file: Path) -> pl.DataFrame:
    return (
        pl.read_parquet(index_file, columns=["date", "close"])
        .with_columns(pl.col("date").str.to_date("%Y-%m-%d").alias("d"))
        .sort("d")
    )


def plot(profit: pl.DataFrame, hs300: pl.DataFrame, output_png: Path) -> None:
    fig, ax_left = plt.subplots(figsize=(15, 7))
    ax_right = ax_left.twinx()

    ax_left.axvspan(date(2007, 1, 1), date(2009, 12, 31), color="#ff7f0e", alpha=0.06)
    ax_left.axhline(0, color="gray", linewidth=0.5, alpha=0.5)

    mom_dates = profit["date"].to_list()
    mom_vals = [None if v is None else v * 100 for v in profit["ttm_mom"].to_list()]
    line_profit, = ax_left.plot(
        mom_dates, mom_vals, "-",
        color="#1f77b4", linewidth=1.8, label="TTM MoM (LHS)",
    )
    line_hs300, = ax_right.plot(
        hs300["d"].to_list(), hs300["close"].to_list(), "-",
        color="#d62728", linewidth=0.7, alpha=0.6, label="CSI300 close (RHS)",
    )

    trans = blended_transform_factory(ax_left.transData, ax_left.transAxes)
    events = [
        (date(2008, 11, 1), "2008 crisis"),
        (date(2015, 6, 1), "2015 bubble"),
        (date(2020, 3, 1), "2020 COVID"),
        (date(2022, 4, 1), "2022 lockdown"),
    ]
    for d, label in events:
        ax_left.axvline(d, color="purple", linestyle="--", linewidth=0.4, alpha=0.35)
        ax_left.text(
            d, 0.03, f" {label}", color="purple", fontsize=8,
            rotation=90, va="bottom", transform=trans,
        )

    ax_left.set_xlabel("Date")
    ax_left.set_ylabel("TTM MoM change (%)", color="black")
    ax_right.set_ylabel("CSI300 close (CNY)", color="#d62728")
    ax_right.tick_params(axis="y", labelcolor="#d62728")

    ax_left.set_title(
        "Industrial Profit TTM MoM Change vs CSI300\n"
        "TTM[M] / TTM[M-1] - 1 = (profit[M] - profit[M-12]) / TTM[M-1]"
    )
    ax_left.grid(True, alpha=0.3)
    ax_left.xaxis.set_major_locator(mdates.YearLocator(2))
    ax_left.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    ax_left.legend(
        handles=[
            line_profit, line_hs300,
            mpatches.Patch(
                color="#ff7f0e", alpha=0.3,
                label="2007-2009 estimate window (Dec filled with Nov)",
            ),
        ],
        loc="upper left", fontsize=9,
    )

    span = mom_dates[-1] - mom_dates[0]
    ax_left.set_xlim(mom_dates[0], mom_dates[-1] + span * 0.02)
    ax_left.text(0.99, 0.03, f"最新 {mom_dates[-1]}", transform=ax_left.transAxes,
                 ha="right", va="bottom", fontsize=10, color="#222", fontweight="bold",
                 bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#bbb", alpha=0.85))

    plt.tight_layout()
    output_png.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_png, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved to {output_png}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profit-dir", type=Path,
        default=Path("/mnt/dataset/gov_stat/industry_profit"),
        help="industry_profit 月度数据目录（默认 /mnt/dataset/gov_stat/industry_profit）",
    )
    parser.add_argument(
        "--index-file", type=Path,
        default=Path("/mnt/dataset/index_quote_history/000300.parquet"),
        help="沪深300 parquet 文件（默认 000300.parquet）",
    )
    parser.add_argument(
        "--output", type=Path,
        default=Path("/mnt/dataset/industry_profit_ttm_change_vs_hs300.png"),
        help="输出 PNG 路径",
    )
    args = parser.parse_args()

    profit = load_ttm_mom(args.profit_dir)
    hs300 = load_hs300(args.index_file)
    plot(profit, hs300, args.output)


if __name__ == "__main__":
    main()
