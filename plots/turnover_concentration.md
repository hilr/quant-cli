# A 股日成交额集中度（5 算法）vs 沪深300

对应脚本：`plots/turnover_concentration.py`
输出：`/mnt/dataset/turnover_concentration.png`

## 图说明

5 个集中度算法各占一个子图，垂直堆叠、共享 x 轴；每个子图右轴叠加沪深300（灰淡线），对照集中度与大盘的相关性。

| 算法 | 含义 |
|---|---|
| **Gini 基尼系数** | 整体不均度（0=完全均等，1=完全集中） |
| **Pareto α** | log-log rank-amount 回归斜率绝对值（越小 = 尾部越厚） |
| **Top5 / 中位数** | top5 均值 / 全样本中位数（头部相对虹吸） |
| **HHI** | 成交额份额平方和（平方放大头部） |
| **CR10** | top10 成交额占比 |

## 怎么读

- 集中度**升高**（Gini/HHI/CR10 走高、α 走低）= 成交向少数个股集中，常出现在抱团/主题炒作期；
- 集中度**下降** = 成交分散，普涨或普跌行情。

## 与沪深300的关系

集中度变化与大盘风格高度相关：抱团牛市（如 2020-2021 核心资产）集中度飙升；普涨/底部反弹时集中度回落。本图用于判断当前是「头部驱动」还是「普涨」格局。

## 数据源

- `turnover_concentration.csv`：全 A 股日成交额集中度（gini/alpha/top5_ratio/hhi/cr10），由 `quant.cli turnover-concentration` 生成，2010 起。详见 [数据集文档](../docs/datasets/turnover_concentration.md)。
- `index_quote_history/000300.parquet`：日收盘。

## 运行

```bash
uv run python plots/turnover_concentration.py
# 可选：--data-file <path> --index-file <path> --output <path> --start-date <YYYY-MM-DD> --end-date <YYYY-MM-DD>
```
