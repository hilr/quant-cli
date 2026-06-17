[← 数据集索引](../../README.md#数据集索引)

# stock_quote_history — 股票行情历史

| 项 | 内容 |
|---|------|
| 命令 | `uv run python -m quant.cli stock-quote <data_path> <source> <output_dir>` |
| 输入 | `{data_path}/{source}/stock_quote/{date}.csv` |
| 输出 | `{output_dir}/stock_quote_history/{code}.parquet`（每股票一个文件） |
| 逻辑 | 读取每日 CSV，合并后按 code+date 排序，分股票写入 parquet |
| 字段 | date, code, 证券简称, prev_close, open, high, low, close, volume, turnover, market_cap, free_float_market_cap |
| 产出 | 6207 只股票 |

**字段含义：**
| 字段 | 含义 |
|------|------|
| date | 交易日期 |
| code | 股票代码（6位，补零） |
| 证券简称 | 股票名称 |
| prev_close | 昨收价 |
| open | 开盘价 |
| high | 最高价 |
| low | 最低价 |
| close | 收盘价 |
| volume | 成交量 |
| turnover | 成交额 |
| market_cap | 总市值 |
| free_float_market_cap | 流通市值 |
