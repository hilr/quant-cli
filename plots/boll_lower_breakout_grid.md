# boll_lower_breakout_grid — Boll 下轨破位 × 当日深度/N 日位置 双维网格

对应脚本：`plots/boll_lower_breakout_grid.py`
输出：`/mnt/dataset/boll_lower_grid_{code}_h{horizon}_w{pct_window}.png` + 控制台详细统计

## 图说明

筛选 close < boll_lower（破下轨）的所有交易日，按两个当日状态维度做网格分桶：

- **X 轴（pct_win）**：当日 close 在过去 `--pct-window`（默认 250 ≈ 1 年）日 close
  范围内的位置
  `(close − rolling_min) / (rolling_max − rolling_min)`。
  0 = N 日新低、1 = N 日新高。
- **Y 轴（penetration）**：当日破位深度
  `(lower − close) / lower`，close 跌破下轨的幅度占下轨的百分比。

每格统计**未来 `--horizon` 日（默认 5）内**的极值收益分布：

- **max_return**：`max(high[t+1..t+N]) / close[t] − 1`（持有期内最大潜在涨幅）
- **min_return**：`min(low[t+1..t+N]) / close[t] − 1`（持有期内最大潜在跌幅）

⚠️ **不是到期收益**：是路径极值，反映"挂单止盈能拿到的最好价"与
"持有期间承受的最深回撤"。

## 算法

- Bollinger 通道：`ma = close.rolling_mean(boll_window)`，
  `sigma = close.rolling_std(boll_window)`（Polars 默认 ddof=1，样本标准差），
  `upper = ma + k·sigma`、`lower = ma − k·sigma`。
- penetration：`max(0, (lower − close) / lower)`，未破位记 0；本图样本已 filter
  close<lower，所以恒 > 0。
- max_return / min_return：对每个 offset 1..horizon 计算
  `high[t+off]/close[t]−1` 或 `low[t+off]/close[t]−1`，再取 max/min。
- **分桶方式**：rank-based 等样本量切（不是 quantile），避免 pct_win 在 0 处大量
  打结导致 quantile 切点塌缩。每格约 N/n² 个样本。
- **每个格子的统计字段**：N（样本数）、μ（均值）、M（中位数）、
  [P1, P5, P95, P99]（尾部分位）。
- **热力图配色**：max_return 用 RdYlGn（绿=高），min_return 用 RdYlGn_r（绿=浅跌）。

## 怎么读

| 看点 | 含义 |
|------|------|
| 整个 r2 行 max_return μ 显著高于其他行 | 深破位（penetration 大）→ 反弹潜力强 |
| c0 列（年内新低）max_return 分布右偏（P99 很高） | 极端超卖 → 少数案例会出现爆发反弹 |
| min_return P1 在 −10% 以下 | 同格样本里最差 1% 会再深跌 10%+，反弹路上剧烈洗盘 |
| max_return P1 ≥ 0 | 历史同类案例 99% 都至少见到一点反弹高点 |
| 当前事件落在哪格 | 用于"今天 vs 历史"的定位判读 |

## 用法

```bash
# 默认：沪深300 / Boll 20±2σ / 250 日位置 / 未来 5 日极值 / 3×3 网格
uv run python plots/boll_lower_breakout_grid.py

# 换位置窗口（如 120 日）
uv run python plots/boll_lower_breakout_grid.py --pct-window 120

# 换未来窗口（如 10 日）
uv run python plots/boll_lower_breakout_grid.py --horizon 10

# 换 Bollinger 参数
uv run python plots/boll_lower_breakout_grid.py --boll-window 30 --k 1.5

# 换标的
uv run python plots/boll_lower_breakout_grid.py --code 000905

# 4×4 网格（每格样本更少，更细分）
uv run python plots/boll_lower_breakout_grid.py --n-buckets 4
```

| 参数 | 说明 | 默认 |
|------|------|------|
| `--code` | 标的代码 | 000300 |
| `--adjusted-dir` | 含 `{code}.parquet` 的行情目录 | /mnt/dataset/index_quote_history |
| `--boll-window` | Bollinger 通道窗口（日） | 20 |
| `--k` | σ 倍数 | 2.0 |
| `--pct-window` | 位置窗口（日） | 250（≈ 1 年） |
| `--horizon` | 未来极值收益窗口（日） | 5 |
| `--n-buckets` | 每维分桶数（n×n 网格） | 3 |
| `--output` | 输出 PNG 路径 | boll_lower_grid_{code}_h{horizon}_w{pct_window}.png |

## 数据源

- `{adjusted-dir}/{code}.parquet`：需含 `date, high, low, close` 四列。

## 参考结果（沪深300，Boll 20±2σ，250 日位置，未来 5 日，3×3，截至 2026-07-17）

破下轨样本 N=259。每格字段为 **N / max μ·M·[P1,P5,P95,P99] / min μ·M·[P1,P5,P95,P99]**：

| | c0: pct_win 0-8.6%（年内新低） | c1: pct_win 9-45%（年内偏低） | c2: pct_win 45-85%（年内中高） |
|---|---|---|---|
| **r2 深破位 0.92-7.82%** | N=29<br>max μ+3.18%/M+1.65% [−0.7%, −0.5%, +12.8%, +18.6%]<br>min μ−4.59%/M−3.94% [−12.1%, −11.4%, −0.4%, +2.1%] | N=26<br>max μ+3.25%/M+2.62% [−2.5%, +0.3%, +10.3%, +11.6%]<br>min μ−3.96%/M−2.90% [−15.8%, −9.4%, 0%, +0.1%] | N=32<br>max μ+3.13%/M+2.15% [+0.1%, +0.4%, +7.8%, +8.6%]<br>min μ−3.12%/M−2.21% [−13.4%, −11.0%, 0%, +0.2%] |
| **r1 中破位 0.30-0.88%** | N=29<br>max μ+2.65%/M+1.68%<br>min μ−2.50%/M−1.77% | N=22<br>max μ+1.39%/M+1.09%<br>min μ−1.87%/M−1.03% | N=35<br>max μ+2.02%/M+1.69%<br>min μ−3.18%/M−1.86% |
| **r0 浅破位 0-0.29%** | N=28<br>max μ+2.40%/M+1.28%<br>min μ−2.44%/M−2.19% | N=38<br>max μ+1.31%/M+1.10%<br>min μ−2.18%/M−1.40% | N=20<br>max μ+1.11%/M+1.34%<br>min μ−3.42%/M−2.75% |

**全局基线**：max μ+2.29%/M+1.59% [P1−1.6%, P5−0.4%, P95+7.1%, P99+14.3%]
　　　　　　min μ−3.01%/M−1.95% [P1−13.2%, P5−9.9%, P95+0.1%, P99+0.5%]

### 几个关键读数

1. **r2 行（深破位）整体反弹潜力最强**：max μ 在 c0/c1/c2 都达 +3.13~+3.25%，
   P95 都在 +7.8~+12.8%——深破位是有效的反弹信号。
2. **r2 行的 min_return 也最差**：μ −3.12~−4.59%，P1 −12~−16%——
   典型"高反弹 + 高波动"格局，反弹路上常有深探。
3. **c0 列 max_return 右偏显著**：P99 都在 +11~+19%（少数案例爆发反弹），
   与"极端超卖后的 V 型反转"现象一致。
4. **当前位置（2026-07-17）落在 [r2, c2]**：penetration 1.419%（深破位）、
   pct250 50.3%（年内中位）。历史 32 个同类案例的 max_return P1 = +0.1%——
   意味着 99% 的同类情况未来 5 日内都会出现反弹高点。

## 口径提醒

- **滚动重叠窗口**（每个破位日都开一个）：相邻事件高度自相关，做"经验概率"
  参考可以，做严格统计推断需对有效样本数打折。
- **P1/P99 在小样本格（N<30）下统计意义弱**：r0c2 N=20 的 P1=−2.1% 仅供参考。
- **极值收益用 high/low 不是 close**：反映日内可达的最好/最坏价，不是收盘价。
  实际可成交价取决于挂单策略与流动性。
