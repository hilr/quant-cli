# turnover_channel_breakout — 成交额通道重入信号（沪深300）

成交额 log Bollinger 通道 + 价格 ZigZag 枢轴评估。核心逻辑：成交额突破通道后重入时产生买卖信号。

- **通道**：对 `log(turnover)` 做 Bollinger（MA±kσ），`exp` 还原 → 成交额乘法通道。log 空间保证早期低位也被同等对待。
- **外溢**：当日 turnover > 上轨（放量外溢）或 < 下轨（缩量外溢），全画小标记。
- **重入信号**：sell = 成交额突破上轨外溢后跌回通道内；buy = 跌破下轨外溢后升回通道内。每段外溢只产生一次重入，无需冷却。
- **评估**：用价格 ZigZag 找阶段高/低点（H/L），对每个重入信号找最近 pivot，报告天数及价格差距。

## 用法

```bash
# 沪深300，默认参数
uv run python plots/turnover_channel_breakout.py

# 调整通道参数
uv run python plots/turnover_channel_breakout.py --window 120 --k 2.0

# 上证综指
uv run python plots/turnover_channel_breakout.py --code 000001
```

| 参数 | 说明 | 默认 |
|------|------|------|
| `--index-dir` | 指数 parquet 父目录 | /mnt/dataset/index_quote_history |
| `--code` | 指数代码 | 000300（沪深300） |
| `--start-date` | 起始日期 | 2005-01-04（沪深300上市日，全周期） |
| `--window` | 通道 MA 窗口 | 60 |
| `--k` | 通道宽度（log 空间 σ 倍数） | 2.0 |
| `--zigzag` | 价格 ZigZag 反转阈值 | 0.08（8%） |
| `--max-look` | 评估找 pivot 最大搜索半径（交易日） | 120 |
| `--output` | 输出 PNG 路径 | /mnt/dataset/turnover_channel_{code}.png |

## 输出

双面板 PNG（上=价格+ZigZag枢轴+重入信号虚线，下=成交额+通道+外溢日+重入信号）+ 控制台 pivot 距离汇总。

## 分析结果（MA120±2σ，沪深300，2010-2026）

- sell 信号 93 次：距最近 H pivot 中位 +10 日（价格中位 +3.89%，信号偏早），≤15 日命中 53%
- buy 信号 66 次：距最近 L pivot 中位 +11 日（价格中位 -3.94%），≤15 日命中 52%
- 信号普遍早于价格极端点，符合「成交额先行」直觉
