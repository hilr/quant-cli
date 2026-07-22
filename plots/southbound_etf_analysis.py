"""港股通南向资金 vs 恒生科技 ETF(513180) 关系量化分析。

两条分析路径：
  1. 累计净流入 vs ETF 收益相关性
     - 信号: net_20d / net_60d = 当日及前 N-1 日 net_yi 滚动合计(亿港元)
     - 目标: etf_fwd_ret_{1,3,5,20}d = t+horizon 收盘 / t 收盘 - 1
     - 全样本 Pearson corr + 120 日滚动 corr 看稳定性
  2. 当日净流入 60 日分位 vs ETF 短期 forward 收益
     - 信号: q60 = 当日 net_yi 在过去 60 个交易日(不含当日)中的百分位 (0~1)
     - 目标: etf_fwd_ret_3d / 5d
     - 全样本 corr + 按 q60 分 10 桶看 forward 收益均值

数据源：
  /mnt/dataset/exchange_hkex/southbound_flow.csv (net_yi, 亿港元)
  /mnt/dataset/fund_quote_adjusted/513180.parquet (前复权 close)

样本期：2021-05-25 ~ 2026-06-23（南向 + ETF 共同交易日），约 1250 行。
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import polars as pl

# --- 信号 / 收益窗口参数 -----------------------------------------------------
NET_WINDOWS = (20, 60)          # 滚动累计净流入窗口
FWD_HORIZONS = (1, 3, 5, 20)    # ETF forward 收益窗口（交易日）
Q_WINDOW = 60                   # 当日 net_yi 分位回看窗口
ROLL_CORR_WINDOW = 120          # 滚动 corr 窗口
N_BUCKETS = 10                  # 分位分桶数

COLOR_NET20 = "#e6550d"   # 橙
COLOR_NET60 = "#08519c"   # 深蓝
COLOR_Q60 = "#31a354"     # 绿
COLOR_ETF = "#d62728"     # 红


def load_southbound(csv_path: Path) -> pl.DataFrame:
    """读南向资金 CSV，加 rolling 累计 + 60 日分位。"""
    float_cols = {c: pl.Float64 for c in
                  ("sse_buy_yi", "sse_sell_yi", "szse_buy_yi", "szse_sell_yi",
                   "buy_yi", "sell_yi", "net_yi")}
    df = (
        pl.read_csv(csv_path, try_parse_dates=True, schema_overrides=float_cols)
        .sort("date")
        .with_columns(pl.col("net_yi").fill_null(0))
    )
    # 20/60 日累计净流入
    df = df.with_columns([
        pl.col("net_yi").rolling_sum(window_size=w, min_samples=w).alias(f"net_{w}d")
        for w in NET_WINDOWS
    ])
    # 60 日分位（不含当日）
    df = df.with_columns(
        rolling_past_quantile(df["net_yi"], Q_WINDOW).alias("q60")
    )
    return df


def rolling_past_quantile(s: pl.Series, w: int) -> pl.Series:
    """每个 t，net_yi[t] 在 net_yi[t-w .. t-1] 中的百分位 (0~1)。

    不含当日，避免与同日 ETF forward 收益产生信息泄漏。
    """
    arr = s.to_numpy().astype(float)
    n = len(arr)
    out = np.full(n, np.nan)
    for i in range(w, n):
        cur = arr[i]
        window = arr[i - w:i]
        if np.isnan(cur) or np.isnan(window).any():
            continue
        out[i] = np.mean(window <= cur)
    return pl.Series("q60", out)


def load_etf(fund_file: Path) -> pl.DataFrame:
    """读 ETF 前复权 close，加 forward return。"""
    df = (
        pl.read_parquet(fund_file, columns=["date", "close"])
        .with_columns(pl.col("date").str.to_date("%Y-%m-%d"))
        .sort("date")
    )
    return df.with_columns([
        (pl.col("close").shift(-h) / pl.col("close") - 1.0).alias(f"etf_fwd_ret_{h}d")
        for h in FWD_HORIZONS
    ])


def merge(sb: pl.DataFrame, etf: pl.DataFrame) -> pl.DataFrame:
    """内连接到共同交易日。要求 ETF 行 ≥ 1 + 最大 horizon 才有 forward 收益。"""
    max_h = max(FWD_HORIZONS)
    etf = etf.filter(pl.col("date") >= sb["date"].min())
    return sb.join(etf, on="date", how="inner").sort("date")


def corr_table(df: pl.DataFrame) -> pl.DataFrame:
    """信号 × horizon 全样本 Pearson corr 表。"""
    signals = [f"net_{w}d" for w in NET_WINDOWS] + ["q60"]
    rows = []
    for sig in signals:
        row = {"signal": sig}
        for h in FWD_HORIZONS:
            ret_col = f"etf_fwd_ret_{h}d"
            sub = df.select(sig, ret_col).drop_nulls()
            row[f"ret_{h}d"] = round(sub.select(pl.corr(sig, ret_col)).item(), 4)
        rows.append(row)
    return pl.DataFrame(rows)


def rolling_corr_pairs(df: pl.DataFrame) -> dict[str, pl.DataFrame]:
    """3 条关键滚动 corr 曲线：net_20d/net_60d/q60 vs etf_fwd_ret_5d。"""
    dates = df["date"]
    y = df["etf_fwd_ret_5d"].to_numpy().astype(float)
    out = {}
    for col, key in [
        ("net_20d", "net_20d_vs_fwd5d"),
        ("net_60d", "net_60d_vs_fwd5d"),
        ("q60", "q60_vs_fwd5d"),
    ]:
        x = df[col].to_numpy().astype(float)
        rc = _rolling_corr_np(x, y, ROLL_CORR_WINDOW)
        out[key] = pl.DataFrame({"date": dates, "rc": rc})
    return out


def _rolling_corr_np(x: np.ndarray, y: np.ndarray, w: int) -> np.ndarray:
    """numpy 实现的 Pearson 滚动 corr，跳过含 NaN 的窗口。"""
    n = len(x)
    out = np.full(n, np.nan)
    if n < w:
        return out
    for i in range(w - 1, n):
        xs = x[i - w + 1:i + 1]
        ys = y[i - w + 1:i + 1]
        if np.isnan(xs).any() or np.isnan(ys).any():
            continue
        sx, sy = xs.std(), ys.std()
        if sx > 0 and sy > 0:
            out[i] = np.corrcoef(xs, ys)[0, 1]
    return out


def bucket_stats(df: pl.DataFrame) -> pl.DataFrame:
    """q60 分 10 桶，每桶 forward 3d/5d 收益均值 + 样本数 + 正收益占比。"""
    sub = df.select(["q60", "etf_fwd_ret_3d", "etf_fwd_ret_5d"]).drop_nulls()
    edges = np.linspace(0, 1, N_BUCKETS + 1)
    # q60 ∈ [0,1]，右闭分桶，最低桶含 0
    labels = [f"[{edges[i]:.1f},{edges[i+1]:.1f}]" for i in range(N_BUCKETS)]
    q_cut = pl.Series(
        "bucket",
        np.clip(
            np.digitize(sub["q60"].to_numpy(), edges[1:-1], right=False),
            0, N_BUCKETS - 1,
        ),
    )
    sub = sub.with_columns(q_cut)
    agg = (
        sub.group_by("bucket").agg(
            pl.len().alias("n"),
            pl.col("q60").mean().alias("q60_mean"),
            pl.col("etf_fwd_ret_3d").mean().alias("ret_3d_mean"),
            pl.col("etf_fwd_ret_5d").mean().alias("ret_5d_mean"),
            (pl.col("etf_fwd_ret_5d") > 0).mean().alias("pos_5d_ratio"),
        ).sort("bucket")
    )
    return agg.with_columns(pl.Series("bucket_label", labels))


def plot_dashboard(
    df: pl.DataFrame,
    rc_pairs: dict[str, pl.DataFrame],
    bucket_df: pl.DataFrame,
    output_png: Path,
) -> None:
    # 中文字体
    for f in plt.rcParams.get("font.sans-serif", []):
        if "Noto" in f or "WenQuanYi" in f:
            break
    else:
        plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "WenQuanYi Zen Hei"]
        plt.rcParams["axes.unicode_minus"] = False

    fig, axes = plt.subplots(
        2, 2, figsize=(15, 10), constrained_layout=True,
    )
    ax_scatter_n, ax_scatter_q = axes[0]
    ax_rc, ax_bucket = axes[1]

    d0 = df["date"].min()
    d1 = df["date"].max()

    # ===== 散点 1: net_60d vs etf_fwd_ret_5d =====
    sub = df.select(["net_60d", "etf_fwd_ret_5d"]).drop_nulls()
    x = sub["net_60d"].to_numpy()
    y = sub["etf_fwd_ret_5d"].to_numpy() * 100
    ax_scatter_n.scatter(
        x, y, s=6, alpha=0.35, color=COLOR_NET60, edgecolors="none",
    )
    if len(x) > 1 and np.std(x) > 0:
        coef = np.polyfit(x, y, 1)
        xs = np.linspace(x.min(), x.max(), 50)
        ax_scatter_n.plot(xs, np.polyval(coef, xs), "--", color="black",
                          linewidth=1.0, alpha=0.7)
    ax_scatter_n.axhline(0, color="gray", linewidth=0.5, alpha=0.5)
    ax_scatter_n.axvline(0, color="gray", linewidth=0.5, alpha=0.5)
    ax_scatter_n.set_xlabel("net_60d：过去 60 日南向累计净流入（亿港元）")
    ax_scatter_n.set_ylabel("etf_fwd_ret_5d：未来 5 日 ETF 收益率 (%)")
    ax_scatter_n.set_title("① 60 日累计净流入 vs 未来 5 日 ETF 收益", fontsize=11)
    ax_scatter_n.grid(True, alpha=0.3)
    # corr 对 y 的线性缩放不敏感，直接算原始两列即可
    r = float(np.corrcoef(sub["net_60d"].to_numpy(),
                          sub["etf_fwd_ret_5d"].to_numpy())[0, 1])
    ax_scatter_n.text(
        0.02, 0.97, f"Pearson r = {r:.4f}\nn = {len(sub)}",
        transform=ax_scatter_n.transAxes, va="top", fontsize=9,
        bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#bbb", alpha=0.85),
    )

    # ===== 散点 2: q60 vs etf_fwd_ret_5d =====
    sub2 = df.select(["q60", "etf_fwd_ret_5d"]).drop_nulls()
    x = sub2["q60"].to_numpy()
    y = sub2["etf_fwd_ret_5d"].to_numpy() * 100
    ax_scatter_q.scatter(
        x, y, s=6, alpha=0.35, color=COLOR_Q60, edgecolors="none",
    )
    if len(x) > 1 and np.std(x) > 0:
        coef = np.polyfit(x, y, 1)
        xs = np.linspace(0, 1, 50)
        ax_scatter_q.plot(xs, np.polyval(coef, xs), "--", color="black",
                          linewidth=1.0, alpha=0.7)
    ax_scatter_q.axhline(0, color="gray", linewidth=0.5, alpha=0.5)
    ax_scatter_q.set_xlabel("q60：当日 net_yi 在过去 60 日的百分位 (0~1)")
    ax_scatter_q.set_ylabel("etf_fwd_ret_5d：未来 5 日 ETF 收益率 (%)")
    ax_scatter_q.set_title("② 当日净流入 60 日分位 vs 未来 5 日 ETF 收益", fontsize=11)
    ax_scatter_q.grid(True, alpha=0.3)
    r = float(np.corrcoef(sub2["q60"].to_numpy(),
                          sub2["etf_fwd_ret_5d"].to_numpy())[0, 1])
    ax_scatter_q.text(
        0.02, 0.97, f"Pearson r = {r:.4f}\nn = {len(sub2)}",
        transform=ax_scatter_q.transAxes, va="top", fontsize=9,
        bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#bbb", alpha=0.85),
    )

    # ===== 滚动 corr =====
    ax_rc.axhline(0, color="gray", linewidth=0.5, alpha=0.5)
    style_map = [
        ("net_20d_vs_fwd5d", COLOR_NET20, 0.6, "-"),
        ("net_60d_vs_fwd5d", COLOR_NET60, 1.0, "-"),
        ("q60_vs_fwd5d", COLOR_Q60, 1.0, "-"),
    ]
    for key, color, lw, ls in style_map:
        rc = rc_pairs[key]
        dates = rc["date"].to_list()
        vals = [v if v is not None else float("nan") for v in rc["rc"].to_list()]
        ax_rc.plot(dates, vals, ls, color=color, linewidth=lw, label=key)
    ax_rc.set_ylabel(f"{ROLL_CORR_WINDOW} 日滚动 Pearson corr")
    ax_rc.set_xlabel("日期")
    ax_rc.set_title(
        f"③ {ROLL_CORR_WINDOW} 日滚动 corr(信号, etf_fwd_ret_5d) —— 关系稳定性",
        fontsize=11,
    )
    ax_rc.legend(loc="upper left", fontsize=8)
    ax_rc.grid(True, alpha=0.3)
    ax_rc.xaxis.set_major_locator(mdates.YearLocator(1))
    ax_rc.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    # ===== 分桶柱状 =====
    labels = bucket_df["bucket_label"].to_list()
    x = np.arange(len(labels))
    width = 0.38
    bars_3d = bucket_df["ret_3d_mean"].to_numpy() * 100
    bars_5d = bucket_df["ret_5d_mean"].to_numpy() * 100
    ax_bucket.bar(x - width / 2, bars_3d, width, label="3 日 forward",
                  color="#9ecae1", edgecolor="#3182bd", linewidth=0.5)
    ax_bucket.bar(x + width / 2, bars_5d, width, label="5 日 forward",
                  color="#fdae6b", edgecolor="#e6550d", linewidth=0.5)
    ax_bucket.axhline(0, color="gray", linewidth=0.5, alpha=0.5)
    ax_bucket.set_xticks(x)
    ax_bucket.set_xticklabels(labels, rotation=30, fontsize=8)
    ax_bucket.set_xlabel(f"q60 分位（{N_BUCKETS} 桶，0=最低净流入，1=最高）")
    ax_bucket.set_ylabel("平均 forward 收益率 (%)")
    ax_bucket.set_title("④ q60 分位分桶 → forward 收益均值", fontsize=11)
    ax_bucket.legend(loc="upper left", fontsize=8)
    ax_bucket.grid(True, alpha=0.3, axis="y")
    # 每柱顶标 n
    ns = bucket_df["n"].to_list()
    for xi, n in zip(x, ns):
        ax_bucket.text(xi, ax_bucket.get_ylim()[1] * 0.02, f"n={n}",
                       ha="center", va="bottom", fontsize=7, color="#555")

    fig.suptitle(
        f"港股通南向资金 vs 恒生科技 ETF(513180) 关系分析  "
        f"({d0} ~ {d1}, n={df.height})",
        fontsize=13, fontweight="bold", x=0.01, ha="left",
    )

    output_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_png, dpi=120, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"Saved to {output_png}")


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--sb-csv", type=Path,
        default=Path("/mnt/dataset/exchange_hkex/southbound_flow.csv"),
        help="南向资金日度 CSV",
    )
    p.add_argument(
        "--fund-file", type=Path,
        default=Path("/mnt/dataset/fund_quote_adjusted/513180.parquet"),
        help="513180 ETF 前复权 parquet",
    )
    p.add_argument(
        "--output", type=Path,
        default=Path("/mnt/dataset/southbound_etf_analysis.png"),
        help="输出 PNG",
    )
    args = p.parse_args()

    sb = load_southbound(args.sb_csv)
    etf = load_etf(args.fund_file)
    merged = merge(sb, etf)
    print(f"样本期: {merged['date'].min()} ~ {merged['date'].max()}, "
          f"n = {merged.height}")

    # ----- 相关性表 -----
    tbl = corr_table(merged)
    print("\n=== 全样本 Pearson corr(信号, etf_fwd_ret_h) ===")
    print(tbl)

    # ----- 滚动 corr -----
    rc_pairs = rolling_corr_pairs(merged)
    print(f"\n=== {ROLL_CORR_WINDOW} 日滚动 corr(信号, etf_fwd_ret_5d) 极值 ===")
    for key, rc in rc_pairs.items():
        arr = rc["rc"].to_numpy().astype(float)
        valid = arr[~np.isnan(arr)]
        if valid.size == 0:
            continue
        peak = valid.max()
        trough = valid.min()
        mean = float(np.nanmean(arr))
        print(f"  {key:25s}: mean={mean:+.4f}, "
              f"peak={peak:+.4f}, trough={trough:+.4f}")

    # ----- 分桶 -----
    buckets = bucket_stats(merged)
    print("\n=== q60 分位 → forward 收益分桶 ===")
    print(buckets)

    # ----- 画图 -----
    plot_dashboard(merged, rc_pairs, buckets, args.output)


if __name__ == "__main__":
    main()
