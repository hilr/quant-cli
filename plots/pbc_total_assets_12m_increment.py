"""央行总资产 12 个月滚动增量（流量），叠加沪深300月末收盘（右轴）。

12 个月增量 = [t] − [t−12]，即过去一年央行资产负债表「总资产」净增规模
（万亿元）。正值=扩表，负值=缩表。右轴叠加沪深300，对照央行扩表/缩表
与 A 股走势。

央行扩表有两个阶段：2003-2014 主要靠外汇占款被动投放（买入外汇→资产端
国外资产膨胀），2014 后外汇占款见顶回落，转向主动投放（MLF/PSL/降准/
买卖国债）。

数据源：
- pbc/central_bank_balance_sheet.csv 的 item=「总资产」（月末余额，亿元）
- index_quote_history/000300.parquet（日频 → 月末收盘）
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import polars as pl


def load_assets_12m(balance_file: Path) -> pl.DataFrame:
    """读央行资产负债表「总资产」月末余额，求 12 月滚动增量，换算万亿元。

    2015 年央行文件 item 名带英文后缀「总资产Total」，其余年份为「总资产」，
    两者无月份重叠，一并纳入。
    """
    return (pl.read_csv(balance_file)
              .filter(pl.col("item").is_in(["总资产", "总资产Total"]))
              .group_by("date").agg(pl.col("value").sum().alias("value"))
              .with_columns(pl.col("date").str.to_date("%Y-%m"))
              .sort("date")
              .with_columns(
                  ((pl.col("value") - pl.col("value").shift(12)) / 10000
                   ).alias("assets_12m_增量_万亿"),
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

    fig, ax = plt.subplots(figsize=(13, 6))
    ax.plot(d["date"], d["assets_12m_增量_万亿"], color="#1f77b4", lw=1.8,
            label="央行总资产 12 个月增量（左轴）")
    ax.fill_between(d["date"], 0, d["assets_12m_增量_万亿"], color="#1f77b4", alpha=0.12)
    ax.axhline(0, color="black", lw=0.5)

    axr = ax.twinx()
    axr.plot(hs300["date"], hs300["hs300"], color="#d62728", lw=1.0, alpha=0.7,
             label="沪深300月末收盘（右轴）")

    ax.set_title("央行总资产 12 个月增量 vs 沪深300")
    ax.set_ylabel("万亿元")
    axr.set_ylabel("沪深300收盘点位", color="#d62728")
    axr.tick_params(axis="y", labelcolor="#d62728")
    ax.set_xlim(date(2003, 1, 1), d["date"].max())
    ax.grid(True, alpha=0.3)

    lines_left, labels_left = ax.get_legend_handles_labels()
    lines_right, labels_right = axr.get_legend_handles_labels()
    ax.legend(lines_left + lines_right, labels_left + labels_right, loc="upper left", fontsize=9)

    for x, lab in [(date(2008, 11, 1), "四万亿"),
                   (date(2014, 12, 1), "外汇占款见顶"),
                   (date(2020, 3, 1), "疫情扩表"),
                   (date(2022, 4, 1), "留抵退税"),
                   (date(2024, 8, 1), "国债买卖")]:
        ax.axvline(x, color="#888", lw=0.7, ls="--", alpha=0.6)
        ax.text(x, ax.get_ylim()[1] * 0.96, lab, fontsize=8, color="#555",
                rotation=90, va="top", ha="right")

    ax.xaxis.set_major_locator(mdates.YearLocator(2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    fig.autofmt_xdate()
    plt.tight_layout()
    output_png.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_png, dpi=130)
    plt.close(fig)
    print(f"Saved to {output_png}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--balance-file", type=Path,
        default=Path("/mnt/dataset/pbc/central_bank_balance_sheet.csv"),
        help="pbc/central_bank_balance_sheet.csv 路径",
    )
    parser.add_argument(
        "--index-file", type=Path,
        default=Path("/mnt/dataset/index_quote_history/000300.parquet"),
        help="沪深300 parquet 路径",
    )
    parser.add_argument(
        "--output", type=Path,
        default=Path("/mnt/dataset/pbc_total_assets_12m_increment_vs_hs300.png"),
        help="输出 PNG 路径",
    )
    args = parser.parse_args()
    d = load_assets_12m(args.balance_file)
    hs300 = load_hs300(args.index_file)
    miss = (d.filter(pl.col("assets_12m_增量_万亿").is_null())["date"].to_list())
    if miss:
        print(f"警告：以下月份缺失（shift 头 12 月回溯窗口）：{miss[:6]}{' ...' if len(miss) > 6 else ''}")
    plot(d, hs300, args.output)


if __name__ == "__main__":
    main()
