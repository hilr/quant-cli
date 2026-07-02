# turnover_minmax_channel — 成交额通道（120 日滚动 max/min）+ 收盘价

对应脚本：`plots/turnover_minmax_channel.py`
输出：`/mnt/dataset/turnover_minmax_channel_{code}.png`（默认 `{code}=000300`）

## 图说明

上下两栏，共享 x 轴：

- **上栏**：标的收盘价（蓝实线）。
- **下栏**：当日成交额（黑细线）+ 通道上下轨 + 通道带，y 轴 log 刻度。
  - 通道带（淡蓝填充）= 上轨与下轨之间。
  - 上轨（红实线）= 过去 N 日 turnover 最大值。
  - 下轨（绿实线）= 过去 N 日 turnover 最小值。
  - 中轨（蓝虚线）= (上轨 + 下轨) / 2。
  - 右下角文本框给出最新日期、当日成交额、通道区间、通道内位置（0%=贴下轨，100%=贴上轨）。

适合回答：「近半年的成交额波动带在哪？当日成交额是触及天量（贴上轨）还是
濒临枯竭（贴下轨）？」例如 2015 牛市顶峰成交额突破上轨后长期维持高位，
2018 熊市则多次贴下轨。

## 算法

```
ch_high = rolling_max(turnover, window=N)
ch_low  = rolling_min(turnover, window=N)
ch_mid  = (ch_high + ch_low) / 2
```

- `turnover > 0` 才参与（剔除无成交的早期或停牌日）。
- 滚动窗口默认 **120 个交易日（≈半年）**，可用 `--window` 改。
- `min_samples=1`：窗口不足 N 日时用已有数据计算（图起始几日仍可见，但通道偏窄）。
- 通道内位置 = `(latest_turnover − ch_low) / (ch_high − ch_low) × 100%`。

## 为什么用 log 刻度？

A 股成交额跨数十倍（早期百亿级 → 牛市万亿级），线性刻度会把早期数据压成平地，
通道带在底部黏成一条线。log 刻度让每个数量级等宽，通道带在任何时段都清晰可辨。

## 与 turnover_channel_breakout 的区别

| 项 | turnover_minmax_channel（本图） | turnover_channel_breakout |
|---|---|---|
| 通道定义 | rolling max / min（极值） | log Bollinger（mean ± k·σ） |
| 对噪音敏感度 | 高（一根天量柱就把上轨拉满窗口） | 低（标准差平滑） |
| 用途 | 看「区间极值带」和是否触及天量/枯竭 | 看成交额是否突破统计常态 |
| 信号 | 触上轨=天量，贴下轨=枯竭 | 触上轨=异常放量（可能反转前兆） |

## 怎么读

| 信号 | 含义 |
|---|---|
| 当日成交额贴上轨 | 近半年天量，常对应情绪高点/放量突破 |
| 当日成交额贴下轨 | 近半年地量，流动性枯竭，常对应底部区域 |
| 通道带整体上移 | 近半年成交活跃度抬升（增量资金进场） |
| 通道带整体下移 | 近半年成交萎缩（资金离场） |
| 上轨长期被压在高位 | 窗口内有一次天量事件仍未滑出，后续成交相对该天量持续缩水 |

## 用法

```bash
# 默认：沪深300，120 日窗口
uv run python plots/turnover_minmax_channel.py

# 换指数（同样要带 turnover 列）
uv run python plots/turnover_minmax_channel.py --code 000905

# 改窗口（如 60 日 ≈ 季度，通道更窄、更贴近日成交额）
uv run python plots/turnover_minmax_channel.py --window 60

# 用股票行情目录（需含 turnover 列）
uv run python plots/turnover_minmax_channel.py --code 600519 \
  --adjusted-dir /mnt/dataset/stock_quote_history

# 重置起点（跳过早期成交稀薄期）
uv run python plots/turnover_minmax_channel.py --code 000300 --start-date 2010-01-01
```

| 参数 | 说明 | 默认 |
|------|------|------|
| `--code` | 指数/基金/股票代码 | 000300 |
| `--adjusted-dir` | 含 `{code}.parquet` 的行情目录（必须含 turnover 列） | /mnt/dataset/index_quote_history |
| `--window` | 滚动 min/max 窗口（交易日） | 120 |
| `--start-date` | 起始日期 YYYY-MM-DD | None（从最早有成交日起） |
| `--output` | 输出 PNG 路径 | turnover_minmax_channel_{code}.png |

## 数据源

- `{adjusted-dir}/{code}.parquet`：必须含 `date`、`close`、`turnover` 列。
- 默认 `/mnt/dataset/index_quote_history/000300.parquet`（沪深300 日行情，由
  `uv run python -m quant.cli index-quote-history` 生成）。

## 历史结果（沪深300，120 日窗口，2005-01-04 ~ 2026-06-30）

- 最新成交额：**9858 亿**，通道 **[3732 亿, 1.1 万亿]**，通道内位置 **79%**
  （偏上轨，近半年成交活跃）。
- 2015 牛市顶峰（6 月）成交额多次贴上轨并突破，随后股灾中快速跌穿中轨、
  长期在中下轨徘徊。
- 2018 熊市成交额多次贴下轨，对应市场低迷期。
- 2024-09 末放量大涨，成交额突破上轨（24900 亿），随后通道整体上移。
