[← 数据集索引](../../README.md#数据集索引)

# fund_quote_history — 基金行情历史

| 项 | 内容 |
|---|------|
| 命令 | `uv run python -m quant.cli fund-quote <data_path> <source> <output_dir>` |
| 输入 | `{data_path}/{source}/fund_quote/{date}.csv` |
| 输出 | `{output_dir}/fund_quote_history/{code}.parquet` |
| 逻辑 | exchange → 交易所 列名统一，数值列 Float64，zfill(6) |
| 字段 | date, code, name, prev_close, open, high, low, close, volume, turnover, net_value, 交易所, 折价率 |
| 产出 | 2614 只基金 |

**字段含义：**
| 字段 | 含义 |
|------|------|
| prev_close | 昨收价 |
| open | 开盘价 |
| high | 最高价 |
| low | 最低价 |
| close | 收盘价 |
| volume | 成交量 |
| turnover | 成交额 |
| net_value | 单位净值 |
| 交易所 | 交易所（SSE/SZSE） |
| 折价率 | 折价率（%） |
