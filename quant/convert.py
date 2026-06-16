"""数据转换模块"""
import polars as pl
from pathlib import Path


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