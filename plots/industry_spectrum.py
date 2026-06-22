"""行业市场光谱图（单日对称双带：左涨右跌）

所有行业按涨跌分两边，竖向堆叠成左右两条色带，呈蝴蝶/对称布局：
- 左侧 = 上涨行业，顶部 = 最大涨幅，向下渐弱
- 右侧 = 下跌行业，顶部 = 最大跌幅，向下渐弱
- 两条色带的总高度 ∝ 该侧成交额 / 全市场成交额（保持资金权重比例）
- 色块颜色 = 加权涨跌幅（A 股惯例红涨绿跌）
- 行业名 + 涨跌幅 + 成交额 标在色块**外侧**（涨侧文字在左色块右边、跌侧文字在右色块左边），
  字号随色块高度自适应；过窄的小行业不标，避免重叠

数据源、数据加载与 industry_heatmap 一致，复用其 load_industry / load_quote /
pick_latest_full_date。默认输出最新交易日；--date 指定任意一天。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import polars as pl
from matplotlib.colors import Normalize
from matplotlib.patches import Rectangle

sys.path.insert(0, str(Path(__file__).resolve().parent))
from industry_heatmap import (
    CJK_FONTS, COLOR_LIMIT, RED_GREEN_CMAP,
    load_industry, load_quote, pick_latest_full_date,
)


def render(industries: pl.DataFrame, target_date: str, level: int, output: Path) -> None:
    """对称双带渲染：左涨右跌。"""
    plt.rcParams["font.sans-serif"] = CJK_FONTS
    plt.rcParams["axes.unicode_minus"] = False

    total = industries["total_turnover"].sum()
    gainers = (industries.filter(pl.col("weighted_chg") > 0)
               .sort("weighted_chg", descending=True))
    losers = (industries.filter(pl.col("weighted_chg") < 0)
              .sort("weighted_chg"))  # 升序：最负（跌幅最大）在前
    flats = industries.filter(pl.col("weighted_chg") == 0)

    g_total = gainers["total_turnover"].sum()
    l_total = losers["total_turnover"].sum()

    # 各侧高度 ∝ 全市场成交额（保持资金权重比例）；两侧都从顶部往下堆
    def make_recs(df: pl.DataFrame) -> list[dict]:
        recs = []
        y_cursor = 100.0
        for r in df.iter_rows(named=True):
            h = r["total_turnover"] / total * 100.0 if total > 0 else 0
            recs.append({**r, "height": h,
                         "y_top": y_cursor, "y_center": y_cursor - h / 2,
                         "y_bottom": y_cursor - h})
            y_cursor -= h
        return recs

    g_recs = make_recs(gainers)
    l_recs = make_recs(losers)

    color_norm = Normalize(vmin=-COLOR_LIMIT, vmax=COLOR_LIMIT)

    n = industries.height
    fig_h = max(10, min(28, n * 0.22 + 3))
    fig = plt.figure(figsize=(11, fig_h), dpi=130)
    fig.patch.set_facecolor("white")

    # 左右色带位置（x 0-100）
    L_STRIP_L, L_STRIP_R = 2.0, 7.0     # 左色带（涨）
    R_STRIP_L, R_STRIP_R = 93.0, 98.0   # 右色带（跌）
    STRIP_TOP, STRIP_BOT = 95.0, 4.0
    STRIP_SPAN = STRIP_TOP - STRIP_BOT

    ax = fig.add_axes([0.02, 0.02, 0.96, 0.96])
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")

    def map_y(v):  # v: 0-100 概念（100=顶）→ 实际 y
        return STRIP_BOT + v / 100.0 * STRIP_SPAN

    def draw_side(recs: list[dict], x_l: float, x_r: float,
                  label_side: str) -> tuple[int, int]:
        """画一侧色带 + 外侧标签。label_side='right' 或 'left'。"""
        labeled = 0
        for r in recs:
            chg = r["weighted_chg"]
            clamped = max(-COLOR_LIMIT, min(COLOR_LIMIT, chg))
            color = RED_GREEN_CMAP(color_norm(clamped))
            y_bot = map_y(r["y_bottom"])
            y_top = map_y(r["y_top"])
            ax.add_patch(Rectangle(
                (x_l, y_bot), x_r - x_l, y_top - y_bot,
                facecolor=color, edgecolor="white", linewidth=0.6, zorder=2,
            ))

            h = r["height"]
            to_yi = r["total_turnover"] / 1e8
            n_st = r["n_stocks"]
            cy = map_y(r["y_center"])
            if h > 3.0:
                fontsize, weight = 10.5, "bold"
                parts = (r["industry"], f"{chg*100:+.2f}%", f"{to_yi:.0f} 亿", f"{n_st} 只")
            elif h > 1.5:
                fontsize, weight = 9, "normal"
                parts = (r["industry"], f"{chg*100:+.2f}%", f"{to_yi:.0f} 亿", f"{n_st} 只")
            elif h > 0.7:
                fontsize, weight = 7.5, "normal"
                parts = (r["industry"], f"{chg*100:+.2f}%", f"{n_st} 只")
            elif h > 0.3:
                fontsize, weight = 6.5, "normal"
                parts = (r["industry"], f"{chg*100:+.2f}%")
            else:
                continue  # 过窄不标
            labeled += 1

            if label_side == "right":
                # 涨侧：文字在色块右侧，行业名靠色块
                label_x = x_r + 0.6
                text = "    ".join(parts)
                ha = "left"
            else:
                # 跌侧：文字在色块左侧，行业名靠色块 → 反转 parts 顺序
                label_x = x_l - 0.6
                text = "    ".join(reversed(parts))
                ha = "right"

            # 文字颜色：红涨绿跌
            if chg > 0.005:
                txt_color = "#b22222"
            elif chg < -0.005:
                txt_color = "#13795b"
            else:
                txt_color = "#555"
            ax.text(label_x, cy, text, ha=ha, va="center",
                    fontsize=fontsize, color=txt_color, fontweight=weight, zorder=3)
        return labeled, len(recs)

    g_labeled, g_total_n = draw_side(g_recs, L_STRIP_L, L_STRIP_R, "right")
    l_labeled, l_total_n = draw_side(l_recs, R_STRIP_L, R_STRIP_R, "left")

    # 顶/底方向标注（左右两侧）
    ax.text(L_STRIP_L, STRIP_TOP + 0.5, "▲ 最大涨幅", ha="left", va="bottom",
            fontsize=10, color="#b22222", fontweight="bold")
    ax.text(L_STRIP_L, STRIP_BOT - 0.5, "渐弱 ▼", ha="left", va="top",
            fontsize=9, color="#888")
    ax.text(R_STRIP_R, STRIP_TOP + 0.5, "最大跌幅 ▲", ha="right", va="bottom",
            fontsize=10, color="#13795b", fontweight="bold")
    ax.text(R_STRIP_R, STRIP_BOT - 0.5, "▼ 渐弱", ha="right", va="top",
            fontsize=9, color="#888")

    # 中间分隔线（视觉对称轴）
    ax.axvline(50, color="#ddd", lw=0.6, ls=":", alpha=0.6, zorder=1,
               ymin=0.02, ymax=0.98)

    # 中间对称统计面板：左涨 / 右跌 各 4 行
    g_n_stocks = int(gainers["n_stocks"].sum()) if g_total_n > 0 else 0
    l_n_stocks = int(losers["n_stocks"].sum()) if l_total_n > 0 else 0
    g_yi = g_total / 1e8
    l_yi = l_total / 1e8
    g_w_chg = ((gainers["weighted_chg"] * gainers["total_turnover"]).sum()
               / g_total * 100) if g_total > 0 else 0
    l_w_chg = ((losers["weighted_chg"] * losers["total_turnover"]).sum()
               / l_total * 100) if l_total > 0 else 0

    stats = [
        (f"{g_total_n} 个行业",      f"{l_total_n} 个行业"),
        (f"{g_n_stocks} 只股票",     f"{l_n_stocks} 只股票"),
        (f"{g_yi:.0f} 亿成交",       f"{l_yi:.0f} 亿成交"),
        (f"加权 {g_w_chg:+.2f}%",    f"加权 {l_w_chg:+.2f}%"),
    ]
    stats_top = 78.0
    row_h = 7.0
    # 头部
    ax.text(46, stats_top + row_h * 0.9, "▲ 涨", ha="right", va="center",
            fontsize=16, color="#b22222", fontweight="bold")
    ax.text(54, stats_top + row_h * 0.9, "跌 ▼", ha="left", va="center",
            fontsize=16, color="#13795b", fontweight="bold")
    for i, (g_stat, l_stat) in enumerate(stats):
        y = stats_top - i * row_h
        ax.text(46, y, g_stat, ha="right", va="center",
                fontsize=12, color="#b22222", fontweight="bold")
        ax.text(54, y, l_stat, ha="left", va="center",
                fontsize=12, color="#13795b", fontweight="bold")

    # 标题
    level_name = {1: "一", 2: "二", 3: "三", 4: "四"}[level]
    total_turnover_yi = total / 1e8
    mkt_chg = ((industries["weighted_chg"] * industries["total_turnover"]).sum()
               / total * 100)
    fig.text(
        0.5, 0.985,
        f"行业市场光谱 · {target_date} · 中证{level_name}级 · 全 A 股\n"
        f"左=最大涨幅，右=最大跌幅（各自向下渐弱），两侧总高 ∝ 该侧成交额 / 全市场，颜色 = 加权涨跌幅\n"
        f"共 {n} 个行业（涨 {g_total_n} / 跌 {l_total_n} / 平 {flats.height}）  "
        f"总成交额 {total_turnover_yi:.0f} 亿  "
        f"全市场加权 {mkt_chg:+.2f}%",
        ha="center", va="top", fontsize=11, fontweight="bold",
    )

    # 未标注小行业数（图底中间）
    unlabeled = n - g_labeled - l_labeled - flats.height
    if unlabeled > 0:
        fig.text(0.5, 0.03,
                 f"另有 {unlabeled} 个小行业未标（多为成交额占比 < 0.3% 的细分行业）",
                 ha="center", va="center", fontsize=8, color="#888", fontstyle="italic")

    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=130, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"Saved: {output}  (涨 {g_total_n} 标 {g_labeled} / "
          f"跌 {l_total_n} 标 {l_labeled}，全市场加权 {mkt_chg:+.2f}%)")


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
                        help="输出 PNG 路径（默认 /mnt/dataset/industry_spectrum_{date}_l{level}.png）")
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
            pl.len().alias("n_stocks"),
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

    output = args.output or Path(f"/mnt/dataset/industry_spectrum_{target_date}_l{args.level}.png")
    render(industries, target_date, args.level, output)


if __name__ == "__main__":
    main()
