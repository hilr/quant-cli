[← 数据集索引](../../README.md#数据集索引)

# gov_stat/port_freight — 全国港口货物吞吐量月度指标

| 项 | 内容 |
|---|------|
| 命令 | `uv run python -m quant.cli gov-stat-port-freight --data-path <readonly> --output-dir <dataset>` |
| 输入 | `{data_path}/gov_stats/全国港口货物吞吐量/{year}.xlsx` |
| 输出 | `{output_dir}/gov_stat/port_freight.csv`，长表，2019-01 起 |
| 逻辑 | 「指标×月份」宽表转长表，月份按列名 `YYYY年M月` 解析（列序倒序）；1-2 月合并缺口的当期值自动填补（见下） |

**字段：**
| 字段 | 含义 |
|------|------|
| date | 月份 YYYY-MM |
| indicator | 指标名（含单位后缀，见下） |
| value | 数值 |

**indicator 取值（12 个 = 3 主指标 × 4 子指标）：**
- 全国港口货物吞吐量：当期值(万吨)、累计值(万吨)、同比增长(%)、累计增长(%)
- 外贸货物吞吐量：当期值、累计值、同比增长、累计增长
- 沿海港口货物吞吐量：当期值、累计值、同比增长、累计增长

单位由 indicator 名的括号后缀标明：`万吨` 或 `%`。

## 1-2 月合并发布的三种模式

NBS（实际为交通运输部）对 1-2 月合并发布的处理方式历年有变，转换器自动识别并填补：

| 年份 | 模式 | 原始数据 | 填补规则 |
|---|---|---|---|
| 2019-2023 | SPLIT | 当期[1月]、当期[2月] 各自独立 | 不动 |
| 2024-2025 | MERGED | 当期[1月]、当期[2月] 都空；累计[2月] = 1+2 月合计 | **平摊**：Jan = Feb = 累计[2月] / 2 |
| 2026 | 半合并 | 当期[1月] 空，**当期[2月] 有值**；累计[2月] = 1+2 月合计 | **反推**：Jan = 累计[2月] − 当期[2月]，Feb 保留实际值 |

反推模式下 Jan + Feb = 累计[2月]（和校验自洽）。详见 `quant/convert.py::_gov_stat_fill_jan_feb`。

## 源数据坑

- **月份列倒序**：xlsx 表头月份从 12 月→1 月，按列名文本解析（不依赖列顺序）。
- **指标名空格**：xlsx 带尾随空格（如 `全国港口货物吞吐量_当期值 (万吨) `），已统一去除所有空白。
- **2026 文件不完整**：截至当前只到当年 5 月，是部分年份。
- **统计口径调整（影响同比可比性）**：2020-01 起海洋水路运输统计方式由行业主管部门报送改为企业联网直报，2020 年增速按可比口径计算。跨 2019/2020 的同比需谨慎解读。

## 使用示例

```bash
uv run python -m quant.cli gov-stat-port-freight --data-path /mnt/readonly_dataset --output-dir /mnt/dataset
```

**关联：** 同类口径还有 [`gov_stat/freight`](gov_stat_freight.md)（货运量）、[`gov_stat/passenger`](gov_stat_passenger.md)（客运量），均为交通运输部月度指标。

**关联图表：** [`plots/port_freight_vs_hs300`](../../plots/port_freight_vs_hs300.md)——取全国港口 + 外贸（码头过磅称重，计量准确），3 panel 看 12 月滚动合计水平 / 同比 / 环比 vs 沪深300。
