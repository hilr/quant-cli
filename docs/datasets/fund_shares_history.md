[← 数据集索引](../../README.md#数据集索引)

# fund_shares_history — 基金份额历史

| 项 | 内容 |
|---|------|
| 命令 | `uv run python -m quant.cli fund-shares <data_path> <output_dir>` |
| 输入 | `{data_path}/exchange_sse/fund_shares/{date}.csv` + `{data_path}/exchange_szse/fund_shares/{date}.csv` |
| 输出 | `{output_dir}/fund_shares_history/{code}.parquet` |
| 逻辑 | SSE: shares_10k × 10000, SZSE: shares 直接取，统一为 shares(Float64)，zfill(6) |
| 字段 | date, code, name, shares, share_change |
| 产出 | 1989 只基金 |

**字段含义：**
| 字段 | 含义 |
|------|------|
| shares | 基金份额 |
| share_change | 份额变动（与上日差额） |
