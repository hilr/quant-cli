# industry_turnover_stack — 行业成交额占比 river 图（streamgraph，时序）

每条带 = 一个中证二级行业的成交额占比，沿时间连续流动（weighted-wiggle 基线）。每个行业一种固定颜色（按一级行业色相分组、组内二级用亮度区分），同色 = 同行业，便于追踪单一行业的连贯演变。行业按 (一级代码, 二级代码) 固定排序。

## 用法

```bash
# 最近 30 个日历日内的交易日（默认）
uv run python plots/industry_turnover_stack.py

# 最近 60 日
uv run python plots/industry_turnover_stack.py --days 60
```

| 参数 | 说明 | 默认 |
|------|------|------|
| `--days` | 最近 N 个日历日内的完整交易日 | 30 |
| `--data-path` | 只读原始数据根目录 | /mnt/readonly_dataset |
| `--output` | 输出 PNG 路径 | /mnt/dataset/industry_turnover_stack_{end}.png |

## 数据源

同 `industry_heatmap`（行业分类 + `finance_sina/stock_quote`，缺失回退 eastmoney）。

## 行业表字段

证券代码, 证券简称, 中证一/二/三/四级行业分类代码与简称（8394 只股票，11 个一级、35 个二级、~90 个三级、~200 个四级）
