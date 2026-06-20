"""外资持有境内人民币金融资产 12 个月新增额（股票/债券）vs 沪深300。

数据源 overseas_rmb_assets 拆成股票、债券两项，分别求 12 月新增额
（= 存量[t] − 存量[t−12]，亿元，换算万亿元）。正值=外资净增持，负值=外资
净减持。各子图右轴叠加沪深300，对照外资进出与 A 股走势。

数据源：
- pbc/overseas_rmb_assets.csv（月末存量，亿元）
- index_quote_history/000300.parquet（日频 → 月末收盘）
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import polars as pl


def load_overseas_12m(csv_file: Path) -> pl.DataFrame:
    """读外资持有境内人民币金融资产，股票/债券分别求 12 月新增额（万亿元）。"""
    return (pl.read_csv(csv_file)
              .with_columns(pl.col("date").str.to_date("%Y-%m"))
              .sort("date")
              .with_columns(
                  ((pl.col("股票") - pl.col("股票").shift(12)) / 10000
                   ).alias("股票_12m_增量_万亿"),
                  ((pl.col("债券") - pl.col("债券").shift(12)) / 10000
                   ).alias("债券_12m_增量_万亿"),
              ))


def load_hs300(index_file: Path) -> pl.DataFrame:
    """读沪深300日频收盘，重采样为月末收盘（对齐月度宏观数据）。"""
    return (pl.read_parquet(index_file, columns=["date", "close"])
              .with_columns(pl.col("date").str.to_date("%Y-%m-%d").alias("d"))
              .sort("d")
              .group_by(pl.col("d").dt.strftime("%Y-%m").alias("date"))
              .agg(pl.col("close").last().alias("hs300"))
              .with_columns(pl.col("date").str.to_date("%Y-%m"))
              .sort("date"))


def plot(d: pl.DataFrame, hs300: pl.DataFrame, output_png: Path) -> None:
    plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "WenQuanYi Zen Hei"]
    plt.rcParams["axes.unicode_minus"] = False

    fig, (ax_stock, ax_bond) = plt.subplots(2, 1, figsize=(13, 9), sharex=True)
    panels = [
        (ax_stock, "股票_12m_增量_万亿", "外资持有境内股票", "#1f77b4"),
        (ax_bond, "债券_12m_增量_万亿", "外资持有境内债券", "#2ca02c"),
    ]
    events = [(date(2014, 11, 1), "沪港通"),
              (date(2017, 1, 1), "外资大流入"),
              (date(2020, 3, 1), "疫情冲击"),
              (date(2022, 3, 1), "美联储加息"),
              (date(2024, 9, 1), "924 政策")]

    for idx, (ax, col, label, color) in enumerate(panels):
        ax.plot(d["date"], d[col], color=color, lw=1.8,
                label=f"{label} 12 个月新增额（左轴）")
        ax.fill_between(d["date"], 0, d[col], color=color, alpha=0.12)
        ax.axhline(0, color="black", lw=0.5)

        axr = ax.twinx()
        axr.plot(hs300["date"], hs300["hs300"], color="#d62728", lw=1.0, alpha=0.7,
                 label="沪深300月末收盘（右轴）")
        axr.set_ylabel("沪深300", color="#d62728")
        axr.tick_params(axis="y", labelcolor="#d62728")

        ax.set_ylabel("万亿元")
        ax.set_title(f"{label} 12 个月新增额 vs 沪深300")
        ax.grid(True, alpha=0.3)

        for x, lab in events:
            ax.axvline(x, color="#888", lw=0.7, ls="--", alpha=0.6)
            if idx == 0:
                ax.text(x, ax.get_ylim()[1] * 0.96, lab, fontsize=8, color="#555",
                        rotation=90, va="top", ha="right")

        lines_l, labels_l = ax.get_legend_handles_labels()
        lines_r, labels_r = axr.get_legend_handles_labels()
        ax.legend(lines_l + lines_r, labels_l + labels_r, loc="upper left", fontsize=9)

    ax_bond.set_xlim(date(2015, 1, 1), d["date"].max())
    ax_bond.xaxis.set_major_locator(mdates.YearLocator(1))
    ax_bond.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    fig.autofmt_xdate()
    plt.tight_layout()
    output_png.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_png, dpi=130)
    plt.close(fig)
    print(f"Saved to {output_png}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--csv-file", type=Path,
        default=Path("/mnt/dataset/pbc/overseas_rmb_assets.csv"),
        help="pbc/overseas_rmb_assets.csv 路径",
    )
    parser.add_argument(
        "--index-file", type=Path,
        default=Path("/mnt/dataset/index_quote_history/000300.parquet"),
        help="沪深300 parquet 路径",
    )
    parser.add_argument(
        "--output", type=Path,
        default=Path("/mnt/dataset/overseas_rmb_assets_12m_increment_vs_hs300.png"),
        help="输出 PNG 路径",
    )
    args = parser.parse_args()
    d = load_overseas_12m(args.csv_file)
    hs300 = load_hs300(args.index_file)
    miss = d.filter(pl.col("股票_12m_增量_万亿").is_null())["date"].to_list()
    if miss:
        print(f"警告：以下月份缺失（shift 头 12 月回溯窗口）：{miss[:6]}{' ...' if len(miss) > 6 else ''}")
    plot(d, hs300, args.output)


if __name__ == "__main__":
    main()
