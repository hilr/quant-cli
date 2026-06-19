[← 数据集索引](../../README.md#数据集索引)

# pbc/social_financing_stock — 社会融资规模存量

| 项 | 内容 |
|---|------|
| 命令 | `uv run python -m quant.cli pbc-social-financing-stock --data-path <readonly> --output-dir <dataset>` |
| 输入 | `{data_path}/gov_pbc/{year}/社会融资规模/社会融资规模存量统计表.{htm,xls,xlsx}` |
| 输出 | `{output_dir}/pbc/social_financing_stock.csv`，长表，2015-03 起 |
| 格式优先级 | xlsx > xls > htm |
| 单位 | 存量 stock 为万亿元，增速 growth_rate 为 % |

**字段：**
| 字段 | 含义 |
|------|------|
| date | 月份 YYYY-MM |
| item | 分项名（同 flow，见下） |
| stock | 月末存量余额（万亿元） |
| growth_rate | 同比增速（%） |

**item 取值**：社会融资规模存量（总量）、人民币贷款、外币贷款（折合人民币）、委托贷款、信托贷款、未贴现银行承兑汇票、企业债券、政府债券、非金融企业境内股票、存款类金融机构资产支持证券、贷款核销。

## 源数据坑

- **2015 是季度数据**：表头为 `2015.Q1..Q4`，映射到季末月（03/06/09/12）。2016+ 为月度（12 个月）。
- **特殊列布局**：存量表月份在列方向，且每个月份占 **2 列**（存量 + 增速），表头在第 4-6 行。解析按列位置 i 推月份、i 与 i+1 分别取存量/增速。
- **与 flow 单位不同**：flow 是亿元，stock 是万亿元（差 10⁴），不要混用。
- **2012-2014 无存量表**：央行 2015 才开始公布存量数据。

## 使用示例

```bash
uv run python -m quant.cli pbc-social-financing-stock --data-path /mnt/readonly_dataset --output-dir /mnt/dataset
```
