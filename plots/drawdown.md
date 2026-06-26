# drawdown — 历史回撤水下曲线 + 前复权价格（基金/指数/股票通用）

`drawdown.py` 的完整文档与结果快照。结果随数据更新，由脚本控制台输出誊写。

## 用法

```bash
# 上证红利ETF（510880），全历史
uv run python plots/drawdown.py --code 510880

# 从 2019 年起算（cummax 从该日期起累计，旧高点不参与）
uv run python plots/drawdown.py --code 510880 --start-date 2019-01-01 \
  --output /mnt/dataset/drawdown_510880_since_2019.png

# 指定输出路径
uv run python plots/drawdown.py --code 512890 --output /mnt/dataset/drawdown_512890.png
```

| 参数 | 说明 | 默认 |
|------|------|------|
| `--code` | 标的代码（基金/指数/股票） | 512890 |
| `--adjusted-dir` | 前复权行情目录 | /mnt/dataset/fund_quote_adjusted |
| `--start-date` | 起始日期 YYYY-MM-DD（cummax 从该日期起累计） | None（从最早数据起） |
| `--output` | 输出 PNG 路径（不指定则 drawdown_{code}.png） | None |

**输出：** 控制台谷值表 + 双栏 PNG（上=前复权收盘价 + 历史最高虚线；下=回撤水下曲线，深于 −15% 的谷值标日期+幅度，最大回撤标 (max)）。

## 算法

- 峰值 = 截至当日的历史最高价 `cummax(high)`
- 回撤 = 当日最低价 / 历史最高价 − 1（用 low 而非 close，口径偏深）
- 谷值检测：按历史新高分段，取每段最深谷值；深于 −15% 的谷值标注日期 + 幅度
- 用**前复权**价格，避免分红制造假回撤
- `--start-date`：过滤起始日后 cummax 从该日累计——2007/2015 等旧高点不再压制水位，适合观察特定阶段回撤

## 怎么读

| 信号 | 含义 |
|---|---|
| 红色水下面积 | 价格低于历史峰值的部分，面积越大长期套牢越重 |
| 标注谷值 | 每个新高周期的最深回撤点 |
| (max) | 区间内最大回撤 |

## 示例结果（510880 上证红利ETF，截至 2026-06-23）

**全历史**（2007-01-18 ~ 2026-06-23）：最大回撤 **−75.61%**（2008-11-04，金融危机）

| 谷值日期 | 回撤 |
|---|---|
| 2008-11-04 | −75.61% (max) |
| 2007-06-05 | −26.22% |
| 2025-04-07 | −19.35% |
| 2007-02-06 | −17.82% |

**从 2019 起**（2019-01-02 ~ 2026-06-23）：最大回撤 **−22.30%**（2022-03-16）

| 谷值日期 | 回撤 |
|---|---|
| 2022-03-16 | −22.30% (max) |
| 2020-03-23 | −20.93% |
| 2025-04-07 | −19.35% |

## 数据源

- `fund_quote_adjusted/{code}.parquet`：前复权日行情（OHLC）。

## 复现

```bash
uv run python plots/drawdown.py --code 510880 --output /mnt/dataset/drawdown_510880.png
uv run python plots/drawdown.py --code 510880 --start-date 2019-01-01 --output /mnt/dataset/drawdown_510880_since_2019.png
```
