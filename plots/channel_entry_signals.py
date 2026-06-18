"""通道策略入场信号图：下轨买入点 + 前瞻收益标注（不含离场信号）。

复用 channel_backtest 的下轨入场逻辑（close ≤ MA(window) − k·σ），
画出价格通道，标记每一个买入点（绿色三角），并在其上方标注
此后 N 个交易日（默认 63 ≈ 3 个月）的收益率，直观评估入场信号质量。
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
    p.add_argument("--fwd", type=int, default=63, help="前瞻窗口（交易日，默认 63≈3 月）")
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

    # 每个买入点的前瞻收益
    fwd: list[tuple] = []
    for d, price, _tag in entries:
        i = date_idx[d]
        j = i + args.fwd
        r = closes_full[j] / price - 1 if j < len(dates_all) else None
        fwd.append((d, price, r))

    valid = [f for f in fwd if f[2] is not None]
    win = sum(1 for f in valid if f[2] > 0)
    mean_r = sum(f[2] for f in valid) / len(valid) if valid else 0.0
    med_r = sorted(f[2] for f in valid)[len(valid) // 2] if valid else 0.0

    fig, ax = plt.subplots(figsize=(15, 7))
    ax.fill_between(dates, lower, upper, color="#1f77b4", alpha=0.08)
    ax.plot(dates, upper, "-", color="#1f77b4", linewidth=0.5, alpha=0.5)
    ax.plot(dates, lower, "-", color="#1f77b4", linewidth=0.9, alpha=0.8,
            label=f"lower band (MA{args.window}−{args.k}σ)")
    ax.plot(dates, ma, "--", color="gray", linewidth=0.5, alpha=0.6,
            label=f"MA{args.window}")
    ax.plot(dates, closes, "-", color="black", linewidth=0.7, label="close")

    for d, price, r in fwd:
        ax.scatter([d], [price], marker="^", color="green", s=55, zorder=5,
                   edgecolors="white", linewidths=0.5)
        if r is None:
            txt, color = "n/a", "gray"
        else:
            txt = f"{r*100:+.1f}%"
            color = "#1a7f37" if r > 0 else "#b22222"
        ax.annotate(txt, xy=(d, price), xytext=(0, 9), textcoords="offset points",
                    ha="center", fontsize=7, color=color, fontweight="bold")

    ax.set_ylabel("Price")
    ax.set_xlabel("Date")
    ax.set_title(
        f"{args.code} 通道入场信号：close ≤ MA{args.window}−{args.k}σ 买入，"
        f"标注为此后 {args.fwd} 日（≈3 月）收益\n"
        f"{len(valid)} 个可验买入点：胜率 {win}/{len(valid)}（{win/len(valid)*100:.0f}%），"
        f"均值 {mean_r*100:+.1f}%，中位数 {med_r*100:+.1f}%（共 {len(entries)} 个买入点）",
        fontsize=11,
    )
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    plt.tight_layout()
    output = args.output or Path(f"/mnt/dataset/channel_entries_{args.code}.png")
    output.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved to {output}")
    print(f"  {args.code}: {len(entries)} 买入点，{len(valid)} 个已可验前瞻收益")
    print(f"  胜率 {win}/{len(valid)}，均值 {mean_r*100:+.1f}%，中位数 {med_r*100:+.1f}%")


if __name__ == "__main__":
    main()
