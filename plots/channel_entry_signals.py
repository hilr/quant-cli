"""通道策略入场信号图：下轨买入点 + 前瞻收益 / 跌幅标注（不含离场信号）。

复用 channel_backtest 的下轨入场逻辑（close ≤ MA(window) − k·σ），
画出价格通道，标记每一个买入点（绿色实心三角），并在其上方标注
此后 N 个交易日（默认 60 ≈ 3 个月）的收益率与窗口内最大跌幅，
直观评估入场信号质量。

最近若干买入点若 N 日窗口未满，用截至最新的已知数据补全（空心三角标记），
days 列显示实际使用的交易日数；聚合统计仍只用完整窗口点。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
from channel_backtest import run_backtest


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--code", default="512890")
    p.add_argument("--adjusted-dir", type=Path,
                   default=Path("/mnt/dataset/fund_quote_adjusted"))
    p.add_argument("--window", type=int, default=120)
    p.add_argument("--k", type=float, default=1.5)
    p.add_argument("--fwd", type=int, default=60, help="前瞻窗口（交易日，默认 60≈3 月）")
    p.add_argument("--output", type=Path, default=None)
    args = p.parse_args()

    df = (
        pl.read_parquet(args.adjusted_dir / f"{args.code}.parquet")
        .with_columns(pl.col("date").str.to_date("%Y-%m-%d"))
        .sort("date")
    )
    out, entries, _exits = run_backtest(
        df, args.window, args.k, False, "trail", 1, 1.5,
    )

    ma_full = out["ma"].to_list()
    first = next(i for i, v in enumerate(ma_full) if v is not None)
    dates_all = out["date"].to_list()
    closes_full = out["close"].to_list()
    dates = dates_all[first:]
    closes = closes_full[first:]
    ma = ma_full[first:]
    upper = out["upper"].to_list()[first:]
    lower = out["lower"].to_list()[first:]
    date_idx = {d: i for i, d in enumerate(dates_all)}

    # 每个买入点的前瞻收益 + 窗口内最大跌幅 + 见底天数
    # 窗口未满的最近买入点用截至最新的已知数据补全，标 actual_days/is_partial 区分
    fwd: list[tuple] = []
    for d, price, _tag in entries:
        i = date_idx[d]
        j_end = min(i + args.fwd, len(dates_all) - 1)
        actual_days = j_end - i
        is_partial = actual_days < args.fwd
        r = closes_full[j_end] / price - 1
        seg = closes_full[i : j_end + 1]
        # 从入场价起算的最大浮亏（不是 peak-to-trough），突出入场点质量
        mdd = 0.0
        t_bot = 0
        mx_gain = 0.0
        t_peak = 0
        for k, c in enumerate(seg):
            dd = c / price - 1  # 相对入场价的跌幅
            if dd < mdd:
                mdd = dd
                t_bot = k
            if dd > mx_gain:
                mx_gain = dd
                t_peak = k
        fwd.append((d, price, r, mdd, t_bot, mx_gain, t_peak, actual_days, is_partial))

    # 聚合统计只用完整窗口的买入点，避免被样本不足的最近点带偏
    valid = [f for f in fwd if not f[8]]
    n_partial = sum(1 for f in fwd if f[8])
    win = sum(1 for f in valid if f[2] > 0)
    mean_r = sum(f[2] for f in valid) / len(valid) if valid else 0.0
    med_r = sorted(f[2] for f in valid)[len(valid) // 2] if valid else 0.0
    mean_mdd = sum(f[3] for f in valid) / len(valid) if valid else 0.0
    worst_mdd = min((f[3] for f in valid), default=0.0)
    mean_tbot = sum(f[4] for f in valid) / len(valid) if valid else 0.0
    mean_mx = sum(f[5] for f in valid) / len(valid) if valid else 0.0
    med_mx = sorted(f[5] for f in valid)[len(valid) // 2] if valid else 0.0
    mean_tpeak = sum(f[6] for f in valid) / len(valid) if valid else 0.0
    # 统计 "跌多少转入涨"（从浮亏最深处转到正收益的比例）
    bounce = sum(1 for f in valid if f[2] > 0 and f[3] < 0)  # 先浮亏后转正

    fig, ax = plt.subplots(figsize=(15, 7))
    ax.fill_between(dates, lower, upper, color="#1f77b4", alpha=0.08)
    ax.plot(dates, upper, "-", color="#1f77b4", linewidth=0.5, alpha=0.5)
    ax.plot(dates, lower, "-", color="#1f77b4", linewidth=0.9, alpha=0.8,
            label=f"lower band (MA{args.window}−{args.k}σ)")
    ax.plot(dates, ma, "--", color="gray", linewidth=0.5, alpha=0.6,
            label=f"MA{args.window}")
    ax.plot(dates, closes, "-", color="black", linewidth=0.7, label="close")

    for d, price, r, mdd, _tbot, mx_gain, t_peak, _days, is_partial in fwd:
        if is_partial:
            # 窗口未满：空心三角区分，标注仍用最新已知值
            ax.scatter([d], [price], marker="^", s=70, zorder=5,
                       facecolors="white", edgecolors="green", linewidths=1.3)
        else:
            ax.scatter([d], [price], marker="^", color="green", s=55, zorder=5,
                       edgecolors="white", linewidths=0.5)
        txt = f"+{mx_gain*100:.1f}%\n{r*100:+.1f}%"
        color = "#1a7f37" if r > 0 else "#b22222"
        ax.annotate(txt, xy=(d, price), xytext=(0, -4), textcoords="offset points",
                    ha="center", va="top", fontsize=6.5, color=color, fontweight="bold",
                    linespacing=1.1)

    ax.set_ylabel("Price")
    ax.set_xlabel("Date")
    partial_note = f"，其中 {n_partial} 个窗口未满用最新已知值补" if n_partial else ""
    ax.set_title(
        f"{args.code} 通道入场信号：close ≤ MA{args.window}−{args.k}σ 买入，"
        f"标注：上排={args.fwd} 日窗口内最大涨幅，下排={args.fwd} 日收益"
        f"（空心△=窗口未满，按已知数据估算）\n"
        f"{len(valid)} 个完整窗口买入点：{args.fwd} 日收益均值 {mean_r*100:+.1f}%，"
        f"最大涨幅均值 {mean_mx*100:.1f}%，见顶均值 {mean_tpeak:.1f} 日；"
        f"最大跌幅均值 {mean_mdd*100:.1f}%（共 {len(entries)} 个买入点{partial_note}）",
        fontsize=11,
    )
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(True, alpha=0.3)
    span = dates[-1] - dates[0]
    ax.set_xlim(dates[0], dates[-1] + span * 0.02)
    ax.text(0.99, 0.03, f"最新 {dates[-1]}", transform=ax.transAxes,
            ha="right", va="bottom", fontsize=10, color="#222", fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#bbb", alpha=0.85))
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    plt.tight_layout()
    output = args.output or Path(f"/mnt/dataset/channel_entries_{args.code}.png")
    output.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved to {output}")
    partial_note = f"，{n_partial} 个窗口未满用最新已知值补" if n_partial else ""
    print(f"  {args.code}: {len(entries)} 买入点（{len(valid)} 个完整窗口{partial_note}）")
    print(f"  {args.fwd} 日收益（仅完整窗口）：胜率 {win}/{len(valid)}，均值 {mean_r*100:+.1f}%，中位数 {med_r*100:+.1f}%")
    print(f"  最大涨幅：均值 {mean_mx*100:.1f}%，中位数 {med_mx*100:.1f}%，见顶均值 {mean_tpeak:.1f} 日")
    print(f"  最大跌幅（相对入场价）：均值 {mean_mdd*100:.1f}%，最差 {worst_mdd*100:.1f}%，"
          f"见底均值 {mean_tbot:.1f} 日；先浮亏后转盈 {bounce}/{len(valid)}")
    print()
    fwd_label = f"{args.fwd}d ret"
    print(f"  {'date':<12}{'price':>9}{'days':>6}{'max gain':>10}{'t_peak':>8}"
          f"{fwd_label:>9}{'max loss':>10}{'t_bot':>8}")
    for d, price, r, mdd, tbot, mx_gain, t_peak, actual_days, _partial in fwd:
        rs = f"{r*100:+7.2f}%"
        ms = f"{mdd*100:6.2f}%"
        ts = f"{tbot:>5d}"
        mg = f"{mx_gain*100:8.2f}%"
        tp = f"{t_peak:>5d}"
        print(f"  {d!s:<12}{price:>9.4f}{actual_days:>6d}{mg:>10}{tp:>8}{rs:>9}{ms:>10}{ts:>8}")


if __name__ == "__main__":
    main()
