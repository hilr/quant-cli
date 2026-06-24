[← 数据集索引](../../README.md#数据集索引)

# index_constituent_history — 指数成份股历史区间

| 项 | 内容 |
|---|------|
| 命令 | `uv run python -m quant.cli index-constituent-history <data_path> <adjust_dir> <output_dir> [--index-code 000300]` |
| 输入 | `{data_path}/csindex/index_weight/{code}/*.{csv,xls,xlsx}`（最新一份作锚点）<br>`{adjust_dir}/index_adjust_history/*.parquet`（调整事件流） |
| 输出 | `{output_dir}/index_constituent_history/{index_code}/{year}.parquet`（按指数分目录、按年份分文件） |
| 覆盖 | 2015 ~ 2026，仅 `000300`（沪深300）/`000905`（中证500）——受 weight 快照覆盖范围限制 |
| 用途 | 输入指数代码 + 日期即可过滤出该指数在该日的成份股清单 |

**字段：**
| 字段 | 含义 |
|------|------|
| index_code | 指数代码 |
| index_name | 指数简称 |
| constituent_code | 成份券代码（6 位） |
| constituent_name | 成份券名称 |
| start_date | 本次进入指数的生效日；反推窗口起点（2015）前的存量股取「最早事件 effective_date」作下界 |
| end_date | 本次退出指数的生效日；仍在册（截止锚点 T0）则为 null |

## 查询用法

每段区间 `[start_date, end_date]` **跨年份展开**——在区间覆盖的每个年份文件里都写一行（字段不变）。因此查某日成份**只需读该日期所在年份的单个文件**：

```python
import polars as pl
from datetime import date

D = date(2024, 6, 1)
df = pl.read_parquet("/mnt/dataset/index_constituent_history/000300/2024.parquet")
constituents = df.filter(
    (pl.col("start_date") <= D)
    & (pl.col("end_date").is_null() | (pl.col("end_date") >= D))
)
```

## 反推算法

1. **锚点**：取 `{code}/` 下日期最大的 weight 快照 → T0、在册集合 S0。
2. **事件**：读 `index_adjust_history` 中该指数、`effective_date <= T0` 的事件，按 `effective_date` **降序**。
3. **倒推**（从 T0 向过去走）：
   - `direction=out`（T 日调出 → T 之前在册）：code 不在 current 则加入 `current[code]=(None, T)`。
   - `direction=in`（T 日调入 → T 之前不在册）：code 在 current 则闭合该段 `(T, end)` 并移出。
   - 遍历后 current 中剩余视为「窗口起点前已在册」：start 取最早事件 effective_date。
4. **年份展开**：每段区间覆盖 `range(start.year, end_year+1)`，end 为 null 时 end_year=T0.year。

## 校验结果（2026-05-31 锚点）

- **沪深300**：全部 13 份 weight 快照交叉校验 **0 缺 0 多**（完美匹配）；查询任意日期返回 300 只。
- **中证500**：全部快照校验仅 1 只（302132）在 2023 年初 5 个月多覆盖——该股的调入事件在源数据缺失，反推只能按「最早在册」近似。
- **集合守恒**：T0 当日查询 == 最新快照全集（300==300 / 500==500）。

## 已知边界

- **窗口起点前的存量股**：start_date 取「最早事件 effective_date」作下界，实际可能更早（沪深300 2005 年成立时的元老股）。
- **调入事件缺失的股票**（如 302132）：无法确定进入时点，按「最早在册」近似 → 早期日期会多覆盖。
- **仅支持 000300/000905**：weight 数据只覆盖这两个指数；其他指数需先补 weight 数据。
- **未来调整已过滤**：effective_date > T0 的事件（锚点之后的调整）不参与反推。
