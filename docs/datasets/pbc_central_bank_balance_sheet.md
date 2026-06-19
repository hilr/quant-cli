[← 数据集索引](../../README.md#数据集索引)

# pbc/central_bank_balance_sheet — 货币当局资产负债表

| 项 | 内容 |
|---|------|
| 命令 | `uv run python -m quant.cli pbc-central-bank-balance-sheet --data-path <readonly> --output-dir <dataset>` |
| 输入 | `{data_path}/gov_pbc/{year}/[货币统计概览/]货币当局资产负债表.{htm,xls,xlsx}` |
| 输出 | `{output_dir}/pbc/central_bank_balance_sheet.csv`，长表，1999-01 起 |
| 格式优先级 | xlsx > xls > htm |
| 单位 | 亿元 |

**字段：**
| 字段 | 含义 |
|------|------|
| date | 月份 YYYY-MM |
| item | 项目名（资产方 + 负债方全明细） |
| value | 月末余额（亿元） |

**item 包括**（按出现顺序）：资产方——国外资产（外汇、货币黄金、其他国外资产）、对政府债权（其中中央政府）、对其他存款性公司债权、对其他金融性公司债权、对非金融性部门债权、其他资产、**总资产**；负债方——储备货币（货币发行、金融性公司存款、其他存款性公司存款、其他金融性公司存款、非金融机构存款）、不计入储备货币的金融性公司存款、发行债券、国外负债、政府存款、自有资金、其他负债、**总负债**。

## 源数据坑

- **1999-2007 在年份根目录**：早期文件直接在 `gov_pbc/{year}/`，2008+ 在 `货币统计概览` 子目录。查找函数自动回退到根目录。
- **总资产 = 总负债**：央行资产负债表恒等，两个汇总行每月数值相等，可作数据完整性校验。
- **Excel 月份截断**：xlsx 月份列是数字 `2024.01`，10 月被截断成 `2024.1`。月份按列位置推断。
- **全明细输出**：约 22 个项目行/月。项目名已去英文翻译、去「其中：」前缀外的多余空白。

## 使用示例

```bash
uv run python -m quant.cli pbc-central-bank-balance-sheet --data-path /mnt/readonly_dataset --output-dir /mnt/dataset
```
