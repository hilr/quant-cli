# 沪深300 成交额占两市总成交额比例 vs 沪深300

对应脚本：`plots/hs300_turnover_share.py`
输出：`/mnt/dataset/hs300_turnover_share.png`

## 图说明

双轴日频图：
- **左轴**：沪深300 成交额 / 两市总成交额（蓝色面积 + 红色 20 日滚动均线）
- **右轴**：沪深300 收盘价（灰淡线），对照占比与大盘走势的相关性

## 计算口径

```
share = hs300_turnover / (sh_turnover + sz_turnover)
```

三个数据全部来自 `/mnt/dataset/index_quote_history/`：

| 角色 | 代码 | 文件 |
|---|---|---|
| 分子（沪深300） | 000300 | `000300.parquet` |
| 分母·沪 | 000001 上证综指 | `000001.parquet` |
| 分母·深 | 399106 深证综指 | `399106.parquet` |

按日 `inner join` 三者 `turnover > 0` 的交易日（起点 2005-01-04，沪深300 上市日）。
上证综指 / 深证综指 的 `turnover` 即对应市场全部股票成交额之和，故分母 ≈ 沪深两市全部成交额。

> ⚠️ 分母必须用「综合指数」，不可用深证成指 399001：后者仅 500 只成分股，
> 2001-2022 期间是成分股口径（2014 年最低只覆盖深市 ~11%），会严重低估深市、
> 抬高沪深300 占比。仅 1995-2000 与 2023+ 399001 才 ≈ 全市场。

## 怎么读

- **占比升高**：资金向大盘蓝筹集中，常出现在抱团行情 / 风格切向大盘期；
- **占比下降**：资金向中小盘、题材股分散，常出现在普涨或中小盘行情；
- **MA20**：平滑日频噪音，看中期趋势更清晰（日频 share 单日波动较大）。

## 历史区间特征（分母 = 000001 上证综指 + 399106 深证综指）

- 2005：A 股股票少，沪深300 占比均值 ~50%；
- 2010 后随中小板 / 创业板扩容，占比趋势性下行（2010 ~38%、2015 ~37%）；
- 2020 ~30%，近年（2025 ~23%）继续走低；
- 全期均值 ~36%，最新 ~29%。

## 数据源

- `index_quote_history/000300.parquet`：沪深300 日 turnover + close
- `index_quote_history/000001.parquet`：上证综指日 turnover
- `index_quote_history/399106.parquet`：深证综指日 turnover

均由 `uv run python -m quant.cli index-quote-history` 生成。

## 运行

```bash
uv run python plots/hs300_turnover_share.py
# 可选：--hs300-file <path> --sh-file <path> --sz-file <path>
#       --output <path> --start-date <YYYY-MM-DD> --end-date <YYYY-MM-DD>
#       --ma-window <int>（默认 20）
```

**更换分母指数**：上证默认用 000001（上证综指，覆盖沪市全部 A/B 股）；
如需对照可传 `--sh-file .../000016.parquet`（上证50）等。深证同理。
