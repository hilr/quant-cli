[← 数据集索引](../../README.md#数据集索引)

# gov_stat/retail_sales — 社会消费品零售总额月度指标

| 项 | 内容 |
|---|------|
| 命令 | `uv run python -m quant.cli gov-stat-retail-sales --data-path <readonly> --output-dir <dataset>` |
| 输入 | `{data_path}/gov_stats/社会消费品零售总额/{year}.csv`（≤2024）或 `.xlsx`（≥2025） |
| 输出 | `{output_dir}/gov_stat/retail_sales.csv`，长表，2000-01 起 |
| 逻辑 | 「指标×月份」宽表转长表，月份按列名 `YYYY年M月` 解析（列序乱序/倒序均可） |

**字段：**
| 字段 | 含义 |
|------|------|
| date | 月份 YYYY-MM |
| indicator | 指标名（含单位后缀，见下） |
| value | 数值 |

**indicator 取值（8 个）：**
- 社会消费品零售总额：当期值(亿元)、累计值(亿元)、同比增长(%)、累计增长(%)
- 限上单位消费品零售额：当期值、累计值、同比增长、累计增长

单位由 indicator 名的括号后缀标明：`亿元` 或 `%`。

## 源数据坑

- **月份列乱序/倒序**：与 trade 同源格式，按列名文本解析月份。
- **1-2 月合并公布（2012 起）**：2012 年起 1-2 月合并发布，当期值 1、2 月为空（不生成行），累计值 2 月为空；2000-2011 年单独公布，1、2 月当期值均有值。
- **格式过渡**：2025 起由 csv 改为 xlsx。
- **限上单位**：指「限额以上批零住餐单位」，体量约为全社会零售额的 40%。
- **指标名空格**：xlsx 带空格、csv 不带，已统一去除所有空白。

## 使用示例

```bash
uv run python -m quant.cli gov-stat-retail-sales --data-path /mnt/readonly_dataset --output-dir /mnt/dataset
```
