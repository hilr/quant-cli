"""回撤均值回归策略回测（探索版）。

回撤口径（注意与 fund_drawdown.py 不同）：
  - 策略用收盘价口径：dd = close / rolling_max(close, window) - 1
  - 这样 dd = 0 即「创滚动新高」，出场信号自然成立；fund_drawdown.py 的
    「最低价 / cummax(最高价)」是可视化用的最坏情形口径，不适合做出场触发。

信号（T-1 决定 T 持仓，避免未来函数）：
  - 入场/加仓：dd <= -10% 持 1/3，<= -15% 持 2/3，<= -20% 满仓；只加不减
  - 出场：BIAS120 = close/MA120 - 1 >= 阈值（默认 +10%，约 512890 的 95 分位）
    → 超买止盈清仓，等待下一次回撤重新建仓

纯数学模拟，无交易成本/滑点。
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import polars as pl


def parse_thresholds(s: str) -> list[float]:
    return sorted(float(x) for x in s.split(","))


def run_backtest(
    df: pl.DataFrame, window: int, thresholds: list[float],
    ma_window: int, bias_exit: float,
) -> tuple[pl.DataFrame, list, list]:
    n_tr = len(thresholds)
    df = (
        df.sort("date")
        .with_columns(
            pl.col("close").rolling_max(window_size=window, min_samples=window).alias("roll_high"),
            pl.col("close").rolling_mean(ma_window).alias("ma"),
        )
        .with_columns(
            (pl.col("close") / pl.col("roll_high") - 1.0).alias("dd"),
            (pl.col("close") / pl.col("ma") - 1.0).alias("bias"),
        )
    )
    dates = df["date"].to_list()
    closes = df["close"].to_list()
    dd = df["dd"].to_list()
    bias = df["bias"].to_list()
    n = df.height

    pos = [0.0] * n
    entries: list[tuple] = []   # (date, price, frac_after)
    exits: list[tuple] = []     # (date, price, frac_before)
    held = 0
    for t in range(1, n):
        dd_prev = dd[t - 1]
        bias_prev = bias[t - 1]
        if dd_prev is None or bias_prev is None:
            pos[t] = 0.0
            continue
        # 出场：BIAS 超买止盈（T-1 信号）
        if held > 0 and bias_prev >= bias_exit:
            exits.append((dates[t], closes[t], held / n_tr))
            held = 0
        else:
            # 入场/加仓：回撤分档（T-1 信号）
            target = sum(1 for th in thresholds if dd_prev <= th)
            if target > held:
                entries.append((dates[t], closes[t], target / n_tr))
                held = target
        pos[t] = held / n_tr

    nav = [1.0] * n
    bh = [1.0] * n
    for t in range(1, n):
        r = closes[t] / closes[t - 1] - 1.0
        nav[t] = nav[t - 1] * (1.0 + pos[t] * r)
        bh[t] = bh[t - 1] * (1.0 + r)

    out = df.with_columns(
        pl.Series("position", pos),
        pl.Series("strategy_nav", nav),
        pl.Series("bnh_nav", bh),
    )
    return out, entries, exits


def _stats(nav_series: list[float], dates: list, pos_series: list[float]) -> dict:
    n = len(nav_series)
    n_years = (dates[-1] - dates[0]).days / 365.25
    total = nav_series[-1] / nav_series[0] - 1
    cagr = (nav_series[-1] / nav_series[0]) ** (1 / n_years) - 1 if n_years > 0 else 0
    daily = [
        nav_series[t] / nav_series[t - 1] - 1 for t in range(1, n) if nav_series[t - 1]
    ]
    mean_d = sum(daily) / len(daily) if daily else 0
    var = sum((x - mean_d) ** 2 for x in daily) / (len(daily) - 1) if len(daily) > 1 else 0
    vol = var ** 0.5 * (252 ** 0.5)
    sharpe = (mean_d * 252) / vol if vol > 0 else 0
    peak = nav_series[0]
    max_dd = 0.0
    for v in nav_series:
        peak = max(peak, v)
        max_dd = min(max_dd, v / peak - 1)
    time_in = sum(1 for p in pos_series if p > 0) / n
    return {
        "total_return": total, "cagr": cagr, "annual_vol": vol,
        "sharpe": sharpe, "max_drawdown": max_dd,
        "n_days": n, "time_in_market": time_in,
    }


def plot(out: pl.DataFrame, entries, exits, code, params, output_png, output_csv) -> None:
    dates_all = out["date"].to_list()
    strat_all = out["strategy_nav"].to_list()
    bnh_all = out["bnh_nav"].to_list()
    dd_all = out["dd"].to_list()
    bias_all = out["bias"].to_list()
    pos_all = out["position"].to_list()

    # slice from first valid drawdown (strategy is flat before window warmup)
    first = next(i for i, v in enumerate(dd_all) if v is not None)
    dates = dates_all[first:]
    strat = [strat_all[i] / strat_all[first] for i in range(first, len(strat_all))]
    bnh = [bnh_all[i] / bnh_all[first] for i in range(first, len(bnh_all))]
    dd = [dd_all[i] * 100 for i in range(first, len(dd_all))]
    bias = [bias_all[i] * 100 for i in range(first, len(bias_all))]
    pos = pos_all[first:]
    nav_by_date = dict(zip(dates, strat))

    s_strat = _stats(strat, dates, pos)
    s_bnh = _stats(bnh, dates, [1.0] * len(bnh))

    fig, (ax_nav, ax_dd) = plt.subplots(
        2, 1, figsize=(15, 8), sharex=True,
        gridspec_kw={"height_ratios": [2, 1]},
    )

    ax_nav.semilogy(dates, bnh, "-", color="#1f77b4", linewidth=0.9, alpha=0.8,
                    label=f"{code} Buy&Hold")
    ax_nav.semilogy(dates, strat, "-", color="black", linewidth=1.2,
                    label="DD-reversion Strategy")

    ent_dates = [e[0] for e in entries]
    ax_nav.scatter([d for d in ent_dates if d in nav_by_date],
                   [nav_by_date[d] for d in ent_dates if d in nav_by_date],
                   marker="^", color="green", s=22, zorder=5, label="entry / add")
    ex_dates = [d for d, *_ in exits if d in nav_by_date]
    ax_nav.scatter(ex_dates, [nav_by_date[d] for d in ex_dates],
                   marker="v", color="red", s=22, zorder=5,
                   label=f"exit (BIAS{params['ma_window']}>={params['bias_exit']*100:.0f}%)")

    ax_nav.set_ylabel("NAV (log)")
    ax_nav.legend(loc="upper left", fontsize=9)
    ax_nav.grid(True, alpha=0.3, which="both")

    # 下栏：回撤（红，入场语境）+ BIAS（蓝，出场信号）+ 出场阈值线
    ax_dd.fill_between(dates, dd, 0, color="#d62728", alpha=0.25)
    ax_dd.plot(dates, dd, "-", color="#d62728", linewidth=0.5, alpha=0.7)
    ax_dd.plot(dates, bias, "-", color="#1f77b4", linewidth=0.7, label=f"BIAS{params['ma_window']}")
    ax_dd.axhline(params["bias_exit"] * 100, color="orange", linestyle="--",
                  linewidth=0.8, alpha=0.8, label=f"exit {params['bias_exit']*100:.0f}%")
    for th in params["thresholds"]:
        ax_dd.axhline(th * 100, color="green", linestyle=":", linewidth=0.4, alpha=0.4)
    ax_dd.axhline(0, color="black", linewidth=0.5)
    ax_dd.set_ylabel("DD % / BIAS %")
    ax_dd.set_xlabel("Date")
    ax_dd.legend(loc="lower left", fontsize=8)
    ax_dd.grid(True, alpha=0.3)
    ax_dd.xaxis.set_major_locator(mdates.YearLocator())
    ax_dd.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    fig.suptitle(
        f"{code} DD-reversion: entry=DD ladder {params['thresholds']} (window {params['window']}d), "
        f"exit=BIAS{params['ma_window']}>={params['bias_exit']*100:.0f}%\n"
        f"Strategy total {s_strat['total_return']*100:+.1f}% (CAGR {s_strat['cagr']*100:+.1f}%, "
        f"maxDD {s_strat['max_drawdown']*100:.1f}%)  vs  "
        f"B&H {s_bnh['total_return']*100:+.1f}% (maxDD {s_bnh['max_drawdown']*100:.1f}%)",
        fontsize=11,
    )
    plt.tight_layout(rect=[0, 0, 1, 0.95])
    output_png.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_png, dpi=120, bbox_inches="tight")
    plt.close(fig)

    if output_csv:
        out.write_csv(output_csv)

    # print stats
    print(f"Saved to {output_png}")
    print(f"\n{code}  period {dates[0]} ~ {dates[-1]}  ({s_strat['n_days']} days)")
    print(f"{'metric':<18}{'Strategy':>14}{'Buy&Hold':>14}")
    for k in ("total_return", "cagr", "annual_vol", "sharpe", "max_drawdown", "time_in_market"):
        sv = s_strat[k]
        bv = s_bnh.get(k)
        sv_s = f"{sv*100:+.2f}%" if k != "time_in_market" else f"{sv*100:.1f}%"
        bv_s = f"{bv*100:+.2f}%" if (bv is not None and k != "time_in_market") else (f"{bv*100:.1f}%" if bv is not None else "—")
        print(f"{k:<18}{sv_s:>14}{bv_s:>14}")
    print(f"\nrounds: {len(exits)} exits (+{1 if pos[-1] > 0 else 0} open at end), {len(entries)} ladder adds")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--code", default="512890")
    p.add_argument("--adjusted-dir", type=Path,
                   default=Path("/mnt/dataset/fund_quote_adjusted"))
    p.add_argument("--window", type=int, default=250, help="滚动高点窗口（交易日）")
    p.add_argument("--thresholds", type=parse_thresholds,
                   default=[-0.10, -0.15, -0.20],
                   help="分档建仓阈值，逗号分隔，如 -0.10,-0.15,-0.20")
    p.add_argument("--ma-window", type=int, default=120, help="BIAS 均线窗口（交易日）")
    p.add_argument("--bias-exit", type=float, default=0.10,
                   help="BIAS 超买止盈阈值（512890 约 95 分位）；如 0.10=+10%")
    p.add_argument("--output", type=Path, default=None)
    p.add_argument("--output-csv", type=Path, default=None)
    args = p.parse_args()

    output = args.output or Path(f"/mnt/dataset/dd_reversion_backtest_{args.code}.png")
    df = (
        pl.read_parquet(args.adjusted_dir / f"{args.code}.parquet")
        .with_columns(pl.col("date").str.to_date("%Y-%m-%d"))
        .sort("date")
    )
    out, entries, exits = run_backtest(
        df, args.window, args.thresholds, args.ma_window, args.bias_exit
    )
    plot(out, entries, exits, args.code,
         {"window": args.window, "thresholds": args.thresholds,
          "ma_window": args.ma_window, "bias_exit": args.bias_exit},
         output, args.output_csv)


if __name__ == "__main__":
    main()
