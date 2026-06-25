"""人民币兑美元汇率（USD/CNY，月度中间价）1999-2026，叠加沪深300。

数据：/mnt/dataset/pbc/exchange_rate.csv（usd_cny_eop 月末 / usd_cny_avg 月均）。
沪深300：/mnt/dataset/index_quote_history/000300.parquet（日收盘，按日期 join）。
上图：USD/CNY 月末中间价（左轴）+ 沪深300收盘（右轴），标注几次重大汇率制度变化。
下图：月度变动（eop 环比 %），看贬值/升值节奏。
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import polars as pl

DEFAULT_CSV = Path("/mnt/dataset/pbc/exchange_rate.csv")

# (日期, 标签, 颜色) —— 重大汇率制度节点
EVENTS = [
    ("2005-07", "7/21 汇改\n脱钩美元", "#1f77b4"),
    ("2008-07", "危机重盯\n~6.83", "#888888"),
    ("2010-06", "重启浮动", "#1f77b4"),
    ("2014-01", "升值高点\n6.04", "#2ca02c"),
    ("2015-08", "811 汇改\n一次性贬值", "#d62728"),
    ("2022-04", "快速贬值\n6.3→7.3", "#d62728"),
]


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    p.add_argument(
        "--index-file", type=Path,
        default=Path("/mnt/dataset/index_quote_history/000300.parquet"),
        help="沪深300 parquet（日收盘）",
    )
    p.add_argument("--output", type=Path, default=None)
    args = p.parse_args()

    df = (
        pl.read_csv(args.csv)
        .with_columns(pl.col("date").str.to_date("%Y-%m"))
        .sort("date")
    )
    df = df.with_columns(
        (pl.col("usd_cny_eop") / pl.col("usd_cny_eop").shift(1) - 1).alias("mom")
    )

    hs300 = (
        pl.read_parquet(args.index_file, columns=["date", "close"])
        .with_columns(pl.col("date").str.to_date("%Y-%m-%d"))
        .sort("date")
    )

    plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "WenQuanYi Zen Hei"]
    plt.rcParams["axes.unicode_minus"] = False

    fig, (ax_top, ax_bot) = plt.subplots(
        2, 1, figsize=(14, 8), sharex=True,
        gridspec_kw={"height_ratios": [2.2, 1.0], "hspace": 0.08},
        constrained_layout=True,
    )

    dates = df["date"].to_list()
    eop = df["usd_cny_eop"].to_list()
    avg = df["usd_cny_avg"].to_list()
    mom = df["mom"].to_list()

    # 上图：汇率
    ax_top.plot(dates, eop, color="#1f77b4", lw=1.0, label="月末中间价 (eop)")
    ax_top.plot(dates, avg, color="#1f77b4", lw=0.6, alpha=0.5, linestyle="--",
                label="月均 (avg)")
    ax_top.axhline(8.2765, color="#999", lw=0.6, ls=":", alpha=0.7)
    ax_top.text(dates[2], 8.2765, " 8.28 盯住线", fontsize=8, color="#666",
                va="bottom", ha="left")
    # 事件标注
    from datetime import date as _date
    for d_str, label, color in EVENTS:
        d = _date.fromisoformat(d_str + "-01")
        # 找最近的汇率值定位 y
        j = min(range(len(dates)), key=lambda i: abs((dates[i] - d).days))
        yv = eop[j]
        ax_top.axvline(d, color=color, lw=0.7, alpha=0.5, linestyle="--", zorder=1)
        ax_top.annotate(
            label, xy=(d, yv), xytext=(8, 18 if color == "#d62728" else -28),
            textcoords="offset points", fontsize=7.5, color=color,
            arrowprops=dict(arrowstyle="-", color=color, lw=0.6, alpha=0.7),
            ha="left", va="bottom" if color == "#d62728" else "top",
        )
    ax_top.set_ylabel("USD/CNY（人民币元/美元）", fontsize=10)
    ax_top.grid(True, alpha=0.3)

    # 右轴：沪深300收盘
    ax_right = ax_top.twinx()
    ax_right.plot(hs300["date"].to_list(), hs300["close"].to_list(),
                  color="#d62728", lw=0.6, alpha=0.75, label="沪深300收盘 (右轴)")
    ax_right.set_ylabel("沪深300 收盘", fontsize=10, color="#d62728")
    ax_right.tick_params(axis="y", labelcolor="#d62728")

    h1, l1 = ax_top.get_legend_handles_labels()
    h2, l2 = ax_right.get_legend_handles_labels()
    ax_top.legend(h1 + h2, l1 + l2, loc="upper right", fontsize=9)
    ax_top.set_title(
        f"人民币兑美元汇率 vs 沪深300  {dates[0].strftime('%Y-%m')} ~ "
        f"{dates[-1].strftime('%Y-%m')}（{len(df)} 个月）",
        fontsize=12, fontweight="bold", loc="left")

    # 下图：月度变动 %
    colors = ["#d62728" if (v is not None and v > 0) else "#2ca02c"
              for v in mom]
    ax_bot.bar(dates, [v * 100 if v is not None else 0 for v in mom],
               width=25, color=colors, alpha=0.7)
    ax_bot.axhline(0, color="#444", lw=0.6)
    ax_bot.set_ylabel("月度变动（%）", fontsize=10)
    ax_bot.grid(True, alpha=0.3)
    ax_bot.xaxis.set_major_locator(mdates.YearLocator(2))
    ax_bot.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    span = dates[-1] - dates[0]
    ax_bot.set_xlim(dates[0], dates[-1] + span * 0.02)
    ax_bot.text(0.99, 0.03, f"最新 {dates[-1]}", transform=ax_bot.transAxes,
                ha="right", va="bottom", fontsize=10, color="#222", fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#bbb", alpha=0.85))

    output = args.output or Path("/mnt/dataset/usd_cny_exchange_rate.png")
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"图: {output}")
    print(f"区间 {dates[0]} ~ {dates[-1]}，USD/CNY 期末范围 "
          f"{min(v for v in eop if v):.3f} ~ {max(v for v in eop if v):.3f}")
    print(f"沪深300 {hs300['date'].min()} ~ {hs300['date'].max()}，"
          f"{hs300.height} 个交易日，"
          f"收盘 {hs300['close'].min():.0f} ~ {hs300['close'].max():.0f}")


if __name__ == "__main__":
    main()
