# 融资余额月度净增长 vs 沪深300（最近 5 年）

对应脚本：`plots/margin_balance_change.py`
输出：`/mnt/dataset/margin_balance_change_vs_hs300.png`

## 图说明

- **左轴**：沪深北三所融资余额（margin_buy_total）合计的月度净增长，单位亿元（蓝）。即本月末余额较上月末的增减。
- **右轴**：沪深300月末收盘（黑）。
- 仅显示最近 5 年。
- 竖虚线标事件：2022 封控、2022 重开、2024 小盘股崩、2024 政策转向。

## 算法

```
三所按日汇总：balance[d] = Σ(bse,sse,szse) margin_buy_total[d]
取每月最后一个交易日 → balance[M]
月度净增长：chg[M] = (balance[M] − balance[M−1]) / 1e8   # 亿元
```

> 默认 `WINDOWS=[1]`，只画月环比净增长；改该常量（如 `[3,6,12]`）可叠加多窗口。

## 怎么读

| 信号 | 含义 |
|---|---|
| **净增长深正** | 杠杆资金持续加仓（融资买入活跃） |
| **净增长转负** | 杠杆资金偿还 / 减仓（去杠杆） |

## 与沪深300的关系

融资盘是 A 股典型的杠杆/情绪资金：

- 融资余额持续净增通常对应做多情绪升温；
- 融资余额净减少（偿还）往往出现在调整或恐慌期（如 2024-02 小盘股流动性危机）；
- 融资盘是同步偏滞后的情绪指标，而非领先信号。

## 数据源

- `/mnt/readonly_dataset/eastmoney/margin_trade_total_history/{bse,sse,szse}/{year}.csv.gz`：每日融资余额（margin_buy_total），三所合计。
- `index_quote_history/000300.parquet`：日频 → 月末收盘。

## 运行

```bash
uv run python plots/margin_balance_change.py
# 可选：--data-path <path> --index-file <path> --output <path>
```
