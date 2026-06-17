"""SHIBOR 3M 利率 vs 沪深300 双轴图。

SHIBOR 原始数据：/mnt/readonly_dataset/shibor/shibor/{year}.csv（≤2025）/ .xls（2026，实为 xlsx）。
列名跨格式不一致（CSV 用 3m，XLS 用 3M），日期格式也不同（CSV: 2026-06-16；XLS: 16 Jun 2026）。
本脚本统一为 `rate_3m` 列。
"""
from __future__ import annotations

import argparse
import re
import zipfile
from datetime import date, datetime
from pathlib import Path
from xml.etree import ElementTree as ET

import matplotlib.dates as mdates
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import polars as pl
from matplotlib.transforms import blended_transform_factory

_XLSX_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _load_shibor_csv(path: Path) -> pl.DataFrame:
    """读 SHIBOR CSV（列名：date,on,1w,2w,1m,3m,6M,9M,1Y）."""
    df = pl.read_csv(path)
    if "3m" not in df.columns:
        return pl.DataFrame()
    return df.select([
        pl.col("date").str.to_date("%Y-%m-%d").alias("date"),
        pl.col("3m").cast(pl.Float64).alias("rate_3m"),
    ])


def _load_shibor_xls(path: Path) -> pl.DataFrame:
    """读 SHIBOR XLS（实为 xlsx；列名：Date,O/N,...,3M,...；日期格式 '16 Jun 2026'）."""
    with zipfile.ZipFile(path) as z:
        shared = z.read("xl/sharedStrings.xml").decode("utf-8")
        strings = re.findall(r"<t[^>]*>([^<]*)</t>", shared)
        root = ET.fromstring(z.read("xl/worksheets/sheet1.xml").decode("utf-8"))

    # 第一行是表头，定位 3M 列索引
    rows = list(root.iter(f"{_XLSX_NS}row"))
    header = []
    for c in list(rows[0]):
        v = c.find(f"{_XLSX_NS}v")
        t = c.attrib.get("t")
        header.append(strings[int(v.text)] if (v is not None and t == "s") else (v.text if v is not None else ""))
    try:
        col_3m = header.index("3M")
    except ValueError:
        return pl.DataFrame()
    col_date = header.index("Date")

    records = []
    for row in rows[1:]:
        cells = list(row)
        if len(cells) <= max(col_date, col_3m):
            continue

        def cell_text(i):
            v = cells[i].find(f"{_XLSX_NS}v")
            t = cells[i].attrib.get("t")
            if v is None:
                return ""
            return strings[int(v.text)] if t == "s" else v.text

        d_str = cell_text(col_date)
        r_str = cell_text(col_3m)
        if not d_str or not r_str:
            continue
        try:
            d = datetime.strptime(d_str, "%d %b %Y").date()
            r = float(r_str)
        except ValueError:
            continue
        records.append({"date": d, "rate_3m": r})

    return pl.DataFrame(records)


def load_shibor_3m(data_path: Path) -> pl.DataFrame:
    """读所有 SHIBOR 年度文件，返回 date + rate_3m."""
    src = data_path / "shibor" / "shibor"
    dfs = []
    for year in range(2013, 2027):
        csv_file = src / f"{year}.csv"
        xls_file = src / f"{year}.xls"
        if csv_file.exists():
            df = _load_shibor_csv(csv_file)
        elif xls_file.exists():
            df = _load_shibor_xls(xls_file)
        else:
            continue
        if df.height > 0:
            dfs.append(df)
    combined = pl.concat(dfs).unique(subset=["date"]).sort("date")
    return combined


def load_hs300(index_file: Path) -> pl.DataFrame:
    return (
        pl.read_parquet(index_file, columns=["date", "close"])
        .with_columns(pl.col("date").str.to_date("%Y-%m-%d").alias("date"))
        .sort("date")
    )


def plot(shibor: pl.DataFrame, hs300: pl.DataFrame, output_png: Path) -> None:
    # 只保留 SHIBOR 起始日期之后的 CSI300，避免左边一段没有 SHIBOR 对照
    shibor_start = shibor["date"].min()
    hs300 = hs300.filter(pl.col("date") >= shibor_start)

    fig, ax_left = plt.subplots(figsize=(15, 7))
    ax_right = ax_left.twinx()

    line_shibor, = ax_left.plot(
        shibor["date"].to_list(), shibor["rate_3m"].to_list(), "-",
        color="#1f77b4", linewidth=1.2, label="SHIBOR 3M (LHS, %)",
    )
    line_hs300, = ax_right.plot(
        hs300["date"].to_list(), hs300["close"].to_list(), "-",
        color="#d62728", linewidth=0.6, alpha=0.75, label="CSI300 close (RHS)",
    )

    trans = blended_transform_factory(ax_left.transData, ax_left.transAxes)
    events = [
        (date(2013, 6, 1), "2013 cash crunch"),
        (date(2015, 6, 1), "2015 crash"),
        (date(2018, 4, 1), "2018 deleveraging"),
        (date(2020, 3, 1), "2020 COVID"),
        (date(2022, 4, 1), "2022 lockdown"),
        (date(2024, 9, 1), "2024 policy pivot"),
    ]
    for d, label in events:
        ax_left.axvline(d, color="purple", linestyle="--", linewidth=0.4, alpha=0.35)
        ax_left.text(
            d, 0.03, f" {label}", color="purple", fontsize=8,
            rotation=90, va="bottom", transform=trans,
        )

    ax_left.set_xlabel("Date")
    ax_left.set_ylabel("SHIBOR 3M (%)", color="#1f77b4")
    ax_left.tick_params(axis="y", labelcolor="#1f77b4")
    ax_right.set_ylabel("CSI300 close (CNY)", color="#d62728")
    ax_right.tick_params(axis="y", labelcolor="#d62728")

    ax_left.set_title("SHIBOR 3M Interbank Rate vs CSI300 Index")
    ax_left.grid(True, alpha=0.3)
    ax_left.xaxis.set_major_locator(mdates.YearLocator(1))
    ax_left.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    ax_left.legend(
        handles=[line_shibor, line_hs300],
        loc="upper right", fontsize=9,
    )

    plt.tight_layout()
    output_png.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_png, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved to {output_png}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-path", type=Path,
        default=Path("/mnt/readonly_dataset"),
        help="只读原始数据根目录",
    )
    parser.add_argument(
        "--index-file", type=Path,
        default=Path("/mnt/dataset/index_quote_history/000300.parquet"),
        help="沪深300 parquet 文件",
    )
    parser.add_argument(
        "--output", type=Path,
        default=Path("/mnt/dataset/shibor_3m_vs_hs300.png"),
        help="输出 PNG 路径",
    )
    args = parser.parse_args()

    shibor = load_shibor_3m(args.data_path)
    hs300 = load_hs300(args.index_file)
    print(f"SHIBOR 3M: {shibor['date'].min()} ~ {shibor['date'].max()}, {shibor.height} rows")
    print(f"  range: {shibor['rate_3m'].min():.4f}% ~ {shibor['rate_3m'].max():.4f}%")
    print(f"CSI300:   {hs300['date'].min()} ~ {hs300['date'].max()}, {hs300.height} rows")
    plot(shibor, hs300, args.output)


if __name__ == "__main__":
    main()
