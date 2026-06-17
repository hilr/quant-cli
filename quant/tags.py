"""Tag 层 —— 最简单的「股票 × 日期」布尔标记。

每个 tag 是一个纯函数：接收一只股票的完整 DataFrame（通常来自 stock_quote_ta），
返回带新增 ``tag_*`` 布尔列的 DataFrame。

filter 层在 tag 之上做组合查询，例如 ``filter_by_tags(date, tags=["surge_3d", "volume_spike"])``
返回当日同时命中多个 tag 的股票。

新增 tag 时：
1. 在本文件加 ``tag_xxx(df, ...) -> pl.DataFrame``
2. 注册到 ``TAG_FUNCS`` dict（key 是简短名，value 是函数）
3. 注册到 ``TAG_REQUIRED_COLUMNS``（filter 按需读列时用）
"""
import polars as pl


# 默认参数：保持与原 filter 一致，方便迁移
DEFAULT_SURGE_MIN_TOTAL_RETURN = 0.10
DEFAULT_VOLUME_MA_PERIOD = 20
DEFAULT_VOLUME_RATIO = 2.0
DEFAULT_LIMIT_UP_RATIO = 0.099  # 主板 10%，预留 0.1% 给取整


def tag_surge_3d(
    df: pl.DataFrame,
    min_total_return: float = DEFAULT_SURGE_MIN_TOTAL_RETURN,
) -> pl.DataFrame:
    """连续 3 日上涨且累计涨幅 >= ``min_total_return``。

    - 过去 3 个交易日（含当日）每日 close > prev_close
    - close[t] / close[t-3] - 1 >= min_total_return
    """
    out = df.sort("date")
    out = out.with_columns(
        pl.col("close").shift(3).alias("_close_3d_ago")
    )
    # 3 日每日上涨：当日 close > prev_close，再用 shift 检查前两日
    today_up = pl.col("close") > pl.col("prev_close")
    yesterday_up = today_up.shift(1)
    day_before_up = today_up.shift(2)
    out = out.with_columns(
        (
            today_up & yesterday_up & day_before_up
            & (pl.col("close") / pl.col("_close_3d_ago") - 1 >= min_total_return)
        ).alias("tag_surge_3d")
    )
    return out.drop("_close_3d_ago")


def tag_volume_spike(
    df: pl.DataFrame,
    ma_period: int = DEFAULT_VOLUME_MA_PERIOD,
    ratio: float = DEFAULT_VOLUME_RATIO,
) -> pl.DataFrame:
    """成交额 >= ``ratio`` × turnover_ma{ma_period}。"""
    ma_col = f"turnover_ma{ma_period}"
    return df.with_columns(
        (
            pl.col(ma_col).is_not_null()
            & (pl.col("turnover") >= ratio * pl.col(ma_col))
        ).alias("tag_volume_spike")
    )


def tag_limit_up(
    df: pl.DataFrame,
    ratio: float = DEFAULT_LIMIT_UP_RATIO,
) -> pl.DataFrame:
    """close >= round(prev_close × (1 + ratio), 2)。"""
    return df.with_columns(
        (
            pl.col("prev_close").is_not_null()
            & (pl.col("close") >= (pl.col("prev_close") * (1 + ratio)).round(2))
        ).alias("tag_limit_up")
    )


# tag 名 → 函数（filter_by_tags 用这个名字查 tag）
TAG_FUNCS = {
    "surge_3d": tag_surge_3d,
    "volume_spike": tag_volume_spike,
    "limit_up": tag_limit_up,
}

# 每个 tag 需要从 parquet 读的原始列（filter_by_tags 按需读，避免读全表）
TAG_REQUIRED_COLUMNS = {
    "surge_3d": ["date", "code", "close", "prev_close", "market_cap"],
    "volume_spike": ["date", "code", "turnover", "turnover_ma20", "market_cap"],
    "limit_up": ["date", "code", "close", "prev_close", "market_cap"],
}


def add_tags(df: pl.DataFrame, tags: list[str]) -> pl.DataFrame:
    """对一只股票的 df 应用多个 tag，返回带所有 tag_* 列的 df。

    未知 tag 抛 ValueError。
    """
    out = df
    for t in tags:
        if t not in TAG_FUNCS:
            raise ValueError(f"Unknown tag: {t}. Available: {list(TAG_FUNCS.keys())}")
        out = TAG_FUNCS[t](out)
    return out
