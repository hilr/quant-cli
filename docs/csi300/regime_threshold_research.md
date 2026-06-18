# CSI300 Regime-aware Threshold 研究

> 起始时间：2026-06-18
> 状态：原型探索阶段（脚本在 /tmp/，产出数据在 /mnt/dataset/）

## 背景

CSI300（000300）触下轨买入策略（`close ≤ MA120 − 1.5σ`）60 日胜率仅 ~50%，最大浮亏 −30%；同策略在 512890（红利低波）上胜率 93%、最大浮亏 −5%。差异巨大。

**研究目标**：诊断 CSI300 上通道策略失效的原因，并探索改进方向。

## 研究路径

### Step 1：牛市段波动率特征（2024-09-24+）

详见 [CSI300 牛市段波动率特征](2024-09-24~至今.md)。

CSI300 自 2024-09-24 政策利好引爆后的牛市段（415 个交易日）：
- 日均收益 +0.099%，年化波动率 19.9%（低于全历史 25.0%）
- 偏度 **+0.28**（与全历史 −0.24 相反，正偏）
- 超峰 **+10.6**（厚尾，比全历史 +4.3 更厚）
- Jarque-Bera 强烈拒绝正态

→ 牛市里"3σ 事件"实际概率远高于理论 0.13%，单纯用 σ 定阈值会偏。

### Step 2：Zigzag 切分全历史

用 15% 阈值的 zigzag 算法切 CSI300（2002-2026），得 52 段：26 牛 + 26 熊。

**算法**：跟踪 running max/min，价格从当前极端值反向回撤 ≥ threshold 即确认 pivot。

- 数据：`/mnt/dataset/csi300_regime/zigzag_t15_segments.csv`
- 图：`/mnt/dataset/csi300_zigzag.png`
- 脚本：`/tmp/zigzag_csi300.py`

主要波段都对上了：2005-06~2007-05 大牛市（+410%）、2008 金融危机（−53%）、2014-2015 杠杆牛（+156%）、2024-2026 当前牛市（+39%）。

### Step 3：每段日收益率分布

按段切开计算 mean/std/skew/kurt。

- 数据：`/mnt/dataset/csi300_regime/zigzag_t15_segment_stats.csv`
- 脚本：`/tmp/zigzag_segment_stats.py`

**Bull vs Bear 段内日收益率分布**：

| 指标 | Bull (26 段) | Bear (25 段) |
|---|---|---|
| 平均段收益 | +54.0% | −26.6% |
| 日均收益 | +0.070% | −0.066% |
| 年化波动率 | 27.9% | 30.1% |
| **偏度** | **+0.18** | **−0.04** |
| **超峰** | **+2.05** | **+0.75** |

→ 牛市正偏厚峰（向上跳空多），熊市近零偏薄峰（跌得相对均匀）。**波动率几乎对称，差别在偏度方向**。

### Step 4：偏态分布的阈值理论

正态分布下 `±3σ = 0.13% 罕见事件`，因为 σ 和分位数有解析对应。一旦分布偏了/厚尾了，对应关系被破坏。三种调整方法：

| 方法 | 公式 | 用到的统计量 | 假设 |
|---|---|---|---|
| **normal** | `k = μ_z + σ_z · Φ⁻¹(α)` | 均值、方差 | 形状=正态 |
| **CF** (Cornish-Fisher) | `k = μ_z + σ_z · [z + (z²−1)/6·S + (z³−3z)/24·K − (2z³−5z)/36·S²]` | +偏度 S、峰度 K | 形状≈正态+修正 |
| **empirical** | `k = np.quantile(z_obs, α)` | 历史全样本 | 无形状假设 |

### Step 5：三种方法在 CSI300 全历史对比

z_obs = `(close − MA120) / σ120`，全样本 5810 个观察值：

```
mean=+0.095  std=1.446  skew=+0.076  kurt=−0.88（扁峰！）
```

**关键发现**：z_obs 不是厚尾而是**扁峰**（platykurtic）。MA 把长期趋势抹掉、再被同期 σ 归一化，结果被"压扁"。

α=1% 左尾阈值：

| 方法 | k | 命中数 | 命中率 |
|---|---|---|---|
| normal | −3.27 | 11 | 0.19% |
| CF | −2.89 | 27 | 0.46% |
| **empirical** | **−2.57** | **59** | **1.02%** |

三者命中关系：**normal ⊂ CF ⊂ empirical**。完全嵌套 —— normal/CF 漏掉的 32 个点都是 empirical 抓到的真 1% 事件。

→ 在 BB 通道上简单用 `−kσ` 会**系统性少买**，因为真实分布比正态"集中"。

- 图：`/mnt/dataset/threshold_compare_000300.png`
- 脚本：`/tmp/threshold_compare.py`

### Step 6：z_obs 按 regime 切开

把 z_obs 按 zigzag 切的 bull/bear 段分组重新算分布。

- 数据：`/mnt/dataset/csi300_regime/zobs_by_segment.csv`
- 脚本：`/tmp/zobs_by_regime.py`

**Bull vs Bear z_obs 分布差异巨大**：

| | Bull (n=3198) | Bear (n=2638) | 全历史 |
|---|---|---|---|
| 均值 | **+0.74** | **−0.70** | +0.09 |
| 标准差 | 1.32 | 1.19 | 1.45 |
| **偏度** | **−0.29** | **+0.43** | +0.08 |
| 峰度 | −0.59 | −0.37 | −0.88 |
| **α=1% 左尾** | **−2.25σ** | **−2.87σ** | −2.57σ |

**三个反直觉发现**：

1. **均值位移 1.44σ**：牛市价格常态在 MA 上方（中位 +0.89），熊市常态在下方（中位 −0.89）。同样的 `−1.5σ` 在牛市是"罕见回调"，在熊市是"日常水位"。
2. **偏度反向**：牛市负偏（左尾厚，**极端事件是突然暴跌**）；熊市正偏（右尾厚，**极端事件是报复性反弹**）。
3. **左尾阈值差 0.62σ**：bull 1% 事件 = −2.25σ，bear 1% 事件 = −2.87σ。全历史 −2.57σ 掩盖了差异。

### Step 7：per-regime 阈值回测

三种配置在 CSI300 上跑通道策略，看 60 日前瞻收益：

| 方法 | 信号数 | 胜率 | 60d 均值 | 平均浮亏 | 最差浮亏 |
|---|---|---|---|---|---|
| fixed k=1.5（当前默认） | 990 | 51.7% | +0.59% | −8.65% | **−37.2%** |
| fixed emp (k=−2.57) | 58 | 53.4% | −0.20% | −9.15% | −26.9% |
| **per_regime (bull 2.25 / bear 2.87)** | 55 | **70.9%** | **+6.41%** | **−5.91%** | **−21.6%** |

per_regime 在 bull/bear 段各自命中 ~1% 天数（bull 1.01%、bear 0.92%），校准目标达成。

- 脚本：`/tmp/regime_threshold_backtest.py`

## 核心结论

1. **z_obs 不是正态，是扁峰**：用 normal/CF 阈值都会欠触发。empirical 才能正确校准命中率。
2. **z_obs 分布在牛/熊里形态完全不同**：均值位移 1.4σ，偏度反向。固定 k 的"3σ 事件"在不同 regime 里意义完全不同。
3. **per-regime 阈值潜力巨大**：胜率 53% → **71%**（+18pp），60d 均值 −0.2% → **+6.4%**。
4. **问题不在阈值高低，在 regime 敏感性**：fixed_emp 比 fixed_k15 收益还低就证明了 —— 把"牛市卡太严"和"熊市卡太松"两个错误平均，等于没改善。

## 重要警告：hindsight 上界

Step 7 的 regime 标签来自 zigzag（用到未来数据确认转折）。实盘里**不可能实时知道**当前在牛还是熊，转折点往往滞后几周/几月才确认。

所以 71% 胜率是**天花板**，实盘一定更低。但即使 regime 识别有滞后/误差，应该还是显著优于固定 k。

## 数据产物清单

| 路径 | 内容 |
|---|---|
| `/mnt/dataset/csi300_regime/zigzag_t15_segments.csv` | 52 段牛熊区间（start_date/end_date/start_idx/end_idx/start_price/end_price/leg_return/leg_days/start_type/label） |
| `/mnt/dataset/csi300_regime/zigzag_t15_segment_stats.csv` | 每段日收益率分布（n/mean/std/ann_vol/skew/kurt/sharpe/max_day/min_day） |
| `/mnt/dataset/csi300_regime/zobs_by_segment.csv` | 每段 z_obs 分布（mean/std/skew/kurt/quantiles） |
| `/mnt/dataset/csi300_zigzag.png` | zigzag 可视化 |
| `/mnt/dataset/threshold_compare_000300.png` | 三种阈值方法对比图 |

## 待办

- [ ] **B（推荐）**：滚动 252 天算 z_obs 的 mean/std/skew/kurt，动态调阈值。**不依赖 regime 识别**（避免因果错误），完全可用实盘。先看分布形态自适应能撑多远。
- [ ] **C**：因果版 regime 识别（MA60 斜率 + 回撤阈值 / HMM）+ per-regime 阈值。预期收益：接近 Step 7 的天花板；预期成本：实现复杂、需评估 regime 识别准确率。
- [ ] 把阈值方法接入 `plots/channel_entry_signals.py`，加 `--threshold-mode normal|cf|empirical|regime` 开关正式化。

## 相关文档

- [CSI300 牛市段波动率特征（2024-09-24+）](2024-09-24~至今.md)
- [算法调研笔记 - 布林带通道策略优化探索](../algo_notes.md)
