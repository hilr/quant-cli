"""天量天价事件研究：成交额异常放大能否预测指数顶部？

单指数分析：天量与天价都用同一指数（--code，默认上证综指 000001）。
  - 天量 = {code}.turnover（该指数全部成交额）
  - 天价 = {code}.close

两种天量定义并行：
  - A：成交额创过去 N 日（默认 250）新高（含当日，实时可知）
  - B：成交额 / MA(默认 60) ≥ 倍数（默认 2.0）

事件研究：对每个冷却去重后的天量日，算此后 5/20/60 个交易日指数前向收益，
与全部交易日基线对比，bootstrap 95% CI 估计差值。
并用 ZigZag 标记上证综指阶段高点，量化「天量事件→后续阶段高点」的间隔。

信号在完整历史上计算（保证预热），再 mask 到 --start-date 之后。
"""
from __future__ import annotations

import argparse
import bisect
import csv
import random
from datetime import date
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import polars as pl

INDEX_CODE = "000001"


def load_index(index_dir: Path, code: str) -> pl.DataFrame:
    return (
        pl.read_parquet(
            index_dir / f"{code}.parquet",
            columns=["date", "close", "turnover", "high", "low"],
        )
        .with_columns(pl.col("date").str.to_date("%Y-%m-%d"))
        .sort("date")
    )


def build_signals(df: pl.DataFrame, roll_high: int, ma: int, mult: float) -> pl.DataFrame:
    """在完整历史上算信号（min_samples=window，预热期出 null 而非假信号）。"""
    ma_expr = pl.col("turnover").rolling_mean(window_size=ma, min_samples=ma)
    return df.with_columns(
        (
            pl.col("turnover")
            == pl.col("turnover").rolling_max(window_size=roll_high, min_samples=roll_high)
        ).alias("spike_A"),
        (pl.col("turnover") / ma_expr >= mult).alias("spike_B"),
        ma_expr.alias("_ma"),
    ).with_columns(
        (pl.col("turnover") / pl.col("_ma")).alias("turnover_vs_ma")
    ).drop("_ma")


def zigzag_pivots(highs: list, lows: list, pct: float) -> list[tuple[int, float, str]]:
    """回溯式 ZigZag 枢轴点。返回 [(idx, price, 'H'|'L'), ...]。

    pct = 最小反转幅度（如 0.08 = 8%）。上升段跟踪最高 high，下降段跟踪最低 low；
    反方向移动 ≥ pct 才确认枢轴。最后一个未确认的极值**不**返回（实时不可知）。
    因此标记落在真实峰值日，但「确认」存在滞后——这是 ZigZag 固有的回顾性。
    """
    n = len(highs)
    if n < 2:
        return []
    pivots: list[tuple[int, float, str]] = []
    direction = 0
    i = 1
    seed_h, seed_l = highs[0], lows[0]
    ext_idx, ext_val = 0, highs[0]
    while i < n and direction == 0:
        if highs[i] >= seed_l * (1 + pct):
            direction = 1
            pivots.append((0, lows[0], "L"))
            ext_idx, ext_val = i, highs[i]
        elif lows[i] <= seed_h * (1 - pct):
            direction = -1
            pivots.append((0, highs[0], "H"))
            ext_idx, ext_val = i, lows[i]
        i += 1
    if direction == 0:
        return []
    while i < n:
        if direction == 1:
            if highs[i] > ext_val:
                ext_idx, ext_val = i, highs[i]
            if lows[i] <= ext_val * (1 - pct):
                pivots.append((ext_idx, ext_val, "H"))
                direction = -1
                ext_idx, ext_val = i, lows[i]
        else:
            if lows[i] < ext_val:
                ext_idx, ext_val = i, lows[i]
            if highs[i] >= ext_val * (1 + pct):
                pivots.append((ext_idx, ext_val, "L"))
                direction = 1
                ext_idx, ext_val = i, highs[i]
        i += 1
    return pivots


def apply_cooldown(flags: list[bool], cooldown: int) -> list[int]:
    """位置索引贪心：首个信号胜出，保留事件间位置间隔 ≥ cooldown。"""
    last_kept = None
    events: list[int] = []
    for pos, flag in enumerate(flags):
        if not flag:
            continue
        if last_kept is None or (pos - last_kept) >= cooldown:
            events.append(pos)
            last_kept = pos
    return events


def compute_event_rows(
    positions: list[int],
    dates: list,
    closes: list,
    turnovers: list,
    to_vs_ma: list,
    horizons: list[int],
    n: int,
    signal_def: str,
) -> list[dict]:
    """每个事件位置算各 horizon 前向收益 + 最大回撤/涨幅（max horizon 窗口）。"""
    maxh = max(horizons)
    rows = []
    for i in positions:
        row: dict = {
            "signal_def": signal_def,
            "event_date": dates[i],
            "close_at_event": closes[i],
            "turnover_at_event": turnovers[i],
            "turnover_vs_ma": to_vs_ma[i],
        }
        for k in horizons:
            row[f"fwd_ret_{k}"] = (closes[i + k] / closes[i] - 1) if i + k < n else None
        if i + maxh < n:
            seg = closes[i : i + maxh + 1]
            base = closes[i]
            row["mdd"] = min(c / base - 1 for c in seg)
            row["max_gain"] = max(c / base - 1 for c in seg)
        else:
            row["mdd"] = None
            row["max_gain"] = None
        rows.append(row)
    return rows


def bootstrap_diff_ci(
    event_returns: list[float], baseline_mean: float, n_boot: int = 10000, seed: int = 7
) -> tuple[float, float]:
    """重采样事件集，对 (event_mean − baseline_mean) 取 2.5/97.5 分位。baseline 视为固定。"""
    if not event_returns:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    m = len(event_returns)
    diffs = []
    for _ in range(n_boot):
        s = 0.0
        for _ in range(m):
            s += event_returns[rng.randrange(m)]
        diffs.append(s / m - baseline_mean)
    diffs.sort()
    return diffs[int(0.025 * n_boot)], diffs[int(0.975 * n_boot)]


def summarize(event_rows: list[dict], baseline_means: dict, horizons: list[int]) -> dict:
    """返回 {horizon: stats}。"""
    out: dict = {}
    for k in horizons:
        rets = [r[f"fwd_ret_{k}"] for r in event_rows if r[f"fwd_ret_{k}"] is not None]
        if not rets:
            out[k] = None
            continue
        mean = float(np.mean(rets))
        median = float(np.median(rets))
        neg_pct = sum(1 for r in rets if r < 0) / len(rets)
        bmean = baseline_means[k]
        ci_lo, ci_hi = bootstrap_diff_ci(rets, bmean)
        out[k] = {
            "n_closable": len(rets),
            "mean": mean,
            "median": median,
            "neg_pct": neg_pct,
            "baseline_mean": bmean,
            "diff": mean - bmean,
            "ci_lo": ci_lo,
            "ci_hi": ci_hi,
        }
    return out


def print_block(
    signal_def: str, def_desc: str, summary: dict, n_events: int,
    horizons: list[int], cooldown: int, maxh: int, index_name: str,
) -> None:
    if n_events == 0:
        print(f"\n=== 定义 {signal_def}（{def_desc}）: 0 事件（检查阈值/参数）===")
        return
    print(f"\n=== 定义 {signal_def}（{def_desc}）· {index_name} · 事件数={n_events} · "
          f"cooldown={cooldown} · mdd/max_gain 窗口={maxh}日 ===")
    print(f"{'指标':>18}" + "".join(f"{k}日".rjust(13) for k in horizons))
    rows = [
        ("事件均值", [summary[k]["mean"] for k in horizons], "{:+.2%}"),
        ("事件中位数", [summary[k]["median"] for k in horizons], "{:+.2%}"),
        ("下跌占比", [summary[k]["neg_pct"] for k in horizons], "{:.1%}"),
        ("基线均值", [summary[k]["baseline_mean"] for k in horizons], "{:+.2%}"),
        ("差值(事件-基线)", [summary[k]["diff"] for k in horizons], "{:+.2%}"),
        ("CI下界2.5%", [summary[k]["ci_lo"] for k in horizons], "{:+.2%}"),
        ("CI上界97.5%", [summary[k]["ci_hi"] for k in horizons], "{:+.2%}"),
    ]
    for name, vals, fmt in rows:
        line = f"{name:>18}" + "".join(fmt.format(v).rjust(13) for v in vals)
        print(line)
    line = f"{'结论':>18}"
    for k in horizons:
        d = summary[k]
        tag = "跑输★" if d["ci_hi"] < 0 else ("跑赢★" if d["ci_lo"] > 0 else "不显著")
        line += tag.rjust(13)
    print(line)


def print_zigzag_gaps(
    events_A: list[int], events_B: list[int], events_C: list[int],
    zz_highs: list[tuple[int, float]],
    dates: list, closes: list, turnovers: list, def_descs: dict, n: int,
    max_look: int = 250,
) -> None:
    """每个天量事件 → 最近的「后续」上证阶段高点，与「随机交易日」基线对比。"""
    high_idxs = sorted(idx for idx, _ in zz_highs)
    base_gaps = []
    for i in range(n):
        j = bisect.bisect_left(high_idxs, i)
        if j < len(high_idxs):
            base_gaps.append(high_idxs[j] - i)
    base_med = sorted(base_gaps)[len(base_gaps) // 2] if base_gaps else None

    print(f"\n=== 天量事件 → 最近的后续上证阶段高点（间隔 ≤ {max_look} 交易日）===")
    print(f"基线：随机交易日 → 下一高点间隔中位数 = {base_med} 交易日（{len(high_idxs)} 个高点）；"
          f"事件间隔显著短于基线则「天量领先高点」成立")
    for signal_def, events in (("A", events_A), ("B", events_B), ("C", events_C)):
        gaps: list[int] = []
        rows = []
        for ep in events:
            j = bisect.bisect_left(high_idxs, ep)
            nxt = high_idxs[j] if j < len(high_idxs) else None
            if nxt is not None and (nxt - ep) <= max_look:
                gaps.append(nxt - ep)
                rows.append((dates[ep], turnovers[ep] / 1e8, dates[nxt], closes[nxt], nxt - ep))
            else:
                rows.append((dates[ep], turnovers[ep] / 1e8, None, None, None))
        print(f"\n-- 定义 {signal_def}（{def_descs[signal_def]}），{len(events)} 事件 --")
        print(f"{'事件日':<12}{'成交额(亿)':>12}{'后续高点':>13}{'高点指数':>10}{'间隔(交易日)':>14}")
        for ev_dt, to_yi, hi_dt, hi_px, gap in rows:
            hi_dt_s = str(hi_dt)[:10] if hi_dt else "—"
            hi_px_s = f"{hi_px:>10.0f}" if hi_px else f"{'—':>10}"
            gap_s = f"{gap:>14d}" if gap is not None else f"{'无(>250日)':>14}"
            print(f"{str(ev_dt):<12}{to_yi:>12.0f}{hi_dt_s:>13}{hi_px_s}{gap_s}")
        if gaps:
            gaps_sorted = sorted(gaps)
            med = gaps_sorted[len(gaps_sorted) // 2]
            within_20 = sum(1 for g in gaps if g <= 20)
            within_60 = sum(1 for g in gaps if g <= 60)
            ratio = f"{base_med / med:.1f}×" if med and base_med else "—"
            print(f"  事件间隔中位数 {med} vs 基线 {base_med} 交易日（事件快 {ratio}）；"
                  f"≤20日 {within_20}/{len(gaps)}，≤60日 {within_60}/{len(gaps)}")


def plot_figure(
    df: pl.DataFrame,
    events_A: list[int],
    events_B: list[int],
    events_C: list[int],
    summary_A: dict,
    summary_B: dict,
    summary_C: dict,
    horizons: list[int],
    output: Path,
    start_date: date,
    def_descs: dict,
    zz_pivots: list[tuple[int, float, str]],
    zigzag_pct: float,
    zz_to_highs: list[tuple[int, float]],
    zz_turnover_pct: float,
    index_name: str,
) -> None:
    plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "WenQuanYi Zen Hei"]
    plt.rcParams["axes.unicode_minus"] = False

    dates = df["date"].to_list()
    turnovers = df["turnover"].to_list()
    closes = df["close"].to_list()

    set_A, set_B, set_C = set(events_A), set(events_B), set(events_C)
    all_three = set_A & set_B & set_C
    ab_only = (set_A & set_B) - all_three
    ac_only = (set_A & set_C) - all_three
    bc_only = (set_B & set_C) - all_three
    only_A = set_A - set_B - set_C
    only_B = set_B - set_A - set_C
    only_C = set_C - set_A - set_B

    fig = plt.figure(figsize=(15, 10))
    gs = fig.add_gridspec(2, 1, height_ratios=[1.3, 1], hspace=0.32)
    ax_top = fig.add_subplot(gs[0])

    ax_top.plot(dates, turnovers, color="#1f77b4", lw=0.6, label=f"{index_name}成交额")
    ax_top.set_yscale("log")
    ax_top.set_ylabel("成交额（元，log）", color="#1f77b4", fontsize=9)
    ax_top.tick_params(axis="y", labelcolor="#1f77b4")

    ax_r = ax_top.twinx()
    ax_r.plot(dates, closes, color="#888", lw=0.5, alpha=0.6, label=f"{index_name}收盘")
    ax_r.set_ylabel(f"{index_name}收盘", color="#888", fontsize=9)
    ax_r.tick_params(axis="y", labelcolor="#888")

    if zz_pivots:
        pv_dates = [dates[p[0]] for p in zz_pivots]
        pv_prices = [p[1] for p in zz_pivots]
        ax_r.plot(pv_dates, pv_prices, "-", color="#2ca02c", lw=1.0, alpha=0.75,
                  zorder=4, label=f"ZigZag 枢轴（{zigzag_pct:.0%}）")
        h_idx = [p[0] for p in zz_pivots if p[2] == "H"]
        if h_idx:
            ax_r.scatter([dates[i] for i in h_idx], [closes[i] for i in h_idx],
                         marker="D", color="black", s=42, zorder=6,
                         edgecolors="#2ca02c", linewidths=0.8,
                         label=f"{index_name}阶段高点（{len(h_idx)}）")

    def scatter(positions, marker, color, label, size=50, edge="white"):
        if not positions:
            return
        kwargs = dict(marker=marker, color=color, s=size, zorder=5, linewidths=0.4,
                      label=label)
        if edge is not None:
            kwargs["edgecolors"] = edge
        ax_top.scatter(
            [dates[p] for p in positions], [turnovers[p] for p in positions],
            **kwargs,
        )

    # 成交额 zigzag 高拐点：C 的「前一个高点」参考线（小横杠，叠在成交额曲线上）
    if zz_to_highs:
        to_h_idx = [p[0] for p in zz_to_highs if 0 <= p[0] < len(dates)]
        scatter(sorted(set(to_h_idx)), "_", "#17becf",
                f"成交额ZigZag高拐点（阈值{zz_turnover_pct:.0%}，{len(to_h_idx)}）",
                size=90, edge=None)

    scatter(sorted(only_A), "v", "#d62728", f"仅A（{len(only_A)}）")
    scatter(sorted(only_B), "^", "#ff7f0e", f"仅B（{len(only_B)}）")
    scatter(sorted(only_C), "s", "#17becf", f"仅C（{len(only_C)}）")
    scatter(sorted(ab_only), "*", "#9467bd", f"A∩B（{len(ab_only)}）")
    scatter(sorted(ac_only), "P", "#e377c2", f"A∩C（{len(ac_only)}）")
    scatter(sorted(bc_only), "X", "#8c564b", f"B∩C（{len(bc_only)}）")
    scatter(sorted(all_three), "*", "black", f"A∩B∩C（{len(all_three)}）", size=80)

    ax_top.set_xlim(dates[0], dates[-1])
    ax_top.set_title(
        f"天量天价事件研究（{index_name}）· {start_date} ~ {dates[-1]}\n"
        f"天量={index_name}成交额（A={def_descs['A']} B={def_descs['B']} C={def_descs['C']}）；"
        f"黑◆=ZigZag {index_name}阶段高点（阈值 {zigzag_pct:.0%}，回溯式）",
        fontsize=12, fontweight="bold",
    )
    ax_top.grid(True, alpha=0.3)
    ax_top.xaxis.set_major_locator(mdates.YearLocator())
    ax_top.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    h1, l1 = ax_top.get_legend_handles_labels()
    h2, l2 = ax_r.get_legend_handles_labels()
    ax_top.legend(h1 + h2, l1 + l2, loc="upper left", fontsize=8)

    # 下面板：事件 vs 基线（A/B/C 各 事件+基线 = 6 根柱/horizon）
    ax_bot = fig.add_subplot(gs[1])
    x = np.arange(len(horizons))
    width = 0.13
    offsets = [-2.5, -1.5, -0.5, 0.5, 1.5, 2.5]
    series = [
        ("A 事件", summary_A, "mean", "#d62728", None, True),
        ("A 基线", summary_A, "baseline_mean", "#d62728", "//", False),
        ("B 事件", summary_B, "mean", "#ff7f0e", None, True),
        ("B 基线", summary_B, "baseline_mean", "#ff7f0e", "//", False),
        ("C 事件", summary_C, "mean", "#17becf", None, True),
        ("C 基线", summary_C, "baseline_mean", "#17becf", "//", False),
    ]
    for j, (name, s, field, color, hatch, is_event) in enumerate(series):
        vals = [(s[k][field] * 100) if s.get(k) else 0.0 for k in horizons]
        ax_bot.bar(x + offsets[j] * width, vals, width, color=color,
                   alpha=0.9 if is_event else 0.45, hatch=hatch, label=name, zorder=3)
        if is_event:
            ev = [(s[k]["mean"] * 100) if s.get(k) else 0.0 for k in horizons]
            lo = [(s[k]["ci_lo"] * 100) if s.get(k) else 0.0 for k in horizons]
            hi = [(s[k]["ci_hi"] * 100) if s.get(k) else 0.0 for k in horizons]
            has_ci = [bool(s.get(k)) for k in horizons]
            ax_bot.errorbar(
                x + offsets[j] * width, ev,
                yerr=[[e - l for e, l in zip(ev, lo)], [h - e for h, e in zip(hi, ev)]],
                fmt="none", ecolor="black", capsize=2.5, lw=0.9, zorder=4)
            for jj, k in enumerate(horizons):
                if not has_ci[jj]:
                    continue
                d = s[k]
                tag = "★" if (d["ci_hi"] < 0 or d["ci_lo"] > 0) else ""
                ax_bot.text(x[jj] + offsets[j] * width, ev[jj], tag,
                            ha="center", va="bottom", fontsize=10, fontweight="bold")

    ax_bot.axhline(0, color="black", lw=0.6)
    ax_bot.set_xticks(x)
    ax_bot.set_xticklabels([f"{k}日" for k in horizons])
    ax_bot.set_ylabel("前向收益 (%)")
    ax_bot.set_title(f"{index_name}：事件 vs 基线均值（★=bootstrap CI 排除 0）", fontsize=10)
    ax_bot.grid(True, alpha=0.3, axis="y")
    ax_bot.legend(loc="best", fontsize=8, ncol=4)

    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=120, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"图已保存: {output}")


def write_csv(rows: list[dict], path: Path, horizons: list[int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    fields = (
        ["signal_def", "event_date", "close_at_event",
         "turnover_at_event", "turnover_vs_ma"]
        + [f"fwd_ret_{k}" for k in horizons]
        + ["mdd", "max_gain"]
    )
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"事件明细 CSV: {path}（{len(rows)} 行）")


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--index-dir", type=Path,
                   default=Path("/mnt/dataset/index_quote_history"))
    p.add_argument("--code", default="000001",
                   help="指数代码（000001=上证综指，000300=沪深300，000905=中证500）")
    p.add_argument("--start-date", type=str, default="2010-01-01")
    p.add_argument("--cooldown", type=int, default=60,
                   help="事件间最小间隔（交易日，=最大 horizon 时前向窗口不重叠）")
    p.add_argument("--roll-high", type=int, default=250, help="定义 A 滚动新高窗口")
    p.add_argument("--ma", type=int, default=60, help="定义 B 均线窗口")
    p.add_argument("--mult", type=float, default=2.0, help="定义 B 倍数阈值")
    p.add_argument("--horizons", type=str, default="5,20,60")
    p.add_argument("--zigzag", type=float, default=0.08,
                   help="ZigZag 反转阈值（上证阶段高/低点检测，如 0.08=8%%）")
    p.add_argument("--zz-turnover", type=float, default=0.30,
                   help="定义 C：成交额 ZigZag 反转阈值（如 0.30=30%%，比价格阈值大因成交额更波动）")
    p.add_argument("--retol", type=float, default=0.20,
                   help="定义 C：re-test 容忍度（后一个成交额高点 / 前一个 - 1 的绝对值 ≤ 此值即算 re-test）")
    p.add_argument("--output", type=Path, default=None)
    p.add_argument("--csv-out", type=Path, default=None)
    args = p.parse_args()

    horizons = [int(x) for x in args.horizons.split(",")]
    maxh = max(horizons)
    start = date.fromisoformat(args.start_date)
    def_descs = {
        "A": f"{args.roll_high}日新高",
        "B": f"≥{args.mult}×MA{args.ma}",
        "C": f"天量re-test(±{args.retol:.0%})",
    }

    df_full = load_index(args.index_dir, args.code)
    df_full = build_signals(df_full, args.roll_high, args.ma, args.mult)

    df = df_full.filter(pl.col("date") >= start)
    n = df.height
    if n == 0:
        raise SystemExit(f"--start-date {start} 后无数据")

    dates = df["date"].to_list()
    closes = df["close"].to_list()
    turnovers = df["turnover"].to_list()
    to_vs_ma = df["turnover_vs_ma"].to_list()
    highs = df["high"].to_list()
    lows = df["low"].to_list()

    flags_A = [bool(x) if x is not None else False for x in df["spike_A"].to_list()]
    flags_B = [bool(x) if x is not None else False for x in df["spike_B"].to_list()]
    events_A = apply_cooldown(flags_A, args.cooldown)
    events_B = apply_cooldown(flags_B, args.cooldown)

    # 定义 C：成交额 ZigZag H pivots 中的 re-test（后一个高点接近前一个）。
    # 在完整历史上算 turnover zigzag —— 否则 2010 年的第一个「前高」会丢掉 2006-2009 的峰值。
    # 成交额列在 1990 年代早期有少量 null（7 行），前向填充后 zigzag 才能跑。
    # 个别指数（如中证500）早期所有值为 null，需要 backward_fill 兜底。
    turnovers_full = (df_full.with_columns(
        pl.col("turnover").forward_fill().backward_fill()
    )["turnover"].to_list())
    zz_to_full = zigzag_pivots(turnovers_full, turnovers_full, args.zz_turnover)
    zz_to_highs_full = [(i, v) for i, v, t in zz_to_full if t == "H"]
    # re-test 检测：后一个高点 / 前一个 - 1 的绝对值 ≤ retol。k=0 的首个高点无前驱，跳过。
    retest_full_idxs = []
    for k in range(1, len(zz_to_highs_full)):
        idx_k, val_k = zz_to_highs_full[k]
        _, val_prev = zz_to_highs_full[k - 1]
        if val_prev > 0 and abs(val_k / val_prev - 1) <= args.retol:
            retest_full_idxs.append(idx_k)
    # 把完整历史的位置映射到过滤后 df 的位置（df = df_full[date >= start]）
    offset = df_full.filter(pl.col("date") < start).height
    flags_C = [False] * n
    for pos_full in retest_full_idxs:
        pos = pos_full - offset
        if 0 <= pos < n:
            flags_C[pos] = True
    events_C = apply_cooldown(flags_C, args.cooldown)

    print(f"区间: {dates[0]} ~ {dates[-1]}（{n} 个交易日）")
    print(f"定义 A（{def_descs['A']}）原始触发 {sum(flags_A)} 次，冷却去重后 {len(events_A)} 事件")
    print(f"定义 B（{def_descs['B']}）原始触发 {sum(flags_B)} 次，冷却去重后 {len(events_B)} 事件")
    print(f"定义 C（{def_descs['C']}）：成交额 ZigZag(±{args.zz_turnover:.0%}) "
          f"共 {len(zz_to_highs_full)} 个高拐点，re-test 触发 {sum(flags_C)} 次，"
          f"冷却去重后 {len(events_C)} 事件")
    print(f"两定义同日（去重后）A∩B={len(set(events_A) & set(events_B))}，"
          f"A∩C={len(set(events_A) & set(events_C))}，B∩C={len(set(events_B) & set(events_C))}")

    zz_pivots = zigzag_pivots(highs, lows, args.zigzag)
    zz_highs = [(p[0], p[1]) for p in zz_pivots if p[2] == "H"]
    zz_lows = [(p[0], p[1]) for p in zz_pivots if p[2] == "L"]
    print(f"\nZigZag（阈值 {args.zigzag:.0%}）：上证综指 {len(zz_highs)} 个阶段高点，"
          f"{len(zz_lows)} 个阶段低点（注：最近未确认的极值不计）")

    rows_A = compute_event_rows(
        events_A, dates, closes, turnovers, to_vs_ma, horizons, n, "A")
    rows_B = compute_event_rows(
        events_B, dates, closes, turnovers, to_vs_ma, horizons, n, "B")
    rows_C = compute_event_rows(
        events_C, dates, closes, turnovers, to_vs_ma, horizons, n, "C")

    # 基线 = 全部交易日（无条件）。标准事件研究基线；事件占比极小（~14/4000），
    # 含事件日本身不影响均值。不剔除事件窗口——那样会移除「天量后续上涨」段，反向压低基线。
    df_base = df.with_columns(
        *[(pl.col("close").shift(-k) / pl.col("close") - 1).alias(f"fwd_{k}") for k in horizons],
    )
    baseline_means: dict = {}
    for k in horizons:
        col = df_base.filter(pl.col(f"fwd_{k}").is_not_null())[f"fwd_{k}"]
        baseline_means[k] = float(col.mean())

    summary_A = summarize(rows_A, baseline_means, horizons)
    summary_B = summarize(rows_B, baseline_means, horizons)
    summary_C = summarize(rows_C, baseline_means, horizons)

    print("\n基线（全部交易日，无条件）前向收益均值：")
    for k in horizons:
        print(f"  {k}日: {baseline_means[k]:+.2%}")

    index_names = {"000001": "上证综指", "000300": "沪深300", "000905": "中证500"}
    index_name = index_names.get(args.code, args.code)
    print_block("A", def_descs["A"], summary_A, len(events_A), horizons, args.cooldown, maxh, index_name)
    print_block("B", def_descs["B"], summary_B, len(events_B), horizons, args.cooldown, maxh, index_name)
    print_block("C", def_descs["C"], summary_C, len(events_C), horizons, args.cooldown, maxh, index_name)

    print_zigzag_gaps(events_A, events_B, events_C, zz_highs, dates, closes, turnovers,
                      def_descs, n)

    output = args.output or Path(f"/mnt/dataset/turnover_spike_vs_index_top_{args.code}.png")
    # 过滤后的成交额 zigzag 高拐点（供上面板标记 C 的「前一个高点」参考）
    zz_to_highs_plot = [(i - offset, v) for i, v in zz_to_highs_full if i - offset >= 0]
    plot_figure(df, events_A, events_B, events_C,
                summary_A, summary_B, summary_C, horizons, output, start,
                def_descs, zz_pivots, args.zigzag, zz_to_highs_plot, args.zz_turnover,
                index_name)

    csv_out = args.csv_out or Path(f"/mnt/dataset/turnover_spike_events_{args.code}.csv")
    write_csv(rows_A + rows_B + rows_C, csv_out, horizons)


if __name__ == "__main__":
    main()
