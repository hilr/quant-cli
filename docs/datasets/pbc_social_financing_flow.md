[← 数据集索引](../../README.md#数据集索引)

# pbc/social_financing_flow — 社会融资规模增量（流量）

| 项 | 内容 |
|---|------|
| 命令 | `uv run python -m quant.cli pbc-social-financing-flow --data-path <readonly> --output-dir <dataset>` |
| 输入 | `{data_path}/gov_pbc/{year}/社会融资规模/[社会融资规模增量统计表\|社会融资规模统计表].{htm,xls,xlsx}` |
| 输出 | `{output_dir}/pbc/social_financing_flow.csv`，长表，2012-01 起 |
| 格式优先级 | xlsx > xls > htm |
| 单位 | 亿元 |

**字段：**
| 字段 | 含义 |
|------|------|
| date | 月份 YYYY-MM |
| item | 分项名（见下） |
| value | 当月增量（亿元，可为负） |

**item 取值**（2024 年口径，早期分项较少）：社会融资规模增量（总量）、人民币贷款、外币贷款（折合人民币）、委托贷款、信托贷款、未贴现银行承兑汇票、企业债券、政府债券、非金融企业境内股票融资、存款类金融机构资产支持证券、贷款核销。

## 源数据坑

- **2012-2014 是宽表（htm）**：项目在行、月份在列；2015+ 是长表（月份在行、分项在列）。解析自动识别两种布局。
- **总量项命名变体**：早期「社会融资规模」，现代「社会融资规模增量」，已归一化为「社会融资规模增量」。
- **人民币贷款变体**：早期「其中:人民币贷款」，现代「人民币贷款」，已归一化。
- **分项随年代增加**：2012 仅 8 个分项，2024 有 11 个（政府债券、存款类金融机构资产支持证券、贷款核销为后增项）。

## 使用示例

```bash
uv run python -m quant.cli pbc-social-financing-flow --data-path /mnt/readonly_dataset --output-dir /mnt/dataset
```
