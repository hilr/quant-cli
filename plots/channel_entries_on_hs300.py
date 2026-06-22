"""512890 通道买入点叠加在沪深300日线图：观察买入点出现时的市场背景。

复用 channel_backtest 的下轨入场逻辑（close ≤ MA120 − 1.5σ），
把买入日期作为竖线 + 散点（散点 y = 当日沪深300收盘）标在沪深300日线上，
直接看到每次信号触发时大盘所处的位置。
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
from channel_backtest import run_backtest


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--code", default="512890")
    p.add_argument("--adjusted-dir", type=Path,
                   default=Path("/mnt/dataset/fund_quote_adjusted"))
    p.add_argument("--index-file", type=Path,
                   default=Path("/mnt/dataset/index_quote_history/000300.parquet"))
    p.add_argument("--window", type=int, default=120)
    p.add_argument("--k", type=float, default=1.5)
    p.add_argument("--output", type=Path, default=None)
    args = p.parse_args()

    # 复算 512890 通道买入点
    fund = (pl.read_parquet(args.adjusted_dir / f"{args.code}.parquet")
              .with_columns(pl.col("date").str.to_date("%Y-%m-%d"))
              .sort("date"))
    _out, entries, _exits = run_backtest(
        fund, args.window, args.k, False, "trail", 1, 1.5,
    )
    entries = sorted(entries, key=lambda e: e[0])

    # 沪深300日线
    hs300 = (pl.read_parquet(args.index_file, columns=["date", "close"])
               .with_columns(pl.col("date").str.to_date("%Y-%m-%d").alias("d"))
               .sort("d"))
    d2c = dict(zip(hs300["d"].to_list(), hs300["close"].to_list()))

    plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "WenQuanYi Zen Hei"]
    plt.rcParams["axes.unicode_minus"] = False

    fig, ax = plt.subplots(figsize=(15, 7))
    ax.plot(hs300["d"], hs300["close"], color="#1f77b4", lw=0.7,
            label="沪深300 收盘（右轴：标准化 100）")
    # 标准化到 100 起点更直观（从首买入点前一年起算）
    start = date(entries[0][0].year - 1, 1, 1)
    base_row = hs300.filter(pl.col("d") >= start)
    if len(base_row) > 0:
        base_val = base_row["close"].to_list()[0]
        base_d = base_row["d"].to_list()[0]
        ax.plot([], [])  # 保持颜色顺序
        ax2 = ax.twinx()
        ax2.plot(hs300["d"], hs300["close"] / base_val * 100, color="#1f77b4",
                 lw=0.7, alpha=0)
        ax2.set_ylim(ax.get_ylim()[0] / base_val * 100, ax.get_ylim()[1] / base_val * 100)
        ax2.set_ylabel("沪深300（起点=100）", color="#1f77b4")

    # 买入点：竖线 + 散点 + 日期标签
    for i, (d, _price, _tag) in enumerate(entries):
        if d not in d2c:
            continue
        ax.axvline(d, color="#d62728", alpha=0.30, lw=0.7, ls="--", zorder=1)
        ax.scatter([d], [d2c[d]], color="#d62728", s=55, zorder=5,
                   edgecolors="white", linewidths=0.6)
        # 标签上下交替，避免重叠
        offset = 12 if i % 2 == 0 else -16
        va = "bottom" if i % 2 == 0 else "top"
        ax.annotate(d.strftime("%Y-%m-%d"), xy=(d, d2c[d]),
                    xytext=(0, offset), textcoords="offset points",
                    ha="center", va=va, fontsize=6.5, color="#b22222",
                    fontweight="bold")

    ax.set_ylabel("沪深300 收盘")
    ax.set_xlabel("日期")
    ax.set_title(
        f"{args.code} 红利低波通道买入点（MA{args.window}−{args.k}σ）"
        f"叠加沪深300：共 {len(entries)} 个买入点",
        fontsize=12,
    )
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(True, alpha=0.3)
    ax.set_xlim(start, hs300["d"].max())
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    # 次刻度：每季度
    ax.xaxis.set_minor_locator(mdates.MonthLocator(bymonth=[1, 4, 7, 10]))

    plt.tight_layout()
    output = args.output or Path(f"/mnt/dataset/channel_entries_on_hs300_{args.code}.png")
    output.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output, dpi=130, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved to {output}")
    print(f"\n{len(entries)} 个买入点对应的沪深300点位：")
    print(f"  {'date':<12}{'hs300':>10}")
    for d, _p, _t in entries:
        v = d2c.get(d)
        print(f"  {d!s:<12}{v:>10.2f}" if v else f"  {d!s:<12}{'n/a':>10}")


if __name__ == "__main__":
    main()
