"""A+H 上市：港股上市日前 2/3 月买入 A 股 → 持有期内最高收益率分布。

回答：「A 股公司在港股上市日 D 之前 2 / 3 个月买入、持有到 D 期间，
A 股最高能涨到多少？买入点在过去 120 日价格通道里的位置对峰值涨幅有预测力吗？」

口径：
- 买入日 = D − Δ（Δ ∈ {60, 90} 自然日，即 2m / 3m），向最近 A 股交易日对齐
- 持有期 = [buy_idx, list_idx]（含两端）
- list_idx = D 当天或之前最近一个 A 股交易日
- max_close = max(close[buy_idx : list_idx+1])，持有期内最高收盘价
- max_ret = (max_close / close[buy_idx] − 1) × 100  ← 本次主指标
- 通道位置 pos_120 = (close[buy_idx] − min) / (max − min)，
  min/max 取过去 120 个交易日（含 buy 当日）的 close；0 = 买在过去 120 日最低点，1 = 最高点

数据来源：用户提供的 A+H 公司清单（xlsx）+ /mnt/dataset/stock_quote_adjusted/

输出：
- PNG：2 行 × N 列面板（N = offsets 数，默认 2）
    第 1 行：每个 offset 的 max_ret 直方图
    第 2 行：每个 offset 按 120 日通道位置分桶的 max_ret 箱线图
- CSV：每行一个 (公司 × offset) 观测
- 控制台：总分布 + 按 120 日位置分桶的条件分布
"""
from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import polars as pl
from python_calamine import CalamineWorkbook

OFFSET_LABELS = {60: "2m", 90: "3m"}
DEFAULT_POSITION_EDGES = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
LOOKBACK = 120


def load_companies(xlsx_path: Path) -> pl.DataFrame:
    wb = CalamineWorkbook.from_path(str(xlsx_path))
    rows = wb.get_sheet_by_name("Sheet1").to_python()
    header, data = rows[0], rows[1:]
    str_rows = [[str(v) for v in r] for r in data]
    df = pl.DataFrame(
        str_rows, schema=list(header), infer_schema_length=None, orient="row"
    )
    df = df.with_columns(
        pl.col("港股上市日期").str.to_date("%Y-%m-%d", strict=False),
        pl.col("A股代码").str.slice(0, 6).alias("a_code"),
    )
    df = df.unique(subset=["a_code", "港股上市日期"], keep="first")
    return df


def load_closes(adjusted_dir: Path, code: str) -> pl.DataFrame:
    return (
        pl.read_parquet(adjusted_dir / f"{code}.parquet", columns=["date", "close"])
        .with_columns(pl.col("date").str.to_date("%Y-%m-%d"))
        .sort("date")
    )


def _last_idx_at_or_before(dates: np.ndarray, target: dt.date) -> int | None:
    target_np = np.datetime64(target, "ns")
    idx = np.searchsorted(dates, target_np, side="right") - 1
    return int(idx) if idx >= 0 else None


def compute_company(
    df: pl.DataFrame, list_date: dt.date, offsets: list[int]
) -> list[dict]:
    dates = df["date"].to_numpy()
    closes = df["close"].to_numpy()
    list_idx = _last_idx_at_or_before(dates, list_date)
    if list_idx is None:
        return []
    list_close = float(closes[list_idx])
    list_date_used = df["date"][list_idx]

    out = []
    for off in offsets:
        target = list_date - dt.timedelta(days=off)
        buy_idx = _last_idx_at_or_before(dates, target)
        if buy_idx is None or buy_idx >= list_idx:
            continue
        buy_close = float(closes[buy_idx])
        if buy_close <= 0:
            continue

        hold = closes[buy_idx : list_idx + 1]
        max_rel = int(np.argmax(hold))
        max_idx = buy_idx + max_rel
        max_close = float(closes[max_idx])

        max_ret = (max_close / buy_close - 1.0) * 100.0

        # 买入点在过去 LOOKBACK 个交易日的 close 区间里的位置
        chan_start = max(0, buy_idx - LOOKBACK + 1)
        chan = closes[chan_start : buy_idx + 1]
        if len(chan) < 2:
            pos_120 = float("nan")
        else:
            lo = float(chan.min())
            hi = float(chan.max())
            pos_120 = (buy_close - lo) / (hi - lo) if hi > lo else 0.5

        out.append(
            {
                "offset": off,
                "buy_date": df["date"][buy_idx],
                "buy_close": buy_close,
                "max_date": df["date"][max_idx],
                "max_close": max_close,
                "max_to_list_days": list_idx - max_idx,
                "list_date_used": list_date_used,
                "list_close": list_close,
                "hold_days": list_idx - buy_idx,
                "max_ret": max_ret,
                "pos_120": pos_120,
            }
        )
    return out


def stats_block(arr: np.ndarray) -> dict:
    n = len(arr)
    if n == 0:
        return {"n": 0}
    std = float(np.std(arr, ddof=1)) if n > 1 else float("nan")
    return {
        "n": n,
        "mean": float(np.mean(arr)),
        "median": float(np.median(arr)),
        "std": std,
        "p5": float(np.percentile(arr, 5)),
        "p25": float(np.percentile(arr, 25)),
        "p75": float(np.percentile(arr, 75)),
        "p95": float(np.percentile(arr, 95)),
        "p_pos": float(np.mean(arr > 0) * 100),
        "se_mean": std / np.sqrt(n) if not np.isnan(std) else float("nan"),
    }


def fmt_row(label: str, s: dict) -> str:
    if s["n"] == 0:
        return f"{label:<14}{0:>4}"
    ci = (
        f"({s['mean'] - 1.96 * s['se_mean']:+.2f},"
        f"{s['mean'] + 1.96 * s['se_mean']:+.2f})"
        if not np.isnan(s["se_mean"])
        else "—"
    )
    return (
        f"{label:<14}{s['n']:>4}{s['mean']:>+10.2f}{ci:>22}{s['median']:>+10.2f}"
        f"{s['std']:>9.2f}{s['p_pos']:>8.1f}%{s['p5']:>+9.2f}{s['p95']:>+9.2f}"
    )


def bucket_index(value: float, edges: list[float]) -> int:
    """半开 [lo, hi)，最后一个桶闭区间。"""
    for i in range(len(edges) - 1):
        lo, hi = edges[i], edges[i + 1]
        if (i < len(edges) - 2 and lo <= value < hi) or (
            i == len(edges) - 2 and lo <= value <= hi
        ):
            return i
    return -1


def bucket_label(lo: float, hi: float, is_last: bool) -> str:
    right = "]" if is_last else ")"
    return f"[{lo*100:.0f}%, {hi*100:.0f}%{right}"


def print_stats(
    rows: list[dict], offsets: list[int], edges: list[float]
) -> None:
    print("\n=== 持有期内最高收益率（总分布）===")
    hdr = (
        f"{'指标':<14}{'N':>4}{'均值%':>10}{'±95%CI':>22}{'中位%':>10}"
        f"{'σ%':>9}{'P(>0)':>8}{'P5%':>9}{'P95%':>9}"
    )
    print(hdr)
    print("-" * len(hdr))
    for off in offsets:
        sub = [r for r in rows if r["offset"] == off]
        print(f"\n  -- offset = {OFFSET_LABELS[off]}（买入日：D-{off}d）--")
        max_arr = np.array([r["max_ret"] for r in sub], dtype=float)
        print(fmt_row("最高收益率", stats_block(max_arr)))
        cnt_peak_at_list = sum(1 for r in sub if r["max_to_list_days"] == 0)
        print(
            f"  其中峰值就在上市日的：{cnt_peak_at_list} / {len(sub)} "
            f"({cnt_peak_at_list / len(sub) * 100:.1f}%)"
        )

    print(f"\n=== 按 {LOOKBACK} 日通道位置分桶（基于 max_ret） ===")
    bhdr = (
        f"{'位置桶':<14}{'N':>4}{'均值%':>10}{'±95%CI':>22}"
        f"{'α vs 全局':>11}{'中位%':>10}{'σ%':>9}{'P(>0)':>8}"
    )
    for off in offsets:
        print(f"\n  -- offset = {OFFSET_LABELS[off]}（买入日：D-{off}d）--")
        print(bhdr)
        print("-" * len(bhdr))
        off_rows = [
            r for r in rows
            if r["offset"] == off and not np.isnan(r.get("pos_120", np.nan))
        ]
        overall = stats_block(np.array([r["max_ret"] for r in off_rows], dtype=float))
        base = overall["mean"]
        for i in range(len(edges) - 1):
            lo, hi = edges[i], edges[i + 1]
            in_bucket = [
                r for r in off_rows if bucket_index(r["pos_120"], edges) == i
            ]
            arr = np.array([r["max_ret"] for r in in_bucket], dtype=float)
            if len(arr) == 0:
                print(f"{bucket_label(lo, hi, i == len(edges) - 2):<14}{0:>4}")
                continue
            s = stats_block(arr)
            ci = (
                f"({s['mean'] - 1.96 * s['se_mean']:+.2f},"
                f"{s['mean'] + 1.96 * s['se_mean']:+.2f})"
                if not np.isnan(s["se_mean"])
                else "—"
            )
            alpha = s["mean"] - base
            print(
                f"{bucket_label(lo, hi, i == len(edges) - 2):<14}"
                f"{s['n']:>4}{s['mean']:>+10.2f}{ci:>22}{alpha:>+11.2f}"
                f"{s['median']:>+10.2f}{s['std']:>9.2f}{s['p_pos']:>7.1f}%"
            )
        print(
            f"{'全局':<14}{overall['n']:>4}{overall['mean']:>+10.2f}{'(参考)':>22}"
            f"{'':>11}{overall['median']:>+10.2f}{overall['std']:>9.2f}"
            f"{overall['p_pos']:>7.1f}%"
        )


def plot_hist(
    ax, arr: np.ndarray, title: str, xlabel: str, color: str = "#9ecae1",
) -> None:
    s = stats_block(arr)
    if arr.max() - arr.min() < 1:
        bins = np.linspace(arr.min() - 0.5, arr.max() + 0.5, 10)
    else:
        bins = max(10, int(np.sqrt(len(arr)) * 1.6))
    ax.hist(
        arr, bins=bins, color=color, edgecolor="white",
        linewidth=0.5, alpha=0.85,
    )
    ax.axvline(0, color="black", lw=0.7)
    ax.axvline(s["mean"], color="#ff7f0e", lw=1.4, ls="--",
               label=f"均值 {s['mean']:+.2f}%")
    ax.axvline(s["median"], color="#1f77b4", lw=1.2, ls=":",
               label=f"中位 {s['median']:+.2f}%")
    txt = (
        f"N = {s['n']}\n"
        f"均值 {s['mean']:+.2f}%  ±95%CI "
        f"({s['mean']-1.96*s['se_mean']:+.1f},"
        f"{s['mean']+1.96*s['se_mean']:+.1f})\n"
        f"σ {s['std']:.2f}%  P(>0) {s['p_pos']:.1f}%\n"
        f"P5 / P95\n {s['p5']:+.1f} / {s['p95']:+.1f}"
    )
    ax.text(
        0.97, 0.97, txt, transform=ax.transAxes, ha="right", va="top",
        fontsize=8.5,
        bbox=dict(boxstyle="round,pad=0.4", fc="white", ec="#bbb", alpha=0.92),
    )
    ax.set_title(title, fontsize=11, fontweight="bold")
    ax.set_xlabel(xlabel)
    ax.set_ylabel("公司数")
    ax.grid(True, axis="y", alpha=0.3)
    ax.legend(loc="upper left", fontsize=7.5)


def plot_box(
    ax,
    off_rows: list[dict],
    edges: list[float],
    title: str,
) -> None:
    rets_all = np.array([r["max_ret"] for r in off_rows], dtype=float)
    base_mean = float(np.mean(rets_all)) if len(rets_all) else 0.0

    box_data, positions, labels, ns = [], [], [], []
    for i in range(len(edges) - 1):
        in_bucket = [
            r for r in off_rows if bucket_index(r["pos_120"], edges) == i
        ]
        arr = np.array([r["max_ret"] for r in in_bucket], dtype=float)
        box_data.append(arr if len(arr) >= 3 else [])
        positions.append(i)
        labels.append(bucket_label(edges[i], edges[i + 1], i == len(edges) - 2))
        ns.append(len(arr))

    ax.boxplot(
        box_data, positions=positions, widths=0.55,
        whis=[5, 95], showfliers=False, patch_artist=True,
        boxprops=dict(facecolor="#c6dbef", edgecolor="#3182bd", lw=1.0),
        whiskerprops=dict(color="#3182bd", lw=1.0),
        capprops=dict(color="#3182bd", lw=1.0),
        medianprops=dict(color="black", lw=1.2),
    )
    ymax = max(
        (np.percentile(d, 95) for d in box_data if len(d) >= 3),
        default=1.0,
    )
    ymin = min(
        (np.percentile(d, 5) for d in box_data if len(d) >= 3),
        default=0.0,
    )
    for i, d in enumerate(box_data):
        if len(d) >= 3:
            s = stats_block(d)
            ci95 = 1.96 * s["se_mean"]
            ax.errorbar(i, s["mean"], yerr=ci95, color="#d62728",
                        lw=1.0, capsize=3, zorder=4)
            ax.plot(i, s["mean"], "o", color="#d62728", ms=5, zorder=5)
        if ns[i] > 0:
            ax.text(i, ymax * 1.04, f"n={ns[i]}", ha="center",
                    va="bottom", fontsize=7, color="#555")

    ax.axhline(0, color="gray", lw=0.6, alpha=0.6)
    ax.axhline(base_mean, color="#ff7f0e", lw=1.3, ls="--",
               label=f"全局均值 {base_mean:+.2f}%")
    ax.set_xticks(positions)
    ax.set_xticklabels(labels, rotation=20, ha="right", fontsize=8)
    ax.set_xlabel(f"买入点在 {LOOKBACK} 日通道里的位置")
    ax.set_ylabel("持有期内最高收益率（%）")
    ax.set_ylim(ymin * 1.15, ymax * 1.15)
    ax.set_title(title, fontsize=10.5, fontweight="bold")
    ax.grid(True, axis="y", alpha=0.3)
    ax.legend(loc="upper left", fontsize=7.5)


def plot_figure(
    rows: list[dict],
    offsets: list[int],
    edges: list[float],
    output_png: Path,
) -> None:
    plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "WenQuanYi Zen Hei"]
    plt.rcParams["axes.unicode_minus"] = False

    n_cols = len(offsets)
    fig, axes = plt.subplots(
        2, n_cols, figsize=(8.0 * n_cols, 8.5), constrained_layout=True,
    )
    if n_cols == 1:
        axes = axes.reshape(2, 1)

    for ci, off in enumerate(offsets):
        sub = [r for r in rows if r["offset"] == off]
        max_arr = np.array([r["max_ret"] for r in sub], dtype=float)
        plot_hist(
            axes[0, ci], max_arr,
            title=f"前 {OFFSET_LABELS[off]} 买入 → 持有期内最高收益率",
            xlabel="最高收益率（%）",
            color="#9ecae1",
        )
        plot_box(
            axes[1, ci],
            [r for r in sub if not np.isnan(r.get("pos_120", np.nan))],
            edges,
            title=f"前 {OFFSET_LABELS[off]} 买入 × {LOOKBACK}d 通道位置  "
                  f"(N={len([r for r in sub if not np.isnan(r.get('pos_120', np.nan))])})",
        )

    fig.suptitle(
        f"A+H 上市：上市前 { '/'.join(OFFSET_LABELS[o] for o in offsets)} 买入"
        f" → 持有期内最高收益率（{len(set(r['code'] for r in rows))} 家公司）",
        fontsize=13, fontweight="bold",
    )
    output_png.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_png, dpi=130, bbox_inches="tight")
    plt.close(fig)
    print(f"\nSaved to {output_png}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--input-xlsx", type=Path, required=True,
        help="A+H 公司清单 xlsx",
    )
    p.add_argument(
        "--adjusted-dir", type=Path,
        default=Path("/mnt/dataset/stock_quote_adjusted"),
    )
    p.add_argument(
        "--calendar-offsets", type=int, nargs="+", default=[60, 90],
        help="买入日相对港股上市日倒推的自然日偏移（默认 60 90 = 2m / 3m）",
    )
    p.add_argument(
        "--bucket-edges", type=float, nargs="+",
        default=DEFAULT_POSITION_EDGES,
        help="通道位置桶边界（0~1，默认 0 0.2 0.4 0.6 0.8 1.0）",
    )
    p.add_argument(
        "--as-of", type=str, default=None,
        help="只保留 港股上市日 <= 此日期 的公司（YYYY-MM-DD，默认今天）",
    )
    p.add_argument(
        "--output-png", type=Path,
        default=Path("/mnt/dataset/ah_listing_runup.png"),
    )
    p.add_argument(
        "--output-csv", type=Path,
        default=Path("/mnt/dataset/ah_listing_runup.csv"),
    )
    args = p.parse_args()

    if len(args.bucket_edges) < 2:
        raise SystemExit("--bucket-edges 至少需要 2 个值")
    if any(b <= a for a, b in zip(args.bucket_edges, args.bucket_edges[1:])):
        raise SystemExit("--bucket-edges 必须严格递增")
    if args.bucket_edges[0] != 0.0 or args.bucket_edges[-1] != 1.0:
        raise SystemExit("--bucket-edges 必须以 0.0 开始、1.0 结束")

    for off in args.calendar_offsets:
        OFFSET_LABELS.setdefault(off, f"{off}d")

    as_of = (
        dt.datetime.strptime(args.as_of, "%Y-%m-%d").date()
        if args.as_of
        else dt.date.today()
    )

    companies = load_companies(args.input_xlsx).filter(
        pl.col("港股上市日期") <= as_of
    )
    print(f"已上市（港股上市日 <= {as_of}）公司数：{companies.height}")

    rows = []
    skipped = []
    for comp in companies.iter_rows(named=True):
        code = comp["a_code"]
        name = comp["公司名称"]
        list_date = comp["港股上市日期"]
        try:
            df = load_closes(args.adjusted_dir, code)
        except FileNotFoundError:
            skipped.append((code, name, "无价格文件"))
            continue
        if df.height == 0:
            skipped.append((code, name, "价格空"))
            continue
        latest = df["date"].max()
        if list_date > latest:
            skipped.append(
                (code, name, f"港股上市日 {list_date} 晚于数据截止 {latest}（疑似未上市）")
            )
            continue
        out = compute_company(df, list_date, args.calendar_offsets)
        if not out:
            skipped.append((code, name, "上市日早于价格起点"))
            continue
        for r in out:
            r["code"] = code
            r["name"] = name
            r["hk_code"] = comp.get("港股代码")
            r["industry"] = comp.get("行业")
            r["list_date"] = list_date
            rows.append(r)

    if skipped:
        print(f"\n跳过 {len(skipped)} 条：")
        for s in skipped:
            print(f"  {s}")

    print(f"\n有效观测数：{len(rows)} "
          f"（{len(set((r['code'], r['list_date']) for r in rows))} 家公司 × "
          f"{len(args.calendar_offsets)} 个 offset）")

    print_stats(rows, args.calendar_offsets, args.bucket_edges)

    detail = pl.DataFrame(rows).with_columns(
        pl.col("code").cast(pl.Utf8).str.zfill(6)
    )
    cols = [
        "code", "name", "hk_code", "industry", "list_date", "offset",
        "buy_date", "buy_close", "pos_120",
        "max_date", "max_close", "max_to_list_days",
        "list_date_used", "list_close",
        "hold_days", "max_ret",
    ]
    detail = detail.select(cols).sort(
        ["offset", "max_ret"], descending=[False, True]
    )
    detail.write_csv(args.output_csv)
    print(f"\n明细 CSV：{args.output_csv}")

    plot_figure(rows, args.calendar_offsets, args.bucket_edges, args.output_png)


if __name__ == "__main__":
    main()
