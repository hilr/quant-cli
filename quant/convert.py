"""数据转换模块"""
import polars as pl
from pathlib import Path


# 默认数据路径
DEFAULT_DATA_PATH = "/mnt/readonly_datasets"
OUTPUT_DATA_PATH = "/mnt/datasets"


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
    input_dir: str = "/mnt/datasets/margin_trade_history",
    output_dir: str = "/mnt/datasets/margin_trade_daily",
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
    input_dir: str = "/mnt/datasets/stock_quote_history",
    output_dir: str = "/mnt/datasets/stock_quote_adjusted",
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


# ============== ma ==============

def convert_ma(
    input_dir: str = "/mnt/datasets/stock_quote_adjusted",
    output_dir: str = "/mnt/datasets/stock_quote_ma",
) -> int:
    """基于前复权数据计算 close 的滚动均线"""
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    parquet_files = sorted(input_path.glob("*.parquet"))
    if not parquet_files:
        raise FileNotFoundError(f"No parquet files found in {input_path}")

    windows = [5, 10, 20, 60, 120, 250]

    count = 0
    for pf in parquet_files:
        df = pl.read_parquet(pf)
        df = df.sort("date")

        # 批量计算 close 和 turnover 的 MA
        df = df.with_columns([
            pl.col("close").rolling_mean(w).alias(f"ma{w}")
            for w in windows
        ] + [
            pl.col("turnover").rolling_mean(w).alias(f"turnover_ma{w}")
            for w in windows
        ])

        df.write_parquet(output_path / pf.name)
        count += 1

    print(f"Saved {count} stocks to {output_path}")
    return count


# ============== boll ==============

def convert_boll(
    input_dir: str = "/mnt/datasets/stock_quote_adjusted",
    output_dir: str = "/mnt/datasets/stock_quote_boll",
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

def convert_index_ma(
    input_dir: str = "/mnt/datasets/index_quote_history",
    output_dir: str = "/mnt/datasets/index_quote_ma",
) -> int:
    """基于指数行情计算 close 和 turnover 的滚动均线"""
    windows = [5, 10, 20, 60, 120, 250]
    return _compute_ma(input_dir, output_dir, windows, "indices")


def convert_index_boll(
    input_dir: str = "/mnt/datasets/index_quote_history",
    output_dir: str = "/mnt/datasets/index_quote_boll",
) -> int:
    """基于指数行情计算布林带（period=20/60, k=2）"""
    return _compute_boll(input_dir, output_dir, [20, 60], "indices")


def _compute_ma(input_dir: str, output_dir: str, windows: list[int], label: str) -> int:
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    parquet_files = sorted(input_path.glob("*.parquet"))
    if not parquet_files:
        raise FileNotFoundError(f"No parquet files found in {input_path}")
    count = 0
    for pf in parquet_files:
        df = pl.read_parquet(pf).sort("date")
        df = df.with_columns([
            pl.col("close").rolling_mean(w).alias(f"ma{w}")
            for w in windows
        ] + [
            pl.col("turnover").rolling_mean(w).alias(f"turnover_ma{w}")
            for w in windows
        ])
        df.write_parquet(output_path / pf.name)
        count += 1
    print(f"Saved {count} {label} to {output_path}")
    return count


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
    for offset in range(1, N + 1):
        df = df.with_columns([
            pl.col("high").shift(-offset).alias(f"_h{offset}"),
            pl.col("low").shift(-offset).alias(f"_l{offset}"),
        ])
    df = df.with_columns(pl.col("close").shift(-N).alias(f"_c{N}"))

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
    input_dir: str = "/mnt/datasets/stock_quote_adjusted",
    output_dir: str = "/mnt/datasets/stock_fwd_return",
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
    input_dir: str = "/mnt/datasets/stock_quote_adjusted",
    output_dir: str = "/mnt/datasets/stock_historical_stats",
) -> int:
    """计算股票过去250/120/60/20天的最高价、最低价、收益率、当前收盘价"""
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    parquet_files = sorted(input_path.glob("*.parquet"))
    if not parquet_files:
        raise FileNotFoundError(f"No parquet files found in {input_path}")

    periods = [250, 120, 60, 20]

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


# ============== volume spike filter ==============

def convert_filter_volume_spike(
    input_dir: str,
    min_market_cap: float,
    lookback_days: int = 5,
    min_ratio: float = 2.0,
    ma_period: int = 10,
    min_date: str = None,
    min_zt_days: int = 0,
    input_dir_adj: str = None,
) -> list[dict]:
    """筛选满足条件的股票：
    1. 市值 > min_market_cap
    2. 最新交易日 >= min_date（可选）
    3. 过去 lookback_days 个交易日内有成交额 > min_ratio * turnover_ma{ma_period}
    4. 过去60个交易日涨停天数 >= min_zt_days（可选）
    """
    input_path = Path(input_dir)
    parquet_files = sorted(input_path.glob("*.parquet"))
    if not parquet_files:
        raise FileNotFoundError(f"No parquet files found in {input_path}")

    adj_dir = Path(input_dir_adj) if input_dir_adj else Path(str(input_path).replace("ma", "adjusted"))
    results = []
    ma_col = f"turnover_ma{ma_period}"
    required_cols = ["date", "code", "turnover", ma_col, "market_cap"]

    for pf in parquet_files:
        try:
            df = pl.read_parquet(pf, columns=required_cols)
            df_adj = pl.read_parquet(adj_dir / pf.name)
        except Exception:
            continue

        df = df.sort("date", descending=False)
        df_adj = df_adj.sort("date", descending=False)

        if len(df) < 5 or len(df_adj) < 60:
            continue

        # 获取最新行的市值和日期
        latest = df.tail(1)
        if latest["market_cap"][0] < min_market_cap:
            continue

        # 检查最新交易日期
        if min_date and latest["date"][0] < min_date:
            continue

        # 获取最近 lookback_days 行
        if len(df) < lookback_days:
            lookback_df = df
        else:
            lookback_df = df.slice(-lookback_days)

        # 过滤 null 值并检查放量倍数
        lookback_df = lookback_df.filter(pl.col(ma_col).is_not_null())
        if len(lookback_df) == 0:
            continue

        lookback_df = lookback_df.with_columns([
            (pl.col("turnover") / pl.col(ma_col)).alias("ratio")
        ])
        spike_rows = lookback_df.filter(pl.col("ratio") >= min_ratio)

        # 检查涨停天数
        if min_zt_days > 0:
            df_60 = df_adj.tail(60)
            df_60 = df_60.with_columns([
                ((pl.col("close") - pl.col("prev_close")) / pl.col("prev_close") * 100).alias("pct_change")
            ])
            zt_10 = df_60.filter(pl.col("pct_change") >= 9.8)
            zt_20 = df_60.filter(pl.col("pct_change") >= 19.8)
            zt_days = len(zt_10) + len(zt_20)
            if zt_days < min_zt_days:
                continue
        else:
            zt_days = 0

        if len(spike_rows) > 0:
            # 获取放量最大的那一行
            spike_row = spike_rows.sort(pl.col("turnover"), descending=True).row(0, named=True)
            latest_row = latest.row(0, named=True)

            results.append({
                "code": latest_row["code"],
                "name": "",
                "market_cap": latest_row["market_cap"],
                "latest_date": latest_row["date"],
                "turnover": latest_row["turnover"],
                f"turnover_ma{ma_period}": latest_row[ma_col],
                "spike_date": spike_row["date"],
                "spike_turnover": spike_row["turnover"],
                f"spike_ma{ma_period}": spike_row[ma_col],
                "spike_ratio": spike_row["ratio"],
                "zt_days": zt_days,
            })

    # 按市值降序排序
    results.sort(key=lambda x: x["market_cap"], reverse=True)
    return results


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
    input_dir: str = "/mnt/datasets/fund_quote_history",
    output_dir: str = "/mnt/datasets/fund_quote_adjusted",
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
    shares_dir: str = "/mnt/datasets/fund_shares_history",
    quote_dir: str = "/mnt/datasets/fund_quote_adjusted",
    output_dir: str = "/mnt/datasets/fund_flow",
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