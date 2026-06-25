# SHIBOR 3M 银行间利率 vs 沪深300

对应脚本：`plots/shibor_vs_hs300.py`
输出：`/mnt/dataset/shibor_3m_vs_hs300.png`

## 图说明

- **左轴**：SHIBOR（上海银行间同业拆放利率）3 个月品种，单位 %（蓝）。
- **右轴**：沪深300日收盘（红，淡）。
- 时间范围 2013 至今（受限于 SHIBOR 年度文件起始 2013）。
- 竖虚线标关键事件：2013 钱荒、2015 股灾、2018 去杠杆、2020 疫情、2022 封控、2024 政策转向。

## 算法

直接读 SHIBOR 原始年度文件，统一为 `rate_3m` 列后按日排序拼接。**源格式跨年不一致**：

- ≤2025：`shibor/shibor/{year}.csv`，列名 `date,on,1w,2w,1m,3m,...`，日期 `2026-06-16`。
- 2026：`shibor/shibor/{year}.xls`（实为 xlsx），列名 `Date,O/N,...,3M,...`，日期 `16 Jun 2026`。

2026 的 xlsx 用 zipfile + ElementTree 手解（定位 `3M` 列索引 + `Date` 列），按 `%d %b %Y` 解析日期。

## 怎么读

| 信号 | 含义 |
|---|---|
| **SHIBOR 3M 飙升** | 银行间流动性收紧（如 2013 钱荒 3M 冲到 ~5%+） |
| **SHIBOR 3M 持续走低** | 货币宽松，银行间资金充裕 |
| **急速下行** | 政策宽松信号（如 2024 转向） |

## 与沪深300的关系

SHIBOR 反映银行间（无风险短端）流动性，与大盘并非简单同步：

- **流动性收紧（利率飙升）** 通常压制风险资产，如 2013 钱荒、2018 去杠杆对应 A 股调整；
- **宽松（利率走低）** 是行情的必要条件之一，但能否转化成 A 股上涨还看信用传导与风险偏好。

## 数据源

- `/mnt/readonly_dataset/shibor/shibor/{year}.csv`（≤2025）/ `{year}.xls`（2026，实为 xlsx）：每日 SHIBOR 各期限利率。
- `index_quote_history/000300.parquet`：日收盘。

## 运行

```bash
uv run python plots/shibor_vs_hs300.py
# 可选：--data-path <path> --index-file <path> --output <path>
```
