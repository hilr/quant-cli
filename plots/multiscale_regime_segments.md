# multiscale_regime_segments — 多尺度牛熊分段金标准（沪深300）

`multiscale_regime_segments.py` 的完整文档与结果快照。结果随数据更新，由脚本控制台输出誊写。

## 用法

```bash
# 默认：沪深300，ZigZag 25%，三尺度分段，输出 CSV + PNG
uv run python plots/multiscale_regime_segments.py

# 改阈值/指数
uv run python plots/multiscale_regime_segments.py --pct 0.30 --code 000905

# 自定义输出
uv run python plots/multiscale_regime_segments.py \
    --output-dir /mnt/dataset/csi300_regime_segments \
    --output /mnt/dataset/csi300_regime_segments/multiscale_segments_000300.png
```

| 参数 | 说明 | 默认 |
|------|------|------|
| `--index-dir` | 指数 parquet 父目录 | /mnt/dataset/index_quote_history |
| `--code` | 指数代码 | 000300 |
| `--pct` | ZigZag 反转阈值 | 0.25 |
| `--output-dir` | 分段 CSV 输出目录 | /mnt/dataset/csi300_regime_segments |
| `--output` | 三联 PNG 路径 | output-dir/multiscale_segments_{code}.png |

**输出：**
- 控制台三尺度分段明细表（大≥120 / 中≥60 / 小≥30 交易日）
- `{large,medium,small}_segments.csv`：各尺度分段表（seg/dir/size/trade_days/start_date/end_date/high/low/return_pct/tail）
- `multiscale_segments_{code}.png`：三联图（每行一尺度，绿=bull 红=bear，段内标 #/dir/size/td/ret）

## 方法

### 1. 原始枢轴段

`pivot_eval.zigzag_pivots`（pct 反转阈值）在 day high/low 上标记 H/L 枢轴（回顾式，最后一个未确认极值不计）。相邻枢轴配段：**L→H = bull（上涨）**、**H→L = bear（下跌）**。最后一段（最后枢轴→最后一日）标 `tail=true` 未确认。

### 2. 多尺度最小周期要求

三档（交易日）：**大 ≥120 / 中 ≥60 / 小 ≥30**。低于阈值的短段需要合并。

### 3. 熊市豁免合并规则（核心）

**熊市无论多短都保留**——短熊是真实风险事件，要标出来。只过滤「短牛」：

> 当一个 `td < min_days` 的 **bull** 段夹在两个 **bear** 之间，且**第二腿 bear 创新低**（`nxt.lo < prev.lo`，说明中间那个 bull 是死猫跳而非新牛市起点），三段合一为 bear。
>
> 短熊（夹在两 bull 之间）**不触发合并**，作为独立熊段保留。

迭代合并到稳定。对称地不处理"短熊 + 两 bull 创新高 → 合并为 bull"——熊市豁免。

### 设计动机：2015 股灾

固定百分比 ZigZag 的固有盲区：30% 阈值下，2015-08-26 低点（2952）后的死猫跳反弹 **+33.0%** 刚好过线，骗算法以为熊结束；随后熔断第二腿 −27.7% 没过 30%，没形成新 L，整段 2015-06→2018-01 被误判成一轮 bull。真实周期低点是 **2016-02-29（2821）**，比第一腿还低 131 点。

25% 阈值能把熔断第二腿（−25.6%）选出来；熊市豁免合并再把"下跌-死猫跳-第二腿创新低"还原成一段大熊。结果：

| 尺度 | 2015 区域 |
|------|-----------|
| 大（≥120td） | 一段 bear（2015-06-09→2016-02-29，175td，−45.9%） |
| 中（≥60td） | bear(55td) → bull(78td, +27.8%) → bear(42td)，反弹作为中级牛市浮出 |
| 小（≥30td） | 同中尺度，更细的波动也保留 |

## 结果明细（截至 2026-07-08，000300，ZigZag 25%）

### 大尺度（≥120td）→ 12 段

| # | dir | td | start → end | ret |
|---|-----|----|-------------|-----|
| 1 | bear | 818 | 2002-01-04 → 2005-06-06 | −36.3% |
| 2 | bull | 575 | 2005-06-06 → 2007-10-17 | +594.2% |
| 3 | bear | 257 | 2007-10-17 → 2008-11-04 | −72.1% |
| 4 | bull | 184 | 2008-11-04 → 2009-08-04 | +132.6% |
| 5 | bear | 940 | 2009-08-04 → 2013-06-25 | −42.8% |
| 6 | bull | 478 | 2013-06-25 → 2015-06-09 | +145.6% |
| 7 | bear | 175 | 2015-06-09 → 2016-02-29 | −45.9% |
| 8 | bull | 471 | 2016-02-29 → 2018-01-26 | +52.3% |
| 9 | bear | 227 | 2018-01-26 → 2019-01-04 | −30.7% |
| 10 | bull | 513 | 2019-01-04 → 2021-02-18 | +90.0% |
| 11 | bear | 722 | 2021-02-18 → 2024-02-02 | −44.9% |
| 12⚡ | bull | 584 | 2024-02-02 → 2026-07-08 | +49.6% |

合并 6 次短牛（死猫跳）：2008 金融危机两次反抽、2009-2013 震荡期三次反弹、2015 股灾中的死猫跳。

### 中尺度（≥60td）→ 16 段

大尺度的 #5（940td 长熊）拆成 bear(221) + bull(86, 2010 反弹) + bear(633)；大尺度的 #7（2015 整段熊）拆成 bear(55) + bull(78, 死猫跳) + bear(42)。

### 小尺度（≥30td）→ 20 段

进一步保留 2009-2013 区间的次级波动（#5 波动 20td、#6 小 54td、#10 小 45td 等）。

## 与 zigzag_bull_bear_cycle 的区别

| | zigzag_bull_bear_cycle | multiscale_regime_segments |
|---|---|---|
| 阈值 | 30%（固定） | 25% |
| 合并 | 无（原始枢轴段） | 熊市豁免 + 死猫跳吸收 |
| 2015 股灾 | 误切成 bear(55td)+bull（死猫跳当牛市起点） | 大尺度一段熊 / 中尺度三段 |
| 尺度 | 单一 | 大/中/小 三档层级 |
| 用途 | 描述性周期统计 | 分层 regime 金标准标签 |

## 复现

```bash
uv run python plots/multiscale_regime_segments.py
```
