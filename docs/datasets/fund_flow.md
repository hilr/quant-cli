[← 数据集索引](../../README.md#数据集索引)

# fund_flow — 基金资金流

| 项 | 内容 |
|---|------|
| 命令 | `uv run python -m quant.cli fund-flow <shares_dir> <quote_dir> <output_dir>` |
| 输入 | `{shares_dir}/{code}.parquet`（fund_shares_history） + `{quote_dir}/{code}.parquet`（fund_quote_history） |
| 输出 | `{output_dir}/{code}.parquet` |
| 逻辑 | share_change × close = est_amount（估算每日加减仓金额） |
| 字段 | date, shares, share_change, close, net_value, est_amount |
| 产出 | 1988 只基金（两数据源均有覆盖的） |

**字段含义：**
| 字段 | 含义 |
|------|------|
| shares | 基金份额 |
| share_change | 份额变动 |
| close | 收盘价 |
| net_value | 单位净值 |
| est_amount | 估算资金流（份额变动 × 收盘价） |
