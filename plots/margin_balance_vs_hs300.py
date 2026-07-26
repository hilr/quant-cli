"""全市场融资余额 / 融券余额 vs 沪深300 三轴图（全部历史，日频）。

数据源：/mnt/dataset/margin_trade_history/{code}.parquet（个股融资融券历史）
按日汇总所有标的的 margin_buy_total（融资余额）与 short_sell_total（融券余额）。

3 条曲线：融资余额（左轴，亿元），融券余额（第三轴，亿元），CSI300 日收盘（右轴）。
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import polars as pl


def load_margin_balance(data_path: Path) -> pl.DataFrame:
    """读所有个股融资/融券余额 parquet，按日汇总求和."""
    dfs = [
        pl.read_parquet(pf, columns=["date", "margin_buy_total", "short_sell_total"])
        for pf in sorted(data_path.glob("*.parquet"))
    ]
    combined = (
        pl.concat(dfs)
        .with_columns(pl.col("date").str.to_date("%Y-%m-%d").alias("d"))
        .group_by("d").agg(
            pl.col("margin_buy_total").sum().alias("balance"),
            pl.col("short_sell_total").sum().alias("short_balance"),
        )
        .sort("d")
    )
    return combined.rename({"d": "date"})


def plot(margin: pl.DataFrame, hs300: pl.DataFrame, output_png: Path) -> None:
    plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "WenQuanYi Zen Hei"]
    plt.rcParams["axes.unicode_minus"] = False

    fig, ax_left = plt.subplots(figsize=(15, 7))
    ax_right = ax_left.twinx()
    ax_third = ax_left.twinx()
    ax_third.spines["right"].set_position(("axes", 1.085))

    dates = margin["date"].to_list()
    balance_yi = (margin["balance"] / 1e8).to_list()
    short_yi = (margin["short_balance"] / 1e8).to_list()
    ax_left.plot(dates, balance_yi, "-", color="#1f77b4", linewidth=0.5,
                 alpha=0.85, label="融资余额 (LHS)")
    ax_third.plot(dates, short_yi, "-", color="#ff7f0e", linewidth=0.5,
                  alpha=0.85, label="融券余额 (3rd)")
    ax_right.plot(hs300["date"].to_list(), hs300["close"].to_list(), "-",
                  color="black", linewidth=0.5, alpha=0.85, label="CSI300 (RHS)")

    ax_left.set_xlabel("Date")
    ax_left.set_ylabel("融资余额 (亿元)", color="#1f77b4")
    ax_right.set_ylabel("CSI300 收盘", color="black")
    ax_third.set_ylabel("融券余额 (亿元)", color="#ff7f0e")
    ax_left.tick_params(axis="y", labelcolor="#1f77b4")
    ax_right.tick_params(axis="y", labelcolor="black")
    ax_third.tick_params(axis="y", labelcolor="#ff7f0e")

    ax_left.set_title(
        f"全市场融资余额 / 融券余额 vs 沪深300（全部历史，日频）"
    )
    ax_left.grid(True, alpha=0.3)
    ax_left.xaxis.set_major_locator(mdates.YearLocator())
    ax_left.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    h1, l1 = ax_left.get_legend_handles_labels()
    h2, l2 = ax_right.get_legend_handles_labels()
    h3, l3 = ax_third.get_legend_handles_labels()
    ax_left.legend(h1 + h2 + h3, l1 + l2 + l3, loc="upper left", fontsize=9)

    span = dates[-1] - dates[0]
    ax_left.set_xlim(dates[0], dates[-1] + span * 0.02)
    latest_bal = balance_yi[-1]
    latest_short = short_yi[-1]
    ax_left.text(0.99, 0.03,
                 f"最新 {dates[-1]}  融资 {latest_bal:.0f} 亿  融券 {latest_short:.1f} 亿",
                 transform=ax_left.transAxes, ha="right", va="bottom",
                 fontsize=10, color="#222", fontweight="bold",
                 bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#bbb", alpha=0.85))

    plt.tight_layout()
    output_png.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_png, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved to {output_png}")
    print(f"融资/融券余额: {margin['date'].min()} ~ {margin['date'].max()}, {margin.height} 行")
    print(f"  最新融资余额: {latest_bal:.0f} 亿  峰值: {margin['balance'].max() / 1e8:.0f} 亿")
    print(f"  最新融券余额: {latest_short:.1f} 亿  峰值: {margin['short_balance'].max() / 1e8:.1f} 亿")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-path", type=Path,
                        default=Path("/mnt/dataset/margin_trade_history"),
                        help="融资融券个股历史目录")
    parser.add_argument("--index-file", type=Path,
                        default=Path("/mnt/dataset/index_quote_history/000300.parquet"),
                        help="沪深300 parquet 文件")
    parser.add_argument("--output", type=Path,
                        default=Path("/mnt/dataset/margin_balance_vs_hs300.png"),
                        help="输出 PNG 路径")
    args = parser.parse_args()

    margin = load_margin_balance(args.data_path)
    hs300 = (pl.read_parquet(args.index_file, columns=["date", "close"])
             .with_columns(pl.col("date").str.to_date("%Y-%m-%d"))
             .sort("date"))
    plot(margin, hs300, args.output)


if __name__ == "__main__":
    main()
