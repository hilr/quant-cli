"""港股通南向资金 20/60 日滚动净流入 vs 恒生科技 ETF（513180 前复权）双轴图。

数据源：/mnt/dataset/exchange_hkex/southbound_flow.csv（net_yi，亿港元）；
        /mnt/dataset/fund_quote_adjusted/513180.parquet（前复权 close）。

3 条滚动合计线（左轴，亿港元）+ 513180 前复权收盘（右轴）。
- 20 日窗口：反映短期节奏（最敏感）
- 60 日窗口：长期趋势（最平滑）

正值=内地过去 N 个交易日净买入港股的累计金额。
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import polars as pl
from matplotlib.transforms import blended_transform_factory

WINDOWS = [20, 60]
# (window, color, linewidth, alpha)
LINE_STYLE = {
    20: ("#e6550d", 0.6, 0.7),   # 橙：短期，避免与绿色填充冲突
    60: ("#08519c", 1.0, 0.9),   # 深蓝：长期趋势
}
COLOR_ETF = "#d62728"
# (color, alpha) — 中国市场习惯：红=净流入（买），绿=净流出（卖）
POS_FILL = ("#fcae91", 0.45)
NEG_FILL = ("#a1d99b", 0.45)


def load_southbound(csv_path: Path) -> pl.DataFrame:
    # schema_overrides：前 ~309 行（2015-08 ~ 2016-12，SZSE 深股通未开通）
    # sse_*_yi 有值但 szse_*/net_yi 全空，polars 默认看前 100 行会推成 str。
    float_cols = {c: pl.Float64 for c in
                  ("sse_buy_yi", "sse_sell_yi", "szse_buy_yi", "szse_sell_yi",
                   "buy_yi", "sell_yi", "net_yi")}
    df = (
        pl.read_csv(csv_path, try_parse_dates=True, schema_overrides=float_cols)
        .sort("date")
        # 南向停盘日（HK 假期）+ 早期 SZSE 未开通日的 net_yi 是 null，rolling_sum
        # 默认会把 null 传染整个窗口。停盘/未开通 = 没流量 = 加 0。
        .with_columns(pl.col("net_yi").fill_null(0))
    )
    # 计算每个窗口的滚动合计
    return df.with_columns([
        pl.col("net_yi").rolling_sum(window_size=w, min_samples=w).alias(f"net_{w}d")
        for w in WINDOWS
    ])


def load_etf(fund_file: Path) -> pl.DataFrame:
    return (
        pl.read_parquet(fund_file, columns=["date", "close"])
        .with_columns(pl.col("date").str.to_date("%Y-%m-%d"))
        .sort("date")
    )


def plot(sb: pl.DataFrame, etf: pl.DataFrame, output_png: Path) -> None:
    cutoff = sb["date"].min()
    etf = etf.filter(pl.col("date") >= cutoff)

    # 中文字体
    for f in plt.rcParams.get("font.sans-serif", []):
        if "Noto" in f or "WenQuanYi" in f:
            break
    else:
        plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "WenQuanYi Zen Hei"]
        plt.rcParams["axes.unicode_minus"] = False

    fig, (ax_top, ax_bot) = plt.subplots(
        2, 1, figsize=(15, 9), sharex=True,
        gridspec_kw={"height_ratios": [1.0, 1.0], "hspace": 0.06},
        constrained_layout=True,
    )

    dates = sb["date"].to_list()
    d_min, d_max = sb["date"].min(), sb["date"].max()

    # ===== 上图：513180 ETF =====
    ax_top.plot(
        etf["date"].to_list(), etf["close"].to_list(), "-",
        color=COLOR_ETF, linewidth=1.3, alpha=0.85,
        label="513180 前复权",
    )
    ax_top.set_ylabel("513180 前复权收盘", color=COLOR_ETF, fontsize=10)
    ax_top.tick_params(axis="y", labelcolor=COLOR_ETF)
    ax_top.grid(True, alpha=0.3)
    ax_top.legend(loc="upper right", fontsize=9)

    # ===== 下图：20d + 60d 滚动净流入 =====
    ax_bot.axhline(0, color="gray", linewidth=0.5, alpha=0.5)
    # 先画 60d（背景，填充更显眼），再画 20d（前景，填充更淡避免压住 60d）
    for w in [60, 20]:
        # polars to_list 在预热期返回 None；matplotlib 不认 None，转 NaN 画出断点。
        vals = [v if v is not None else float("nan") for v in sb[f"net_{w}d"].to_list()]
        color, lw, alpha = LINE_STYLE[w]
        fill_mult = 1.0 if w == 60 else 0.55
        pos_color, pos_alpha = POS_FILL
        neg_color, neg_alpha = NEG_FILL
        ax_bot.fill_between(
            dates, vals, 0,
            where=[(v is not None and v >= 0) for v in vals],
            color=pos_color, alpha=pos_alpha * fill_mult, interpolate=True,
            linewidth=0,
        )
        ax_bot.fill_between(
            dates, vals, 0,
            where=[(v is not None and v < 0) for v in vals],
            color=neg_color, alpha=neg_alpha * fill_mult, interpolate=True,
            linewidth=0,
        )
        ax_bot.plot(
            dates, vals, "-",
            color=color, linewidth=lw, alpha=alpha,
            label=f"南向 {w}d 净流入合计",
        )
    ax_bot.set_ylabel("滚动净流入（亿港元）", fontsize=10)
    ax_bot.set_xlabel("日期")
    ax_bot.grid(True, alpha=0.3)
    ax_bot.legend(loc="upper left", fontsize=9)

    # ===== 事件标注：axvline 跨两图，文字贴上图顶端 =====
    trans = blended_transform_factory(ax_top.transData, ax_top.transAxes)
    events = [
        (date(2018, 6, 1), "2018 贸易战"),
        (date(2021, 9, 1), "双减/恒大"),
        (date(2022, 3, 1), "中概退市危机"),
        (date(2022, 10, 1), "HK 重开预期"),
        (date(2024, 4, 1), "HK 牛市启动"),
        (date(2024, 9, 1), "924 政策"),
        (date(2025, 8, 1), "南向峰值"),
    ]
    for d, label in events:
        if not (d_min <= d <= d_max):
            continue
        for ax in (ax_top, ax_bot):
            ax.axvline(d, color="purple", linestyle="--", linewidth=0.4, alpha=0.35)
        ax_top.text(
            d, 0.98, f" {label}", color="purple", fontsize=8,
            rotation=90, va="top", ha="left", transform=trans,
        )

    # X 轴格式
    ax_bot.xaxis.set_major_locator(mdates.YearLocator(1))
    ax_bot.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    # 总标题
    d0 = d_min.strftime("%Y-%m-%d")
    d1 = d_max.strftime("%Y-%m-%d")
    fig.suptitle(
        f"港股通南向资金 20/60 日滚动净流入 vs 恒生科技 ETF (513180)  ({d0} ~ {d1})",
        fontsize=12, fontweight="bold", x=0.01, ha="left",
    )

    output_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_png, dpi=120, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"Saved to {output_png}")

    # 摘要：每个窗口的最新值 + 历史极值
    print(f"\n南向日度: {sb['date'].min()} ~ {sb['date'].max()}, {sb.height} 行")
    for w in WINDOWS:
        col = f"net_{w}d"
        latest = sb.filter(pl.col(col).is_not_null()).tail(1)
        peak = sb.filter(pl.col(col).is_not_null()).sort(col, descending=True).head(1)
        trough = sb.filter(pl.col(col).is_not_null()).sort(col).head(1)
        print(f"  {w}d: 最新 {latest[col][0]:+.1f}, "
              f"峰 {peak[col][0]:+.1f}@{peak['date'][0]}, "
              f"谷 {trough[col][0]:+.1f}@{trough['date'][0]}")


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--csv", type=Path,
        default=Path("/mnt/dataset/exchange_hkex/southbound_flow.csv"),
        help="南向资金日度 CSV",
    )
    p.add_argument(
        "--fund-file", type=Path,
        default=Path("/mnt/dataset/fund_quote_adjusted/513180.parquet"),
        help="513180 恒生科技 ETF 前复权 parquet",
    )
    p.add_argument(
        "--output", type=Path,
        default=Path("/mnt/dataset/southbound_flow_rolling_vs_513180.png"),
        help="输出 PNG",
    )
    args = p.parse_args()

    sb = load_southbound(args.csv)
    etf = load_etf(args.fund_file)
    plot(sb, etf, args.output)


if __name__ == "__main__":
    main()
