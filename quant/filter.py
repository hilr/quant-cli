"""筛选功能模块

filter 层基于 ``quant.tags`` 做 (股票, 日期) 维度的组合查询。

当前提供：

- ``filter_by_tags`` —— 单日 AND 组合多个 tag
- ``filter_limit_up_pullback`` —— 复合 filter：近期 tag_limit_up + 回踩到涨停前价位
- ``filter_volume_spike`` —— 扫描所有历史日期，找出每日成交额放量股票（批量导出版）
- ``filter_ma_converge`` —— 单日筛选均线收敛股票（条件较复杂，未拆 tag）
"""
from datetime import datetime
from pathlib import Path

import polars as pl

from quant.tags import TAG_REQUIRED_COLUMNS, add_tags, tag_limit_up


# ============== filter_by_tags ==============

def _load_st_codes(input_path: Path, date: str) -> set[str]:
    """读取指定日期原始行情，返回 name 含 ST 的 code 集合。"""
    raw_csv = input_path.parent.parent / "readonly_dataset" / "finance_sina" / "stock_quote" / f"{date}.csv"
    if not raw_csv.exists():
        return set()
    raw_df = pl.read_csv(raw_csv, columns=["code", "name"])
    raw_df = raw_df.with_columns(pl.col("code").cast(pl.String).str.zfill(6))
    return set(raw_df.filter(
        pl.col("name").str.to_uppercase().str.contains("ST")
    )["code"].to_list())


def filter_by_tags(
    input_dir: str,
    date: str,
    tags: list[str],
    min_market_cap: float = 0,
    exclude_st: bool = True,
) -> list[dict]:
    """筛选指定日期同时命中所有 ``tags`` 的股票（AND 组合）。

    每只股票读一次，应用所有 tag 函数，留下 ``date`` 当日 ``tag_*`` 全为 True 的股票。

    输出每条包含：code, date, close, market_cap, 以及命中的每个 ``tag_*`` 列。
    """
    if not tags:
        raise ValueError("tags 不能为空")

    input_path = Path(input_dir)
    parquet_files = sorted(input_path.glob("*.parquet"))
    if not parquet_files:
        raise FileNotFoundError(f"No parquet files found in {input_path}")

    required_cols = sorted(set(["date", "code", "close", "market_cap"]) |
                           {c for t in tags for c in TAG_REQUIRED_COLUMNS[t]})

    st_codes = _load_st_codes(input_path, date) if exclude_st else set()

    results = []
    for pf in parquet_files:
        code = pf.stem
        if code in st_codes:
            continue

        try:
            df = pl.read_parquet(pf, columns=required_cols)
        except Exception:
            continue

        df = add_tags(df, tags)

        row = df.filter(pl.col("date") == date)
        if row.height == 0:
            continue

        r = row.row(0, named=True)
        if r["close"] is None or r["market_cap"] is None:
            continue
        if r["market_cap"] < min_market_cap:
            continue

        tag_cols = [f"tag_{t}" for t in tags]
        if any(r.get(c) is not True for c in tag_cols):
            continue

        out = {"code": code, "date": date, "close": r["close"], "market_cap": r["market_cap"]}
        for c in tag_cols:
            out[c] = r[c]
        results.append(out)

    results.sort(key=lambda x: x["market_cap"], reverse=True)
    return results


# ============== filter_volume_spike（批量导出版） ==============

def filter_volume_spike(
    input_dir: str,
    output_csv: str,
    min_market_cap: float,
    min_ratio: float = 2.0,
    ma_period: int = 20,
    min_date: str = None,
) -> int:
    """扫描所有历史日期，找出每日成交额放量股票，输出到单个 CSV。

    内部走 ``tag_volume_spike``，把所有命中的日期全部写出。
    """
    from quant.tags import tag_volume_spike

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

        df = tag_volume_spike(df, ma_period=ma_period, ratio=min_ratio)
        df = df.filter(pl.col("tag_volume_spike"))
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

    st_codes = _load_st_codes(ma_path, date)

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

def filter_limit_up_pullback(
    input_dir: str,
    date: str,
    min_market_cap: float = 100e8,
    lookback_days: int = 10,
    max_calendar_span: int = 14,
    pullback_tolerance: float = 0.01,
    limit_up_ratio: float = 0.099,
) -> list[dict]:
    """复合 filter：近期涨停后回踩到涨停前价位的股票。

    时间窗口条件（属于 filter 层，不是 tag 层）：
    1. 非 ST 股票
    2. 指定日期 market_cap >= min_market_cap
    3. 指定日期前 lookback_days 个交易日内（窗口跨度 <= max_calendar_span 自然日，
       用于排除停牌），出现过 ``tag_limit_up``
    4. 指定日期 close < (1 + pullback_tolerance) * 涨停日 prev_close

    多次涨停取最近一次作为锚点。
    """
    input_path = Path(input_dir)
    parquet_files = sorted(input_path.glob("*.parquet"))
    if not parquet_files:
        raise FileNotFoundError(f"No parquet files found in {input_path}")

    required_cols = ["date", "code", "close", "prev_close", "market_cap"]
    target_date = datetime.strptime(date, "%Y-%m-%d").date()
    st_codes = _load_st_codes(input_path, date)

    results = []

    for pf in parquet_files:
        code = pf.stem
        if code in st_codes:
            continue

        try:
            df = pl.read_parquet(pf, columns=required_cols)
        except Exception:
            continue

        df = df.sort("date")
        df = tag_limit_up(df, ratio=limit_up_ratio)

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

        zt_rows = window_df.filter(pl.col("tag_limit_up"))
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
