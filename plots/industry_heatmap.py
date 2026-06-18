"""行业方块热力图

一个三级行业一个方块，方块大小 ∝ 行业内所有股票当日成交额合计，颜色 ∝ 行业成交额加权涨跌幅（A股惯例红涨绿跌）。
不限定股票范围，全部 A 股按行业聚合。

数据源：
- 行业分类：/mnt/readonly_dataset/csindex/industry/{date}.xlsx
- 当日行情：/mnt/readonly_dataset/eastmoney/stock_quote/{date}.csv
"""
from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path

import matplotlib.pyplot as plt
import polars as pl
import squarify
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


def render(industries: pl.DataFrame, target_date: str, level: int, output: Path) -> None:
    """单层 squarify 渲染行业热力图。"""
    plt.rcParams["font.sans-serif"] = CJK_FONTS
    plt.rcParams["axes.unicode_minus"] = False

    fig, ax = plt.subplots(figsize=(20, 12), dpi=120)
    fig.patch.set_facecolor("white")
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")

    level_name = {1: "一级", 2: "二级", 3: "三级", 4: "四级"}[level]
    total_turnover_yi = industries["total_turnover"].sum() / 1e8
    up = industries.filter(pl.col("weighted_chg") > 0).height
    down = industries.filter(pl.col("weighted_chg") < 0).height
    ax.set_title(
        f"行业全景热力图 · {target_date} · 中证{level_name}行业 · 全 A 股\n"
        f"方块大小=行业总成交额（共 {total_turnover_yi:.0f} 亿）  "
        f"颜色=成交额加权涨跌幅（红涨绿跌）  "
        f"{industries.height} 个行业（涨 {up} / 跌 {down}）",
        fontsize=14, pad=18,
    )

    sizes = industries["total_turnover"].to_list()
    norm_sizes = squarify.normalize_sizes(sizes, 100, 100)
    rects = squarify.squarify(norm_sizes, 0, 0, 100, 100)
    color_norm = Normalize(vmin=-COLOR_LIMIT, vmax=COLOR_LIMIT)

    for ind, rect in zip(industries.iter_rows(named=True), rects):
        chg = ind["weighted_chg"]
        clamped = max(-COLOR_LIMIT, min(COLOR_LIMIT, chg))
        color = RED_GREEN_CMAP(color_norm(clamped))

        ax.add_patch(Rectangle(
            (rect["x"], rect["y"]), rect["dx"], rect["dy"],
            facecolor=color, edgecolor="white", linewidth=1.5, zorder=2,
        ))

        # 文字：根据方块大小决定显示密度
        area = rect["dx"] * rect["dy"]
        if area < 0.3:
            continue  # 太小不标
        txt_color = "white" if abs(chg) > 0.04 else "#1a1a1a"
        center_x = rect["x"] + rect["dx"] / 2
        center_y = rect["y"] + rect["dy"] / 2

        turnover_yi = ind["total_turnover"] / 1e8
        if area > 15:
            # 大方块：行业名 + 涨幅 + 成交额 + 股票数
            ax.text(center_x, center_y + rect["dy"] * 0.18,
                    ind["industry"], ha="center", va="center",
                    fontsize=14, fontweight="bold", color=txt_color, zorder=3)
            ax.text(center_x, center_y,
                    f"{chg*100:+.2f}%", ha="center", va="center",
                    fontsize=20, fontweight="bold", color=txt_color, zorder=3)
            ax.text(center_x, center_y - rect["dy"] * 0.18,
                    f"{turnover_yi:.0f}亿  ({ind['count']}只)",
                    ha="center", va="center",
                    fontsize=10, color=txt_color, zorder=3)
        elif area > 4:
            ax.text(center_x, center_y + rect["dy"] * 0.12,
                    ind["industry"], ha="center", va="center",
                    fontsize=10, fontweight="bold", color=txt_color, zorder=3)
            ax.text(center_x, center_y - rect["dy"] * 0.12,
                    f"{chg*100:+.2f}%  {turnover_yi:.0f}亿",
                    ha="center", va="center",
                    fontsize=9, color=txt_color, zorder=3)
        elif area > 1:
            ax.text(center_x, center_y,
                    f"{ind['industry']}\n{chg*100:+.2f}%",
                    ha="center", va="center",
                    fontsize=8, color=txt_color, zorder=3)
        else:
            ax.text(center_x, center_y,
                    ind["industry"], ha="center", va="center",
                    fontsize=6.5, color=txt_color, zorder=3)

    sm = plt.cm.ScalarMappable(cmap=RED_GREEN_CMAP, norm=color_norm)
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax, orientation="horizontal",
                        fraction=0.025, pad=0.02, aspect=50)
    cbar.set_label("成交额加权涨跌幅", fontsize=10)
    ticks = [-0.05, -0.03, -0.01, 0, 0.01, 0.03, 0.05]
    cbar.set_ticks(ticks)
    cbar.set_ticklabels([f"{t*100:+.0f}%" for t in ticks])

    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=120, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"Saved: {output}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--date", type=str, default=None,
                        help="目标日期 YYYY-MM-DD（默认最新完整数据）")
    parser.add_argument("--level", type=int, default=3, choices=[1, 2, 3, 4],
                        help="行业层级：1=一级(约11类), 2=二级(约35), 3=三级(约90), 4=四级(约200)")
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

    # 关联行情 + 行业
    df = quote.join(industry_map, on="code", how="inner")
    print(f"匹配到行业: {df.height} / {quote.height} 条")

    # 按行业聚合：总成交额 + 成交额加权涨幅
    industries = (
        df.group_by("industry")
        .agg([
            pl.col("turnover").sum().alias("total_turnover"),
            (pl.col("pct_chg") * pl.col("turnover")).sum().alias("_weighted_sum"),
            pl.len().alias("count"),
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
