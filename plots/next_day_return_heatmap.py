"""沪深300 截止当日 N1 日收益 → 之后 N2 日收益 2D 热力图（牛 vs 熊对比）。

研究「过去 N1 日涨跌 → 未来 N2 日涨跌」的经验关系：
N1 日大涨后，未来 N2 日是延续还是反转？牛市和熊市里有何差异？

口径：
- r_back(t)  = close[t] / close[t-N1] - 1           （截止当日的 N1 日收益）
- r_fwd(t)   = close[t+N2] / close[t] - 1           （之后的 N2 日收益）
- 把 (r_back, r_fwd) 按指定步长做 2D 直方图，x = 截止当日、y = 之后
- 按大级别牛/熊分段归属聚合（半开区间避免重复计数；anchor day t 决定归属，
  跨段边界的窗口不剔除）
- 颜色：log scale（(0,0) 附近频次远高于尾部，线性刻度会糊成一片）
- 象限：右上 = 前涨后涨（延续）、左下 = 前跌后跌（延续）、左上/右下 = 反转

默认 N1=N2=1（即原"今天 → 明天"行为）。未指定 --step/--range 时按
sqrt(max(N1,N2)) 自动缩放（波动率 ∝ sqrt(时间)）。

输出：`segment_return_heatmap_{code}_{N1}f_{N2}b.png`（牛/熊左右两面板，
共享色阶，可直接对比）+ 控制台牛熊 ρ / 象限占比 / 条件概率明细。
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import polars as pl
from matplotlib.colors import LogNorm

DIR_CN = {"bull": "牛市", "bear": "熊市"}


def load_segments(path: Path) -> pl.DataFrame:
    return pl.read_csv(path).with_columns(
        pl.col("start_date").str.to_date("%Y-%m-%d"),
        pl.col("end_date").str.to_date("%Y-%m-%d"),
    ).sort("seg")


def load_pair_returns(
    quote_path: Path, today_window: int, next_window: int
) -> pl.DataFrame:
    """返回带 ret_today / ret_next 的表。

    - ret_today = close[t] / close[t-today_window] - 1
    - ret_next  = close[t+next_window] / close[t] - 1
    首部丢 today_window 行、尾部丢 next_window 行。
    """
    return (
        pl.read_parquet(quote_path, columns=["date", "close"])
        .with_columns(pl.col("date").str.to_date("%Y-%m-%d"))
        .sort("date")
        .with_columns(
            (
                pl.col("close") / pl.col("close").shift(today_window) - 1
            ).alias("ret_today"),
            (
                pl.col("close").shift(-next_window) / pl.col("close") - 1
            ).alias("ret_next"),
        )
        .drop_nulls(["ret_today", "ret_next"])
    )


def auto_step_range(today_window: int, next_window: int) -> tuple[float, float]:
    """按 sqrt(N) 估算合适的 (step, range)。波动率 ∝ sqrt(时间)。"""
    n = max(today_window, next_window, 1)
    factor = math.sqrt(n)
    step_raw = 0.5 * factor
    step = max(0.5, round(step_raw / 0.5) * 0.5)
    rng = max(7.0, round(7.0 * factor))
    return step, rng


def label_regime(df: pl.DataFrame, segments: pl.DataFrame) -> pl.DataFrame:
    """给每天打 regime 标签（[start, end) 半开，最后一段闭区间）。"""
    regime = pl.Series("regime", [None] * df.height, dtype=pl.Utf8)
    last_idx = segments.height - 1
    dates = df["date"]
    for i, seg in enumerate(segments.iter_rows(named=True)):
        upper = dates <= seg["end_date"] if i == last_idx else dates < seg["end_date"]
        mask = (dates >= seg["start_date"]) & upper
        regime = regime.set(mask, seg["dir"])
    return df.with_columns(regime)


def make_edges(lo: float, hi: float, step: float) -> np.ndarray:
    """半开桶边，对齐到 step 整数倍，覆盖 [lo, hi]。"""
    lo = np.floor(lo / step) * step
    hi = np.ceil(hi / step) * step
    n = int(round((hi - lo) / step)) + 1
    return np.linspace(lo, hi, n)


def quadrant_shares(pct: np.ndarray, edges: np.ndarray) -> dict:
    """统计四个象限的占比（%）。pct[i, j] = 今天 bin i、明天 bin j。"""
    zero_idx = int(np.searchsorted(edges, 0.0))
    zero_idx = max(1, min(zero_idx, len(edges) - 1))

    def block(i_slice, j_slice):
        return float(pct[i_slice, j_slice].sum())

    shares = {
        "up_up":      block(slice(zero_idx, None), slice(zero_idx, None)),   # 右上 同涨
        "down_down":  block(slice(0, zero_idx),   slice(0, zero_idx)),       # 左下 同跌
        "down_up":    block(slice(0, zero_idx),   slice(zero_idx, None)),    # 左上 反转上
        "up_down":    block(slice(zero_idx, None), slice(0, zero_idx)),      # 右下 反转下
    }
    shares["continuation"] = shares["up_up"] + shares["down_down"]
    shares["reversal"] = shares["down_up"] + shares["up_down"]
    return shares


def conditional_p(x: np.ndarray, y: np.ndarray) -> dict:
    """条件概率：今天涨/跌时，明天涨的概率。"""
    up_today = x > 0
    down_today = x < 0
    return {
        "p_up_given_up":   float(np.mean(y[up_today] > 0) * 100) if up_today.sum() else float("nan"),
        "p_up_given_down": float(np.mean(y[down_today] > 0) * 100) if down_today.sum() else float("nan"),
    }


def plot_panel(
    ax, x: np.ndarray, y: np.ndarray, edges: np.ndarray,
    title: str, vmin: float, vmax: float,
    x_label: str, y_label: str,
) -> tuple:
    H, _, _ = np.histogram2d(x, y, bins=[edges, edges])
    pct = H / H.sum() * 100
    # log 色阶，0 桶用 mask 屏蔽
    H_disp = np.ma.masked_where(H == 0, pct)
    mesh = ax.pcolormesh(
        edges, edges, H_disp.T,
        cmap="viridis", norm=LogNorm(vmin=vmin, vmax=vmax),
        shading="auto",
    )
    ax.axhline(0, color="white", lw=0.8, alpha=0.6)
    ax.axvline(0, color="white", lw=0.8, alpha=0.6)
    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    ax.set_title(title, fontsize=12, fontweight="bold")
    ax.grid(True, color="white", lw=0.3, alpha=0.2)
    return mesh, pct


def annotate_quadrants(
    ax, pct: np.ndarray, edges: np.ndarray, shares: dict,
    up_up_label: str, down_down_label: str,
    down_up_label: str, up_down_label: str,
) -> None:
    zero_idx = int(np.searchsorted(edges, 0.0))
    zero_idx = max(1, min(zero_idx, len(edges) - 1))
    mid_right = (edges[zero_idx] + edges[-1]) / 2
    mid_left = (edges[0] + edges[zero_idx]) / 2
    mid_top = (edges[zero_idx] + edges[-1]) / 2
    mid_bot = (edges[0] + edges[zero_idx]) / 2

    style = dict(fontsize=9, ha="center", va="center", color="white", fontweight="bold",
                 bbox=dict(boxstyle="round,pad=0.25", fc="black", alpha=0.45, ec="none"))
    ax.text(mid_right, mid_top, f"{up_up_label}\n{shares['up_up']:.1f}%", **style)
    ax.text(mid_left, mid_bot, f"{down_down_label}\n{shares['down_down']:.1f}%", **style)
    ax.text(mid_left, mid_top, f"{down_up_label}\n{shares['down_up']:.1f}%", **style)
    ax.text(mid_right, mid_bot, f"{up_down_label}\n{shares['up_down']:.1f}%", **style)


def plot_figure(
    panels: dict, edges: np.ndarray, code: str, output_png: Path,
    today_window: int, next_window: int,
) -> None:
    plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "WenQuanYi Zen Hei"]
    plt.rcParams["axes.unicode_minus"] = False

    fig, axes = plt.subplots(1, 2, figsize=(14, 6), constrained_layout=True)

    # 共享色阶：取两边非零密度的 [1%, 99] 分位作为 vmin/vmax
    all_density = []
    for d in ("bull", "bear"):
        x = panels[d]["x"]; y = panels[d]["y"]
        H, _, _ = np.histogram2d(x, y, bins=[edges, edges])
        p = H / H.sum() * 100
        all_density.append(p[H > 0])
    combined = np.concatenate(all_density)
    vmin = max(combined.min(), 1e-3)
    vmax = combined.max()

    x_label = f"截止当日 {today_window} 日收益（%）"
    y_label = f"之后 {next_window} 日收益（%）"
    up_up_lbl = "前涨后涨"
    down_down_lbl = "前跌后跌"
    down_up_lbl = "前跌后涨"
    up_down_lbl = "前涨后跌"

    for ax, d in zip(axes, ("bull", "bear")):
        p = panels[d]
        x = p["x"]; y = p["y"]
        corr = float(np.corrcoef(x, y)[0, 1])
        title = (
            f"{DIR_CN[d]}  N={p['n']:,}  "
            f"ρ(back{today_window}d, fwd{next_window}d)={corr:+.3f}"
        )
        mesh, pct = plot_panel(
            ax, x, y, edges, title, vmin, vmax, x_label, y_label,
        )
        shares = quadrant_shares(pct, edges)
        annotate_quadrants(
            ax, pct, edges, shares,
            up_up_lbl, down_down_lbl, down_up_lbl, up_down_lbl,
        )

        summary = (
            f"延续 {shares['continuation']:.1f}%   "
            f"反转 {shares['reversal']:.1f}%\n"
            f"P(后涨|前涨) = {p['cond']['p_up_given_up']:.1f}%\n"
            f"P(后涨|前跌) = {p['cond']['p_up_given_down']:.1f}%"
        )
        ax.text(
            0.02, 0.98, summary, transform=ax.transAxes,
            ha="left", va="top", fontsize=9,
            bbox=dict(boxstyle="round,pad=0.4", fc="white", ec="#bbb", alpha=0.9),
        )

    fig.suptitle(
        f"{code} 截止当日 {today_window} 日 → 之后 {next_window} 日 收益 2D 分布"
        f"（大级别牛熊分段聚合，步长 {(edges[1]-edges[0]):.1f}%，log 色阶）",
        fontsize=13, fontweight="bold",
    )
    cbar = fig.colorbar(mesh, ax=axes, location="right", pad=0.02)
    cbar.set_label("占该面板总样本的比例（%）")

    output_png.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_png, dpi=130, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved to {output_png}")


def print_table(panels: dict, today_window: int, next_window: int) -> None:
    print(
        f"\n=== 牛 vs 熊 截止当日 {today_window} 日 → 之后 {next_window} 日 自相关结构 ==="
    )
    hdr = (
        f"{'类型':<5} {'N':>5} {'ρ':>7} "
        f"{'前涨后涨%':>9} {'前跌后跌%':>9} {'前跌后涨%':>9} {'前涨后跌%':>9} "
        f"{'延续合计%':>9} {'反转合计%':>9} "
        f"{'P(后涨|前涨)':>13} {'P(后涨|前跌)':>13}"
    )
    print(hdr)
    print("-" * len(hdr))
    for d in ("bull", "bear"):
        p = panels[d]
        s = p["shares"]
        c = p["cond"]
        print(
            f"{DIR_CN[d]:<5} {p['n']:>5} {p['corr']:>+7.3f} "
            f"{s['up_up']:>9.1f} {s['down_down']:>9.1f} "
            f"{s['down_up']:>9.1f} {s['up_down']:>9.1f} "
            f"{s['continuation']:>9.1f} {s['reversal']:>9.1f} "
            f"{c['p_up_given_up']:>13.1f} {c['p_up_given_down']:>13.1f}"
        )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--segments-csv", type=Path,
        default=Path("/mnt/dataset/csi300_regime_segments/large_segments.csv"),
        help="分段 CSV（默认 large_segments.csv）",
    )
    p.add_argument(
        "--quote-path", type=Path,
        default=Path("/mnt/dataset/index_quote_history/000300.parquet"),
        help="指数日行情 parquet",
    )
    p.add_argument("--code", default="000300", help="指数代码（标题用）")
    p.add_argument(
        "--today-window", type=int, default=1,
        help="截止当日的 N 日收益窗口长度（默认 1，即当天收益）",
    )
    p.add_argument(
        "--next-window", type=int, default=1,
        help="之后的 N 日收益窗口长度（默认 1，即次日收益）",
    )
    p.add_argument(
        "--step", type=float, default=None,
        help="2D 直方图步长（%，0.5 = 0.5%）。默认按 sqrt(max(N1,N2)) 自动缩放",
    )
    p.add_argument(
        "--range", type=float, default=None,
        help="轴范围 ±N%。默认按 sqrt(max(N1,N2)) 自动缩放，超出范围归入边缘桶",
    )
    p.add_argument(
        "--clip", action="store_true",
        help="丢弃超出 --range 的样本（默认归入边缘桶）",
    )
    p.add_argument(
        "--output", type=Path, default=None,
        help="输出 PNG 路径",
    )
    args = p.parse_args()

    if args.today_window < 1 or args.next_window < 1:
        raise SystemExit("--today-window 和 --next-window 必须 >= 1")

    auto_step, auto_range = auto_step_range(args.today_window, args.next_window)
    step = args.step if args.step is not None else auto_step
    rng = args.range if args.range is not None else auto_range
    if args.step is None or args.range is None:
        print(
            f"[info] 窗口 ({args.today_window},{args.next_window}) → 自动 step={step}% range=±{rng}%"
        )

    segments = load_segments(args.segments_csv)
    pairs = load_pair_returns(args.quote_path, args.today_window, args.next_window)
    pairs = label_regime(pairs, segments)

    edges = make_edges(-rng, rng, step)

    panels: dict = {}
    for d in ("bull", "bear"):
        sub = pairs.filter(pl.col("regime") == d)
        x = sub["ret_today"].to_numpy() * 100
        y = sub["ret_next"].to_numpy() * 100
        if args.clip:
            inside = (np.abs(x) <= rng) & (np.abs(y) <= rng)
            n_clip = int((~inside).sum())
            if n_clip:
                print(f"[info] {DIR_CN[d]} 丢弃 {n_clip} 个超出 ±{rng}% 的样本")
            x, y = x[inside], y[inside]
        else:
            x = np.clip(x, edges[0], edges[-1])
            y = np.clip(y, edges[0], edges[-1])
        H, _, _ = np.histogram2d(x, y, bins=[edges, edges])
        pct = H / H.sum() * 100
        shares = quadrant_shares(pct, edges)
        panels[d] = {
            "x": x, "y": y, "n": len(x),
            "corr": float(np.corrcoef(x, y)[0, 1]),
            "shares": shares,
            "cond": conditional_p(x, y),
        }

    output = args.output or Path(
        f"/mnt/dataset/segment_return_heatmap_{args.code}_"
        f"{args.today_window}b_{args.next_window}f.png"
    )
    plot_figure(panels, edges, args.code, output, args.today_window, args.next_window)
    print_table(panels, args.today_window, args.next_window)


if __name__ == "__main__":
    main()
