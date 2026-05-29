# quant 命令行量化工具

基于 Polars 的命令行量化数据处理工具。

## 默认数据源

| 数据类型 | 数据源 |
|---------|--------|
| 股票每日成交 | finance_sina |
| 指数每日成交 | finance_sina |
| 融资融券 | eastmoney |
| 基金行情 | cninfo |
| 基金份额 | exchange_sse + exchange_szse |

---

## 数据集

### stock_quote_history — 股票行情历史

| 项 | 内容 |
|---|------|
| 命令 | `uv run python -m quant.cli stock-quote` |
| 输入 | `finance_sina/stock_quote/{date}.csv` |
| 输出 | `stock_quote_history/{code}.parquet`（每股票一个文件） |
| 字段 | date, code, 证券简称, prev_close, open, high, low, close, volume, turnover, market_cap, free_float_market_cap |
| 产出 | 6207 只股票 |

### stock_quote_adjusted — 前复权行情

| 项 | 内容 |
|---|------|
| 命令 | `uv run python -m quant.cli adjust` |
| 输入 | `stock_quote_history/{code}.parquet` |
| 输出 | `stock_quote_adjusted/{code}.parquet` |
| 逻辑 | 降序检测 prev_close ≠ 前一天 close → 每日调整因子 → cum_prod(shift).fill_null(1) → 所有价格列 × 累积因子 |
| 字段 | prev_close, open, high, low, close（已复权） + date, code + 其他原列 |
| 产出 | 6207 只股票 |

### stock_quote_ma — 均线

| 项 | 内容 |
|---|------|
| 命令 | `uv run python -m quant.cli ma` |
| 输入 | `stock_quote_adjusted/{code}.parquet` |
| 输出 | `stock_quote_ma/{code}.parquet` |
| 逻辑 | sort by date → rolling_mean(close, window) + rolling_mean(turnover, window) |
| 新增字段 | ma5, ma10, ma20, ma60, ma120, ma250, turnover_ma5, turnover_ma10, turnover_ma20, turnover_ma60, turnover_ma120, turnover_ma250 |
| 产出 | 6207 只股票 |

### stock_quote_boll — 布林带

| 项 | 内容 |
|---|------|
| 命令 | `uv run python -m quant.cli boll` |
| 输入 | `stock_quote_adjusted/{code}.parquet` |
| 输出 | `stock_quote_boll/{code}.parquet` |
| 逻辑 | mid = rolling_mean, std = rolling_std, upper = mid + 2*std, lower = mid - 2*std, period=[20, 60] |
| 新增字段 | boll_upper/mid/lower 20/60, turnover_boll_upper/mid/lower 20/60 |
| 产出 | 6207 只股票 |

### margin_trade_history — 融资融券历史

| 项 | 内容 |
|---|------|
| 命令 | `uv run python -m quant.cli margin-trade` |
| 输入 | `eastmoney/margin_trade/{date}.csv` |
| 输出 | `margin_trade_history/{code}.parquet` |
| 逻辑 | Schema A (深交所) → Schema B (上交所) 列名归一化，code 补零 6 位，数值列 Float64 |
| 字段 | date, code, name, margin_buy_total, margin_buy, margin_close, short_sell_total, short_sell_total_vol, short_sell_vol, short_close_vol |
| 产出 | 5117 只标的 |
| 附加 | 每股票计算：margin_net_change, short_net_change, short_vol_net_change（与上日余额之差） |

### margin_trade_daily — 融资融券每日净变化

| 项 | 内容 |
|---|------|
| 命令 | `uv run python -m quant.cli margin-trade-daily` |
| 输入 | `margin_trade_history/{code}.parquet` |
| 输出 | `margin_trade_daily/{date}.parquet` |
| 逻辑 | 读入所有标的的净变化列，按日期分组写入，已存在则跳过 |
| 字段 | code, name, margin_net_change, short_net_change, short_vol_net_change |
| 产出 | 3901 个日期文件 |

### fund_shares_history — 基金份额历史

| 项 | 内容 |
|---|------|
| 命令 | `uv run python -m quant.cli fund-shares` |
| 输入 | `exchange_sse/fund_shares/{date}.csv` + `exchange_sze/fund_shares/{date}.csv` |
| 输出 | `fund_shares_history/{code}.parquet` |
| 逻辑 | SSE: shares_10k × 10000, SZSE: shares 直接取，统一为 shares(Float64)，zfill(6) |
| 字段 | date, code, name, shares |
| 附加 | 每基金计算：share_change（与上日份额之差） |
| 产出 | 1989 只基金 |

### fund_quote_history — 基金行情历史

| 项 | 内容 |
|---|------|
| 命令 | `uv run python -m quant.cli fund-quote` |
| 输入 | `cninfo/fund_quote/{date}.csv` |
| 输出 | `fund_quote_history/{code}.parquet` |
| 逻辑 | exchange → 交易所 列名统一，数值列 Float64，zfill(6) |
| 字段 | date, code, name, prev_close, open, high, low, close, volume, turnover, net_value, 交易所, 折价率 |
| 产出 | 2614 只基金 |

### fund_flow — 基金资金流

| 项 | 内容 |
|---|------|
| 命令 | `uv run python -m quant.cli fund-flow` |
| 输入 | `fund_shares_history/{code}.parquet` + `fund_quote_history/{code}.parquet` |
| 输出 | `fund_flow/{code}.parquet` |
| 逻辑 | share_change × close = est_amount（估算每日加减仓金额） |
| 字段 | date, shares, share_change, close, net_value, est_amount |
| 产出 | 1988 只基金（两数据源均有覆盖的） |

---

## 数据流全景

```
finance_sina/stock_quote → stock_quote_history → stock_quote_adjusted → stock_quote_ma
                                                                     → stock_quote_boll

eastmoney/margin_trade → margin_trade_history → margin_trade_daily

exchange_sse/fund_shares ─┐
                          ├─→ fund_shares_history ─┐
exchange_sze/fund_shares ─┘                        ├─→ fund_flow
cninfo/fund_quote ─────────→ fund_quote_history ───┘
```