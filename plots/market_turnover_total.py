"""沪深两市总成交额（日频）vs 沪深300（双轴）。

数据源：/mnt/dataset/index_quote_history/ 下两个综合指数 parquet
  - 000001 上证综指（沪市全市场）
  - 399106 深证综指（深市全市场）

两市总成交额 = sh_turnover + sz_turnover，单位亿元。
（必须用「综合指数」：上证综指/深证综指 的 turnover 即各自市场全部股票成交额之和；
  深证成指 399001 仅 500 只成分股，2001-2022 期间是成分股口径、远小于全市场，不可作分母。）
左轴：总成交额（面积填充）+ 20 日滚动均线；
右轴：沪深300 收盘（灰淡线），对照量价关系。
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import polars as pl

MA_WINDOW = 20


def load_turnover(path: Path, code: str) -> pl.DataFrame:
    return (pl.read_parquet(path, columns=["date", "turnover"])
            .with_columns(pl.col("date").str.to_date("%Y-%m-%d"))
            .filter(pl.col("turnover") > 0)
            .rename({"turnover": code}))


def compute_total(sh_file: Path, sz_file: Path, ma_window: int = MA_WINDOW) -> pl.DataFrame:
    sh = load_turnover(sh_file, "sh")
    sz = load_turnover(sz_file, "sz")
    d = (sh.join(sz, on="date", how="inner").sort("date"))
    d = d.with_columns(
        ((pl.col("sh") + pl.col("sz")) / 1e8).alias("total"),  # 亿元
    ).with_columns(
        pl.col("total").rolling_mean(window_size=ma_window).alias(f"total_ma{ma_window}"),
    )
    return d


def load_hs300_close(path: Path) -> pl.DataFrame:
    return (pl.read_parquet(path, columns=["date", "close"])
            .with_columns(pl.col("date").str.to_date("%Y-%m-%d"))
            .sort("date"))


def plot(d: pl.DataFrame, hs300: pl.DataFrame, output: Path, ma_window: int,
         use_log: bool) -> None:
    plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "WenQuanYi Zen Hei"]
    plt.rcParams["axes.unicode_minus"] = False

    dates = d["date"].to_list()
    total = d["total"].to_list()
    total_ma = d[f"total_ma{ma_window}"].to_list()
    hs_dates = hs300["date"].to_list()
    hs_close = hs300["close"].to_list()

    fig, ax = plt.subplots(figsize=(15, 7))
    axr = ax.twinx()

    ax.fill_between(dates, 0, total, color="#1f77b4", alpha=0.18)
    ax.plot(dates, total, color="#1f77b4", lw=0.6, alpha=0.7, label="总成交额（日频）")
    ax.plot(dates, total_ma, color="#d62728", lw=1.4, label=f"总成交额 MA{ma_window}")

    axr.plot(hs_dates, hs_close, color="#888", lw=0.7, alpha=0.55, label="沪深300（右轴）")

    ax.set_ylabel("沪深两市总成交额（亿元）", color="#1f77b4", fontsize=11)
    ax.tick_params(axis="y", labelcolor="#1f77b4")
    if use_log:
        ax.set_yscale("log")

    axr.set_ylabel("沪深300 收盘", color="#888", fontsize=10)
    axr.tick_params(axis="y", labelcolor="#888")
    axr.spines["right"].set_color("#bbb")

    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.xaxis.set_minor_locator(mdates.MonthLocator(bymonth=[4, 7, 10]))

    span = dates[-1] - dates[0]
    ax.set_xlim(dates[0], dates[-1] + span * 0.02)

    latest = total[-1]
    latest_ma = total_ma[-1]
    peak_v = d["total"].max()
    peak_d = d.filter(pl.col("total") == peak_v)["date"][0]
    ax.text(0.99, 0.03,
            f"最新 {dates[-1]}\n总成交额 {latest:,.0f} 亿  ·  MA{ma_window} {latest_ma:,.0f} 亿\n"
            f"历史峰值 {peak_v:,.0f} 亿 @ {peak_d}",
            transform=ax.transAxes, ha="right", va="bottom",
            fontsize=10, color="#222", fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.4", fc="white", ec="#bbb", alpha=0.9))

    scale_note = "（log 刻度）" if use_log else ""
    ax.set_title(
        f"沪深两市总成交额{scale_note} · "
        f"{dates[0].strftime('%Y-%m-%d')} ~ {dates[-1].strftime('%Y-%m-%d')}",
        fontsize=13, fontweight="bold")

    lines_left, labels_left = ax.get_legend_handles_labels()
    lines_right, labels_right = axr.get_legend_handles_labels()
    ax.legend(lines_left + lines_right, labels_left + labels_right,
              loc="upper left", fontsize=9, ncol=3)

    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=130, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"Saved to {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sh-file", type=Path,
                        default=Path("/mnt/dataset/index_quote_history/000001.parquet"))
    parser.add_argument("--sz-file", type=Path,
                        default=Path("/mnt/dataset/index_quote_history/399106.parquet"),
                        help="深证市场综合指数（默认 399106 深证综指；勿用 399001 深证成指，仅 500 成分股）")
    parser.add_argument("--hs300-file", type=Path,
                        default=Path("/mnt/dataset/index_quote_history/000300.parquet"))
    parser.add_argument("--output", type=Path,
                        default=Path("/mnt/dataset/market_turnover_total.png"))
    parser.add_argument("--start-date", type=str, default=None)
    parser.add_argument("--end-date", type=str, default=None)
    parser.add_argument("--ma-window", type=int, default=MA_WINDOW)
    parser.add_argument("--log", action="store_true",
                        help="左轴用对数刻度（早期几百亿 vs 现在万亿，跨度大时更清晰）")
    args = parser.parse_args()

    d = compute_total(args.sh_file, args.sz_file, args.ma_window)
    if args.start_date:
        d = d.filter(pl.col("date") >= date.fromisoformat(args.start_date))
    if args.end_date:
        d = d.filter(pl.col("date") <= date.fromisoformat(args.end_date))

    hs300 = load_hs300_close(args.hs300_file)
    if not d.is_empty():
        hs300 = hs300.filter(
            (pl.col("date") >= d["date"].min()) & (pl.col("date") <= d["date"].max()))

    print(f"总成交额: {len(d)} 行（{d['date'].min()} ~ {d['date'].max()}）")
    if not d.is_empty():
        print(f"  最新: {d.tail(1)['total'][0]:,.0f} 亿元")
        print(f"  均值: {d['total'].mean():,.0f} 亿  中位: {d['total'].median():,.0f} 亿")
    plot(d, hs300, args.output, args.ma_window, args.log)


if __name__ == "__main__":
    main()
