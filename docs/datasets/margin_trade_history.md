[← 数据集索引](../../README.md#数据集索引)

# margin_trade_history — 融资融券历史

| 项 | 内容 |
|---|------|
| 命令 | `uv run python -m quant.cli margin-trade <data_path> <source> <output_dir>` |
| 输入 | `{data_path}/{source}/margin_trade/{date}.csv` |
| 输出 | `{output_dir}/margin_trade_history/{code}.parquet` |
| 逻辑 | Schema A (深交所) → Schema B (上交所) 列名归一化，code 补零 6 位，数值列 Float64 |
| 字段 | date, code, name, margin_buy_total, margin_buy, margin_close, short_sell_total, short_sell_total_vol, short_sell_vol, short_close_vol |
| 产出 | 5117 只标的 |
| 附加 | 每股票计算：margin_net_change, short_net_change, short_vol_net_change（与上日余额之差） |

**字段含义：**
| 字段 | 含义 |
|------|------|
| margin_buy_total | 融资余额 |
| margin_buy | 融资买入额 |
| margin_close | 融资偿还额 |
| short_sell_total | 融券余额 |
| short_sell_total_vol | 融券余量 |
| short_sell_vol | 融券卖出量 |
| short_close_vol | 融券偿还量 |
| margin_net_change | 融资余额净变化 |
| short_net_change | 融券余额净变化 |
| short_vol_net_change | 融券余量净变化 |
