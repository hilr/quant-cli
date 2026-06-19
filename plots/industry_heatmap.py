"""行业方块热力图

二维布局：行 = 涨幅 tier（顶 = 高涨幅，底 = 大跌），行内列 = 按成交额降序（左 = 高）。
- 左上角：高涨幅 tier 中成交额最大的行业
- 左下角：大跌 tier 中成交额最大的行业
- 方块颜色 = 行业成交额加权涨跌幅（A股惯例红涨绿跌）
- 方块宽度 ∝ 行业总成交额（行高均匀，故面积 ∝ 成交额）

数据源：
- 行业分类：/mnt/readonly_dataset/csindex/industry/{date}.xlsx
- 当日行情：/mnt/readonly_dataset/eastmoney/stock_quote/{date}.csv
"""
from __future__ import annotations

import argparse
import math
import shutil
import tempfile
from pathlib import Path

import matplotlib.pyplot as plt
import polars as pl
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.patches import Rectangle

INDUSTRY_DIR_NAME = "csindex/industry"
QUOTE_DIR_NAME = "eastmoney/stock_quote"

MIN_FULL_ROWS = 4000
COLOR_LIMIT = 0.05

CJK_FONTS = [
    "Noto Sans SC", "WenQuanYi Zen Hei", "Source Han Sans SC",
    "Noto Sans CJK SC", "SimHei", "Microsoft YaHei", "Arial Unicode MS",
]

RED_GREEN_CMAP = LinearSegmentedColormap.from_list(
    "a_share_rg",
    ["#13795b", "#5fa583", "#c8e0d4", "#f5f5f5", "#e6c5c1", "#cf6b60", "#c0392b"],
)

OLE_MAGIC = b"\xd0\xcf\x11\xe0"


def _read_sheet(path: Path) -> list[list]:
    """用 calamine 读 xls/xlsx，处理 OLE .xls 伪装成 .xlsx 的情况。"""
    from python_calamine import CalamineWorkbook

    with open(path, "rb") as f:
        magic = f.read(4)
    if magic == OLE_MAGIC and path.suffix == ".xlsx":
        with tempfile.NamedTemporaryFile(suffix=".xls", delete=False) as tmp:
            shutil.copyfileobj(open(path, "rb"), tmp)
            tmp_path = tmp.name
        try:
            wb = CalamineWorkbook.from_path(tmp_path)
        finally:
            Path(tmp_path).unlink(missing_ok=True)
    else:
        wb = CalamineWorkbook.from_path(str(path))
    ws = wb.get_sheet_by_name(wb.sheet_names[0])
    return ws.to_python()


def load_industry(data_path: Path, level: int) -> pl.DataFrame:
    """最新一份行业分类表 → [code, industry]。level=1/2/3/4 对应中证一/二/三/四级行业简称。"""
    ind_dir = data_path / INDUSTRY_DIR_NAME
    files = sorted(ind_dir.glob("*.xlsx"))
    if not files:
        raise FileNotFoundError(f"找不到行业分类 xlsx: {ind_dir}")
    rows = _read_sheet(files[-1])
    col_industry = 1 + level * 2

    records = []
    for r in rows[1:]:
        if len(r) <= col_industry:
            continue
        code, industry = r[0], r[col_industry]
        if code and industry:
            records.append({"code": str(code), "industry": industry})
    return pl.DataFrame(records)


def load_quote(data_path: Path, target_date: str) -> pl.DataFrame:
    """指定日期行情 → [code(6位字符串), turnover, pct_chg]。"""
    f = data_path / QUOTE_DIR_NAME / f"{target_date}.csv"
    if not f.exists():
        raise FileNotFoundError(f"找不到行情文件: {f}")
    df = pl.read_csv(f, infer_schema_length=10000)
    return (
        df.with_columns([
            pl.col("code").cast(pl.Utf8).str.zfill(6).alias("code"),
            ((pl.col("close") - pl.col("prev_close")) / pl.col("prev_close")).alias("pct_chg"),
        ])
        .filter(pl.col("turnover") > 0)
        .filter(pl.col("pct_chg").is_not_null() & pl.col("pct_chg").is_finite())
        .select(["code", "turnover", "pct_chg"])
    )


def pick_latest_full_date(data_path: Path) -> str:
    """扫描 stock_quote 目录，取最新一份行数 >= MIN_FULL_ROWS 的日期。"""
    quote_dir = data_path / QUOTE_DIR_NAME
    for f in sorted(quote_dir.glob("*.csv"), reverse=True):
        with open(f, "rb") as fp:
            n = sum(1 for _ in fp)
        if n >= MIN_FULL_ROWS:
            return f.stem
    raise RuntimeError(f"找不到行数 >= {MIN_FULL_ROWS} 的完整行情文件")


def _draw_block(ax, x: float, y: float, w: float, h: float, ind: dict, color_norm) -> None:
    """画一个行业方块 + 文字。文字密度按方块大小自适应。

    x, y 是方块左下角的 matplotlib 坐标（y-up：0 在底部）。
    """
    chg = ind["weighted_chg"]
    clamped = max(-COLOR_LIMIT, min(COLOR_LIMIT, chg))
    color = RED_GREEN_CMAP(color_norm(clamped))
    ax.add_patch(Rectangle(
        (x, y), w, h,
        facecolor=color, edgecolor="white", linewidth=1.0, zorder=2,
    ))
    if w < 0.4 or h < 1.0:
        return  # 太小不画文字

    txt_color = "white" if abs(chg) > 0.04 else "#1a1a1a"
    turnover_yi = ind["total_turnover"] / 1e8
    cx = x + w / 2
    cy = y + h / 2

    # 文字密度按面积分档
    if w > 8 and h > 6:
        ax.text(cx, y + h * 0.72, ind["industry"],
                ha="center", va="center", fontsize=11, fontweight="bold",
                color=txt_color, zorder=3)
        ax.text(cx, cy, f"{chg*100:+.2f}%",
                ha="center", va="center", fontsize=15, fontweight="bold",
                color=txt_color, zorder=3)
        ax.text(cx, y + h * 0.18, f"{turnover_yi:.0f}亿",
                ha="center", va="center", fontsize=9.5,
                color=txt_color, zorder=3)
    elif w > 4 and h > 4:
        ax.text(cx, y + h * 0.68, ind["industry"],
                ha="center", va="center", fontsize=9, fontweight="bold",
                color=txt_color, zorder=3)
        ax.text(cx, y + h * 0.28, f"{chg*100:+.2f}%  {turnover_yi:.0f}亿",
                ha="center", va="center", fontsize=8,
                color=txt_color, zorder=3)
    elif w > 2 and h > 2:
        ax.text(cx, cy, f"{ind['industry']}\n{chg*100:+.2f}%",
                ha="center", va="center", fontsize=7.5,
                color=txt_color, zorder=3)
    elif w > 0.8 and h > 1.5:
        ax.text(cx, cy, ind["industry"],
                ha="center", va="center", fontsize=6.5,
                color=txt_color, zorder=3)
    elif w > 0.5:
        ax.text(cx, cy, ind["industry"][:2],
                ha="center", va="center", fontsize=5.5,
                color=txt_color, zorder=3)


def render(industries: pl.DataFrame, target_date: str, level: int, output: Path) -> None:
    """二维矩阵渲染：行=涨幅 tier；行内头部横向排、尾部 squarify 打包。"""
    plt.rcParams["font.sans-serif"] = CJK_FONTS
    plt.rcParams["axes.unicode_minus"] = False

    fig = plt.figure(figsize=(22, 13), dpi=120)
    fig.patch.set_facecolor("white")
    ax = fig.add_axes([0.06, 0.05, 0.93, 0.88])
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")

    level_name = {1: "一级", 2: "二级", 3: "三级", 4: "四级"}[level]
    total_turnover_yi = industries["total_turnover"].sum() / 1e8
    up = industries.filter(pl.col("weighted_chg") > 0).height
    down = industries.filter(pl.col("weighted_chg") < 0).height
    fig.text(
        0.525, 0.965,
        f"行业全景热力图 · {target_date} · 中证{level_name}行业 · 全 A 股\n"
        f"按成交额加权涨幅倒序自然换行 → 左上=最大涨幅，右下=最大跌幅  方块面积 ∝ 成交额  "
        f"共 {industries.height} 个行业（涨 {up} / 跌 {down}），总成交额 {total_turnover_yi:.0f} 亿",
        ha="center", va="top", fontsize=13,
    )

    # 按加权涨幅倒序，自然换行（行优先填充）。行高 ∝ 行内总成交额 → 跨行面积仍严格等比。
    # 空间顺序严格等于排序顺序：第一行 = 涨幅最大的一批，最后一行 = 跌幅最大的一批。
    color_norm = Normalize(vmin=-COLOR_LIMIT, vmax=COLOR_LIMIT)
    sorted_df = industries.sort("weighted_chg", descending=True)
    n = sorted_df.height
    n_cols = max(5, int(round(math.sqrt(n * 1.7))))
    n_rows = math.ceil(n / n_cols)
    rows = [sorted_df.slice(i * n_cols, n_cols) for i in range(n_rows)]

    total_all = sorted_df["total_turnover"].sum()
    row_heights = [r["total_turnover"].sum() / total_all * 100.0 for r in rows]

    y_cursor = 100.0
    for row_df, h in zip(rows, row_heights):
        row_total = row_df["total_turnover"].sum()
        y_bot = y_cursor - h
        x = 0.0
        for ind in row_df.iter_rows(named=True):
            w = ind["total_turnover"] / row_total * 100.0
            _draw_block(ax, x, y_bot, w, h, ind, color_norm)
            x += w
        y_cursor = y_bot

    # 左侧垂直 colorbar
    cax = fig.add_axes([0.012, 0.15, 0.028, 0.7])
    sm = plt.cm.ScalarMappable(cmap=RED_GREEN_CMAP, norm=color_norm)
    sm.set_array([])
    cbar = fig.colorbar(sm, cax=cax, orientation="vertical")
    cbar.set_label("成交额加权涨跌幅", fontsize=10)
    ticks = [-0.05, -0.03, -0.01, 0, 0.01, 0.03, 0.05]
    cbar.set_ticks(ticks)
    cbar.set_ticklabels([f"{t*100:+.0f}%" for t in ticks])

    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=120, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"Saved: {output}  (自然换行 {n_cols} 列 × {n_rows} 行, {industries.height} 个行业)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--date", type=str, default=None,
                        help="目标日期 YYYY-MM-DD（默认最新完整数据）")
    parser.add_argument("--level", type=int, default=3, choices=[1, 2, 3, 4],
                        help="行业层级：1=一级(约11类), 2=二级(约35), 3=三级(约94), 4=四级(约200)")
    parser.add_argument("--data-path", type=Path, default=Path("/mnt/readonly_dataset"),
                        help="只读原始数据根目录")
    parser.add_argument("--output", type=Path, default=None,
                        help="输出 PNG 路径（默认 /mnt/dataset/industry_heatmap_{date}_l{level}.png）")
    args = parser.parse_args()

    target_date = args.date or pick_latest_full_date(args.data_path)
    level_cn = {1: "一", 2: "二", 3: "三", 4: "四"}[args.level]
    print(f"目标日期: {target_date}, 行业层级: 中证{level_cn}级（全 A 股）")

    industry_map = load_industry(args.data_path, args.level)
    print(f"行业分类表: {industry_map.height} 只股票, {industry_map['industry'].n_unique()} 个行业")

    quote = load_quote(args.data_path, target_date)
    print(f"行情: {quote.height} 条")

    df = quote.join(industry_map, on="code", how="inner")
    print(f"匹配到行业: {df.height} / {quote.height} 条")

    industries = (
        df.group_by("industry")
        .agg([
            pl.col("turnover").sum().alias("total_turnover"),
            (pl.col("pct_chg") * pl.col("turnover")).sum().alias("_weighted_sum"),
        ])
        .with_columns(
            (pl.col("_weighted_sum") / pl.col("total_turnover")).alias("weighted_chg"),
        )
        .drop("_weighted_sum")
        .filter(pl.col("industry").is_not_null())
        .sort("total_turnover", descending=True)
    )
    print(f"入图: {industries.height} 个行业, "
          f"总成交额 {industries['total_turnover'].sum()/1e8:.0f} 亿")

    if industries.height == 0:
        raise RuntimeError("聚合后无数据")

    output = args.output or Path(f"/mnt/dataset/industry_heatmap_{target_date}_l{args.level}.png")
    render(industries, target_date, args.level, output)


if __name__ == "__main__":
    main()
