# 剔除股价影响的月度流通市值变化 vs 沪深300（双轴）

对应脚本：`plots/new_float_market_cap.py`
输出：`/mnt/dataset/new_float_market_cap.png`

## 图说明

把 A 股「**真实筹码进出**」（剥离股价涨跌后）按月汇总，与沪深300 同框：

| 元素 | 数据 | 颜色 | 含义 |
|---|---|---|---|
| 上行柱 | `float_market_cap_increase` 月合计 | 绿 | **扩容**：IPO / 限售解禁 / 增发 / 配股 —— **从股市拿钱** |
| 下行柱 | `float_market_cap_decrease` 月合计 | 红 | **现金回报**：分红 / 回购注销 —— **向股市发钱** |
| 中线 | `new_float_market_cap` 月合计（净额） | 黑 | 扩容 + 回报 |
| 次右轴（外偏 60pt） | 沪深300 月末收盘 | 灰 | 大盘走势 |

正/负**分开统计**：increase 是市场潜在卖压（新筹码进场），decrease 是资金流出股市的现金回报。
两者方向相反、成因不同，分开比净额更有信息量。

## 数据源

- 主数据：`/mnt/dataset/new_float_market_cap.csv`（日频，2005 起）
- 沪深300：`/mnt/dataset/index_quote_history/000300.parquet`（日频 → 月末收盘）

数据集由 `uv run python -m quant.cli new-float-market-cap` 生成，
详细字段定义 / 公式 / 数据清洗（交易日历过滤、口径跳变日剔除）见
[`docs/datasets/new_float_market_cap.md`](../docs/datasets/new_float_market_cap.md)。

## 怎么读

- **绿柱巨峰 = 历史级解禁**：例如 2010-11（中国石油上市 3 周年解禁 +2.3 万亿）、
  2009-10（工商银行 +1.3 万亿）、2009-07（建设银行 +0.8 万亿）。
- **红柱深谷 = 分红季**：每年 6-7 月茅台/平安等大额现金分红集中爆发；
  深度逐年加深 = A 股分红规模逐年提升。
- **绿柱抬升 = IPO 加速**：2010 创业板开闸、2019-2020 科创板、2023 全面注册制。
- **净额长期为正**：A 股以融资为主，扩容 > 回报；个别月份（如 6 月分红季）净额转负。
- **与沪深300 对照**：解禁洪峰不一定对应指数顶（如 2010-11 解禁巨量但指数震荡）；
  大规模 IPO 加速期往往伴随指数表现平淡（筹码分流）。

## 局限

- 见数据集文档 [`new_float_market_cap.md`](../docs/datasets/new_float_market_cap.md#局限)：
  前复权基准快照、分红记为负、早期/北交所覆盖等。
- 月度汇总会**平滑日度异常**：单个交易日的解禁巨峰在月度柱中可能与同月其他事件合并。

## 运行

```bash
uv run python plots/new_float_market_cap.py
# 可选：--data-file <path> --hs300-file <path> --output <path>
#       --start-date <YYYY-MM-DD>（默认 2005-01-01）
#       --end-date <YYYY-MM-DD>
```
