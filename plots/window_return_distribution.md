# window_return_distribution — 任意标的 N 日窗口收益率分布直方图

对应脚本：`plots/window_return_distribution.py`
输出：`/mnt/dataset/return_distribution_{code}_{window}d.png`

## 图说明

把每个交易日都视作一个 N 日持有期的起点，计算 `close[t]/close[t-N] - 1`，
得到历史上所有 N 日窗口的收益率序列，再以指定桶宽做直方图，回答：

> 「历史上任意 N 个交易日的持有期收益分布长什么样？涨 / 跌超过 X% 的经验概率多大？」

- **柱子**：每个桶的占比（%）。绿 = 负收益、红 = 正收益、灰 = 恰好 0 的桶
  （中国市场习惯：红涨绿跌）。
- **橙虚线** = 均值；**蓝虚线** = 中位数；**黑实线** = 0%。
- **灰虚/点线** = 1% / 5% / 95% / 99% 尾部分位（内层 5/95 虚线、外层 1/99 点线），
  底部标 `Pq` 与对应收益。
- **紫粗线** = 当前值（最新一个 N 日窗口收益），图例与文本框标其经验百分位
  `p=…`（即历史上有 p% 的窗口收益 ≤ 当前值）。
- 右上文本框：样本数、均值 / 中位数 / 标准差、范围、1/5/95/99 分位、当前值与 p、涨跌持平占比。

## 算法

- **收益率**：前复权 `close` 的 `close[t]/close[t-N] - 1`（用前复权避免分红除息制造假跌）。
- **重叠滚动窗口（step=1）**：每个交易日都开一个新窗口，用足所有数据；
  ⚠️ 相邻窗口高度自相关，**不是独立同分布**——做"经验概率"参考可以，
  做严格统计推断（如置信区间、假设检验）要谨慎，或改用非重叠窗口。
- **桶边对齐到桶宽整数倍**（0 是桶边）：`[-1%, 0%)` 归负、`[0%, +1%)` 归正，
  0 附近不会出现跨符号的桶。

## 怎么读

| 看点 | 含义 |
|------|------|
| 分布整体右偏（右侧尾巴更长） | 历史上 N 日大涨比大跌更常见（典型于长牛标的） |
| 均值 > 中位数 | 右偏确认；少数大涨拉高了均值 |
| 红 / 绿柱高度对比 | 直观感受「胜率」——红柱总面积 = 涨的概率 |
| 1 / 5 / 95 / 99 分位线 | 极端 N 日回撤 / 拉升的经验幅度 |
| 紫线（当前）落在左尾外侧（p 很小） | 当前 N 日跌幅处于历史极端低位，相对"罕见" |
| 紫线（当前）落在右尾外侧（p 很大） | 当前 N 日涨幅处于历史极端高位，相对"过热" |
| 0 附近桶最高 | 大多数 N 日窗口收益接近 0，趋势性不强 |

## 用法

```bash
# 默认：512890 / 20 日 / 1% 桶宽
uv run python plots/window_return_distribution.py

# 换窗口长度
uv run python plots/window_return_distribution.py --window 60
uv run python plots/window_return_distribution.py --window 5

# 换桶宽（0.5%）
uv run python plots/window_return_distribution.py --bucket-width 0.005

# 换标的（基金/指数/股票均可，注意 --adjusted-dir 要对应）
uv run python plots/window_return_distribution.py --code 510880
uv run python plots/window_return_distribution.py --code 000300 \
  --adjusted-dir /mnt/dataset/index_quote_adjusted

# 限定起始日期（只看某段历史）
uv run python plots/window_return_distribution.py --start-date 2020-01-01
```

| 参数 | 说明 | 默认 |
|------|------|------|
| `--code` | 标的代码（基金/指数/股票） | 512890 |
| `--adjusted-dir` | 含 `{code}.parquet` 的前复权行情目录 | /mnt/dataset/fund_quote_adjusted |
| `--window` | 窗口长度（交易日） | 20 |
| `--bucket-width` | 直方图桶宽（小数，0.01 = 1%） | 0.01 |
| `--start-date` | 起始日期 YYYY-MM-DD | None（从最早数据起） |
| `--output` | 输出 PNG 路径 | return_distribution_{code}_{window}d.png |

## 数据源

- `{adjusted-dir}/{code}.parquet`：标的的前复权日收盘（`date`, `close` 两列即可）。

## 参考结果（512890 / 20 日 / 1% 桶宽，2019-01-18 ~ 2026-06-30）

N = 1,782 个窗口；均值 +1.02%，中位数 +0.83%，标准差 4.54%；
范围 [−11.57%, +17.14%]；1 / 5 / 95 / 99 分位 = −9.3% / −6.0% / +9.1% / +15.5%；
涨 58.2% ｜ 跌 40.9%。分布右偏，与该标的区间整体上行一致。
当前（截至 2026-06-30）20 日收益 −9.65%，p=1%——落在历史极端左尾。
