[← 数据集索引](../../README.md#数据集索引)

# pbc/money_supply — 央行货币供应量 M0/M1/M2

| 项 | 内容 |
|---|------|
| 命令 | `uv run python -m quant.cli pbc-money-supply --data-path <readonly> --output-dir <dataset>` |
| 输入 | `{data_path}/gov_pbc/{year}/[货币统计概览/]货币供应量[表].{htm,xls,xlsx}` |
| 输出 | `{output_dir}/pbc/money_supply.csv`，宽表，2004-01 起 |
| 格式优先级 | xlsx > xls > htm（有电子表格就不用 htm） |

**字段：**
| 字段 | 含义 |
|------|------|
| date | 月份 YYYY-MM |
| m0 | 流通中货币/现金 M0（亿元） |
| m1 | 货币 M1（亿元） |
| m2 | 货币和准货币 M2（亿元） |

## 源数据坑

- **1999-2003 跳过**：这几年没有专门的「货币供应量表」，只有「货币概览」（含 M0/M1/M2 但仅年末单月数据）。数据集从 2004（首张专门表）起。
- **文件名变体**：`货币供应量.htm` / `货币供应量表.htm` / `货币供应量Money Supply.xls` / `货币供应量.xlsx`，按 startswith「货币供应量」统一匹配。
- **M0 名称变体**：早期「流通中现金（M0）」，近年「流通中货币（M0）」，已归一化到同一列。
- **层级缩进**：M1/M0 项目名通过列位置表示层级（M1 在第 1 列、M0 在第 2 列）。解析用「行内数字序列」法——每行第一个非数字单元格作项目名，其余数字按序对应月份。
- **Excel 月份截断**：xlsx 里 10 月单元格是数字 `2024.10`，被 Excel 存成浮点 `2024.1`（与 1 月同值）。月份严格按列位置推断（第 i 个数据列 = 第 i 个月），不解析数值。

## 使用示例

```bash
uv run python -m quant.cli pbc-money-supply --data-path /mnt/readonly_dataset --output-dir /mnt/dataset
```
