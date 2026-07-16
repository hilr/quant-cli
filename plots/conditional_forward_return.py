"""沪深300 截止当日 N1 日收益分桶 → 之后 N2 日收益的条件分布。

回答：「前 N1 日涨跌幅处于某个范围时（例如大跌之后），未来 N2 日的收益
分布是否有明显的均值偏移或厚尾？」——而不是只看整体聚合的 ρ / P(↑|↑)。
整体均值会被中间大量样本主导，掩盖尾部条件下的真实结构。

口径：
- r_back(t) = close[t] / close[t-N1] - 1
- r_fwd(t)  = close[t+N2] / close[t] - 1
- 按 r_back 分桶（默认边界 -∞/-8%/-5%/-3%/-1%/0/+1%/+3%/+5%/+8%/+∞，近 0 更细、
  尾部更宽，捕捉尾部偏移和厚尾）
- 每桶内统计 r_fwd 的：N / 均值 / 标准差 / 偏度 / 峰度 / P5/P25/P50/P75/P95 / 均值 95%CI
- 按 regime（牛/熊）分别统计

输出：
- 控制台：每 regime 一张条件统计表 + 全局基线
- PNG：牛/熊两面板箱线图（须=P5/P95、箱=P25/P75、中线=中位、红点=均值±95%CI、
  橙虚线=全局均值），可一眼看出哪些桶有显著均值偏移或异常厚尾

判定阈值（粗略经验）：
- 均值偏移显著：桶均值 95%CI 不包含全局基线均值
- 厚尾：峰度（excess kurtosis）>> 0（正态分布 = 0）
- 偏态：偏度 |skew| > 0.5 视为明显偏向
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import polars as pl

DIR_CN = {"bull": "牛市", "bear": "熊市"}
DEFAULT_BUCKET_EDGES = [-np.inf, -8, -5, -3, -1, 0, 1, 3, 5, 8, np.inf]


def load_segments(path: Path) -> pl.DataFrame:
    return pl.read_csv(path).with_columns(
        pl.col("start_date").str.to_date("%Y-%m-%d"),
        pl.col("end_date").str.to_date("%Y-%m-%d"),
    ).sort("seg")


def load_pair_returns(
    quote_path: Path, today_window: int, next_window: int
) -> pl.DataFrame:
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


def parse_edges(s: str | None) -> list[float]:
    if s is None:
        return list(DEFAULT_BUCKET_EDGES)
    out = []
    for p in s.split(","):
        p = p.strip()
        if p in ("-inf", "-∞"):
            out.append(-np.inf)
        elif p in ("inf", "+inf", "∞", "+∞"):
            out.append(np.inf)
        else:
            out.append(float(p))
    return out


def bucket_label(lo: float, hi: float) -> str:
    def fmt(x: float, lower: bool) -> str:
        if np.isneginf(x):
            return "(-∞"
        if np.isposinf(x):
            return "+∞)"
        bracket = "[" if lower else ")"
        return f"{bracket}{x:+g}%"
    return f"{fmt(lo, True)}, {fmt(hi, False)}"


def skewness(arr: np.ndarray) -> float:
    n = len(arr)
    if n < 3:
        return float("nan")
    m = float(np.mean(arr))
    s = float(np.std(arr, ddof=1))
    if s == 0:
        return 0.0
    return float(np.sum((arr - m) ** 3) / ((n - 1) * s ** 3))


def excess_kurtosis(arr: np.ndarray) -> float:
    n = len(arr)
    if n < 4:
        return float("nan")
    m = float(np.mean(arr))
    s = float(np.std(arr, ddof=1))
    if s == 0:
        return 0.0
    return float(np.sum((arr - m) ** 4) / ((n - 1) * s ** 4) - 3.0)


def stats(arr: np.ndarray) -> dict:
    n = len(arr)
    if n == 0:
        return {"n": 0}
    if n < 2:
        return {
            "n": n, "mean": float(arr[0]), "std": float("nan"),
            "skew": float("nan"), "kurt": float("nan"),
            "p5": float(arr[0]), "p25": float(arr[0]), "p50": float(arr[0]),
            "p75": float(arr[0]), "p95": float(arr[0]),
            "se_mean": float("nan"),
        }
    std = float(np.std(arr, ddof=1))
    return {
        "n": n,
        "mean": float(np.mean(arr)),
        "std": std,
        "skew": skewness(arr),
        "kurt": excess_kurtosis(arr),
        "p5":  float(np.percentile(arr, 5)),
        "p25": float(np.percentile(arr, 25)),
        "p50": float(np.percentile(arr, 50)),
        "p75": float(np.percentile(arr, 75)),
        "p95": float(np.percentile(arr, 95)),
        "se_mean": std / np.sqrt(n),
    }


def compute_panel(x_back: np.ndarray, y_fwd: np.ndarray, edges: list[float]) -> dict:
    """按 edges 把 x_back 分桶，每桶统计 y_fwd。"""
    idx = np.clip(
        np.digitize(x_back, edges[1:-1], right=False), 0, len(edges) - 2
    )
    buckets = []
    for i in range(len(edges) - 1):
        mask = idx == i
        y_in = y_fwd[mask]
        s = stats(y_in)
        s["label"] = bucket_label(edges[i], edges[i + 1])
        s["y"] = y_in
        buckets.append(s)
    return {"buckets": buckets, "baseline": stats(y_fwd), "n": len(y_fwd)}


def print_table(
    panel: dict, regime: str, today_window: int, next_window: int
) -> None:
    bl = panel["baseline"]
    print(
        f"\n=== {regime} 条件统计（前 {today_window} 日收益分桶 → "
        f"之后 {next_window} 日收益分布） ==="
    )
    hdr = (
        f"{'前 N1 日收益桶':<20} {'N':>5} {'均值%':>8} {'±95%CI':>16} "
        f"{'标准差%':>8} {'偏度':>6} {'峰度':>6} "
        f"{'P5%':>7} {'P25%':>7} {'中位%':>7} {'P75%':>7} {'P95%':>7}"
    )
    print(hdr)
    print("-" * len(hdr))
    for b in panel["buckets"]:
        if b["n"] == 0:
            print(f"{b['label']:<20} {0:>5}")
            continue
        ci_str = (
            f"({b['mean'] - 1.96 * b['se_mean']:+.2f},{b['mean'] + 1.96 * b['se_mean']:+.2f})"
            if not np.isnan(b["se_mean"]) else "—"
        )
        print(
            f"{b['label']:<20} {b['n']:>5} {b['mean']:>+8.3f} {ci_str:>16} "
            f"{b['std']:>8.3f} {b['skew']:>+6.2f} {b['kurt']:>+6.2f} "
            f"{b['p5']:>+7.2f} {b['p25']:>+7.2f} {b['p50']:>+7.2f} "
            f"{b['p75']:>+7.2f} {b['p95']:>+7.2f}"
        )
    print(
        f"{'全局基线':<20} {bl['n']:>5} {bl['mean']:>+8.3f} "
        f"{'(参考)':>16} {bl['std']:>8.3f} {bl['skew']:>+6.2f} {bl['kurt']:>+6.2f} "
        f"{bl['p5']:>+7.2f} {bl['p25']:>+7.2f} {bl['p50']:>+7.2f} "
        f"{bl['p75']:>+7.2f} {bl['p95']:>+7.2f}"
    )


def plot_figure(
    panels: dict, edges: list[float], code: str, output_png: Path,
    today_window: int, next_window: int,
) -> None:
    plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "WenQuanYi Zen Hei"]
    plt.rcParams["axes.unicode_minus"] = False

    fig, axes = plt.subplots(1, 2, figsize=(15, 6.5), constrained_layout=True)
    bucket_labels = [bucket_label(edges[i], edges[i + 1]) for i in range(len(edges) - 1)]
    x_pos = np.arange(len(bucket_labels))

    for ax, d in zip(axes, ("bull", "bear")):
        p = panels[d]
        buckets = p["buckets"]
        baseline_mean = p["baseline"]["mean"]

        box_data = [b["y"] if b["n"] >= 5 else [] for b in buckets]
        ax.boxplot(
            box_data, positions=x_pos, widths=0.55,
            whis=[5, 95], showfliers=False, patch_artist=True,
            boxprops=dict(facecolor="#c6dbef", edgecolor="#3182bd", lw=1.0),
            whiskerprops=dict(color="#3182bd", lw=1.0),
            capprops=dict(color="#3182bd", lw=1.0),
            medianprops=dict(color="black", lw=1.2),
        )
        for i, b in enumerate(buckets):
            if b["n"] >= 5:
                ci = 1.96 * b["se_mean"]
                ax.errorbar(
                    i, b["mean"], yerr=ci,
                    color="#d62728", lw=1.0, capsize=3, zorder=4,
                )
                ax.plot(i, b["mean"], "o", color="#d62728", ms=5, zorder=5)

        ax.axhline(0, color="gray", lw=0.6, alpha=0.5)
        ax.axhline(
            baseline_mean, color="#ff7f0e", lw=1.3, ls="--",
            label=f"全局均值 {baseline_mean:+.3f}%",
        )

        ymax = max(
            (b["p95"] for b in buckets if b["n"] >= 5), default=1
        )
        for i, b in enumerate(buckets):
            if b["n"] > 0:
                ax.text(
                    i, ymax * 1.02, f"n={b['n']}",
                    ha="center", va="bottom", fontsize=7, color="#555",
                )

        ax.set_xticks(x_pos)
        ax.set_xticklabels(bucket_labels, rotation=35, ha="right", fontsize=8)
        ax.set_xlabel(f"前 {today_window} 日收益桶")
        ax.set_ylabel(f"之后 {next_window} 日收益（%）")
        ax.set_title(f"{DIR_CN[d]}  N={p['n']:,}", fontsize=12, fontweight="bold")
        ax.grid(True, axis="y", alpha=0.3)
        ax.legend(loc="upper right", fontsize=8)

    fig.suptitle(
        f"{code} 前 {today_window} 日收益分桶 → 之后 {next_window} 日收益 条件分布"
        f"（须=P5/P95、箱=P25/P75、红点=均值±95%CI、橙虚=全局均值，n<5 不画）",
        fontsize=12.5, fontweight="bold",
    )

    output_png.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_png, dpi=130, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved to {output_png}")


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
        help="截止当日的 N1 日收益窗口长度（默认 1，即当天收益）",
    )
    p.add_argument(
        "--next-window", type=int, default=1,
        help="之后的 N2 日收益窗口长度（默认 1，即次日收益）",
    )
    p.add_argument(
        "--bucket-edges", type=str, default=None,
        help="桶边界（%，逗号分隔，支持 -inf/inf）。"
             "默认 -inf,-8,-5,-3,-1,0,1,3,5,8,inf",
    )
    p.add_argument("--output", type=Path, default=None, help="输出 PNG 路径")
    args = p.parse_args()

    if args.today_window < 1 or args.next_window < 1:
        raise SystemExit("--today-window 和 --next-window 必须 >= 1")

    edges = parse_edges(args.bucket_edges)
    if len(edges) < 2:
        raise SystemExit("--bucket-edges 至少需要 2 个值")
    if any(b <= a for a, b in zip(edges, edges[1:])):
        raise SystemExit("--bucket-edges 必须严格递增")

    segments = load_segments(args.segments_csv)
    pairs = load_pair_returns(args.quote_path, args.today_window, args.next_window)
    pairs = label_regime(pairs, segments)

    panels: dict = {}
    for d in ("bull", "bear"):
        sub = pairs.filter(pl.col("regime") == d)
        x = sub["ret_today"].to_numpy() * 100
        y = sub["ret_next"].to_numpy() * 100
        panels[d] = compute_panel(x, y, edges)
        print_table(panels[d], DIR_CN[d], args.today_window, args.next_window)

    output = args.output or Path(
        f"/mnt/dataset/conditional_forward_return_{args.code}_"
        f"{args.today_window}b_{args.next_window}f.png"
    )
    plot_figure(
        panels, edges, args.code, output, args.today_window, args.next_window
    )


if __name__ == "__main__":
    main()
