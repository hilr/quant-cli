# 港股通南向资金 vs 恒生科技 ETF(513180) 关系量化分析

`plots/southbound_etf_analysis.py` 的输出文档。

## 输出

`/mnt/dataset/southbound_etf_analysis.png` —— 4 子图 dashboard：

1. 散点：net_60d（60 日累计净流入）vs etf_fwd_ret_5d（未来 5 日 ETF 收益）
2. 散点：q60（当日 net_yi 在过去 60 日分位）vs etf_fwd_ret_5d
3. 120 日滚动 Pearson corr(信号, etf_fwd_ret_5d)：关系稳定性
4. q60 分 10 桶后 forward 3d/5d 平均收益

## 数据源

| 数据 | 路径 | 字段 |
|---|---|---|
| 南向资金 | `/mnt/dataset/exchange_hkex/southbound_flow.csv` | `net_yi`（亿港元） |
| ETF 前复权 | `/mnt/dataset/fund_quote_adjusted/513180.parquet` | `close` |

样本期：2021-05-25 ~ 2026-06-23（共同交易日，n = 1193）。

## 信号定义

| 列名 | 含义 | 公式 |
|---|---|---|
| `net_20d` | 20 日累计南向净流入（亿港元） | `rolling_sum(net_yi, 20)` |
| `net_60d` | 60 日累计南向净流入（亿港元） | `rolling_sum(net_yi, 60)` |
| `q60` | 当日 net_yi 在过去 60 日的百分位（0~1） | `mean(net_yi[t-60..t-1] <= net_yi[t])`（不含当日） |
| `etf_fwd_ret_h_d` | ETF h 个交易日 forward 收益 | `close[t+h] / close[t] - 1`（h ∈ {1, 3, 5, 20}） |

q60 用「过去 60 日不含当日」窗口，避免与同日 ETF forward 收益产生信息泄漏。

## 全样本 Pearson corr（2026-06-23 复现）

| 信号 | fwd 1d | fwd 3d | fwd 5d | fwd 20d |
|---|---|---|---|---|
| net_20d | 0.053 | 0.085 | 0.104 | 0.143 |
| net_60d | 0.030 | 0.043 | 0.055 | 0.107 |
| q60     | -0.004 | 0.007 | 0.040 | 0.091 |

## 120 日滚动 corr(信号, etf_fwd_ret_5d) 极值

| 信号 | mean | peak | trough |
|---|---|---|---|
| net_20d | +0.057 | +0.478 | -0.339 |
| net_60d | -0.017 | +0.528 | -0.474 |
| q60     | +0.036 | +0.329 | -0.176 |

## 关键发现

1. **方向弱正确，强度微弱**：所有中长期（≥5d）组合均为正相关，但 r 最高仅 0.143（R² ≈ 2%），单因子解释力低。

2. **窗口越短反而信号越强**：net_20d > net_60d。最新 1 个月的资金态度对 ETF 后续走势最有预示意义，更早的部分稀释信号。

3. **当日分位短期预测力近乎为零**：q60 vs fwd 3d/5d 的 corr ≈ 0.004/0.040；10 个分位桶 forward 收益均在 ±0.5% 内、无单调性。**不能作为短线择时信号**。

4. **关系高度 regime-dependent**：net_60d_vs_fwd5d 的滚动 corr 在 -0.47 ~ +0.53 之间漂移，均值接近 0。全样本低 corr 是不同市场状态相互抵消的结果。要发挥预测价值需要分段建模（如港股 60 日趋势上/下、波动率 regime）。

## 局限

- 仅一只 ETF（513180）；恒生科技 vs 恒生指数、国企指数 vs 红筹指数等可能差异显著
- 未做 turnover 加权（净流入金额相同但成交占比不同的日子未区分）
- 未排除 ETF 分红、停盘日异常值
- 2021-2022 是港股熊市、2024 后是港股牛市，样本结构不均匀

## CLI

```bash
.venv/bin/python plots/southbound_etf_analysis.py \
    --sb-csv /mnt/dataset/exchange_hkex/southbound_flow.csv \
    --fund-file /mnt/dataset/fund_quote_adjusted/513180.parquet \
    --output /mnt/dataset/southbound_etf_analysis.png
```
