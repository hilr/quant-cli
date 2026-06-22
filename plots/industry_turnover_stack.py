"""行业成交额占比 river 图（streamgraph，时序）。

两种范围：
1. 默认（不加 --parent）：全市场**一级行业**成交额占比，100% = 全市场
2. 钻取（--parent <行业名>）：选定行业的**下一级**子行业成交额占比，
   100% = 该父行业。--parent 自动识别父级（l1 或 l2）：
   - 传一个一级行业名（如「工业」）→ 显示其二级子行业
   - 传一个二级行业名（如「工程机械」）→ 显示其三级子行业

x 轴只用交易日（跳过周末/节假日），sym 基线让河流总宽恒为 100%。
颜色用黄金角分布色相，相邻色带差距最大。

数据源：finance_sina/stock_quote（实时源）+ eastmoney/stock_quote（历史归档）fallback。
"""
from __future__ import annotations

import argparse
import colorsys
from datetime import date, timedelta
from pathlib import Path

import matplotlib.pyplot as plt
import polars as pl

from industry_common import (
    CJK_FONTS,
    INDUSTRY_DIR_NAME,
    MIN_FULL_ROWS,
    QUOTE_DIR_CANDIDATES,
    _read_sheet,
    load_quote,
)


def load_industry_full(data_path: Path) -> pl.DataFrame:
    """最新行业分类表 → [code, l1_code, l1_name, l2_code, l2_name, l3_code, l3_name]。"""
    ind_dir = data_path / INDUSTRY_DIR_NAME
    files = sorted(ind_dir.glob("*.xlsx"))
    if not files:
        raise FileNotFoundError(f"找不到行业分类 xlsx: {ind_dir}")
    rows = _read_sheet(files[-1])
    records = []
    for r in rows[1:]:
        if len(r) < 4:
            continue
        code = r[0]
        if not code:
            continue
        rec: dict = {"code": str(code)}
        for lvl in (1, 2, 3):
            ccol, ncol = lvl * 2, 1 + lvl * 2
            if len(r) > ncol and r[ccol] and r[ncol]:
                rec[f"l{lvl}_code"] = str(r[ccol])
                rec[f"l{lvl}_name"] = str(r[ncol])
        records.append(rec)
    return pl.DataFrame(records)


def resolve_scope(
    industry: pl.DataFrame, parent: str | None
) -> tuple[str | None, str | None, str, str, list[tuple]]:
    """确定钻取范围 → (filter_col, filter_val, target_name_col, scope_label, order)。

    - parent=None：全市场 l1 视图
    - parent 匹配 l1：钻取到 l2
    - parent 匹配 l2：钻取到 l3
    order = [(target_code, target_name)] 按代码 int 升序。
    """
    if parent is None:
        sub = (industry.select(["l1_code", "l1_name"]).unique()
               .sort(pl.col("l1_code").cast(pl.Int64)))
        return (None, None, "l1_name", "全市场 · 一级行业",
                list(sub.iter_rows()))

    found_level = None
    for lvl in (3, 2, 1):  # 优先深级（避免重名误判）
        if (industry.filter(pl.col(f"l{lvl}_name") == parent)).height > 0:
            found_level = lvl
            break
    if found_level is None:
        all_names = sorted({
            n for col in ("l1_name", "l2_name") for n in industry[col].to_list()
            if n is not None
        })
        raise SystemExit(f"未找到行业「{parent}」。可选：\n  " + " / ".join(all_names))
    if found_level == 3:
        raise SystemExit(f"「{parent}」已是三级行业，无下一级可展开")

    filter_col = f"l{found_level}_name"
    target_lvl = found_level + 1
    target_code_col = f"l{target_lvl}_code"
    target_name_col = f"l{target_lvl}_name"
    level_cn = {2: "二", 3: "三"}[target_lvl]
    scope_label = f"{parent} · {level_cn}级子行业"

    sub = (industry.filter(pl.col(filter_col) == parent)
           .select([target_code_col, target_name_col]).unique()
           .sort(pl.col(target_code_col).cast(pl.Int64)))
    return (filter_col, parent, target_name_col, scope_label,
            list(sub.iter_rows()))


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


def aggregate(
    industry: pl.DataFrame,
    data_path: Path,
    dates: list[str],
    filter_col: str | None,
    filter_val: str | None,
    target_name_col: str,
) -> pl.DataFrame:
    """逐日按目标行业聚合 → 长表 [date, target_name, pct]。

    filter_col 非空时：仅聚合该父行业的股票，分母 = 该父行业当日成交额；
    否则：聚合全市场，分母 = 全市场当日成交额。
    """
    records = []
    for dt in dates:
        q = load_quote(data_path, dt)
        df = q.join(industry, on="code", how="inner")
        if filter_col is not None:
            df = df.filter(pl.col(filter_col) == filter_val)
        day_total = df["turnover"].sum()
        if day_total <= 0:
            continue
        records.append(
            df.group_by(target_name_col).agg([
                pl.col("turnover").sum().alias("turnover"),
            ])
            .with_columns([
                pl.lit(dt).alias("date"),
                (pl.col("turnover") / day_total * 100.0).alias("pct"),
            ])
            .rename({target_name_col: "target_name"})
            .select(["date", "target_name", "pct"])
        )
    return pl.concat(records)


def _palette(order: list[tuple]) -> list[tuple]:
    """黄金角分布色相，相邻色带色相差距最大。"""
    out = []
    for i, _p in enumerate(order):
        h = (i * 0.618033988749895) % 1.0
        light = 0.60 if (i % 2 == 0) else 0.40
        out.append(colorsys.hls_to_rgb(h, light, 0.70))
    return out


def render(
    long: pl.DataFrame,
    order: list[tuple],
    dates: list[str],
    scope_label: str,
    output: Path,
) -> None:
    plt.rcParams["font.sans-serif"] = CJK_FONTS
    plt.rcParams["axes.unicode_minus"] = False

    names = [p[1] for p in order]
    date_objs = [date.fromisoformat(d) for d in dates]
    n_dates = len(date_objs)
    x = list(range(n_dates))

    pct_wide = long.pivot("target_name", index="date", values="pct").sort("date")

    def _select(df, fill):
        cols = []
        for name in names:
            if name in df.columns:
                cols.append(pl.col(name))
            else:
                cols.append(pl.lit(fill).alias(name))
        return df.select(cols)

    pct_arr = _select(pct_wide, 0.0).fill_null(0.0).to_numpy()
    if pct_arr.ndim == 1:
        pct_arr = pct_arr.reshape(1, -1)
    Y = pct_arr.T

    colors = _palette(order)

    fig = plt.figure(figsize=(20, 10), dpi=120)
    fig.patch.set_facecolor("white")
    ax = fig.add_axes([0.05, 0.08, 0.78, 0.84])
    ax.set_facecolor("white")
    ax.stackplot(x, *Y, baseline="sym", colors=colors,
                 edgecolor="none", linewidth=0)

    ax.set_xlim(0, n_dates - 1)
    ax.set_ylim(-50, 50)
    ax.margins(y=0)

    tick_step = 4
    tick_idx = list(range(0, n_dates, tick_step))
    labels = []
    prev_year = None
    for i in tick_idx:
        d = date_objs[i]
        if d.year != prev_year:
            labels.append(d.strftime("%Y-%m-%d"))
            prev_year = d.year
        else:
            labels.append(d.strftime("%m-%d"))
    ax.set_xticks(tick_idx)
    ax.set_xticklabels(labels)
    plt.setp(ax.get_xticklabels(), rotation=90, ha="center", va="top", fontsize=6)
    ax.tick_params(axis="x", pad=2, length=2)
    ax.set_yticks([-50, -25, 0, 25, 50])
    ax.set_yticklabels(["", "75%", "50%\n(中线)", "75%", ""])
    ax.yaxis.set_tick_params(labelsize=8, length=0, colors="#888")
    ax.grid(axis="y", color="#eee", lw=0.5, zorder=0)
    for sp in ("left", "top", "right"):
        ax.spines[sp].set_visible(False)

    # 行业名标在最后一天该 band 的中心 y 位置（右侧 y 轴旁）
    last_pct = Y[:, -1]
    cum = 0.0
    for i, name in enumerate(names):
        band_h = float(last_pct[i])
        center_y = -50 + cum + band_h / 2
        cum += band_h
        ax.annotate(
            name,
            xy=(n_dates - 1, center_y),
            xytext=(8, 0), textcoords="offset points",
            ha="left", va="center",
            fontsize=8.5, color="#222", fontweight="bold",
            annotation_clip=False,
        )

    n = len(date_objs)
    start, end = dates[0], dates[-1]
    fig.text(
        0.44, 0.965,
        f"{scope_label} · 成交额占比 river 图 · {start} ~ {end}（{n} 个交易日）\n"
        f"sym 基线：整体恒为 100%，对称居中；每条带 = 一个行业的成交额占比",
        ha="center", va="top", fontsize=12.5,
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=120, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"Saved: {output}  ({n} 日 × {len(names)} 个行业)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--days", type=int, default=30,
                        help="最近 N 个日历日内的完整交易日（默认 30）")
    parser.add_argument("--parent", type=str, default=None,
                        help="钻取模式：父行业名（一级行业 → 看二级；"
                             "二级行业 → 看三级）；不填则展示全市场一级行业")
    parser.add_argument("--data-path", type=Path, default=Path("/mnt/readonly_dataset"),
                        help="只读原始数据根目录")
    parser.add_argument("--output", type=Path, default=None,
                        help="输出 PNG 路径")
    args = parser.parse_args()

    industry = load_industry_full(args.data_path)
    filter_col, filter_val, target_name_col, scope_label, order = resolve_scope(
        industry, args.parent
    )

    print(f"范围: {scope_label}  行业数: {len(order)}")
    print(f"股票数: {industry.height}")

    dates = pick_recent_dates(args.data_path, args.days)
    print(f"日期范围: {dates[0]} ~ {dates[-1]}（{len(dates)} 个交易日）")

    long = aggregate(industry, args.data_path, dates,
                     filter_col, filter_val, target_name_col)
    print(f"聚合: {long.height} 条 (date × industry)")

    slug = f"sub_{args.parent}" if args.parent else "market"
    output = args.output or Path(
        f"/mnt/dataset/industry_turnover_stack_{slug}_{dates[-1]}.png"
    )
    render(long, order, dates, scope_label, output)


if __name__ == "__main__":
    main()
