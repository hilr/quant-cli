[← 数据集索引](../../README.md#数据集索引)

# fund_hs300_correlation — 沪深300关联基金滚动相关性

| 项 | 内容 |
|---|------|
| 命令 | `uv run python -m quant.cli fund-hs300-corr <input_dir> <output_dir>` |
| 输入 | `{input_dir}/{code}.parquet`（fund_quote_adjusted） |
| 输出 | `{output_dir}/{code}.parquet` |
| 逻辑 | 筛选名称含"300"的基金，计算日收益率，与510300做滚动Pearson相关（窗口5/10/20日） |
| 字段 | date, return, corr_5, corr_10, corr_20 |
| 产出 | 80 只基金（510300自身除外） |

**字段含义：**
| 字段 | 含义 |
|------|------|
| date | 交易日期 |
| return | 日收益率（close / prev_close - 1） |
| corr_5 | 与510300的5日滚动Pearson相关系数 |
| corr_10 | 与510300的10日滚动Pearson相关系数 |
| corr_20 | 与510300的20日滚动Pearson相关系数 |
