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

## 数据集索引

每个数据集的详细文档（命令、输入输出、字段含义）单独存放在 [`docs/datasets/`](docs/datasets/)，一个数据集一个文件。

| 数据集 | 类型 | 说明 | 文档 |
|--------|------|------|------|
| gov_stats/工业企业指标 | 原始 | 规模以上工业企业月度经济效益 | [文档](docs/datasets/gov_stats_industrial.md) |
| gov_stats/{进出口,社会消费品零售总额} | 原始 | 海关进出口、社会消费品零售总额月度指标（千美元/亿元/%），csv≤近年 + xlsx | 见下方 |
| gov_pbc | 原始 | 央行月度统计（货币供应量、社融、信贷收支、货币当局资产负债表），按年目录，htm/xls/xlsx 混合格式 | 见下方 |
| csindex/industry | 原始 | 中证行业分类快照（一/二/三/四级），日度但变化慢 | 见下方 |
| csindex/index_weight/{000300,000905} | 原始 | HS300 / CSI500 月度成分权重（OLE .xls 伪装成 .xlsx） | 见下方 |
| industry_profit | 生成 | 工业企业每月利润总额 | [文档](docs/datasets/industry_profit.md) |
| pbc/money_supply | 生成 | 央行货币供应量 M0/M1/M2 月度（亿元），宽表 | [文档](docs/datasets/pbc_money_supply.md) |
| pbc/social_financing_flow | 生成 | 社会融资规模增量（流量），长表 | [文档](docs/datasets/pbc_social_financing_flow.md) |
| pbc/social_financing_stock | 生成 | 社会融资规模存量 + 增速，长表 | [文档](docs/datasets/pbc_social_financing_stock.md) |
| pbc/credit_funds | 生成 | 金融机构信贷收支（存贷款全明细），长表 | [文档](docs/datasets/pbc_credit_funds.md) |
| pbc/central_bank_balance_sheet | 生成 | 货币当局资产负债表（全明细），长表 | [文档](docs/datasets/pbc_central_bank_balance_sheet.md) |
| pbc/overseas_rmb_assets | 生成 | 境外机构/个人持有境内人民币金融资产（股票/债券/贷款/存款），宽表 | [文档](docs/datasets/pbc_overseas_rmb_assets.md) |
| pbc/exchange_rate | 生成 | 人民币兑美元汇率（月末/月均中间价），宽表 | [文档](docs/datasets/pbc_exchange_rate.md) |
| exchange_hkex/southbound_flow | 生成 | 港股通南向每日买卖净额（亿港元），宽表，2021-06 起 | [文档](docs/datasets/exchange_hkex_southbound_flow.md) |
| gov_stat/trade | 生成 | 海关进出口月度指标（长表） | [文档](docs/datasets/gov_stat_trade.md) |
| gov_stat/retail_sales | 生成 | 社会消费品零售总额月度指标（长表） | [文档](docs/datasets/gov_stat_retail_sales.md) |
| gov_stat/retail_sales_monthly | 生成 | 社会消费品零售总额每月新增额（宽表，累计值差分） | [文档](docs/datasets/gov_stat_retail_sales_monthly.md) |
| stock_quote_history | 生成 | 股票行情历史 | [文档](docs/datasets/stock_quote_history.md) |
| stock_quote_adjusted | 生成 | 前复权行情 | [文档](docs/datasets/stock_quote_adjusted.md) |
| stock_quote_ta | 生成 | 技术指标 | [文档](docs/datasets/stock_quote_ta.md) |
| turnover_concentration | 生成 | 全 A 股日成交额集中度（gini/alpha/top5-median/hhi/cr10），宽表，2010 起 | [文档](docs/datasets/turnover_concentration.md) |
| margin_trade_history | 生成 | 融资融券历史 | [文档](docs/datasets/margin_trade_history.md) |
| margin_trade_daily | 生成 | 融资融券每日净变化 | [文档](docs/datasets/margin_trade_daily.md) |
| fund_shares_history | 生成 | 基金份额历史 | [文档](docs/datasets/fund_shares_history.md) |
| fund_quote_history | 生成 | 基金行情历史 | [文档](docs/datasets/fund_quote_history.md) |
| fund_flow | 生成 | 基金资金流 | [文档](docs/datasets/fund_flow.md) |
| fund_hs300_correlation | 生成 | 沪深300关联基金滚动相关性 | [文档](docs/datasets/fund_hs300_correlation.md) |

---

## 可视化脚本

独立 argparse 脚本，放在 `plots/`，输出 PNG 到 `/mnt/dataset/`。每个脚本的完整文档（用法/参数/数据源/结果）单独存放在 `plots/xxx.md`，下表只做索引。

| 脚本 | 说明 | 文档 |
|------|------|------|
| industry_heatmap | 行业成交额-涨幅方块热力图（finviz 风格，全 A 股聚合） | [文档](plots/industry_heatmap.md) |
| industry_turnover_stack | 行业成交额占比 river 图（streamgraph，时序） | [文档](plots/industry_turnover_stack.md) |
| turnover_channel_breakout | 成交额通道重入信号（沪深300，log Bollinger + ZigZag 评估） | [文档](plots/turnover_channel_breakout.md) |
| zigzag_annual_return | ZigZag 枢轴每年最大做多收益率（沪深300） | [文档](plots/zigzag_annual_return.md) |
| annual_volatility | 沪深300 每年年化波动率 + 指数对照 | [文档](plots/annual_volatility.md) |

---


## Tag 层

`quant/tags.py` 提供最简单的「股票 × 日期」布尔标记。每个 tag 是纯函数：接收一只股票的完整 DataFrame，返回带新增 `tag_*` 列的 DataFrame。filter 层在 tag 之上做组合查询。

### 内置 tags

| Tag | 函数 | 判定 |
|------|------|------|
| `surge_3d` | `tag_surge_3d(df, min_total_return=0.10)` | 过去 3 个交易日（含当日）每日 `close > prev_close`，且 `close / close[t-3] - 1 >= min_total_return` |
| `volume_spike` | `tag_volume_spike(df, ma_period=20, ratio=2.0)` | `turnover >= ratio × turnover_ma{ma_period}` |
| `limit_up` | `tag_limit_up(df, ratio=0.099)` | `close >= round(prev_close × (1 + ratio), 2)` |

### 添加新 tag

1. 在 `quant/tags.py` 写 `tag_xxx(df, ...) -> pl.DataFrame`，函数内 `with_columns(... .alias("tag_xxx"))`
2. 注册到 `TAG_FUNCS` dict（key 是简短名，value 是函数）
3. 注册到 `TAG_REQUIRED_COLUMNS`（声明该 tag 需要读哪些原始列，`filter_by_tags` 会按需读列避免全表扫描）

---

## 筛选功能

### filter_by_tags — 单日 tag AND 组合查询

| 项 | 内容 |
|---|------|
| 命令 | `uv run python -m quant.cli filter-by-tags <date> <tag> [<tag> ...] [options]` |
| 输入 | `{input_dir}/{code}.parquet`（默认 stock_quote_ta） |
| 输出 | 控制台表格 + 可选 CSV |
| 逻辑 | 每只股票读一次，应用所有 tag 函数，留下指定日期 `tag_*` 全为 True 的股票 |

**参数：**
| 参数 | 说明 | 默认值 |
|------|------|--------|
| date | 指定日期（YYYY-MM-DD，位置参数） | 必填 |
| tags | Tag 名（AND 组合，可多个，位置参数） | 必填 |
| input_dir | 输入目录 | /mnt/dataset/stock_quote_ta |
| min_market_cap | 最小市值（单位：元） | 0（不过滤） |
| exclude_st | 是否排除 ST 股票 | True（用 `--no-exclude-st` 关闭） |
| output_csv | 导出 CSV 路径 | None（不导出） |

**输出字段：**
| 字段 | 含义 |
|------|------|
| code | 股票代码 |
| date | 指定日期 |
| close | 指定日期收盘价 |
| market_cap | 指定日期总市值 |
| tag_* | 每个命中 tag 的布尔列（全 True，列出来仅作记录） |

**使用示例：**
```bash
# 单 tag: 3 日连涨强势股
uv run python -m quant.cli filter-by-tags 2026-06-15 surge_3d --min-market-cap 20000000000

# 组合: 3 日连涨 且 当日涨停
uv run python -m quant.cli filter-by-tags 2026-06-15 surge_3d limit_up

# 组合: 涨停 且 放量
uv run python -m quant.cli filter-by-tags 2026-06-15 limit_up volume_spike --min-market-cap 10000000000

# 不过滤 ST
uv run python -m quant.cli filter-by-tags 2026-06-15 limit_up --no-exclude-st
```

---

### filter_limit_up_pullback — 涨停回踩（tag + 时间窗口复合 filter）

| 项 | 内容 |
|---|------|
| 命令 | `uv run python -m quant.cli filter-limit-up-pullback <date> [options]` |
| 输入 | `{input_dir}/{code}.parquet`（默认 stock_quote_ta） |
| 输出 | 控制台表格 + 可选 CSV |
| 逻辑 | 在 `tag_limit_up` 之上叠加时间窗口条件：近期涨停 + 回踩到涨停前价位 |

**筛选条件：**
1. 非 ST 股票
2. 指定日期 `market_cap >= min_market_cap`
3. 指定日期前 `lookback_days` 个交易日内（窗口跨度 ≤ `max_calendar_span` 自然日，用于排除停牌）出现过 `tag_limit_up`
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
# 默认参数
uv run python -m quant.cli filter-limit-up-pullback 2026-06-15

# 放宽到近 20 个交易日、市值 50 亿
uv run python -m quant.cli filter-limit-up-pullback 2026-06-15 --lookback-days 20 --min-market-cap 5000000000
```

---

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

### channel_strategy — 布林带通道入场信号

基于布林带下轨的买入策略。买入条件：`close ≤ MA(window) − k·σ(window)`（触及下轨），持仓由移动止损 `close < peak − m·σ` 离场。信号 T-1 决定 T 日持仓，避免未来函数。纯数学模拟，无交易成本。

**脚本：** `plots/channel_entry_signals.py`（入场信号质量可视化）
**策略引擎：** `quant/strategy.run_signal_strategy`（通用 Signal/Stop 回测）

**参数：**
| 参数 | 说明 | 默认 |
|------|------|------|
| `--code` | 基金代码 | 512890 |
| `--window` | MA + σ 窗口 | 120 |
| `--k` | 带宽倍数 | 1.5 |
| `--fwd` | 前瞻窗口（交易日） | 60（≈3 月） |
| `--adjusted-dir` | 复权数据目录 | /mnt/dataset/fund_quote_adjusted |

**使用示例：**
```bash
uv run python plots/channel_entry_signals.py --code 512890 --window 120 --k 1.5 --fwd 60
```

#### 买入信号质量（512890，复权数据，2000 年至今 14 笔可验）

| # | 买入日期 | 买入价 | 60日最大涨幅 | 见顶日 | 60日收益 | 最大浮亏 | 见底日 |
|---|---|---|---|---|---|---|---|
| 1 | 2020-02-03 | 0.512 | +13.6% | 23d | +3.9% | −1.2% | 35d |
| 2 | 2020-03-16 | 0.529 | +5.1% | 57d | +4.3% | −4.4% | 5d |
| 3 | 2020-03-20 | 0.521 | +7.0% | 60d | +7.0% | −2.9% | 1d |
| 4 | 2021-01-28 | 0.628 | +12.8% | 59d | +11.8% | −0.2% | 1d |
| 5 | 2022-03-15 | 0.747 | +16.3% | 14d | +14.1% | 0.0% | 0d |
| 6 | 2022-08-03 | 0.790 | +13.2% | 27d | −0.6% | −2.3% | 57d |
| 7 | 2022-10-26 | 0.803 | +7.9% | 28d | +4.2% | −3.9% | 3d |
| 8 | 2022-11-01 | 0.780 | +11.0% | 24d | +8.9% | 0.0% | 0d |
| 9 | 2023-12-19 | 0.911 | +12.7% | 51d | +10.4% | −1.4% | 23d |
| 10 | 2024-01-22 | 0.898 | +20.7% | 56d | +17.2% | 0.0% | 0d |
| 11 | 2024-09-03 | 0.995 | +14.8% | 18d | +10.7% | −5.1% | 6d |
| 12 | 2024-09-10 | 0.967 | +18.1% | 13d | +16.1% | −2.4% | 1d |
| 13 | 2025-04-07 | 1.064 | +13.8% | 60d | +13.8% | 0.0% | 0d |
| 14 | 2026-01-14 | 1.156 | +4.7% | 38d | +2.4% | −1.1% | 2d |

**汇总（14 笔可验）：**
- 60 日胜率：**13/14（93%）**，60 日收益均值 **+8.9%**，中位数 **+10.4%**
- 60 日最大涨幅均值 **+12.3%**，中位数 **+13.2%**（最差也有 +4.7%）
- 买入后最大浮亏（相对入场价）：均值 **−1.8%**，最差 **−5.1%**，见底均值 **9.6 日**
- **5 笔**买入后从未浮亏，**9 笔**先浮亏后转盈，唯一下跌的（2022-08-03）只亏 −0.6%
- 最大涨幅均值（12.3%）远大于 60 日收益均值（8.9%），说明多数买入后经历了先涨后回调，而非单边持有

**算法说明：**
- 买入信号 = `close ≤ MA(120) − 1.5·σ(120)`（`tag_boll_lower`，见 `quant/tags.py`）
- 入场价 = 信号触发当日收盘价，实际持仓从下一日开始（T-1 信号 → T 持仓）
- 最大浮亏 = `min(price[t] / 入场价 − 1)`，从入场价起算（不是 peak-to-trough），反映真实买入后经历的最大账面损失
- 数据源 = 前复权收盘价（`fund_quote_adjusted`），消除分红除权影响

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

┌─────────────────────────────────────────────────────────────────┐
│                        央行宏观数据流                            │
├─────────────────────────────────────────────────────────────────┤
│  gov_pbc/{year}/[子目录]/{表}.{htm,xls,xlsx}                    │
│       ↓  (xlsx > xls > htm 优先；htm 用 html.parser，xls/xlsx   │
│          用 calamine；月份列按位置推断避免 Excel 浮点截断)        │
│  pbc/  money_supply          (M0/M1/M2，2004+)                  │
│        social_financing_flow (社融增量，2012+)                   │
│        social_financing_stock(社融存量+增速，2015+)              │
│        credit_funds          (信贷收支，本外币+人民币，1999+)    │
│        central_bank_balance_sheet (央行资产负债表，1999+)       │
│        overseas_rmb_assets  (境外持境内金融资产，2014+)         │
│        exchange_rate       (人民币兑美元汇率，1999+)            │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                      统计局月度指标数据流                        │
├─────────────────────────────────────────────────────────────────┤
│  gov_stats/{工业企业指标,进出口,社会消费品零售总额}/{year}.{csv,xlsx} │
│       ↓  (月份列乱序/倒序，按列名 'YYYY年M月' 解析；指标×月份宽表转长表) │
│  gov_stat/  industry_profit  (利润累计→当月差分，每年一文件)     │
│             trade             (进出口，千美元/%)                 │
│             retail_sales      (消费品零售，亿元/%)              │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                      港交所互联互通数据流                        │
├─────────────────────────────────────────────────────────────────┤
│  exchange_hkex/connect_top/{YYYY-MM-DD}.csv                     │
│       ↓  (每个文件顶部 4 行聚合：SSE/SZSE × North/South；         │
│          按 code 列名取南向两行；date 取自文件名；               │
│          schema 跨年变化 2021/2022/2023+，按列名读不依赖顺序)    │
│  exchange_hkex/  southbound_flow (港股通南向每日买卖净额，2021+) │
└─────────────────────────────────────────────────────────────────┘
```
