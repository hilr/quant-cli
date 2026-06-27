"""沪深两市股票数 / 流通市值 / 总市值 / 沪深300（三轴，日频）。

数据源：/mnt/dataset/turnover_concentration.csv（1992 起，无截断）
  - stock_count：当日 turnover > 0 的股票数
  - free_float_market_cap_total / market_cap_total：同口径（turnover>0）股票流通/总市值之和（元）

左轴：股票数（面积，广度）；
右轴：沪深300 收盘（灰淡线，表现）；
右次轴（外偏）：流通市值 + 总市值（万亿元，深度）。
用 --start-date / --end-date 选择查看的时间段。
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import polars as pl


def load_stock_count(csv_path: Path) -> pl.DataFrame:
    return (pl.read_csv(csv_path, columns=[
                "date", "stock_count",
                "free_float_market_cap_total", "market_cap_total"])
            .with_columns(pl.col("date").str.to_date("%Y-%m-%d"))
            .sort("date"))


def load_hs300_close(path: Path) -> pl.DataFrame:
    return (pl.read_parquet(path, columns=["date", "close"])
            .with_columns(pl.col("date").str.to_date("%Y-%m-%d"))
            .sort("date"))


def plot(d: pl.DataFrame, hs300: pl.DataFrame, output: Path) -> None:
    plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "WenQuanYi Zen Hei"]
    plt.rcParams["axes.unicode_minus"] = False

    dates = d["date"].to_list()
    cnt = d["stock_count"].to_list()
    ffmc = [v / 1e12 if v is not None else None
            for v in d["free_float_market_cap_total"].to_list()]  # 万亿元
    tmc = [v / 1e12 if v is not None else None
           for v in d["market_cap_total"].to_list()]  # 万亿元
    hs_dates = hs300["date"].to_list()
    hs_close = hs300["close"].to_list()

    fig, ax = plt.subplots(figsize=(16, 7))
    fig.subplots_adjust(right=0.84)
    axr = ax.twinx()
    axr2 = ax.twinx()
    axr2.spines["right"].set_position(("outward", 64))

    ax.fill_between(dates, 0, cnt, color="#2ca02c", alpha=0.18)
    ax.plot(dates, cnt, color="#2ca02c", lw=0.8, label="股票数（日频）")

    axr.plot(hs_dates, hs_close, color="#888", lw=0.7, alpha=0.55, label="沪深300（右轴）")

    axr2.plot(dates, tmc, color="#9467bd", lw=0.9, alpha=0.75, linestyle="--",
              label="总市值（次右轴）")
    axr2.plot(dates, ffmc, color="#1f77b4", lw=0.9, alpha=0.85,
              label="流通市值（次右轴）")

    ax.set_ylabel("沪深两市股票数（turnover > 0）", color="#2ca02c", fontsize=11)
    ax.tick_params(axis="y", labelcolor="#2ca02c")

    axr.set_ylabel("沪深300 收盘", color="#888", fontsize=10)
    axr.tick_params(axis="y", labelcolor="#888")
    axr.spines["right"].set_color("#bbb")

    axr2.set_ylabel("市值（万亿元）", color="#1f77b4", fontsize=10)
    axr2.tick_params(axis="y", labelcolor="#1f77b4")
    axr2.spines["right"].set_color("#1f77b4")

    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.xaxis.set_minor_locator(mdates.MonthLocator(bymonth=[4, 7, 10]))

    span = dates[-1] - dates[0]
    ax.set_xlim(dates[0], dates[-1] + span * 0.02)

    latest = cnt[-1]
    first = cnt[0]
    peak = d["stock_count"].max()
    peak_d = d.filter(pl.col("stock_count") == peak)["date"][0]
    latest_ffmc = ffmc[-1]
    latest_tmc = tmc[-1]
    ffmc_txt = f"{latest_ffmc:,.1f} 万亿" if latest_ffmc is not None else "—"
    tmc_txt = f"{latest_tmc:,.1f} 万亿" if latest_tmc is not None else "—"
    ax.text(0.99, 0.03,
            f"最新 {dates[-1]}\n股票数 {latest:,}（起始 {first:,}，+{latest-first:,}）\n"
            f"历史峰值 {peak:,} @ {peak_d}\n"
            f"流通市值 {ffmc_txt}  ·  总市值 {tmc_txt}",
            transform=ax.transAxes, ha="right", va="bottom",
            fontsize=10, color="#222", fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.4", fc="white", ec="#bbb", alpha=0.9))

    ax.set_title(
        f"沪深两市股票数 / 流通市值 / 总市值 / 沪深300 · "
        f"{dates[0].strftime('%Y-%m-%d')} ~ {dates[-1].strftime('%Y-%m-%d')}",
        fontsize=13, fontweight="bold")

    lines_l, labels_l = ax.get_legend_handles_labels()
    lines_r, labels_r = axr.get_legend_handles_labels()
    lines_r2, labels_r2 = axr2.get_legend_handles_labels()
    ax.legend(lines_l + lines_r + lines_r2, labels_l + labels_r + labels_r2,
              loc="upper left", fontsize=9, ncol=4)

    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=130, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"Saved to {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-file", type=Path,
                        default=Path("/mnt/dataset/turnover_concentration.csv"))
    parser.add_argument("--hs300-file", type=Path,
                        default=Path("/mnt/dataset/index_quote_history/000300.parquet"))
    parser.add_argument("--output", type=Path,
                        default=Path("/mnt/dataset/market_stock_count.png"))
    parser.add_argument("--start-date", type=str, default="2000-01-01",
                        help="起始日期（默认 2000-01-01；传更早可看 1992 起全历史）")
    parser.add_argument("--end-date", type=str, default=None)
    args = parser.parse_args()

    d = load_stock_count(args.data_file)
    if args.start_date:
        d = d.filter(pl.col("date") >= date.fromisoformat(args.start_date))
    if args.end_date:
        d = d.filter(pl.col("date") <= date.fromisoformat(args.end_date))

    hs300 = load_hs300_close(args.hs300_file)
    if not d.is_empty():
        hs300 = hs300.filter(
            (pl.col("date") >= d["date"].min()) & (pl.col("date") <= d["date"].max()))

    print(f"股票数: {len(d)} 行（{d['date'].min()} ~ {d['date'].max()}）")
    if not d.is_empty():
        print(f"  最新 {d.tail(1)['stock_count'][0]:,}, 最早 {d.head(1)['stock_count'][0]:,}")
        latest_ffmc = d.tail(1)["free_float_market_cap_total"][0]
        if latest_ffmc is not None:
            print(f"  最新流通市值 {latest_ffmc/1e12:.1f} 万亿")
        latest_tmc = d.tail(1)["market_cap_total"][0]
        if latest_tmc is not None:
            print(f"  最新总市值 {latest_tmc/1e12:.1f} 万亿")
    plot(d, hs300, args.output)


if __name__ == "__main__":
    main()
