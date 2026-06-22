"""行业成交额占比 river 图（streamgraph，时序）。

每条带 = 一个中证二级行业的成交额占比，沿时间连续流动（weighted-wiggle 基线，
band 居中、扭曲最小）。每个行业一种固定颜色（按一级行业色相分组、组内二级用亮度
区分），同色 = 同行业，便于追踪单一行业的连贯演变。

数据源：finance_sina/stock_quote（实时源）+ eastmoney/stock_quote（历史归档）fallback。
"""
from __future__ import annotations

import argparse
import colorsys
from datetime import date, timedelta
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import polars as pl
from matplotlib.patches import Rectangle

from industry_common import (
    CJK_FONTS,
    INDUSTRY_DIR_NAME,
    MIN_FULL_ROWS,
    QUOTE_DIR_CANDIDATES,
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
            ])
            .with_columns([
                pl.lit(dt).alias("date"),
                (pl.col("turnover") / day_total * 100.0).alias("pct"),
            ])
            .select(["date", "l2_name", "pct"])
        )
    return pl.concat(records)


def _l2_palette(l2_order: list[tuple]) -> list[tuple]:
    """按一级行业分组配色：每组一个色相，组内二级用亮度区分。返回每个 l2 的 RGB。"""
    groups: list[tuple[str, list[str]]] = []
    cur = None
    for l1c, l1n, l2c, l2n in l2_order:
        if l1n != cur:
            groups.append((l1n, []))
            cur = l1n
        groups[-1][1].append(l2n)
    n_groups = len(groups)
    palette: dict[str, tuple] = {}
    for g, (l1n, members) in enumerate(groups):
        m_total = len(members)
        for m, l2n in enumerate(members):
            h = (g / n_groups) % 1.0
            light = 0.50 + (0.20 * (m / (m_total - 1)) if m_total > 1 else 0.0)
            palette[l2n] = colorsys.hls_to_rgb(h, light, 0.60)
    return [palette[p[3]] for p in l2_order]


def render(
    long: pl.DataFrame, l2_order: list[tuple], dates: list[str], output: Path
) -> None:
    plt.rcParams["font.sans-serif"] = CJK_FONTS
    plt.rcParams["axes.unicode_minus"] = False

    l2_names = [p[3] for p in l2_order]
    date_objs = [date.fromisoformat(d) for d in dates]
    x = mdates.date2num(date_objs)

    pct_wide = long.pivot("l2_name", index="date", values="pct").sort("date")

    def _select(df, fill):
        cols = []
        for name in l2_names:
            if name in df.columns:
                cols.append(pl.col(name))
            else:
                cols.append(pl.lit(fill).alias(name))
        return df.select(cols)

    pct_arr = _select(pct_wide, 0.0).fill_null(0.0).to_numpy()
    if pct_arr.ndim == 1:
        pct_arr = pct_arr.reshape(1, -1)
    Y = pct_arr.T  # (n_l2, n_dates)：stackplot 每行一个行业

    colors = _l2_palette(l2_order)

    fig = plt.figure(figsize=(20, 10), dpi=120)
    fig.patch.set_facecolor("white")
    ax = fig.add_axes([0.05, 0.10, 0.60, 0.74])
    ax.set_facecolor("white")
    ax.stackplot(x, *Y, baseline="weighted_wiggle", colors=colors,
                 edgecolor="white", linewidth=0.3)

    ax.set_xlim(x[0], x[-1])
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right", fontsize=9)
    ax.set_yticks([])  # weighted_wiggle 基线下 y 绝对值无意义
    for sp in ("left", "top", "right"):
        ax.spines[sp].set_visible(False)

    n = len(date_objs)
    start, end = dates[0], dates[-1]
    fig.text(
        0.35, 0.965,
        f"行业成交额占比 river 图 · {start} ~ {end}（{n} 个交易日）\n"
        f"每条带 = 一个中证二级行业的成交额占比（streamgraph 基线）；同色 = 同行业，按一级行业色相分组",
        ha="center", va="top", fontsize=12.5,
    )

    # 右侧图例：每个 l2 带色块，按一级分组，自上而下 = 河流自上而下
    ax_lg = fig.add_axes([0.685, 0.06, 0.30, 0.82])
    ax_lg.axis("off")
    ax_lg.set_xlim(0, 1)
    ax_lg.set_ylim(0, 1)
    ax_lg.text(0.0, 0.99, "行业（自上而下）", fontsize=9.5, fontweight="bold", va="top")
    y = 0.965
    prev_l1 = None
    for l1c, l1n, l2c, l2n in reversed(l2_order):
        if l1n != prev_l1:
            ax_lg.text(0.0, y, l1n, fontsize=9, fontweight="bold", va="top", color="#222")
            y -= 0.023
            prev_l1 = l1n
        c = colors[l2_names.index(l2n)]
        ax_lg.add_patch(Rectangle((0.02, y - 0.004), 0.045, 0.013,
                                  facecolor=c, edgecolor="none"))
        ax_lg.text(0.075, y, l2n, fontsize=7.5, va="top", color="#444")
        y -= 0.0175

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
