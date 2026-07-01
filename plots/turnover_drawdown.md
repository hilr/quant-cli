# turnover_drawdown — 沪深300 成交额回撤水下曲线 + 沪深300 收盘价

对应脚本：`plots/turnover_drawdown.py`
输出：`/mnt/dataset/turnover_drawdown_{code}.png`（默认 `{code}=000300`）

## 图说明

上下两栏，共享 x 轴：

- **上栏**：标的收盘价（蓝实线）+ 累计最高价（灰虚线 `cummax close`）。
- **下栏**：成交额回撤水下曲线（红色面积 + 实线，单位 %），0 线为历史峰值。
  - 深于 −50% 的谷值会标日期 + 深度；最深那个加 `(max)`。

适合回答：「成交额的枯竭（量缩）是否预示价格拐点？」例如 2015 牛市顶峰成交额
爆炸，随后股灾中成交额缩水 −95%（2016-01-07 见底），对应价格也跌入熊市。

## 算法

```
peak_turnover = cummax(turnover)       # 截至当日为止的历史最高成交额
dd            = turnover / peak_turnover - 1
```

- `turnover > 0` 才参与（剔除无成交的早期或停牌日）。
- **分段**：按"创新高"把历史切成若干段，每段取一个最深谷值。
- **筛选**：只标深于 `ANNOT_THRESHOLD`（默认 −50%）的谷，过滤小波动噪音。
- 末段（尚未创新高）的谷也会被标出。

## 怎么读

| 信号 | 含义 |
|---|---|
| 下栏深谷处上栏也低位 | 量价共振底，常见于熊市末段 |
| 下栏深谷处上栏仍高位 | 量在缩、价未跌 → 警示（流动性衰竭先行） |
| 下栏长期贴近 0 | 成交活跃度持续创新高（牛市） |
| 上栏创新高但下栏不创新高 | 量价背离，上涨缺量的支撑不足 |

## 用法

```bash
# 默认：沪深300
uv run python plots/turnover_drawdown.py

# 换指数（同样要带 turnover 列）
uv run python plots/turnover_drawdown.py --code 000905

# 用股票行情目录（需含 turnover 列）
uv run python plots/turnover_drawdown.py --code 600519 \
  --adjusted-dir /mnt/dataset/stock_quote_history

# 重置 cummax 起点（跳过早期成交稀薄期）
uv run python plots/turnover_drawdown.py --code 000300 --start-date 2010-01-01
```

| 参数 | 说明 | 默认 |
|------|------|------|
| `--code` | 指数/基金/股票代码 | 000300 |
| `--adjusted-dir` | 含 `{code}.parquet 的行情目录（必须含 turnover 列） | /mnt/dataset/index_quote_history |
| `--start-date` | cummax 起算日（YYYY-MM-DD） | None（从最早有成交日起） |
| `--output` | 输出 PNG 路径 | turnover_drawdown_{code}.png |

## 数据源

- `{adjusted-dir}/{code}.parquet`：必须含 `date`、`close`、`turnover` 列。
- 默认 `/mnt/dataset/index_quote_history/000300.parquet`（沪深300 日行情，由
  `uv run python -m quant.cli index-quote-history` 生成）。

## 历史结果（沪深300，2005-01-04 ~ 2026-06-30）

- **最大成交额回撤 −95.04%**（2016-01-07）：2015 牛市顶峰成交额爆炸后的枯竭谷。
- 其它深谷：2008-09-09（−92.64%，金融危机）、2011-12-12（−92.09%）、
  2025-05-28（−85.62%）。
- 注意 2005 年初的 −60% ~ −85% 谷值源自 HS300 刚上市时的稀薄成交，
  若想跳过这段可用 `--start-date 2006-01-01`。
