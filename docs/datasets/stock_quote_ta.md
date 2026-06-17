[← 数据集索引](../../README.md#数据集索引)

# stock_quote_ta — 技术指标

| 项 | 内容 |
|---|------|
| 命令 | `uv run python -m quant.cli ta <input_dir> <output_dir>` |
| 输入 | `{input_dir}/{code}.parquet`（stock_quote_adjusted） |
| 输出 | `{output_dir}/{code}.parquet` |
| 逻辑 | sort by date → 一次计算均线、布林带、历史统计、前向收益、收益率、波动率等 |
| 产出 | 6207 只股票 |

**新增字段含义：**

均线（收盘价）：
| 字段 | 含义 |
|------|------|
| ma5, ma10, ma20, ma60, ma120, ma250 | 收盘价N日简单移动平均（SMA） |
| ema5, ema10, ema20, ema60, ema120, ema250 | 收盘价N日指数移动平均（EMA，α=2/(N+1)） |

均线（成交额）：
| 字段 | 含义 |
|------|------|
| turnover_ma5, turnover_ma10, turnover_ma20, turnover_ma60, turnover_ma120, turnover_ma250 | 成交额N日SMA |
| turnover_ema5, turnover_ema10, turnover_ema20, turnover_ema60, turnover_ema120, turnover_ema250 | 成交额N日EMA |

收益率：
| 字段 | 含义 |
|------|------|
| return_1d | 每日收益率 (close - prev_close) / prev_close |
| return_5d, return_10d, return_20d, return_60d, return_120d, return_250d | N日日化收益率 |

波动率：
| 字段 | 含义 |
|------|------|
| volatility_1d | 日波动率 ln(close / prev_close) |
| volatility_std10, volatility_std20, volatility_std40, volatility_std60, volatility_std120 | 日波动率N日滚动标准差 |

成交额标准差：
| 字段 | 含义 |
|------|------|
| turnover_std10, turnover_std20, turnover_std40 | 成交额N日滚动标准差 |

布林带（收盘价）：
| 字段 | 含义 |
|------|------|
| boll_mid20, boll_upper20, boll_lower20 | 20日布林中轨/上轨/下轨 |
| boll_mid60, boll_upper60, boll_lower60 | 60日布林中轨/上轨/下轨 |

布林带（成交额）：
| 字段 | 含义 |
|------|------|
| turnover_boll_mid20, turnover_boll_upper20, turnover_boll_lower20 | 成交额20日布林带 |
| turnover_boll_mid60, turnover_boll_upper60, turnover_boll_lower60 | 成交额60日布林带 |

历史统计：
| 字段 | 含义 |
|------|------|
| high_{20,60,120,250,500,750,1000} | 过去N日最高价 |
| low_{20,60,120,250,500,750,1000} | 过去N日最低价 |
| return_{20,60,120,250,500,750,1000} | 过去N日区间收益率（%） |

前向收益：
| 字段 | 含义 |
|------|------|
| fwd5_high, fwd5_low, fwd5_close | 未来5日最高/最低/收盘价 |
| fwd5_high_day, fwd5_low_day | 未来5日最高/最低价出现天数（1-5） |
| fwd5_high_pct, fwd5_low_pct, fwd5_final_pct | 未来5日最大涨幅/最大回撤/最终收益（%） |
| fwd10_* | 同上，未来10日 |
