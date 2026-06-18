"""Zigzag 转折点识别 + 牛/熊段着色（CSI300 全历史）。

算法：在 close 上做经典 zigzag —— 跟踪上次 pivot 之后的 running max/min，
当价格从当前极端值反向回撤 >= threshold 时确认一个新 pivot。
threshold=15% 表示只关心幅度 ≥15% 的波段，过滤掉小噪声。
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import polars as pl


def zigzag(prices: list[float], threshold: float) -> list[tuple[int, float, str]]:
    """返回 [(idx, price, 'H'|'L'), ...]。

    state machine: direction=+1 在上升段找高点，direction=-1 在下降段找低点。
    每次反向回撤 >= threshold 即确认前一个极端值为 pivot。
    """
    n = len(prices)
    if n == 0:
        return []
    if n == 1:
        return [(0, prices[0], "H")]

    pivots: list[tuple[int, float, str]] = []
    last_pivot_idx = 0

    run_max_idx, run_max_val = 0, prices[0]
    run_min_idx, run_min_val = 0, prices[0]
    direction = 0  # +1 找高，-1 找低，0 未定

    for i in range(1, n):
        p = prices[i]
        if p > run_max_val:
            run_max_idx, run_max_val = i, p
        if p < run_min_val:
            run_min_idx, run_min_val = i, p

        spread_up = (run_max_val - run_min_val) / run_min_val

        if direction == 0:
            if spread_up >= threshold:
                if run_max_idx < run_min_idx:
                    pivots.append((run_max_idx, run_max_val, "H"))
                    last_pivot_idx = run_max_idx
                    direction = -1
                else:
                    pivots.append((run_min_idx, run_min_val, "L"))
                    last_pivot_idx = run_min_idx
                    direction = 1
        elif direction == 1:
            drop = (run_max_val - p) / run_max_val
            if drop >= threshold and run_max_idx > last_pivot_idx:
                pivots.append((run_max_idx, run_max_val, "H"))
                last_pivot_idx = run_max_idx
                direction = -1
                run_min_idx, run_min_val = i, p
        else:  # direction == -1
            rise = (p - run_min_val) / run_min_val
            if rise >= threshold and run_min_idx > last_pivot_idx:
                pivots.append((run_min_idx, run_min_val, "L"))
                last_pivot_idx = run_min_idx
                direction = 1
                run_max_idx, run_max_val = i, p

    if direction == 1:
        pivots.append((run_max_idx, run_max_val, "H"))
    elif direction == -1:
        pivots.append((run_min_idx, run_min_val, "L"))
    else:
        if run_max_idx >= run_min_idx:
            pivots.append((run_max_idx, run_max_val, "H"))
        else:
            pivots.append((run_min_idx, run_min_val, "L"))

    return pivots


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--code", default="000300")
    p.add_argument(
        "--data",
        type=Path,
        default=Path("/mnt/dataset/index_quote_history/000300.parquet"),
    )
    p.add_argument("--threshold", type=float, default=0.15)
    p.add_argument("--output", type=Path, default=Path("/mnt/dataset/csi300_zigzag.png"))
    p.add_argument(
        "--csv",
        type=Path,
        default=Path("/mnt/dataset/csi300_regime/zigzag_t15_segments.csv"),
    )
    args = p.parse_args()

    df = (
        pl.read_parquet(args.data)
        .with_columns(pl.col("date").str.to_date("%Y-%m-%d"))
        .sort("date")
    )
    closes = df["close"].to_list()
    dates = df["date"].to_list()

    pivots = zigzag(closes, args.threshold)

    n_bull = sum(1 for k in range(len(pivots) - 1) if pivots[k + 1][1] > pivots[k][1])
    n_bear = sum(1 for k in range(len(pivots) - 1) if pivots[k + 1][1] < pivots[k][1])
    bull_days = sum(
        pivots[k + 1][0] - pivots[k][0]
        for k in range(len(pivots) - 1)
        if pivots[k + 1][1] > pivots[k][1]
    )
    bear_days = sum(
        pivots[k + 1][0] - pivots[k][0]
        for k in range(len(pivots) - 1)
        if pivots[k + 1][1] < pivots[k][1]
    )

    print(
        f"CSI300 zigzag threshold={args.threshold*100:.0f}%  "
        f"pivots={len(pivots)}  bull_legs={n_bull}  bear_legs={n_bear}  "
        f"bull_days={bull_days}  bear_days={bear_days}"
    )
    print(
        f"  {'k':>3} {'idx':>5} {'date':<12}{'price':>10}{'type':>5}"
        f"{'leg_ret':>10}{'leg_days':>10}{'label':>8}"
    )
    for k, (idx, price, typ) in enumerate(pivots):
        if k == 0:
            leg_ret, leg_days, label = "", "", ""
        else:
            prev_p, prev_i = pivots[k - 1][1], pivots[k - 1][0]
            leg_ret = f"{(price / prev_p - 1) * 100:+.2f}%"
            leg_days = f"{idx - prev_i}"
            label = "bull" if price > prev_p else "bear"
        print(
            f"  {k:>3} {idx:>5} {str(dates[idx]):<12}{price:>10.2f}{typ:>5}"
            f"{leg_ret:>10}{leg_days:>10}{label:>8}"
        )

    fig, ax = plt.subplots(figsize=(15, 7))
    ax.plot(dates, closes, "-", color="gray", linewidth=0.4, alpha=0.5, label="close")

    for k in range(len(pivots) - 1):
        i1, p1, _ = pivots[k]
        i2, p2, _ = pivots[k + 1]
        seg_dates = dates[i1 : i2 + 1]
        seg_prices = closes[i1 : i2 + 1]
        color = "#1a7f37" if p2 > p1 else "#b22222"
        ax.plot(seg_dates, seg_prices, "-", color=color, linewidth=1.8, alpha=0.85)

    for idx, price, typ in pivots:
        marker = "v" if typ == "H" else "^"
        color = "#b22222" if typ == "H" else "#1a7f37"
        ax.scatter(
            [dates[idx]],
            [price],
            marker=marker,
            color=color,
            s=70,
            zorder=5,
            edgecolors="black",
            linewidths=0.5,
        )
        ax.annotate(
            f"{dates[idx].strftime('%Y-%m')}\n{price:.0f}",
            xy=(dates[idx], price),
            xytext=(0, 12 if typ == "H" else -16),
            textcoords="offset points",
            ha="center",
            fontsize=7,
            color=color,
        )

    ax.set_title(
        f"CSI300 Zigzag Segmentation  threshold={args.threshold*100:.0f}%  "
        f"({len(pivots)} pivots, {n_bull} bull legs / {n_bear} bear legs)",
        fontsize=12,
    )
    ax.set_xlabel("Date")
    ax.set_ylabel("Close")
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    plt.tight_layout()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(args.output, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"\nSaved chart to {args.output}")

    # 段级 CSV：每个牛/熊段一行
    seg_rows = []
    for k in range(len(pivots) - 1):
        i1, p1, t1 = pivots[k]
        i2, p2, _ = pivots[k + 1]
        seg_rows.append(
            {
                "seg_id": k,
                "start_date": dates[i1],
                "end_date": dates[i2],
                "start_idx": i1,
                "end_idx": i2,
                "start_price": p1,
                "end_price": p2,
                "leg_return": p2 / p1 - 1,
                "leg_days": i2 - i1,
                "start_type": t1,
                "label": "bull" if p2 > p1 else "bear",
            }
        )
    seg_df = pl.DataFrame(seg_rows)
    args.csv.parent.mkdir(parents=True, exist_ok=True)
    seg_df.write_csv(args.csv)
    print(f"Saved segments CSV to {args.csv}  ({len(seg_df)} rows)")


if __name__ == "__main__":
    main()
