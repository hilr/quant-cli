[← 数据集索引](../../README.md#数据集索引)

# new_float_market_cap — 剔除股价影响的日度流通市值变化

| 项 | 内容 |
|---|------|
| 命令 | `uv run python -m quant.cli new-float-market-cap [--input-dir ...] [--output-dir ...] [--trading-days-dir ...]` |
| 输入 | `{input_dir}/{code}.parquet`（stock_quote_adjusted，前复权行情） |
| 输出 | `{output_dir}/new_float_market_cap.csv`，宽表，2004-12-31 ~ 今 |
| 交易日历 | `{trading-days-dir}/*.csv` 文件名集合（深交所 index_quote），剔除休市日脏数据 |
| 字段 | date, new_float_market_cap, float_market_cap_increase, float_market_cap_decrease, stock_count |

## 思路

流通市值的日变化 = 股价变化 + 筹码变化。本数据集剥离股价涨跌，只留筹码变化
（IPO / 限售解禁 / 增发 / 配股 / 现金分红 / 回购）。

基于前复权行情（`close` 为前复权价、`free_float_market_cap` 为真实市值）：

```
shares_t = free_float_market_cap_t / close_t          # 复权口径股本，吸收除权除息
delta_t  = close_t × (shares_t − shares_{t−1})        # 剔除股价部分后的市值变化
```

等价写法（更直观）：

```
delta_t = ffmc_t − ffmc_{t−1} × (close_t / close_{t−1})
```

即「今日流通市值 − 假设股价按比例变动的股价部分」。

前复权 close 在除权日连续（吸收送股/转股/拆股/分红），所以 `shares` 只在**真实筹码变化**
时跳变；送股/转股/拆股等对所有股东同比例的"形式变化"被消除。

## 字段

| 字段 | 含义 | 单位 | 符号 |
|------|------|------|------|
| date | 交易日 | — | — |
| new_float_market_cap | 净流通市值变化 = increase + decrease | 元 | 正=扩张，负=收缩 |
| float_market_cap_increase | 正项合计：IPO / 限售解禁 / 增发 / 配股（**从股市拿钱**） | 元 | + |
| float_market_cap_decrease | 负项合计：现金分红 / 回购注销（**向股市发钱**） | 元 | − |
| stock_count | 当日有效 delta 的股票数 | 只 | — |

**正/负分开统计**：increase 是市场扩容（新筹码进场，潜在卖压），decrease 是现金回报
（资金流出股市）。两者方向相反，分开看比净额更有信息量。

## 数据清洗

- **交易日历过滤**：用深交所 `index_quote` 目录的文件名集合作权威交易日，剔除休市日脏数据
  （数据源在 2025-01-01 等休市日误灌入 ffill 行，会被 `convert_adjust` 的 factor 计算放大，
  污染全市场所有历史日期的前复权价）。
- **口径跳变日剔除**：上游 `free_float_market_cap` 在个别日期发生局部集体口径调整
  （非真实筹码变化），delta 失真，从输出剔除：
  - **2022-05-09**：上游数据源对**深市**（深 A + 创业板 + 深 B）约 2600 只股票的 ffmc 一致下调
    约 -7%（中位数 -0.72%，IQR [-14.4%, 0]）；沪市、科创板不受影响；B 股（900xxx / 200xxx）
    出现 -85% / +18% 的汇率口径级跳变。该日全市场净 −2.2 万亿，但分散在 3801 只股票上、
    无主导个股，符合 caliber change 特征（对比真实解禁如 2010-11-08 中石油 +2 万亿，
    TOP1 占比 38.9%）。
  - 剔除清单见 `quant/convert.py::_KNOWN_REGIME_BREAK_DATES`，发现新的可追加。
- **`convert_adjust` 已修复休市日污染**（曾导致 2025-01-02 全市场 ffmc 假跳变 +1.4 万亿）：
  上游 sina 在元旦休市日灌入 prev_close 失真的 ffill 假行，被 factor 计算放大；
  现在 `convert_adjust` 用交易日历过滤输入，假跳变消失（修复后 2025-01-02 真实 delta +37 亿）。

## 典型信号

- **历史级解禁（increase 巨峰）**：
  - 2010-11-08 +2.0 万亿：中国石油（601857）上市 3 周年限售股解禁
  - 2009-10-27 +1.3 万亿：工商银行（601398）上市 3 周年解禁
  - 2009-07-06 +0.8 万亿：建设银行解禁
- **分红季（decrease 集中）**：每年 6-7 月，茅台/平安等大额现金分红，全市场 decrease 集中爆发。
- **IPO 加速期（increase 抬升）**：2010 创业板、2019-2020 科创板、2022 全面注册制。

## 局限

- **前复权基准**：每只股票的前复权以自身最新日为基准。本数据集基于已生成的
  `stock_quote_adjusted` 快照，不会随上游追加交易日自更新；如需更新应先重跑 `adjust`。
- **分红记为负**：现金分红除息日 ffmc 真实下降，被归入 decrease。语义上"分红 = 向股市发钱"
  成立；若要单独剥离分红需额外除息数据。
- **早期/北交所覆盖**：2005 前、以及北交所 920 段（2025-10 才入库）的数据缺失，对应区间数值偏低。

## 使用示例

```bash
uv run python -m quant.cli new-float-market-cap

# 配套可视化：月度 increase/decrease 柱 + 净额线 vs 沪深300
uv run python plots/new_float_market_cap.py
```

**关联图表：** `plots/new_float_market_cap.py` — 月度 increase（绿柱向上）/ decrease（红柱向下）
/ 净额线，次右轴叠加沪深300。
