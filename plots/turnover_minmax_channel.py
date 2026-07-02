"""沪深300 + 成交额通道（120 日滚动最大/最小值），上下两栏。

通道定义（非参数化，区别于 turnover_channel_breakout 的 log Bollinger）：
  上轨 = rolling_max(turnover, window)
  下轨 = rolling_min(turnover, window)
  中轨 = (上轨 + 下轨) / 2

上下两栏共享 x 轴：
  上栏：沪深300 收盘价
  下栏：当日成交额（细线）+ 通道上下轨（粗线）+ 通道带（淡色填充）
        y 轴 log 刻度（成交额跨数十倍，线性会把早期压成平地）

适合回答：「近半年的成交额波动带在哪？当日成交额是触及天量（贴上轨）还是
濒临枯竭（贴下轨）？」例如 2015 牛市顶峰成交额突破上轨后长期维持高位，
2018 熊市则多次贴下轨。

数据源：/mnt/dataset/index_quote_history/000300.parquet（含 turnover 列）。
也适用于任何带 turnover 列的指数/基金/股票行情 parquet。
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import polars as pl

DEFAULT_WINDOW = 120


def load_with_channel(
    adjusted_dir: Path, code: str, window: int, start_date: date | None = None
) -> pl.DataFrame:
    """读 {code}.parquet，过滤 turnover>0，计算 rolling min/max/mid。"""
    df = (
        pl.read_parquet(adjusted_dir / f"{code}.parquet")
        .with_columns(pl.col("date").str.to_date("%Y-%m-%d"))
        .filter(pl.col("turnover") > 0)
        .sort("date")
    )
    if start_date is not None:
        df = df.filter(pl.col("date") >= start_date)
    df = df.with_columns(
        pl.col("turnover").rolling_max(window_size=window, min_samples=1).alias("ch_high"),
        pl.col("turnover").rolling_min(window_size=window, min_samples=1).alias("ch_low"),
    ).with_columns(
        ((pl.col("ch_high") + pl.col("ch_low")) / 2).alias("ch_mid"),
    )
    return df


def _fmt_turnover(x: float, _pos) -> str:
    if x >= 1e12:
        return f"{x/1e12:.1f}万亿"
    if x >= 1e8:
        return f"{x/1e8:.0f}亿"
    if x >= 1e4:
        return f"{x/1e4:.0f}万"
    return f"{x:.0f}"


def plot(df: pl.DataFrame, code: str, window: int, output_png: Path) -> None:
    dates = df["date"].to_list()
    closes = df["close"].to_list()
    turnover = df["turnover"].to_list()
    ch_high = df["ch_high"].to_list()
    ch_low = df["ch_low"].to_list()
    ch_mid = df["ch_mid"].to_list()

    plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "WenQuanYi Zen Hei"]
    plt.rcParams["axes.unicode_minus"] = False

    fig, (ax_price, ax_vol) = plt.subplots(
        2, 1, figsize=(15, 8), sharex=True,
        gridspec_kw={"height_ratios": [1, 1]},
    )

    # --- 上栏：收盘价 ---
    ax_price.plot(dates, closes, "-", color="#1f77b4", linewidth=0.8, label=f"{code} 收盘")
    ax_price.set_ylabel(f"{code} 收盘", fontsize=11)
    ax_price.legend(loc="upper left", fontsize=9)
    ax_price.grid(True, alpha=0.3)

    # --- 下栏：成交额 + 通道 ---
    # 通道带（淡色填充）
    ax_vol.fill_between(dates, ch_low, ch_high, color="#1f77b4", alpha=0.15,
                        label=f"通道带（{window} 日 min/max）")
    # 中轨
    ax_vol.plot(dates, ch_mid, "--", color="#1f77b4", linewidth=0.6, alpha=0.6,
                label="中轨 (max+min)/2")
    # 上下轨
    ax_vol.plot(dates, ch_high, "-", color="#d62728", linewidth=1.0, alpha=0.85,
                label=f"上轨（{window} 日 max）")
    ax_vol.plot(dates, ch_low, "-", color="#27ae60", linewidth=1.0, alpha=0.85,
                label=f"下轨（{window} 日 min）")
    # 当日成交额
    ax_vol.plot(dates, turnover, "-", color="black", linewidth=0.4, alpha=0.6,
                label="当日成交额")

    ax_vol.set_yscale("log")
    ax_vol.yaxis.set_major_formatter(mticker.FuncFormatter(_fmt_turnover))
    ax_vol.set_ylabel("成交额（log）", fontsize=11)
    ax_vol.set_xlabel("日期")
    ax_vol.grid(True, alpha=0.3, which="both")
    ax_vol.legend(loc="upper left", fontsize=8.5, ncol=2)

    ax_vol.xaxis.set_major_locator(mdates.YearLocator())
    ax_vol.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax_vol.xaxis.set_minor_locator(mdates.MonthLocator(bymonth=[1, 4, 7, 10]))

    span = dates[-1] - dates[0]
    ax_vol.set_xlim(dates[0], dates[-1] + span * 0.02)

    latest_to = turnover[-1]
    latest_high = ch_high[-1]
    latest_low = ch_low[-1]
    pos_in_channel = (latest_to - latest_low) / (latest_high - latest_low) * 100 if latest_high > latest_low else 0
    ax_vol.text(
        0.99, 0.03,
        f"最新 {dates[-1]}\n成交额 {_fmt_turnover(latest_to, None)}\n"
        f"通道 [{_fmt_turnover(latest_low, None)}, {_fmt_turnover(latest_high, None)}]\n"
        f"位置 {pos_in_channel:.0f}%",
        transform=ax_vol.transAxes, ha="right", va="bottom",
        fontsize=10, color="#222", fontweight="bold",
        bbox=dict(boxstyle="round,pad=0.4", fc="white", ec="#bbb", alpha=0.9),
    )

    fig.suptitle(
        f"{code} — 成交额通道（{window} 日滚动 max/min）+ 收盘价\n"
        f"{dates[0].strftime('%Y-%m-%d')} ~ {dates[-1].strftime('%Y-%m-%d')}",
        fontsize=12, fontweight="bold",
    )

    plt.tight_layout(rect=[0, 0, 1, 0.96])
    output_png.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_png, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved to {output_png}")
    print(f"  {code}: {dates[0]} ~ {dates[-1]}, {df.height} rows, 窗口 {window} 日")
    print(f"  最新成交额: {_fmt_turnover(latest_to, None)}")
    print(f"  最新通道:   [{_fmt_turnover(latest_low, None)}, {_fmt_turnover(latest_high, None)}]")
    print(f"  通道内位置: {pos_in_channel:.0f}%  (0%=贴下轨, 100%=贴上轨)")


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
        help=f"滚动 min/max 窗口（交易日，默认 {DEFAULT_WINDOW}）",
    )
    parser.add_argument(
        "--output", type=Path, default=None,
        help="输出 PNG 路径（默认 /mnt/dataset/turnover_minmax_channel_{code}.png）",
    )
    parser.add_argument(
        "--start-date", type=str, default=None,
        help="起始日期 YYYY-MM-DD（默认从最早有成交日起）",
    )
    args = parser.parse_args()

    output = args.output or Path(f"/mnt/dataset/turnover_minmax_channel_{args.code}.png")
    start = date.fromisoformat(args.start_date) if args.start_date else None
    df = load_with_channel(args.adjusted_dir, args.code, args.window, start)
    plot(df, args.code, args.window, output)


if __name__ == "__main__":
    main()
