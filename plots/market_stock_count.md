# 沪深两市股票数 / 流通市值 / 总市值 / 沪深300（三轴，日频）

对应脚本：`plots/market_stock_count.py`
输出：`/mnt/dataset/market_stock_count.png`

## 图说明

三轴日频图，把 A 股「广度」「深度」「表现」放进一张图：

| 轴 | 数据 | 颜色 | 含义 |
|---|---|---|---|
| 左轴 | 股票数（turnover>0 的活跃股票） | 绿色面积 | **广度**：市场扩容速度 |
| 右轴 | 沪深300 收盘 | 灰淡线 | **表现**：大盘走势 |
| 次右轴（外偏 64pt） | 流通市值 / 总市值（万亿元） | 蓝实线 / 紫虚线 | **深度**：市场体量 |

## 数据源

单一来源：`/mnt/dataset/turnover_concentration.csv`（1992 起，无截断）

字段：
- `stock_count` — 当日 turnover>0 的股票数
- `free_float_market_cap_total` — 同口径股票流通市值之和（元）
- `market_cap_total` — 同口径股票总市值之和（元）

沪深300 收盘来自 `/mnt/dataset/index_quote_history/000300.parquet`。

数据集由 `uv run python -m quant.cli turnover-concentration` 生成，详细字段定义见
[`docs/datasets/turnover_concentration.md`](../docs/datasets/turnover_concentration.md)。

## 怎么读

- **股票数（绿）单调上行**：A 股持续扩容（1992 ~50 只 → 2026 ~5400 只）；
  斜率陡增段对应 IPO 加速期（2009-2010 创业板、2019-2020 科创板、2023 全面注册制）。
- **市值（蓝/紫）与股票数背离**：扩容快但市值不涨 = 单只票变小（IPO 多为中小盘）；
  市值快速膨胀但股票数平稳 = 指数级行情（蓝筹估值抬升）。
- **流通市值 < 总市值**：差值即大股东限售部分；差额收窄 = 全流通深化。
- **与沪深300 对照**：市值顶往往对应指数顶（2007、2015、2021）。

## 历史区间特征（默认起始 2000-01-01）

- 2000：~1000 只、流通市值 ~1.5 万亿；
- 2010：~1700 只（创业板开闸）、流通市值 ~20 万亿；
- 2015：~2400 只、流通市值 ~50 万亿（杠杆牛顶）；
- 2020：~3800 只（科创板 + 注册制）、流通市值 ~65 万亿；
- 2026：~5400 只、流通市值 ~85 万亿。

## 运行

```bash
uv run python plots/market_stock_count.py
# 可选：--data-file <path> --hs300-file <path> --output <path>
#       --start-date <YYYY-MM-DD>（默认 2000-01-01，早期集中度样本少、噪音大；
#                                 传 1992-01-01 可看全历史）
#       --end-date <YYYY-MM-DD>
```
