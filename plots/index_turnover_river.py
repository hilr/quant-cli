"""沪深300 / 中证500 / 中证1000 / 其他 成交额占比 river 图（streamgraph）。

每日各档成交额 / 两市总成交额（sym 基线，整体恒为 100%）。
  - 沪深300  (000300)：大盘
  - 中证500  (000905)：中大盘
  - 中证1000 (000852)：中小盘
  - 其他 = 两市总成交额 −（沪深300 + 中证500 + 中证1000）
          （含更小微盘、ST、及三指数未覆盖的股票）

两市总成交额 = 上证综指 (000001) + 深证综指 (399106) turnover 之和
（这两个综合指数的 turnover 即对应市场全部股票成交额之和；
 注意深证成指 399001 仅 500 只成分股，早期 turnover 远小于全市场，故不用它作分母）。
按日 inner join 五个指数 turnover > 0 的交易日（起点 2005-01-04，五者共同起点）。
右轴叠加沪深300 收盘（灰淡线），对照占比结构与大盘走势的相关性。

x 轴只用交易日（跳过周末/节假日）；sym 基线让河流总宽恒为 100%，内部边界随风格轮动起伏。
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import matplotlib.pyplot as plt
import polars as pl

# 档位定义：(内部 key, 显示名, parquet code, 颜色)；自下而上堆叠。
TIERS = [
    ("hs300",   "沪深300",  "000300", "#1f77b4"),
    ("csi500",  "中证500",  "000905", "#2ca02c"),
    ("csi1000", "中证1000", "000852", "#ff7f0e"),
]
OTHER_NAME = "其他"
OTHER_COLOR = "#bbbbbb"
SH_CODE = "000001"   # 上证综指（沪市全市场）
SZ_CODE = "399106"   # 深证综指（深市全市场；399001 深证成指仅 500 成分股，不作分母）


def load_turnover(path: Path, code: str) -> pl.DataFrame:
    """读单个指数 parquet → (date, turnover)，过滤 turnover>0，列名改为 code。"""
    return (pl.read_parquet(path, columns=["date", "turnover"])
            .with_columns(pl.col("date").str.to_date("%Y-%m-%d"))
            .filter(pl.col("turnover") > 0)
            .rename({"turnover": code}))


def compute_river(index_dir: Path) -> pl.DataFrame:
    """inner join 五指数 turnover → [date, hs300, csi500, csi1000, sh, sz, total, other]。"""
    sh = load_turnover(index_dir / f"{SH_CODE}.parquet", "sh")
    sz = load_turnover(index_dir / f"{SZ_CODE}.parquet", "sz")
    idx_frames = [load_turnover(index_dir / f"{t[2]}.parquet", t[0]) for t in TIERS]

    d = sh.join(sz, on="date", how="inner")
    for f in idx_frames:
        d = d.join(f, on="date", how="inner")
    d = d.sort("date")

    idx_keys = [t[0] for t in TIERS]
    idx_sum_expr = sum((pl.col(k) for k in idx_keys), start=pl.lit(0))
    d = d.with_columns((pl.col("sh") + pl.col("sz")).alias("total"))
    d = d.with_columns((pl.col("total") - idx_sum_expr).alias("other"))
    return d


def load_hs300_close(path: Path) -> pl.DataFrame:
    return (pl.read_parquet(path, columns=["date", "close"])
            .with_columns(pl.col("date").str.to_date("%Y-%m-%d"))
            .sort("date"))


def render(d: pl.DataFrame, output: Path, hs300_close: list[float]) -> None:
    plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "WenQuanYi Zen Hei"]
    plt.rcParams["axes.unicode_minus"] = False

    dates = d["date"].to_list()
    total = d["total"].to_list()
    n = len(dates)

    keys = [t[0] for t in TIERS] + ["other"]
    names = [t[1] for t in TIERS] + [OTHER_NAME]
    colors = [t[3] for t in TIERS] + [OTHER_COLOR]

    # 各档每日占比（%），shape [n_bands][n_dates]
    Y = [[d[k][i] / total[i] * 100.0 for i in range(n)] for k in keys]

    fig = plt.figure(figsize=(18, 9), dpi=120)
    fig.patch.set_facecolor("white")
    ax = fig.add_axes([0.06, 0.08, 0.80, 0.80])
    ax.set_facecolor("white")
    ax.stackplot(list(range(n)), *Y, baseline="sym",
                 colors=colors, edgecolor="none", linewidth=0)

    ax.set_xlim(0, n - 1)
    ax.set_ylim(-50, 50)
    ax.margins(y=0)

    # x 轴：每年首日一个刻度
    tick_idx, tick_lab, prev_year = [], [], None
    for i, dt in enumerate(dates):
        if dt.year != prev_year:
            tick_idx.append(i)
            tick_lab.append(dt.strftime("%Y"))
            prev_year = dt.year
    ax.set_xticks(tick_idx)
    ax.set_xticklabels(tick_lab)
    plt.setp(ax.get_xticklabels(), rotation=0, ha="center", fontsize=9)
    ax.tick_params(axis="x", pad=4, length=3)

    ax.set_yticks([-50, -25, 0, 25, 50])
    ax.set_yticklabels(["", "75%", "50%\n(中线)", "75%", ""])
    ax.yaxis.set_tick_params(labelsize=8, length=0, colors="#888")
    ax.grid(axis="y", color="#eee", lw=0.5, zorder=0)
    for sp in ("left", "top", "right"):
        ax.spines[sp].set_visible(False)

    # 右轴：沪深300 收盘（灰淡线，对照大盘走势）
    axr = ax.twinx()
    axr.plot(range(n), hs300_close, color="#444", lw=0.8, alpha=0.5,
             label="沪深300（右轴）")
    axr.set_ylabel("沪深300 收盘", color="#888", fontsize=10)
    axr.tick_params(axis="y", labelcolor="#888", labelsize=8)
    axr.spines["right"].set_color("#bbb")
    axr.legend(loc="lower left", fontsize=8.5, framealpha=0.9)

    # 右侧标注各档名（最后一天该 band 的中心 y）
    last_pct = [Y[b][n - 1] for b in range(len(keys))]
    cum = 0.0
    for i, name in enumerate(names):
        band_h = float(last_pct[i])
        center_y = -50 + cum + band_h / 2
        cum += band_h
        ax.annotate(
            name,
            xy=(n - 1, center_y),
            xytext=(10, 0), textcoords="offset points",
            ha="left", va="center",
            fontsize=10.5, color="#222", fontweight="bold",
            annotation_clip=False,
        )

    # 最新日各档占比（右下角文本框）
    latest_lines = "\n".join(f"{names[i]}  {last_pct[i]:.1f}%"
                             for i in range(len(keys)))
    ax.text(0.99, 0.03,
            f"最新 {dates[-1]}\n{latest_lines}",
            transform=ax.transAxes, ha="right", va="bottom",
            fontsize=9.5, color="#222", fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.4", fc="white", ec="#ccc", alpha=0.92))

    fig.text(0.46, 0.955,
             f"沪深300 / 中证500 / 中证1000 / 其他 · 成交额占比 river 图 · "
             f"{dates[0].strftime('%Y-%m-%d')} ~ {dates[-1].strftime('%Y-%m-%d')}"
             f"（{n} 个交易日）",
             ha="center", va="top", fontsize=13, fontweight="bold")
    fig.text(0.46, 0.913,
             "sym 基线：整体恒为 100%；其他 = 两市总成交额 −"
             "（沪深300 + 中证500 + 中证1000）",
             ha="center", va="top", fontsize=9.5, color="#555")

    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=120, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"Saved to {output}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--index-dir", type=Path,
                        default=Path("/mnt/dataset/index_quote_history"))
    parser.add_argument("--output", type=Path,
                        default=Path("/mnt/dataset/index_turnover_river.png"))
    parser.add_argument("--start-date", type=str, default=None,
                        help="起始日期 YYYY-MM-DD")
    parser.add_argument("--end-date", type=str, default=None,
                        help="结束日期 YYYY-MM-DD")
    args = parser.parse_args()

    d = compute_river(args.index_dir)
    if args.start_date:
        d = d.filter(pl.col("date") >= date.fromisoformat(args.start_date))
    if args.end_date:
        d = d.filter(pl.col("date") <= date.fromisoformat(args.end_date))

    if d.is_empty():
        raise SystemExit("过滤后无数据")

    print(f"行数: {len(d)}（{d['date'].min()} ~ {d['date'].max()}）")
    last = d.tail(1)
    total_v = last["total"][0]
    for t in TIERS:
        print(f"  {t[1]}: {last[t[0]][0] / total_v * 100:.1f}%")
    print(f"  其他: {last['other'][0] / total_v * 100:.1f}%")

    hs300 = load_hs300_close(args.index_dir / "000300.parquet")
    hs300_close = (d.select("date").join(hs300, on="date", how="left")
                   ["close"].to_list())
    render(d, args.output, hs300_close)


if __name__ == "__main__":
    main()
