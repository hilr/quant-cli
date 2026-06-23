"""数据转换模块"""
import csv
import re
import zipfile
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
    """对「当期值」指标，用 2 月累计值的一半补全 1、2 月当期值缺失（统计局 1-2 月
    合并发布所致）。按 indicator 名自动配对：含「当期值」的，配对其「累计值」变体。
    合计平分：1 月 = 2 月累计 / 2，2 月 = 2 月累计 / 2（与官方累计值自洽）。
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
        feb = wide.filter(pl.col("_m") == 2).select("_y", pl.col(acc).alias("_feb"))
        wide = wide.join(feb, on="_y", how="left")
        cond = pl.col("_m").is_in([1, 2]) & pl.col(cur).is_null() & pl.col("_feb").is_not_null()
        wide = wide.with_columns(pl.when(cond).then(pl.col("_feb") / 2).otherwise(pl.col(cur)).alias(cur))
        wide = wide.drop("_feb")
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
# 早期 A 股股票数少（2010 ~1700 只、2015 ~2400 只、2020 ~3800 只），用 1000 行阈值过滤
# 半截/测试文件但保留 2010 起的完整历史
_TURNOVER_MIN_ROWS = 1000


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
    start_year: int = 2010,
) -> int:
    """全 A 股日成交额集中度（gini/alpha/top5-median/hhi/cr10），宽表，2010 起。"""
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
        x = (df.filter(pl.col("turnover") > 0)["turnover"].to_numpy().astype(float))
        m = _concentration_metrics(x)
        m["date"] = dt
        m["stock_count"] = int(len(x))
        records.append(m)
        if (i + 1) % 200 == 0:
            print(f"  {i + 1}/{len(dates)}...")

    if not records:
        raise RuntimeError("无有效数据")

    out_df = (pl.DataFrame(records)
              .select(["date", "gini", "alpha", "top5_ratio", "hhi", "cr10", "stock_count"])
              .sort("date"))
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    out_df.write_csv(out_path / "turnover_concentration.csv")
    print(f"Saved turnover_concentration: {len(out_df)} rows to {out_path}")
    return len(out_df)