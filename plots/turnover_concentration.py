"""A 股日成交额集中度（5 算法）vs 沪深300。

读 /mnt/dataset/turnover_concentration.csv（由 quant.cli turnover-concentration 生成）
+ /mnt/dataset/index_quote_history/000300.parquet。

5 个算法各占一个子图，垂直堆叠，共享 x 轴：
  - Gini        基尼系数（0-1，整体不均度）
  - Pareto α    log-log rank-amount 回归斜率绝对值（越小 = 尾部越厚）
  - Top5/median top5 均值 / 全样本中位数（头部相对虹吸）
  - HHI         成交额份额平方和（平方放大头部）
  - CR10        top10 成交额占比

每个子图右轴叠加沪深300（绿色淡线），看集中度与大盘的相关性。
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import polars as pl


METRICS = [
    ("gini", "Gini 基尼系数", "整体不均度（0=完全均等，1=完全集中）", "#1f77b4"),
    ("alpha", "Pareto α", "log-log 回归斜率（越小 = 尾部越厚）", "#9467bd"),
    ("top5_ratio", "Top5 / 中位数", "头部相对虹吸（越大 = 头部越突出）", "#ff7f0e"),
    ("hhi", "HHI", "成交额份额平方和（平方放大头部）", "#d62728"),
    ("cr10", "CR10", "top10 成交额占比", "#2ca02c"),
]


def load_concentration(path: Path) -> pl.DataFrame:
    return (pl.read_csv(path)
             .with_columns(pl.col("date").str.to_date("%Y-%m-%d"))
             .sort("date"))


def load_hs300(path: Path) -> pl.DataFrame:
    return (pl.read_parquet(path, columns=["date", "close"])
              .with_columns(pl.col("date").str.to_date("%Y-%m-%d"))
              .sort("date"))


def plot(d: pl.DataFrame, hs300: pl.DataFrame, output: Path) -> None:
    plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "WenQuanYi Zen Hei"]
    plt.rcParams["axes.unicode_minus"] = False

    dates = d["date"].to_list()
    hs_dates = hs300["date"].to_list()
    hs_close = hs300["close"].to_list()

    fig, axes = plt.subplots(len(METRICS), 1, figsize=(14, 16),
                             sharex=True, constrained_layout=True)

    for ax, (col, title, desc, color) in zip(axes, METRICS):
        y = d[col].to_list()
        ax.plot(dates, y, color=color, lw=0.9, label=col)
        ax.fill_between(dates, min(y) if y else 0, y, color=color, alpha=0.10)
        ax.set_ylabel(title, color=color, fontsize=10)
        ax.tick_params(axis="y", labelcolor=color)
        ax.set_title(f"{title} — {desc}", fontsize=10, loc="left")
        ax.grid(True, alpha=0.3)

        axr = ax.twinx()
        axr.plot(hs_dates, hs_close, color="#888", lw=0.7, alpha=0.55, label="沪深300")
        axr.set_ylabel("沪深300", color="#888", fontsize=9)
        axr.tick_params(axis="y", labelcolor="#888")
        axr.spines["right"].set_color("#bbb")

    span = dates[-1] - dates[0]
    axes[-1].set_xlim(dates[0], dates[-1] + span * 0.02)
    axes[-1].text(0.99, 0.03, f"最新 {dates[-1]}", transform=axes[-1].transAxes,
                  ha="right", va="bottom", fontsize=10, color="#222", fontweight="bold",
                  bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#bbb", alpha=0.85))
    axes[-1].xaxis.set_major_locator(mdates.YearLocator())
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    axes[-1].xaxis.set_minor_locator(mdates.MonthLocator(bymonth=[4, 7, 10]))

    fig.suptitle(
        f"A 股日成交额集中度（5 算法）vs 沪深300 · "
        f"{dates[0].strftime('%Y-%m-%d')} ~ {dates[-1].strftime('%Y-%m-%d')}",
        fontsize=13, fontweight="bold",
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=130, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"Saved to {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-file", type=Path,
                        default=Path("/mnt/dataset/turnover_concentration.csv"))
    parser.add_argument("--index-file", type=Path,
                        default=Path("/mnt/dataset/index_quote_history/000300.parquet"))
    parser.add_argument("--output", type=Path,
                        default=Path("/mnt/dataset/turnover_concentration.png"))
    parser.add_argument("--start-date", type=str, default=None,
                        help="起始日期 YYYY-MM-DD")
    parser.add_argument("--end-date", type=str, default=None,
                        help="结束日期 YYYY-MM-DD")
    args = parser.parse_args()

    d = load_concentration(args.data_file)
    if args.start_date:
        d = d.filter(pl.col("date") >= date.fromisoformat(args.start_date))
    if args.end_date:
        d = d.filter(pl.col("date") <= date.fromisoformat(args.end_date))
    hs300 = load_hs300(args.index_file)
    print(f"集中度: {len(d)} 行（{d['date'].min()} ~ {d['date'].max()}）")
    print(f"沪深300: {len(hs300)} 行")
    plot(d, hs300, args.output)


if __name__ == "__main__":
    main()
