"""沪深两融融资余额滚动 N 个月净增长 vs 沪深300 双轴图。

数据源：/mnt/readonly_dataset/eastmoney/margin_trade_total_history/{bse,sse,szse}/{year}.csv.gz
将 bse/sse/sze 三个交易所的 margin_buy_total（融资余额）按日汇总求和，取每个月最后一个交易日，
然后对月度序列做 N 个月差分（balance[M] - balance[M-N]），得到滚动 N 个月的净增长额。

3 条曲线：滚动 3M / 6M / 12M 净增长（左轴，亿元），CSI300 月末收盘（右轴）。
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import polars as pl
from matplotlib.transforms import blended_transform_factory

WINDOWS = [1]
COLORS = {1: "#1f77b4"}


def load_margin_monthly(data_path: Path) -> pl.DataFrame:
    """读所有交易所所有年份的 gz，按日汇总融资余额，再取月度末值."""
    src = data_path / "eastmoney" / "margin_trade_total_history"
    dfs = []
    for ex in ("bse", "sse", "szse"):
        ex_dir = src / ex
        if not ex_dir.exists():
            continue
        for gz in sorted(ex_dir.glob("*.csv.gz")):
            df = pl.read_csv(gz, infer_schema_length=10000)
            if "margin_buy_total" not in df.columns:
                continue
            dfs.append(df.select(["date", "margin_buy_total"]))

    combined = (
        pl.concat(dfs)
        .with_columns(pl.col("date").str.to_date("%Y-%m-%d").alias("d"))
        .group_by("d").agg(pl.col("margin_buy_total").sum().alias("balance"))
        .sort("d")
    )

    # 取每个月最后一个交易日
    monthly = (
        combined.with_columns(pl.col("d").dt.strftime("%Y-%m").alias("ym"))
        .sort("d")
        .group_by("ym").agg(
            pl.col("balance").last(),
            pl.col("d").last().alias("date"),
        )
        .sort("date")
        .drop("ym")
    )
    return monthly


def load_hs300_monthly(index_file: Path) -> pl.DataFrame:
    """沪深300 月末收盘."""
    return (
        pl.read_parquet(index_file, columns=["date", "close"])
        .with_columns(pl.col("date").str.to_date("%Y-%m-%d").alias("d"))
        .sort("d")
        .with_columns(pl.col("d").dt.strftime("%Y-%m").alias("ym"))
        .group_by("ym").agg(
            pl.col("close").last(),
            pl.col("d").last().alias("date"),
        )
        .sort("date")
        .drop("ym")
    )


def plot(margin: pl.DataFrame, hs300: pl.DataFrame, output_png: Path) -> None:
    # 计算 N 个月净增长额（亿元）
    for n in WINDOWS:
        margin = margin.with_columns(
            ((pl.col("balance") - pl.col("balance").shift(n)) / 1e8).alias(f"chg_{n}m")
        )

    # CSI300 也对齐到月度，限制到最近 5 年
    margin_start = margin["date"].max().replace(year=margin["date"].max().year - 5)
    margin = margin.filter(pl.col("date") >= margin_start)
    hs300 = hs300.filter(pl.col("date") >= margin_start)

    fig, ax_left = plt.subplots(figsize=(15, 7))
    ax_right = ax_left.twinx()

    ax_left.axhline(0, color="gray", linewidth=0.5, alpha=0.5)

    lines = []
    for n in WINDOWS:
        dates = margin["date"].to_list()
        vals = margin[f"chg_{n}m"].to_list()
        line, = ax_left.plot(
            dates, vals, "-",
            color=COLORS[n], linewidth=0.9, alpha=0.85,
            label=f"{n}M net change (LHS)",
        )
        lines.append(line)

    line_hs300, = ax_right.plot(
        hs300["date"].to_list(), hs300["close"].to_list(), "-",
        color="black", linewidth=0.9, alpha=0.85, label="CSI300 monthly close (RHS)",
    )

    trans = blended_transform_factory(ax_left.transData, ax_left.transAxes)
    events = [
        (date(2022, 4, 1), "2022 lockdown"),
        (date(2022, 10, 1), "2022 reopen"),
        (date(2024, 2, 1), "2024 small-cap crash"),
        (date(2024, 9, 1), "2024 policy pivot"),
    ]
    d_min, d_max = margin["date"].min(), margin["date"].max()
    for d, label in events:
        if not (d_min <= d <= d_max):
            continue
        ax_left.axvline(d, color="purple", linestyle="--", linewidth=0.4, alpha=0.35)
        ax_left.text(
            d, 0.03, f" {label}", color="purple", fontsize=8,
            rotation=90, va="bottom", transform=trans,
        )

    ax_left.set_xlabel("Date (month-end)")
    ax_left.set_ylabel("Margin balance net change (100M CNY)", color="black")
    ax_right.set_ylabel("CSI300 close (CNY)", color="black")
    ax_right.tick_params(axis="y", labelcolor="black")

    ax_left.set_title(
        "Margin Balance (sum of bse/sse/sze) Rolling Net Change vs CSI300\n"
        "Monthly end-of-month value; change = balance[M] - balance[M-N]"
    )
    ax_left.grid(True, alpha=0.3)
    ax_left.xaxis.set_major_locator(mdates.MonthLocator(interval=6))
    ax_left.xaxis.set_minor_locator(mdates.MonthLocator())
    ax_left.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    plt.setp(ax_left.get_xticklabels(), rotation=45, ha="right")

    ax_left.legend(handles=lines + [line_hs300], loc="upper left", fontsize=9, ncol=2)

    plt.tight_layout()
    output_png.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_png, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved to {output_png}")

    # 摘要
    print(f"\nMargin balance monthly: {margin['date'].min()} ~ {margin['date'].max()}, {margin.height} rows")
    print(f"  latest balance: {margin['balance'][-1] / 1e8:.0f} 亿")
    print(f"  peak balance:   {margin['balance'].max() / 1e8:.0f} 亿 at {margin.filter(pl.col('balance') == margin['balance'].max())['date'][0]}")
    print(f"\n最近一期各窗口净增长：")
    latest = margin.tail(1)
    for n in WINDOWS:
        v = latest[f"chg_{n}m"][0]
        print(f"  {n}M: {v:+.0f} 亿" if v is not None else f"  {n}M: null")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-path", type=Path,
        default=Path("/mnt/readonly_dataset"),
        help="只读原始数据根目录",
    )
    parser.add_argument(
        "--index-file", type=Path,
        default=Path("/mnt/dataset/index_quote_history/000300.parquet"),
        help="沪深300 parquet 文件",
    )
    parser.add_argument(
        "--output", type=Path,
        default=Path("/mnt/dataset/margin_balance_change_vs_hs300.png"),
        help="输出 PNG 路径",
    )
    args = parser.parse_args()

    margin = load_margin_monthly(args.data_path)
    hs300 = load_hs300_monthly(args.index_file)
    plot(margin, hs300, args.output)


if __name__ == "__main__":
    main()
