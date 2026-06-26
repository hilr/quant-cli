"""历史回撤水下曲线 + 前复权价格（上下两栏）。

基金/指数/股票通用：只要 --adjusted-dir 指向含 {code}.parquet 的 OHLC 行情目录即可。
峰值 = 截至当日为止的历史最高价（cummax(high)）；
回撤 = 当日最低价 / 历史最高价 - 1。
前复权价格可避免分红制造假回撤（指数无分红则无需前复权）。
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import polars as pl

# 标注深度阈值（回撤深于该值的谷值会标日期 + 幅度）
ANNOT_THRESHOLD = -0.15


def load_quote(adjusted_dir: Path, code: str, start_date: date | None = None) -> pl.DataFrame:
    df = (
        pl.read_parquet(adjusted_dir / f"{code}.parquet")
        .with_columns(pl.col("date").str.to_date("%Y-%m-%d"))
        .sort("date")
    )
    if start_date is not None:
        df = df.filter(pl.col("date") >= start_date)
    df = (
        df.with_columns(pl.col("high").cum_max().alias("peak_high"))
        .with_columns((pl.col("low") / pl.col("peak_high") - 1).alias("dd"))
    )
    return df


def find_troughs(df: pl.DataFrame, threshold: float) -> list[tuple]:
    """按历史新高分段，取每段最深谷值；返回深于 threshold 的 (date, depth) 列表。"""
    dates = df["date"].to_list()
    highs = df["high"].to_list()
    lows = df["low"].to_list()
    peak_high = df["peak_high"].to_list()
    prev_peak = [None] + peak_high[:-1]

    troughs = []
    cur_lo_idx = 0
    for i in range(len(dates)):
        is_start = (i == 0) or (prev_peak[i] is not None and highs[i] > prev_peak[i])
        if is_start and i != 0:
            depth = lows[cur_lo_idx] / highs[0] - 1  # placeholder, recomputed below
            d = lows[cur_lo_idx] / df["peak_high"].to_list()[cur_lo_idx] - 1
            if d <= threshold:
                troughs.append((dates[cur_lo_idx], d))
            cur_lo_idx = i
        if lows[i] < lows[cur_lo_idx]:
            cur_lo_idx = i
    # last segment
    d = lows[cur_lo_idx] / df["peak_high"].to_list()[cur_lo_idx] - 1
    if d <= threshold:
        troughs.append((dates[cur_lo_idx], d))
    return troughs


def plot(df: pl.DataFrame, code: str, output_png: Path) -> None:
    dates = df["date"].to_list()
    closes = df["close"].to_list()
    peak_high = df["peak_high"].to_list()
    dd = [v * 100 for v in df["dd"].to_list()]

    fig, (ax_price, ax_dd) = plt.subplots(
        2, 1, figsize=(15, 8), sharex=True,
        gridspec_kw={"height_ratios": [1, 1]},
    )

    # --- top: price + running ATH ---
    ax_price.plot(dates, closes, "-", color="#1f77b4", linewidth=0.8, label="adjusted close")
    ax_price.plot(dates, peak_high, "--", color="gray", linewidth=0.5, alpha=0.7,
                  label="running ATH (cummax high)")
    ax_price.set_ylabel("Adjusted price")
    ax_price.legend(loc="upper left", fontsize=9)
    ax_price.grid(True, alpha=0.3)

    # --- bottom: drawdown underwater ---
    ax_dd.fill_between(dates, dd, 0, color="#d62728", alpha=0.35)
    ax_dd.plot(dates, dd, "-", color="#d62728", linewidth=0.7)
    ax_dd.axhline(0, color="black", linewidth=0.5)
    ax_dd.set_ylabel("Drawdown (%)")
    ax_dd.set_xlabel("Date")
    ax_dd.grid(True, alpha=0.3)

    # annotate major troughs
    max_dd = df["dd"].min()
    for d, depth in find_troughs(df, ANNOT_THRESHOLD):
        is_max = abs(depth - max_dd) < 1e-9
        ax_dd.annotate(
            f"{d}  {depth * 100:.1f}%" + ("  (max)" if is_max else ""),
            xy=(d, depth * 100),
            xytext=(0, 8 if is_max else 4), textcoords="offset points",
            ha="center", va="bottom", fontsize=7.5,
            color="#7f0000" if is_max else "#b22222",
            fontweight="bold" if is_max else "normal",
            arrowprops=dict(arrowstyle="-", color="gray", lw=0.4),
        )

    ax_dd.xaxis.set_major_locator(mdates.YearLocator())
    ax_dd.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    span = dates[-1] - dates[0]
    ax_dd.set_xlim(dates[0], dates[-1] + span * 0.02)
    ax_dd.text(0.99, 0.03, f"最新 {dates[-1]}", transform=ax_dd.transAxes,
               ha="right", va="bottom", fontsize=10, color="#222", fontweight="bold",
               bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#bbb", alpha=0.85))

    fig.suptitle(
        f"{code} — drawdown (peak = cummax high, trough = daily low)\n"
        f"max drawdown: {max_dd * 100:.2f}%",
        fontsize=12,
    )

    plt.tight_layout(rect=[0, 0, 1, 0.96])
    output_png.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_png, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved to {output_png}")
    print(f"  {code}: {dates[0]} ~ {dates[-1]}, {df.height} rows")
    print(f"  max drawdown: {max_dd * 100:.2f}%")
    print(f"  annotated troughs (depth <= {ANNOT_THRESHOLD * 100:.0f}%):")
    for d, depth in find_troughs(df, ANNOT_THRESHOLD):
        print(f"    {d}  {depth * 100:.2f}%")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--code", default="512890", help="标的代码（基金/指数/股票）")
    parser.add_argument(
        "--adjusted-dir", type=Path,
        default=Path("/mnt/dataset/fund_quote_adjusted"),
        help="前复权行情目录",
    )
    parser.add_argument(
        "--output", type=Path, default=None,
        help="输出 PNG 路径（默认 /mnt/dataset/drawdown_{code}.png）",
    )
    parser.add_argument(
        "--start-date", type=str, default=None,
        help="起始日期 YYYY-MM-DD（cummax 从该日期起累计，默认从最早数据起）",
    )
    args = parser.parse_args()

    output = args.output or Path(f"/mnt/dataset/drawdown_{args.code}.png")
    start = date.fromisoformat(args.start_date) if args.start_date else None
    df = load_quote(args.adjusted_dir, args.code, start)
    plot(df, args.code, output)


if __name__ == "__main__":
    main()
