[← 数据集索引](../../README.md#数据集索引)

# pbc/exchange_rate — 人民币兑美元汇率

| 项 | 内容 |
|---|------|
| 命令 | `uv run python -m quant.cli pbc-exchange-rate --data-path <readonly> --output-dir <dataset>` |
| 输入 | `{data_path}/gov_pbc/{year}/[货币统计概览/]汇率报表[Exchange Rate].{htm,xls,xlsx}` |
| 输出 | `{output_dir}/pbc/exchange_rate.csv`，宽表，1999-12 起 |
| 格式优先级 | xlsx > xls > htm（有电子表格就不用 htm） |

**字段（单位均为人民币元/美元，中间价）：**

| 字段 | 含义 |
|------|------|
| date | 月份 YYYY-MM |
| usd_cny_eop | 一美元折合人民币（期末数）= 月末美元中间价 |
| usd_cny_avg | 一美元折合人民币（平均数）= 月均美元中间价 |

## 算法

每个源文件是「项目×月份」宽表：项目固定 3 行（USD 期末 / USD 平均 / SDR 期末），月份在列。
只取 USD 两行（SDR 行不输出）。用列对齐法：表头单元格经 `_pbc_parse_period_str`
解析首列真实年月，后续月份按列位置递增，再按列索引取数据行同列的值。

## 源数据坑

- **文件名变体**：早期（1999-2014）为根目录或「货币统计概览」下的「汇率报表.htm」；
  2015-2022 为「汇率报表Exchange Rate.{xls,htm,pdf}」（取 .xls）；2023+ 为纯中文「汇率报表.xlsx」。
  按 startswith「汇率报表」统一匹配。
- **Excel 月份浮点截断**：.xls 里 10 月表头 `2015.10` 被 Excel 存成浮点 `2015.1`，
  被 `_pbc_parse_period_str` 误判为 Q1→3 月（实测 2015/2017/2018/2021 的 10 月曾被吃掉）。
  月份不逐列解析字符串——取首列真实年月（首列总是 `YYYY.01` 或 1999 的 `1999.12`，
  不受截断影响），后续按列位置递增（第 10 列即 10 月）。
- **1999 只有 12 月**：1999 文件仅有 12 月一列（PBC 当年起开始发布）。列位置法会把
  col_pos=1 误判为 1 月，故必须读首列字符串 `1999.12` 才能正确归到 12 月。
- **项目名中英分行**：2015+ 文件每个项目占两行（中文 + 英文翻译 `Yuan per US Dollar ...`）。
  英文行经 `_pbc_norm_item` 归一化后不含「美元」关键词，自然被跳过。

## 使用示例

```bash
uv run python -m quant.cli pbc-exchange-rate --data-path /mnt/readonly_dataset --output-dir /mnt/dataset
```

## 典型读数（人民币元/美元）

| 时点 | usd_cny_eop | usd_cny_avg | 备注 |
|---|---|---|---|
| 1999-12 | 8.2793 | 8.2783 | 8.28 盯住时代 |
| 2005-07 | 8.1080 | 8.2369 | 7/21 汇改，一次性升值 |
| 2014-12 | 6.1190 | 6.1238 | |
| 2024-12 | 7.1884 | 7.1887 | |
