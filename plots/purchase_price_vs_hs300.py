"""工业生产者购进价格指数同比 vs 沪深300。

直接读 /mnt/readonly_dataset/gov_stats/工业生产者购进价格指数/ 下的年度文件
（2000-2022 csv、2023-2026 xlsx），取主指数及若干代表性原料子类，均以
(上年同月=100) 为基，值 −100 = 同比涨跌幅（%）：
- 工业生产者购进价格指数（总指数）
- 燃料、动力类
- 黑色金属材料类
- 有色金属材料和电线类
- 化工原料类

右轴叠加沪深300月末收盘。源文件另有农副产品、纺织原料、木材纸浆、建材、其它
等子类，此处取价格波动最大、对周期股最敏感的四个。

文件头部：csv 表头在第 1 行；xlsx 前 2 行是元数据、表头在第 3 行。月份乱序，按年月解析后排序。
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

# 指标匹配前缀 → 列名
_INDICATORS = [
    ("工业生产者购进价格指数", "ppi_purchase"),
    ("燃料、动力类", "fuel"),
    ("黑色金属材料类", "ferrous"),
    ("有色金属材料和电线类", "nonferrous"),
    ("化工原料类", "chemical"),
]
_MONTH_RE = re.compile(r"(\d{4})年(\d{1,2})月")


def _parse_month(s: str) -> date | None:
    m = _MONTH_RE.search(str(s))
    if not m:
        return None
    return date(int(m.group(1)), int(m.group(2)), 1)


def _match_indicator(name: str) -> str | None:
    name = name.strip()
    for prefix, col in _INDICATORS:
        if name.startswith(prefix):
            return col
    return None


def load_purchase(src_dir: Path) -> pl.DataFrame:
    rows: list[dict] = []
    for fp in sorted(src_dir.iterdir()):
        if fp.suffix.lower() == ".csv":
            with fp.open(encoding="utf-8") as f:
                lines = [ln.rstrip("\n") for ln in f if ln.strip()]
            header = lines[0].split(",")
            data_start = 1
        elif fp.suffix.lower() == ".xlsx":
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
            lines = [",".join("" if c is None else str(c) for c in r) for r in sh[data_start:]]
            data_start = 0
        else:
            continue
        months = [_parse_month(c) for c in header[1:]]
        for ln in lines[data_start:]:
            cells = ln.split(",")
            if len(cells) < 2:
                continue
            col = _match_indicator(cells[0])
            if col is None:
                continue
            for i, m in enumerate(months):
                if m is None or i + 1 >= len(cells):
                    continue
                try:
                    v = float(cells[i + 1])
                except ValueError:
                    continue
                rows.append({"date": m, "col": col, "v": v})
    return (pl.DataFrame(rows)
             .pivot(values="v", index="date", on="col")
             .sort("date"))


def load_hs300(index_file: Path) -> pl.DataFrame:
    return (pl.read_parquet(index_file, columns=["date", "close"])
              .with_columns(pl.col("date").str.to_date("%Y-%m-%d").alias("d"))
              .sort("d")
              .group_by(pl.col("d").dt.strftime("%Y-%m").alias("date"))
              .agg(pl.col("close").last().alias("hs300"))
              .with_columns(pl.col("date").str.to_date("%Y-%m"))
              .sort("date"))


def plot(p: pl.DataFrame, hs300: pl.DataFrame, output_png: Path) -> None:
    plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "WenQuanYi Zen Hei"]
    plt.rcParams["axes.unicode_minus"] = False

    series = [
        ("ppi_purchase", "购进总指数", "#1f77b4", 1.8),
        ("fuel", "燃料动力", "#d62728", 1.2),
        ("ferrous", "黑色金属", "#9467bd", 1.2),
        ("nonferrous", "有色金属", "#17becf", 1.2),
        ("chemical", "化工原料", "#ff7f0e", 1.2),
    ]

    fig, ax = plt.subplots(figsize=(13, 6.5))
    for col, lab, color, lw in series:
        ax.plot(p["date"], p[col] - 100, color=color, lw=lw, label=f"{lab} 同比（左轴）")
    total_yoy = p["ppi_purchase"] - 100
    ax.fill_between(p["date"], 0, total_yoy, where=(total_yoy >= 0),
                   color="#d62728", alpha=0.10)
    ax.fill_between(p["date"], 0, total_yoy, where=(total_yoy < 0),
                   color="#1f77b4", alpha=0.12)
    ax.axhline(0, color="black", lw=0.5)

    axr = ax.twinx()
    axr.plot(hs300["date"], hs300["hs300"], color="#2ca02c", lw=1.0, alpha=0.7,
             label="沪深300月末收盘（右轴）")

    ax.set_title("工业生产者购进价格指数同比 vs 沪深300")
    ax.set_ylabel("同比 %")
    axr.set_ylabel("沪深300", color="#2ca02c")
    axr.tick_params(axis="y", labelcolor="#2ca02c")
    ax.set_xlim(date(2005, 1, 1), p["date"].max())
    ax.grid(True, alpha=0.3)

    lines_l, labels_l = ax.get_legend_handles_labels()
    lines_r, labels_r = axr.get_legend_handles_labels()
    ax.legend(lines_l + lines_r, labels_l + labels_r, loc="upper left", fontsize=9)

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
        default=Path("/mnt/readonly_dataset/gov_stats/工业生产者购进价格指数"),
        help="购进价格指数年度文件目录",
    )
    parser.add_argument(
        "--index-file", type=Path,
        default=Path("/mnt/dataset/index_quote_history/000300.parquet"),
        help="沪深300 parquet 路径",
    )
    parser.add_argument(
        "--output", type=Path,
        default=Path("/mnt/dataset/purchase_price_yoy_vs_hs300.png"),
        help="输出 PNG 路径",
    )
    args = parser.parse_args()
    p = load_purchase(args.src_dir)
    hs300 = load_hs300(args.index_file)
    print(f"purchase: {len(p)} rows, {p['date'].min()} -> {p['date'].max()}")
    print("nulls:", p.null_count().to_dicts()[0])
    plot(p, hs300, args.output)


if __name__ == "__main__":
    main()
