[← 数据集索引](../../README.md#数据集索引)

# stock_quote_adjusted — 前复权行情

| 项 | 内容 |
|---|------|
| 命令 | `uv run python -m quant.cli adjust <input_dir> <output_dir>` |
| 输入 | `{input_dir}/{code}.parquet`（stock_quote_history） |
| 输出 | `{output_dir}/{code}.parquet` |
| 逻辑 | 降序检测 prev_close ≠ 前一天 close → 每日调整因子 → cum_prod(shift).fill_null(1) → 所有价格列 × 累积因子 |
| 字段 | prev_close, open, high, low, close（已复权） + date, code + 其他原列 |
| 产出 | 6207 只股票 |

**字段含义：**
| 字段 | 含义 |
|------|------|
| prev_close | 昨收价（前复权） |
| open | 开盘价（前复权） |
| high | 最高价（前复权） |
| low | 最低价（前复权） |
| close | 收盘价（前复权） |
