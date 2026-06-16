"""筛选功能模块

包含基于技术指标的股票筛选函数。当前提供：

- ``filter_volume_spike`` —— 扫描所有历史日期，找出每日成交额放量股票
- ``filter_ma_converge`` —— 单日筛选均线收敛股票
- ``filter_limit_up_pullback`` —— 单日筛选涨停后回踩的股票
"""
from datetime import datetime
from pathlib import Path

import polars as pl


# ============== filter_volume_spike ==============

def filter_volume_spike(
    input_dir: str,
    output_csv: str,
    min_market_cap: float,
    min_ratio: float = 2.0,
    ma_period: int = 20,
    min_date: str = None,
) -> int:
    """扫描所有历史日期，找出每日触发放量的股票，输出到单个 CSV。

    每只股票读一次，用 Polars 向量化筛选所有满足 turnover > ratio * turnover_ma 的日期。
    """
    input_path = Path(input_dir)
    parquet_files = sorted(input_path.glob("*.parquet"))
    if not parquet_files:
        raise FileNotFoundError(f"No parquet files found in {input_path}")

    ma_col = f"turnover_ma{ma_period}"
    required_cols = ["date", "code", "turnover", ma_col, "market_cap"]

    chunks = []
    for pf in parquet_files:
        try:
            df = pl.read_parquet(pf, columns=required_cols)
        except Exception:
            continue

        filter_expr = (
            pl.col(ma_col).is_not_null()
            & (pl.col("market_cap") >= min_market_cap)
            & (pl.col("turnover") >= min_ratio * pl.col(ma_col))
        )
        df = df.filter(filter_expr)
        if min_date:
            df = df.filter(pl.col("date") >= min_date)
        if df.height > 0:
            df = df.select([
                pl.col("date"),
                pl.col("code"),
                pl.col("market_cap"),
                pl.col("turnover"),
                pl.col(ma_col).alias(f"turnover_ma{ma_period}"),
                (pl.col("turnover") / pl.col(ma_col)).alias("spike_ratio"),
            ])
            chunks.append(df)

    if not chunks:
        Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
        header = f"date,code,market_cap,turnover,turnover_ma{ma_period},spike_ratio\n"
        with open(output_csv, "w", newline="", encoding="utf-8") as f:
            f.write(header)
        return 0

    combined = pl.concat(chunks).sort(["date", "market_cap"], descending=[False, True])
    Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
    combined.write_csv(output_csv)
    return combined.height


# ============== filter_ma_converge ==============

MA_CONVERGE_WINDOWS = [60, 120, 250]


def filter_ma_converge(
    ma_dir: str,
    date: str,
    min_market_cap: float = 200e8,
    min_turnover: float = 10e8,
    max_ma_spread: float = 0.1,
) -> list[dict]:
    """筛选均线收敛的股票：
    1. 指定日期市值 > min_market_cap
    2. 不是 ST 股票
    3. 当日成交额 >= min_turnover
    4. MA250 以内的均线中，max / min - 1 <= max_ma_spread
    """
    ma_path = Path(ma_dir)
    parquet_files = sorted(ma_path.glob("*.parquet"))
    if not parquet_files:
        raise FileNotFoundError(f"No parquet files found in {ma_path}")

    ma_cols = [f"ma{w}" for w in MA_CONVERGE_WINDOWS]
    required_cols = ["date", "code", "close", "turnover", "market_cap", "return_5d"] + ma_cols

    # 读取当天原始数据获取股票名称（用于过滤 ST）
    raw_csv = Path(ma_dir).parent.parent / "readonly_dataset" / "finance_sina" / "stock_quote" / f"{date}.csv"
    if raw_csv.exists():
        raw_df = pl.read_csv(raw_csv, columns=["code", "name"])
        raw_df = raw_df.with_columns(pl.col("code").cast(pl.String).str.zfill(6))
        st_codes = set(raw_df.filter(
            pl.col("name").str.to_uppercase().str.contains("ST")
        )["code"].to_list())
    else:
        st_codes = set()

    results = []

    for pf in parquet_files:
        try:
            df = pl.read_parquet(pf, columns=required_cols)
        except Exception:
            continue

        code = pf.stem
        if code in st_codes:
            continue

        row = df.filter(pl.col("date") == date)
        if len(row) == 0:
            continue

        r = row.row(0, named=True)

        if len(df) < 1000:
            continue

        if r["market_cap"] < min_market_cap:
            continue
        if r["turnover"] < min_turnover:
            continue
        if r["close"] >= r["ma120"]:
            continue
        if r.get("return_5d") is None or r["return_5d"] <= 0:
            continue

        ma_vals = [r[c] for c in ma_cols]
        if len(ma_vals) != len(ma_cols) or any(v is None for v in ma_vals):
            continue

        ma_max = max(ma_vals)
        ma_min = min(ma_vals)
        if ma_min == 0 or (ma_max / ma_min - 1) > max_ma_spread:
            continue

        results.append({
            "code": code,
            "close": r["close"],
            "market_cap": r["market_cap"],
            "turnover": r["turnover"],
            "ma_max": ma_max,
            "ma_min": ma_min,
            "ma_spread": ma_max / ma_min - 1,
        })

    results.sort(key=lambda x: x["market_cap"], reverse=True)
    return results


# ============== filter_limit_up_pullback ==============

# 涨停检测阈值：主板 10%，用 1.099 兼顾 prev_close 取整误差
LIMIT_UP_RATIO = 0.099


def filter_limit_up_pullback(
    input_dir: str,
    date: str,
    min_market_cap: float = 100e8,
    lookback_days: int = 10,
    max_calendar_span: int = 14,
    pullback_tolerance: float = 0.01,
) -> list[dict]:
    """筛选涨停后回踩的股票：

    1. 指定日期 market_cap >= min_market_cap
    2. 指定日期前 lookback_days 个交易日内（窗口跨度 <= max_calendar_span 自然日，
       用于排除停牌），出现过涨停（close >= round(prev_close * 1.099, 2)）
    3. 指定日期 close < (1 + pullback_tolerance) * 涨停日 prev_close

    多次涨停取最近一次作为锚点。
    """
    input_path = Path(input_dir)
    parquet_files = sorted(input_path.glob("*.parquet"))
    if not parquet_files:
        raise FileNotFoundError(f"No parquet files found in {input_path}")

    required_cols = ["date", "code", "close", "prev_close", "market_cap"]
    target_date = datetime.strptime(date, "%Y-%m-%d").date()

    results = []

    for pf in parquet_files:
        code = pf.stem

        try:
            df = pl.read_parquet(pf, columns=required_cols)
        except Exception:
            continue

        df = df.sort("date")

        dates_list = df["date"].to_list()
        try:
            target_idx = dates_list.index(date)
        except ValueError:
            continue

        target_row = df.row(target_idx, named=True)
        target_close = target_row["close"]
        target_market_cap = target_row["market_cap"]
        if target_close is None or target_market_cap is None:
            continue
        if target_market_cap < min_market_cap:
            continue

        window_start = max(0, target_idx - lookback_days)
        window_df = df.slice(window_start, target_idx - window_start)
        if window_df.height == 0:
            continue

        window_first_date = datetime.strptime(window_df["date"][0], "%Y-%m-%d").date()
        if (target_date - window_first_date).days > max_calendar_span:
            continue

        zt_threshold = (pl.col("prev_close") * (1 + LIMIT_UP_RATIO)).round(2)
        zt_rows = window_df.with_columns(
            (pl.col("close") >= zt_threshold).alias("_is_zt")
        ).filter(pl.col("_is_zt"))
        if zt_rows.height == 0:
            continue

        zt_row = zt_rows.row(-1, named=True)
        zt_date = zt_row["date"]
        zt_prev_close = zt_row["prev_close"]
        if zt_prev_close is None or zt_prev_close <= 0:
            continue

        if target_close >= (1 + pullback_tolerance) * zt_prev_close:
            continue

        results.append({
            "code": code,
            "date": date,
            "close": target_close,
            "market_cap": target_market_cap,
            "zt_date": zt_date,
            "zt_prev_close": zt_prev_close,
            "pullback_pct": target_close / zt_prev_close - 1,
        })

    results.sort(key=lambda x: x["market_cap"], reverse=True)
    return results
