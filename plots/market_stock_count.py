"""沪深两市每月新上市股票数 / 新增流通市值 / 沪深300（左轴+右轴+次右轴，月频）。

按每只股票在其 parquet 中的最早交易日（「首日」≈ IPO 日）归组到月：
- 左轴（柱）：当月新上市股票数
- 右轴（线 + 面积）：当月新上市股票首日流通市值之和（亿元）
- 次右轴（外偏，灰淡线）：沪深300 收盘（大盘表现对照）

时间范围默认按沪深300的范围（2002 起）。
数据源：个股明细 /mnt/dataset/stock_quote_history/*.parquet；
        沪深300 /mnt/dataset/index_quote_history/000300.parquet。
排除北交所/三板（code 首位 4/8、或 920 段）：数据覆盖不全（920 段自 2025-10 才入库），
且北交所独立于「沪深两市」。
"""
from __future__ import annotations

import argparse
import time
from datetime import date
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import polars as pl


def load_ipo_firstday(data_dir: Path) -> pl.DataFrame:
    """扫描个股明细，取每只股票首日 date + 首日 free_float_market_cap。"""
    files = sorted(data_dir.glob("*.parquet"))
    if not files:
        raise SystemExit(f"未找到 parquet：{data_dir}")
    parts = []
    t0 = time.time()
    for f in files:
        r = (pl.scan_parquet(f)
             .select(pl.col("date"), pl.col("code"), pl.col("free_float_market_cap"))
             .sort("date")
             .head(1)
             .collect())
        parts.append(r)
    first = (pl.concat(parts, how="vertical")
             .with_columns(pl.col("date").str.to_date("%Y-%m-%d")))
    print(f"扫描 {len(files)} 只股票（{time.time() - t0:.1f}s）"
          f"· 首日范围 {first['date'].min()} ~ {first['date'].max()}")
    return first


def load_hs300_close(path: Path) -> pl.DataFrame:
    return (pl.read_parquet(path, columns=["date", "close"])
            .with_columns(pl.col("date").str.to_date("%Y-%m-%d"))
            .sort("date"))


def monthly_agg(first: pl.DataFrame) -> pl.DataFrame:
    """按月聚合：当月新上市股票数 + 首日流通市值之和。"""
    return (first
            .with_columns(pl.col("date").dt.truncate("1mo").alias("month"))
            .group_by("month")
            .agg(pl.len().alias("new_count"),
                 pl.col("free_float_market_cap").sum().fill_null(0).alias("ffmc_sum"))
            .sort("month"))


def plot(d: pl.DataFrame, hs300: pl.DataFrame, output: Path) -> None:
    plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "WenQuanYi Zen Hei"]
    plt.rcParams["axes.unicode_minus"] = False

    months = d["month"].to_list()
    cnt = d["new_count"].to_list()
    ffmc_yi = [v / 1e8 if v is not None else 0.0 for v in d["ffmc_sum"].to_list()]  # 亿元
    hs_dates = hs300["date"].to_list()
    hs_close = hs300["close"].to_list()

    fig, ax = plt.subplots(figsize=(16, 7))
    fig.subplots_adjust(right=0.84)
    axr = ax.twinx()
    axr2 = ax.twinx()
    axr2.spines["right"].set_position(("outward", 64))

    ax.bar(months, cnt, width=25, color="#2ca02c", alpha=0.55,
           label="当月新上市股票数（左轴）")
    axr.fill_between(months, 0, ffmc_yi, color="#1f77b4", alpha=0.12)
    axr.plot(months, ffmc_yi, color="#1f77b4", lw=1.3,
             label="当月新增流通市值（右轴）")
    axr2.plot(hs_dates, hs_close, color="#888", lw=0.7, alpha=0.55,
              label="沪深300（次右轴）")

    ax.set_ylabel("当月新上市股票数", color="#2ca02c", fontsize=11)
    ax.tick_params(axis="y", labelcolor="#2ca02c")
    axr.set_ylabel("当月新增流通市值（亿元）", color="#1f77b4", fontsize=11)
    axr.tick_params(axis="y", labelcolor="#1f77b4")
    axr.spines["right"].set_color("#1f77b4")
    axr2.set_ylabel("沪深300 收盘", color="#888", fontsize=10)
    axr2.tick_params(axis="y", labelcolor="#888")
    axr2.spines["right"].set_color("#bbb")

    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.xaxis.set_minor_locator(mdates.MonthLocator(bymonth=[4, 7, 10]))
    span = hs_dates[-1] - hs_dates[0]
    ax.set_xlim(hs_dates[0], hs_dates[-1] + span * 0.02)

    total_new = int(d["new_count"].sum())
    peak_cnt = int(d["new_count"].max())
    peak_cnt_d = d.filter(pl.col("new_count") == peak_cnt)["month"][0]
    peak_ffmc = d["ffmc_sum"].max()
    peak_ffmc_d = d.filter(pl.col("ffmc_sum") == peak_ffmc)["month"][0]
    hs_latest = hs_close[-1]
    ax.text(0.99, 0.97,
            f"区间 {months[0].strftime('%Y-%m')} ~ {months[-1].strftime('%Y-%m')}\n"
            f"累计新上市 {total_new:,} 只\n"
            f"单月新股峰值 {peak_cnt} 只 @ {peak_cnt_d.strftime('%Y-%m')}\n"
            f"单月流通市值峰值 {peak_ffmc / 1e8:,.0f} 亿 @ {peak_ffmc_d.strftime('%Y-%m')}\n"
            f"沪深300 最新 {hs_latest:,.0f}",
            transform=ax.transAxes, ha="right", va="top",
            fontsize=10, color="#222", fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.4", fc="white", ec="#bbb", alpha=0.9))

    ax.set_title(
        f"沪深两市每月新上市股票数 / 新增流通市值 vs 沪深300 · "
        f"{hs_dates[0].strftime('%Y-%m-%d')} ~ {hs_dates[-1].strftime('%Y-%m-%d')}",
        fontsize=13, fontweight="bold")

    lines_l, labels_l = ax.get_legend_handles_labels()
    lines_r, labels_r = axr.get_legend_handles_labels()
    lines_r2, labels_r2 = axr2.get_legend_handles_labels()
    ax.legend(lines_l + lines_r + lines_r2, labels_l + labels_r + labels_r2,
              loc="upper left", fontsize=9, ncol=3)

    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=130, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"Saved to {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path,
                        default=Path("/mnt/dataset/stock_quote_history"))
    parser.add_argument("--hs300-file", type=Path,
                        default=Path("/mnt/dataset/index_quote_history/000300.parquet"))
    parser.add_argument("--output", type=Path,
                        default=Path("/mnt/dataset/market_stock_count.png"))
    parser.add_argument("--start-date", type=str, default=None,
                        help="起始日期（默认按沪深300起始；可传更晚日期收窄范围）")
    parser.add_argument("--end-date", type=str, default=None,
                        help="结束日期（默认按沪深300最新；可传更早日收窄范围）")
    args = parser.parse_args()

    hs300 = load_hs300_close(args.hs300_file)
    start = hs300["date"].min()
    end = hs300["date"].max()
    if args.start_date:
        start = max(start, date.fromisoformat(args.start_date))
    if args.end_date:
        end = min(end, date.fromisoformat(args.end_date))
    print(f"时间范围（按沪深300）：{start} ~ {end}")

    first = load_ipo_firstday(args.data_dir)
    # 排除北交所/三板（code 首位 4/8，或 920 段）：数据覆盖不全且独立于沪深两市。
    before = first.height
    first = first.filter(
        ~(pl.col("code").str.slice(0, 1).is_in(["4", "8"])
          | pl.col("code").str.starts_with("920")))
    print(f"排除北交所/三板 {before - first.height} 只，剩余 {first.height} 只")

    first = first.filter((pl.col("date") >= start) & (pl.col("date") <= end))
    hs300 = hs300.filter((pl.col("date") >= start) & (pl.col("date") <= end))

    d = monthly_agg(first)
    print(f"月度聚合：{len(d)} 行（{d['month'].min()} ~ {d['month'].max()}）")
    if not d.is_empty():
        print(f"  累计新上市 {d['new_count'].sum():,} 只 · "
              f"单月新股峰值 {d['new_count'].max()} 只")
    plot(d, hs300, args.output)


if __name__ == "__main__":
    main()
