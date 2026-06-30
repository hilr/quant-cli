# drawdown_extremes_vs_hs300 — 任意标的回撤极值点（峰/谷）叠加沪深300

对应脚本：`plots/drawdown_extremes_vs_hs300.py`
输出：`/mnt/dataset/drawdown_extremes_vs_hs300_{code}.png`

## 图说明

把指定标的的回撤峰/谷以竖虚线标在双轴图上，看每次大幅回撤时大盘所处的位置：

- **右轴（黑线）**：标的复权收盘价。
- **左轴（淡蓝线）**：沪深300 收盘（背景对照）。
- **绿虚线** = 标的峰值（创新高当日）。
- **红虚线** = 标的谷底，顶部标红字回撤深度（当前未完成的回撤标"当前"）。
- **x 轴裁到标的与指数的共有区间**，两条线完整对齐。

适合回答：「某标的深跌时，大盘是同步跌还是背离？」例如 512890 当前回撤的谷值对应沪深300 仍在 5000 历史高位 → 背离，说明是标的自身的技术性回调而非系统性风险。

## 算法

- **累计最高** = 每日 `high`（盘中最高价）的 `cummax`，与 `drawdown.py` 同口径。
- **回撤** = 每日 `low` / 累计最高 − 1。
- **分段**：按"创新高"把历史切成若干段，每段一个 peak（段起点）和一个 trough（段内最低 low）。
- **筛选**：只画回撤深于 `--threshold`（默认 −10%）的峰谷，过滤小波动噪音。
- 末段（尚未创新高）标记为"进行中"。

## 怎么读

| 信号 | 含义 |
|---|---|
| 红虚线处沪深300 也低位 | 系统性熊市，标的随大盘跌 |
| 红虚线处沪深300 高位 | 标的自身独立回调，与大盘背离 |
| 多根红虚线密集 | 标的处于长期下行或反复磨底 |

## 用法

```bash
# 默认：512890 vs 沪深300，回撤 ≤ -10%
uv run python plots/drawdown_extremes_vs_hs300.py

# 换标的（基金/指数/股票均可，注意 --adjusted-dir 要对应）
uv run python plots/drawdown_extremes_vs_hs300.py --code 510880
uv run python plots/drawdown_extremes_vs_hs300.py --code 000300 \
  --adjusted-dir /mnt/dataset/index_quote_adjusted

# 调阈值（只标更深回撤）
uv run python plots/drawdown_extremes_vs_hs300.py --code 512890 --threshold -0.15

# 换对照指数（如中证500）
uv run python plots/drawdown_extremes_vs_hs300.py --code 512890 \
  --index-file /mnt/dataset/index_quote_history/000905.parquet --index-code 000905
```

| 参数 | 说明 | 默认 |
|------|------|------|
| `--code` | 标的代码（基金/指数/股票） | 512890 |
| `--adjusted-dir` | 含 `{code}.parquet` 的前复权行情目录 | /mnt/dataset/fund_quote_adjusted |
| `--index-file` | 对照指数 parquet | /mnt/dataset/index_quote_history/000300.parquet |
| `--index-code` | 对照指数代码（用于标题/图例） | 000300 |
| `--threshold` | 标记阈值（回撤深于该值才画虚线） | -0.10 |
| `--start-date` | 标的起始日期（cummax 从该日起累计） | None（从最早数据起） |
| `--output` | 输出 PNG 路径 | drawdown_extremes_vs_hs300_{code}.png |

## 数据源

- `{adjusted-dir}/{code}.parquet`：标的的前复权日行情（OHLC）。
- `index_quote_history/000300.parquet`（或 `--index-file`）：对照指数日收盘。
