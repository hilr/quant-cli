"""北向持股季度环比分析：筛选主动增持个股。

最近 8 个季度（YYYY-QQ 末）的 stock_northbound 持股记录 + 同期未复权/复权价
→ 算每只 A 股的：
  - 持股量环比、持股比例变化(pp)
  - 持股市值（持股量 × 未复权价）环比
  - 复权价环比（剔除股价被动影响的基准）
  - 主动增减 = 市值环比 − 复权价环比（≈ 持股量变化贡献）

对比窗口默认最新一期 vs 上一季度（2026-03-31 vs 2025-12-31），--cur/--prev 可调。

数据源：
  /mnt/readonly_dataset/exchange_hkex/stock_northbound/{YYYY-MM-DD}.csv
  /mnt/dataset/stock_quote_history/{code}.parquet       未复权
  /mnt/dataset/stock_quote_adjusted/{code}.parquet      前复权

输出：
  /mnt/dataset/northbound_holdings_qoq.csv   完整明细
  /mnt/dataset/northbound_holdings_qoq.png   散点 4 象限 + TopN
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import matplotlib.pyplot as plt
import polars as pl

QUARTER_ENDS = [
    "2024-09-30", "2024-12-31", "2025-03-31", "2025-06-30",
    "2025-09-30", "2025-12-31", "2026-03-31",
]
TRADING_DAYS_OFFSET = 14   # 季度末当天可能非交易日，向前回看这么多天找最近收盘

COLOR_BUY = "#d62728"      # 主动增持（红，中国市场习惯）
COLOR_SELL = "#31a354"     # 主动减持
COLOR_PASSIVE = "#ff7f0e"  # 被动增持
COLOR_FLAT = "#969696"     # 稳定


def load_holdings(data_path: Path) -> pl.DataFrame:
    """合并 8 期 stock_northbound，过滤 6 位 A 股代码。"""
    src = data_path / "exchange_hkex" / "stock_northbound"
    parts = []
    for d in QUARTER_ENDS:
        fp = src / f"{d}.csv"
        if not fp.exists():
            print(f"  跳过缺失：{fp}")
            continue
        parts.append(
            pl.read_csv(fp)
            .rename({"日期": "date", "证券代码": "code",
                     "证券名称": "name", "持股量": "shares",
                     "流通股占比": "free_float_pct"})
            .with_columns([
                pl.lit(d).alias("period"),
                pl.col("code").cast(pl.Utf8),
                pl.col("shares").cast(pl.Int64, strict=False),
                pl.col("free_float_pct").cast(pl.Float64, strict=False),
            ])
            # 仅保留 6 位代码（A 股：6/3/0/8 开头）
            .filter(pl.col("code").str.len_chars() == 6)
            .filter(pl.col("code").str.slice(0, 1).is_in(["6", "3", "0", "8"]))
        )
    df = pl.concat(parts, how="vertical_relaxed")
    # 同期同名取最新（去重）
    df = df.group_by(["period", "code"]).agg([
        pl.col("name").first(),
        pl.col("shares").sum(),
        pl.col("free_float_pct").sum(),
    ])
    return df.sort(["code", "period"])


def fetch_close(history_dir: Path, adjusted_dir: Path, code: str,
                period: str) -> dict:
    """查 code 在 period 当天（或最近 ≤ 14 天）的未复权/复权 close。

    返回 {'raw': ..., 'adj': ..., 'match_date': 'YYYY-MM-DD'}，缺失返回 {None...}
    """
    fp_raw = history_dir / f"{code}.parquet"
    fp_adj = adjusted_dir / f"{code}.parquet"
    if not fp_raw.exists() or not fp_adj.exists():
        return {"raw": None, "adj": None, "match_date": None}
    try:
        raw = pl.read_parquet(fp_raw, columns=["date", "close"])
        adj = pl.read_parquet(fp_adj, columns=["date", "close"])
    except Exception:
        return {"raw": None, "adj": None, "match_date": None}
    # 转 date 类型
    raw = raw.with_columns(pl.col("date").str.to_date("%Y-%m-%d")).sort("date")
    adj = adj.with_columns(pl.col("date").str.to_date("%Y-%m-%d")).sort("date")

    target = date.fromisoformat(period)
    # asof：取 ≤ target 的最后一行
    raw_b = raw.filter(pl.col("date") <= target).tail(1)
    adj_b = adj.filter(pl.col("date") <= target).tail(1)
    if raw_b.is_empty() or adj_b.is_empty():
        return {"raw": None, "adj": None, "match_date": None}
    md = raw_b["date"][0]
    # 防止回看到太久之前（>14 天说明该股票当时还没上市/已退市）
    if (target - md).days > TRADING_DAYS_OFFSET:
        return {"raw": None, "adj": None, "match_date": None}
    return {
        "raw": float(raw_b["close"][0]),
        "adj": float(adj_b["close"][0]),
        "match_date": md.isoformat(),
    }


def build_qoq_table(
    holdings: pl.DataFrame,
    history_dir: Path,
    adjusted_dir: Path,
    cur_period: str,
    prev_period: str,
) -> pl.DataFrame:
    """构造对比窗口的环比表。"""
    # 取当期 + 前期，inner join（两期都有持股的）
    cur = (
        holdings.filter(pl.col("period") == cur_period)
        .select(["code", "name",
                 pl.col("shares").alias("shares_cur"),
                 pl.col("free_float_pct").alias("pct_cur")])
    )
    prev = (
        holdings.filter(pl.col("period") == prev_period)
        .select(["code",
                 pl.col("shares").alias("shares_prev"),
                 pl.col("free_float_pct").alias("pct_prev")])
    )
    base = cur.join(prev, on="code", how="inner")

    # 对每只股票拉价格（cur + prev 各 1 次）
    print(f"  拉 {base.height} 只股票的 {cur_period} 和 {prev_period} 收盘价...")
    rows = []
    for r in base.iter_rows(named=True):
        code = r["code"]
        p_cur = fetch_close(history_dir, adjusted_dir, code, cur_period)
        p_prev = fetch_close(history_dir, adjusted_dir, code, prev_period)
        rows.append({
            "code": code,
            "raw_close_cur": p_cur["raw"],
            "adj_close_cur": p_cur["adj"],
            "match_cur": p_cur["match_date"],
            "raw_close_prev": p_prev["raw"],
            "adj_close_prev": p_prev["adj"],
            "match_prev": p_prev["match_date"],
        })
    prices = pl.DataFrame(rows)
    df = base.join(prices, on="code", how="left")

    # 计算环比字段
    df = df.with_columns([
        (pl.col("shares_cur") / pl.col("shares_prev") - 1.0)
        .alias("shares_qoq"),
        (pl.col("pct_cur") - pl.col("pct_prev")).alias("pct_chg_pp"),
        (pl.col("raw_close_cur") / pl.col("raw_close_prev") - 1.0)
        .alias("price_qoq_raw"),
        (pl.col("adj_close_cur") / pl.col("adj_close_prev") - 1.0)
        .alias("price_qoq_adj"),
    ])
    # 持股市值（亿元）
    df = df.with_columns([
        ((pl.col("shares_cur") * pl.col("raw_close_cur")) / 1e8)
        .alias("mv_cur_yi"),
        ((pl.col("shares_prev") * pl.col("raw_close_prev")) / 1e8)
        .alias("mv_prev_yi"),
    ])
    df = df.with_columns(
        (pl.col("mv_cur_yi") / pl.col("mv_prev_yi") - 1.0).alias("mv_qoq")
    )
    # 主动增减贡献：市值环比 − 复权价环比（拆开，polars 同 with_columns 内不能引用刚定义的列）
    df = df.with_columns(
        (pl.col("mv_qoq") - pl.col("price_qoq_adj")).alias("active_chg")
    )
    # 主动增减金额（亿元）= 持股量变化 × 当期未复权价
    # 剔除价格变动后，纯靠增/减持股份带来的市值变化
    df = df.with_columns(
        ((pl.col("shares_cur") - pl.col("shares_prev"))
         * pl.col("raw_close_cur") / 1e8).alias("active_value_yi")
    )

    # 7 类分类：价格方向 × 市值方向（价格/市值"平稳"= |变化| < 阈值）
    #   价格大跌 + 市值不跌（涨或平稳） → 逆势加仓（持股量增加抵消下跌）
    #   价格大涨 + 市值大涨             → 顺势加仓
    #   价格平稳 + 市值大涨             → 加仓（纯主动增持，价不变）
    #   价格大涨 + 市值大跌             → 逆势减仓（持股量大跌超过价格上涨）
    #   价格大涨 + 市值平稳             → 顺势减仓（持股量减少抵消上涨）
    #   价格大跌 + 市值大跌             → 顺势减仓（量价齐跌）
    #   价格平稳 + 市值大跌             → 减仓（纯主动减持，价不变）
    #   其他（价平稳 + 市值平稳）       → 无显著变化
    PRICE_THRESH = 0.05   # 价格环比 ≥5% 算显著
    MV_THRESH = 0.05      # 市值环比 ≥5% 算显著
    df = df.with_columns(
        pl.when(
            (pl.col("price_qoq_adj") < -PRICE_THRESH)
            & (pl.col("mv_qoq") > -MV_THRESH)
        ).then(pl.lit("逆势加仓"))
        .when(
            (pl.col("price_qoq_adj") > PRICE_THRESH)
            & (pl.col("mv_qoq") > MV_THRESH)
        ).then(pl.lit("顺势加仓"))
        .when(
            (pl.col("price_qoq_adj").abs() <= PRICE_THRESH)
            & (pl.col("mv_qoq") > MV_THRESH)
        ).then(pl.lit("加仓"))
        .when(
            (pl.col("price_qoq_adj") > PRICE_THRESH)
            & (pl.col("mv_qoq") < -MV_THRESH)
        ).then(pl.lit("逆势减仓"))
        .when(
            (
                (pl.col("price_qoq_adj") > PRICE_THRESH)
                & (pl.col("mv_qoq").abs() <= MV_THRESH)
            )
            | (
                (pl.col("price_qoq_adj") < -PRICE_THRESH)
                & (pl.col("mv_qoq") < -MV_THRESH)
            )
        ).then(pl.lit("顺势减仓"))
        .when(
            (pl.col("price_qoq_adj").abs() <= PRICE_THRESH)
            & (pl.col("mv_qoq") < -MV_THRESH)
        ).then(pl.lit("减仓"))
        .otherwise(pl.lit("无显著变化"))
        .alias("category")
    )
    return df


def summarize(df: pl.DataFrame, cur_period: str, prev_period: str) -> None:
    """控制台打印摘要。"""
    n = df.height
    print(f"\n=== 分类分布 {cur_period} vs {prev_period}（全样本 n = {n}）===")
    print(df.group_by("category").len().sort("len", descending=True))

    # 流通市值 ≥ 5 亿的"主流"样本（剔除极小盘、新建仓噪音）
    big = df.filter(pl.col("mv_cur_yi") >= 5)
    print(f"\n=== 流通市值 ≥ 5 亿样本（n = {big.height}）===")
    print(big.group_by("category").len().sort("len", descending=True))

    def _top_cat(cat: str, n: int = 10) -> pl.DataFrame:
        """单类按金额绝对值排序 TopN（mv ≥ 5 亿门槛）"""
        sub = df.filter((pl.col("category") == cat) & (pl.col("mv_cur_yi") >= 5))
        return sub.sort("active_value_yi", descending=(cat.endswith("加仓"))).head(n).select([
            "code", "name", "shares_qoq", "pct_chg_pp",
            "price_qoq_adj", "mv_qoq", "active_chg",
            "active_value_yi", "mv_cur_yi",
        ])

    for cat in ["逆势加仓", "顺势加仓", "加仓",
                "逆势减仓", "顺势减仓", "减仓"]:
        print(f"\n=== {cat} Top 10（mv ≥ 5 亿，按净增持金额排序）===")
        print(_top_cat(cat))

    print(f"\n=== Top 10 持股市值最大 ===")
    print(
        df.sort("mv_cur_yi", descending=True)
        .head(10)
        .select([
            "code", "name", "mv_cur_yi", "mv_qoq",
            "shares_qoq", "pct_chg_pp", "active_value_yi", "category",
        ])
    )

    # 总主动增减金额（全样本求和）
    total_buy = df.filter(pl.col("active_value_yi") > 0)["active_value_yi"].sum()
    total_sell = df.filter(pl.col("active_value_yi") < 0)["active_value_yi"].sum()
    print(f"\n=== 全样本净增持金额（active_value_yi 求和）===")
    print(f"  增持合计：+{total_buy:.1f} 亿")
    print(f"  减持合计：{total_sell:.1f} 亿")
    print(f"  净额：{total_buy + total_sell:+.1f} 亿")


def plot_scatter(
    df: pl.DataFrame, cur_period: str, prev_period: str, output_png: Path,
) -> None:
    for f in plt.rcParams.get("font.sans-serif", []):
        if "Noto" in f or "WenQuanYi" in f:
            break
    else:
        plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "WenQuanYi Zen Hei"]
        plt.rcParams["axes.unicode_minus"] = False

    fig, (ax_scat, ax_top) = plt.subplots(
        1, 2, figsize=(16, 8), constrained_layout=True,
        gridspec_kw={"width_ratios": [1.4, 1.0]},
    )

    color_map = {
        "逆势加仓": COLOR_BUY,
        "顺势加仓": "#fdae6b",
        "加仓": "#e7298a",
        "逆势减仓": COLOR_SELL,
        "顺势减仓": "#3182bd",
        "减仓": "#756bb1",
        "无显著变化": COLOR_FLAT,
    }
    # 散点：x = 价格环比, y = 市值环比（按用户语义"价格下跌 + 市值上涨"分类）
    sub = df.filter(
        pl.col("price_qoq_adj").is_not_null()
        & pl.col("mv_qoq").is_not_null()
        & pl.col("price_qoq_adj").is_between(-0.7, 2.0)
        & pl.col("mv_qoq").is_between(-0.8, 8.0)
    )
    cat_series = sub["category"].to_list()
    colors = [color_map.get(c, COLOR_FLAT) for c in cat_series]

    # ===== 左：散点（4 象限：价格 × 市值）=====
    ax_scat.axhline(0, color="gray", linewidth=0.5, alpha=0.5)
    ax_scat.axvline(0, color="gray", linewidth=0.5, alpha=0.5)
    ax_scat.scatter(
        sub["price_qoq_adj"].to_numpy(),
        sub["mv_qoq"].to_numpy(),
        s=4, c=colors, alpha=0.45, edgecolors="none",
    )
    # 象限标签（按用户语义：价格 vs 市值）
    ax_scat.text(0.97, 0.97, "顺势加仓\n（价升 + 市值升）",
                 transform=ax_scat.transAxes,
                 ha="right", va="top", fontsize=9, color="#fdae6b", alpha=0.95,
                 fontweight="bold")
    ax_scat.text(0.03, 0.97, "逆势加仓\n（价跌 + 市值升）",
                 transform=ax_scat.transAxes,
                 ha="left", va="top", fontsize=9, color=COLOR_BUY, alpha=0.95,
                 fontweight="bold")
    ax_scat.text(0.97, 0.03, "逆势减仓\n（价升 + 市值跌）",
                 transform=ax_scat.transAxes,
                 ha="right", va="bottom", fontsize=9, color=COLOR_SELL, alpha=0.95,
                 fontweight="bold")
    ax_scat.text(0.03, 0.03, "顺势减仓\n（价跌 + 市值跌）",
                 transform=ax_scat.transAxes,
                 ha="left", va="bottom", fontsize=9, color="#3182bd", alpha=0.95,
                 fontweight="bold")
    ax_scat.set_xlabel(f"复权价环比（{cur_period} vs {prev_period}）")
    ax_scat.set_ylabel("持股市值环比")
    ax_scat.set_title("① 价格环比 × 市值环比 —— 4 象限分类", fontsize=11)
    ax_scat.grid(True, alpha=0.3)

    handles = [
        plt.Line2D([0], [0], marker="o", linestyle="", markersize=8,
                   color=c, label=lab)
        for lab, c in color_map.items()
    ]
    ax_scat.legend(handles=handles, loc="center left", fontsize=8)

    # ===== 右：净增减持 Top 15 横向柱（按金额绝对值排序）=====
    top = (
        df.filter(pl.col("mv_cur_yi") >= 5)
        .sort("active_value_yi", descending=True).head(15)
        .select(["name", "code", "active_value_yi", "category"])
    )
    bot = (
        df.filter(pl.col("mv_cur_yi") >= 5)
        .sort("active_value_yi").head(15)
        .select(["name", "code", "active_value_yi", "category"])
    )
    combined = pl.concat([top, bot]).unique(subset=["code"])
    combined = combined.sort("active_value_yi")  # 升序，barh 默认底→顶
    if combined.height > 0:
        names = [f"{r['name']}\n{r['code']}" for r in combined.iter_rows(named=True)]
        vals = [r["active_value_yi"] for r in combined.iter_rows(named=True)]
        cats = [r["category"] for r in combined.iter_rows(named=True)]
        bar_colors = [color_map.get(c, COLOR_FLAT) for c in cats]
        ax_top.barh(range(len(names)), vals, color=bar_colors, alpha=0.85)
        ax_top.set_yticks(range(len(names)))
        ax_top.set_yticklabels(names, fontsize=7)
        ax_top.axvline(0, color="gray", linewidth=0.5, alpha=0.5)
        ax_top.set_xlabel("净增（减）持金额（亿元，按当期未复权价）")
        ax_top.set_title("② 净增持 Top 15 / 净减持 Top 15（按金额绝对值）",
                         fontsize=11)
        ax_top.grid(True, alpha=0.3, axis="x")

    fig.suptitle(
        f"北向持股季度环比分析  {cur_period} vs {prev_period}  "
        f"（价格 × 市值 4 象限分类 + 净增减持金额）",
        fontsize=13, fontweight="bold", x=0.01, ha="left",
    )

    output_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_png, dpi=120, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"Saved to {output_png}")


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-path", type=Path,
                   default=Path("/mnt/readonly_dataset"))
    p.add_argument("--history-dir", type=Path,
                   default=Path("/mnt/dataset/stock_quote_history"))
    p.add_argument("--adjusted-dir", type=Path,
                   default=Path("/mnt/dataset/stock_quote_adjusted"))
    p.add_argument("--output-csv", type=Path,
                   default=Path("/mnt/dataset/northbound_holdings_qoq.csv"))
    p.add_argument("--output-png", type=Path,
                   default=Path("/mnt/dataset/northbound_holdings_qoq.png"))
    p.add_argument("--cur", default="2026-03-31", help="当期季度末（YYYY-MM-DD）")
    p.add_argument("--prev", default="2025-12-31", help="上一季度末（YYYY-MM-DD）")
    args = p.parse_args()

    if args.cur not in QUARTER_ENDS or args.prev not in QUARTER_ENDS:
        # 允许用户传任意季度末，但提示
        print(f"  注意：{args.cur} 或 {args.prev} 不在最近 7 期默认列表里")

    print("加载北向持股记录...")
    holdings = load_holdings(args.data_path)
    print(f"  共 {holdings.height} (code × period) 记录，"
          f"涉及 {holdings['code'].n_unique()} 只 A 股")

    print(f"\n构造对比窗口 {args.cur} vs {args.prev} ...")
    df = build_qoq_table(holdings, args.history_dir, args.adjusted_dir,
                         args.cur, args.prev)

    # 写 CSV
    out_cols = [
        "code", "name",
        "shares_cur", "shares_prev", "shares_qoq",
        "pct_cur", "pct_prev", "pct_chg_pp",
        "raw_close_cur", "raw_close_prev", "price_qoq_raw",
        "adj_close_cur", "adj_close_prev", "price_qoq_adj",
        "mv_cur_yi", "mv_prev_yi", "mv_qoq",
        "active_chg", "active_value_yi", "category",
        "match_cur", "match_prev",
    ]
    df.select(out_cols).write_csv(args.output_csv)
    print(f"\nCSV: {args.output_csv}  ({df.height} 行)")

    summarize(df, args.cur, args.prev)
    plot_scatter(df, args.cur, args.prev, args.output_png)


if __name__ == "__main__":
    main()
