# turnover_drawdown — 沪深300 成交额回撤水下曲线 + 沪深300 收盘价

对应脚本：`plots/turnover_drawdown.py`
输出：`/mnt/dataset/turnover_drawdown_{code}.png`（默认 `{code}=000300`）

## 图说明

上下两栏，共享 x 轴：

- **上栏**：标的收盘价（蓝实线）+ 累计最高价（灰虚线 `cummax close`）。
- **下栏**：成交额回撤水下曲线（红色面积 + 实线，单位 %），0 线为近期峰值。
  - 深于阈值（默认 −80%）的谷值会标日期 + 深度；最深那个加 `(max)`。

适合回答：「近半年成交额的枯竭（量缩）是否预示价格拐点？」例如 2015 牛市顶峰成交额
爆炸，120 日滚动峰值长期被压在高位，随后股灾中每日成交额相对该峰值缩水至 −92%
（2016-01-07 见底），对应价格也跌入熊市。

## 算法

```
peak_turnover = rolling_max(turnover, window=N)   # 过去 N 个交易日的最高成交额
dd            = turnover / peak_turnover - 1
```

- `turnover > 0` 才参与（剔除无成交的早期或停牌日）。
- 滚动窗口默认 **120 个交易日（≈半年）**，可用 `--window` 改。
- **分段**：滚动峰值非单调，按"连续低于阈值"分段，每段取最深谷值。
- **筛选**：只标深于 `--threshold`（默认 −80%）的谷，过滤日常噪音。
  - 滚动窗口下 −50% 太常见（每隔几周一次），−80% 才是流动性枯竭级别的事件。

## 为什么用 rolling max 而非 cummax？

- **cummax**：被历史天量长期压住，2015 牛市顶峰后再也回不到 −0%，图几乎永远是"水下"。
- **rolling 120d**：只看近半年，能突出中期成交萎缩 → 量缩信号更敏锐，
  且当窗口滑过老峰值后曲线自然回到 0，便于识别新一轮枯竭。

## 怎么读

| 信号 | 含义 |
|---|---|
| 下栏深谷处上栏也低位 | 量价共振底，常见于熊市末段 |
| 下栏深谷处上栏仍高位 | 量在缩、价未跌 → 警示（流动性衰竭先行） |
| 下栏长期贴近 0 | 近半年成交活跃度持续创新高 |
| 上栏创新高但下栏不创新高 | 量价背离，上涨缺量的支撑不足 |

## 用法

```bash
# 默认：沪深300，120 日滚动峰值，−80% 阈值
uv run python plots/turnover_drawdown.py

# 换指数（同样要带 turnover 列）
uv run python plots/turnover_drawdown.py --code 000905

# 改窗口（如 60 日 ≈ 季度）
uv run python plots/turnover_drawdown.py --window 60

# 改阈值（如只标更深的 −85%）
uv run python plots/turnover_drawdown.py --threshold -0.85

# 用股票行情目录（需含 turnover 列）
uv run python plots/turnover_drawdown.py --code 600519 \
  --adjusted-dir /mnt/dataset/stock_quote_history

# 重置起点（跳过早期成交稀薄期）
uv run python plots/turnover_drawdown.py --code 000300 --start-date 2010-01-01
```

| 参数 | 说明 | 默认 |
|------|------|------|
| `--code` | 指数/基金/股票代码 | 000300 |
| `--adjusted-dir` | 含 `{code}.parquet` 的行情目录（必须含 turnover 列） | /mnt/dataset/index_quote_history |
| `--window` | 滚动最高成交额窗口（交易日） | 120 |
| `--threshold` | 标注阈值（回撤深于该值才标） | -0.80 |
| `--start-date` | rolling max 起算日（YYYY-MM-DD） | None（从最早有成交日起） |
| `--output` | 输出 PNG 路径 | turnover_drawdown_{code}.png |

## 数据源

- `{adjusted-dir}/{code}.parquet`：必须含 `date`、`close`、`turnover` 列。
- 默认 `/mnt/dataset/index_quote_history/000300.parquet`（沪深300 日行情，由
  `uv run python -m quant.cli index-quote-history` 生成）。

## 历史结果（沪深300，120 日窗口，2005-01-04 ~ 2026-06-30）

- **最大成交额回撤 −92.11%**（2016-01-07）：2015 牛市顶峰成交额爆炸后的枯竭谷。
- 其它 −85% 以下的深谷：
  - 2008-09-09（−89.64%，金融危机）
  - 2015-09-28（−90.73%，股灾 1.0 后流动性枯竭）
  - 2016-04-26（−86.09%，股灾 2.0 后）
  - 2006-08-09（−85.30%，早期成交稀薄期，可用 `--start-date 2007-01-01` 跳过）
- 2025-03-28 出现 −81.12% 谷值，为近一年的流动性枯竭信号。
