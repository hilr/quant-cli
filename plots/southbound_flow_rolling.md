# 港股通南向资金滚动净流入 vs 恒生科技 ETF(513180) 双轴图

`plots/southbound_flow_rolling.py` 的输出文档。

## 输出

`/mnt/dataset/southbound_flow_rolling_vs_513180.png` —— 2 panel：
- 上：513180 前复权收盘价
- 下：20 日 / 60 日滚动净流入合计（带正/负填充），红=净流入、绿=净流出（中国市场习惯）

跨两图的虚线 + 顶部文字标注关键事件：
- 2018 贸易战
- 2021 双减/恒大
- 2022 中概退市危机
- 2022 HK 重开预期
- 2024 HK 牛市启动
- 2024 924 政策
- 2025 南向峰值

## 数据源

| 数据 | 路径 | 字段 |
|---|---|---|
| 南向资金 | `/mnt/dataset/exchange_hkex/southbound_flow.csv` | `net_yi`（亿港元） |
| ETF | `/mnt/dataset/fund_quote_adjusted/513180.parquet` | `close` |

样本期：南向最早 2015-08-10 起，ETF 2021-05-25 起，绘图从二者重叠日开始。

## 信号定义

| 列名 | 含义 |
|---|---|
| `net_20d` | 20 日南向累计净流入（亿港元） |
| `net_60d` | 60 日南向累计净流入（亿港元） |

停盘日和早期 SZSE 未开通日的 `net_yi` 为 null，`fill_null(0)` 后参与 rolling_sum。

## 控制台摘要

每次运行打印：
- 样本期 + 行数
- 每个窗口的最新值、历史峰值、历史谷底（含日期）

## CLI

```bash
.venv/bin/python plots/southbound_flow_rolling.py \
    --csv /mnt/dataset/exchange_hkex/southbound_flow.csv \
    --fund-file /mnt/dataset/fund_quote_adjusted/513180.parquet \
    --output /mnt/dataset/southbound_flow_rolling_vs_513180.png
```
