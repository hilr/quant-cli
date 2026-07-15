"""剔除股价影响的月度流通市值变化（正/负/净）vs 沪深300。

数据源：/mnt/dataset/new_float_market_cap.csv（日频，正/负/净分列）
  - float_market_cap_increase：正项合计（IPO/限售解禁/增发/配股，从股市拿钱）
  - float_market_cap_decrease：负项合计（现金分红/回购注销，向股市发钱）
  - new_float_market_cap：净额 = increase + decrease

按月汇总，左轴：
  - 绿柱向上 = increase（市场扩容）
  - 红柱向下 = decrease（现金回报）
  - 黑实线 = 净额
右轴：沪深300 月末收盘（灰淡线）。

口径说明见 docs/datasets/new_float_market_cap.md。
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import polars as pl


def load_monthly(csv_path: Path) -> pl.DataFrame:
    """读日频数据，按月汇总 increase/decrease/净额，返回月度宽表。"""
    return (pl.read_csv(csv_path, try_parse_dates=True)
              .filter(pl.col("date") >= pl.date(2005, 1, 1))  # 去掉 2004-12-31 占位行
              .with_columns(pl.col("date").dt.strftime("%Y-%m").alias("ym"))
              .group_by("ym").agg(
                  pl.col("float_market_cap_increase").sum().alias("increase"),
                  pl.col("float_market_cap_decrease").sum().alias("decrease"),
                  pl.col("new_float_market_cap").sum().alias("net"),
                  pl.col("date").min().alias("month_start"))
              .sort("month_start")
              .with_columns(pl.col("month_start").dt.offset_by("1mo").dt.offset_by("-1d")
                              .alias("month_end"))
              .with_columns(
                  (pl.col("increase") / 1e12).alias("increase_t"),
                  (pl.col("decrease") / 1e12).alias("decrease_t"),
                  (pl.col("net") / 1e12).alias("net_t")))


def load_hs300_monthly(index_file: Path) -> pl.DataFrame:
    return (pl.read_parquet(index_file, columns=["date", "close"])
              .with_columns(pl.col("date").str.to_date("%Y-%m-%d").alias("d"))
              .sort("d")
              .group_by(pl.col("d").dt.strftime("%Y-%m").alias("ym"))
              .agg(pl.col("close").last().alias("hs300"),
                   pl.col("d").max().alias("month_end"))
              .sort("month_end"))


def plot(monthly: pl.DataFrame, hs300: pl.DataFrame, output: Path) -> None:
    plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "WenQuanYi Zen Hei"]
    plt.rcParams["axes.unicode_minus"] = False

    months = monthly["month_end"].to_list()
    inc = monthly["increase_t"].to_list()
    dec = monthly["decrease_t"].to_list()
    net = monthly["net_t"].to_list()
    hs_months = hs300["month_end"].to_list()
    hs_close = hs300["hs300"].to_list()

    fig, ax = plt.subplots(figsize=(16, 7))
    fig.subplots_adjust(right=0.89)
    axr = ax.twinx()
    axr.spines["right"].set_position(("outward", 60))

    width = 24.0  # 月柱宽（天）

    ax.bar(months, inc, width=width, color="#2ca02c", alpha=0.75,
           label="扩容（IPO/解禁/增发/配股）", align="center", linewidth=0)
    ax.bar(months, dec, width=width, color="#d62728", alpha=0.75,
           label="现金回报（分红/回购）", align="center", linewidth=0)
    ax.plot(months, net, color="#222", lw=0.9, alpha=0.85,
            label="净额（扩容 + 回报）")

    axr.plot(hs_months, hs_close, color="#888", lw=0.8, alpha=0.55,
             label="沪深300 月末收盘（次右轴）")

    ax.axhline(0, color="black", lw=0.5, alpha=0.5)

    ax.set_ylabel("月度流通市值变化（剔除股价，万亿元）", fontsize=11)
    axr.set_ylabel("沪深300 收盘", color="#888", fontsize=10)
    axr.tick_params(axis="y", labelcolor="#888")
    axr.spines["right"].set_color("#bbb")

    ax.grid(True, alpha=0.3, axis="y")
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.xaxis.set_minor_locator(mdates.MonthLocator(bymonth=[4, 7, 10]))

    span = months[-1] - months[0]
    ax.set_xlim(months[0] - span * 0.01, months[-1] + span * 0.03)

    peak_inc_i = monthly["increase"].arg_max()
    peak_dec_i = monthly["decrease"].arg_min()
    peak_inc_d = monthly["month_end"][peak_inc_i]
    peak_inc_v = monthly["increase_t"][peak_inc_i]
    peak_dec_d = monthly["month_end"][peak_dec_i]
    peak_dec_v = monthly["decrease_t"][peak_dec_i]
    last_net = net[-1]

    ax.annotate(f"{peak_inc_d.strftime('%Y-%m')} +{peak_inc_v:.2f} 万亿",
                xy=(peak_inc_d, peak_inc_v), xytext=(8, 6),
                textcoords="offset points", fontsize=8, color="#2ca02c",
                arrowprops=dict(arrowstyle="-", color="#2ca02c", lw=0.5, alpha=0.7))
    ax.annotate(f"{peak_dec_d.strftime('%Y-%m')} {peak_dec_v:.2f} 万亿",
                xy=(peak_dec_d, peak_dec_v), xytext=(8, -10),
                textcoords="offset points", fontsize=8, color="#d62728",
                arrowprops=dict(arrowstyle="-", color="#d62728", lw=0.5, alpha=0.7))

    ytd_inc = monthly.filter(
        pl.col("month_end").dt.year() == months[-1].year)["increase"].sum() / 1e12
    ytd_dec = monthly.filter(
        pl.col("month_end").dt.year() == months[-1].year)["decrease"].sum() / 1e12

    ax.text(0.99, 0.03,
            f"最新 {months[-1].strftime('%Y-%m')}\n"
            f"净额 {last_net:+.2f} 万亿\n"
            f"今年累计 扩容 {ytd_inc:+.2f} / 回报 {ytd_dec:+.2f} 万亿",
            transform=ax.transAxes, ha="right", va="bottom",
            fontsize=10, color="#222", fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.4", fc="white", ec="#bbb", alpha=0.9))

    ax.set_title(
        f"剔除股价影响的月度流通市值变化 vs 沪深300 · "
        f"{months[0].strftime('%Y-%m')} ~ {months[-1].strftime('%Y-%m')}",
        fontsize=13, fontweight="bold")

    lines_l, labels_l = ax.get_legend_handles_labels()
    lines_r, labels_r = axr.get_legend_handles_labels()
    ax.legend(lines_l + lines_r, labels_l + labels_r,
              loc="upper left", fontsize=9, ncol=5)

    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=130, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"Saved to {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-file", type=Path,
                        default=Path("/mnt/dataset/new_float_market_cap.csv"))
    parser.add_argument("--hs300-file", type=Path,
                        default=Path("/mnt/dataset/index_quote_history/000300.parquet"))
    parser.add_argument("--output", type=Path,
                        default=Path("/mnt/dataset/new_float_market_cap.png"))
    parser.add_argument("--start-date", type=str, default="2005-01-01",
                        help="起始日期（默认 2005-01-01；数据集本身从 2004-12-31 起）")
    parser.add_argument("--end-date", type=str, default=None)
    args = parser.parse_args()

    monthly = load_monthly(args.data_file)
    if args.start_date:
        monthly = monthly.filter(pl.col("month_end") >= date.fromisoformat(args.start_date))
    if args.end_date:
        monthly = monthly.filter(pl.col("month_end") <= date.fromisoformat(args.end_date))

    hs300 = load_hs300_monthly(args.hs300_file)
    if not monthly.is_empty():
        hs300 = hs300.filter(
            (pl.col("month_end") >= monthly["month_end"].min())
            & (pl.col("month_end") <= monthly["month_end"].max()))

    print(f"月度数据: {monthly.height} 行（{monthly['month_end'].min()} ~ {monthly['month_end'].max()}）")
    if not monthly.is_empty():
        peak_inc_i = monthly["increase"].arg_max()
        peak_dec_i = monthly["decrease"].arg_min()
        print(f"  扩容峰值 {monthly['month_end'][peak_inc_i]}: +{monthly['increase_t'][peak_inc_i]:.2f} 万亿")
        print(f"  回报峰值 {monthly['month_end'][peak_dec_i]}: {monthly['decrease_t'][peak_dec_i]:.2f} 万亿")
        print(f"  最新净额: {monthly['net_t'][-1]:+.2f} 万亿")
    plot(monthly, hs300, args.output)


if __name__ == "__main__":
    main()
