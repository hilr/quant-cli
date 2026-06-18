"""布林带通道策略回测（上升通道 + 区间震荡 标的）。

通道：center = MA(window)，upper = MA + k·σ，lower = MA − k·σ。
  - 通道随 MA 上行而上升（捕捉趋势斜率），带宽随波动自适应。

架构：买入/卖出分离的 Signal 层（见 quant/signals.py + quant/strategy.run_signal_strategy）
  - 买入 Signal：close ≤ 下轨（tag_boll_lower）；可选叠加 tag_rising_ma（MA 上行过滤）
  - 卖出按 --exit-mode：
      touch     → 卖出 Signal = tag_boll_upper_touch（触及上轨即卖）
      breakdown → 有状态 Stop(kind=breakdown)：先站上上轨、后连续 confirm 日跌回上轨之下
      trail     → 有状态 Stop(kind=trail)：close < 持仓峰值 − m·σ
  - 实际卖出 = sell Signal OR 触及 Stop；买卖不对称、各自可多 tag 组合。
信号 T-1 决定 T 持仓，避免未来函数；binary 进出，纯数学模拟无交易成本。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import polars as pl

# 作为脚本直接跑时，把项目根加入 path 以便 import quant
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def run_backtest(
    df: pl.DataFrame, window: int, k: float, rising_ma: bool,
    exit_mode: str = "breakdown",
    confirm: int = 1, trail_m: float = 3.0,
) -> tuple[pl.DataFrame, list, list]:
    """布林带通道策略：构造 buy/sell Signal + Stop，转交 run_signal_strategy。"""
    from quant.signals import Signal, Stop, TagSpec
    from quant.strategy import run_signal_strategy

    # 挂通道带列（ma/sigma/upper/lower）供绘图与 Stop 复用
    df = (
        df.sort("date")
        .with_columns(
            pl.col("close").rolling_mean(window).alias("ma"),
            pl.col("close").rolling_std(window).alias("sigma"),
        )
        .with_columns(
            (pl.col("ma") + k * pl.col("sigma")).alias("upper"),
            (pl.col("ma") - k * pl.col("sigma")).alias("lower"),
        )
    )

    buy_tags = [TagSpec("boll_lower", {"window": window, "k": k})]
    if rising_ma:
        buy_tags.append(TagSpec("rising_ma", {"window": window}))
    buy = Signal(buy_tags, "all")

    if exit_mode == "touch":
        sell = Signal([TagSpec("boll_upper_touch", {"window": window, "k": k})], "all")
        stop = None
    elif exit_mode == "trail":
        sell = Signal([], "all")
        stop = Stop(kind="trail", m=trail_m, window=window)
    else:  # breakdown
        sell = Signal([], "all")
        stop = Stop(kind="breakdown", window=window, k=k, confirm=confirm)

    out, entries, exits = run_signal_strategy(df, buy, sell, stop)
    out = out.drop([c for c in out.columns if c.startswith("_")])
    return out, entries, exits


def _stats(series: list[float], dates: list) -> dict:
    n = len(series)
    n_years = (dates[-1] - dates[0]).days / 365.25
    total = series[-1] / series[0] - 1
    cagr = (series[-1] / series[0]) ** (1 / n_years) - 1 if n_years > 0 else 0
    daily = [series[t] / series[t - 1] - 1 for t in range(1, n) if series[t - 1]]
    mean_d = sum(daily) / len(daily) if daily else 0
    var = sum((x - mean_d) ** 2 for x in daily) / (len(daily) - 1) if len(daily) > 1 else 0
    vol = var ** 0.5 * (252 ** 0.5)
    sharpe = (mean_d * 252) / vol if vol > 0 else 0
    peak = series[0]
    max_dd = 0.0
    for v in series:
        peak = max(peak, v)
        max_dd = min(max_dd, v / peak - 1)
    return {"total_return": total, "cagr": cagr, "annual_vol": vol,
            "sharpe": sharpe, "max_drawdown": max_dd, "n_days": n}


def plot(out, entries, exits, code, params, output_png, output_csv) -> None:
    dates_all = out["date"].to_list()
    first = next(i for i, v in enumerate(out["ma"].to_list()) if v is not None)
    dates = dates_all[first:]
    strat_all = out["strategy_nav"].to_list()
    bnh_all = out["bnh_nav"].to_list()
    strat = [strat_all[i] / strat_all[first] for i in range(first, len(strat_all))]
    bnh = [bnh_all[i] / bnh_all[first] for i in range(first, len(bnh_all))]
    closes = out["close"].to_list()[first:]
    ma = out["ma"].to_list()[first:]
    upper = out["upper"].to_list()[first:]
    lower = out["lower"].to_list()[first:]
    pos = out["position"].to_list()[first:]
    nav_by_date = dict(zip(dates, strat))

    s_strat = _stats(strat, dates)
    s_bnh = _stats(bnh, dates)
    time_in = sum(1 for p in pos if p > 0) / len(pos)

    fig, (ax_nav, ax_ch) = plt.subplots(
        2, 1, figsize=(15, 8), sharex=True,
        gridspec_kw={"height_ratios": [2, 1]},
    )

    ax_nav.semilogy(dates, bnh, "-", color="#1f77b4", linewidth=0.9, alpha=0.8,
                    label=f"{code} Buy&Hold")
    ax_nav.semilogy(dates, strat, "-", color="black", linewidth=1.3,
                    label="Channel Strategy")
    ent_dates = [e[0] for e in entries if e[0] in nav_by_date]
    ax_nav.scatter(ent_dates, [nav_by_date[d] for d in ent_dates],
                   marker="^", color="green", s=24, zorder=5, label="entry (lower band)")
    ex_dates = [e[0] for e in exits if e[0] in nav_by_date]
    ax_nav.scatter(ex_dates, [nav_by_date[d] for d in ex_dates],
                   marker="v", color="red", s=24, zorder=5, label="exit (upper band)")
    ax_nav.set_ylabel("NAV (log)")
    ax_nav.legend(loc="upper left", fontsize=9)
    ax_nav.grid(True, alpha=0.3, which="both")

    ax_ch.fill_between(dates, lower, upper, color="#1f77b4", alpha=0.08)
    ax_ch.plot(dates, upper, "-", color="#1f77b4", linewidth=0.6, alpha=0.7, label="upper band")
    ax_ch.plot(dates, lower, "-", color="#1f77b4", linewidth=0.6, alpha=0.7, label="lower band")
    ax_ch.plot(dates, ma, "--", color="gray", linewidth=0.6, alpha=0.7, label=f"MA{params['window']}")
    ax_ch.plot(dates, closes, "-", color="black", linewidth=0.7)
    ax_ch.scatter(ent_dates, [e[1] for e in entries if e[0] in nav_by_date],
                  marker="^", color="green", s=24, zorder=5)
    ax_ch.scatter(ex_dates, [e[1] for e in exits if e[0] in nav_by_date],
                  marker="v", color="red", s=24, zorder=5)
    ax_ch.set_ylabel("Price")
    ax_ch.set_xlabel("Date")
    ax_ch.legend(loc="upper left", fontsize=8)
    ax_ch.grid(True, alpha=0.3)
    ax_ch.xaxis.set_major_locator(mdates.YearLocator())
    ax_ch.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    rising = ", rising-MA filter" if params["rising_ma"] else ""
    exit_desc = "sell on close back below upper" if params["exit_mode"] == "breakdown" else "sell on touch upper"
    fig.suptitle(
        f"{code} Bollinger channel: MA{params['window']} ± {params['k']}σ, "
        f"buy@lower, {exit_desc}{rising}\n"
        f"Strategy total {s_strat['total_return']*100:+.1f}% (CAGR {s_strat['cagr']*100:+.1f}%, "
        f"maxDD {s_strat['max_drawdown']*100:.1f}%, in mkt {time_in*100:.0f}%)  vs  "
        f"B&H {s_bnh['total_return']*100:+.1f}% (maxDD {s_bnh['max_drawdown']*100:.1f}%)",
        fontsize=11,
    )
    plt.tight_layout(rect=[0, 0, 1, 0.95])
    output_png.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_png, dpi=120, bbox_inches="tight")
    plt.close(fig)

    if output_csv:
        out.write_csv(output_csv)

    print(f"Saved to {output_png}")
    print(f"\n{code}  period {dates[0]} ~ {dates[-1]}  ({s_strat['n_days']} days)")
    print(f"{'metric':<16}{'Strategy':>14}{'Buy&Hold':>14}")
    print(f"{'total_return':<16}{s_strat['total_return']*100:>13.2f}%{s_bnh['total_return']*100:>13.2f}%")
    print(f"{'cagr':<16}{s_strat['cagr']*100:>13.2f}%{s_bnh['cagr']*100:>13.2f}%")
    print(f"{'annual_vol':<16}{s_strat['annual_vol']*100:>13.2f}%{s_bnh['annual_vol']*100:>13.2f}%")
    print(f"{'sharpe':<16}{s_strat['sharpe']:>14.2f}{s_bnh['sharpe']:>14.2f}")
    print(f"{'max_drawdown':<16}{s_strat['max_drawdown']*100:>13.2f}%{s_bnh['max_drawdown']*100:>13.2f}%")
    print(f"{'time_in_market':<16}{time_in*100:>13.1f}%{100.0:>13.1f}%")
    print(f"\nrounds: {len(exits)} exits (+{1 if pos[-1] > 0 else 0} open at end), {len(entries)} entries")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--code", default="512890")
    p.add_argument("--adjusted-dir", type=Path,
                   default=Path("/mnt/dataset/fund_quote_adjusted"))
    p.add_argument("--window", type=int, default=120, help="通道中心均线窗口")
    p.add_argument("--k", type=float, default=2.0, help="带宽 = k 倍标准差")
    p.add_argument("--rising-ma", action="store_true", help="仅 MA 上行时才按下轨买入")
    p.add_argument("--exit-mode", choices=["breakdown", "touch", "trail"], default="breakdown",
                   help="breakdown=突破上轨后跌回上轨之下才卖（默认）；touch=触及即卖；trail=移动止损")
    p.add_argument("--confirm", type=int, default=1,
                   help="breakdown 确认期：连续 N 日收盘在上轨之下才卖（1=原逻辑）")
    p.add_argument("--trail-m", type=float, default=3.0,
                   help="trail 模式：peak − m×σ 止损")
    p.add_argument("--output", type=Path, default=None)
    p.add_argument("--output-csv", type=Path, default=None)
    args = p.parse_args()

    output = args.output or Path(f"/mnt/dataset/channel_backtest_{args.code}.png")
    df = (
        pl.read_parquet(args.adjusted_dir / f"{args.code}.parquet")
        .with_columns(pl.col("date").str.to_date("%Y-%m-%d"))
        .sort("date")
    )
    out, entries, exits = run_backtest(
        df, args.window, args.k, args.rising_ma, args.exit_mode,
        args.confirm, args.trail_m,
    )
    plot(out, entries, exits, args.code,
         {"window": args.window, "k": args.k, "rising_ma": args.rising_ma,
          "exit_mode": args.exit_mode, "confirm": args.confirm,
          "trail_m": args.trail_m},
         output, args.output_csv)


if __name__ == "__main__":
    main()
