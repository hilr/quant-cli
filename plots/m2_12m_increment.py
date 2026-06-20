"""M1（老口径）/M2 12 个月滚动新增额（流量），叠加沪深300月末收盘（右轴）。

12 个月新增额 = [t] − [t−12]，即过去一年净增的货币存量（万亿元）。
M2 是广义货币（含定期存款等），M1 是狭义货币（现金 + 活期存款），M1 增速
更能反映企业活化和短期流动性。右轴叠加沪深300，对照货币宽松与 A 股走势。

**M1 用老口径**（2025-01 前定义：现金 + 单位活期存款）：2025-01 前直接用
原始 m1 列（本身就是老口径，2011-2014 亦完整）；2025-01 央行扩 M1 口径
（纳入个人活期存款、非银支付备付金），故 2025-01 起从新口径 m1 减去
credit_funds 的住户活期存款还原老口径（仍含非银备付金，偏高约 +2.5%）。

数据源：
- pbc/money_supply.csv 的 m1/m2 列（月末余额，亿元）
- pbc/credit_funds.csv 的住户活期存款（人民币，亿元）
- index_quote_history/000300.parquet（日频 → 月末收盘）
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import polars as pl


_HOUSEHOLD_DEMAND_ITEMS = [
    "活期储蓄",                        # 1999-01..2006-12
    "储蓄存款·(1)活期储蓄",            # 2007-01..2010-12
    "住户存款·（1）住户活期存款",      # 2015-01..2022-12
    "住户存款·（1）活期存款",          # 2023-01..2026-05
]


def load_money_12m(money_file: Path, credit_file: Path) -> pl.DataFrame:
    """读 M1（老口径）/M2 月末余额，求各自 12 月滚动增量，换算万亿元。

    M1 用老口径（2025-01 前定义：现金 + 单位活期存款）。2025-01 央行扩 M1 口径
    （纳入个人活期存款、非银备付金），故 2025-01 起从新口径 m1 减去住户活期存款
    还原老口径（仍含非银备付金，偏高约 +2.5%，作为系统误差接受）；2025-01 前
    直接用原始 m1 列（本身就是老口径，2011-2014 亦完整）。
    """
    hh = (pl.read_csv(credit_file)
            .filter((pl.col("currency") == "人民币")
                    & pl.col("item").is_in(_HOUSEHOLD_DEMAND_ITEMS))
            .with_columns(pl.col("date").str.to_date("%Y-%m"))
            .group_by("date").agg(pl.col("value").sum().alias("hh_demand"))
            .sort("date"))
    return (pl.read_csv(money_file)
              .with_columns(pl.col("date").str.to_date("%Y-%m"))
              .sort("date")
              .join(hh, on="date", how="left")
              .with_columns(
                  pl.when(pl.col("date") >= pl.date(2025, 1, 1))
                    .then(pl.col("m1") - pl.col("hh_demand"))
                    .otherwise(pl.col("m1"))
                    .alias("m1_old"),
              )
              .with_columns([
                  ((pl.col("m2") - pl.col("m2").shift(12)) / 10000).alias("m2_12m_增量_万亿"),
                  ((pl.col("m1_old") - pl.col("m1_old").shift(12)) / 10000).alias("m1_12m_增量_万亿"),
              ]))


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
    ax.plot(d["date"], d["m2_12m_增量_万亿"], color="#1f77b4", lw=1.8,
            label="M2 12 个月新增额（左轴）")
    ax.fill_between(d["date"], 0, d["m2_12m_增量_万亿"], color="#1f77b4", alpha=0.12)
    ax.plot(d["date"], d["m1_12m_增量_万亿"], color="#ff7f0e", lw=1.6,
            label="M1（老口径）12 个月新增额（左轴）")
    ax.axhline(0, color="black", lw=0.5)

    axr = ax.twinx()
    axr.plot(hs300["date"], hs300["hs300"], color="#d62728", lw=1.0, alpha=0.7,
             label="沪深300月末收盘（右轴）")

    ax.set_title("M1（老口径）/ M2 货币 12 个月新增额 vs 沪深300")
    ax.set_ylabel("万亿元")
    axr.set_ylabel("沪深300收盘点位", color="#d62728")
    axr.tick_params(axis="y", labelcolor="#d62728")
    ax.set_xlim(date(2005, 4, 1), d["date"].max())
    ax.grid(True, alpha=0.3)

    lines_left, labels_left = ax.get_legend_handles_labels()
    lines_right, labels_right = axr.get_legend_handles_labels()
    ax.legend(lines_left + lines_right, labels_left + labels_right, loc="upper left", fontsize=9)

    for x, lab in [(date(2008, 11, 1), "四万亿"),
                   (date(2014, 11, 1), "降息周期"),
                   (date(2020, 3, 1), "疫情冲击"),
                   (date(2022, 4, 1), "居民超额储蓄"),
                   (date(2024, 9, 1), "924 政策")]:
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
        "--money-file", type=Path,
        default=Path("/mnt/dataset/pbc/money_supply.csv"),
        help="pbc/money_supply.csv 路径",
    )
    parser.add_argument(
        "--credit-file", type=Path,
        default=Path("/mnt/dataset/pbc/credit_funds.csv"),
        help="pbc/credit_funds.csv 路径（住户活期存款）",
    )
    parser.add_argument(
        "--index-file", type=Path,
        default=Path("/mnt/dataset/index_quote_history/000300.parquet"),
        help="沪深300 parquet 路径",
    )
    parser.add_argument(
        "--output", type=Path,
        default=Path("/mnt/dataset/m1_m2_12m_increment_vs_hs300.png"),
        help="输出 PNG 路径",
    )
    args = parser.parse_args()
    d = load_money_12m(args.money_file, args.credit_file)
    hs300 = load_hs300(args.index_file)
    miss = (d.filter(pl.col("m1_12m_增量_万亿").is_null() | pl.col("m2_12m_增量_万亿").is_null())
              ["date"].to_list())
    if miss:
        print(f"警告：以下月份缺失（shift 头 12 月回溯窗口）：{miss[:6]}{' ...' if len(miss) > 6 else ''}")
    plot(d, hs300, args.output)


if __name__ == "__main__":
    main()
