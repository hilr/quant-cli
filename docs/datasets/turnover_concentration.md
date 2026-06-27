[← 数据集索引](../../README.md#数据集索引)

# turnover_concentration — 全 A 股日成交额集中度（5 算法）

| 项 | 内容 |
|---|------|
| 命令 | `uv run python -m quant.cli turnover-concentration --data-path <readonly> --output-dir <dataset> [--start-year 1990]` |
| 输入 | `{data_path}/finance_sina/stock_quote/{date}.csv`，缺失时回退 `{data_path}/eastmoney/stock_quote/{date}.csv` |
| 输出 | `{output_dir}/turnover_concentration.csv`，宽表，1992-10-20 起（默认不截断，`--start-year` 可再收窄） |
| 完整性 | 当日 CSV 行数 ≥ 50 才纳入（过滤半截/测试文件；现代年份无残缺抓取，门槛只影响早期小市场） |
| 字段 | date, gini, alpha, top5_ratio, hhi, cr10, stock_count, free_float_market_cap_total, market_cap_total |

## 字段

| 字段 | 含义 | 量纲 | 集中度↑ | 集中度↓ |
|------|------|------|---------|---------|
| date | 交易日 YYYY-MM-DD | — | — | — |
| gini | Gini 基尼系数 | [0, 1] 无量纲 | 抱团/虹吸 | 普涨/分散 |
| alpha | Pareto 幂律指数（log-log 回归斜率绝对值） | 无量纲，典型 1.0~1.6 | 尾部变薄（分布更均） | 尾部变厚（少数头部虹吸） |
| top5_ratio | 成交额前 5 均值 / 全样本中位数 | 倍数，典型 30~300 | 头部相对虹吸 | 头部优势减弱 |
| hhi | HHI 赫芬达尔指数 | [0, 1] 无量纲，典型 0.001~0.005 | 头部集中（平方放大） | 分散 |
| cr10 | 前 10 大成交额占比 | [0, 1] 无量纲，典型 0.05~0.12 | top10 虹吸 | top10 占比下降 |
| stock_count | 当日 turnover > 0 的股票数 | 只 | — | — |
| free_float_market_cap_total | 同口径（turnover>0）股票流通市值之和 | 元（作图除以 1e12 → 万亿） | — | — |
| market_cap_total | 同口径（turnover>0）股票总市值之和 | 元（作图除以 1e12 → 万亿） | — | — |

**集中度↑ 对大盘的含义：** 资金在少数票上抱团，风格偏向结构性行情；
**集中度↓：** 资金分散到多数票，偏向普涨。

## 算法

输入：当日全 A 股 `turnover > 0` 的成交额序列 `x`（长度 n，和 s）。
所有算法在 `quant/convert.py::_concentration_metrics` 中实现。

### Gini 基尼系数

整体不均度，取值 [0, 1]：0 = 完全均等，1 = 完全集中在一票。
对长尾分布敏感度适中，是 5 个算法里最"中性"的指标。

```
gini = Σ((2i - n - 1) · x_sorted[i]) / (n · s)
```

### Pareto α（幂律指数）

把当日成交额按降序排名（rank 1 = 最大），对 (log rank, log amount) 全点回归，
斜率绝对值即 α。α 越小 = 尾部越厚 = 头部虹吸越显著。
α ∈ (1, ∞)，A 股典型 1.0~1.6。

```
slope, _ = polyfit(log(1..n), log(x_sorted[::-1]), 1)
alpha    = |slope|
```

### Top5 / median

成交额前 5 名均值 ÷ 全样本中位数。
对极端头部最敏感（单只票放量爆炒时该值飙升），同时因为分母用中位数而非均值，
不受头部以外大部分票的分布影响。
跨度大（30~300+），适合观察极端抱团事件。

### HHI（赫芬达尔-赫希曼指数）

各票成交额份额平方和。平方放大让头部票的权重显著超过线性指标。
取值 [1/n, 1]，A 股典型 0.001~0.005，差异分辨率高。

```
hhi = Σ(share_i²)  where share_i = x_i / s
```

### CR10（前 10 大成交额占比）

最直观可解释的指标：成交额前 10 大票占当日全市场成交额的比例。
适合做叙事性展示（"今天最活跃的 10 只票占了 X% 的成交"）。

```
cr10 = Σ(top10 shares)
```

## 源数据坑

- **早期 A 股股票数少**：1992 ~50 只、2000 ~1000 只、2010 ~1700 只、2015 ~2400 只、
  2020 ~3800 只、2026 ~5400 只。行数阈值定为 50 以保留 1992 起的完整历史（早期全市场本身就 <1000 只）。
  现代年份（2005+）最小文件均 >800 行、无残缺抓取，故 50 行门槛只影响早期。
  注意早期（尤其 1992-2000）集中度算法在样本极少时噪音大，解读需谨慎；
  `stock_count` / `market_cap` 等汇总列对任何年代都成立。
- **CSV dtype 推断**：单日 CSV 的 `turnover` / `market_cap` 列在早期行若是纯整数，
  Polars 默认推断为 i64，遇到后面的浮点行会报解析错误。读取时显式设 `infer_schema_length=10000`
  让 Polars 看到足够多样本后再决定类型。
- **finance_sina → eastmoney fallback**：finance_sina 是实时源（1992-至今），
  eastmoney 是历史归档（2022-2025 已停更）。同日 finance_sina 优先，避免重复；
  只在 finance_sina 缺该日时才走 eastmoney。
- **turnover ≤ 0 过滤**：停牌/异常股票的 turnover 为 0 或 NaN，全部剔除，
  否则会让 gini/hhi 等指标失真。

## 使用示例

```bash
# 生成 1992 起的完整历史（默认不截断）
uv run python -m quant.cli turnover-concentration \
    --data-path /mnt/readonly_dataset \
    --output-dir /mnt/dataset

# 配套可视化：5 子图叠加沪深300
uv run python plots/turnover_concentration.py \
    --data-file /mnt/dataset/turnover_concentration.csv \
    --index-file /mnt/dataset/index_quote_history/000300.parquet \
    --output /mnt/dataset/turnover_concentration.png
```

**关联图表：** `plots/turnover_concentration.py` — 5 个算法各占一个垂直堆叠子图，
右轴叠加沪深300 收盘价，用于肉眼比较每个算法的信号质量及与大盘的相关性。

## 阶段 2 接口（未实现）

本数据集只输出原始测量值，不做标准化/合成。计划在阶段 2 建立独立数据集
`turnover_concentration_composite.csv`，将 5 个指标各自做滚动 250 日百分位标准化后
加权合成单一综合指标；阶段 1 的 CSV 列名（`gini, alpha, top5_ratio, hhi, cr10`）
**发布后不再改名**，以便阶段 2 稳定索引。
