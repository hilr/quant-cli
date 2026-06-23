[← 数据集索引](../../README.md#数据集索引)

# exchange_hkex/southbound_flow — 港股通南向每日资金流

| 项 | 内容 |
|---|------|
| 命令 | `uv run python -m quant.cli exchange-hkex-southbound-flow --data-path <readonly> --output-dir <dataset>` |
| 输入 1 | `{data_path}/exchange_hkex/hk_connect_total.csv`（长表，已为亿港元，覆盖 < 2021-06-15） |
| 输入 2 | `{data_path}/exchange_hkex/connect_top/{YYYY-MM-DD}.csv`（覆盖 ≥ 2021-06-15） |
| 输出 | `{output_dir}/exchange_hkex/southbound_flow.csv`，宽表，2015-08-10 起 |

**字段（单位均为亿港元）：**

| 字段 | 含义 |
|------|------|
| date | 交易日 YYYY-MM-DD |
| sse_buy_yi | 沪股通南向买入额（SSE Southbound 聚合行） |
| sse_sell_yi | 沪股通南向卖出额（SSE Southbound 聚合行） |
| szse_buy_yi | 深股通南向买入额（SZSE Southbound 聚合行） |
| szse_sell_yi | 深股通南向卖出额（SZSE Southbound 聚合行） |
| buy_yi | 南向合计买入 = sse_buy_yi + szse_buy_yi |
| sell_yi | 南向合计卖出 = sse_sell_yi + szse_sell_yi |
| net_yi | **南向净流入 = buy_yi − sell_yi**，>0 表示内地净买入港股 |

## 算法

两个源拼接：

- **`hk_connect_total.csv`**（早期，< 2021-06-15）：长表 `date,code,buy,sell`，
  筛 `code ∈ {SSE Southbound, SZSE Southbound}` 两行，**直接读为亿港元**，无需换算。
- **`connect_top/{YYYY-MM-DD}.csv`**（≥ 2021-06-15）：每日一文件，顶部 4 行通道
  聚合（"南下资金统计"）+ top10 个股明细。筛 `code ∈ {SSE Southbound, SZSE Southbound}`，
  原值单位推断为**百万港元**（÷100 换算到亿港元），`date` 一律取自文件名。

两源同日 SSE Southbound 实测一致：2021-06-24 `hk=80.87` ≈ `connect_top=8086.67÷100`。

## 源数据坑

- **`hk_connect_total` 覆盖 2015-08-10 ~ 2023-03-24**：用 connect_top 启动前部分
  （< 2021-06-15），其余 ignore。`connect_top` 与之重叠的 2021-06-15 ~ 2023-03
  部分一律 connect_top 优先。
- **2016-12-05 前深股通未开通**：hk_connect_total 中 SZSE Southbound 缺失，
  对应 ~309 个交易日的 `szse_*_yi` 列为 null，`net_yi` 也为 null
  （只算 SSE Southbound 才有意义）。下游计算前需 `fill_null(0)`（停盘/未开通
  = 没流量 = 加 0）。注意：polars `read_csv` 默认 `infer_schema_length=100`，
  会因前 309 行 szse 全空而误推 str，下游需 `schema_overrides={*: Float64}`。
- **Schema 跨年变化**（connect_top，按列名读取，不依赖顺序）：
  - 2021-2022 多数：`date,code,name,buy,sell`
  - 2022 部分（如 2022-06-15）：`code,buy,sell,name`（无 date 列！）
  - 2023+：`date,code,证券简称,buy,sell`
- **聚合行单位（connect_top）= 百万港元**：2024-06-14 实测 SSE Southbound
  聚合 buy=12848.62，对应 top10 个股 buy 合计 ≈ 4412 百万港元（44.12 亿），
  聚合是个股的 ~2.9 倍，符合"汇总 > top10"预期；若单位为万元则聚合反小于
  top10，不成立。输出 ÷100 换算到亿港元。
- **空值（南向停盘）**：HK 假期或半日市时（如 2021-07-01 HK 回归日、2022-04-18
  复活节翌日等共 9 个 connect_top 日期）buy/sell 为空字符串，输出 null。
- **999999999 sentinel**：北向 2025+ 出现（疑似源系统标记缺失），南向目前无此值，
  但 `convert` 一律按 `>= 9.9e8` 置 null 以防后续变化。
- **北向 aggregate 在 2025+ 也异常**：SSE Northbound 2025+ 文件 buy 是 6-7 位数
  大值、sell 恒为 999999999（明显坏数据）。本数据集只取南向，不受影响，但提醒
  后续若做北向需另行排查。

## 使用示例

```bash
uv run python -m quant.cli exchange-hkex-southbound-flow \
    --data-path /mnt/readonly_dataset --output-dir /mnt/dataset
```

下游 polars 读取示例（避免类型推断坑）：

```python
import polars as pl
df = pl.read_csv("southbound_flow.csv", try_parse_dates=True,
                 schema_overrides={c: pl.Float64 for c in
                     ["sse_buy_yi","sse_sell_yi","szse_buy_yi","szse_sell_yi",
                      "buy_yi","sell_yi","net_yi"]})
df = df.with_columns(pl.col("net_yi").fill_null(0))
```

## 典型读数（亿港元）

| 日期 | sse_buy_yi | sse_sell_yi | szse_buy_yi | szse_sell_yi | net_yi | 备注 |
|---|---|---|---|---|---|---|
| 2015-08-10 | 19.66 | 13.46 | null | null | null | 首日，深股通 2016-12 才开 |
| 2017-01-04 | 14.25 | 10.31 | 2.96 | 0.71 | 6.19 | 早期规模小 |
| 2021-07-01 | null | null | null | null | null | HK 回归日停盘 |
| 2024-06-14 | 128.49 | 97.97 | 113.09 | 85.53 | 58.07 | 普通交易日 |
| 2025-04-09 | — | — | — | — | 大正 | 60 日滚动峰值附近 |
| 2025-12-30 | 289.06 | 302.33 | 153.22 | 178.40 | -38.45 | 年末净流出 |
