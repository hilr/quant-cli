"""融资净买入异常值择时策略 + 网格搜索。

逻辑：当某日全市场融资净流入为正，且超过过去 N 日均值 + k 倍标准差时，买入
标的指数；当净流入为负且低于均值 - k 倍标准差时，卖出平仓。持有到反向信号。

两个参数（窗口 N、倍数 k）做网格搜索，以年化夏普比率找最优；交易标的通过
--index-file 切换（默认沪深300）。

数据源：
  融资余额：/mnt/dataset/margin_trade_history/{code}.parquet（个股，按日聚合求和）
  日净流入 = balance[t] - balance[t-1]
  指数行情：--index-file（默认 000300 沪深300）

避免前视：融资数据盘后公布，信号 T 日收盘后可得、T+1 日生效。
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import polars as pl
from matplotlib import gridspec


def load_margin_balance(data_path: Path) -> pl.DataFrame:
    """读所有个股融资余额 parquet，按日汇总求和."""
    dfs = [
        pl.read_parquet(pf, columns=["date", "margin_buy_total"])
        for pf in sorted(data_path.glob("*.parquet"))
    ]
    combined = (
        pl.concat(dfs)
        .with_columns(pl.col("date").str.to_date("%Y-%m-%d").alias("d"))
        .group_by("d").agg(pl.col("margin_buy_total").sum().alias("balance"))
        .sort("d")
    )
    return combined.rename({"d": "date"})


def run_backtest(
    merged: pl.DataFrame, window: int, k: float, cost: float
) -> tuple[dict, pl.DataFrame]:
    """单次回测。返回 (指标 dict, 带仓位的完整 df)."""
    df = (
        merged
        .with_columns((pl.col("balance") - pl.col("balance").shift(1)).alias("inflow"))
        .with_columns(
            pl.col("inflow").rolling_mean(window).shift(1).alias("mu"),
            pl.col("inflow").rolling_std(window).shift(1).alias("sigma"),
        )
        .with_columns(
            ((pl.col("inflow") > 0)
             & (pl.col("inflow") > pl.col("mu") + k * pl.col("sigma"))).alias("buy_sig"),
            ((pl.col("inflow") < 0)
             & (pl.col("inflow") < pl.col("mu") - k * pl.col("sigma"))).alias("sell_sig"),
        )
        # 信号 T 日可得 → T+1 生效
        .with_columns(
            pl.col("buy_sig").shift(1).alias("buy_s"),
            pl.col("sell_sig").shift(1).alias("sell_s"),
        )
        .with_columns(
            pl.when(pl.col("buy_s")).then(1.0)
            .when(pl.col("sell_s")).then(0.0)
            .otherwise(None).alias("raw_pos")
        )
        # 持有到反向信号：forward_fill 上一个 buy/sell 决策
        .with_columns(
            pl.col("raw_pos").fill_null(strategy="forward").fill_null(0.0).alias("position")
        )
        .with_columns((pl.col("close") / pl.col("close").shift(1) - 1).alias("index_ret"))
        .with_columns(
            (pl.col("position") * pl.col("index_ret")
             - cost * (pl.col("position") - pl.col("position").shift(1)).abs()
            ).alias("strat_ret")
        )
    )

    valid = df.filter(pl.col("strat_ret").is_not_null())
    rets = valid["strat_ret"].to_numpy()
    idx_rets = valid["index_ret"].to_numpy()
    std = rets.std()
    sharpe = float(rets.mean() / std * np.sqrt(252)) if std > 0 else 0.0
    nav = np.cumprod(1 + rets)
    bnh = np.cumprod(1 + idx_rets)
    running_max = np.maximum.accumulate(nav)
    max_dd = float((nav / running_max - 1).min())
    n_trades = valid.filter(
        (pl.col("position").shift(1) == 0) & (pl.col("position") == 1)
    ).height

    metrics = {
        "window": window,
        "k": k,
        "sharpe": sharpe,
        "total_return": float(nav[-1] - 1),
        "bnh_return": float(bnh[-1] - 1),
        "max_dd": max_dd,
        "n_trades": n_trades,
    }
    return metrics, df


def grid_search(
    merged: pl.DataFrame, windows: list[int], k_values: list[float], cost: float
) -> tuple[pl.DataFrame, dict, pl.DataFrame]:
    """网格搜索。返回 (结果 df, 最优 metrics, 最优 df)."""
    rows = []
    best_metrics = None
    best_df = None
    for w in windows:
        for k in k_values:
            m, d = run_backtest(merged, w, k, cost)
            rows.append(m)
            if best_metrics is None or m["sharpe"] > best_metrics["sharpe"]:
                best_metrics = m
                best_df = d
    return pl.DataFrame(rows), best_metrics, best_df


def plot(
    results: pl.DataFrame,
    best: dict,
    best_df: pl.DataFrame,
    index_name: str,
    output: Path,
) -> None:
    plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "WenQuanYi Zen Hei"]
    plt.rcParams["axes.unicode_minus"] = False

    fig = plt.figure(figsize=(15, 12))
    gs = gridspec.GridSpec(3, 1, height_ratios=[2.2, 1, 1.3], hspace=0.32)

    # ---- 顶部：NAV ----
    ax_nav = fig.add_subplot(gs[0])
    valid = best_df.filter(pl.col("strat_ret").is_not_null())
    dates = valid["date"].to_numpy()
    nav = np.cumprod(1 + valid["strat_ret"].to_numpy())
    bnh = np.cumprod(1 + valid["index_ret"].to_numpy())
    ax_nav.plot(dates, nav, color="#1f77b4", lw=0.7,
                label=f"策略 (N={best['window']}, k={best['k']})")
    ax_nav.plot(dates, bnh, color="gray", lw=0.7, label="买入持有")

    # 标记进出场（基于次日生效的仓位变化）
    pos = valid["position"].to_numpy()
    entries = np.where((pos[1:] == 1) & (pos[:-1] == 0))[0] + 1
    exits = np.where((pos[1:] == 0) & (pos[:-1] == 1))[0] + 1
    ax_nav.scatter(dates[entries], nav[entries], marker="^", color="green",
                   s=28, zorder=5, label=f"买入 ({len(entries)})")
    ax_nav.scatter(dates[exits], nav[exits], marker="v", color="red",
                   s=28, zorder=5, label=f"卖出 ({len(exits)})")
    ax_nav.set_ylabel("NAV (起点=1)")
    ax_nav.set_title(
        f"融资净买入异常值择时 — {index_name}  "
        f"最优 N={best['window']}, k={best['k']}  "
        f"夏普={best['sharpe']:.2f}  收益={best['total_return']*100:+.1f}%  "
        f"最大回撤={best['max_dd']*100:.1f}%  交易={best['n_trades']}次"
    )
    ax_nav.legend(loc="upper left", fontsize=9, ncol=5)
    ax_nav.grid(True, alpha=0.3)

    # ---- 中部：净流入 + 信号 ----
    ax_flow = fig.add_subplot(gs[1], sharex=ax_nav)
    flow_dates = best_df["date"].to_numpy()
    flow_vals = best_df["inflow"].to_numpy()
    colors = ["#d62728" if x < 0 else "#1f77b4" for x in flow_vals]
    ax_flow.bar(flow_dates, flow_vals, width=0.9, color=colors, alpha=0.5)
    buy_dates = best_df.filter(pl.col("buy_sig") == True)["date"].to_numpy()
    buy_vals = best_df.filter(pl.col("buy_sig") == True)["inflow"].to_numpy()
    sell_dates = best_df.filter(pl.col("sell_sig") == True)["date"].to_numpy()
    sell_vals = best_df.filter(pl.col("sell_sig") == True)["inflow"].to_numpy()
    ax_flow.scatter(buy_dates, buy_vals, marker="^", color="green", s=20, zorder=5)
    ax_flow.scatter(sell_dates, sell_vals, marker="v", color="red", s=20, zorder=5)
    ax_flow.axhline(0, color="black", lw=0.5)
    ax_flow.set_ylabel("融资净流入 (元)")
    ax_flow.grid(True, alpha=0.3)
    ax_flow.xaxis.set_major_locator(mdates.YearLocator())
    ax_flow.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    # ---- 底部：夏普热力图 ----
    ax_hm = fig.add_subplot(gs[2])
    pivot = results.pivot(on="k", index="window", values="sharpe").sort("window")
    windows_sorted = pivot["window"].to_list()
    k_cols = [c for c in pivot.columns if c != "window"]
    k_vals_sorted = [float(c) for c in k_cols]
    matrix = pivot.select(k_cols).to_numpy()
    im = ax_hm.imshow(matrix, aspect="auto", cmap="RdYlGn")
    ax_hm.set_xticks(range(len(k_vals_sorted)))
    ax_hm.set_xticklabels([f"{v:.1f}" for v in k_vals_sorted])
    ax_hm.set_yticks(range(len(windows_sorted)))
    ax_hm.set_yticklabels(windows_sorted)
    ax_hm.set_xlabel("k (标准差倍数)")
    ax_hm.set_ylabel("N (回看窗口)")
    # 标注数值 + 高亮最优
    best_w, best_k = best["window"], best["k"]
    for i, w in enumerate(windows_sorted):
        for j, kv in enumerate(k_vals_sorted):
            val = matrix[i, j]
            ax_hm.text(j, i, f"{val:.1f}", ha="center", va="center", fontsize=8,
                       color="black" if abs(val) < 1.0 else "white")
            if w == best_w and abs(kv - best_k) < 1e-9:
                ax_hm.add_patch(plt.Rectangle((j - 0.5, i - 0.5), 1, 1,
                                              fill=False, edgecolor="black", lw=2.5))
    cbar = fig.colorbar(im, ax=ax_hm, fraction=0.025, pad=0.02)
    cbar.set_label("年化夏普比率")
    ax_hm.set_title("网格搜索：年化夏普比率 (N × k)", fontsize=10)

    output.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output, dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved to {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-path", type=Path,
                        default=Path("/mnt/dataset/margin_trade_history"),
                        help="融资融券个股历史目录")
    parser.add_argument("--index-file", type=Path,
                        default=Path("/mnt/dataset/index_quote_history/000300.parquet"),
                        help="标的指数 parquet 文件")
    parser.add_argument("--output", type=Path,
                        default=Path("/mnt/dataset/margin_inflow_outlier_strategy.png"),
                        help="输出 PNG 路径")
    parser.add_argument("--cost-rate", type=float, default=0.0005,
                        help="单边交易成本（默认万分之五）")
    parser.add_argument("--windows", type=str, default="10,15,20,25,30,40,60",
                        help="回看窗口网格（逗号分隔）")
    parser.add_argument("--k-values", type=str, default="1.0,1.5,2.0,2.5,3.0,3.5,4.0",
                        help="标准差倍数网格（逗号分隔）")
    args = parser.parse_args()

    windows = [int(x) for x in args.windows.split(",")]
    k_values = [float(x) for x in args.k_values.split(",")]

    margin = load_margin_balance(args.data_path)
    idx = (pl.read_parquet(args.index_file, columns=["date", "close", "name"])
           .with_columns(pl.col("date").cast(pl.Date)).sort("date"))
    index_name = idx["name"][0]
    merged = (margin.join(idx.select("date", "close"), on="date", how="inner")
              .sort("date"))
    print(f"数据区间: {merged['date'][0]} ~ {merged['date'][-1]}, {merged.height} 行, "
          f"标的={index_name}, 网格={len(windows)}×{len(k_values)}={len(windows)*len(k_values)}")

    results, best, best_df = grid_search(merged, windows, k_values, args.cost_rate)
    plot(results, best, best_df, index_name, args.output)

    print(f"\n=== 最优参数 ===")
    print(f"  N={best['window']}, k={best['k']}")
    print(f"  夏普={best['sharpe']:.3f}  收益={best['total_return']*100:+.1f}%  "
          f"买入持有={best['bnh_return']*100:+.1f}%  最大回撤={best['max_dd']*100:.1f}%  "
          f"交易={best['n_trades']}次")

    print(f"\n=== 网格搜索前 10 名（按夏普）===")
    top = results.sort("sharpe", descending=True).head(10)
    for row in top.iter_rows(named=True):
        print(f"  N={row['window']:>3}, k={row['k']:.1f}  夏普={row['sharpe']:>6.2f}  "
              f"收益={row['total_return']*100:>+7.1f}%  回撤={row['max_dd']*100:>5.1f}%  "
              f"交易={row['n_trades']:>3}次")


if __name__ == "__main__":
    main()
