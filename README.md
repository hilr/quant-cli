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

### filter_volume_spike — 放量股票批量筛选

| 项 | 内容 |
|---|------|
| 命令 | `uv run python -m quant.cli filter-volume-spike <input_dir> <output_csv> <min_market_cap> [options]` |
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
| ma_period | 均线周期（基准） | 20 |
| min_date | 起始日期（含，YYYY-MM-DD） | None（全历史） |

**CSV 字段：**
| 字段 | 含义 |
|------|------|
| date | 触发放量的日期 |
| code | 股票代码 |
| market_cap | 当日总市值 |
| turnover | 当日成交额 |
| turnover_ma20 | 20日成交额均线（基准） |
| spike_ratio | 放量倍数（turnover / turnover_ma20） |

**使用示例：**
```bash
# 筛选市值200亿以上，2倍放量
uv run python -m quant.cli filter-volume-spike /mnt/dataset/stock_quote_ta /tmp/out.csv 20000000000

# 只要 2026 年的记录
uv run python -m quant.cli filter-volume-spike /mnt/dataset/stock_quote_ta /tmp/out.csv 20000000000 --min-date 2026-01-01

# 改用 60 日均线作基准，3 倍阈值
uv run python -m quant.cli filter-volume-spike /mnt/dataset/stock_quote_ta /tmp/out.csv 20000000000 --ma-period 60 --min-ratio 3.0
```

**性能：** 单进程下全市场（6000+股票）扫描所有历史日期约耗时 30-60 秒。

---

### filter_limit_up_pullback — 涨停回踩单日筛选

| 项 | 内容 |
|---|------|
| 命令 | `uv run python -m quant.cli filter-limit-up-pullback <date> [options]` |
| 输入 | `{input_dir}/{code}.parquet`（默认 stock_quote_ta） |
| 输出 | 控制台表格 + 可选 CSV |
| 逻辑 | 找出指定日期前 10 个交易日内涨停过、且当日已回踩到涨停前价位的股票 |

**筛选条件：**
1. 非 ST 股票（从当天原始行情 `finance_sina/stock_quote/{date}.csv` 的 name 字段判断）
2. 指定日期 `market_cap ≥ min_market_cap`
3. 指定日期前 `lookback_days` 个交易日内（窗口跨度 ≤ `max_calendar_span` 自然日，用于排除停牌），出现过涨停：`close ≥ round(prev_close × 1.099, 2)`
4. 指定日期 `close < (1 + pullback_tolerance) × 涨停日 prev_close`

窗口内多次涨停取最近一次作为锚点。

**参数：**
| 参数 | 说明 | 默认值 |
|------|------|--------|
| date | 指定日期（YYYY-MM-DD，位置参数） | 必填 |
| input_dir | 输入目录 | /mnt/dataset/stock_quote_ta |
| min_market_cap | 最小市值（单位：元） | 10000000000（100亿） |
| lookback_days | 回看交易日数 | 10 |
| max_calendar_span | 窗口最大自然日跨度 | 14 |
| pullback_tolerance | 相对涨停前价位的容忍度 | 0.01（1%） |
| output_csv | 导出 CSV 路径 | None（不导出） |

**输出字段：**
| 字段 | 含义 |
|------|------|
| code | 股票代码 |
| date | 指定日期 |
| close | 指定日期收盘价 |
| market_cap | 指定日期总市值 |
| zt_date | 锚点涨停日 |
| zt_prev_close | 涨停前一交易日收盘价 |
| pullback_pct | `close / zt_prev_close - 1` |

**使用示例：**
```bash
# 默认参数（100亿市值、近10个交易日、回踩1%以内）
uv run python -m quant.cli filter-limit-up-pullback 2026-06-15

# 放宽到近 20 个交易日、市值 50 亿
uv run python -m quant.cli filter-limit-up-pullback 2026-06-15 --lookback-days 20 --min-market-cap 5000000000

# 导出 CSV
uv run python -m quant.cli filter-limit-up-pullback 2026-06-15 --output-csv /tmp/lup.csv
```

---

## 策略

### momentum_strategy — 月度动量轮动

每月最后一个交易日，比较 CSI300/中证500/创业板50 三指数当月收益，选最强者持有到下个月末。

```bash
uv run python -m quant.cli momentum-strategy \
    --input-dir /mnt/dataset/index_quote_history \
    --output-csv /mnt/dataset/strategy_momentum.csv \
    --output-png /mnt/dataset/strategy_momentum.png \
    --cash-when-all-negative
```

可选 `--cash-when-all-negative`：当上月三个指数收益全部为负时，本月空仓（收益记为 0）。

输出：

- `output_csv`：每月明细（持仓指数、当月收益、累计净值）
- `output_png`：策略与三指数 B&H 的 NAV 曲线（对数轴）

回测区间约 12 年（2014 至今）。纯数学模拟，不考虑交易成本、滑点、税费。

### ma_crossover_strategy — 双均线突破

基于单一指数的双均线突破策略：快线上穿慢线时持仓，跌破时空仓。使用 T-1 日信号决定 T 日持仓，避免未来函数。

```bash
uv run python -m quant.cli ma-crossover-strategy \
    --input-dir /mnt/dataset/index_quote_history \
    --index-code 000300 \
    --fast-window 5 \
    --slow-window 60 \
    --output-csv /mnt/dataset/strategy_ma_cross.csv \
    --output-png /mnt/dataset/strategy_ma_cross.png
```

参数：

- `--index-code`：指数代码（默认 000300 = CSI300）
- `--fast-window` / `--slow-window`：快慢均线窗口（默认 5 / 60）

输出：

- `output_csv`：每日明细（收盘价、快慢均线、持仓、收益、累计净值）
- `output_png`：策略与指数 B&H 的 NAV 曲线，绿色阴影为持仓区间

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