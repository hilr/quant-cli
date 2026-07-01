"""沪深300 成交额回撤水下曲线 + 沪深300 收盘价（上下两栏）。

峰值 = 过去 N 个交易日（默认 120）内 turnover 的最高（rolling max）；
回撤 = turnover / peak_turnover - 1。

下栏用红色面积显示成交额回撤水下曲线（%），上栏画沪深300 收盘价
（含累计最高虚线）作为对照，看「量缩深」的时点是否对应价格低点，
即成交额的「枯竭」是否预示价格拐点。

用滚动窗口（而非 cummax）测峰值，可突出中期（~半年）成交萎缩，
避免被早期历史天量长期压住。

数据源：/mnt/dataset/index_quote_history/000300.parquet（含 turnover 列）。
也适用于任何带 turnover 列的指数/基金/股票行情 parquet。
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import polars as pl

# 标注深度阈值（回撤深于该值的谷值会标日期 + 幅度）
# 滚动窗口下 −50% 噪音太多（每隔几周就会出现），−80% 才是流动性枯竭级别的事件
DEFAULT_THRESHOLD = -0.80
# 滚动窗口（交易日）
DEFAULT_WINDOW = 120


def load_turnover(
    adjusted_dir: Path, code: str, window: int, start_date: date | None = None
) -> pl.DataFrame:
    """读 {code}.parquet，过滤 turnover>0（剔除无成交的早期），按 rolling max 算峰值。"""
    df = (
        pl.read_parquet(adjusted_dir / f"{code}.parquet")
        .with_columns(pl.col("date").str.to_date("%Y-%m-%d"))
        .filter(pl.col("turnover") > 0)
        .sort("date")
    )
    if start_date is not None:
        df = df.filter(pl.col("date") >= start_date)
    df = (
        df.with_columns(
            pl.col("turnover").rolling_max(window_size=window, min_samples=1).alias("peak_turnover")
        )
        .with_columns((pl.col("turnover") / pl.col("peak_turnover") - 1).alias("dd"))
    )
    return df


def find_troughs(df: pl.DataFrame, threshold: float) -> list[tuple]:
    """连续低于 threshold 的段取最深谷值；返回 (date, depth) 列表。

    滚动窗口下峰值非单调，不能用「创新高分段」；改为阈值穿越分段。
    """
    dates = df["date"].to_list()
    dd = df["dd"].to_list()

    troughs = []
    in_dip = False
    cur_lo_idx = 0
    for i in range(len(dates)):
        if dd[i] <= threshold:
            if not in_dip:
                in_dip = True
                cur_lo_idx = i
            elif dd[i] < dd[cur_lo_idx]:
                cur_lo_idx = i
        elif in_dip:
            troughs.append((dates[cur_lo_idx], dd[cur_lo_idx]))
            in_dip = False
    if in_dip:
        troughs.append((dates[cur_lo_idx], dd[cur_lo_idx]))
    return troughs


def plot(df: pl.DataFrame, code: str, window: int, threshold: float, output_png: Path) -> None:
    dates = df["date"].to_list()
    closes = df["close"].to_list()
    peak_close = df["close"].cum_max().to_list()
    dd = [v * 100 for v in df["dd"].to_list()]

    plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "WenQuanYi Zen Hei"]
    plt.rcParams["axes.unicode_minus"] = False

    fig, (ax_price, ax_dd) = plt.subplots(
        2, 1, figsize=(15, 8), sharex=True,
        gridspec_kw={"height_ratios": [1, 1]},
    )

    # --- 上栏：收盘价 + 累计最高 ---
    ax_price.plot(dates, closes, "-", color="#1f77b4", linewidth=0.8, label=f"{code} 收盘")
    ax_price.plot(dates, peak_close, "--", color="gray", linewidth=0.5, alpha=0.7,
                  label="累计最高（cummax close）")
    ax_price.set_ylabel(f"{code} 收盘", fontsize=11)
    ax_price.legend(loc="upper left", fontsize=9)
    ax_price.grid(True, alpha=0.3)

    # --- 下栏：成交额回撤水下曲线 ---
    ax_dd.fill_between(dates, dd, 0, color="#d62728", alpha=0.35)
    ax_dd.plot(dates, dd, "-", color="#d62728", linewidth=0.7)
    ax_dd.axhline(0, color="black", linewidth=0.5)
    ax_dd.set_ylabel("成交额回撤 (%)", fontsize=11)
    ax_dd.set_xlabel("日期")
    ax_dd.grid(True, alpha=0.3)

    # 标注主要谷值
    max_dd = df["dd"].min()
    for d, depth in find_troughs(df, threshold):
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
    ax_dd.xaxis.set_minor_locator(mdates.MonthLocator(bymonth=[1, 4, 7, 10]))

    span = dates[-1] - dates[0]
    ax_dd.set_xlim(dates[0], dates[-1] + span * 0.02)
    ax_dd.text(
        0.99, 0.03, f"最新 {dates[-1]}", transform=ax_dd.transAxes,
        ha="right", va="bottom", fontsize=10, color="#222", fontweight="bold",
        bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#bbb", alpha=0.85),
    )

    fig.suptitle(
        f"{code} — 成交额回撤（peak = rolling max turnover, 窗口 {window} 日）\n"
        f"最大成交额回撤: {max_dd * 100:.2f}%",
        fontsize=12, fontweight="bold",
    )

    plt.tight_layout(rect=[0, 0, 1, 0.96])
    output_png.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_png, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved to {output_png}")
    print(f"  {code}: {dates[0]} ~ {dates[-1]}, {df.height} rows, 滚动窗口 {window} 日")
    print(f"  最大成交额回撤: {max_dd * 100:.2f}%")
    print(f"  标注谷值（深度 <= {threshold * 100:.0f}%）：")
    for d, depth in find_troughs(df, threshold):
        print(f"    {d}  {depth * 100:.2f}%")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--code", default="000300", help="指数/基金/股票代码")
    parser.add_argument(
        "--adjusted-dir", type=Path,
        default=Path("/mnt/dataset/index_quote_history"),
        help="含 {code}.parquet 的行情目录（必须含 turnover 列）",
    )
    parser.add_argument(
        "--window", type=int, default=DEFAULT_WINDOW,
        help=f"滚动最高成交额窗口（交易日，默认 {DEFAULT_WINDOW}）",
    )
    parser.add_argument(
        "--threshold", type=float, default=DEFAULT_THRESHOLD,
        help=f"标注阈值：回撤深于该值的谷才标（默认 {DEFAULT_THRESHOLD}，即 −80%）",
    )
    parser.add_argument(
        "--output", type=Path, default=None,
        help="输出 PNG 路径（默认 /mnt/dataset/turnover_drawdown_{code}.png）",
    )
    parser.add_argument(
        "--start-date", type=str, default=None,
        help="起始日期 YYYY-MM-DD（rolling max 从该日期起算，默认从最早有成交日起）",
    )
    args = parser.parse_args()

    output = args.output or Path(f"/mnt/dataset/turnover_drawdown_{args.code}.png")
    start = date.fromisoformat(args.start_date) if args.start_date else None
    df = load_turnover(args.adjusted_dir, args.code, args.window, start)
    plot(df, args.code, args.window, args.threshold, output)


if __name__ == "__main__":
    main()
