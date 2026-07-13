"""数据转换模块"""
import csv
import re
import zipfile
from datetime import date
from html.parser import HTMLParser
from xml.etree import ElementTree as ET

import numpy as np
import polars as pl
from pathlib import Path
from python_calamine import CalamineWorkbook


# 默认数据路径
DEFAULT_DATA_PATH = "/mnt/readonly_dataset"
OUTPUT_DATA_PATH = "/mnt/dataset"

# ============== TA 窗口常量 ==============

TA_MA_WINDOWS = [5, 10, 20, 60, 120, 250]
TA_EMA_WINDOWS = [5, 10, 20, 60, 120, 250]
TA_BOLL_PERIODS = [20, 60]
TA_HIST_PERIODS = [1000, 750, 500, 250, 120, 60, 20]
TA_TURNOVER_STD_WINDOWS = [10, 20, 40]
TA_VOLATILITY_STD_WINDOWS = [10, 20, 40, 60, 120]
TA_FWD_WINDOWS = [5, 10]


# ============== stock_quote ==============

STOCK_QUOTE_FLOAT_COLS = [
    "prev_close", "open", "high", "low", "close", "volume", "turnover",
    "market_cap", "free_float_market_cap"
]
STOCK_QUOTE_STR_COLS = ["证券简称"]


def convert_stock_quote(
    data_path: str = DEFAULT_DATA_PATH,
    source: str = "finance_sina",
    output_dir: str = OUTPUT_DATA_PATH,
) -> int:
    """将每日股票行情数据转换为每个股票的历史数据"""
    source_path = Path(data_path) / source / "stock_quote"

    csv_files = sorted(source_path.glob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(f"No CSV files found in {source_path}")

    first_df = pl.read_csv(csv_files[0])
    std_cols = first_df.columns.copy()

    dfs = []
    for csv_file in csv_files:
        df = pl.read_csv(csv_file, ignore_errors=True)
        # code 转字符串，zfill 6位
        df = df.with_columns(pl.col("code").cast(pl.String).str.zfill(6))
        for col in STOCK_QUOTE_FLOAT_COLS:
            if col in df.columns:
                df = df.with_columns(pl.col(col).cast(pl.Float64))
        for col in std_cols:
            if col not in df.columns:
                df = df.with_columns(
                    pl.lit(None).cast(pl.Float64).alias(col)
                    if col not in STOCK_QUOTE_STR_COLS
                    else pl.lit("").cast(pl.String).alias(col)
                )
        df = df.select(std_cols)
        dfs.append(df)

    combined = pl.concat(dfs)
    combined = combined.sort(["code", "date"])

    output_path = Path(output_dir) / "stock_quote_history"
    output_path.mkdir(parents=True, exist_ok=True)

    for code, group in combined.group_by("code"):
        code_val = code[0]
        file_path = output_path / f"{code_val}.parquet"
        group.sort("date").write_parquet(file_path)

    print(f"Saved {len(combined.unique("code"))} stocks to {output_path}")
    return len(combined.unique("code"))


# ============== margin_trade ==============

MARGIN_TRADE_FLOAT_COLS = [
    "margin_buy_total", "margin_buy", "margin_close", "short_sell_total",
    "short_sell_total_vol", "short_sell_vol", "short_close_vol"
]
MARGIN_TRADE_STR_COLS = ["name"]

# Schema A → Schema B 列名映射
MARGIN_TRADE_COL_MAP = {
    "证券简称": "name",
    "margin_total": "margin_buy_total",
    "short_total": "short_sell_total",
    "short_total_vol": "short_sell_total_vol",
}


def convert_margin_trade(
    data_path: str = DEFAULT_DATA_PATH,
    source: str = "eastmoney",
    output_dir: str = OUTPUT_DATA_PATH,
) -> int:
    """将每日融资融券数据转换为每个标的的历史数据"""
    source_path = Path(data_path) / source / "margin_trade"

    csv_files = sorted(source_path.glob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(f"No CSV files found in {source_path}")

    # Schema B 标准列（以最新格式为准）
    STD_COLS = ["date", "code", "name", "margin_buy_total", "margin_buy",
                "margin_close", "short_sell_total", "short_sell_total_vol",
                "short_sell_vol", "short_close_vol"]

    dfs = []
    for csv_file in csv_files:
        df = pl.read_csv(csv_file, ignore_errors=True)

        # Schema A → Schema B: 重命名列
        df = df.rename({k: v for k, v in MARGIN_TRADE_COL_MAP.items() if k in df.columns})

        # code 转字符串，zfill 6位
        df = df.with_columns(pl.col("code").cast(pl.String).str.zfill(6))

        # 数值列转 Float64
        for col in MARGIN_TRADE_FLOAT_COLS:
            if col in df.columns:
                df = df.with_columns(pl.col(col).cast(pl.Float64))

        # 补齐缺失的列
        for col in STD_COLS:
            if col not in df.columns:
                df = df.with_columns(
                    pl.lit(None).cast(pl.Float64).alias(col)
                    if col not in MARGIN_TRADE_STR_COLS
                    else pl.lit("").cast(pl.String).alias(col)
                )

        df = df.select(STD_COLS)
        dfs.append(df)

    combined = pl.concat(dfs)
    combined = combined.sort(["code", "date"])

    output_path = Path(output_dir) / "margin_trade_history"
    output_path.mkdir(parents=True, exist_ok=True)

    for code, group in combined.group_by("code"):
        code_val = code[0]
        group = group.sort("date")

        # 计算净变化额
        group = group.with_columns([
            (pl.col("margin_buy_total") - pl.col("margin_buy_total").shift(1)).alias("margin_net_change"),
            (pl.col("short_sell_total") - pl.col("short_sell_total").shift(1)).alias("short_net_change"),
            (pl.col("short_sell_total_vol") - pl.col("short_sell_total_vol").shift(1)).alias("short_vol_net_change"),
        ])

        file_path = output_path / f"{code_val}.parquet"
        group.write_parquet(file_path)

    print(f"Saved {len(combined.unique("code"))} items to {output_path}")
    return len(combined.unique("code"))


# ============== margin_trade_daily ==============

def convert_margin_trade_daily(
    input_dir: str = "/mnt/dataset/margin_trade_history",
    output_dir: str = "/mnt/dataset/margin_trade_daily",
) -> int:
    """从个股文件中提取净变化数据，生成每日汇总文件。
    一次性读入所有标的的净变化列，按日期分组输出。
    从最新日期往前反推，文件存在则跳过。"""
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    parquet_files = sorted(input_path.glob("*.parquet"))
    if not parquet_files:
        raise FileNotFoundError(f"No parquet files found in {input_path}")

    net_cols = ["date", "code", "name", "margin_net_change", "short_net_change", "short_vol_net_change"]

    # 一次性读入所有标的的净变化数据
    dfs = []
    for pf in parquet_files:
        df = pl.read_parquet(pf, columns=net_cols)
        dfs.append(df)

    combined = pl.concat(dfs)
    combined = combined.sort("date")

    # 获取全部日期，从最新往前
    all_dates = sorted(combined["date"].unique().to_list(), reverse=True)

    count = 0
    for date in all_dates:
        daily_file = output_path / f"{date}.parquet"
        if daily_file.exists():
            continue

        day_df = combined.filter(pl.col("date") == date)
        day_df.write_parquet(daily_file)
        count += 1

    print(f"Saved {count} daily files to {output_path}")
    return count

PRICE_COLS = ["prev_close", "open", "high", "low", "close"]


def convert_adjust(
    input_dir: str = "/mnt/dataset/stock_quote_history",
    output_dir: str = "/mnt/dataset/stock_quote_adjusted",
) -> int:
    """前复权：将股票历史价格按最新价格向前调整"""
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    parquet_files = sorted(input_path.glob("*.parquet"))
    if not parquet_files:
        raise FileNotFoundError(f"No parquet files found in {input_path}")

    count = 0
    for pf in parquet_files:
        df = pl.read_parquet(pf)

        # 降序排序（新→旧）
        df = df.sort("date", descending=True)

        # factor = prev_close / 前一天close
        df = df.with_columns(
            pl.col("close").shift(-1).alias("prev_day_close"),
        )
        df = df.with_columns(
            pl.when(pl.col("prev_day_close").is_null())
            .then(1.0)
            .otherwise(pl.col("prev_close") / pl.col("prev_day_close"))
            .alias("factor"),
        )

        # cum_factor = 排除当天因子的累积乘积
        df = df.with_columns(
            pl.col("factor").cum_prod().shift(1).fill_null(1.0).alias("cum_factor"),
        )

        # 应用到所有价格列
        for c in PRICE_COLS:
            df = df.with_columns((pl.col(c) * pl.col("cum_factor")).alias(c))

        # 清理中间列，恢复升序
        df = df.select(PRICE_COLS + ["date", "code"] + [c for c in df.columns if c not in PRICE_COLS and c != "date" and c != "code"])
        df = df.drop(["prev_day_close", "factor", "cum_factor"])
        df = df.sort("date")

        df.write_parquet(output_path / pf.name)
        count += 1

    print(f"Saved {count} stocks to {output_path}")
    return count


# ============== ta ==============

def _add_ma(df: pl.DataFrame, windows: list[int]) -> pl.DataFrame:
    return df.with_columns([
        pl.col("close").rolling_mean(w).alias(f"ma{w}")
        for w in windows
    ] + [
        pl.col("turnover").rolling_mean(w).alias(f"turnover_ma{w}")
        for w in windows
    ] + [
        ((pl.col("close") - pl.col("close").shift(w)) / pl.col("close").shift(w) / w).alias(f"return_{w}d")
        for w in windows
    ])


def _add_ema(df: pl.DataFrame, windows: list[int]) -> pl.DataFrame:
    """指数移动平均：α = 2/(N+1)，adjust=False 走传统递推公式。"""
    return df.with_columns([
        pl.col("close").ewm_mean(span=w, adjust=False, min_samples=0).alias(f"ema{w}")
        for w in windows
    ] + [
        pl.col("turnover").ewm_mean(span=w, adjust=False, min_samples=0).alias(f"turnover_ema{w}")
        for w in windows
    ])


def _add_volatility(df: pl.DataFrame, std_windows: list[int], turnover_std_windows: list[int]) -> pl.DataFrame:
    df = df.with_columns([
        ((pl.col("close") - pl.col("prev_close")) / pl.col("prev_close")).alias("return_1d"),
        (pl.col("close") / pl.col("prev_close")).log().alias("volatility_1d"),
    ])
    return df.with_columns([
        pl.col("volatility_1d").rolling_std(w).alias(f"volatility_std{w}")
        for w in std_windows
    ] + [
        pl.col("turnover").rolling_std(w).alias(f"turnover_std{w}")
        for w in turnover_std_windows
    ])


def _add_boll(df: pl.DataFrame, periods: list[int]) -> pl.DataFrame:
    for p in periods:
        std_c = pl.col("close").rolling_std(p)
        std_t = pl.col("turnover").rolling_std(p)
        df = df.with_columns([
            pl.col(f"ma{p}").alias(f"boll_mid{p}"),
            (pl.col(f"ma{p}") + 2 * std_c).alias(f"boll_upper{p}"),
            (pl.col(f"ma{p}") - 2 * std_c).alias(f"boll_lower{p}"),
            pl.col(f"turnover_ma{p}").alias(f"turnover_boll_mid{p}"),
            (pl.col(f"turnover_ma{p}") + 2 * std_t).alias(f"turnover_boll_upper{p}"),
            (pl.col(f"turnover_ma{p}") - 2 * std_t).alias(f"turnover_boll_lower{p}"),
        ])
    return df


def _add_hist(df: pl.DataFrame, periods: list[int]) -> pl.DataFrame:
    return df.with_columns([
        expr
        for p in periods
        for expr in [
            pl.col("high").rolling_max(p).alias(f"high_{p}"),
            pl.col("low").rolling_min(p).alias(f"low_{p}"),
            ((pl.col("close") - pl.col("close").shift(p - 1)) / pl.col("close").shift(p - 1) * 100).alias(f"return_{p}"),
        ]
    ])


def _add_fwd(df: pl.DataFrame, windows: list[int]) -> pl.DataFrame:
    for N in windows:
        df = _compute_fwd(df, N, str(N))
    fwd_drop = [c for c in df.columns if c.startswith("_h") or c.startswith("_l") or c.startswith("_c")]
    return df.drop(fwd_drop)


def _compute_ta_pipeline(
    input_dir: str,
    output_dir: str,
    indicators: list,
    label: str,
) -> int:
    """通用 TA 计算管道：逐文件读取 → 按顺序应用指标 → 写入"""
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    parquet_files = sorted(input_path.glob("*.parquet"))
    if not parquet_files:
        raise FileNotFoundError(f"No parquet files found in {input_path}")
    count = 0
    for pf in parquet_files:
        df = pl.read_parquet(pf).sort("date")
        for indicator in indicators:
            df = indicator(df)
        df.write_parquet(output_path / pf.name)
        count += 1
    print(f"Saved {count} {label} to {output_path}")
    return count


def convert_ta(
    input_dir: str = "/mnt/dataset/stock_quote_adjusted",
    output_dir: str = "/mnt/dataset/stock_quote_ta",
) -> int:
    """基于前复权数据计算均线、布林带、历史统计、前向收益等指标"""
    return _compute_ta_pipeline(
        input_dir, output_dir,
        indicators=[
            lambda df: _add_ma(df, TA_MA_WINDOWS),
            lambda df: _add_ema(df, TA_EMA_WINDOWS),
            lambda df: _add_volatility(df, TA_VOLATILITY_STD_WINDOWS, TA_TURNOVER_STD_WINDOWS),
            lambda df: _add_boll(df, TA_BOLL_PERIODS),
            lambda df: _add_hist(df, TA_HIST_PERIODS),
            lambda df: _add_fwd(df, TA_FWD_WINDOWS),
        ],
        label="stocks",
    )


# ============== boll ==============

def convert_boll(
    input_dir: str = "/mnt/dataset/stock_quote_adjusted",
    output_dir: str = "/mnt/dataset/stock_quote_boll",
) -> int:
    """基于前复权数据计算布林带（period=20/60, k=2）"""
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    parquet_files = sorted(input_path.glob("*.parquet"))
    if not parquet_files:
        raise FileNotFoundError(f"No parquet files found in {input_path}")

    periods = [20, 60]

    count = 0
    for pf in parquet_files:
        df = pl.read_parquet(pf)
        df = df.sort("date")

        for p in periods:
            mid_c = pl.col("close").rolling_mean(p)
            std_c = pl.col("close").rolling_std(p)
            mid_t = pl.col("turnover").rolling_mean(p)
            std_t = pl.col("turnover").rolling_std(p)
            df = df.with_columns([
                mid_c.alias(f"boll_mid{p}"),
                (mid_c + 2 * std_c).alias(f"boll_upper{p}"),
                (mid_c - 2 * std_c).alias(f"boll_lower{p}"),
                mid_t.alias(f"turnover_boll_mid{p}"),
                (mid_t + 2 * std_t).alias(f"turnover_boll_upper{p}"),
                (mid_t - 2 * std_t).alias(f"turnover_boll_lower{p}"),
            ])

        df.write_parquet(output_path / pf.name)
        count += 1

    print(f"Saved {count} stocks to {output_path}")
    return count


# ============== index ma/boll ==============

def convert_index_ta(
    input_dir: str = "/mnt/dataset/index_quote_history",
    output_dir: str = "/mnt/dataset/index_quote_ta",
) -> int:
    """基于指数行情计算 close 和 turnover 的滚动均线"""
    return _compute_ta_pipeline(
        input_dir, output_dir,
        indicators=[
            lambda df: _add_ma(df, TA_MA_WINDOWS),
            lambda df: _add_ema(df, TA_EMA_WINDOWS),
            lambda df: _add_volatility(df, TA_VOLATILITY_STD_WINDOWS, TA_TURNOVER_STD_WINDOWS),
            lambda df: _add_boll(df, TA_BOLL_PERIODS),
            lambda df: _add_hist(df, TA_HIST_PERIODS),
        ],
        label="indices",
    )


def convert_index_boll(
    input_dir: str = "/mnt/dataset/index_quote_history",
    output_dir: str = "/mnt/dataset/index_quote_boll",
) -> int:
    """基于指数行情计算布林带（period=20/60, k=2）"""
    return _compute_boll(input_dir, output_dir, [20, 60], "indices")


def _compute_boll(input_dir: str, output_dir: str, periods: list[int], label: str) -> int:
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    parquet_files = sorted(input_path.glob("*.parquet"))
    if not parquet_files:
        raise FileNotFoundError(f"No parquet files found in {input_path}")
    count = 0
    for pf in parquet_files:
        df = pl.read_parquet(pf).sort("date")
        for p in periods:
            mid_c = pl.col("close").rolling_mean(p)
            std_c = pl.col("close").rolling_std(p)
            mid_t = pl.col("turnover").rolling_mean(p)
            std_t = pl.col("turnover").rolling_std(p)
            df = df.with_columns([
                mid_c.alias(f"boll_mid{p}"), (mid_c + 2 * std_c).alias(f"boll_upper{p}"), (mid_c - 2 * std_c).alias(f"boll_lower{p}"),
                mid_t.alias(f"turnover_boll_mid{p}"), (mid_t + 2 * std_t).alias(f"turnover_boll_upper{p}"), (mid_t - 2 * std_t).alias(f"turnover_boll_lower{p}"),
            ])
        df.write_parquet(output_path / pf.name)
        count += 1
    print(f"Saved {count} {label} to {output_path}")
    return count


# ============== fwd_return ==============

def _compute_fwd(df: pl.DataFrame, N: int, tag: str) -> pl.DataFrame:
    """对单个股票计算前向 N 日收益率特征"""
    df = df.with_columns([
        pl.col("high").shift(-offset).alias(f"_h{offset}")
        for offset in range(1, N + 1)
    ] + [
        pl.col("low").shift(-offset).alias(f"_l{offset}")
        for offset in range(1, N + 1)
    ] + [
        pl.col("close").shift(-N).alias(f"_c{N}"),
    ])

    h_cols = [f"_h{i}" for i in range(1, N + 1)]
    l_cols = [f"_l{i}" for i in range(1, N + 1)]

    h_arr = pl.concat_list(h_cols)
    l_arr = pl.concat_list(l_cols)
    close = pl.col("close")

    prefix = f"fwd{tag}"
    df = df.with_columns([
        h_arr.list.max().alias(f"{prefix}_high"),
        l_arr.list.min().alias(f"{prefix}_low"),
        (h_arr.list.arg_max() + 1).alias(f"{prefix}_high_day"),
        (l_arr.list.arg_min() + 1).alias(f"{prefix}_low_day"),
        pl.col(f"_c{N}").alias(f"{prefix}_close"),
    ])

    df = df.with_columns([
        ((pl.col(f"{prefix}_high") - close) / close * 100).alias(f"{prefix}_high_pct"),
        ((pl.col(f"{prefix}_low") - close) / close * 100).alias(f"{prefix}_low_pct"),
        ((pl.col(f"{prefix}_close") - close) / close * 100).alias(f"{prefix}_final_pct"),
    ])

    return df


FWD_PREFIX_COLS = ["high", "high_day", "high_pct", "low", "low_day", "low_pct", "close", "final_pct"]


def convert_fwd_return(
    input_dir: str = "/mnt/dataset/stock_quote_adjusted",
    output_dir: str = "/mnt/dataset/stock_fwd_return",
) -> int:
    """基于复权后数据，计算每日的未来5/10日收益率特征"""
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    parquet_files = sorted(input_path.glob("*.parquet"))
    if not parquet_files:
        raise FileNotFoundError(f"No parquet files found in {input_path}")

    keep = ["date", "code", "close"]
    for tag, N in [("5", 5), ("10", 10)]:
        keep += [f"fwd{tag}_{c}" for c in FWD_PREFIX_COLS]

    count = 0
    for pf in parquet_files:
        df = pl.read_parquet(pf).sort("date")
        df = _compute_fwd(df, 5, "5")
        df = _compute_fwd(df, 10, "10")
        df = df.select(keep)
        df.write_parquet(output_path / pf.name)
        count += 1

    print(f"Saved {count} stocks to {output_path}")
    return count


# ============== historical stats ==============

def convert_historical_stats(
    input_dir: str = "/mnt/dataset/stock_quote_adjusted",
    output_dir: str = "/mnt/dataset/stock_historical_stats",
) -> int:
    """计算股票过去1000/750/500/250/120/60/20天的最高价、最低价、收益率、当前收盘价"""
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    parquet_files = sorted(input_path.glob("*.parquet"))
    if not parquet_files:
        raise FileNotFoundError(f"No parquet files found in {input_path}")

    periods = [1000, 750, 500, 250, 120, 60, 20]

    count = 0
    for pf in parquet_files:
        df = pl.read_parquet(pf).sort("date")

        for p in periods:
            high_col = pl.col("high").rolling_max(p)
            low_col = pl.col("low").rolling_min(p)
            close_col = pl.col("close")
            close_shift = pl.col("close").shift(p - 1)

            df = df.with_columns([
                high_col.alias(f"high_{p}"),
                low_col.alias(f"low_{p}"),
                ((close_col - close_shift) / close_shift * 100).alias(f"return_{p}"),
                close_col.alias(f"close_{p}"),
            ])

        df.write_parquet(output_path / pf.name)
        count += 1

    print(f"Saved {count} stocks to {output_path}")
    return count


# ============== fund ==============

def _read_fund_shares(source_path: Path, exchange: str) -> list[pl.DataFrame]:
    """读取一个交易所的 fund_shares 数据，统一列"""
    dfs = []
    csv_files = sorted(source_path.glob("*.csv"))
    for csv_file in csv_files:
        try:
            df = pl.read_csv(csv_file, ignore_errors=True)
        except Exception:
            print(f"  Skip empty: {csv_file.name}")
            continue
        if len(df) == 0:
            continue
        df = df.with_columns(pl.col("code").cast(pl.String).str.zfill(6))
        if exchange == "sse":
            if "shares_10k" in df.columns:
                df = df.with_columns((pl.col("shares_10k") * 10000).cast(pl.Float64).alias("shares"))
        else:
            if "shares" in df.columns:
                df = df.with_columns(pl.col("shares").cast(pl.Float64))
        df = df.select(["date", "code", "name", "shares"])
        dfs.append(df)
    return dfs


def convert_fund_adjust(
    input_dir: str = "/mnt/dataset/fund_quote_history",
    output_dir: str = "/mnt/dataset/fund_quote_adjusted",
) -> int:
    """前复权：将基金历史价格按最新价格向前调整"""
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    parquet_files = sorted(input_path.glob("*.parquet"))
    if not parquet_files:
        raise FileNotFoundError(f"No parquet files found in {input_path}")

    count = 0
    for pf in parquet_files:
        df = pl.read_parquet(pf)
        df = df.sort("date", descending=True)
        df = df.with_columns(pl.col("close").shift(-1).alias("prev_day_close"))
        df = df.with_columns(
            pl.when(pl.col("prev_day_close").is_null())
            .then(1.0)
            .otherwise(pl.col("prev_close") / pl.col("prev_day_close"))
            .alias("factor"),
        )
        df = df.with_columns(
            pl.col("factor").cum_prod().shift(1).fill_null(1.0).alias("cum_factor"),
        )
        for c in PRICE_COLS:
            df = df.with_columns((pl.col(c) * pl.col("cum_factor")).alias(c))
        df = df.select(PRICE_COLS + ["date", "code"] + [c for c in df.columns if c not in PRICE_COLS and c != "date" and c != "code"])
        df = df.drop(["prev_day_close", "factor", "cum_factor"])
        df = df.sort("date")
        df.write_parquet(output_path / pf.name)
        count += 1

    print(f"Saved {count} funds to {output_path}")
    return count


def convert_index_quote(
    data_path: str = DEFAULT_DATA_PATH,
    source: str = "finance_sina",
    output_dir: str = OUTPUT_DATA_PATH,
) -> int:
    """将每日指数行情数据转换为每个指数的历史数据"""
    source_path = Path(data_path) / source / "index_quote"
    csv_files = sorted(source_path.glob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(f"No CSV files found in {source_path}")

    first_df = pl.read_csv(csv_files[0])
    std_cols = first_df.columns.copy()
    float_cols = ["prev_close", "open", "high", "low", "close", "volume", "turnover"]

    dfs = []
    for csv_file in csv_files:
        df = pl.read_csv(csv_file, ignore_errors=True)
        df = df.with_columns(pl.col("code").cast(pl.String).str.zfill(6))
        for col in float_cols:
            if col in df.columns:
                df = df.with_columns(pl.col(col).cast(pl.Float64))
        for col in std_cols:
            if col not in df.columns:
                df = df.with_columns(pl.lit(None).cast(pl.Float64).alias(col))
        df = df.select(std_cols)
        dfs.append(df)

    combined = pl.concat(dfs)
    combined = combined.sort(["code", "date"])

    output_path = Path(output_dir) / "index_quote_history"
    output_path.mkdir(parents=True, exist_ok=True)

    for code, group in combined.group_by("code"):
        code_val = code[0]
        file_path = output_path / f"{code_val}.parquet"
        group.sort("date").write_parquet(file_path)

    print(f"Saved {len(combined.unique("code"))} indices to {output_path}")
    return len(combined.unique("code"))


def convert_fund_shares(
    data_path: str = DEFAULT_DATA_PATH,
    output_dir: str = OUTPUT_DATA_PATH,
) -> int:
    """将 SSE + SZSE 基金份额数据转换为每基金历史数据"""
    output_path = Path(output_dir) / "fund_shares_history"
    output_path.mkdir(parents=True, exist_ok=True)

    all_dfs = []
    for exchange in ["sse", "szse"]:
        source_path = Path(data_path) / f"exchange_{exchange}" / "fund_shares"
        if source_path.exists():
            all_dfs.extend(_read_fund_shares(source_path, exchange))

    combined = pl.concat(all_dfs)
    combined = combined.sort(["code", "date"])

    count = 0
    for code, group in combined.group_by("code"):
        code_val = code[0]
        group = group.sort("date")
        group = group.with_columns(
            (pl.col("shares") - pl.col("shares").shift(1)).alias("share_change")
        )
        group.write_parquet(output_path / f"{code_val}.parquet")
        count += 1

    print(f"Saved {count} funds to {output_path}")
    return count


def convert_fund_quote(
    data_path: str = DEFAULT_DATA_PATH,
    source: str = "cninfo",
    output_dir: str = OUTPUT_DATA_PATH,
) -> int:
    """将基金行情数据转换为每基金历史数据"""
    source_path = Path(data_path) / source / "fund_quote"
    csv_files = sorted(source_path.glob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(f"No CSV files found in {source_path}")

    first_df = pl.read_csv(csv_files[0])
    std_cols = first_df.columns.copy()

    float_cols = ["prev_close", "open", "high", "low", "close", "volume", "turnover", "net_value", "折价率"]

    dfs = []
    for csv_file in csv_files:
        df = pl.read_csv(csv_file, ignore_errors=True)
        # 统一列名: exchange → 交易所
        if "exchange" in df.columns:
            df = df.rename({"exchange": "交易所"})
        df = df.with_columns(pl.col("code").cast(pl.String).str.zfill(6))
        for col in float_cols:
            if col in df.columns:
                df = df.with_columns(pl.col(col).cast(pl.Float64))
        for col in std_cols:
            if col not in df.columns:
                df = df.with_columns(pl.lit(None).cast(pl.Float64).alias(col))
        df = df.select(std_cols)
        dfs.append(df)

    combined = pl.concat(dfs)
    combined = combined.sort(["code", "date"])

    output_path = Path(output_dir) / "fund_quote_history"
    output_path.mkdir(parents=True, exist_ok=True)

    count = 0
    for code, group in combined.group_by("code"):
        code_val = code[0]
        group.sort("date").write_parquet(output_path / f"{code_val}.parquet")
        count += 1

    print(f"Saved {count} funds to {output_path}")
    return count


def convert_fund_flow(
    shares_dir: str = "/mnt/dataset/fund_shares_history",
    quote_dir: str = "/mnt/dataset/fund_quote_adjusted",
    output_dir: str = "/mnt/dataset/fund_flow",
) -> int:
    """结合份额变动和收盘价，估算每日加减仓金额"""
    shares_path = Path(shares_dir)
    quote_path = Path(quote_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    shares_files = {pf.stem: pf for pf in shares_path.glob("*.parquet")}
    quote_files = {pf.stem: pf for pf in quote_path.glob("*.parquet")}
    common_codes = set(shares_files) & set(quote_files)

    count = 0
    for code in sorted(common_codes):
        shares = pl.read_parquet(shares_files[code], columns=["date", "shares", "share_change"])
        quote = pl.read_parquet(quote_files[code], columns=["date", "close", "net_value"])

        merged = shares.join(quote, on="date", how="left")
        merged = merged.sort("date")

        merged = merged.with_columns([
            (pl.col("share_change") * pl.col("close")).alias("est_amount"),
        ])

        merged.write_parquet(output_path / f"{code}.parquet")
        count += 1

    print(f"Saved {count} funds to {output_path}")
    return count


# ============== fund_hs300_correlation ==============

BENCHMARK_CODE = "510300"
CORR_WINDOWS = [5, 10, 20]

# 排除的基金类型关键词
_EXCLUDE_KEYWORDS = [
    # 固收/货币
    "债", "货币", "短融", "日利", "添益", "城投", "企债", "金利", "快线",
    "财富宝", "添利", "国开", "快钱", "天金",
    # 海外
    "纳斯达克", "纳指", "标普", "恒生", "恒指", "港股", "港美", "香港",
    "HK", "H股", "中概", "美股", "海外", "日经", "德国", "法国", "英国",
    "印度", "东南亚", "日本", "越南", "韩国", "中韩", "新加坡", "欧洲",
    "金砖", "东盟", "亚太", "全球", "QDII", "沪港深", "沪港通",
    "REIT", "reits",
    # 其他非权益
    "石油LOF", "石油基金", "港医", "港高",
    # REITs (508xxx 代码)
    "安居", "高速REIT", "地产租住", "亦庄", "科投", "清能",
    "REITs", "产业园", "仓储", "物流REIT", "高速", "公路REIT",
    "有巢", "两江", "金隅", "九州通",
    # 商品
    "原油", "黄金", "白银", "豆粕", "铜", "铝", "油气", "有色ETF",
]

# REITs 代码前缀
_REIT_CODE_PREFIXES = ("508", "506")

# 关键词 → 基金类型，按优先级排序（长关键词优先匹配）
_FUND_TYPE_RULES = [
    ("沪深港300", "沪深港300"),
    ("AH300", "AH300"),
    ("HGS300", "HGS300"),
    ("创业板", "创业板"),
    ("现金流", "300现金流"),
    ("等权", "300等权"),
    ("国证2000", "国证2000"),
    ("沪深300", "沪深300"),
    ("HS300", "沪深300"),
    ("300ETF", "沪深300"),
    ("300LOF", "沪深300LOF"),
    ("沪深300LOF", "沪深300LOF"),
    ("300增强", "300增强"),
    ("300指增", "300增强"),
    ("300成长", "300成长"),
    ("300价值", "300价值"),
    ("300红利", "300红利"),
    ("300ESG", "300ESG"),
    ("成长", "成长"),
    ("价值", "价值"),
    ("增强", "增强"),
    ("指增", "增强"),
    ("红利", "红利"),
    ("ESG", "ESG"),
    ("LOF", "LOF"),
    ("证券", "证券"),
    ("银行", "银行"),
    ("军工", "军工"),
    ("医药", "医药"),
    ("消费", "消费"),
    ("科技", "科技"),
    ("芯片", "芯片"),
    ("半导体", "半导体"),
    ("新能源", "新能源"),
    ("光伏", "光伏"),
    ("汽车", "汽车"),
    ("房地产", "房地产"),
    ("有色", "有色"),
    ("煤炭", "煤炭"),
    ("钢铁", "钢铁"),
    ("石油", "石油"),
    ("养殖", "养殖"),
    ("粮食", "粮食"),
    ("科创", "科创"),
    ("50ETF", "上证50"),
    ("500ETF", "中证500"),
    ("1000ETF", "中证1000"),
    ("2000", "中证2000"),
    ("A500", "中证A500"),
    ("A50", "中证A50"),
]


def _fund_type(name: str) -> str:
    """按关键词提取基金类型"""
    for keyword, type_name in _FUND_TYPE_RULES:
        if keyword in name:
            return type_name
    return name  # 无法分类的基金，用完整名称作为类型（不会去重）


def convert_fund_hs300_correlation(
    input_dir: str,
    output_dir: str,
) -> int:
    """排除债券/货币/国外指数基金，同类型取成交额最大，计算与510300的滚动相关性（5/10/20日窗口）"""
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    for f in output_path.glob("*.parquet"):
        f.unlink()

    # 1. 加载 510300 基准收益率
    benchmark_file = input_path / f"{BENCHMARK_CODE}.parquet"
    if not benchmark_file.exists():
        print(f"Benchmark fund {BENCHMARK_CODE} not found in {input_path}")
        return 0

    benchmark = (
        pl.read_parquet(benchmark_file, columns=["date", "close"])
        .sort("date")
        .with_columns((pl.col("close") / pl.col("close").shift(1) - 1).alias("bm_return"))
        .select(["date", "bm_return"])
    )

    # 2. 筛选基金：排除债券/货币/国外指数，排除 510300 自身，日期须与基准一致，至少20个交易日
    bm_latest_date = benchmark.filter(pl.col("bm_return").is_not_null())["date"][-1]
    min_days = max(CORR_WINDOWS)
    fund_info = []
    for pf in input_path.glob("*.parquet"):
        code = pf.stem
        if code == BENCHMARK_CODE:
            continue
        try:
            df_head = pl.read_parquet(pf, columns=["name", "date", "turnover"])
            name = df_head["name"][0]
            if any(kw in name for kw in _EXCLUDE_KEYWORDS):
                continue
            if code.startswith(_REIT_CODE_PREFIXES):
                continue
            latest_date = df_head["date"][-1]
            if latest_date != bm_latest_date:
                continue
            if len(df_head) < min_days:
                continue
            latest_turnover = df_head.sort("date").tail(1)["turnover"][0]
            fund_info.append({
                "code": code, "name": name,
                "turnover": latest_turnover, "type": _fund_type(name),
            })
        except Exception:
            pass

    # 3. 同类型只取成交额最大的
    fund_df = pl.DataFrame(fund_info, orient="row")
    deduped = (
        fund_df.sort("turnover", descending=True)
        .group_by("type", maintain_order=True)
        .agg(pl.all().first())
    )
    target_codes = deduped["code"].to_list()

    for row in deduped.iter_rows(named=True):
        print(f"  {row['type']:12s} → {row['code']} {row['name']} (turnover={row['turnover']:.0f})")

    # 4. 逐基金计算滚动相关性
    count = 0
    for code in sorted(target_codes):
        df = (
            pl.read_parquet(input_path / f"{code}.parquet", columns=["date", "close"])
            .sort("date")
            .with_columns((pl.col("close") / pl.col("close").shift(1) - 1).alias("return"))
        )

        joined = df.join(benchmark, on="date", how="inner")

        corr_exprs = []
        for w in CORR_WINDOWS:
            corr_exprs.append(
                pl.rolling_corr("return", "bm_return", window_size=w).alias(f"corr_{w}")
            )

        result = joined.with_columns(corr_exprs).select(
            ["date", "return"] + [f"corr_{w}" for w in CORR_WINDOWS]
        )

        result.write_parquet(output_path / f"{code}.parquet")
        count += 1

    print(f"Saved {count} funds to {output_path}")
    return count


# ============== etf_universe ==============

# ETF 大类分类规则（按优先级，先匹配的生效；均不匹配则归「行业ETF」）
_ETF_CATEGORY_RULES = [
    # 债券ETF
    ("债", "债券ETF"),
    ("国债", "债券ETF"),
    ("国开", "债券ETF"),
    # 商品ETF
    ("黄金", "商品ETF"),
    ("原油", "商品ETF"),
    ("白银", "商品ETF"),
    ("豆粕", "商品ETF"),
    ("有色ETF", "商品ETF"),
    ("油气", "商品ETF"),
    # 境外市场ETF（港股/美股/日股等跨境，优先级在宽基前，避免恒生50等污染 A 股宽基）
    ("恒生", "境外市场ETF"), ("恒指", "境外市场ETF"), ("港股", "境外市场ETF"),
    ("港美", "境外市场ETF"), ("香港", "境外市场ETF"), ("H股", "境外市场ETF"),
    ("中概", "境外市场ETF"), ("美股", "境外市场ETF"), ("美国", "境外市场ETF"), ("海外", "境外市场ETF"),
    ("日经", "境外市场ETF"), ("纳斯达克", "境外市场ETF"), ("纳指", "境外市场ETF"),
    ("标普", "境外市场ETF"), ("德国", "境外市场ETF"), ("法国", "境外市场ETF"),
    ("英国", "境外市场ETF"), ("印度", "境外市场ETF"), ("东南亚", "境外市场ETF"),
    ("日本", "境外市场ETF"), ("越南", "境外市场ETF"), ("韩国", "境外市场ETF"),
    ("中韩", "境外市场ETF"), ("新加坡", "境外市场ETF"), ("欧洲", "境外市场ETF"),
    ("金砖", "境外市场ETF"), ("东盟", "境外市场ETF"), ("亚太", "境外市场ETF"),
    ("全球", "境外市场ETF"), ("QDII", "境外市场ETF"),
    ("沪港深", "境外市场ETF"), ("沪港通", "境外市场ETF"),
    # 宽基指数ETF（含沪深300策略变体；300 兜底覆盖沪深300简称如 510300「300ETF」）
    ("沪深300", "宽基指数ETF"),
    ("HS300", "宽基指数ETF"),
    ("上证50", "宽基指数ETF"),
    ("中证500", "宽基指数ETF"),
    ("中证1000", "宽基指数ETF"),
    ("中证2000", "宽基指数ETF"),
    ("国证2000", "宽基指数ETF"),
    ("中证800", "宽基指数ETF"),
    ("A500", "宽基指数ETF"),
    ("A50", "宽基指数ETF"),
    ("MSCI", "宽基指数ETF"),
    ("科创50", "宽基指数ETF"),
    ("科创100", "宽基指数ETF"),
    ("科创板", "宽基指数ETF"),
    ("创业板", "宽基指数ETF"),
    ("深证", "宽基指数ETF"),
    ("等权", "宽基指数ETF"),
    ("300", "宽基指数ETF"),
    # 核心宽基简称（510050「50ETF」/510500「500ETF」等，无前缀的招牌简称）
    ("50ETF", "宽基指数ETF"),
    ("500ETF", "宽基指数ETF"),
]

_ETF_DEFAULT_CATEGORY = "行业ETF"

# 行业/主题关键词（用于宽基回判：宽基前缀 + 行业后缀时降级为行业ETF，如「创业板新能源」）
_ETF_INDUSTRY_KEYWORDS = [
    "消费", "医药", "军工", "新能源", "芯片", "半导体", "光伏",
    "汽车", "房地产", "煤炭", "钢铁", "养殖", "粮食", "银行",
    "证券", "化工", "农业", "人工智能", "机器人", "锂电", "环保",
    "传媒", "旅游", "基建", "建材", "机械", "电力", "通信",
    "计算机", "电子", "食品饮料", "白酒", "家电", "有色",
]


def _etf_category(name: str) -> str:
    """按名称关键词判断 ETF 大类，无匹配归「行业ETF」。
    宽基命中后回判：若同时含行业词（如「创业板新能源」），降级为行业ETF。"""
    for keyword, category in _ETF_CATEGORY_RULES:
        if keyword in name:
            if category == "宽基指数ETF" and any(kw in name for kw in _ETF_INDUSTRY_KEYWORDS):
                return _ETF_DEFAULT_CATEGORY
            return category
    return _ETF_DEFAULT_CATEGORY


# 行业子类规则（优先匹配：保证「创业板新能源」→新能源 而非创业板；具体词前置）
_ETF_INDUSTRY_SUB_RULES = [
    ("消费电子", "消费电子"),
    ("食品饮料", "食品饮料"), ("白酒", "白酒"), ("家电", "家电"), ("消费", "消费"),
    ("创新药", "创新药"), ("生物医药", "生物医药"), ("医疗器械", "医疗器械"),
    ("医疗", "医疗"), ("医药", "医药"),
    ("券商", "证券"), ("证券", "证券"), ("保险", "保险"), ("银行", "银行"), ("金融", "金融"),
    ("国防", "军工"), ("军工", "军工"),
    ("新能源车", "新能源车"), ("新能源汽车", "新能源车"),
    ("光伏", "光伏"), ("锂电", "锂电池"), ("电池", "锂电池"), ("新能源", "新能源"),
    ("汽车", "汽车"),
    ("芯片", "芯片"), ("半导体", "半导体"),
    ("人工智能", "人工智能"), ("机器人", "机器人"), ("云计算", "云计算"),
    ("大数据", "大数据"), ("计算机", "计算机"), ("通信", "通信"), ("5G", "通信"),
    ("传媒", "传媒"), ("游戏", "游戏"), ("影视", "影视"),
    ("煤炭", "煤炭"), ("钢铁", "钢铁"), ("稀土", "稀土"),
    ("有色金属", "有色金属"), ("有色", "有色金属"), ("化工", "化工"), ("石油", "石油"),
    ("房地产", "房地产"), ("地产", "房地产"),
    ("基建", "基建"), ("建材", "建材"), ("建筑", "建筑"),
    ("机械", "机械"), ("绿电", "绿电"), ("电力", "电力"), ("环保", "环保"),
    ("农业", "农业"), ("养殖", "养殖"), ("粮食", "粮食"), ("种业", "种业"),
    ("旅游", "旅游"), ("物流", "物流"), ("交运", "交通运输"),
]

# 宽基子类规则（行业不匹配时再用；顺序敏感：风格变体→沪深300全称→非沪深300排除→300ETF简称）
_ETF_BROADBASED_SUB_RULES = [
    ("沪深港300", "沪深港300"), ("HGS300", "沪深港300"), ("AH300", "AH300"),
    # 沪深300 风格变体（先于全称、先于排除、先于简称）
    ("300现金流", "300现金流"), ("300等权", "300等权"),
    ("300增强", "300增强"), ("300指增", "300增强"), ("300ETF增", "300增强"),
    ("300成长", "300成长"), ("300价值", "300价值"),
    ("300红利", "300红利"),
    # 沪深300 全称（必须在「深300」前——「沪深300」含子串「深300」）
    ("沪深300LOF", "沪深300"), ("沪深300", "沪深300"), ("HS300", "沪深300"),
    # 非沪深300的 300 指数（排除，各自独立子类）
    ("民企300", "民企300"), ("ESG300", "ESG300"),
    ("创300", "创业板300"), ("中小300", "中小300"), ("深300", "深证300"),
    # 沪深300 简称（排除后，避免创300ETF/深300ETF 误匹配）
    ("300LOF", "沪深300"), ("300ETF", "沪深300"),
    ("中证800", "中证800"),
    # A500族（增强/红利低波变体各自子类）
    ("A500增强", "A500增强"), ("A500红利低波", "A500红利低波"),
    ("A500", "中证A500"), ("A50", "中证A50"), ("MSCI", "MSCI中国A50"),
    ("上证50", "上证50"),
    ("中证500", "中证500"), ("500ETF", "中证500"),
    ("中证1000", "中证1000"), ("1000ETF", "中证1000"),
    ("国证2000", "国证2000"), ("中证2000", "中证2000"),
    ("科创50", "科创50"), ("科创100", "科创100"), ("科创板", "科创板"),
    ("创业板50", "创业板50"), ("创50", "创业板50"),
    ("创业板", "创业板"), ("深证", "深证"),
    # 不设「50ETF」简称兜底：「XX50ETF」是海量主题ETF命名（软件50/TMT50/美国50），
    # 无法与上证50区分；510050「50ETF」等简称 sub=None（category 仍为宽基）
]


def _etf_subcategory(name: str) -> str | None:
    """行业子类优先（保证「创业板新能源」→新能源），其次宽基子类，无匹配返回 None"""
    for kw, sub in _ETF_INDUSTRY_SUB_RULES:
        if kw in name:
            return sub
    for kw, sub in _ETF_BROADBASED_SUB_RULES:
        if kw in name:
            return sub
    return None


def convert_etf_universe(
    input_dir: str,
    output_dir: str,
) -> int:
    """从基金行情数据中筛出 ETF（名称含 ETF），按名称关键词分为宽基指数/行业/商品/债券/境外市场五类，
    并给宽基与行业 ETF 标注子分类，输出范围清单"""
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    for f in output_path.glob("*.parquet"):
        f.unlink()

    rows = []
    for pf in sorted(input_path.glob("*.parquet")):
        try:
            name = pl.read_parquet(pf, columns=["name"])["name"][0]
        except Exception:
            continue
        if "ETF" not in name:
            continue
        cat = _etf_category(name)
        sub = _etf_subcategory(name) if cat in ("宽基指数ETF", "行业ETF") else None
        rows.append({"code": pf.stem, "name": name, "category": cat, "subcategory": sub})

    if not rows:
        print(f"No ETF found in {input_path}")
        return 0

    result = pl.DataFrame(rows, orient="row")
    result.write_parquet(output_path / "etf_universe.parquet")

    for row in result.group_by("category").len().sort("category").iter_rows(named=True):
        print(f"  {row['category']:12s} → {row['len']}")

    multi = (result.filter(pl.col("subcategory").is_not_null())
             .group_by("subcategory").len().filter(pl.col("len") >= 2)
             .sort("len", descending=True))
    print(f"  细分子类（成员≥2）共 {len(multi)} 个:")
    for row in multi.iter_rows(named=True):
        print(f"    {row['subcategory']:10s} → {row['len']}")
    print(f"Saved {len(rows)} ETFs to {output_path / 'etf_universe.parquet'}")
    return len(rows)


# ============== industry_profit ==============

# XLSX 命名空间
_XLSX_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _load_cumulative(path: Path, indicator_prefix: str) -> dict[int, float]:
    r"""读一个年文件，返回 {month: 累计值}。

    支持 CSV（第 1 行表头）和 XLSX（前 2 行元数据，第 3 行表头）。
    月份列顺序乱序，按列名 `(\d+)月` 提取月份后映射。
    """
    if path.suffix.lower() == ".csv":
        return _load_cumulative_csv(path, indicator_prefix)
    return _load_cumulative_xlsx(path, indicator_prefix)


def _load_cumulative_csv(path: Path, indicator_prefix: str) -> dict[int, float]:
    with open(path, encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        month_by_col: dict[int, int] = {}
        for col_idx, name in enumerate(header[1:], start=1):
            m = re.search(r"(\d+)月", name)
            if m:
                month_by_col[col_idx] = int(m.group(1))
        for row in reader:
            if not row or not row[0].strip().startswith(indicator_prefix):
                continue
            return _row_to_cum(row, month_by_col)
    return {}


def _load_cumulative_xlsx(path: Path, indicator_prefix: str) -> dict[int, float]:
    with zipfile.ZipFile(path) as z:
        strings = re.findall(
            r"<t[^>]*>([^<]*)</t>",
            z.read("xl/sharedStrings.xml").decode("utf-8"),
        )
        root = ET.fromstring(z.read("xl/worksheets/sheet1.xml").decode("utf-8"))

    def cell_text(cell):
        v = cell.find(f"{_XLSX_NS}v")
        if v is None:
            return ""
        t = cell.attrib.get("t")
        if t == "s":
            return strings[int(v.text)]
        return v.text or ""

    header_row = None
    for row in root.iter(f"{_XLSX_NS}row"):
        first_text = cell_text(list(row)[0]) if list(row) else ""
        if first_text == "指标":
            header_row = row
            break
    if header_row is None:
        return {}

    cells = list(header_row)
    month_by_col: dict[int, int] = {}
    for col_idx, cell in enumerate(cells[1:], start=1):
        m = re.search(r"(\d+)月", cell_text(cell))
        if m:
            month_by_col[col_idx] = int(m.group(1))

    for row in root.iter(f"{_XLSX_NS}row"):
        cells = list(row)
        if not cells:
            continue
        if cell_text(cells[0]).strip().startswith(indicator_prefix):
            return _row_to_cum([cell_text(c) for c in cells], month_by_col)
    return {}


def _row_to_cum(values: list[str], month_by_col: dict[int, int]) -> dict[int, float]:
    cum: dict[int, float] = {}
    for col_idx, month in month_by_col.items():
        if col_idx >= len(values):
            continue
        raw = (values[col_idx] or "").strip()
        if not raw:
            continue
        try:
            cum[month] = float(raw)
        except ValueError:
            continue
    return cum


def _cumulative_to_monthly(cum: dict[int, float]) -> dict[int, float | None]:
    """相邻已知累计点之间均摊差额。

    锚点 cum[0]=0；对每个已知月 m：区间 (prev_m, m] 共 gap=m-prev_m 个月，
    每个月 profit = (cum[m] - prev_cum) / gap。
    最后一个已知月之后的月份返回 None。
    """
    profit: dict[int, float | None] = {m: None for m in range(1, 13)}
    months_known = sorted(cum.keys())
    prev_m, prev_cum = 0, 0.0
    for m in months_known:
        gap = m - prev_m
        if gap <= 0:
            continue
        per_month = (cum[m] - prev_cum) / gap
        for mm in range(prev_m + 1, m + 1):
            profit[mm] = per_month
        prev_m, prev_cum = m, cum[m]
    return profit


def convert_industry_profit(data_path: str, output_dir: str) -> int:
    """将工业企业利润累计值转换为每月当月利润总额，每年一个 CSV。

    - 满数据年（gap=1）：精确差分。
    - 稀疏年 2007–2009（仅 2/5/8/11 月）：3–11 月为等额估计值，12 月空。
    - 2010 从 2011 文件的「上年同期累计值」重建（新口径，2–12 月齐全，精确）。
    - 2026 当前仅有 2/3/4 月：1–4 月有值，5–12 月空。
    """
    src_path = Path(data_path) / "gov_stats" / "工业企业指标"
    output_path = Path(output_dir) / "gov_stat" / "industry_profit"
    output_path.mkdir(parents=True, exist_ok=True)

    count = 0
    for year in range(2000, 2027):
        if year == 2010:
            src_year, prefix = 2011, "利润总额上年同期累计值"
        else:
            src_year, prefix = year, "利润总额累计值"

        src_file = src_path / f"{src_year}.csv"
        if not src_file.exists():
            src_file = src_path / f"{src_year}.xlsx"
        if not src_file.exists():
            print(f"  跳过 {year}：找不到源文件 {src_year}")
            continue

        cum = _load_cumulative(src_file, prefix)
        if not cum:
            print(f"  跳过 {year}：{src_file.name} 未找到 {prefix}")
            continue

        profit = _cumulative_to_monthly(cum)
        df = pl.DataFrame({
            "year": [year] * 12,
            "month": list(range(1, 13)),
            "profit": [profit[m] for m in range(1, 13)],
        })
        df.write_csv(output_path / f"{year}.csv")
        count += 1

    print(f"Saved {count} yearly files to {output_path}")
    return count


# ============== pbc（央行统计数据）==============

# 文件格式优先级：有电子表格就不用 htm（用户要求）
_PBC_EXT_PRIORITY = [".xlsx", ".xls", ".htm"]


class _PbcHtmlTableParser(HTMLParser):
    """从 Excel 导出的 HTML 中提取所有 <table> 的单元格文本。"""

    def __init__(self):
        super().__init__()
        self._in_table = False
        self._in_tr = False
        self._in_td = False
        self.tables: list[list[list[str]]] = []
        self._cur_table: list[list[str]] = []
        self._cur_row: list[str] = []
        self._cur_cell: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._in_table = True
            self._cur_table = []
        elif tag == "tr" and self._in_table:
            self._in_tr = True
            self._cur_row = []
        elif tag in ("td", "th") and self._in_tr:
            self._in_td = True
            self._cur_cell = []

    def handle_endtag(self, tag):
        if tag == "table":
            self._in_table = False
            if self._cur_table:
                self.tables.append(self._cur_table)
            self._cur_table = []
        elif tag == "tr" and self._in_tr:
            self._in_tr = False
            if self._cur_row:
                self._cur_table.append(self._cur_row)
            self._cur_row = []
        elif tag in ("td", "th") and self._in_td:
            self._in_td = False
            self._cur_row.append("".join(self._cur_cell).strip())
            self._cur_cell = []

    def handle_data(self, data):
        if self._in_td:
            self._cur_cell.append(data)


def _pbc_read_htm(path: Path) -> list[list[str]]:
    """读 Excel 导出的 HTML，返回第一个非空表格（二维字符串数组）。
    编码 utf-8/gbk 混用，依次尝试。"""
    raw = path.read_bytes()
    text = None
    for enc in ("utf-8", "gbk", "gb18030"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = raw.decode("utf-8", errors="ignore")
    parser = _PbcHtmlTableParser()
    parser.feed(text)
    for table in parser.tables:
        if any(any(cell for cell in row) for row in table):
            return table
    return []


def _pbc_read_sheet(path: Path) -> list[list[str]]:
    """统一读取 .htm/.xls/.xlsx → 二维字符串数组。"""
    if path.suffix.lower() == ".htm":
        return _pbc_read_htm(path)
    wb = CalamineWorkbook.from_path(str(path))
    ws = wb.get_sheet_by_index(0)
    return [["" if c is None else str(c) for c in row] for row in ws.to_python()]


def _pbc_find_file(year_dir: Path, subdirs: list[str], keywords: list[str],
                   exclude: tuple[str, ...] = ()) -> Path | None:
    """在 year_dir/{subdir}（按顺序）或 year_dir 根下查找文件。
    优先级 .xlsx > .xls > .htm。匹配：文件名 stem 以某个 keyword 开头，
    且不含 exclude 中的子串。兼容早期年份文件直接在根目录的情况。"""
    search_dirs = [year_dir / sd for sd in subdirs] + [year_dir]
    for sd in search_dirs:
        if not sd.is_dir():
            continue
        for ext in _PBC_EXT_PRIORITY:
            for entry in sorted(sd.iterdir()):
                if entry.suffix.lower() != ext or not entry.is_file():
                    continue
                base = entry.stem
                if any(x in base for x in exclude):
                    continue
                if any(base.startswith(kw) for kw in keywords):
                    return entry
    return None


def _pbc_to_float(v) -> float | None:
    if v is None:
        return None
    s = str(v).strip()
    if s in ("", "--", "…", "—", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


# 项目名清洗：去全角空白、折叠空白、去尾部英文翻译、去中文序号前缀
# 尾部英文 = 「空格+字母」或「右括号+字母」开头直到行尾（央行项目名都是
# 「中文 English」格式；M0/M1/M2 在全角括号内、括号后无内容，不会被误删）
_PBC_EN_TAIL = re.compile(r"(?:\s+|(?<=[）)]))[A-Za-z].*$")
_PBC_CN_PREFIX = re.compile(r"^[一二三四五六七八九十]+、")

# 信贷收支表 / 资产负债表的层级前缀（消歧用）：
#   一、/二、 …     顶级分项（来源/运用方），出现即重置层级上下文
#   （一）/（二） … 子段（境内/境外），同上
#   1./2. …        分组父项（住户存款、企（事）业单位贷款 …）
#   （1）/（2） …   分组下的子项（活期存款、短期贷款 …），跨分组重名
#   其中：…         上级行的「其中」明细（资产负债表：对政府债权/政府存款下均有「其中：中央政府」）
_PBC_TOP_SECTION = re.compile(r"^[一二三四五六七八九十]+、")
_PBC_SUB_SECTION = re.compile(r"^[（(][一二三四五六七八九十]+[）)]")
_PBC_GROUP_PARENT = re.compile(r"^(\d+)\.\s*(.*)$")
_PBC_GROUP_CHILD = re.compile(r"^[（(](\d+)[）)]\s*(.*)$")


def _pbc_norm_item(raw) -> str:
    if not raw:
        return ""
    s = str(raw).replace("　", " ").replace("\n", " ").replace("\r", " ")
    s = re.sub(r"\s+", " ", s).strip()
    # 反复去尾部英文（应对中英交替）
    prev = None
    while prev != s:
        prev = s
        s = _PBC_EN_TAIL.sub("", s).strip()
    s = _PBC_CN_PREFIX.sub("", s).strip()
    return s


def _pbc_is_item_header_cell(s) -> bool:
    """表头中项目列单元格（应跳过，不是月份/数据）。"""
    if s is None:
        return True
    t = str(s).strip()
    if t == "":
        return True
    return "项目" in t or t.lower().startswith("item")


def _pbc_period_to_date(header_text, year: int, col_pos: int) -> str | None:
    """把表头单元格（如 '2015.Q1' / 2024.01 / '2024.10'）转成 'YYYY-MM'。
    季度表头（含 Q）→ 季末月；否则按 col_pos 推断月份（不依赖浮点数值，
    因为 Excel 会把 2024.10 截断为 2024.1）。"""
    s = str(header_text).strip()
    if "Q" in s.upper():
        qm = {1: "03", 2: "06", 3: "09", 4: "12"}
        return f"{year}-{qm[col_pos]}" if col_pos in qm else None
    if 1 <= col_pos <= 12:
        return f"{year}-{col_pos:02d}"
    return None


def _pbc_parse_period_str(s) -> tuple[int, int] | None:
    """解析月份字符串 '2024.01' / '2024.10' / '2024-Q1' → (year, month)。
    按字符串解析（'10' 不会被截断）。"""
    s = str(s).strip().replace("．", ".").replace("。", ".")
    qm = re.match(r"(\d{4})[.\-\s]?Q?([1-4])$", s, re.IGNORECASE)
    if qm:
        return int(qm.group(1)), {1: 3, 2: 6, 3: 9, 4: 12}[int(qm.group(2))]
    m = re.match(r"(\d{4})[.\-\s年]+(\d{1,2})", s)
    if m:
        mo = int(m.group(2))
        if 1 <= mo <= 12:
            return int(m.group(1)), mo
    return None


def _pbc_find_header_row(rows: list[list[str]]) -> int | None:
    """定位表头行：前两列含「项目」或「报表项目」的行。"""
    for i, r in enumerate(rows):
        if not r:
            continue
        head = " ".join(str(c) for c in r[:2])
        if "项目" in head:
            return i
    return None


def _pbc_row_is_note(name: str) -> bool:
    n = str(name)
    return n.startswith("注") or "注：" in n or "注:" in n or n.lower().startswith("note")


def _pbc_parse_wide_months(rows: list[list[str]], year: int,
                           disambiguate: bool = False) -> list[tuple[str, str, float]]:
    """解析「项目在行、月份在列」的宽表。
    返回 [(date, item_norm, value), ...]，跳过空值和注释行。

    用「行内数字序列」法：每行的项目名 = 第一个非空非数字单元格，
    数据值 = 该行其余数字单元格（按列顺序）。月份由表头数据列按位置推断
    （不依赖浮点数值，因 Excel 会把 2024.10 截断为 2024.1）。这能兼容
    货币供应量表 M1/M0 因层级缩进把项目名放在数据列位置的情况。

    disambiguate=True 时按层级前缀给同名子项补父级上下文（用「·」拼接），
    消除跨分组重名导致的重复：
      （1）活期存款      → 住户存款·（1）活期存款 / 非金融企业存款·（1）活期存款
      消费贷款（裸项）   → 住户贷款·短期贷款·消费贷款 / 住户贷款·中长期贷款·消费贷款
      其中：中央政府     → 对政府债权·其中：中央政府 / 政府存款·其中：中央政府
    顶级分项（一、/（一））、分组父项（1.）保持原名；货币供应量等无层级表不受影响。"""
    header_idx = _pbc_find_header_row(rows)
    if header_idx is None:
        return []
    header = rows[header_idx]
    # 表头月份序列（按数据列位置 → 1..12 月或季末月）
    month_dates: list[str] = []
    for cell in header:
        if _pbc_is_item_header_cell(cell):
            continue
        date = _pbc_period_to_date(cell, year, len(month_dates) + 1)
        if date:
            month_dates.append(date)
    if not month_dates:
        return []

    out: list[tuple[str, str, float]] = []
    cur_group = None   # 最近分组父项标签，如「住户存款」（来自 1./2. 行）
    cur_inter = None   # 最近分组子项标签，如「短期贷款」（来自 （1）行），裸项的父
    cur_parent = None  # 最近非「其中」行，作为「其中：」明细的父级
    for r in rows[header_idx + 1:]:
        if not r:
            continue
        name = ""
        raw_cell = None
        nums: list[float] = []
        for c in r:
            if c is None or str(c).strip() == "":
                continue
            v = _pbc_to_float(c)
            if v is not None:
                nums.append(v)
            elif not name:
                cand = _pbc_norm_item(c)
                if cand:
                    name = cand
                    raw_cell = c
        if not name:
            continue
        if _pbc_row_is_note(name):
            break
        qname = _pbc_qualify_item(name, raw_cell, disambiguate,
                                  cur_group, cur_inter, cur_parent)
        # 更新层级上下文：按本行在层级中的位置推进
        if disambiguate:
            top = raw_cell is not None and bool(
                _PBC_TOP_SECTION.match(str(raw_cell).lstrip().replace("　", " ")))
            mg = _PBC_GROUP_PARENT.match(name)
            ms = _PBC_SUB_SECTION.match(name)
            mi = _PBC_GROUP_CHILD.match(name)
            if top or ms:
                cur_group = None
                cur_inter = None
                cur_parent = name
            elif mg:
                cur_group = mg.group(2).strip()
                cur_inter = None
                cur_parent = name
            elif mi:
                cur_inter = mi.group(2).strip()
                cur_parent = name
            elif not name.startswith("其中"):
                # 裸项：作为后续「其中」的潜在父级，但不改 cur_group/cur_inter
                cur_parent = name
        for date, v in zip(month_dates, nums):
            out.append((date, qname, v))
    return out


def _pbc_qualify_item(name: str, raw_cell, disambiguate: bool,
                      cur_group, cur_inter, cur_parent) -> str:
    """按层级上下文给 item 名补父级前缀（disambiguate=True 时）。否则原样返回。"""
    if not disambiguate:
        return name
    # 顶级行保持原名，绝不补父级：
    #   - 分组父项（1./2./3.…）：住户存款、非金融企业存款、机关团体存款 … 互为兄弟，
    #     不能因为前一行是「1.住户存款」就把「2.非金融企业存款」当成它的子项。
    #   - 子段（（一）/（二）…）：境内存款/境内贷款 等。
    #   - 章节标题（一、/二、…）：被 _pbc_norm_item 剥掉前缀，故用 raw_cell 判定。
    if _PBC_GROUP_PARENT.match(name) or _PBC_SUB_SECTION.match(name):
        return name
    if raw_cell is not None:
        s = str(raw_cell).lstrip().replace("　", " ")
        if _PBC_TOP_SECTION.match(s):
            return name
    mi = _PBC_GROUP_CHILD.match(name)
    if mi:
        return f"{cur_group}·{name}" if cur_group else name
    if name.startswith("其中"):
        return f"{cur_parent}·{name}" if cur_parent else name
    # 裸项：直接挂在分组下时用 cur_group，挂在 （N）子项下时再叠一层 cur_inter
    if cur_inter and cur_group:
        return f"{cur_group}·{cur_inter}·{name}"
    if cur_inter:
        return f"{cur_inter}·{name}"
    if cur_group:
        return f"{cur_group}·{name}"
    return name


_PBC_FLOW_NOISE = re.compile(r"^(Unit|Chart|Month|Item|项目|单位)", re.IGNORECASE)


def _pbc_flow_table_unit(rows: list[list[str]], header_idx: int) -> str:
    """从表头行向上找最近的「单位：/Unit:」标记，判断该表是增量(亿)还是占比(%)。"""
    for k in range(header_idx - 1, -1, -1):
        r = rows[k]
        cv = _pbc_norm_item(r[0]) if r and r[0] else ""
        if cv.startswith("单位") or cv.lower().startswith("unit"):
            return "%" if "%" in cv else "亿"
        if cv.startswith("表") or cv == "月份":
            break
    return "亿"


def _pbc_parse_flow_long(rows: list[list[str]]) -> list[tuple[str, str, float]]:
    """解析社融增量长表：月份在第 1 列（行），分项在表头列。
    返回 [(date, item, value), ...]。

    单个 .xls/.htm 常把多张表堆在一个 sheet 里（如 2019 年：主增量表 + 表1 完善后
    增量表 + 表2 占比表），这里按表头「月份」拆表，并：
      - 用归一化 c0=='月份' 定位表头（避开早期合并单元格「项目\\n月份」）；
      - 表头出现「其中」时按两行表头合并（第二行才是真正分项名）；
      - 向上查「单位：」标记，剔除占比(%)表；
      - 数据区遇「注：/表N：/新月份表头」即停，绝不跨表混读。"""
    n = len(rows)
    out: list[tuple[str, str, float]] = []
    i = 0
    while i < n:
        r = rows[i]
        if not (r and r[0] and _pbc_norm_item(r[0]) == "月份"):
            i += 1
            continue
        header = r
        two_row = i + 1 < n and any(_pbc_norm_item(header[j]) == "其中"
                                    for j in range(1, len(header)))
        second = rows[i + 1] if two_row else None
        item_cols: list[tuple[int, str]] = []
        for j in range(1, len(header)):
            v = _pbc_norm_item(header[j])
            if v in ("", "其中"):
                if second and j < len(second):
                    v2 = _pbc_norm_item(second[j])
                    v = v2 if (v2 and v2 != "其中") else ""
                else:
                    v = ""
            if v and not _pbc_is_item_header_cell(v):
                item_cols.append((j, v))
        is_ratio = _pbc_flow_table_unit(rows, i) == "%"
        start = i + 2 if two_row else i + 1
        for rr in rows[start:]:
            if not rr:
                continue
            c0 = str(rr[0]).strip()
            if not c0:
                continue
            parsed = _pbc_parse_period_str(rr[0])
            if parsed is None:
                nv = _pbc_norm_item(rr[0])
                # 英文翻译/单位/Chart 等噪声行跳过；表/注/新表头 → 本表结束
                if (nv.startswith("表") or nv.startswith("注") or nv == "月份"
                        or not _PBC_FLOW_NOISE.match(nv)):
                    break
                continue
            if is_ratio:
                continue
            date = f"{parsed[0]:04d}-{parsed[1]:02d}"
            for j, item in item_cols:
                val = _pbc_to_float(rr[j]) if j < len(rr) else None
                if val is not None:
                    out.append((date, item, val))
        i += 1
    return out


def _pbc_parse_stock_table(rows: list[list[str]], year: int) -> list[tuple[str, str, float, float]]:
    """解析社融存量表：月份在列且每月份占 2 列（存量+增速）。
    返回 [(date, item, stock, growth_rate), ...]。"""
    hidx = _pbc_find_header_row(rows)
    if hidx is None or hidx == 0:
        return []
    month_row = rows[hidx - 1]
    # 月份单元格在数据列；每月份后跟一个增速列
    pairs: list[tuple[int, int, str]] = []
    pos = 0
    for j in range(len(month_row)):
        c = month_row[j]
        if _pbc_is_item_header_cell(c):
            continue
        pos += 1
        date = _pbc_period_to_date(c, year, pos)
        if date is None:
            continue
        pairs.append((j, j + 1, date))  # (stock_col, growth_col, date)
    out = []
    for r in rows[hidx + 1:]:
        if not r:
            continue
        name = _pbc_norm_item(r[0])
        if not name:
            continue
        if _pbc_row_is_note(name):
            break
        for sc, gc, date in pairs:
            stock = _pbc_to_float(r[sc]) if sc < len(r) else None
            growth = _pbc_to_float(r[gc]) if gc < len(r) else None
            if stock is None and growth is None:
                continue
            out.append((date, name, stock, growth))
    return out


# M0/M1/M2 项目名历史变体（归一化到 m0/m1/m2）
_MS_ALIASES = {
    "m2": ["货币和准货币（M2）", "货币和准货币(M2)", "货币和准货币"],
    "m1": ["货币（M1）", "货币(M1)", "货币"],
    "m0": ["流通中现金（M0）", "流通中货币（M0）", "流通中现金(M0)", "流通中货币(M0)",
           "流通中现金", "流通中货币"],
}

# 住户活期存款的历史命名变体（用于 m1_new 计算）：
#   1999-01..2006-12  活期储蓄（旧分类）
#   2007-01..2010-12  储蓄存款·(1)活期储蓄
#   2015-01..2022-12  住户存款·（1）住户活期存款
#   2023-01..         住户存款·（1）活期存款
# 2011-2014 信贷表把个人存款按总额披露（个人存款·储蓄存款），未拆活期/定期，故无数据。
_HOUSEHOLD_DEMAND_DEPOSIT_ITEMS = [
    "活期储蓄",
    "储蓄存款·(1)活期储蓄",
    "住户存款·（1）住户活期存款",
    "住户存款·（1）活期存款",
]


def _pbc_parse_m1_backfill_2024(rows: list[list]) -> dict[str, float]:
    """从 2025 年货币供应量文件解析 M1 新口径 2024 年回填数据。

    央行自 2025-01 起改 M1 口径（新增个人活期存款、非银支付机构客户备付金），
    并在 2025 年文件末尾的注释块里官方回填了 2024 全年新口径 M1。

    文件结构：注释行（含「按可比口径回溯」）→ 月份行（2024.01..2024.12，
    10 月被 Excel 截断为 2024.1，按列位置回退）→ 余额行（数字）。
    返回 {'2024-01': m1_new_亿元, ...}，找不到返回 {}。
    """
    note_idx = None
    for i, r in enumerate(rows):
        for c in r:
            if c and "按可比口径" in str(c):
                note_idx = i
                break
        if note_idx is not None:
            break
    if note_idx is None:
        return {}

    months_idx = None
    for i in range(note_idx + 1, min(note_idx + 6, len(rows))):
        r = rows[i]
        for c in r:
            if c and re.match(r"^2024[\.\s]0?1$", str(c).strip()):
                months_idx = i
                break
        if months_idx is not None:
            break
    if months_idx is None:
        return {}

    months_row = rows[months_idx]
    month_cols: list[tuple[int, str]] = []
    for j, c in enumerate(months_row):
        if not c:
            continue
        d = _pbc_period_to_date(str(c), 2024, len(month_cols) + 1)
        if d:
            month_cols.append((j, d))

    balance_idx = None
    for i in range(months_idx + 1, min(months_idx + 6, len(rows))):
        r = rows[i]
        if all(j < len(r) and _pbc_to_float(r[j]) is not None for j, _ in month_cols):
            balance_idx = i
            break
    if balance_idx is None:
        return {}

    result: dict[str, float] = {}
    balance_row = rows[balance_idx]
    for j, d in month_cols:
        v = _pbc_to_float(balance_row[j]) if j < len(balance_row) else None
        if v is not None:
            result[d] = v
    return result


def _pbc_load_household_demand(credit_funds_csv: Path) -> dict[str, float]:
    """从 credit_funds.csv 读住户活期存款（人民币），合并 4 个历史命名变体。

    返回 {'YYYY-MM': 住户活期_亿元}。覆盖 1999-2006 / 2007-2010 / 2015-2026，
    2011-2014 信贷表未拆住户活期，无对应 key。
    """
    df = (pl.read_csv(credit_funds_csv)
            .filter((pl.col("currency") == "人民币")
                    & pl.col("item").is_in(_HOUSEHOLD_DEMAND_DEPOSIT_ITEMS))
            .with_columns(pl.col("date").str.to_date("%Y-%m"))
            .group_by("date").agg(pl.col("value").sum())
            .sort("date"))
    return {r["date"].strftime("%Y-%m"): r["value"] for r in df.iter_rows(named=True)}


def _pbc_alias_map(aliases: dict[str, list[str]]) -> dict[str, str]:
    m = {}
    for canonical, alts in aliases.items():
        for a in alts:
            m[a] = canonical
    return m


# 社融分项跨年命名变体（早期口径 vs 现代口径）
_SF_FLOW_ALIASES = {
    "社会融资规模增量": ["社会融资规模增量", "社会融资规模", "社会融资规模当月增量"],
    "人民币贷款": ["人民币贷款", "其中:人民币贷款", "其中：人民币贷款"],
    "外币贷款（折合人民币）": ["外币贷款（折合人民币）", "外币贷款（折合人民币)"],
}
_SF_STOCK_ALIASES = {
    "社会融资规模存量": ["社会融资规模存量"],
    "人民币贷款": ["人民币贷款", "其中:人民币贷款", "其中：人民币贷款"],
}


def convert_pbc_money_supply(data_path: str, output_dir: str,
                             credit_funds_csv: str) -> int:
    """央行货币供应量 M0/M1/M2 月度数据（亿元），宽表 date/m0/m1/m1_new/m2。
    源：gov_pbc/{year}/[货币统计概览/]货币供应量[表].{htm,xls,xlsx}，2004 起。

    **m1_new 列**（新口径 M1，消除 2025-01 的口径断点）：
      - 2025-01+  : m1 本身已是新口径（含个人活期存款、非银支付备付金）
      - 2024      : 央行 2025 文件官方回填的新口径值（精确）
      - 其余年份  : 旧 m1 + 住户活期存款（credit_funds），近似新口径
                    精度经 2024 官方回填交叉验证，差额稳定在 +2.5%（即非银
                    支付机构客户备付金，本数据集无法单独获取）
      - 2011-2014 : 信贷表未拆住户活期，m1_new 留空

    credit_funds_csv 必须先于本命令生成（用于补住户活期存款）。
    """
    src_root = Path(data_path) / "gov_pbc"
    out_path = Path(output_dir) / "pbc"
    out_path.mkdir(parents=True, exist_ok=True)

    alias_map = _pbc_alias_map(_MS_ALIASES)
    grid: dict[str, dict[str, float]] = {}
    backfill_2024: dict[str, float] = {}

    for year in range(2004, 2027):
        yd = src_root / str(year)
        if not yd.is_dir():
            continue
        fp = _pbc_find_file(yd, ["货币统计概览"], ["货币供应量"])
        if fp is None:
            print(f"  跳过 {year}：找不到货币供应量表")
            continue
        try:
            rows = _pbc_read_sheet(fp)
            records = _pbc_parse_wide_months(rows, year)
        except Exception as e:
            print(f"  跳过 {year}：解析失败 {e}")
            continue
        for date, item, val in records:
            key = alias_map.get(item)
            if key is None:
                continue
            grid.setdefault(date, {})[key] = val
        # 2025 文件额外解析 M1 新口径 2024 回填
        if year == 2025:
            backfill_2024 = _pbc_parse_m1_backfill_2024(rows)
            if not backfill_2024:
                print("  警告：2025 文件未找到 M1 新口径 2024 回填段")

    hh_map = _pbc_load_household_demand(Path(credit_funds_csv))

    dates = sorted(grid)
    m1_new_list: list[float | None] = []
    for d in dates:
        year = int(d[:4])
        if year >= 2025:
            v = grid[d].get("m1")
        elif year == 2024:
            v = backfill_2024.get(d)
        else:
            m1_old = grid[d].get("m1")
            hh_v = hh_map.get(d)
            v = (m1_old + hh_v) if (m1_old is not None and hh_v is not None) else None
        m1_new_list.append(v)

    df = pl.DataFrame({
        "date": dates,
        "m0": [grid[d].get("m0") for d in dates],
        "m1": [grid[d].get("m1") for d in dates],
        "m1_new": m1_new_list,
        "m2": [grid[d].get("m2") for d in dates],
    })
    df.write_csv(out_path / "money_supply.csv")
    n_backfill = sum(1 for d in dates if d.startswith("2024-") and backfill_2024.get(d) is not None)
    n_approx = sum(1 for d in dates if int(d[:4]) < 2024 and hh_map.get(d) is not None)
    print(f"Saved money_supply: {len(df)} rows to {out_path} "
          f"(m1_new: {n_backfill} 月官方回填 + {n_approx} 月近似)")
    return len(df)


def convert_pbc_overseas_rmb_assets(data_path: str, output_dir: str) -> int:
    """境外机构和个人持有境内人民币金融资产（月末存量），宽表
    date/股票/债券/贷款/存款（亿元）。
    源：gov_pbc/{year}/货币统计概览/境外机构和个人持有境内人民币金融资产情况
    [Domestic RMB Financial Assets Held by Overseas Entities].{htm,xls,xlsx}，2014 起。

    每个文件是「项目×月份」宽表：行=股票/债券/贷款/存款，列=当年 12 个月。
    用「行内数字序列」法对齐（项目名=首个非数字单元格，值=其后数字按序），
    不依赖绝对列索引——因为 2014 htm 的表头与数据行列不对齐（表头首列是
    「2013年末」，数据首列是项目名，数据多一个前导空列）。
    两个坑：
      - Excel 把 10 月单元格 2024.10 存成 2024.1（与 1 月同值），月份严格按
        数据列位置推断（_pbc_period_to_date），不解析浮点数值；
      - 2014 文件表头多一个「2013年末」期末列（非月度），用 _pbc_parse_period_str
        过滤掉，并在数据行多出对应值时跳过前导期末值。
    项目名清洗：源文件是「中文\\n English」，_pbc_norm_item 去换行 + 尾部英文。
    """
    src_root = Path(data_path) / "gov_pbc"
    out_path = Path(output_dir) / "pbc"
    out_path.mkdir(parents=True, exist_ok=True)

    targets = {"股票", "债券", "贷款", "存款"}
    grid: dict[str, dict[str, float]] = {}

    for year in range(2014, 2027):
        yd = src_root / str(year)
        if not yd.is_dir():
            continue
        fp = _pbc_find_file(yd, ["货币统计概览"], ["境外机构"])
        if fp is None:
            print(f"  跳过 {year}：找不到境外机构人民币金融资产文件")
            continue
        try:
            rows = _pbc_read_sheet(fp)
        except Exception as e:
            print(f"  跳过 {year}：读取失败 {e}")
            continue

        header_idx = _pbc_find_header_row(rows)
        if header_idx is None:
            print(f"  跳过 {year}：找不到表头行")
            continue
        header = rows[header_idx]

        # 表头识别月份序列 + 额外期末列数（如 2014 的「2013年末」）。
        # 用「行内数字序列」法对齐（不依赖绝对列索引，兼容 htm 表头/数据列错位）。
        months: list[str] = []
        n_extra = 0
        for cell in header:
            if _pbc_is_item_header_cell(cell):
                continue
            if not str(cell).strip():
                continue
            if _pbc_parse_period_str(cell) is not None:
                d = _pbc_period_to_date(cell, year, len(months) + 1)
                if d:
                    months.append(d)
            else:
                n_extra += 1  # 非月份数据列（如「2013年末」）
        if not months:
            print(f"  跳过 {year}：未识别到月份列")
            continue

        n_year = 0
        for r in rows[header_idx + 1:]:
            if not r:
                continue
            # 行内数字序列法：项目名=首个非数字单元格，值=其后所有数字（按序）
            name = ""
            vals: list[float] = []
            seen_num = False
            for c in r:
                if c is None or str(c).strip() == "":
                    continue
                v = _pbc_to_float(c)
                if v is not None:
                    vals.append(v)
                    seen_num = True
                elif not seen_num and not name:
                    name = _pbc_norm_item(c)
            if name not in targets:
                continue
            # 表头有期末列（n_extra>0）且数据多出对应个数时，跳过前导期末值
            start = n_extra if (n_extra and len(vals) == len(months) + n_extra) else 0
            for i, d in enumerate(months):
                vi = start + i
                if vi < len(vals) and vals[vi] is not None:
                    grid.setdefault(d, {})[name] = vals[vi]
                    n_year += 1
        print(f"  {year}: {n_year} 个值")

    dates = sorted(grid)
    df = pl.DataFrame({
        "date": dates,
        "股票": [grid[d].get("股票") for d in dates],
        "债券": [grid[d].get("债券") for d in dates],
        "贷款": [grid[d].get("贷款") for d in dates],
        "存款": [grid[d].get("存款") for d in dates],
    })
    df.write_csv(out_path / "overseas_rmb_assets.csv")
    print(f"Saved overseas_rmb_assets: {len(df)} rows to {out_path}")
    return len(df)


def convert_pbc_exchange_rate(data_path: str, output_dir: str) -> int:
    """人民币兑美元汇率（月度），宽表 date,usd_cny_eop,usd_cny_avg（人民币元/美元）。
    源：gov_pbc/{year}/[货币统计概览/]汇率报表[Exchange Rate].{htm,xls,xlsx}，1999 起。

    两个序列（均来自「一美元折合人民币」= 1 美元兑 X 人民币元）：
      usd_cny_eop  期末数 = 月末美元中间价
      usd_cny_avg  平均数 = 月均美元中间价

    每个文件是「项目×月份」宽表，月份在列。用列对齐法取数据行同列的值。
      - 月份用首列真实年月（_pbc_parse_period_str 解析 'YYYY.01' 或 1999 的
        '1999.12'）+ 列位置递增；不逐列解析字符串——.xls 会把 10 月表头
        'YYYY.10' 存成浮点 YYYY.1 被误判为 Q1→3 月。
    """
    src_root = Path(data_path) / "gov_pbc"
    out_path = Path(output_dir) / "pbc"
    out_path.mkdir(parents=True, exist_ok=True)

    # (列名, 关键词1, 关键词2)：标准化项目名需同时含两个关键词，避开英文翻译行
    series = [
        ("usd_cny_eop", "美元", "期末"),
        ("usd_cny_avg", "美元", "平均"),
    ]
    grid: dict[str, dict[str, float]] = {}

    for year in range(1999, 2027):
        yd = src_root / str(year)
        if not yd.is_dir():
            continue
        fp = _pbc_find_file(yd, ["货币统计概览"], ["汇率报表"])
        if fp is None:
            print(f"  跳过 {year}：找不到汇率报表")
            continue
        try:
            rows = _pbc_read_sheet(fp)
        except Exception as e:
            print(f"  跳过 {year}：读取失败 {e}")
            continue
        header_idx = _pbc_find_header_row(rows)
        if header_idx is None:
            print(f"  跳过 {year}：找不到表头行")
            continue
        header = rows[header_idx]
        # 月份列：用首列真实年月（_pbc_parse_period_str 解析首列 'YYYY.01' 或
        # 1999 的 '1999.12'），后续按列位置递增。不逐列解析字符串——.xls 会把
        # 10 月表头 'YYYY.10' 存成浮点 YYYY.1，被 _pbc_parse_period_str 误判为
        # Q1→3 月。首列总是 01 月（或 1999 的 12 月），不受此截断影响。
        raw_idxs: list[int] = []
        start_pm = None
        for ci, cell in enumerate(header):
            if _pbc_is_item_header_cell(cell):
                continue
            if not str(cell).strip():
                continue
            pm = _pbc_parse_period_str(cell)
            if pm is None:
                continue
            if start_pm is None:
                start_pm = pm
            raw_idxs.append(ci)
        if not raw_idxs or start_pm is None:
            print(f"  跳过 {year}：未识别到月份列")
            continue
        base_year, start_month = start_pm
        month_cols = [
            (ci, f"{base_year:04d}-{start_month + off:02d}")
            for off, ci in enumerate(raw_idxs)
            if start_month + off <= 12
        ]

        n_year = 0
        for r in rows[header_idx + 1:]:
            if not r:
                continue
            name = _pbc_norm_item(r[0]) if r[0] else ""
            if not name or _pbc_row_is_note(name):
                continue
            key = next((k for k, kw1, kw2 in series if kw1 in name and kw2 in name), None)
            if key is None:
                continue
            for ci, d in month_cols:
                if ci >= len(r):
                    continue
                v = _pbc_to_float(r[ci])
                if v is None:
                    continue
                grid.setdefault(d, {})[key] = v
                n_year += 1
        print(f"  {year}: {fp.name} → {n_year} 个值")

    dates = sorted(grid)
    df = pl.DataFrame({
        "date": dates,
        "usd_cny_eop": [grid[d].get("usd_cny_eop") for d in dates],
        "usd_cny_avg": [grid[d].get("usd_cny_avg") for d in dates],
    })
    df.write_csv(out_path / "exchange_rate.csv")
    print(f"Saved exchange_rate: {len(df)} rows to {out_path}")
    return len(df)


def convert_pbc_social_financing_flow(data_path: str, output_dir: str) -> int:
    """社会融资规模增量（流量），长表 date/item/value（亿元）。
    源：gov_pbc/{year}/社会融资规模/[社会融资规模增量统计表|社会融资规模统计表]
    .{htm,xls,xlsx}，2012 起。2012-2014 为宽表（htm），2015+ 为长表。

    单个文件常把多张表堆在一个 sheet 里（主增量表 + 完善后增量表 + 占比表），
    _pbc_parse_flow_long 按表头拆表、剔除占比(%)表、合并两行表头；跨年按最新
    修订取值（口径调整年如 2019 会回填历史数据，越新的文件越权威），保证
    (date,item) 唯一。"""
    src_root = Path(data_path) / "gov_pbc"
    out_path = Path(output_dir) / "pbc"
    out_path.mkdir(parents=True, exist_ok=True)
    alias_map = _pbc_alias_map(_SF_FLOW_ALIASES)

    # 按年升序处理；同一 (date,item) 以最新年份（最新修订）为准。
    # 央行在统计口径调整年（如 2019）会把历史数据回填进新表，故越新的文件越权威。
    best: dict[tuple[str, str], float] = {}
    for year in range(2012, 2027):
        yd = src_root / str(year) / "社会融资规模"
        if not yd.is_dir():
            continue
        fp = _pbc_find_file(yd, [], ["社会融资规模增量统计表"], exclude=("地区",))
        if fp is None:
            fp = _pbc_find_file(yd, [], ["社会融资规模统计表"],
                                exclude=("地区", "增量", "存量"))
        if fp is None:
            print(f"  跳过 {year}：找不到社融增量表")
            continue
        try:
            rows = _pbc_read_sheet(fp)
            # 优先长表（2015+），否则宽表（2012-2014 htm）
            recs = _pbc_parse_flow_long(rows)
            if not recs:
                recs = _pbc_parse_wide_months(rows, year)
        except Exception as e:
            print(f"  跳过 {year}：解析失败 {e}")
            continue
        for date, item, val in recs:
            best[(date, alias_map.get(item, item))] = val

    df = pl.DataFrame({
        "date": [k[0] for k in best],
        "item": [k[1] for k in best],
        "value": list(best.values()),
    }).sort(["date", "item"])
    df.write_csv(out_path / "social_financing_flow.csv")
    print(f"Saved social_financing_flow: {len(df)} rows to {out_path}")
    return len(df)


def convert_pbc_social_financing_stock(data_path: str, output_dir: str) -> int:
    """社会融资规模存量，长表 date/item/stock/growth_rate（万亿元 / %）。
    源：gov_pbc/{year}/社会融资规模/社会融资规模存量统计表.{htm,xls,xlsx}，2015 起。
    2015 为季度数据（Q1-Q4，映射到季末月），2016+ 为月度。"""
    src_root = Path(data_path) / "gov_pbc"
    out_path = Path(output_dir) / "pbc"
    out_path.mkdir(parents=True, exist_ok=True)
    alias_map = _pbc_alias_map(_SF_STOCK_ALIASES)

    records: list[tuple[str, str, float, float]] = []
    for year in range(2015, 2027):
        yd = src_root / str(year) / "社会融资规模"
        if not yd.is_dir():
            continue
        fp = _pbc_find_file(yd, [], ["社会融资规模存量统计表"], exclude=("地区",))
        if fp is None:
            print(f"  跳过 {year}：找不到社融存量表")
            continue
        try:
            rows = _pbc_read_sheet(fp)
            recs = _pbc_parse_stock_table(rows, year)
        except Exception as e:
            print(f"  跳过 {year}：解析失败 {e}")
            continue
        records.extend(recs)

    df = pl.DataFrame({
        "date": [r[0] for r in records],
        "item": [alias_map.get(r[1], r[1]) for r in records],
        "stock": [r[2] for r in records],
        "growth_rate": [r[3] for r in records],
    }).sort(["date", "item"])
    df.write_csv(out_path / "social_financing_stock.csv")
    print(f"Saved social_financing_stock: {len(df)} rows to {out_path}")
    return len(df)


def convert_pbc_credit_funds(data_path: str, output_dir: str) -> int:
    """金融机构信贷收支表（存贷款），长表 date/currency/item/value（亿元）。
    currency ∈ {本外币, 人民币}。全明细输出（含各项存款、各项贷款、资金来源/运用
    总计及所有分项）。源：gov_pbc/{year}/[金融机构信贷收支统计/]金融机构{本外币,人民币}
    信贷收支表.{htm,xls,xlsx}，1999 起（本外币口径部分年份缺失）。

    item 带层级上下文（「·」拼接）以保证唯一：跨分组重名的子项补父级，如
    「住户存款·（1）活期存款」「非金融企业存款·（1）活期存款」「住户贷款·短期贷款·消费贷款」；
    顶级分项（各项存款/贷款）、分组父项（1.住户存款）保持原名。详见 _pbc_parse_wide_months。"""
    src_root = Path(data_path) / "gov_pbc"
    out_path = Path(output_dir) / "pbc"
    out_path.mkdir(parents=True, exist_ok=True)

    specs = [
        ("本外币", ["金融机构本外币信贷收支表"], ("按部门",)),
        ("人民币", ["金融机构人民币信贷收支表"], ("按部门",)),
    ]
    records: list[tuple[str, str, str, float]] = []
    for currency, keywords, exclude in specs:
        for year in range(1999, 2027):
            yd = src_root / str(year)
            if not yd.is_dir():
                continue
            fp = _pbc_find_file(yd, ["金融机构信贷收支统计"], keywords, exclude)
            if fp is None:
                continue
            try:
                rows = _pbc_read_sheet(fp)
                recs = _pbc_parse_wide_months(rows, year, disambiguate=True)
            except Exception as e:
                print(f"  跳过 {currency} {year}：{e}")
                continue
            for date, item, val in recs:
                records.append((date, currency, item, val))

    df = pl.DataFrame({
        "date": [r[0] for r in records],
        "currency": [r[1] for r in records],
        "item": [r[2] for r in records],
        "value": [r[3] for r in records],
    }).sort(["date", "currency", "item"])
    df.write_csv(out_path / "credit_funds.csv")
    print(f"Saved credit_funds: {len(df)} rows to {out_path}")
    return len(df)


def convert_pbc_central_bank_balance_sheet(data_path: str, output_dir: str) -> int:
    """货币当局资产负债表，长表 date/item/value（亿元）。全明细输出（资产方+
    负债方各项，含总资产/总负债）。源：gov_pbc/{year}/[货币统计概览/]货币当局资产
    负债表.{htm,xls,xlsx}，1999 起。

    「其中：」明细补父级以消歧：资产方与负债方均有「其中：中央政府」，输出为
    「对政府债权·其中：中央政府」「政府存款·其中：中央政府」。详见 _pbc_parse_wide_months。"""
    src_root = Path(data_path) / "gov_pbc"
    out_path = Path(output_dir) / "pbc"
    out_path.mkdir(parents=True, exist_ok=True)

    records: list[tuple[str, str, float]] = []
    for year in range(1999, 2027):
        yd = src_root / str(year)
        if not yd.is_dir():
            continue
        fp = _pbc_find_file(yd, ["货币统计概览"], ["货币当局资产负债表"])
        if fp is None:
            print(f"  跳过 {year}：找不到货币当局资产负债表")
            continue
        try:
            rows = _pbc_read_sheet(fp)
            recs = _pbc_parse_wide_months(rows, year, disambiguate=True)
        except Exception as e:
            print(f"  跳过 {year}：{e}")
            continue
        records.extend(recs)

    df = pl.DataFrame({
        "date": [r[0] for r in records],
        "item": [r[1] for r in records],
        "value": [r[2] for r in records],
    }).sort(["date", "item"])
    df.write_csv(out_path / "central_bank_balance_sheet.csv")
    print(f"Saved central_bank_balance_sheet: {len(df)} rows to {out_path}")
    return len(df)


# ============== gov_stat（国家统计局月度指标）==============

def _gov_stat_read_rows(path: Path) -> list[list[str]]:
    """读 gov_stats 的 csv/xlsx → 二维字符串数组。"""
    if path.suffix.lower() == ".csv":
        with open(path, encoding="utf-8") as f:
            return list(csv.reader(f))
    wb = CalamineWorkbook.from_path(str(path))
    ws = wb.get_sheet_by_index(0)
    return [["" if c is None else str(c) for c in row] for row in ws.to_python()]


_GOV_STAT_MONTH_RE = re.compile(r"(\d{4})年(\d{1,2})月")


def _gov_stat_parse_indicator_table(path: Path) -> list[tuple[str, str, float]]:
    """读 gov_stats 的「指标×月份」表（csv 或 xlsx），返回 [(date, indicator, value)]。
    月份列名形如 'YYYY年M月'，可能乱序或倒序，按列名解析（不依赖列顺序）。
    指标名去所有空白统一（如 '当期值 (千美元)' → '当期值(千美元)'），保留括号单位。
    跳过注释/来源行。"""
    rows = _gov_stat_read_rows(path)
    header_idx = None
    for i, r in enumerate(rows):
        if r and r[0] and "指标" in str(r[0]):
            header_idx = i
            break
    if header_idx is None:
        return []
    header = rows[header_idx]
    month_cols: list[tuple[int, int, int]] = []  # (col_idx, year, month)
    for j in range(1, len(header)):
        m = _GOV_STAT_MONTH_RE.search(str(header[j]))
        if m:
            month_cols.append((j, int(m.group(1)), int(m.group(2))))

    out: list[tuple[str, str, float]] = []
    for r in rows[header_idx + 1:]:
        if not r or not r[0]:
            continue
        ind = str(r[0]).strip()
        if not ind or ind.startswith("注") or ind.startswith("数据来源"):
            break
        ind_norm = re.sub(r"\s+", "", ind)
        for j, y, mo in month_cols:
            val = _pbc_to_float(r[j]) if j < len(r) else None
            if val is None:
                continue
            out.append((f"{y:04d}-{mo:02d}", ind_norm, val))
    return out


def _gov_stat_fill_jan_feb(df: pl.DataFrame) -> pl.DataFrame:
    """对「当期值」指标，补全 1、2 月当期值缺失（统计局 1-2 月合并发布所致）。
    按 indicator 名自动配对：含「当期值」的，配对其「累计值」变体。

    两种填补规则（按 2 月当期值是否已发布自动选择）：
    - **平摊**（2024-2025 纯合并）：当期[1月]、当期[2月] 都空 → 各填 累计[2月] / 2。
    - **反推**（2026 半合并）：当期[1月] 空、当期[2月] 有值 → Jan = 累计[2月] − 当期[2月]，
      Feb 保留实际值。和校验自洽（Jan + Feb = 累计[2月]）。
    - 2005-2023 分月发布：两月都有值，不动。

    仅补当期值；累计值/同比等列的 1 月仍按原始（2 月累计值原本就有）。"""
    indicators = df["indicator"].unique().to_list()
    pairs = [(ind, ind.replace("当期值", "累计值")) for ind in indicators
             if "当期值" in ind and ind.replace("当期值", "累计值") in indicators]
    if not pairs:
        return df

    d = df.with_columns(pl.col("date").str.to_date("%Y-%m"))
    wide = d.pivot(on="indicator", values="value", index="date").sort("date")
    # 补齐完整月历，否则没有任何指标的 1 月不会出现在表里
    full = pl.DataFrame({"date": pl.date_range(wide["date"].min(), wide["date"].max(),
                                               "1mo", eager=True)})
    wide = full.join(wide, on="date", how="left")
    wide = wide.with_columns(pl.col("date").dt.year().alias("_y"),
                             pl.col("date").dt.month().alias("_m"))
    for cur, acc in pairs:
        # 2 月累计值（= 1+2 月合计）与 2 月当期值，按年份对齐到每一行
        feb_acc = wide.filter(pl.col("_m") == 2).select("_y", pl.col(acc).alias("_feb_acc"))
        feb_cur = wide.filter(pl.col("_m") == 2).select("_y", pl.col(cur).alias("_feb_cur"))
        wide = wide.join(feb_acc, on="_y", how="left").join(feb_cur, on="_y", how="left")
        # 平摊：1 或 2 月 + 当期空 + 2 月当期也空 + 2 月累计有
        split = (pl.col("_m").is_in([1, 2]) & pl.col(cur).is_null()
                 & pl.col("_feb_cur").is_null() & pl.col("_feb_acc").is_not_null())
        # 反推：仅 1 月 + 当期空 + 2 月当期有 + 2 月累计有
        derive = ((pl.col("_m") == 1) & pl.col(cur).is_null()
                  & pl.col("_feb_cur").is_not_null() & pl.col("_feb_acc").is_not_null())
        wide = wide.with_columns(
            pl.when(split).then(pl.col("_feb_acc") / 2)
            .when(derive).then(pl.col("_feb_acc") - pl.col("_feb_cur"))
            .otherwise(pl.col(cur)).alias(cur))
        wide = wide.drop("_feb_acc", "_feb_cur")
    ind_cols = [c for c in wide.columns if c not in ("date", "_y", "_m")]
    long = (wide.unpivot(on=ind_cols, index="date", variable_name="indicator", value_name="value")
                 .filter(pl.col("value").is_not_null())
                 .with_columns(pl.col("date").dt.strftime("%Y-%m")))
    return long.sort(["date", "indicator"])


def _convert_gov_stat_monthly_indicators(
    data_path: str, output_dir: str, src_name: str, out_name: str,
    year_start: int = 2000, year_end: int = 2026,
) -> int:
    """通用：把 gov_stats/{src_name}/{year}.{csv,xlsx} 的「指标×月份」表汇总为
    长表 {output_dir}/gov_stat/{out_name}.csv（date, indicator, value）。"""
    src_root = Path(data_path) / "gov_stats" / src_name
    out_path = Path(output_dir) / "gov_stat"
    out_path.mkdir(parents=True, exist_ok=True)

    records: list[tuple[str, str, float]] = []
    for year in range(year_start, year_end + 1):
        fp = src_root / f"{year}.csv"
        if not fp.exists():
            fp = src_root / f"{year}.xlsx"
        if not fp.exists():
            continue
        try:
            records.extend(_gov_stat_parse_indicator_table(fp))
        except Exception as e:
            print(f"  跳过 {src_name} {year}：{e}")

    df = pl.DataFrame({
        "date": [r[0] for r in records],
        "indicator": [r[1] for r in records],
        "value": [r[2] for r in records],
    }).sort(["date", "indicator"])
    df = _gov_stat_fill_jan_feb(df)
    df.write_csv(out_path / f"{out_name}.csv")
    print(f"Saved {out_name}: {len(df)} rows to {out_path}")
    return len(df)


def convert_gov_stat_trade(data_path: str, output_dir: str) -> int:
    """海关进出口月度指标（千美元 / %），长表 date/indicator/value。
    指标含进出口/出口/进口总值（当期值、同比、累计值、累计增长）及进出口差额
    （当期值、累计值）。源：gov_stats/进出口/{year}.{csv≤2022, xlsx≥2023}，2000 起。"""
    return _convert_gov_stat_monthly_indicators(
        data_path, output_dir, src_name="进出口", out_name="trade")


def convert_gov_stat_retail_sales(data_path: str, output_dir: str) -> int:
    """社会消费品零售总额月度指标（亿元 / %），长表 date/indicator/value。
    指标含社会消费品零售总额、限上单位消费品零售额的当期值、累计值、同比、
    累计同比。源：gov_stats/社会消费品零售总额/{year}.{csv≤2024, xlsx≥2025}，2000 起。"""
    return _convert_gov_stat_monthly_indicators(
        data_path, output_dir, src_name="社会消费品零售总额", out_name="retail_sales")


def convert_gov_stat_port_freight(data_path: str, output_dir: str) -> int:
    """全国港口货物吞吐量月度指标（万吨 / %），长表 date/indicator/value。
    指标含全国港口 / 外贸 / 沿海港口货物吞吐量各自的当期值、累计值、同比、累计增长。
    源：gov_stats/全国港口货物吞吐量/{year}.xlsx，2019 起。"""
    return _convert_gov_stat_monthly_indicators(
        data_path, output_dir, src_name="全国港口货物吞吐量",
        out_name="port_freight", year_start=2019)


def convert_gov_stat_freight(data_path: str, output_dir: str) -> int:
    """货运量月度指标（万吨 / %），长表 date/indicator/value。
    指标含总 / 铁路 / 公路 / 水运 / 民航货运量各自的当期值、累计值、同比、累计增长。
    源：gov_stats/货运量/{year}.xlsx，2005 起。"""
    return _convert_gov_stat_monthly_indicators(
        data_path, output_dir, src_name="货运量", out_name="freight", year_start=2005)


def convert_gov_stat_passenger(data_path: str, output_dir: str) -> int:
    """客运量月度指标（万人 / %），长表 date/indicator/value。
    指标含总 / 铁路 / 公路 / 水运 / 民航客运量各自的当期值、累计值、同比、累计增长。
    源：gov_stats/客运量/{year}.xlsx，2005 起。"""
    return _convert_gov_stat_monthly_indicators(
        data_path, output_dir, src_name="客运量", out_name="passenger", year_start=2005)


def convert_gov_stat_retail_monthly(data_path: str, output_dir: str) -> int:
    """社会消费品零售总额「每月新增额」（当月零售额，亿元），宽表 date/总额/限上。

    由累计值年内差分得到：每月新增额[t] = 累计值[t] − 累计值[t−1]，1 月 = 累计值[1月]。
    2012 年起统计局 1-2 月合并公布，1 月累计值缺失 → 用「2 月累计值 / 2」平分填充，
    故合并年份 1、2 月新增额均 = 2 月累计值 / 2（与官方累计值自洽）。2011 及以前
    1-2 月分开公布，1 月累计值原值直接用。

    复用 _gov_stat_parse_indicator_table：指标名去空白统一、过滤「注：/数据来源」脚注。
    总额 2000 起，限上 2011 起（限上发布略滞后，总额可能多 1 个月）。
    源：gov_stats/社会消费品零售总额/{year}.{csv≤2024, xlsx≥2025}。
    """
    src_root = Path(data_path) / "gov_stats" / "社会消费品零售总额"
    out_path = Path(output_dir) / "gov_stat"
    out_path.mkdir(parents=True, exist_ok=True)

    records: list[tuple[str, str, float]] = []
    for year in range(2000, 2027):
        fp = src_root / f"{year}.csv"
        if not fp.exists():
            fp = src_root / f"{year}.xlsx"
        if not fp.exists():
            continue
        try:
            records.extend(_gov_stat_parse_indicator_table(fp))
        except Exception as e:
            print(f"  跳过 {year}：{e}")

    acc_total = "社会消费品零售总额累计值(亿元)"
    acc_above = "限上单位消费品零售额累计值(亿元)"
    df = pl.DataFrame({
        "date": [r[0] for r in records],
        "indicator": [r[1] for r in records],
        "value": [r[2] for r in records],
    }).filter(pl.col("indicator").is_in([acc_total, acc_above]))
    if df.is_empty():
        print("  无累计值记录")
        return 0
    kind = (pl.when(pl.col("indicator") == acc_total).then(pl.lit("总额"))
            .otherwise(pl.lit("限上")))
    acc = (df.with_columns(pl.col("date").str.to_date("%Y-%m"), kind.alias("kind"))
             .pivot(on="kind", values="value", index="date")
             .sort("date"))
    # 补完整月历（合并年份缺 1 月行，差分前必须先补出）
    full = pl.DataFrame({"date": pl.date_range(acc["date"].min(), acc["date"].max(),
                                               "1mo", eager=True)})
    acc = full.join(acc, on="date", how="left")
    acc = acc.with_columns(pl.col("date").dt.year().alias("_y"),
                           pl.col("date").dt.month().alias("_m"))

    out = acc.select("date")
    for kind_name in ("总额", "限上"):
        feb = (acc.filter(pl.col("_m") == 2)
                 .select("_y", pl.col(kind_name).alias("_feb"))
                 .group_by("_y").agg(pl.col("_feb").first()))
        w = acc.join(feb, on="_y", how="left")
        cond = (pl.col("_m") == 1) & pl.col(kind_name).is_null() & pl.col("_feb").is_not_null()
        w = w.with_columns(pl.when(cond).then(pl.col("_feb") / 2)
                           .otherwise(pl.col(kind_name)).alias("_acc"))
        w = w.with_columns(pl.col("_acc").diff().over("_y").alias("_diff"))
        w = w.with_columns(pl.when(pl.col("_m") == 1).then(pl.col("_acc"))
                           .otherwise(pl.col("_diff")).alias(kind_name))
        out = out.with_columns(w[kind_name])

    out = (out.with_columns(pl.col("date").dt.strftime("%Y-%m"))
             .filter(pl.col("总额").is_not_null() | pl.col("限上").is_not_null()))
    out.write_csv(out_path / "retail_sales_monthly.csv")
    print(f"Saved retail_sales_monthly: {len(out)} rows to {out_path}")
    return len(out)


# ============== turnover_concentration ==============

# 行情目录候选：finance_sina 是实时源（1992-），eastmoney 是历史归档（2022-2025 停更）。靠前的优先。
_TURNOVER_QUOTE_DIRS = ["finance_sina/stock_quote", "eastmoney/stock_quote"]
# 早期 A 股股票数少（1992 ~50 只、2000 ~1000 只、2010 ~1700 只），用低阈值尽可能保留
# 完整历史（1992 起）；现代年份无残缺抓取（2005+ 最小文件均 >800 行），50 行门槛只影响早期
_TURNOVER_MIN_ROWS = 50


def _concentration_metrics(x: np.ndarray) -> dict:
    """5 个集中度算法，输入 turnover>0 的成交额一维数组。"""
    n = len(x)
    s = x.sum()
    if n < 10 or s <= 0:
        return {k: None for k in ("gini", "alpha", "top5_ratio", "hhi", "cr10")}

    sorted_x = np.sort(x)
    shares = x / s

    # Gini: (Σ(2i-n-1)·x_i) / (n·Σx_i)
    gini = float((np.arange(1, n + 1) * 2 - n - 1) @ sorted_x / (n * s))

    # Pareto α: log-log rank vs amount 全点回归斜率绝对值（rank 从大到小）
    log_ranks = np.log(np.arange(1, n + 1))
    log_amounts = np.log(sorted_x[::-1])
    slope = float(np.polyfit(log_ranks, log_amounts, 1)[0])
    alpha = abs(slope)

    # Top5 / median
    top5_ratio = float(sorted_x[-5:].mean() / np.median(x))

    # HHI = Σ(share_i²)
    hhi = float((shares ** 2).sum())

    # CR10 = top 10 shares 之和
    cr10 = float(np.sort(shares)[-10:].sum())

    return {"gini": gini, "alpha": alpha, "top5_ratio": top5_ratio,
            "hhi": hhi, "cr10": cr10}


def convert_turnover_concentration(
    data_path: str = DEFAULT_DATA_PATH,
    output_dir: str = OUTPUT_DATA_PATH,
    start_year: int = 1990,
) -> int:
    """全 A 股日成交额集中度（gini/alpha/top5-median/hhi/cr10）+ 股票数 + 流通/总市值，宽表。"""
    root = Path(data_path)

    # 扫所有候选目录的完整交易日，同日靠前目录优先
    by_date: dict[str, Path] = {}
    for name in _TURNOVER_QUOTE_DIRS:
        d = root / name
        if not d.is_dir():
            continue
        for f in d.glob("*.csv"):
            by_date.setdefault(f.stem, f)

    dates: list[str] = []
    for dt in sorted(by_date):
        if int(dt[:4]) < start_year:
            continue
        with open(by_date[dt], "rb") as fp:
            n_rows = sum(1 for _ in fp)
        if n_rows >= _TURNOVER_MIN_ROWS:
            dates.append(dt)

    if not dates:
        raise RuntimeError(f"找不到 {start_year} 起行数 ≥ {_TURNOVER_MIN_ROWS} 的行情文件")

    print(f"完整交易日：{len(dates)} 天（{dates[0]} ~ {dates[-1]}）")

    records = []
    for i, dt in enumerate(dates):
        try:
            # infer_schema_length 提高，避免 turnover/market_cap 等列被早期纯整数行推断为 i64
            df = pl.read_csv(by_date[dt], infer_schema_length=10000)
        except Exception as e:
            print(f"  跳过 {dt}（读取失败：{e}）")
            continue
        if "turnover" not in df.columns:
            continue
        df_t = df.filter(pl.col("turnover") > 0)
        x = df_t["turnover"].to_numpy().astype(float)
        m = _concentration_metrics(x)
        m["date"] = dt
        m["stock_count"] = int(len(x))
        # 流通/总市值（与 stock_count 同口径：turnover>0 的活跃股票之和；
        # eastmoney 源无此列 → None，finance_sina 源才有）
        for col in ("free_float_market_cap", "market_cap"):
            m[f"{col}_total"] = (float(df_t[col].sum())
                                 if col in df_t.columns else None)
        records.append(m)
        if (i + 1) % 200 == 0:
            print(f"  {i + 1}/{len(dates)}...")

    if not records:
        raise RuntimeError("无有效数据")

    out_df = (pl.DataFrame(records)
              .select(["date", "gini", "alpha", "top5_ratio", "hhi", "cr10",
                       "stock_count", "free_float_market_cap_total", "market_cap_total"])
              .sort("date"))
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    out_df.write_csv(out_path / "turnover_concentration.csv")
    print(f"Saved turnover_concentration: {len(out_df)} rows to {out_path}")
    return len(out_df)


# ============== exchange_hkex/southbound_flow ==============

def convert_exchange_hkex_southbound_flow(data_path: str, output_dir: str) -> int:
    """港股通（南向）每日买卖净额，宽表 date,sse_buy_yi,sse_sell_yi,szse_buy_yi,
    szse_sell_yi,buy_yi,sell_yi,net_yi（单位：亿港元）。

    两个数据源拼接：
      1. exchange_hkex/hk_connect_total.csv —— 长表 date,code,buy,sell，
         **已直接为亿港元**。覆盖 2015-08-10 ~ 2023-03-24。用于 connect_top
         启动前的早期数据（< 2021-06-15）。同日 SSE Southbound buy 与 connect_top
         实测一致（如 2021-06-24：hk=80.87，connect_top=8086.67÷100=80.87）。
      2. exchange_hkex/connect_top/{YYYY-MM-DD}.csv —— 每日一文件，含 SSE/SZSE
         × North/South 四行聚合（"南下资金统计"）+ 各方向 top10 个股明细。
         **聚合行单位为百万港元**，输出 ÷100 换算到亿。用于 2021-06-15+。

    单位推断（connect_top 聚合 = 百万港元）：2024-06-14 实测 SSE Southbound
    聚合 buy=12848.62，对应 top10 个股 buy 合计 ≈ 4412 百万港元（44.12 亿），
    聚合是个股的 ~2.9 倍，符合"汇总 > top10"预期；若单位为万元则聚合反小于
    top10，不成立。

    net_yi > 0 = 南向净流入（内地净买入港股）。

    Schema（connect_top 跨年变化，按列名读取不依赖顺序）：
      - 2021-2022 多数: date,code,name,buy,sell
      - 2022 部分（如 2022-06-15）: code,buy,sell,name（无 date 列）
      - 2023+: date,code,证券简称,buy,sell
    date 一律取自文件名（YYYY-MM-DD），不读列。

    空值与 sentinel：南向停盘日（HK 假期、半日市等）buy/sell 为空字符串，输出
    null；北向 2025+ 出现 999999999 sentinel（≥9.9e8 一律置 null，南向目前
    无此值但同样过滤以防后续变化）。
    """
    src_root = Path(data_path) / "exchange_hkex"
    out_path = Path(output_dir) / "exchange_hkex"
    out_path.mkdir(parents=True, exist_ok=True)

    # 找 connect_top 实际最小日期（避免硬编码，用作 hk_connect_total 的截止边界）
    ct_dir = src_root / "connect_top"
    ct_dates: list[date] = []
    if ct_dir.exists():
        ct_dates = sorted(
            date.fromisoformat(fp.stem)
            for fp in ct_dir.glob("*.csv")
        )
    if not ct_dates:
        raise RuntimeError("connect_top 目录为空")
    ct_min = ct_dates[0]  # 实测 2021-06-15

    records: dict[date, dict] = {}

    # === Part 1: hk_connect_total.csv（早期，< ct_min）===
    hk_path = src_root / "hk_connect_total.csv"
    if hk_path.exists():
        print(f"读取 {hk_path.name}（用于 {ct_min} 之前）...")
        hk = (
            pl.read_csv(hk_path)
            .with_columns(pl.col("date").str.to_date("%Y-%m-%d").alias("d"))
            .filter(
                pl.col("code").is_in(["SSE Southbound", "SZSE Southbound"])
                & (pl.col("d") < ct_min)
            )
        )
        n = 0
        for r in hk.iter_rows(named=True):
            d = r["d"]
            entry = records.setdefault(d, {
                "date": d, "sse_buy_yi": None, "sse_sell_yi": None,
                "szse_buy_yi": None, "szse_sell_yi": None,
            })
            b = r["buy"]
            s = r["sell"]
            # hk_connect_total 已是亿港元，无需 ÷100
            if r["code"] == "SSE Southbound":
                entry["sse_buy_yi"] = b
                entry["sse_sell_yi"] = s
            else:
                entry["szse_buy_yi"] = b
                entry["szse_sell_yi"] = s
            n += 1
        if records:
            print(f"  hk_connect_total: {len(records)} 天 "
                  f"({min(records)} ~ {max(records)})")

    # === Part 2: connect_top/*.csv（ct_min 及之后）===
    for fp in sorted(ct_dir.glob("*.csv")):
        date_str = fp.stem
        d_obj = date.fromisoformat(date_str)
        if d_obj < ct_min:
            continue
        try:
            df = pl.read_csv(fp)
        except Exception as e:
            print(f"  跳过 {date_str}：读取失败 {e}")
            continue

        if not all(c in df.columns for c in ("code", "buy", "sell")):
            print(f"  跳过 {date_str}：缺少 code/buy/sell 列")
            continue

        # 强制数值化（空字符串 → null；999999999 sentinel → null）
        df = df.with_columns(
            pl.col("buy").cast(pl.Float64, strict=False),
            pl.col("sell").cast(pl.Float64, strict=False),
        ).with_columns(
            pl.when(pl.col("buy") >= 9.9e8).then(None).otherwise(pl.col("buy")).alias("buy"),
            pl.when(pl.col("sell") >= 9.9e8).then(None).otherwise(pl.col("sell")).alias("sell"),
        )

        def _agg(channel: str) -> tuple[float | None, float | None]:
            sub = df.filter(pl.col("code") == channel)
            if sub.is_empty():
                return None, None
            b = sub["buy"][0]
            s = sub["sell"][0]
            # 百万 → 亿（÷100）
            return (
                b / 100 if b is not None else None,
                s / 100 if s is not None else None,
            )

        sse_b, sse_s = _agg("SSE Southbound")
        szse_b, szse_s = _agg("SZSE Southbound")
        records[d_obj] = {
            "date": d_obj,
            "sse_buy_yi": sse_b,
            "sse_sell_yi": sse_s,
            "szse_buy_yi": szse_b,
            "szse_sell_yi": szse_s,
        }

    if not records:
        raise RuntimeError("未读取到任何数据")

    df = (
        pl.DataFrame(list(records.values()), schema_overrides={
            "sse_buy_yi": pl.Float64, "sse_sell_yi": pl.Float64,
            "szse_buy_yi": pl.Float64, "szse_sell_yi": pl.Float64,
        })
        .sort("date")
        # sum_horizontal：null 自动当 0，避免早期 SZSE 未开通（null）导致 buy_yi/net_yi 整列 null
        .with_columns(
            pl.sum_horizontal("sse_buy_yi", "szse_buy_yi").alias("buy_yi"),
            pl.sum_horizontal("sse_sell_yi", "szse_sell_yi").alias("sell_yi"),
        )
        .with_columns(
            (pl.col("buy_yi") - pl.col("sell_yi")).alias("net_yi"),
        )
    )

    df.write_csv(out_path / "southbound_flow.csv")
    print(f"Saved southbound_flow: {len(df)} rows to {out_path}")
    return len(df)


# ============== index_adjust_history（指数成份调整历史）==============

import json

_ADJUST_IN_SHEETS = {"调入", "换入", "addition"}
_ADJUST_OUT_SHEETS = {"调出", "换出", "deletion"}
_CODE6_RE = re.compile(r"^\d{6}$")
_EFFECTIVE_RE = re.compile(r"于\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日.*?生效")
_REPLACE_COUNT_RE = re.compile(r"([一-龥]+[A-Za-z0-9]{0,6}?)指数更换(\d+)只")

# 静态指数名→代码（运行时从 xlsx 数据动态补充）
_INDEX_NAME_TO_CODE = {
    "沪深300": "000300", "中证500": "000905", "中证1000": "000852",
    "中证100": "000903", "中证200": "000908", "中证800": "000906",
    "中证A50": "930050", "中证A100": "930100", "中证A500": "932000",
}


def _ah_resolve_index(name: str, mapping: dict):
    """指数名 → (code, canonical_name)。先精确匹配，再子串模糊（应对「其中沪深300」等前缀）。"""
    name = (name or "").strip()
    if name in mapping:
        return mapping[name], name
    for k, v in mapping.items():
        if k in name or name in k:
            return v, k
    return "", name

_ADJUST_SCHEMA = {
    "index_code": pl.Utf8, "index_name": pl.Utf8,
    "announce_date": pl.Date, "effective_date": pl.Date,
    "constituent_code": pl.Utf8, "constituent_name": pl.Utf8,
    "direction": pl.Utf8, "source": pl.Utf8,
}


def _ah_read_excel_sheets(path: Path) -> dict:
    """读 xls/xlsx（含 OLE2 伪 xlsx）→ {sheet_name: list[list[str]]}。"""
    try:
        wb = CalamineWorkbook.from_path(str(path))
        return {sn: [["" if c is None else str(c) for c in r]
                     for r in wb.get_sheet_by_name(sn).to_python()]
                for sn in wb.sheet_names}
    except Exception:
        import xlrd
        wb = xlrd.open_workbook(str(path))
        return {s.name: [[str(c) for c in s.row_values(i)] for i in range(s.nrows)]
                for s in wb.sheets()}


def _ah_clean_code(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip().split(".")[0]
    return s if _CODE6_RE.match(s) else None


def _ah_parse_adjust_xlsx(path: Path):
    """解析调整 xlsx → [(index_code, index_name, code, name, direction)]。
    兼容两种结构：A=调入/调出分 sheet(4列)；B=单表「调出|调入」双列对(6列)。"""
    sheets = _ah_read_excel_sheets(path)
    events = []
    # 结构 A：按 sheet 名判方向
    for sn, rows in sheets.items():
        snl = str(sn).strip().lower()
        if snl in _ADJUST_IN_SHEETS:
            direction = "in"
        elif snl in _ADJUST_OUT_SHEETS:
            direction = "out"
        else:
            continue
        for row in rows[1:]:
            if len(row) < 4:
                continue
            idx_code = str(row[0]).strip()
            code = _ah_clean_code(row[2])
            if not idx_code or not code:
                continue
            events.append((idx_code, str(row[1]).strip(), code, str(row[3]).strip(), direction))
    if events:
        return events
    # 结构 B：单表双列对，找含「调出」「调入」的表头行
    for rows in sheets.values():
        hdr = None
        for i in range(min(3, len(rows))):
            cells = [str(c) for c in rows[i]]
            if any("调出" in c for c in cells) and any("调入" in c for c in cells):
                hdr = i
                break
        if hdr is None:
            continue
        for row in rows[hdr + 1:]:
            if len(row) < 6:
                continue
            idx_code = str(row[0]).strip()
            if not idx_code:
                continue
            idx_name = str(row[1]).strip()
            out_code = _ah_clean_code(row[2])
            in_code = _ah_clean_code(row[4])
            if out_code:
                events.append((idx_code, idx_name, out_code, str(row[3]).strip(), "out"))
            if in_code:
                events.append((idx_code, idx_name, in_code, str(row[5]).strip(), "in"))
        if events:
            return events
    return events


def _ah_load_meta(news_dir: Path) -> dict:
    mp = news_dir / "meta.json"
    if mp.is_file():
        try:
            return json.loads(mp.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _ah_read_content(news_dir: Path) -> str:
    cp = news_dir / "content.txt"
    if cp.is_file():
        return cp.read_text(encoding="utf-8", errors="ignore")
    return ""


def _ah_extract_effective(content: str):
    m = _EFFECTIVE_RE.search(content)
    if m:
        try:
            return date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            return None
    return None


def _ah_extract_counts(content: str):
    """从正文提取 [(index_name, n)]（按出现顺序），用于 PDF 切分。"""
    return [(m[1].strip(), int(m[2])) for m in _REPLACE_COUNT_RE.finditer(content)]


def _ah_parse_adjust_pdf(path: Path, counts, name_to_code: dict):
    """解析定期调整 PDF → [(index_code, index_name, code, name, direction)]。
    表格为「调出|调入」双列对，按正文各指数更换数量顺序切分。"""
    import pdfplumber
    pdf = pdfplumber.open(str(path))
    data = []  # (out_code, out_name, in_code, in_name)
    for pg in pdf.pages:
        for t in (pg.extract_tables() or []):
            for row in t:
                if not row:
                    continue
                joined = "".join(str(c) for c in row if c)
                if any(k in joined for k in ("名单", "代码", "名称", "指数", "Index", "调整")):
                    continue
                if row[0] and _CODE6_RE.match(str(row[0]).strip()):
                    data.append([str(c).strip() if c else "" for c in row[:4]])
    events = []
    idx = 0
    for name, n in counts:
        code, canon = _ah_resolve_index(name, name_to_code)
        block = data[idx:idx + n]
        idx += n
        for r in block:
            out_code = _ah_clean_code(r[0])
            in_code = _ah_clean_code(r[2]) if len(r) > 2 else None
            if out_code:
                events.append((code, canon, out_code, r[1], "out"))
            if in_code:
                events.append((code, canon, in_code, r[3], "in"))
    return events


def convert_index_adjust_history(data_path: str, output_dir: str) -> int:
    """合并 index_adjust_raw + csindex_news（xlsx 优先，PDF 补缺）→ 按年分文件的调整事件表。
    输出 {output_dir}/index_adjust_history/{year}.parquet。"""
    base = Path(data_path) / "csindex"
    name_to_code = dict(_INDEX_NAME_TO_CODE)
    events = []  # (index_code, index_name, announce, effective, code, name, direction, source)

    # --- a. index_adjust_raw（xlsx，全扫）---
    raw_dir = base / "index_adjust_raw"
    if raw_dir.is_dir():
        for f in sorted(raw_dir.rglob("*")):
            if f.suffix.lower() not in (".xlsx", ".xls") or not f.is_file():
                continue
            try:
                d = date.fromisoformat(f.stem)
            except ValueError:
                continue
            try:
                parsed = _ah_parse_adjust_xlsx(f)
            except Exception as e:
                print(f"  跳过 {f}: {e}")
                continue
            for idx_code, idx_name, code, name, direction in parsed:
                name_to_code.setdefault(idx_name, idx_code)
                events.append((idx_code, idx_name, d, d, code, name, direction, "adjust_raw"))
        print(f"  index_adjust_raw: 累计 {len(events)} 条")

    # --- b. csindex_news xlsx 附件 ---
    news_dir = base / "csindex_data" / "csindex_news"
    n_before = len(events)
    if news_dir.is_dir():
        for nd in sorted(news_dir.iterdir()):
            if not nd.is_dir():
                continue
            meta = _ah_load_meta(nd)
            announce = _ah_extract_date(meta.get("date"))
            effective = _ah_extract_effective(_ah_read_content(nd)) or announce
            for xf in sorted(nd.iterdir()):
                if xf.suffix.lower() not in (".xlsx", ".xls"):
                    continue
                try:
                    parsed = _ah_parse_adjust_xlsx(xf)
                except Exception as e:
                    print(f"  跳过 {nd.name}/{xf.name}: {e}")
                    continue
                for idx_code, idx_name, code, name, direction in parsed:
                    name_to_code.setdefault(idx_name, idx_code)
                    events.append((idx_code, idx_name, announce, effective, code, name, direction, "news_xlsx"))
        print(f"  csindex_news xlsx: +{len(events) - n_before} 条")

    # --- c. csindex_news PDF（补 2023+ 定期）---
    n_before = len(events)
    if news_dir.is_dir():
        for nd in sorted(news_dir.iterdir()):
            if not nd.is_dir():
                continue
            pdfs = [f for f in nd.iterdir() if f.suffix.lower() == ".pdf"]
            if not pdfs:
                continue
            content = _ah_read_content(nd)
            counts = _ah_extract_counts(content)
            if not counts:
                continue
            meta = _ah_load_meta(nd)
            announce = _ah_extract_date(meta.get("date"))
            effective = _ah_extract_effective(content) or announce
            for pdf in pdfs:
                try:
                    parsed = _ah_parse_adjust_pdf(pdf, counts, name_to_code)
                except Exception as e:
                    print(f"  PDF 跳过 {nd.name}/{pdf.name}: {e}")
                    continue
                for idx_code, idx_name, code, name, direction in parsed:
                    events.append((idx_code, idx_name, announce, effective, code, name, direction, "news_pdf"))
        print(f"  csindex_news PDF: +{len(events) - n_before} 条")

    if not events:
        raise RuntimeError("未解析到任何调整事件")

    # --- d. 合并去重（source 优先级 news_xlsx > adjust_raw > news_pdf）---
    df = pl.DataFrame(events, schema=_ADJUST_SCHEMA, orient="row")
    df = df.filter(pl.col("effective_date").is_not_null())
    df = df.with_columns(
        effective_ym=pl.col("effective_date").dt.strftime("%Y-%m"),
        priority=pl.when(pl.col("source") == "news_xlsx").then(0)
                  .when(pl.col("source") == "adjust_raw").then(1)
                  .otherwise(2),
    ).sort("priority").unique(
        subset=["index_code", "effective_ym", "constituent_code", "direction"], keep="first")

    # 第二遍：折叠跨月近重复——同一调整被 news_xlsx（effective≈公告日，偏早）与 adjust_raw
    # （真实 effective，偏晚约 17 天）同时记录，跨月时 ym 去重失效。按 (index, code, direction)
    # 组内 effective_date 升序，gap ≤ 45 天视为同次调整（定期调整间隔 ≥ 5 个月，窗口安全），
    # 保留较晚（真实 effective）的那条。
    df = df.sort(["index_code", "constituent_code", "direction", "effective_date"])
    df = df.with_columns(
        _gap=(pl.col("effective_date")
              - pl.col("effective_date").shift(1).over("index_code", "constituent_code", "direction"))
             .dt.total_days()
    ).with_columns(
        _new_cluster=pl.col("_gap").is_null() | (pl.col("_gap") > 45)
    ).with_columns(
        _cluster=pl.col("_new_cluster").cum_sum().over("index_code", "constituent_code", "direction")
    )
    n_before = df.height
    df = (df.sort(["index_code", "constituent_code", "direction", "_cluster", "effective_date", "priority"])
            .group_by(["index_code", "constituent_code", "direction", "_cluster"], maintain_order=True)
            .last())
    if df.height < n_before:
        print(f"  跨月近重复折叠：{n_before} → {df.height}（-{n_before - df.height}）")

    # --- e. 按 effective_date 年份分文件 ---
    out = Path(output_dir) / "index_adjust_history"
    out.mkdir(parents=True, exist_ok=True)
    df = df.with_columns(_year=pl.col("effective_date").dt.year())
    years = sorted(df["_year"].unique().to_list())
    for y in years:
        g = df.filter(pl.col("_year") == y).drop(
            ["effective_ym", "priority", "_year", "_gap", "_new_cluster", "_cluster"])
        g.write_parquet(out / f"{y}.parquet")
    print(f"Saved index_adjust_history: {len(df)} events, {len(years)} 年 → {out}")
    return len(df)


def _ah_extract_date(s):
    if isinstance(s, date):
        return s
    if not s:
        return None
    try:
        return date.fromisoformat(str(s))
    except ValueError:
        return None


# ============== index_constituent_history ==============

_CH_INDEX_NAMES = {"000300": "沪深300", "000905": "中证500"}

_CH_SCHEMA = {
    "index_code": pl.Utf8, "index_name": pl.Utf8,
    "constituent_code": pl.Utf8, "constituent_name": pl.Utf8,
    "start_date": pl.Date, "end_date": pl.Date,
}

_CH_DATESTEM_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _ch_read_weight_snapshot(path: Path):
    """读单份 weight 快照 → (snapshot_date, {code: name})。
    xlsx/xls 取「成份券代码/成份券名称」双列；csv 仅取「证券代码」（无名称列）。"""
    snap_date = date.fromisoformat(path.stem)
    names: dict[str, str] = {}
    if path.suffix.lower() == ".csv":
        with open(path, newline="", encoding="utf-8-sig") as fh:
            reader = csv.reader(fh)
            header = next(reader, None) or []
            code_idx = next((i for i, h in enumerate(header) if h.strip() == "证券代码"), None)
            if code_idx is None:
                return snap_date, {}
            for row in reader:
                if len(row) > code_idx:
                    code = _ah_clean_code(row[code_idx])
                    if code:
                        names[code] = ""
    else:
        sheets = _ah_read_excel_sheets(path)
        for rows in sheets.values():
            if not rows:
                continue
            header = [str(c).strip() for c in rows[0]]
            code_idx = next((i for i, h in enumerate(header) if "成份券代码" in h), None)
            if code_idx is None:
                continue
            name_idx = next((i for i, h in enumerate(header) if "成份券名称" in h), None)
            for r in rows[1:]:
                code = _ah_clean_code(r[code_idx]) if code_idx < len(r) else None
                if not code:
                    continue
                nm = r[name_idx].strip() if (name_idx is not None and name_idx < len(r)) else ""
                names[code] = nm
            break
    return snap_date, names


def _ch_back_derive(snapshot_codes, snapshot_date, events):
    """从最新快照在册集合倒推成份区间。
    events: [(effective_date, code, direction)] 已按 effective_date 降序。
    返回 segments [(code, start_date, end_date)]，end_date 为 None 表示仍在册。"""
    current = {c: [None, None] for c in snapshot_codes}  # code -> [start, end]
    segments = []
    for eff, code, direction in events:
        if direction == "out":  # T 日调出 → T 之前在册
            if code in current:
                print(f"  ⚠️ 异常：{code} 连续两次调出（缺中间调入），跳过")
                continue
            current[code] = [None, eff]
        elif direction == "in":  # T 日调入 → T 之前不在册
            if code not in current:
                print(f"  ⚠️ 异常：{code} 调入但不在册（孤儿 in @ {eff}），跳过")
                continue
            seg = current.pop(code)
            segments.append((code, eff, seg[1]))
    fallback_start = min((e[0] for e in events), default=None) or snapshot_date
    for code, (start, end) in current.items():
        segments.append((code, start or fallback_start, end))
    return segments


def convert_index_constituent_history(
    data_path: str,
    adjust_dir: str,
    output_dir: str,
    index_codes: list[str] | None = None,
) -> int:
    """基于最新 weight 锚点 + index_adjust_history，反推成份股入/出区间。
    输出 {output_dir}/index_constituent_history/{index_code}/{year}.parquet（区间跨年份展开）。"""
    if index_codes is None:
        index_codes = ["000300", "000905"]

    weight_root = Path(data_path) / "csindex" / "index_weight"
    adjust_glob = Path(adjust_dir) / "index_adjust_history"
    out_root = Path(output_dir) / "index_constituent_history"

    all_events = pl.read_parquet(str(adjust_glob / "*.parquet"))

    total = 0
    for code in index_codes:
        idx_name = _CH_INDEX_NAMES.get(code, code)
        wdir = weight_root / code
        if not wdir.is_dir():
            print(f"  跳过 {code}：无 weight 快照目录")
            continue
        snaps = [f for f in sorted(wdir.iterdir())
                 if f.is_file() and _CH_DATESTEM_RE.match(f.stem)]
        if not snaps:
            print(f"  跳过 {code}：无 weight 快照")
            continue
        latest = snaps[-1]
        T0, S0 = _ch_read_weight_snapshot(latest)
        print(f"  {code} {idx_name}: 锚点 {latest.name} (T0={T0})，在册 {len(S0)} 只")

        ev_df = (all_events.filter(pl.col("index_code") == code)
                 .filter(pl.col("effective_date").is_not_null())
                 .filter(pl.col("effective_date") <= T0)  # 排除锚点之后的未来调整
                 .select("effective_date", "constituent_code", "constituent_name", "direction")
                 .sort("effective_date", descending=True))
        effs = ev_df["effective_date"].to_list()
        ccodes = ev_df["constituent_code"].to_list()
        cnames = ev_df["constituent_name"].to_list()
        dirs = ev_df["direction"].to_list()
        print(f"  {code}: {len(effs)} 条调整事件")

        # 名称合并：事件名优先（按降序，先到先得=最新），快照名补全
        names: dict[str, str] = {}
        for nm, c in zip(cnames, ccodes):
            if nm and c not in names:
                names[c] = nm
        for c, nm in S0.items():
            if nm and c not in names:
                names[c] = nm

        segments = _ch_back_derive(set(S0.keys()), T0, list(zip(effs, ccodes, dirs)))

        # 年份展开写文件
        idx_dir = out_root / code
        idx_dir.mkdir(parents=True, exist_ok=True)
        for old in idx_dir.glob("*.parquet"):
            old.unlink()

        rows = []
        for c, start, end in segments:
            if start is None:
                continue
            end_year = T0.year if end is None else end.year
            for y in range(start.year, end_year + 1):
                rows.append((y, code, idx_name, c, names.get(c, ""), start, end))

        if not rows:
            print(f"  {code}: 无区间产出")
            continue
        df = pl.DataFrame(rows, schema={"_year": pl.Int64, **_CH_SCHEMA}, orient="row")
        for y in sorted(df["_year"].unique().to_list()):
            g = df.filter(pl.col("_year") == y).drop("_year")
            g.write_parquet(idx_dir / f"{y}.parquet")
        total += df.height
        print(f"  {code}: {len(segments)} 段 → 展开 {df.height} 行 → {df['_year'].n_unique()} 个年份文件")

    print(f"Saved index_constituent_history: {total} 行")
    return total