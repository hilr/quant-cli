"""任意标的回撤极值点（峰/谷）叠加沪深300：看每次大幅回撤时大盘的位置。

把指定标的的回撤峰/谷（按 cummax(high) 分段，取每段最深 low）以竖虚线标在双轴图上：
  - 右轴：标的复权收盘价（黑线）
  - 左轴：沪深300 收盘（淡蓝线，背景）
  - 绿虚线 = 峰值（创新高），红虚线 = 谷底（顶部标回撤深度）
  - x 轴裁到标的与指数的共有区间

标的的累计最高用每日 high 计算，回撤用每日 low 计算（与 drawdown.py 同口径）。
适合观察「某标的深跌时，大盘是同步跌还是背离」。
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import polars as pl
from matplotlib.lines import Line2D

# 作为脚本直接跑时，把项目根加入 path 以便 import quant / 兄弟模块
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from drawdown import load_quote  # noqa: E402


def segment_cycles(df: pl.DataFrame) -> list[tuple]:
    """按历史新高分段，返回 [(peak_date, peak_high, trough_date, trough_low, depth, completed), ...]。

    peak = 该段起点（创新高当日），trough = 段内最低 low；末段 completed=False（进行中）。
    """
    dates = df["date"].to_list()
    highs = df["high"].to_list()
    lows = df["low"].to_list()
    peak_high = df["peak_high"].to_list()
    prev_peak = [None] + peak_high[:-1]

    cycles = []
    seg_start = 0
    cur_lo = 0
    for i in range(1, len(dates)):
        if highs[i] > prev_peak[i]:  # 创新高 → 上一段结束
            tr_date = dates[cur_lo]
            tr_low = lows[cur_lo]
            depth = tr_low / peak_high[cur_lo] - 1
            cycles.append((dates[seg_start], highs[seg_start], tr_date, tr_low, depth, True))
            seg_start = i
            cur_lo = i
        if lows[i] < lows[cur_lo]:
            cur_lo = i
    # 末段（未完成）
    tr_date = dates[cur_lo]
    tr_low = lows[cur_lo]
    depth = tr_low / peak_high[cur_lo] - 1
    cycles.append((dates[seg_start], highs[seg_start], tr_date, tr_low, depth, False))
    return cycles


def plot(
    fund: pl.DataFrame,
    hs300: pl.DataFrame,
    major: list[tuple],
    code: str,
    index_code: str,
    threshold: float,
    output_png: Path,
) -> None:
    dates = fund["date"].to_list()
    closes = fund["close"].to_list()
    start_date = dates[0]
    end_date = dates[-1]

    plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "WenQuanYi Zen Hei"]
    plt.rcParams["axes.unicode_minus"] = False

    fig, ax = plt.subplots(figsize=(16, 8))
    ax2 = ax.twinx()

    hs_d = hs300["date"].to_list()
    hs_c = hs300["close"].to_list()
    d2c = dict(zip(hs_d, hs_c))

    ax.plot(hs_d, hs_c, color="#1f77b4", lw=0.6, alpha=0.55,
            label=f"{index_code} 收盘（左轴）", zorder=3)
    ax2.plot(dates, closes, color="black", lw=1.0,
             label=f"{code} 收盘（右轴）", zorder=4)
    ax2.set_ylabel(f"{code} 复权价", color="black")
    ax2.tick_params(axis="y", labelcolor="black")

    for pk_d, _pk_h, tr_d, _tr_l, dp, done in major:
        ax.axvline(pk_d, color="#27ae60", alpha=0.5, lw=0.6, ls="--", zorder=1)
        c = "#c0392b" if not done else "#e74c3c"
        ax.axvline(tr_d, color=c, alpha=0.6, lw=0.7, ls="--", zorder=1)
        ax.annotate(f"{dp * 100:.1f}%", xy=(tr_d, 1.0), xytext=(0, -2),
                    textcoords=("offset points", "axes fraction"),
                    ha="center", va="top", fontsize=8, color="#c0392b", fontweight="bold")
        if not done:
            ax.annotate("当前", xy=(tr_d, 1.0), xytext=(0, -14),
                        textcoords=("offset points", "axes fraction"),
                        ha="center", va="top", fontsize=7, color="#7f0000", fontweight="bold")

    legend = [
        Line2D([0], [0], color="black", lw=1.2, label=f"{code} 收盘（右轴）"),
        Line2D([0], [0], color="#1f77b4", lw=1.2, alpha=0.6, label=f"{index_code} 收盘（左轴）"),
        Line2D([0], [0], color="#27ae60", lw=1.0, ls="--", alpha=0.7, label="峰值（虚线）"),
        Line2D([0], [0], color="#e74c3c", lw=1.0, ls="--", alpha=0.7,
               label="谷值（虚线，标红字=回撤深度）"),
    ]
    ax.legend(handles=legend, loc="upper left", fontsize=9)

    ax.set_title(
        f"{code} 回撤极值点（虚线标记峰/谷，回撤 ≤ {threshold * 100:.0f}%）"
        f"叠加 {index_code}\n"
        f"区间 {start_date} ~ {end_date}（共有部分），共 {len(major)} 个深回撤周期",
        fontsize=12, fontweight="bold",
    )
    ax.set_ylabel(f"{index_code} 收盘")
    ax.set_xlabel("日期")
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.xaxis.set_minor_locator(mdates.MonthLocator(bymonth=[1, 4, 7, 10]))
    ax.set_xlim(start_date, end_date)

    ax.text(
        0.99, 0.03,
        f"最新 {code}={closes[-1]:.4f}  {index_code}={d2c.get(hs_d[-1], 0):.0f}",
        transform=ax.transAxes, ha="right", va="bottom", fontsize=10,
        color="#222", fontweight="bold",
        bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#bbb", alpha=0.85),
    )

    plt.tight_layout()
    output_png.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_png, dpi=130, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved to {output_png}")
    print(f"\n{code} 共 {len(major)} 个回撤 ≤ {threshold * 100:.0f}% 的周期（含进行中）：")
    print(f"  {'峰值日':<12}{'→':^4}{'谷值日':<12}{'回撤':>8}{'状态':>8}{'沪深300':>10}")
    for pk_d, _pk_h, tr_d, _tr_l, dp, done in major:
        status = "完成" if done else "进行中"
        hs = d2c.get(tr_d)
        hs_str = f"{hs:.0f}" if hs else "n/a"
        print(f"  {pk_d!s:<12}{'→':^4}{tr_d!s:<12}{dp:>8.1%}{status:>8}{hs_str:>10}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--code", default="512890", help="标的代码（基金/指数/股票）")
    p.add_argument(
        "--adjusted-dir", type=Path,
        default=Path("/mnt/dataset/fund_quote_adjusted"),
        help="含 {code}.parquet 的前复权行情目录",
    )
    p.add_argument(
        "--index-file", type=Path,
        default=Path("/mnt/dataset/index_quote_history/000300.parquet"),
        help="对照指数 parquet（默认沪深300）",
    )
    p.add_argument("--index-code", default="000300", help="对照指数代码（用于标题/图例）")
    p.add_argument(
        "--threshold", type=float, default=-0.10,
        help="标记阈值：回撤深于该值的峰谷才画虚线（默认 -0.10）",
    )
    p.add_argument(
        "--start-date", type=str, default=None,
        help="标的起始日期 YYYY-MM-DD（cummax 从该日起累计，默认从最早数据起）",
    )
    p.add_argument(
        "--output", type=Path, default=None,
        help="输出 PNG 路径（默认 drawdown_extremes_vs_hs300_{code}.png）",
    )
    args = p.parse_args()

    start = date.fromisoformat(args.start_date) if args.start_date else None
    fund = load_quote(args.adjusted_dir, args.code, start)
    start_date = fund["date"].min()

    hs300 = (
        pl.read_parquet(args.index_file, columns=["date", "close"])
        .with_columns(pl.col("date").str.to_date("%Y-%m-%d"))
        .filter(pl.col("date") >= start_date)
        .sort("date")
    )

    cycles = segment_cycles(fund)
    major = [c for c in cycles if c[4] <= args.threshold]
    if not major:
        print(f"[yellow]{args.code} 没有回撤 ≤ {args.threshold * 100:.0f}% 的周期，请调宽阈值[/yellow]")
        return

    output = args.output or Path(f"/mnt/dataset/drawdown_extremes_vs_hs300_{args.code}.png")
    plot(fund, hs300, major, args.code, args.index_code, args.threshold, output)


if __name__ == "__main__":
    main()
