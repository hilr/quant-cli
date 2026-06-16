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

### stock_quote_ta — 技术指标

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
| ma5, ma10, ma20, ma60, ma120, ma250 | 收盘价N日均线 |

均线（成交额）：
| 字段 | 含义 |
|------|------|
| turnover_ma5, turnover_ma10, turnover_ma20, turnover_ma60, turnover_ma120, turnover_ma250 | 成交额N日均线 |

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

### fund_hs300_correlation — 沪深300关联基金滚动相关性

| 项 | 内容 |
|---|------|
| 命令 | `uv run python -m quant.cli fund-hs300-corr <input_dir> <output_dir>` |
| 输入 | `{input_dir}/{code}.parquet`（fund_quote_adjusted） |
| 输出 | `{output_dir}/{code}.parquet` |
| 逻辑 | 筛选名称含"300"的基金，计算日收益率，与510300做滚动Pearson相关（窗口5/10/20日） |
| 字段 | date, return, corr_5, corr_10, corr_20 |
| 产出 | 80 只基金（510300自身除外） |

**字段含义：**
| 字段 | 含义 |
|------|------|
| date | 交易日期 |
| return | 日收益率（close / prev_close - 1） |
| corr_5 | 与510300的5日滚动Pearson相关系数 |
| corr_10 | 与510300的10日滚动Pearson相关系数 |
| corr_20 | 与510300的20日滚动Pearson相关系数 |

---

## 筛选功能

### filter_volume_spike — 放量股票筛选

| 项 | 内容 |
|---|------|
| 命令 | `uv run python -m quant.cli filter-volume-spike <input_dir> <min_market_cap> [options]` |
| 输入 | `{input_dir}/{code}.parquet`（stock_quote_ta） |
| 输出 | 控制台表格（可选 CSV 文件） |
| 筛选条件 | 市值 > min_market_cap，过去 N 日内有成交额 > M 倍 20日均线 |

**参数：**
| 参数 | 说明 | 默认值 |
|------|------|--------|
| input_dir | 输入目录（stock_quote_ta） | 必填 |
| min_market_cap | 最小市值（单位：元） | 必填（100亿=10000000000） |
| lookback-days | 回看交易日数 | 10 |
| volume-multiplier | 放量倍数 | 2.0 |
| output-csv | 输出 CSV 文件路径 | None（仅控制台显示） |

**使用示例：**
```bash
# 筛选市值100亿以上，过去10日内有2倍放量的股票
uv run python -m quant.cli filter-volume-spike /mnt/dataset/stock_quote_ta 10000000000

# 自定义参数
uv run python -m quant.cli filter-volume-spike /mnt/dataset/stock_quote_ta 50000000000 --lookback-days 15 --volume-multiplier 3.0

# 导出结果
uv run python -m quant.cli filter-volume-spike /mnt/dataset/stock_quote_ta 10000000000 --output-csv /tmp/volume_spike.csv
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

### filter_volume_spike_history — 历史放量批量筛选

| 项 | 内容 |
|---|------|
| 命令 | `uv run python -m quant.cli filter-volume-spike-history <input_dir> <output_csv> <min_market_cap> [options]` |
| 输入 | `{input_dir}/{code}.parquet`（stock_quote_ta） |
| 输出 | 单个 CSV 文件，每行一条放量记录 |
| 逻辑 | 用 Polars 向量化筛选所有满足 `turnover ≥ min_ratio × turnover_ma{ma_period}` 的日期 |

**参数：**
| 参数 | 说明 | 默认值 |
|------|------|--------|
| input_dir | 输入目录（stock_quote_ta） | 必填 |
| output_csv | 输出 CSV 文件路径 | 必填 |
| min_market_cap | 最小市值（单位：元） | 必填（200亿=20000000000） |
| min_ratio | 放量倍数（相对N日均线） | 2.0 |
| ma_period | 均线周期（基准） | 10 |
| min_date | 起始日期（含，YYYY-MM-DD） | None（全历史） |
| require_bull_alignment | 多头排列：ma5/10/20 全部在 ma60/120/250 上方 | False |

**CSV 字段：**
| 字段 | 含义 |
|------|------|
| date | 触发放量的日期 |
| code | 股票代码 |
| market_cap | 当日总市值 |
| turnover | 当日成交额 |
| turnover_ma10 | 10日成交额均线（基准） |
| spike_ratio | 放量倍数（turnover / turnover_ma10） |

**使用示例：**
```bash
# 筛选市值200亿以上，2倍放量
uv run python -m quant.cli filter-volume-spike-history /mnt/dataset/stock_quote_ta /tmp/out.csv 20000000000

# 加多头排列过滤（ma5/10/20 全在 ma60/120/250 上方）
uv run python -m quant.cli filter-volume-spike-history /mnt/dataset/stock_quote_ta /tmp/out.csv 20000000000 --require-bull-alignment

# 改用20日均线作基准，3倍阈值
uv run python -m quant.cli filter-volume-spike-history /mnt/dataset/stock_quote_ta /tmp/out.csv 20000000000 --ma-period 20 --min-ratio 3.0
```

**性能：** 单进程下全市场（6000+股票）扫描所有历史日期约耗时 30-60 秒。

---

## 策略

### momentum_strategy — 月度动量轮动

每月最后一个交易日，比较 CSI300/中证500/创业板50 三指数当月收益，选最强者持有到下个月末。

```bash
uv run python -m quant.cli momentum-strategy \
    --input-dir /mnt/dataset/index_quote_history \
    --output-csv /mnt/dataset/strategy_momentum.csv \
    --output-png /mnt/dataset/strategy_momentum.png
```

输出：

- `output_csv`：每月明细（持仓指数、当月收益、累计净值）
- `output_png`：策略与三指数 B&H 的 NAV 曲线（对数轴）

回测区间约 12 年（2014 至今）。纯数学模拟，不考虑交易成本、滑点、税费。

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
│       └─→ stock_quote_ta (技术指标)                              │
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
│       ↓                                                         │
│  fund_quote_adjusted (前复权)                                   │
│       ├─→ fund_flow ← fund_shares_history                       │
│       └─→ fund_hs300_correlation (沪深300关联基金滚动相关性)    │
└─────────────────────────────────────────────────────────────────┘
```