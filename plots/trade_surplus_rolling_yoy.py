"""进出口顺差：滚动 12 个月合计及其同比。

滚 12 合计 = 当月及前 11 个月的顺差（出口-进口，差额当期值）之和，平滑月度波动；
同比 = 滚12[t] / 滚12[t-12] - 1。

早期（2005 年前后）同比出现数百 % 的尖峰并非数据错误：2004→2005 中国贸易
顺差历史性暴增（全年 328→1021 亿美元），源于 2005 年全球纺织品配额取消、
入世过渡期结束、人民币 7 月汇改前抢出口。2000-2004 顺差盘子小（全年仅
230-330 亿），进一步放大了同比波动。故同比图从 2003 年起、y 轴裁到 [-60, 130]。
数据源 gov_stat/trade.csv 的 1-2 月合并缺口已由 convert 补全（合计平分）。
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import polars as pl


def load_surplus_rolling_yoy(trade_file: Path) -> pl.DataFrame:
    """读 trade.csv 的进出口差额当期值，补齐月历，算滚 12 合计（亿美元）及同比（%）。"""
    df = pl.read_csv(trade_file)
    d = (df.filter(pl.col("indicator") == "进出口差额当期值(千美元)")
           .with_columns(pl.col("date").str.to_date("%Y-%m"))
           .select("date", "value").sort("date"))
    full = pl.DataFrame({"date": pl.date_range(d["date"].min(), d["date"].max(), "1mo", eager=True)})
    d = full.join(d, on="date", how="left")
    d = d.with_columns(
        (pl.col("value").rolling_sum(window_size=12, min_samples=12) / 100000).alias("roll12_亿美元"))
    d = d.with_columns(
        (((pl.col("roll12_亿美元") / pl.col("roll12_亿美元").shift(12)) - 1) * 100).alias("同比%"))
    return d


def plot(d: pl.DataFrame, output_png: Path) -> None:
    plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "WenQuanYi Zen Hei"]
    plt.rcParams["axes.unicode_minus"] = False

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 8), sharex=True,
                                    gridspec_kw={"height_ratios": [1, 1.6]})

    ax1.plot(d["date"], d["roll12_亿美元"], color="#1f77b4", lw=1.2)
    ax1.fill_between(d["date"], 0, d["roll12_亿美元"], color="#1f77b4", alpha=0.12)
    ax1.set_ylabel("滚动12个月顺差合计（亿美元）")
    ax1.set_title("中国进出口顺差：滚动12个月合计及其同比")
    ax1.grid(True, alpha=0.3)

    ax2.plot(d["date"], d["同比%"], color="#d62728", lw=1.2)
    ax2.axhline(0, color="black", lw=0.6)
    ax2.fill_between(d["date"], 0, d["同比%"], where=d["同比%"] >= 0,
                     color="#d62728", alpha=0.15, interpolate=True)
    ax2.fill_between(d["date"], 0, d["同比%"], where=d["同比%"] < 0,
                     color="#1f77b4", alpha=0.15, interpolate=True)
    ax2.set_ylabel("滚12顺差合计 同比（%）")
    ax2.set_xlim(date(2003, 1, 1), d["date"].max())
    ax2.set_ylim(-60, 130)
    ax2.grid(True, alpha=0.3)
    for x, lab in [(date(2008, 9, 1), "金融危机"), (date(2018, 7, 1), "贸易战"),
                   (date(2020, 3, 1), "疫情"), (date(2024, 11, 1), "特朗普关税")]:
        ax2.axvline(x, color="#888", lw=0.7, ls="--", alpha=0.6)
        ax2.text(x, 122, lab, fontsize=8, color="#555", rotation=90, va="top", ha="right")

    ax2.xaxis.set_major_locator(mdates.YearLocator(2))
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    fig.autofmt_xdate()
    plt.tight_layout()
    output_png.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_png, dpi=130)
    plt.close(fig)
    print(f"Saved to {output_png}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--trade-file", type=Path,
        default=Path("/mnt/dataset/gov_stat/trade.csv"),
        help="gov_stat/trade.csv 路径（默认 /mnt/dataset/gov_stat/trade.csv）",
    )
    parser.add_argument(
        "--output", type=Path,
        default=Path("/mnt/dataset/trade_surplus_rolling12_yoy.png"),
        help="输出 PNG 路径",
    )
    args = parser.parse_args()
    d = load_surplus_rolling_yoy(args.trade_file)
    plot(d, args.output)


if __name__ == "__main__":
    main()
