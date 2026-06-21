[← 数据集索引](../../README.md#数据集索引)

# pbc/overseas_rmb_assets — 境外机构和个人持有境内人民币金融资产

| 项 | 内容 |
|---|------|
| 命令 | `uv run python -m quant.cli pbc-overseas-rmb-assets --data-path <readonly> --output-dir <dataset>` |
| 输入 | `{data_path}/gov_pbc/{year}/货币统计概览/境外机构和个人持有境内人民币金融资产情况[Domestic RMB Financial Assets Held by Overseas Entities].{htm,xls,xlsx}` |
| 输出 | `{output_dir}/pbc/overseas_rmb_assets.csv`，宽表，2014-01 起 |
| 格式优先级 | xlsx > xls > htm（有电子表格就不用 htm） |

**字段（单位均为亿元，月末存量）：**

| 字段 | 含义 |
|------|------|
| date | 月份 YYYY-MM |
| 股票 | 境外机构/个人持有的境内股票 |
| 债券 | 境外机构/个人持有的境内债券 |
| 贷款 | 境外机构/个人持有的境内贷款 |
| 存款 | 境外机构/个人持有的境内存款 |

## 算法

每个源文件是「项目×月份」宽表：行=4 个指标，列=当年 12 个月。用「行内数字序列」法解析——项目名取每行首个非数字单元格，值取其后所有数字按序对应表头月份序列。

## 源数据坑

- **文件名变体**：早期（2015-2022）为「境外机构和个人持有境内人民币金融资产情况Domestic RMB Financial Assets Held by Overseas Entities.{xls,htm,pdf}」，近年（2023+）为纯中文 `.xlsx`，2014 仅 `.htm`。按 startswith「境外机构」统一匹配。
- **Excel 月份浮点截断**：xlsx 里 10 月单元格 `2024.10` 被 Excel 存成浮点 `2024.1`（与 1 月同值）。月份按列位置推断（`_pbc_period_to_date`），不解析数值。
- **2014 文件的「2013年末」期末列**：2014 文件表头在 12 个月份前多一个「2013年末」首列。用 `_pbc_parse_period_str` 过滤（它解析不出合法月份），并在数据行多出对应值时跳过前导期末值。
- **2014 htm 表头/数据列错位**：htm 表头首列是「2013年末」，数据首列是项目名（多一个前导空列），绝对列索引对不齐。故采用行内数字序列法（不依赖绝对列索引）。
- **项目名中英混排**：源文件项目名是「中文\n English」含换行，`_pbc_norm_item` 去换行 + 尾部英文后归一化为「股票/债券/贷款/存款」。

## 使用示例

```bash
uv run python -m quant.cli pbc-overseas-rmb-assets --data-path /mnt/readonly_dataset --output-dir /mnt/dataset
```

## 典型读数（亿元）

| 时点 | 股票 | 债券 | 贷款 | 存款 |
|---|---|---|---|---|
| 2014-12 | 5,555 | 6,716 | 8,190 | 23,722 |
| 2018-06 | 12,752 | 16,517 | 8,243 | 11,841 |
| 2025-12 | 36,674 | 34,990 | 11,657 | 18,572 |
