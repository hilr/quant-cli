# industry_heatmap — 行业成交额-涨幅方块热力图

finviz 风格的市场全景热力图（全 A 股聚合）：一个中证行业一个方块，方块面积 ∝ 该行业当日总成交额，颜色 = 行业成交额加权涨跌幅（A股惯例红涨绿跌，±5% 截断）。按加权涨幅倒序自然换行排列 → 左上=最大涨幅，右下=最大跌幅。

## 用法

```bash
# 最新交易日（自动跳过残缺尾段），中证三级行业（约 94 类）
uv run python plots/industry_heatmap.py

# 中证一级行业（约 11 类，更聚合）
uv run python plots/industry_heatmap.py --level 1

# 指定日期
uv run python plots/industry_heatmap.py --date 2026-06-18
```

| 参数 | 说明 | 默认 |
|------|------|------|
| `--date` | 目标日期 YYYY-MM-DD | 最新行数 ≥ 4000 的交易日 |
| `--level` | 行业层级 1/2/3/4 | 3（中证三级，约 94 类） |
| `--data-path` | 只读原始数据根目录 | /mnt/readonly_dataset |
| `--output` | 输出 PNG 路径 | /mnt/dataset/industry_heatmap_{date}_l{level}.png |

## 数据源

- 行业分类：`{data_path}/csindex/industry/{date}.xlsx`（取最新一份）
- 当日行情：`{data_path}/finance_sina/stock_quote/{date}.csv`（实时源；缺失时回退 `eastmoney/stock_quote`，已停更于 2025-11）
