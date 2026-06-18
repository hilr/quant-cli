"""行业成交额-涨幅方块热力图（HS300 + CSI500 成分股）

数据源：
- 行业分类：/mnt/readonly_dataset/csindex/industry/{date}.xlsx
- HS300/CSI500 成分：/mnt/readonly_dataset/csindex/index_weight/{000300,000905}/{date}.xlsx
  注意：这些 .xlsx 实际是 OLE .xls 二进制格式（中证官网下载的伪装样子）
- 当日行情：/mnt/readonly_dataset/eastmoney/stock_quote/{date}.csv

方块按中证行业聚集，方块大小 ∝ 当日成交额，颜色 ∝ 当日涨幅（A股惯例红涨绿跌）。
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
WEIGHT_BASE_DIR = "csindex/index_weight"
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
TITLE_H = 3.5
INNER_PAD = 0.8
TEXT_AREA_THRESHOLD = 1.2


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
    """最新一份行业分类表 → [code, name, industry]。level=1/2/3 对应中证一/二/三级行业简称。"""
    ind_dir = data_path / INDUSTRY_DIR_NAME
    files = sorted(ind_dir.glob("*.xlsx"))
    if not files:
        raise FileNotFoundError(f"找不到行业分类 xlsx: {ind_dir}")
    rows = _read_sheet(files[-1])
    col_industry = 1 + level * 2  # 一级简称在 col 3，二级在 col 5，三级在 col 7

    records = []
    for r in rows[1:]:
        if len(r) <= col_industry:
            continue
        code, name, industry = r[0], r[1], r[col_industry]
        if code and industry:
            records.append({"code": str(code), "name": name, "industry": industry})
    return pl.DataFrame(records)


def load_constituents(data_path: Path) -> pl.DataFrame:
    """HS300 + CSI500 最新月度成分股 → [code, index]。同时属两指数以 HS300 为准。"""
    records = []
    for idx_code, idx_name in [("000300", "HS300"), ("000905", "CSI500")]:
        d = data_path / WEIGHT_BASE_DIR / idx_code
        files = sorted(d.glob("*.xlsx"))
        if not files:
            raise FileNotFoundError(f"找不到权重文件: {d}")
        rows = _read_sheet(files[-1])
        for r in rows[1:]:
            # 成份券代码在第 5 列（index 4）
            if len(r) > 4 and r[4]:
                records.append({"code": str(r[4]), "index": idx_name})
    df = pl.DataFrame(records)
    # HS300 排在 CSI500 前，unique keep=first 即保留 HS300 优先
    return df.sort("index").unique(subset=["code"], keep="first")


def load_quote(data_path: Path, target_date: str) -> pl.DataFrame:
    """指定日期行情 → [code(6位字符串), name, turnover, pct_chg]。"""
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
        .select(["code", "name", "turnover", "pct_chg"])
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


def render(df: pl.DataFrame, target_date: str, level: int, output: Path) -> None:
    plt.rcParams["font.sans-serif"] = CJK_FONTS
    plt.rcParams["axes.unicode_minus"] = False

    fig, ax = plt.subplots(figsize=(22, 13), dpi=120)
    fig.patch.set_facecolor("white")
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")

    level_name = {1: "一级", 2: "二级", 3: "三级"}[level]
    ax.set_title(
        f"市场全景热力图 · {target_date} · 中证{level_name}行业 · HS300+CSI500\n"
        f"方块大小=成交额  颜色=涨跌幅（红涨绿跌）  共 {df.height} 只",
        fontsize=15, pad=18,
    )

    industries = (
        df.group_by("industry")
        .agg([
            pl.col("turnover").sum().alias("total_turnover"),
            pl.col("pct_chg").mean().alias("avg_chg"),
            pl.len().alias("count"),
        ])
        .sort("total_turnover", descending=True)
    )

    ind_norm = squarify.normalize_sizes(industries["total_turnover"].to_list(), 100, 100)
    ind_rects = squarify.squarify(ind_norm, 0, 0, 100, 100)
    norm = Normalize(vmin=-COLOR_LIMIT, vmax=COLOR_LIMIT)

    for ind_row, rect in zip(industries.iter_rows(named=True), ind_rects):
        ind_name = ind_row["industry"]
        avg_chg = ind_row["avg_chg"]

        ax.add_patch(Rectangle(
            (rect["x"], rect["y"]), rect["dx"], rect["dy"],
            facecolor="#fafafa", edgecolor="#888", linewidth=1.0, zorder=1,
        ))

        title_color = "#8b1a1a" if avg_chg > 0.002 else ("#0d5a3f" if avg_chg < -0.002 else "#555")
        ax.text(
            rect["x"] + rect["dx"] / 2, rect["y"] + rect["dy"] - TITLE_H / 2,
            f"{ind_name}  {avg_chg*100:+.2f}%  ({ind_row['count']})",
            ha="center", va="center", fontsize=10.5, fontweight="bold",
            color=title_color, zorder=5,
        )

        sub = df.filter(pl.col("industry") == ind_name).sort("turnover", descending=True)
        if sub.height == 0:
            continue

        ix = rect["x"] + INNER_PAD
        iy = rect["y"] + INNER_PAD
        iw = rect["dx"] - 2 * INNER_PAD
        ih = rect["dy"] - 2 * INNER_PAD - TITLE_H
        if iw <= 0 or ih <= 0:
            continue
        iy += TITLE_H

        norm_sizes = squarify.normalize_sizes(sub["turnover"].to_list(), iw, ih)
        stock_rects = squarify.squarify(norm_sizes, ix, iy, iw, ih)
        chgs = sub["pct_chg"].to_list()
        names = sub["name"].to_list()

        for sr, chg, nm in zip(stock_rects, chgs, names):
            clamped = max(-COLOR_LIMIT, min(COLOR_LIMIT, chg))
            color = RED_GREEN_CMAP(norm(clamped))
            ax.add_patch(Rectangle(
                (sr["x"], sr["y"]), sr["dx"], sr["dy"],
                facecolor=color, edgecolor="white", linewidth=0.3, zorder=2,
            ))
            area = sr["dx"] * sr["dy"]
            if area > TEXT_AREA_THRESHOLD:
                # 文字颜色：底色深时用白，浅时用黑
                txt_color = "white" if abs(chg) > 0.04 else "#1a1a1a"
                fontsize = 8 if area > 4 else (6.5 if area > 2 else 5.5)
                ax.text(
                    sr["x"] + sr["dx"] / 2, sr["y"] + sr["dy"] / 2,
                    f"{nm}\n{chg*100:+.2f}%",
                    ha="center", va="center", fontsize=fontsize,
                    color=txt_color, zorder=3,
                )

    sm = plt.cm.ScalarMappable(cmap=RED_GREEN_CMAP, norm=norm)
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax, orientation="horizontal",
                        fraction=0.025, pad=0.02, aspect=50)
    cbar.set_label("当日涨跌幅", fontsize=10)
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
    parser.add_argument("--level", type=int, default=1, choices=[1, 2, 3],
                        help="行业层级：1=一级(约11类), 2=二级, 3=三级")
    parser.add_argument("--data-path", type=Path, default=Path("/mnt/readonly_dataset"),
                        help="只读原始数据根目录")
    parser.add_argument("--output", type=Path, default=None,
                        help="输出 PNG 路径（默认 /mnt/dataset/industry_heatmap_{date}_l{level}.png）")
    args = parser.parse_args()

    target_date = args.date or pick_latest_full_date(args.data_path)
    print(f"目标日期: {target_date}, 行业层级: 中证{ {1:'一',2:'二',3:'三'}[args.level] }级")

    industry = load_industry(args.data_path, args.level)
    print(f"行业分类: {industry.height} 只股票, {industry['industry'].n_unique()} 个行业")

    constituents = load_constituents(args.data_path)
    print(f"成分股: {constituents.height} 只 (HS300+CSI500)")

    quote = load_quote(args.data_path, target_date)
    print(f"行情: {quote.height} 条")

    df = (
        constituents.join(quote, on="code", how="inner")
        .join(industry.select(["code", "industry"]), on="code", how="left")
        .filter(pl.col("industry").is_not_null())
    )
    print(f"入图: {df.height} 只股票")

    if df.height == 0:
        raise RuntimeError("关联后无数据")

    output = args.output or Path(f"/mnt/dataset/industry_heatmap_{target_date}_l{args.level}.png")
    render(df, target_date, args.level, output)


if __name__ == "__main__":
    main()
