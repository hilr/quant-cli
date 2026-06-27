# 沪深两市总成交额（日频）vs 沪深300

对应脚本：`plots/market_turnover_total.py`
输出：`/mnt/dataset/market_turnover_total.png`

## 图说明

双轴日频图：
- **左轴**：两市总成交额（蓝色面积 + 红色 20 日滚动均线），单位亿元
- **右轴**：沪深300 收盘价（灰淡线），对照量价关系
- `--log`：左轴改对数刻度（早期几百亿 vs 现在万亿，跨度大时更清晰）

## 计算口径

```
total = sh_turnover + sz_turnover        # 元
显示值 = total / 1e8                       # 亿元
```

两个数据全部来自 `/mnt/dataset/index_quote_history/`：

| 角色 | 代码 | 文件 |
|---|---|---|
| 沪市全市场 | 000001 上证综指 | `000001.parquet` |
| 深市全市场 | 399106 深证综指 | `399106.parquet` |

**必须用「综合指数」**：上证综指 / 深证综指 的 `turnover` 即各自市场全部股票成交额之和。
不可用深证成指 399001——它仅 500 只成分股，2001-2022 期间是成分股口径
（2014 年最低只覆盖深市 ~11%），会严重低估深市。
（仅 1995-2000 与 2023+ 399001 才 ≈ 全市场。）

## 怎么读

- **放量**：MA20 抬升、面积走高，常对应行情启动 / 资金涌入；
- **缩量**：MA20 回落，常对应调整 / 观望期；
- **与沪深300 对照**：放量 + 指数走高 = 量价齐升；放量 + 指数走弱 = 顶部分歧 / 出货。

## 数据源

- `index_quote_history/000001.parquet`：上证综指日 turnover
- `index_quote_history/399106.parquet`：深证综指日 turnover
- `index_quote_history/000300.parquet`：沪深300 日 close（右轴）

均由 `uv run python -m quant.cli index-quote` 生成。

## 运行

```bash
uv run python plots/market_turnover_total.py
# 可选：--sh-file <path> --sz-file <path> --hs300-file <path>
#       --output <path> --start-date <YYYY-MM-DD> --end-date <YYYY-MM-DD>
#       --ma-window <int>（默认 20）--log
```
