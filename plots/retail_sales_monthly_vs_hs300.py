"""社会消费品零售总额每月新增额（12 月滚动）vs 沪深300。

数据源 gov_stat/retail_sales_monthly.csv（累计值差分得到的当月零售额，亿元），
取「总额」（社会消费品零售总额）。计算 12 个月滚动合计（万亿元）及其同比增速（%），
对照消费与 A 股走势。消费月度季节性强，故用 12 月滚动合计去季节性。
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import polars as pl


def load_monthly(csv_file: Path) -> pl.DataFrame:
    return (pl.read_csv(csv_file)
              .with_columns(
                  pl.col("date").str.to_date("%Y-%m"),
                  pl.col("总额").cast(pl.Float64),
              )
              .sort("date")
              .with_columns(
                  (pl.col("总额").rolling_sum(12) / 10000).alias("总额_12m_万亿"),
              )
              .with_columns(
                  ((pl.col("总额_12m_万亿") / pl.col("总额_12m_万亿").shift(12) - 1) * 100
                   ).alias("总额_12m_同比"),
              ))


def load_hs300(index_file: Path) -> pl.DataFrame:
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

    fig, (ax_lv, ax_yoy) = plt.subplots(2, 1, figsize=(13, 9), sharex=True)

    # 上图：12 月滚动合计水平（万亿元）
    ax_lv.plot(d["date"], d["总额_12m_万亿"], color="#1f77b4", lw=1.8,
               label="零售总额滚动12月合计（左轴）")
    ax_lv.fill_between(d["date"], 0, d["总额_12m_万亿"], color="#1f77b4", alpha=0.10)
    ax_lv.set_ylabel("万亿元")
    ax_lv.set_title("社会消费品零售总额滚动 12 月合计 vs 沪深300")
    ax_lv.grid(True, alpha=0.3)
    axr1 = ax_lv.twinx()
    axr1.plot(hs300["date"], hs300["hs300"], color="#2ca02c", lw=1.0, alpha=0.7,
              label="沪深300月末收盘（右轴）")
    axr1.set_ylabel("沪深300", color="#2ca02c")
    axr1.tick_params(axis="y", labelcolor="#2ca02c")
    ll, lnl = ax_lv.get_legend_handles_labels()
    lr, lnr = axr1.get_legend_handles_labels()
    ax_lv.legend(ll + lr, lnl + lnr, loc="upper left", fontsize=9)

    # 下图：12 月滚动合计的同比增速（%）
    ax_yoy.plot(d["date"], d["总额_12m_同比"], color="#d62728", lw=1.8,
                label="零售总额滚动12月合计同比（左轴）")
    ax_yoy.fill_between(d["date"], 0, d["总额_12m_同比"], where=(d["总额_12m_同比"] >= 0),
                        color="#d62728", alpha=0.10)
    ax_yoy.fill_between(d["date"], 0, d["总额_12m_同比"], where=(d["总额_12m_同比"] < 0),
                        color="#1f77b4", alpha=0.12)
    ax_yoy.axhline(0, color="black", lw=0.5)
    ax_yoy.set_ylabel("同比 %")
    ax_yoy.set_title("零售总额滚动 12 月合计同比 vs 沪深300")
    ax_yoy.grid(True, alpha=0.3)
    axr2 = ax_yoy.twinx()
    axr2.plot(hs300["date"], hs300["hs300"], color="#2ca02c", lw=1.0, alpha=0.7,
              label="沪深300月末收盘（右轴）")
    axr2.set_ylabel("沪深300", color="#2ca02c")
    axr2.tick_params(axis="y", labelcolor="#2ca02c")
    ll2, lnl2 = ax_yoy.get_legend_handles_labels()
    lr2, lnr2 = axr2.get_legend_handles_labels()
    ax_yoy.legend(ll2 + lr2, lnl2 + lnr2, loc="upper left", fontsize=9)

    ax_yoy.set_xlim(date(2007, 1, 1), d["date"].max())
    ax_yoy.xaxis.set_major_locator(mdates.YearLocator(2))
    ax_yoy.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
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
        default=Path("/mnt/dataset/gov_stat/retail_sales_monthly.csv"),
        help="retail_sales_monthly.csv 路径",
    )
    parser.add_argument(
        "--index-file", type=Path,
        default=Path("/mnt/dataset/index_quote_history/000300.parquet"),
        help="沪深300 parquet 路径",
    )
    parser.add_argument(
        "--output", type=Path,
        default=Path("/mnt/dataset/retail_sales_monthly_vs_hs300.png"),
        help="输出 PNG 路径",
    )
    args = parser.parse_args()
    d = load_monthly(args.csv_file)
    hs300 = load_hs300(args.index_file)
    plot(d, hs300, args.output)


if __name__ == "__main__":
    main()



def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--csv-file", type=Path,
        default=Path("/mnt/dataset/gov_stat/retail_sales_monthly.csv"),
        help="retail_sales_monthly.csv 路径",
    )
    parser.add_argument(
        "--index-file", type=Path,
        default=Path("/mnt/dataset/index_quote_history/000300.parquet"),
        help="沪深300 parquet 路径",
    )
    parser.add_argument(
        "--output", type=Path,
        default=Path("/mnt/dataset/retail_sales_monthly_vs_hs300.png"),
        help="输出 PNG 路径",
    )
    args = parser.parse_args()
    d = load_monthly(args.csv_file)
    hs300 = load_hs300(args.index_file)
    plot(d, hs300, args.output)


if __name__ == "__main__":
    main()
