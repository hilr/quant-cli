[← 数据集索引](../../README.md#数据集索引)

# margin_trade_daily — 融资融券每日净变化

| 项 | 内容 |
|---|------|
| 命令 | `uv run python -m quant.cli margin-trade-daily <input_dir> <output_dir>` |
| 输入 | `{input_dir}/{code}.parquet`（margin_trade_history） |
| 输出 | `{output_dir}/{date}.parquet` |
| 逻辑 | 读入所有标的的净变化列，按日期分组写入，已存在则跳过 |
| 字段 | date, code, name, margin_net_change, short_net_change, short_vol_net_change |
| 产出 | 3901 个日期文件 |
