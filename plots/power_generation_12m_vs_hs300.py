"""发电量每月新增额（12 月滚动合计）vs 沪深300（探查图）。

直接读 /mnt/readonly_dataset/gov_stats/发电量/{year}.xlsx（1990-2026，缺 1994/1996）。
源有累计值（亿千瓦时）和累计增长(%)。由累计值年内差分得当月发电量：
  每月新增额[t] = 累计值[t] − 累计值[t−1]（3-12 月，年内差分不跨年）
  每月新增额[1月] = 每月新增额[2月] = 累计值[2月] / 2（1-2 月合并平分）

12 月滚动合计（亿千瓦时），叠加沪深300。无同比子图。
"""
from __future__ import annotations

import argparse
import re
from datetime import date
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import polars as pl
from python_calamine import CalamineWorkbook

_MONTH_RE = re.compile(r"(\d{4})年(\d{1,2})月")


def _parse_month(s: str) -> date | None:
    m = _MONTH_RE.search(str(s))
    return date(int(m.group(1)), int(m.group(2)), 1) if m else None


def load_power(src_dir: Path) -> pl.DataFrame:
    rows: list[dict] = []
    for fp in sorted(src_dir.iterdir()):
        if fp.suffix.lower() != ".xlsx":
            continue
        sh = CalamineWorkbook.from_path(fp).get_sheet_by_index(0).to_python()
        header = None
        data_start = 0
        for i, r in enumerate(sh):
            if r and str(r[0]).strip() == "指标":
                header = r
                data_start = i + 1
                break
        if header is None:
            continue
        months = [_parse_month(c) for c in header[1:]]
        for r in sh[data_start:]:
            if not r or not r[0]:
                continue
            name = re.sub(r"\s+", "", str(r[0]))
            if "发电量累计值" not in name:
                continue
            for j, mo in enumerate(months):
                if mo is None or j + 1 >= len(r):
                    continue
                try:
                    v = float(r[j + 1])
                except (TypeError, ValueError):
                    continue
                rows.append({"date": mo, "acc": v})
            break  # 只取第一行累计值
    acc = pl.DataFrame(rows).unique("date").sort("date")
    # 完整月历 + 1 月用 2 月累计/2 填充
    full = pl.DataFrame({"date": pl.date_range(acc["date"].min(), acc["date"].max(),
                                               "1mo", eager=True)})
    acc = full.join(acc, on="date", how="left")
    acc = acc.with_columns(pl.col("date").dt.year().alias("_y"),
                           pl.col("date").dt.month().alias("_m"))
    feb = (acc.filter(pl.col("_m") == 2).select("_y", pl.col("acc").alias("_feb"))
             .group_by("_y").agg(pl.col("_feb").first()))
    acc = acc.join(feb, on="_y", how="left")
    cond = (pl.col("_m") == 1) & pl.col("acc").is_null() & pl.col("_feb").is_not_null()
    acc = acc.with_columns(pl.when(cond).then(pl.col("_feb") / 2).otherwise(pl.col("acc")).alias("_acc"))
    acc = acc.with_columns(pl.col("_acc").diff().over("_y").alias("_diff"))
    monthly = (acc.with_columns(pl.when(pl.col("_m") == 1).then(pl.col("_acc"))
                               .otherwise(pl.col("_diff")).alias("monthly"))
                  .with_columns(pl.col("date").dt.strftime("%Y-%m").alias("date_str")))
    return monthly.with_columns(
        pl.col("monthly").rolling_sum(12).alias("m12_亿千瓦时"),
    ).with_columns(
        ((pl.col("m12_亿千瓦时") / pl.col("m12_亿千瓦时").shift(12) - 1) * 100).alias("m12_yoy"),
    )


def load_hs300(index_file: Path) -> pl.DataFrame:
    return (pl.read_parquet(index_file, columns=["date", "close"])
              .with_columns(pl.col("date").str.to_date("%Y-%m-%d").alias("d"))
              .sort("d")
              .group_by(pl.col("d").dt.strftime("%Y-%m").alias("date"))
              .agg(pl.col("close").last().alias("hs300"))
              .with_columns(pl.col("date").str.to_date("%Y-%m"))
              .sort("date"))


def plot(d: pl.DataFrame, hs300: pl.DataFrame, output_png: Path) -> None:
    plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "WenQuanYi Zen Hei"]
    plt.rcParams["axes.unicode_minus"] = False
    dates = pl.Series(d["date_str"]).str.to_date("%Y-%m")

    fig, ax = plt.subplots(figsize=(13, 6))

    ax.plot(dates, d["m12_yoy"], color="#d62728", lw=1.8,
            label="发电量滚动12月合计同比（左轴）")
    ax.fill_between(dates, 0, d["m12_yoy"], where=(d["m12_yoy"] >= 0),
                    color="#d62728", alpha=0.10)
    ax.fill_between(dates, 0, d["m12_yoy"], where=(d["m12_yoy"] < 0),
                    color="#1f77b4", alpha=0.12)
    ax.axhline(0, color="black", lw=0.5)
    ax.set_ylabel("同比 %")
    ax.set_title("发电量滚动 12 月合计同比 vs 沪深300")
    ax.grid(True, alpha=0.3)
    axr = ax.twinx()
    axr.plot(hs300["date"], hs300["hs300"], color="#2ca02c", lw=1.0, alpha=0.7,
             label="沪深300月末收盘（右轴）")
    axr.set_ylabel("沪深300", color="#2ca02c")
    axr.tick_params(axis="y", labelcolor="#2ca02c")
    ll, lnl = ax.get_legend_handles_labels()
    lr, lnr = axr.get_legend_handles_labels()
    ax.legend(ll + lr, lnl + lnr, loc="upper left", fontsize=9)

    ax.set_xlim(date(1995, 1, 1), dates.max())
    ax.xaxis.set_major_locator(mdates.YearLocator(2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    fig.autofmt_xdate()
    plt.tight_layout()
    output_png.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_png, dpi=130)
    plt.close(fig)
    print(f"Saved to {output_png}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--src-dir", type=Path,
        default=Path("/mnt/readonly_dataset/gov_stats/发电量"),
        help="发电量年度文件目录",
    )
    parser.add_argument(
        "--index-file", type=Path,
        default=Path("/mnt/dataset/index_quote_history/000300.parquet"),
        help="沪深300 parquet 路径",
    )
    parser.add_argument(
        "--output", type=Path,
        default=Path("/mnt/dataset/power_generation_12m_vs_hs300.png"),
        help="输出 PNG 路径",
    )
    args = parser.parse_args()
    d = load_power(args.src_dir)
    hs300 = load_hs300(args.index_file)
    print(f"power: {len(d)} rows, {d['date_str'].min()} -> {d['date_str'].max()}")
    plot(d, hs300, args.output)


if __name__ == "__main__":
    main()
