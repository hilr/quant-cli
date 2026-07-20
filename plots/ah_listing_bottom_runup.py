"""A+H 上市：上市前 N 交易日 A 股的"底部 → 反弹最高点"形态分析（默认 N=120）。

回答：「在每家公司港股上市日 D 之前 N 个交易日内（默认 120 ≈ 半年），A 股
的最低点出现在距 D 多少个交易日？低点到之后的最高点反弹了多少？反弹花了多久？」

口径：
- 卖出日 = D（港股上市日），用 D 当天或之前最近一个 A 股交易日的收盘价 close[list_idx]
- 分析窗口 = [list_idx − N + 1, list_idx]，共 ≤ N 个交易日
- min_idx = argmin(close) 在窗口内
- max_idx = argmax(close[min_idx : list_idx+1])，即 min 之后到上市日之间的最高点
  （含上市日当天）
- min_to_list_days = list_idx − min_idx（最低点距上市日的交易日数）
- min_to_max_days = max_idx − min_idx（低点到最高点的交易日数）
- max_to_list_days = list_idx − max_idx（最高点距上市日的交易日数）
- runup_pct = (close[max_idx] / close[min_idx] − 1) × 100（低→高收益率）
- list_vs_peak_pct = (close[list_idx] / close[max_idx] − 1) × 100
  （上市日相对最高点的回撤）

输出：
- PNG：2×3 面板
    左上：min_to_list_days 分布直方图
    中上：min_to_max_days 分布直方图
    右上：runup_pct 分布直方图
    左下：max_to_list_days 分布直方图
    中下：list_vs_peak_pct 分布直方图
    右下：min_to_list_days vs runup_pct 散点（带线性拟合 + ρ）
- CSV：每家公司的 min/max/list 日期、价格、各距离与收益率
- 控制台：每个指标的 N/均值/中位/σ/分位
"""
from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import polars as pl
from python_calamine import CalamineWorkbook


def load_companies(xlsx_path: Path) -> pl.DataFrame:
    wb = CalamineWorkbook.from_path(str(xlsx_path))
    rows = wb.get_sheet_by_name("Sheet1").to_python()
    header, data = rows[0], rows[1:]
    str_rows = [[str(v) for v in r] for r in data]
    df = pl.DataFrame(str_rows, schema=list(header), infer_schema_length=None,
                      orient="row")
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
    df: pl.DataFrame, list_date: dt.date, window: int
) -> dict | None:
    dates = df["date"].to_numpy()
    closes = df["close"].to_numpy()
    list_idx = _last_idx_at_or_before(dates, list_date)
    if list_idx is None:
        return None

    start_idx = max(0, list_idx - window + 1)
    if list_idx - start_idx < 2:
        return None

    # 在窗口内找最低点
    window_closes = closes[start_idx : list_idx + 1]
    min_rel = int(np.argmin(window_closes))
    min_idx = start_idx + min_rel

    # min 之后到 list_idx（含）找最高点
    after_min = closes[min_idx : list_idx + 1]
    max_rel = int(np.argmax(after_min))
    max_idx = min_idx + max_rel

    min_close = float(closes[min_idx])
    max_close = float(closes[max_idx])
    list_close = float(closes[list_idx])

    runup_pct = (max_close / min_close - 1.0) * 100.0
    list_vs_peak_pct = (list_close / max_close - 1.0) * 100.0

    return {
        "list_idx": list_idx,
        "window_size": list_idx - start_idx + 1,
        "min_date": df["date"][min_idx],
        "min_close": min_close,
        "max_date": df["date"][max_idx],
        "max_close": max_close,
        "list_date_used": df["date"][list_idx],
        "list_close": list_close,
        "min_to_list_days": list_idx - min_idx,
        "min_to_max_days": max_idx - min_idx,
        "max_to_list_days": list_idx - max_idx,
        "runup_pct": runup_pct,
        "list_vs_peak_pct": list_vs_peak_pct,
    }


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
        "p10": float(np.percentile(arr, 10)),
        "p25": float(np.percentile(arr, 25)),
        "p75": float(np.percentile(arr, 75)),
        "p90": float(np.percentile(arr, 90)),
        "p95": float(np.percentile(arr, 95)),
        "se_mean": std / np.sqrt(n) if not np.isnan(std) else float("nan"),
    }


def fmt(s: dict, unit: str = "") -> str:
    ci = (
        f"({s['mean'] - 1.96 * s['se_mean']:+.2f},"
        f"{s['mean'] + 1.96 * s['se_mean']:+.2f})"
        if not np.isnan(s["se_mean"])
        else "—"
    )
    return (
        f"{s['n']:>4}{s['mean']:>10.2f}{ci:>20}{s['median']:>10.2f}"
        f"{s['std']:>9.2f}{s['p5']:>9.2f}{s['p25']:>9.2f}"
        f"{s['p75']:>9.2f}{s['p95']:>9.2f}"
    )


def print_stats(rows: list[dict]) -> None:
    metrics = [
        ("min_to_list_days", "最低点距上市日（交易日）"),
        ("min_to_max_days", "低点 → 最高点（交易日）"),
        ("max_to_list_days", "最高点距上市日（交易日）"),
        ("runup_pct", "低点 → 最高点 收益率（%）"),
        ("list_vs_peak_pct", "上市日 vs 最高点（%）"),
    ]
    print("\n=== 形态指标分布 ===")
    hdr = (
        f"{'指标':<26}{'N':>4}{'均值':>10}{'±95%CI':>20}{'中位':>10}"
        f"{'σ':>9}{'P5':>9}{'P25':>9}{'P75':>9}{'P95':>9}"
    )
    print(hdr)
    print("-" * len(hdr))
    for key, label in metrics:
        arr = np.array([r[key] for r in rows], dtype=float)
        s = stats_block(arr)
        print(f"{label:<26}{fmt(s)}")
    # 额外：有多少公司最低点出现在上市前 30 / 60 / 90 交易日之内
    print("\n=== 最低点时机分布 ===")
    arr = np.array([r["min_to_list_days"] for r in rows])
    for thr in (10, 20, 30, 60, 90, 120, 180, 250):
        cnt = int(np.sum(arr <= thr))
        print(f"  最低点距上市日 <= {thr:>3} 交易日：{cnt:>3} / {len(arr)} "
              f"({cnt / len(arr) * 100:.1f}%)")
    # 额外：上市日是否就是最高点
    arr_max_at_list = np.array(
        [r["max_to_list_days"] == 0 for r in rows]
    )
    cnt = int(arr_max_at_list.sum())
    print(f"\n上市日即窗口最高点：{cnt} / {len(arr_max_at_list)} "
          f"({cnt / len(arr_max_at_list) * 100:.1f}%)")


def plot_hist(
    ax, arr: np.ndarray, title: str, xlabel: str, color: str = "#9ecae1"
) -> None:
    s = stats_block(arr)
    if arr.max() - arr.min() < 1:
        bins = np.linspace(arr.min() - 0.5, arr.max() + 0.5, 10)
    else:
        bins = max(8, int(np.sqrt(len(arr)) * 1.5))
    ax.hist(arr, bins=bins, color=color, edgecolor="white", linewidth=0.5,
            alpha=0.85)
    ax.axvline(s["mean"], color="#ff7f0e", lw=1.4, ls="--",
               label=f"均值 {s['mean']:.1f}")
    ax.axvline(s["median"], color="#1f77b4", lw=1.2, ls=":",
               label=f"中位 {s['median']:.1f}")
    txt = (
        f"N = {s['n']}\n"
        f"均值 {s['mean']:.2f}  ±95%CI "
        f"({s['mean']-1.96*s['se_mean']:.1f},"
        f"{s['mean']+1.96*s['se_mean']:.1f})\n"
        f"σ {s['std']:.2f}\n"
        f"P5/25/75/95\n {s['p5']:.1f} / {s['p25']:.1f} / "
        f"{s['p75']:.1f} / {s['p95']:.1f}"
    )
    ax.text(0.97, 0.97, txt, transform=ax.transAxes, ha="right", va="top",
            fontsize=8.5,
            bbox=dict(boxstyle="round,pad=0.4", fc="white", ec="#bbb",
                      alpha=0.92))
    ax.set_title(title, fontsize=11, fontweight="bold")
    ax.set_xlabel(xlabel)
    ax.set_ylabel("公司数")
    ax.grid(True, axis="y", alpha=0.3)
    ax.legend(loc="upper left", fontsize=7.5)


def plot_figure(rows: list[dict], output_png: Path, window: int) -> None:
    plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "WenQuanYi Zen Hei"]
    plt.rcParams["axes.unicode_minus"] = False

    fig, axes = plt.subplots(2, 3, figsize=(17, 9.5), constrained_layout=True)

    plot_hist(
        axes[0, 0],
        np.array([r["min_to_list_days"] for r in rows], dtype=float),
        "最低点距上市日",
        "交易日数",
    )
    plot_hist(
        axes[0, 1],
        np.array([r["min_to_max_days"] for r in rows], dtype=float),
        "低点 → 最高点 持续时间",
        "交易日数",
        color="#a1d99b",
    )
    plot_hist(
        axes[0, 2],
        np.array([r["runup_pct"] for r in rows], dtype=float),
        "低点 → 最高点 收益率",
        "收益率（%）",
        color="#fdae6b",
    )
    plot_hist(
        axes[1, 0],
        np.array([r["max_to_list_days"] for r in rows], dtype=float),
        "最高点距上市日",
        "交易日数（0 = 上市日即最高）",
        color="#c6dbef",
    )
    plot_hist(
        axes[1, 1],
        np.array([r["list_vs_peak_pct"] for r in rows], dtype=float),
        "上市日相对最高点",
        "收益率（%，负值 = 上市日已回调）",
        color="#fcae91",
    )

    # 散点：min_to_list_days vs runup_pct
    ax = axes[1, 2]
    x = np.array([r["min_to_list_days"] for r in rows], dtype=float)
    y = np.array([r["runup_pct"] for r in rows], dtype=float)
    ax.scatter(x, y, s=45, alpha=0.7, color="#3182bd", edgecolor="white",
               linewidth=0.5)
    if len(x) > 2 and x.std() > 0:
        coef = np.polyfit(x, y, 1)
        xs = np.linspace(x.min(), x.max(), 50)
        ax.plot(xs, np.polyval(coef, xs), "r-", lw=1.2,
                label=f"线性拟合  斜率 {coef[0]:.3f}")
        rho = float(np.corrcoef(x, y)[0, 1])
        ax.set_title(f"底部时机 vs 反弹幅度  ρ = {rho:+.2f}",
                     fontsize=11, fontweight="bold")
    ax.axhline(0, color="gray", lw=0.5, alpha=0.6)
    ax.axhline(np.median(y), color="#1f77b4", lw=1.0, ls=":",
               label=f"中位反弹 {np.median(y):.1f}%")
    ax.set_xlabel("最低点距上市日（交易日）")
    ax.set_ylabel("低点 → 最高点 收益率（%）")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="lower right", fontsize=7.5)

    fig.suptitle(
        f"A+H 上市：上市前 {window} 交易日 A 股 最低点 → 反弹最高点 形态分析"
        f"（{len(rows)} 家公司）",
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
        "--window", type=int, default=120,
        help="上市前回看的交易日窗口长度（默认 120 ≈ 半年）",
    )
    p.add_argument(
        "--as-of", type=str, default=None,
        help="只保留 港股上市日 <= 此日期 的公司（YYYY-MM-DD，默认今天）",
    )
    p.add_argument(
        "--output-png", type=Path,
        default=Path("/mnt/dataset/ah_listing_bottom_runup.png"),
    )
    p.add_argument(
        "--output-csv", type=Path,
        default=Path("/mnt/dataset/ah_listing_bottom_runup.csv"),
    )
    args = p.parse_args()

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
        out = compute_company(df, list_date, args.window)
        if out is None:
            skipped.append((code, name, "数据不足"))
            continue
        out["code"] = code
        out["name"] = name
        out["hk_code"] = comp.get("港股代码")
        out["industry"] = comp.get("行业")
        out["list_date"] = list_date
        rows.append(out)

    if skipped:
        print(f"\n跳过 {len(skipped)} 条：")
        for s in skipped:
            print(f"  {s}")

    print(f"\n有效公司数：{len(rows)}")
    print_stats(rows)

    detail = pl.DataFrame(rows).with_columns(
        pl.col("code").cast(pl.Utf8).str.zfill(6)
    )
    cols = [
        "code", "name", "hk_code", "industry", "list_date",
        "window_size",
        "min_date", "min_close",
        "max_date", "max_close",
        "list_date_used", "list_close",
        "min_to_list_days", "min_to_max_days", "max_to_list_days",
        "runup_pct", "list_vs_peak_pct",
    ]
    detail = detail.select(cols).sort("runup_pct", descending=True)
    detail.write_csv(args.output_csv)
    print(f"\n明细 CSV：{args.output_csv}")

    plot_figure(rows, args.output_png, args.window)


if __name__ == "__main__":
    main()
