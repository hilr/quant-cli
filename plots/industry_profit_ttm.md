# 工业企业利润 TTM 环比变动 vs 沪深300

对应脚本：`plots/industry_profit_ttm.py`
输出：`/mnt/dataset/industry_profit_ttm_change_vs_hs300.png`

## 图说明

- **左轴**：工业企业利润 TTM（滚动 12 个月合计）的环比变动 %（蓝）。
- **右轴**：沪深300日收盘（红，淡）。
- 2007-2009 区间用橙色阴影标注（该区间 12 月数据缺失，用 11 月当月值填充）。
- 竖虚线标关键事件：2008 危机、2015 泡沫、2020 疫情、2022 封控。

## 算法

```
TTM[M]   = Σ profit[M−11 .. M]          # 滚动 12 个月当月利润合计
TTM_MoM  = TTM[M] / TTM[M−1] − 1
         = (profit[M] − profit[M−12]) / TTM[M−1]
```

即「本月利润比一年前同月多/少了多少，相对整个滚动 12 月和的占比」，等价于用去年同期替换本月后 TTM 的变化幅度。

**2007/2008/2009 的 12 月源数据缺失**，用同年 11 月的当月值补上（仅用于本图连续性），原始数据集 `gov_stat/industry_profit` 的对应月份仍为 null。

## 怎么读

| 信号 | 含义 |
|---|---|
| **TTM MoM 走高 / 转正** | 企业盈利边际改善（当月利润超过去年同期） |
| **TTM MoM 转负 / 下行** | 企业盈利恶化（当月利润低于去年同期） |

## 与沪深300的关系

工业企业利润是 A 股（尤其周期/制造业权重大的沪深300）的盈利底色：

- 利润 TTM 边际改善往往领先或同步于指数上行；
- 利润同比转负（如 2008-2009、2015、2022）对应 A 股盈利底与指数调整。

## 数据源

- `gov_stat/industry_profit/*.csv`：工业企业每月利润总额（每年一文件，由 convert 从统计局累计值差分得到）。
- `index_quote_history/000300.parquet`：日收盘。

## 运行

```bash
uv run python plots/industry_profit_ttm.py
# 可选：--profit-dir <path> --index-file <path> --output <path>
```
