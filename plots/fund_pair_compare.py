"""两只基金/ETF 对比：双轴价格 + 滚动相关系数柱状。

上面板：两只标的前复权收盘价，各占一个 y 轴（价格量级不同时不归一化，
保留真实价格水位）。

下面板：两者日收益率的 N 日滚动 Pearson 相关系数，柱状（负值红 / 正值蓝），
叠加全程相关系数虚线。

用日收益率（而非价格）算相关：价格序列带漂移，直接相关会虚高；收益相关
衡量「涨跌是否同步」，才是对冲/轮动真正关心的。

数据源：fund_quote_adjusted/{code}.parquet（前复权日行情）。
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import polars as pl


def _load(input_dir: Path, code: str, window: int) -> pl.DataFrame:
    fp = input_dir / f"{code}.parquet"
    df = pl.read_parquet(fp, columns=["date", "close", "name"])
    df = df.with_columns(pl.col("date").cast(pl.Date)).sort("date")
    return df.tail(window)


def _rolling_corr(df: pl.DataFrame, col_a: str, col_b: str, n: int) -> pl.Expr:
    """N 日滚动 Pearson，用滚动求和向量化展开（cov / (σa·σb)）。"""
    sx = pl.col(col_a).rolling_sum(n)
    sy = pl.col(col_b).rolling_sum(n)
    sxy = (pl.col(col_a) * pl.col(col_b)).rolling_sum(n)
    sx2 = (pl.col(col_a) ** 2).rolling_sum(n)
    sy2 = (pl.col(col_b) ** 2).rolling_sum(n)
    cov = sxy / n - sx * sy / n / n
    var_a = sx2 / n - sx * sx / n / n
    var_b = sy2 / n - sy * sy / n / n
    return cov / (var_a.sqrt() * var_b.sqrt())


def plot_pair(
    input_dir: Path,
    code_a: str,
    code_b: str,
    output: Path,
    window: int = 60,
    corr_window: int = 5,
) -> None:
    plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "WenQuanYi Zen Hei"]
    plt.rcParams["axes.unicode_minus"] = False

    a = _load(input_dir, code_a, window)
    b = _load(input_dir, code_b, window)
    name_a = a["name"][0]
    name_b = b["name"][0]

    j = (a.select("date", "close").rename({"close": "ca"})
         .join(b.select("date", "close").rename({"close": "cb"}), on="date")
         .sort("date")
         .with_columns(
             (pl.col("ca") / pl.col("ca").shift(1) - 1).alias("ra"),
             (pl.col("cb") / pl.col("cb").shift(1) - 1).alias("rb"),
         ))
    corr_df = j.with_columns(
        _rolling_corr(j, "ra", "rb", corr_window).alias("corr")
    )
    full_corr = j.drop_nulls(["ra", "rb"]).select(pl.corr("ra", "rb"))[0, 0]

    fig, (ax_top, ax_bot) = plt.subplots(
        2, 1, figsize=(13, 8), sharex=True,
        gridspec_kw={"height_ratios": [2, 1]},
    )
    ax_top_b = ax_top.twinx()
    ax_top.plot(a["date"].to_numpy(), a["close"].to_numpy(),
                color="#d62728", lw=1.9, label=f"{code_a} {name_a}")
    ax_top_b.plot(b["date"].to_numpy(), b["close"].to_numpy(),
                  color="#1f77b4", lw=1.9, label=f"{code_b} {name_b}")
    ax_top.set_ylabel(f"{code_a} 价格", color="#d62728")
    ax_top_b.set_ylabel(f"{code_b} 价格", color="#1f77b4")
    ax_top.tick_params(axis="y", colors="#d62728")
    ax_top_b.tick_params(axis="y", colors="#1f77b4")
    ax_top.grid(True, alpha=0.3)
    h1, l1 = ax_top.get_legend_handles_labels()
    h2, l2 = ax_top_b.get_legend_handles_labels()
    ax_top.legend(h1 + h2, l1 + l2, loc="upper left")
    ax_top.set_title(
        f"{code_a} {name_a}  vs  {code_b} {name_b}"
        f"  (过去 {window} 交易日, 全程 corr={full_corr:+.2f})"
    )

    cc = corr_df.drop_nulls("corr")
    d = cc["date"].to_numpy()
    v = cc["corr"].to_numpy()
    colors = ["#d62728" if x < 0 else "#1f77b4" for x in v]
    ax_bot.bar(d, v, width=0.9, color=colors, alpha=0.8)
    ax_bot.axhline(0, color="black", lw=0.8)
    ax_bot.axhline(full_corr, color="gray", lw=0.9, ls="--", alpha=0.8,
                  label=f"全程 {full_corr:+.2f}")
    ax_bot.set_ylabel(f"{corr_window} 日滚动相关系数")
    ax_bot.set_ylim(-1.05, 1.05)
    ax_bot.grid(True, alpha=0.3, axis="y")
    ax_bot.legend(loc="upper left", fontsize=9)
    ax_bot.xaxis.set_major_locator(mdates.WeekdayLocator(interval=2))
    ax_bot.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))

    fig.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output, dpi=120)
    plt.close(fig)
    print(f"{code_a} {name_a} vs {code_b} {name_b}: "
          f"{a['date'][0]} ~ {a['date'][-1]} | 全程 corr={full_corr:+.3f} | "
          f"{corr_window}d 滚动 mean={v.mean():+.3f} last={v[-1]:+.3f}")
    print(f"Saved to {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path,
                        default=Path("/mnt/dataset/fund_quote_adjusted"),
                        help="前复权行情目录")
    parser.add_argument("--code-a", default="588170", help="标的 A 代码")
    parser.add_argument("--code-b", default="512800", help="标的 B 代码")
    parser.add_argument("--window", type=int, default=60, help="回看交易日数")
    parser.add_argument("--corr-window", type=int, default=5, help="滚动相关窗口")
    parser.add_argument("--output", type=Path,
                        default=Path("/mnt/dataset/fund_pair_compare.png"),
                        help="输出 PNG 路径")
    args = parser.parse_args()

    plot_pair(
        input_dir=args.input_dir,
        code_a=args.code_a,
        code_b=args.code_b,
        output=args.output,
        window=args.window,
        corr_window=args.corr_window,
    )


if __name__ == "__main__":
    main()
