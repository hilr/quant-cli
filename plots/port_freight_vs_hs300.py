"""港口货物吞吐量（全国港口 + 外贸）12 月滚动合计 / 同比 / 环比 vs 沪深300。

数据源 gov_stat/port_freight.csv（长表，2019 起）。取全国港口（总量）与外贸
两条序列——港口数据为码头过磅称重，计量口径干净。外贸反映出口链条景气，
全国港口反映整体物流。

三 panel：上 = 12 月滚动合计水平（亿吨）；中 = 同比 %；下 = 环比 %。
沪深300 月末收盘叠加于各 panel 右轴。
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import polars as pl

INDICATORS: dict[str, tuple[str, str]] = {
    "全国港口货物吞吐量_当期值(万吨)": ("全国港口", "#1f77b4"),
    "外贸货物吞吐量_当期值(万吨)": ("外贸", "#d62728"),
}


def load_series(csv_file: Path) -> pl.DataFrame:
    df = (pl.read_csv(csv_file)
            .filter(pl.col("indicator").is_in(list(INDICATORS)))
            .with_columns(pl.col("date").str.to_date("%Y-%m"),
                          pl.col("value").cast(pl.Float64)))
    parts = []
    for ind in INDICATORS:
        sub = (df.filter(pl.col("indicator") == ind)
                 .sort("date")
                 .with_columns(pl.col("value").rolling_sum(12).alias("roll12"))
                 .with_columns(
                     ((pl.col("roll12") / pl.col("roll12").shift(12) - 1) * 100).alias("yoy"),
                     ((pl.col("roll12") / pl.col("roll12").shift(1) - 1) * 100).alias("mom"),
                     (pl.col("roll12") / 10000).alias("roll12_yi")))  # 万吨 → 亿吨
        parts.append(sub)
    return pl.concat(parts).sort(["indicator", "date"])


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

    fig, (ax_lv, ax_yoy, ax_mom) = plt.subplots(3, 1, figsize=(13, 12), sharex=True)

    def _draw(ax, col, ylabel, fmt_zero: bool):
        for ind, (lab, color) in INDICATORS.items():
            sub = d.filter(pl.col("indicator") == ind).sort("date")
            ax.plot(sub["date"], sub[col], color=color, lw=1.8,
                    label=f"{lab}吞吐量 {ylabel.split('（')[0]}")
        if fmt_zero:
            ax.axhline(0, color="#444", lw=0.7, ls="--", alpha=0.6)
        ax.set_ylabel(ylabel)
        ax.grid(True, alpha=0.3)
        axr = ax.twinx()
        axr.plot(hs300["date"], hs300["hs300"], color="#2ca02c", lw=0.9, alpha=0.5,
                 label="沪深300 月末收盘（右轴）")
        axr.set_ylabel("沪深300", color="#2ca02c")
        axr.tick_params(axis="y", labelcolor="#2ca02c")
        ll, lnl = ax.get_legend_handles_labels()
        lr, lnr = axr.get_legend_handles_labels()
        ax.legend(ll + lr, lnl + lnr, loc="upper left", fontsize=8.5)

    _draw(ax_lv, "roll12_yi", "12 月滚动合计（亿吨）", False)
    ax_lv.set_title("港口货物吞吐量（全国港口 + 外贸）12 月滚动合计 vs 沪深300")
    _draw(ax_yoy, "yoy", "同比 %", True)
    ax_yoy.set_title("港口货物吞吐量 12 月滚动合计 · 同比")
    _draw(ax_mom, "mom", "环比 %", True)
    ax_mom.set_title("港口货物吞吐量 12 月滚动合计 · 环比")

    dates = (d.filter(pl.col("indicator") == list(INDICATORS)[0])
               .sort("date")["date"].to_list())
    span = dates[-1] - dates[0]
    ax_mom.set_xlim(dates[0], dates[-1] + span * 0.02)
    ax_mom.text(0.99, 0.03, f"最新 {dates[-1].strftime('%Y-%m')}",
                transform=ax_mom.transAxes, ha="right", va="bottom",
                fontsize=10, color="#222", fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#bbb", alpha=0.85))
    ax_mom.xaxis.set_major_locator(mdates.YearLocator(1))
    ax_mom.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    fig.autofmt_xdate()
    plt.tight_layout()
    output_png.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_png, dpi=130)
    plt.close(fig)
    print(f"Saved to {output_png}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv-file", type=Path,
                        default=Path("/mnt/dataset/gov_stat/port_freight.csv"))
    parser.add_argument("--index-file", type=Path,
                        default=Path("/mnt/dataset/index_quote_history/000300.parquet"))
    parser.add_argument("--output", type=Path,
                        default=Path("/mnt/dataset/port_freight_vs_hs300.png"))
    args = parser.parse_args()
    plot(load_series(args.csv_file), load_hs300(args.index_file), args.output)


if __name__ == "__main__":
    main()
