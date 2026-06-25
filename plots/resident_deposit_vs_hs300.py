"""住户活期 / 定期存款 12 个月增量 + 定期占比 vs 沪深300。

12 个月增量 = 当月余额 - 12 个月前余额（即滚动一年的净增流量，万亿元）。
比存量更能反映边际存款行为：

  - 定期 12m 增量 ↑ + 活期 12m 增量 ↓/转负 → 居民风险偏好下降
    （存定期锁息、不消费不投资），常对应沪深300 走弱或筑底
  - 活期 12m 增量 转正 / 定期增量回落 → 存款活化，常对应市场回暖

数据源：pbc/credit_funds.csv（人民币口径）。住户存款数据源从 2015-01 起，
12 月回溯再损失头 12 月，故取 2016-01 起。

定期占比 = 定期 / 住户存款合计（存量口径，非增量），反映存款结构性偏好。
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import polars as pl


def load_deposits(credit_file: Path) -> pl.DataFrame:
    """读住户存款各类别人民币月末余额，宽表化 + 12 个月增量。"""
    df = pl.read_csv(credit_file)
    df = (df.filter(pl.col("currency") == "人民币")
            .with_columns(pl.col("date").str.to_date("%Y-%m")))

    def pick(name: str, cond) -> pl.DataFrame:
        return (df.filter(cond)
                  .group_by("date").agg(pl.col("value").sum())
                  .rename({"value": name}))

    d = pick("住户存款合计", pl.col("item") == "1.住户存款")
    for name, cond in [("住户活期", pl.col("item").str.contains("活期")),
                       ("住户定期", pl.col("item").str.contains("定期"))]:
        d = d.join(pick(name, cond), on="date", how="full", coalesce=True)

    return (d.sort("date")
            .drop_nulls("住户存款合计")
            .with_columns([
                (pl.col("住户活期") - pl.col("住户活期").shift(12)).alias("活期_12m增量"),
                (pl.col("住户定期") - pl.col("住户定期").shift(12)).alias("定期_12m增量"),
            ])
            .drop_nulls(["活期_12m增量", "定期_12m增量"]))


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

    dates = d["date"].to_list()
    demand = np.array((d["活期_12m增量"] / 10000).to_list())
    term = np.array((d["定期_12m增量"] / 10000).to_list())

    fig, (ax_top, ax_bot) = plt.subplots(
        2, 1, figsize=(14, 8), sharex=True,
        gridspec_kw={"height_ratios": [1.2, 1.0]},
    )

    # === 上面板：12m 增量堆叠面积（万亿元）+ 沪深300（右轴）===
    ax_top.axhline(0, color="black", lw=0.6, alpha=0.5)
    ax_top.fill_between(dates, 0, term, color="#d62728", alpha=0.65,
                         label="定期 12m 增量（左轴）")
    ax_top.fill_between(dates, term, term + demand,
                         color="#1f77b4", alpha=0.65,
                         label="活期 12m 增量（左轴）")

    axr = ax_top.twinx()
    axr.plot(hs300["date"], hs300["hs300"], color="black", lw=1.4, alpha=0.7, zorder=5,
             label="沪深300月末收盘（右轴）")
    axr.set_ylim(bottom=0)
    axr.set_ylabel("沪深300", fontsize=10)

    ax_top.set_ylabel("万亿元（滚动 12 月净增）", fontsize=10)
    ax_top.set_title(
        "住户人民币存款 12 个月增量：活期 / 定期 vs 沪深300",
        fontsize=12, fontweight="bold", loc="left",
    )

    lines_l, labels_l = ax_top.get_legend_handles_labels()
    lines_r, labels_r = axr.get_legend_handles_labels()
    ax_top.legend(lines_l + lines_r, labels_l + labels_r, loc="upper left", fontsize=9, ncol=2)
    ax_top.grid(True, alpha=0.3)

    # === 下面板：活期 12m 增量 / 定期 12m 增量（比值）===
    flow_ratio = np.where(np.abs(term) > 1e-6, demand / term, np.nan)
    ax_bot.plot(dates, flow_ratio, color="#444", lw=1.4,
                label="活期 12m 增量 / 定期 12m 增量")
    ax_bot.fill_between(dates, 0, flow_ratio, where=flow_ratio > 0,
                         color="#2ca02c", alpha=0.18, interpolate=True)
    ax_bot.fill_between(dates, 0, flow_ratio, where=flow_ratio < 0,
                         color="#d62728", alpha=0.18, interpolate=True)
    ax_bot.axhline(0, color="#888", lw=0.6, alpha=0.5)
    ax_bot.set_ylabel("活期 / 定期（12m 增量比）", fontsize=10)
    ax_bot.grid(True, alpha=0.3)
    ax_bot.legend(loc="upper left", fontsize=9)

    # 事件标注
    for x, lab in [(date(2020, 3, 1), "疫情"),
                   (date(2022, 3, 1), "存款大增"),
                   (date(2024, 9, 1), "924 政策")]:
        ax_bot.axvline(x, color="#888", lw=0.5, ls="--", alpha=0.4)
        ax_bot.text(x, ax_bot.get_ylim()[0] + 1, lab, fontsize=7.5,
                    color="#555", rotation=90, va="bottom", ha="right")

    # 右边距 + 日期标注
    span = dates[-1] - dates[0]
    ax_bot.set_xlim(dates[0], dates[-1] + span * 0.02)
    ax_bot.text(0.99, 0.03, f"最新 {dates[-1]}", transform=ax_bot.transAxes,
                ha="right", va="bottom", fontsize=10, color="#222", fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#bbb", alpha=0.85))
    ax_bot.xaxis.set_major_locator(mdates.YearLocator(2))
    ax_bot.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    fig.autofmt_xdate()

    plt.tight_layout()
    output_png.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_png, dpi=130)
    plt.close(fig)
    print(f"Saved to {output_png}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--credit-file", type=Path,
        default=Path("/mnt/dataset/pbc/credit_funds.csv"),
    )
    parser.add_argument(
        "--index-file", type=Path,
        default=Path("/mnt/dataset/index_quote_history/000300.parquet"),
    )
    parser.add_argument(
        "--output", type=Path,
        default=Path("/mnt/dataset/resident_deposit_12m_increment_vs_hs300.png"),
    )
    args = parser.parse_args()

    d = load_deposits(args.credit_file)
    hs300 = load_hs300(args.index_file)
    dates = d["date"].to_list()
    print(f"住户存款 12m 增量: {dates[0]} ~ {dates[-1]}, {d.height} 行")
    plot(d, hs300, args.output)


if __name__ == "__main__":
    main()
