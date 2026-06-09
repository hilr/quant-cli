# quant 命令行量化工具

基于 Polars 的命令行量化数据处理工具。

## 路径约定

| 类型 | 路径 |
|------|------|
| 只读原始数据 | `/mnt/readonly_dataset` |
| 生成数据集 | `/mnt/dataset` |

所有路径参数必须作为命令行参数传入，不可硬编码。

## 默认数据源

| 数据类型 | 数据源 |
|---------|--------|
| 股票每日成交 | finance_sina |
| 指数每日成交 | finance_sina |
| 融资融券 | eastmoney |
| 基金行情 | cninfo |
| 基金份额 | exchange_sse + exchange_szse |

---

## 刷新全部数据集

### refresh — 按依赖顺序刷新

| 项 | 内容 |
|---|------|
| 命令 | `uv run python -m quant.cli refresh [data_path] [output_dir] [options]` |
| 逻辑 | 按4阶段依赖图自动执行，同阶段内并行 |

**参数：**
| 参数 | 说明 | 默认值 |
|------|------|--------|
| data_path | 原始数据目录 | /mnt/readonly_dataset |
| output_dir | 输出目录 | /mnt/dataset |
| workers | 并行进程数 | 2 |

**执行阶段：**
| 阶段 | 内容 | 并行数 |
|------|------|--------|
| Stage 1 | 原始→历史（stock_quote, margin_trade, fund_shares, fund_quote, index_quote） | 5 |
| Stage 2 | 前复权（stock_adjusted, fund_adjusted） | 2 |
| Stage 3 | 衍生指标（ma, boll, historical_stats, fwd_return, index_ma, index_boll） | 6 |
| Stage 4 | 聚合（margin_trade_daily, fund_flow） | 2 |

**使用示例：**
```bash
# 默认 2 进程
uv run python -m quant.cli refresh

# 4 进程并行
uv run python -m quant.cli refresh /mnt/readonly_dataset /mnt/dataset --workers 4

# 串行执行
uv run python -m quant.cli refresh --workers 1
```

**注意：** 使用 `ProcessPoolExecutor` 实现多进程并行，`workers` 控制每个阶段内的最大并发进程数。

---

## 数据集

### stock_quote_history — 股票行情历史

| 项 | 内容 |
|---|------|
| 命令 | `uv run python -m quant.cli stock-quote <data_path> <source> <output_dir>` |
| 输入 | `{data_path}/{source}/stock_quote/{date}.csv` |
| 输出 | `{output_dir}/stock_quote_history/{code}.parquet`（每股票一个文件） |
| 逻辑 | 读取每日 CSV，合并后按 code+date 排序，分股票写入 parquet |
| 字段 | date, code, 证券简称, prev_close, open, high, low, close, volume, turnover, market_cap, free_float_market_cap |
| 产出 | 6207 只股票 |

**字段含义：**
| 字段 | 含义 |
|------|------|
| date | 交易日期 |
| code | 股票代码（6位，补零） |
| 证券简称 | 股票名称 |
| prev_close | 昨收价 |
| open | 开盘价 |
| high | 最高价 |
| low | 最低价 |
| close | 收盘价 |
| volume | 成交量 |
| turnover | 成交额 |
| market_cap | 总市值 |
| free_float_market_cap | 流通市值 |

---

### stock_quote_adjusted — 前复权行情

| 项 | 内容 |
|---|------|
| 命令 | `uv run python -m quant.cli adjust <input_dir> <output_dir>` |
| 输入 | `{input_dir}/{code}.parquet`（stock_quote_history） |
| 输出 | `{output_dir}/{code}.parquet` |
| 逻辑 | 降序检测 prev_close ≠ 前一天 close → 每日调整因子 → cum_prod(shift).fill_null(1) → 所有价格列 × 累积因子 |
| 字段 | prev_close, open, high, low, close（已复权） + date, code + 其他原列 |
| 产出 | 6207 只股票 |

**字段含义：**
| 字段 | 含义 |
|------|------|
| prev_close | 昨收价（前复权） |
| open | 开盘价（前复权） |
| high | 最高价（前复权） |
| low | 最低价（前复权） |
| close | 收盘价（前复权） |

---

### stock_quote_ma — 均线

| 项 | 内容 |
|---|------|
| 命令 | `uv run python -m quant.cli ma <input_dir> <output_dir>` |
| 输入 | `{input_dir}/{code}.parquet`（stock_quote_adjusted） |
| 输出 | `{output_dir}/{code}.parquet` |
| 逻辑 | sort by date → rolling_mean(close, window) + rolling_mean(turnover, window) |
| 新增字段 | ma5, ma10, ma20, ma60, ma120, ma250, turnover_ma5, turnover_ma10, turnover_ma20, turnover_ma60, turnover_ma120, turnover_ma250 |
| 产出 | 6207 只股票 |

**新增字段含义：**
| 字段 | 含义 |
|------|------|
| ma5 | 5日均线（收盘价） |
| ma10 | 10日均线（收盘价） |
| ma20 | 20日均线（收盘价） |
| ma60 | 60日均线（收盘价） |
| ma120 | 120日均线（收盘价） |
| ma250 | 250日均线（收盘价） |
| turnover_ma5 | 5日成交额均线 |
| turnover_ma10 | 10日成交额均线 |
| turnover_ma20 | 20日成交额均线 |
| turnover_ma60 | 60日成交额均线 |
| turnover_ma120 | 120日成交额均线 |
| turnover_ma250 | 250日成交额均线 |

---

### stock_quote_boll — 布林带

| 项 | 内容 |
|---|------|
| 命令 | `uv run python -m quant.cli boll <input_dir> <output_dir>` |
| 输入 | `{input_dir}/{code}.parquet`（stock_quote_adjusted） |
| 输出 | `{output_dir}/{code}.parquet` |
| 逻辑 | mid = rolling_mean, std = rolling_std, upper = mid + 2*std, lower = mid - 2*std, period=[20, 60] |
| 新增字段 | boll_mid20, boll_upper20, boll_lower20, boll_mid60, boll_upper60, boll_lower60, turnover_boll_* |
| 产出 | 6207 只股票 |

**新增字段含义：**
| 字段 | 含义 |
|------|------|
| boll_mid20 | 20日布林中轨（收盘价均值） |
| boll_upper20 | 20日布林上轨（中轨+2倍标准差） |
| boll_lower20 | 20日布林下轨（中轨-2倍标准差） |
| boll_mid60 | 60日布林中轨 |
| boll_upper60 | 60日布林上轨 |
| boll_lower60 | 60日布林下轨 |
| turnover_boll_mid20/upper20/lower20 | 成交额布林带（20日） |
| turnover_boll_mid60/upper60/lower60 | 成交额布林带（60日） |

---

### stock_historical_stats — 历史统计

| 项 | 内容 |
|---|------|
| 命令 | `uv run python -m quant.cli historical-stats <input_dir> <output_dir>` |
| 输入 | `{input_dir}/{code}.parquet`（stock_quote_adjusted） |
| 输出 | `{output_dir}/{code}.parquet` |
| 逻辑 | rolling_max(high), rolling_min(low), return=(close-close_shift)/close_shift*100 |
| 新增字段 | high_20/60/120/250, low_20/60/120/250, return_20/60/120/250, close_20/60/120/250 |
| 产出 | 6207 只股票 |

**新增字段含义：**
| 字段 | 含义 |
|------|------|
| high_20 | 过去20日最高价 |
| low_20 | 过去20日最低价 |
| return_20 | 过去20日收益率（%） |
| close_20 | 当前收盘价 |
| high_60 | 过去60日最高价 |
| low_60 | 过去60日最低价 |
| return_60 | 过去60日收益率（%） |
| close_60 | 当前收盘价 |
| high_120 | 过去120日最高价 |
| low_120 | 过去120日最低价 |
| return_120 | 过去120日收益率（%） |
| close_120 | 当前收盘价 |
| high_250 | 过去250日最高价 |
| low_250 | 过去250日最低价 |
| return_250 | 过去250日收益率（%） |
| close_250 | 当前收盘价 |

---

### stock_fwd_return — 前向收益

| 项 | 内容 |
|---|------|
| 命令 | `uv run python -m quant.cli fwd-return <input_dir> <output_dir>` |
| 输入 | `{input_dir}/{code}.parquet`（stock_quote_adjusted） |
| 输出 | `{output_dir}/{code}.parquet` |
| 逻辑 | 计算未来N日的最高/最低价、收盘价及收益率百分比 |
| 新增字段 | fwd5_*, fwd10_*（high/high_day/high_pct/low/low_day/low_pct/close/final_pct） |
| 产出 | 6207 只股票 |

**新增字段含义：**
| 字段 | 含义 |
|------|------|
| fwd5_high | 未来5日最高价 |
| fwd5_high_day | 达到最高价的天数（1-5） |
| fwd5_high_pct | 最高价涨幅（%） |
| fwd5_low | 未来5日最低价 |
| fwd5_low_day | 达到最低价的天数（1-5） |
| fwd5_low_pct | 最低价跌幅（%） |
| fwd5_close | 未来5日收盘价 |
| fwd5_final_pct | 5日收益率（%） |
| fwd10_* | 同上，未来10日 |

---

### margin_trade_history — 融资融券历史

| 项 | 内容 |
|---|------|
| 命令 | `uv run python -m quant.cli margin-trade <data_path> <source> <output_dir>` |
| 输入 | `{data_path}/{source}/margin_trade/{date}.csv` |
| 输出 | `{output_dir}/margin_trade_history/{code}.parquet` |
| 逻辑 | Schema A (深交所) → Schema B (上交所) 列名归一化，code 补零 6 位，数值列 Float64 |
| 字段 | date, code, name, margin_buy_total, margin_buy, margin_close, short_sell_total, short_sell_total_vol, short_sell_vol, short_close_vol |
| 产出 | 5117 只标的 |
| 附加 | 每股票计算：margin_net_change, short_net_change, short_vol_net_change（与上日余额之差） |

**字段含义：**
| 字段 | 含义 |
|------|------|
| margin_buy_total | 融资余额 |
| margin_buy | 融资买入额 |
| margin_close | 融资偿还额 |
| short_sell_total | 融券余额 |
| short_sell_total_vol | 融券余量 |
| short_sell_vol | 融券卖出量 |
| short_close_vol | 融券偿还量 |
| margin_net_change | 融资余额净变化 |
| short_net_change | 融券余额净变化 |
| short_vol_net_change | 融券余量净变化 |

---

### margin_trade_daily — 融资融券每日净变化

| 项 | 内容 |
|---|------|
| 命令 | `uv run python -m quant.cli margin-trade-daily <input_dir> <output_dir>` |
| 输入 | `{input_dir}/{code}.parquet`（margin_trade_history） |
| 输出 | `{output_dir}/{date}.parquet` |
| 逻辑 | 读入所有标的的净变化列，按日期分组写入，已存在则跳过 |
| 字段 | date, code, name, margin_net_change, short_net_change, short_vol_net_change |
| 产出 | 3901 个日期文件 |

---

### fund_shares_history — 基金份额历史

| 项 | 内容 |
|---|------|
| 命令 | `uv run python -m quant.cli fund-shares <data_path> <output_dir>` |
| 输入 | `{data_path}/exchange_sse/fund_shares/{date}.csv` + `{data_path}/exchange_szse/fund_shares/{date}.csv` |
| 输出 | `{output_dir}/fund_shares_history/{code}.parquet` |
| 逻辑 | SSE: shares_10k × 10000, SZSE: shares 直接取，统一为 shares(Float64)，zfill(6) |
| 字段 | date, code, name, shares, share_change |
| 产出 | 1989 只基金 |

**字段含义：**
| 字段 | 含义 |
|------|------|
| shares | 基金份额 |
| share_change | 份额变动（与上日差额） |

---

### fund_quote_history — 基金行情历史

| 项 | 内容 |
|---|------|
| 命令 | `uv run python -m quant.cli fund-quote <data_path> <source> <output_dir>` |
| 输入 | `{data_path}/{source}/fund_quote/{date}.csv` |
| 输出 | `{output_dir}/fund_quote_history/{code}.parquet` |
| 逻辑 | exchange → 交易所 列名统一，数值列 Float64，zfill(6) |
| 字段 | date, code, name, prev_close, open, high, low, close, volume, turnover, net_value, 交易所, 折价率 |
| 产出 | 2614 只基金 |

**字段含义：**
| 字段 | 含义 |
|------|------|
| prev_close | 昨收价 |
| open | 开盘价 |
| high | 最高价 |
| low | 最低价 |
| close | 收盘价 |
| volume | 成交量 |
| turnover | 成交额 |
| net_value | 单位净值 |
| 交易所 | 交易所（SSE/SZSE） |
| 折价率 | 折价率（%） |

---

### fund_flow — 基金资金流

| 项 | 内容 |
|---|------|
| 命令 | `uv run python -m quant.cli fund-flow <shares_dir> <quote_dir> <output_dir>` |
| 输入 | `{shares_dir}/{code}.parquet`（fund_shares_history） + `{quote_dir}/{code}.parquet`（fund_quote_history） |
| 输出 | `{output_dir}/{code}.parquet` |
| 逻辑 | share_change × close = est_amount（估算每日加减仓金额） |
| 字段 | date, shares, share_change, close, net_value, est_amount |
| 产出 | 1988 只基金（两数据源均有覆盖的） |

**字段含义：**
| 字段 | 含义 |
|------|------|
| shares | 基金份额 |
| share_change | 份额变动 |
| close | 收盘价 |
| net_value | 单位净值 |
| est_amount | 估算资金流（份额变动 × 收盘价） |

---

## 筛选功能

### filter_volume_spike — 放量股票筛选

| 项 | 内容 |
|---|------|
| 命令 | `uv run python -m quant.cli filter-volume-spike <input_dir> <min_market_cap> [options]` |
| 输入 | `{input_dir}/{code}.parquet`（stock_quote_ma） |
| 输出 | 控制台表格（可选 CSV 文件） |
| 筛选条件 | 市值 > min_market_cap，过去 N 日内有成交额 > M 倍 20日均线 |

**参数：**
| 参数 | 说明 | 默认值 |
|------|------|--------|
| input_dir | 输入目录（stock_quote_ma） | 必填 |
| min_market_cap | 最小市值（单位：元） | 必填（100亿=10000000000） |
| lookback-days | 回看交易日数 | 10 |
| volume-multiplier | 放量倍数 | 2.0 |
| output-csv | 输出 CSV 文件路径 | None（仅控制台显示） |

**使用示例：**
```bash
# 筛选市值100亿以上，过去10日内有2倍放量的股票
uv run python -m quant.cli filter-volume-spike /mnt/dataset/stock_quote_ma 10000000000

# 自定义参数
uv run python -m quant.cli filter-volume-spike /mnt/dataset/stock_quote_ma 50000000000 --lookback-days 15 --volume-multiplier 3.0

# 导出结果
uv run python -m quant.cli filter-volume-spike /mnt/dataset/stock_quote_ma 10000000000 --output-csv /tmp/volume_spike.csv
```

**输出示例：**
```
╒═════════╤══════════╤════════════╤════════════╤═════════════╤══════════════╤═══════════════╕
│ 代码    │ 名称     │ 市值       │ 最新日期   │ 成交额     │ 20日均线   │ 放量日期    │ 放量倍数   │
╞═════════╪══════════╪════════════╪════════════╪═════════════╪══════════════╪═══════════════╡
│ 000001  │ 平安银行  │ 250亿      │ 2024-06-07 │ 500M        │ 200M        │ 2024-06-03   │ 2.5x       │
└─────────┴──────────┴─────────────┴────────────┴─────────────┴──────────────┴─────────────┘

放量股票筛选结果 (共 156 只)
```

**注意：** 数据集只包含交易日数据，`lookback-days` 参数使用交易日数而非自然日。14个自然日约等于10个交易日。

---

## 数据流全景

```
┌─────────────────────────────────────────────────────────────────┐
│                        只读原始数据                              │
│  /mnt/readonly_dataset/finance_sina/stock_quote/              │
│  /mnt/readonly_dataset/finance_sina/index_quote/              │
│  /mnt/readonly_dataset/eastmoney/margin_trade/                │
│  /mnt/readonly_dataset/cninfo/fund_quote/                     │
│  /mnt/readonly_dataset/exchange_sse/fund_shares/              │
│  /mnt/readonly_dataset/exchange_szse/fund_shares/             │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                        股票数据流                                │
├─────────────────────────────────────────────────────────────────┤
│  stock_quote_history ← finance_sina/stock_quote                │
│       ↓                                                         │
│  stock_quote_adjusted (前复权)                                  │
│       ├─→ stock_quote_ma (均线)                                 │
│       ├─→ stock_quote_boll (布林带)                             │
│       ├─→ stock_historical_stats (历史统计)                     │
│       └─→ stock_fwd_return (前向收益)                           │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                        融资融券数据流                            │
├─────────────────────────────────────────────────────────────────┤
│  margin_trade_history ← eastmoney/margin_trade                 │
│       ↓                                                         │
│  margin_trade_daily (每日净变化)                                │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                        基金数据流                                │
├─────────────────────────────────────────────────────────────────┤
│  fund_shares_history ← exchange_sse/fund_shares                 │
│                     + exchange_szse/fund_shares                 │
│       ↓                                                         │
│       ├─→ fund_flow ←──────────────────────┐                   │
│       │                                     │                   │
│  fund_quote_history ← cninfo/fund_quote ───┘                   │
└─────────────────────────────────────────────────────────────────┘
```