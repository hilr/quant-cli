# 融资余额 20 日净流入合计 vs 沪深300（最近 5 年，日频）

对应脚本：`plots/margin_inflow_20d.py`
输出：`/mnt/dataset/margin_inflow_20d_vs_hs300.png`

## 图说明

- **左轴**：沪深北三所融资余额（margin_buy_total）合计的 20 个交易日净流入，单位亿元（蓝）。即当日余额较 20 个交易日前的增减。
- **右轴**：沪深300日收盘（黑）。
- 仅显示最近 5 年（日频，比月度版更细腻）。
- 竖虚线标事件：2022 封控、2022 重开、2024 小盘股崩、2024 政策转向。

## 算法

```
三所按日汇总：balance[t] = Σ(bse,sse,szse) margin_buy_total[t]
20 日净流入：inflow[t] = (balance[t] − balance[t−20]) / 1e8   # 亿元
```

20 个交易日 ≈ 1 个自然月。相比月度版（`margin_balance_change.py`），本图用交易日差分、按日画出，能看到杠杆资金中短期的进退节奏。

## 怎么读

| 信号 | 含义 |
|---|---|
| **inflow 深正且走高** | 近一个月杠杆资金持续加仓 |
| **inflow 转负** | 杠杆资金净偿还 / 离场 |

## 与沪深300的关系

- 20 日融资净流入是较好的中短期情绪温度计：持续净流入伴随指数走强；
- 急速转负（如 2024-02 小盘股危机）常领先或同步于指数快速下跌；
- 作为情绪/杠杆指标，偏同步，单边行情中可能滞后。

## 数据源

- `/mnt/readonly_dataset/eastmoney/margin_trade_total_history/{bse,sse,szse}/{year}.csv.gz`：每日融资余额（margin_buy_total），三所合计。
- `index_quote_history/000300.parquet`：日收盘。

## 运行

```bash
uv run python plots/margin_inflow_20d.py
# 可选：--data-path <path> --index-file <path> --output <path>
```
