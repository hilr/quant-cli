"""各项贷款 12 个月增量 - M2 12 个月增量（流量差），叠加沪深300月末收盘（右轴）。

12 个月增量 = 当月余额 - 12 个月前余额（即滚动一年的净增流量）。
贷款与 M2 都是月末存量，相减得年增量。流量差比存量差更能反映边际宽松/收紧：

  - 差值 < 0 且加深：M2 增量 > 贷款增量，货币宽松未充分传导到实体信贷
    （资金淤积债市/财政沉淀/非银的 proxy）
  - 差值 ≈ 0 或 > 0：信贷与货币同步扩张（典型如 2009 四万亿、2020 疫情信贷放量）

数据源（单位均为亿元）：
- pbc/credit_funds.csv（currency=人民币，item=各项贷款）
- pbc/money_supply.csv 的 m2 列
- index_quote_history/000300.parquet（日频 → 月末收盘）

时间范围受限于沪深300（2005-04 发布），流量计算再损失头 12 个月，故取 2006-04 起。
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import polars as pl


def load_flow_gap(credit_file: Path, money_file: Path) -> pl.DataFrame:
    """读贷款与 M2 月末存量，求各自 12 个月增量（= 当月 - 12 月前），相减换算万亿元。"""
    loans = (pl.read_csv(credit_file)
               .filter((pl.col("currency") == "人民币") & (pl.col("item") == "各项贷款"))
               .with_columns(pl.col("date").str.to_date("%Y-%m"))
               .select("date", "value").rename({"value": "贷款"}))
    m2 = (pl.read_csv(money_file)
            .with_columns(pl.col("date").str.to_date("%Y-%m"))
            .select("date", "m2"))
    d = (loans.join(m2, on="date", how="inner").sort("date")
           .with_columns([
               (pl.col("贷款") - pl.col("贷款").shift(12)).alias("贷款_12m增量"),
               (pl.col("m2") - pl.col("m2").shift(12)).alias("m2_12m增量"),
           ])
           .with_columns(((pl.col("贷款_12m增量") - pl.col("m2_12m增量")) / 10000).alias("流量差_万亿")))
    return d


def load_hs300(index_file: Path) -> pl.DataFrame:
    """读沪深300日频收盘，重采样为月末收盘（对齐月度宏观数据）。"""
    return (pl.read_parquet(index_file, columns=["date", "close"])
              .with_columns(pl.col("date").str.to_date("%Y-%m-%d").alias("d"))
              .sort("d")
              .group_by(pl.col("d").dt.strftime("%Y-%m").alias("date"))
              .agg(pl.col("close").last().alias("hs300"))
              .with_columns(pl.col("date").str.to_date("%Y-%m"))
              .sort("date"))


def plot(d: pl.DataFrame, hs300: pl.DataFrame, output_png: Path) -> None:
    plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "WenQuanYi Zen Hei"]
    plt.rcParams["axes.unicode_minus"] = False

    fig, ax = plt.subplots(figsize=(13, 6.5))
    ax.plot(d["date"], d["流量差_万亿"], color="#d62728", lw=1.6,
            label="贷款12月增量 − M2 12月增量（左轴）")
    ax.fill_between(d["date"], 0, d["流量差_万亿"], where=d["流量差_万亿"] < 0,
                    color="#d62728", alpha=0.12, interpolate=True)
    ax.fill_between(d["date"], 0, d["流量差_万亿"], where=d["流量差_万亿"] >= 0,
                    color="#2ca02c", alpha=0.15, interpolate=True)
    ax.axhline(0, color="black", lw=0.6)

    axr = ax.twinx()
    axr.plot(hs300["date"], hs300["hs300"], color="#1f77b4", lw=1.0, alpha=0.7,
             label="沪深300月末收盘（右轴）")

    ax.set_title("各项贷款 12 月增量 − M2 12 月增量（人民币）vs 沪深300")
    ax.set_ylabel("万亿元（年增量差）")
    axr.set_ylabel("沪深300收盘点位", color="#1f77b4")
    axr.tick_params(axis="y", labelcolor="#1f77b4")
    dates = d["date"].to_list()
    span = dates[-1] - dates[0]
    ax.set_xlim(date(2006, 4, 1), dates[-1] + span * 0.02)
    ax.text(0.99, 0.03, f"最新 {dates[-1]}", transform=ax.transAxes,
            ha="right", va="bottom", fontsize=10, color="#222", fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#bbb", alpha=0.85))
    ax.grid(True, alpha=0.3)

    lines_left, labels_left = ax.get_legend_handles_labels()
    lines_right, labels_right = axr.get_legend_handles_labels()
    ax.legend(lines_left + lines_right, labels_left + labels_right, loc="upper left", fontsize=9)

    for x, lab in [(date(2008, 11, 1), "四万亿\n信贷冲刺"),
                   (date(2014, 11, 1), "降息周期\n2015牛市"),
                   (date(2020, 3, 1), "疫情\n信贷放量"),
                   (date(2022, 4, 1), "存款大增\nM2 远超贷款"),
                   (date(2024, 9, 1), "924 政策")]:
        ax.axvline(x, color="#888", lw=0.7, ls="--", alpha=0.6)
        y = ax.get_ylim()[0] * 0.95 if lab != "四万亿\n信贷冲刺" else ax.get_ylim()[1] * 0.95
        va = "bottom" if lab != "四万亿\n信贷冲刺" else "top"
        ax.text(x, y, lab, fontsize=8, color="#555", rotation=90, va=va, ha="right")

    ax.xaxis.set_major_locator(mdates.YearLocator(2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    fig.autofmt_xdate()
    plt.tight_layout()
    output_png.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_png, dpi=130)
    plt.close(fig)
    print(f"Saved to {output_png}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--credit-file", type=Path,
        default=Path("/mnt/dataset/pbc/credit_funds.csv"),
        help="pbc/credit_funds.csv 路径",
    )
    parser.add_argument(
        "--money-file", type=Path,
        default=Path("/mnt/dataset/pbc/money_supply.csv"),
        help="pbc/money_supply.csv 路径",
    )
    parser.add_argument(
        "--index-file", type=Path,
        default=Path("/mnt/dataset/index_quote_history/000300.parquet"),
        help="沪深300 parquet 路径",
    )
    parser.add_argument(
        "--output", type=Path,
        default=Path("/mnt/dataset/loans_m2_12m_flow_vs_hs300.png"),
        help="输出 PNG 路径",
    )
    args = parser.parse_args()
    d = load_flow_gap(args.credit_file, args.money_file)
    hs300 = load_hs300(args.index_file)
    if d["流量差_万亿"].null_count():
        miss = d.filter(pl.col("流量差_万亿").is_null())["date"].to_list()
        print(f"警告：以下月份缺失：{miss}")
    plot(d, hs300, args.output)


if __name__ == "__main__":
    main()
