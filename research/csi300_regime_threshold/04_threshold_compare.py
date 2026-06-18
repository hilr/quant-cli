"""三种阈值方法在 CSI300 上标记的异常点对比。

z_obs = (close - MA120) / σ120  （布林通道的标准化偏离）

三种方法在同一目标 α 下算左尾阈值：
- normal    : k = Φ⁻¹(α)
- cf        : k = Cornish-Fisher 展开（用 z_obs 全历史的偏度 S、峰度 K）
- empirical : k = z_obs 全历史的 α 分位数

画一张大图：close + MA + 三条阈值线 + 三组异常点。
再打印每个方法命中的日期清单（便于人工对照）。
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import polars as pl
from scipy import stats


def cornish_fisher_z(alpha: float, skew: float, kurt_excess: float) -> float:
    """alpha 分位（左尾 if alpha<0.5）的 CF 修正 z。"""
    z = stats.norm.ppf(alpha)
    return (
        z
        + (z**2 - 1) / 6 * skew
        + (z**3 - 3 * z) / 24 * kurt_excess
        - (2 * z**3 - 5 * z) / 36 * skew**2
    )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--code", default="000300")
    p.add_argument(
        "--data",
        type=Path,
        default=Path("/mnt/dataset/index_quote_history/000300.parquet"),
    )
    p.add_argument("--window", type=int, default=120)
    p.add_argument("--alpha", type=float, default=0.01, help="左尾目标概率，默认 1%")
    p.add_argument(
        "--output",
        type=Path,
        default=Path("/mnt/dataset/threshold_compare_000300.png"),
    )
    args = p.parse_args()

    df = (
        pl.read_parquet(args.data)
        .with_columns(pl.col("date").str.to_date("%Y-%m-%d"))
        .sort("date")
    )
    w = args.window
    df = df.with_columns(
        pl.col("close").rolling_mean(w).alias("ma"),
        pl.col("close").rolling_std(w).alias("sigma"),
    ).with_columns(((pl.col("close") - pl.col("ma")) / pl.col("sigma")).alias("z_obs"))
    df = df.filter(pl.col("z_obs").is_not_null())

    z_obs = df["z_obs"].to_numpy()
    dates_arr = df["date"].to_numpy()
    closes_arr = df["close"].to_numpy()
    ma_arr = df["ma"].to_numpy()
    sigma_arr = df["sigma"].to_numpy()

    # z_obs 自身的均值/方差（注意 std 不一定=1，因为 (close-MA) 的方差 ≠ close 的方差）
    mu_z = float(z_obs.mean())
    sigma_z = float(z_obs.std(ddof=1))
    S = float(stats.skew(z_obs))
    K = float(stats.kurtosis(z_obs))
    print(
        f"z_obs (n={len(z_obs)}): mean={mu_z:+.4f}  std={sigma_z:.4f}  "
        f"skew={S:+.4f}  kurt={K:+.4f}  "
        f"min={z_obs.min():+.3f}  max={z_obs.max():+.3f}"
    )

    # 三种阈值（在 z_obs 尺度上，都已经把 μ_z / σ_z 折算进去）
    k_normal = mu_z + sigma_z * float(stats.norm.ppf(args.alpha))
    k_cf = mu_z + sigma_z * cornish_fisher_z(args.alpha, S, K)
    k_emp = float(np.quantile(z_obs, args.alpha))

    print(
        f"\nα = {args.alpha*100:.2f}% 左尾阈值（z_obs 尺度，已折算 μ_z/sigma_z）：\n"
        f"  normal    k = {k_normal:+.4f}   (= μ_z + σ_z × Φ⁻¹(α) = {mu_z:+.3f} + {sigma_z:.3f} × {stats.norm.ppf(args.alpha):+.3f})\n"
        f"  cf        k = {k_cf:+.4f}   (= μ_z + σ_z × CF(α,S,K), CF z = {cornish_fisher_z(args.alpha, S, K):+.3f})\n"
        f"  empirical k = {k_emp:+.4f}   (= 历史真实分位)"
    )

    mask_n = z_obs <= k_normal
    mask_cf = z_obs <= k_cf
    mask_emp = z_obs <= k_emp
    expected = len(z_obs) * args.alpha
    print(
        f"\n实际命中数（理论 {expected:.1f} 个 = {args.alpha*100:.2f}% × {len(z_obs)}）：\n"
        f"  normal    : {mask_n.sum():>4}  ({mask_n.sum()/len(z_obs)*100:.2f}%)\n"
        f"  cf        : {mask_cf.sum():>4}  ({mask_cf.sum()/len(z_obs)*100:.2f}%)\n"
        f"  empirical : {mask_emp.sum():>4}  ({mask_emp.sum()/len(z_obs)*100:.2f}%)"
    )

    # 三者交集/差集
    all_three = mask_n & mask_cf & mask_emp
    only_n = mask_n & ~mask_cf & ~mask_emp
    only_cf = mask_cf & ~mask_n & ~mask_emp
    only_emp = mask_emp & ~mask_n & ~mask_cf
    print(
        f"\n交集分析：\n"
        f"  三者都命中: {all_three.sum()}\n"
        f"  仅 normal : {only_n.sum()}\n"
        f"  仅 CF     : {only_cf.sum()}\n"
        f"  仅 emp    : {only_emp.sum()}"
    )

    # 打印所有命中日期（按时间排序，标注哪些方法命中）
    all_hits = mask_n | mask_cf | mask_emp
    hit_idx = np.where(all_hits)[0]
    print(f"\n{'date':<12}{'close':>10}{'z_obs':>8}{'normal':>8}{'cf':>5}{'emp':>5}")
    for i in hit_idx:
        print(
            f"  {str(dates_arr[i])[:10]:<12}{closes_arr[i]:>10.2f}{z_obs[i]:>+8.3f}"
            f"{'  *' if mask_n[i] else '':>8}{'  *' if mask_cf[i] else '':>5}"
            f"{'  *' if mask_emp[i] else '':>5}"
        )

    # 画图
    fig, ax = plt.subplots(figsize=(16, 8))
    ax.plot(dates_arr, closes_arr, "-", color="black", linewidth=0.5, alpha=0.5,
            label="close")
    ax.plot(dates_arr, ma_arr, "--", color="gray", linewidth=0.5, alpha=0.5,
            label=f"MA{w}")

    thresh_n = ma_arr + k_normal * sigma_arr
    thresh_cf = ma_arr + k_cf * sigma_arr
    thresh_emp = ma_arr + k_emp * sigma_arr
    ax.plot(dates_arr, thresh_n, "-", color="#1f77b4", linewidth=0.8, alpha=0.6)
    ax.plot(dates_arr, thresh_cf, "-", color="#ff7f0e", linewidth=0.8, alpha=0.6)
    ax.plot(dates_arr, thresh_emp, "-", color="#2ca02c", linewidth=0.8, alpha=0.6)

    # 异常点轻微 y 偏移避免重叠
    ax.scatter(dates_arr[mask_n], closes_arr[mask_n] * 0.985,
               marker="v", color="#1f77b4", s=55, zorder=5,
               edgecolors="black", linewidths=0.4)
    ax.scatter(dates_arr[mask_cf], closes_arr[mask_cf] * 0.96,
               marker="s", color="#ff7f0e", s=50, zorder=6,
               edgecolors="black", linewidths=0.4)
    ax.scatter(dates_arr[mask_emp], closes_arr[mask_emp] * 0.935,
               marker="D", color="#2ca02c", s=45, zorder=7,
               edgecolors="black", linewidths=0.4)

    from matplotlib.lines import Line2D
    legend_handles = [
        Line2D([0], [0], color="black", linewidth=0.8, label="close"),
        Line2D([0], [0], color="gray", linestyle="--", linewidth=0.8, label=f"MA{w}"),
        Line2D([0], [0], color="#1f77b4", linewidth=1.2,
               label=f"normal  k={k_normal:+.2f}σ  ({mask_n.sum()} hits)"),
        Line2D([0], [0], color="#ff7f0e", linewidth=1.2,
               label=f"CF      k={k_cf:+.2f}σ  ({mask_cf.sum()} hits)"),
        Line2D([0], [0], color="#2ca02c", linewidth=1.2,
               label=f"emp     k={k_emp:+.2f}σ  ({mask_emp.sum()} hits)"),
        Line2D([0], [0], marker="v", color="w", markerfacecolor="#1f77b4",
               markeredgecolor="black", markersize=9, label="normal hits"),
        Line2D([0], [0], marker="s", color="w", markerfacecolor="#ff7f0e",
               markeredgecolor="black", markersize=8, label="CF hits"),
        Line2D([0], [0], marker="D", color="w", markerfacecolor="#2ca02c",
               markeredgecolor="black", markersize=8, label="empirical hits"),
    ]
    ax.legend(handles=legend_handles, loc="upper left", fontsize=8, ncol=2)

    ax.set_title(
        f"CSI300 三种阈值方法对比  "
        f"z_obs = (close−MA{w})/σ{w}，α={args.alpha*100:.2f}% 左尾\n"
        f"z_obs 分布：skew={S:+.3f}, kurt(excess)={K:+.3f}",
        fontsize=11,
    )
    ax.set_xlabel("Date")
    ax.set_ylabel("Close")
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_locator(mdates.YearLocator(2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    plt.tight_layout()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(args.output, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"\nSaved to {args.output}")


if __name__ == "__main__":
    main()
