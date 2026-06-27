"""沪深300 成交额占两市总成交额比例 vs 沪深300（双轴，日频）。

数据源：/mnt/dataset/index_quote_history/ 下三个指数 parquet
  - 000300 沪深300   （分子）
  - 000001 上证综指   （分母·沪，沪市全市场）
  - 399106 深证综指   （分母·深，深市全市场）

按日 join 三者 turnover，share = hs300_turnover / (sh_turnover + sz_turnover)。
分母必须用「综合指数」（上证综指/深证综指 turnover 即各自市场全部股票成交额之和）；
深证成指 399001 仅 500 只成分股，2001-2022 期间远小于全市场，不可作分母。
左轴：占比（面积填充）+ 20 日滚动均线（平滑短期噪音）；
右轴：沪深300 收盘（灰淡线），对照占比与大盘走势的相关性。

占比升高 = 资金向大盘蓝筹集中（抱团/风格切换）；
占比下降 = 资金向中小盘/题材股分散（普涨或中小盘行情）。
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
    """读单个指数 parquet，返回 (date, turnover)，过滤 turnover>0。"""
    return (pl.read_parquet(path, columns=["date", "turnover"])
            .with_columns(pl.col("date").str.to_date("%Y-%m-%d"))
            .filter(pl.col("turnover") > 0)
            .rename({"turnover": code}))


def compute_share(
    hs300_file: Path, sh_file: Path, sz_file: Path,
    ma_window: int = MA_WINDOW,
) -> pl.DataFrame:
    hs = load_turnover(hs300_file, "hs300")
    sh = load_turnover(sh_file, "sh")
    sz = load_turnover(sz_file, "sz")

    d = (hs.join(sh, on="date", how="inner")
           .join(sz, on="date", how="inner")
           .sort("date"))
    d = d.with_columns(
        (pl.col("hs300") / (pl.col("sh") + pl.col("sz"))).alias("share"),
    ).with_columns(
        pl.col("share").rolling_mean(window_size=ma_window).alias(f"share_ma{ma_window}"),
    )
    return d


def load_hs300_close(path: Path) -> pl.DataFrame:
    return (pl.read_parquet(path, columns=["date", "close"])
            .with_columns(pl.col("date").str.to_date("%Y-%m-%d"))
            .sort("date"))


def plot(d: pl.DataFrame, hs300: pl.DataFrame, output: Path, ma_window: int) -> None:
    plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "WenQuanYi Zen Hei"]
    plt.rcParams["axes.unicode_minus"] = False

    dates = d["date"].to_list()
    share = d["share"].to_list()
    share_ma = d[f"share_ma{ma_window}"].to_list()
    hs_dates = hs300["date"].to_list()
    hs_close = hs300["close"].to_list()

    fig, ax = plt.subplots(figsize=(15, 7))
    axr = ax.twinx()

    ax.fill_between(dates, 0, share, color="#1f77b4", alpha=0.18)
    ax.plot(dates, share, color="#1f77b4", lw=0.7, alpha=0.75, label="占比（日频）")
    ax.plot(dates, share_ma, color="#d62728", lw=1.4,
            label=f"占比 MA{ma_window}")

    axr.plot(hs_dates, hs_close, color="#888", lw=0.7, alpha=0.55, label="沪深300（右轴）")

    ax.set_ylabel("沪深300 成交额 / 两市总成交额", color="#1f77b4", fontsize=11)
    ax.tick_params(axis="y", labelcolor="#1f77b4")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v*100:.0f}%"))
    ax.set_ylim(0, None)

    axr.set_ylabel("沪深300 收盘", color="#888", fontsize=10)
    axr.tick_params(axis="y", labelcolor="#888")
    axr.spines["right"].set_color("#bbb")

    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.xaxis.set_minor_locator(mdates.MonthLocator(bymonth=[4, 7, 10]))

    span = dates[-1] - dates[0]
    ax.set_xlim(dates[0], dates[-1] + span * 0.02)

    latest_share = share[-1]
    latest_ma = share_ma[-1]
    ax.text(0.99, 0.03,
            f"最新 {dates[-1]}\n占比 {latest_share*100:.1f}%  ·  MA{ma_window} {latest_ma*100:.1f}%",
            transform=ax.transAxes, ha="right", va="bottom",
            fontsize=10, color="#222", fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.4", fc="white", ec="#bbb", alpha=0.9))

    ax.set_title(
        f"沪深300 成交额占两市总成交额比例 · "
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
    parser.add_argument("--hs300-file", type=Path,
                        default=Path("/mnt/dataset/index_quote_history/000300.parquet"))
    parser.add_argument("--sh-file", type=Path,
                        default=Path("/mnt/dataset/index_quote_history/000001.parquet"),
                        help="上证市场指数（默认 000001 上证综指）")
    parser.add_argument("--sz-file", type=Path,
                        default=Path("/mnt/dataset/index_quote_history/399106.parquet"),
                        help="深证市场综合指数（默认 399106 深证综指；勿用 399001 深证成指，仅 500 成分股）")
    parser.add_argument("--output", type=Path,
                        default=Path("/mnt/dataset/hs300_turnover_share.png"))
    parser.add_argument("--start-date", type=str, default=None,
                        help="起始日期 YYYY-MM-DD")
    parser.add_argument("--end-date", type=str, default=None,
                        help="结束日期 YYYY-MM-DD")
    parser.add_argument("--ma-window", type=int, default=MA_WINDOW,
                        help=f"占比滚动均线窗口（默认 {MA_WINDOW}）")
    args = parser.parse_args()

    d = compute_share(args.hs300_file, args.sh_file, args.sz_file, args.ma_window)
    if args.start_date:
        d = d.filter(pl.col("date") >= date.fromisoformat(args.start_date))
    if args.end_date:
        d = d.filter(pl.col("date") <= date.fromisoformat(args.end_date))

    hs300 = load_hs300_close(args.hs300_file)
    if not d.is_empty():
        hs300 = hs300.filter(
            (pl.col("date") >= d["date"].min()) & (pl.col("date") <= d["date"].max()))

    print(f"比例: {len(d)} 行（{d['date'].min()} ~ {d['date'].max()}）")
    if not d.is_empty():
        latest = d.tail(1)
        print(f"  最新占比: {latest['share'][0]*100:.1f}%")
        print(f"  区间均值: {d['share'].mean()*100:.1f}%")
        print(f"  区间中位: {d['share'].median()*100:.1f}%")
    plot(d, hs300, args.output, args.ma_window)


if __name__ == "__main__":
    main()
