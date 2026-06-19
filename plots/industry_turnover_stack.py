"""行业成交额占比堆叠柱状图（时序）。

每根柱子 = 一个交易日，柱高 100% = 当日全市场成交额，按中证二级行业堆叠：
  - 段高 = 该行业成交额占全市场比例（%）
  - 段色 = 该行业成交额加权涨跌幅（红涨绿跌，±5% 截断）
行业顺序固定：按 (一级代码, 二级代码) 排序，一级分组在堆叠里连续。

数据源：finance_sina/stock_quote（实时源）+ eastmoney/stock_quote（历史归档）fallback。
"""
from __future__ import annotations

import argparse
import math
from datetime import date, timedelta
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import polars as pl
from matplotlib.colors import Normalize

from industry_heatmap import (
    CJK_FONTS,
    COLOR_LIMIT,
    INDUSTRY_DIR_NAME,
    MIN_FULL_ROWS,
    QUOTE_DIR_CANDIDATES,
    RED_GREEN_CMAP,
    _read_sheet,
    load_quote,
)

L2_NAME_COL = 5
L1_CODE_COL, L1_NAME_COL = 2, 3
L2_CODE_COL = 4


def load_industry_l2(data_path: Path) -> pl.DataFrame:
    """最新行业分类表 → [code, l1_code, l1_name, l2_code, l2_name]。"""
    ind_dir = data_path / INDUSTRY_DIR_NAME
    files = sorted(ind_dir.glob("*.xlsx"))
    if not files:
        raise FileNotFoundError(f"找不到行业分类 xlsx: {ind_dir}")
    rows = _read_sheet(files[-1])
    records = []
    for r in rows[1:]:
        if len(r) <= L2_NAME_COL:
            continue
        code, l1c, l1n, l2c, l2n = r[0], r[L1_CODE_COL], r[L1_NAME_COL], r[L2_CODE_COL], r[L2_NAME_COL]
        if code and l1n and l2n:
            records.append({
                "code": str(code),
                "l1_code": str(l1c), "l1_name": str(l1n),
                "l2_code": str(l2c), "l2_name": str(l2n),
            })
    return pl.DataFrame(records)


def fixed_l2_order(industry: pl.DataFrame) -> list[tuple]:
    """按 (一级代码, 二级代码) int 升序的 distinct 二级行业顺序 → 一级分组连续。"""
    pairs = (
        industry.select(["l1_code", "l1_name", "l2_code", "l2_name"])
        .unique()
        .sort([(pl.col("l1_code").cast(pl.Int64)), (pl.col("l2_code").cast(pl.Int64))])
    )
    return list(pairs.iter_rows())


def _collect_full_dates(data_path: Path) -> list[str]:
    """所有候选目录里行数 >= MIN_FULL_ROWS 的日期（升序，同日期靠前目录优先）。"""
    by_date: dict[str, Path] = {}
    for name in QUOTE_DIR_CANDIDATES:
        d = data_path / name
        if not d.exists():
            continue
        for f in d.glob("*.csv"):
            by_date.setdefault(f.stem, f)
    full = []
    for dt in sorted(by_date):
        with open(by_date[dt], "rb") as fp:
            n = sum(1 for _ in fp)
        if n >= MIN_FULL_ROWS:
            full.append(dt)
    return full


def pick_recent_dates(data_path: Path, days: int) -> list[str]:
    """最近 days 个日历日内的完整交易日（升序）。"""
    full = _collect_full_dates(data_path)
    if not full:
        raise RuntimeError("找不到完整行情文件")
    latest = date.fromisoformat(full[-1])
    cutoff = latest - timedelta(days=days)
    recent = [d for d in full if date.fromisoformat(d) >= cutoff]
    return recent or full[-1:]


def aggregate(industry: pl.DataFrame, data_path: Path, dates: list[str]) -> pl.DataFrame:
    """逐日按二级行业聚合 → 长表 [date, l2_name, pct, wchg]。"""
    records = []
    for dt in dates:
        q = load_quote(data_path, dt)
        df = q.join(industry, on="code", how="inner")
        day_total = df["turnover"].sum()
        if day_total <= 0:
            continue
        records.append(
            df.group_by("l2_name").agg([
                pl.col("turnover").sum().alias("turnover"),
                (pl.col("pct_chg") * pl.col("turnover")).sum().alias("_w"),
            ])
            .with_columns([
                pl.lit(dt).alias("date"),
                (pl.col("turnover") / day_total * 100.0).alias("pct"),
                (pl.col("_w") / pl.col("turnover")).alias("wchg"),
            ])
            .select(["date", "l2_name", "pct", "wchg"])
        )
    return pl.concat(records)


def render(
    long: pl.DataFrame, l2_order: list[tuple], dates: list[str], output: Path
) -> None:
    plt.rcParams["font.sans-serif"] = CJK_FONTS
    plt.rcParams["axes.unicode_minus"] = False

    l2_names = [p[3] for p in l2_order]
    date_objs = [date.fromisoformat(d) for d in dates]

    pct_wide = long.pivot("l2_name", index="date", values="pct").sort("date")
    wchg_wide = long.pivot("l2_name", index="date", values="wchg").sort("date")

    def _select(df, fill):
        cols = []
        for name in l2_names:
            if name in df.columns:
                cols.append(pl.col(name))
            else:
                cols.append(pl.lit(fill).alias(name))
        return df.select(cols)

    pct_arr = _select(pct_wide, 0.0).fill_null(0.0).to_numpy()
    wchg_arr = _select(wchg_wide, float("nan")).fill_null(float("nan")).to_numpy()
    if pct_arr.ndim == 1:
        pct_arr = pct_arr.reshape(1, -1)
        wchg_arr = wchg_arr.reshape(1, -1)

    norm = Normalize(vmin=-COLOR_LIMIT, vmax=COLOR_LIMIT)
    n = len(date_objs)
    bottom = np.zeros(n)

    fig = plt.figure(figsize=(20, 10), dpi=120)
    fig.patch.set_facecolor("white")
    ax = fig.add_axes([0.06, 0.12, 0.58, 0.72])
    ax.set_facecolor("#fafafa")

    for j in range(len(l2_names)):
        heights = pct_arr[:, j]
        chgs = wchg_arr[:, j]
        colors = []
        for c in chgs:
            if c != c:  # NaN
                colors.append("#e0e0e0")
            else:
                clamped = max(-COLOR_LIMIT, min(COLOR_LIMIT, float(c)))
                colors.append(RED_GREEN_CMAP(norm(clamped)))
        ax.bar(date_objs, heights, bottom=bottom, color=colors,
               width=0.8, edgecolor="white", linewidth=0.3)
        bottom += heights

    ax.set_ylim(0, 100)
    ax.set_ylabel("成交额占比 (%)", fontsize=11)
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right", fontsize=9)
    ax.grid(True, axis="y", alpha=0.25, linestyle="--")
    ax.set_axisbelow(True)

    start, end = dates[0], dates[-1]
    fig.text(
        0.35, 0.965,
        f"行业成交额占比堆叠图 · {start} ~ {end}（{n} 个交易日）\n"
        f"柱高 = 行业成交额占全市场比例（%）；颜色 = 成交额加权涨跌幅（红涨绿跌）；按一级行业分组、二级在组内排序",
        ha="center", va="top", fontsize=12.5,
    )

    # 左侧 colorbar
    cax = fig.add_axes([0.015, 0.16, 0.016, 0.64])
    sm = plt.cm.ScalarMappable(cmap=RED_GREEN_CMAP, norm=norm)
    sm.set_array([])
    cbar = fig.colorbar(sm, cax=cax, orientation="vertical")
    cbar.set_label("成交额加权涨跌幅", fontsize=10)
    ticks = [-0.05, -0.03, -0.01, 0, 0.01, 0.03, 0.05]
    cbar.set_ticks(ticks)
    cbar.set_ticklabels([f"{t*100:+.0f}%" for t in ticks])

    # 右侧行业顺序图例：自上而下 = 堆叠自上而下
    fig.text(0.685, 0.90, "行业顺序（自上而下）", fontsize=9.5, fontweight="bold", va="top")
    y = 0.875
    prev_l1 = None
    for l1c, l1n, l2c, l2n in reversed(l2_order):
        if l1n != prev_l1:
            fig.text(0.685, y, f"{l1n}", fontsize=9, fontweight="bold", va="top", color="#222")
            y -= 0.0215
            prev_l1 = l1n
        fig.text(0.695, y, l2n, fontsize=7.5, va="top", color="#555")
        y -= 0.0162

    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=120, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"Saved: {output}  ({n} 日 × {len(l2_names)} 个二级行业)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--days", type=int, default=30,
                        help="最近 N 个日历日内的完整交易日（默认 30）")
    parser.add_argument("--data-path", type=Path, default=Path("/mnt/readonly_dataset"),
                        help="只读原始数据根目录")
    parser.add_argument("--output", type=Path, default=None,
                        help="输出 PNG 路径（默认 /mnt/dataset/industry_turnover_stack_{end}.png）")
    args = parser.parse_args()

    industry = load_industry_l2(args.data_path)
    l2_order = fixed_l2_order(industry)
    print(f"行业表: {industry.height} 只股票, {len(l2_order)} 个二级行业（{len(set(p[1] for p in l2_order))} 个一级）")

    dates = pick_recent_dates(args.data_path, args.days)
    print(f"日期范围: {dates[0]} ~ {dates[-1]}（{len(dates)} 个交易日）")

    long = aggregate(industry, args.data_path, dates)
    print(f"聚合: {long.height} 条 (date × l2)")

    output = args.output or Path(f"/mnt/dataset/industry_turnover_stack_{dates[-1]}.png")
    render(long, l2_order, dates, output)


if __name__ == "__main__":
    main()
