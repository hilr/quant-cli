# CSI300 Regime-aware Threshold 研究 — 原型脚本

研究目标：诊断 CSI300 上通道策略（`close ≤ MA120 − 1.5σ`）失效原因，并探索改进方向。

**完整研究日志**：[`docs/csi300/regime_threshold_research.md`](../../docs/csi300/regime_threshold_research.md)

## 脚本顺序

| # | 脚本 | 作用 | 输出 |
|---|---|---|---|
| 01 | `zigzag_segment.py` | 15% 阈值 zigzag 切分 CSI300 牛熊段 | `/mnt/dataset/csi300_regime/zigzag_t15_segments.csv` + 图 |
| 02 | `segment_return_stats.py` | 每段日收益率分布（mean/std/skew/kurt） | `/mnt/dataset/csi300_regime/zigzag_t15_segment_stats.csv` |
| 03 | `zobs_by_regime.py` | 每段 z_obs 分布（按 regime 切开） | `/mnt/dataset/csi300_regime/zobs_by_segment.csv` |
| 04 | `threshold_compare.py` | normal / CF / empirical 三种阈值方法对比 | `/mnt/dataset/threshold_compare_000300.png` |
| 05 | `regime_threshold_backtest.py` | per-regime 阈值回测（hindsight 上界） | 控制台输出对比表 |

## 运行

```bash
# 顺序执行（每个脚本依赖前一个的输出）
uv run python research/csi300_regime_threshold/01_zigzag_segment.py
uv run python research/csi300_regime_threshold/02_segment_return_stats.py
uv run python research/csi300_regime_threshold/03_zobs_by_regime.py
uv run python research/csi300_regime_threshold/04_threshold_compare.py
uv run python research/csi300_regime_threshold/05_regime_threshold_backtest.py
```

## 关键参数

- `--threshold` (01): zigzag 反转阈值，默认 0.15（15%）
- `--window` (01, 04): MA/σ 滚动窗口，默认 120
- `--alpha` (04): 左尾目标概率，默认 0.01

## 状态

**原型阶段**。脚本里路径直接写死 `/mnt/dataset/...`（按 CLAUDE.md 规则，仅 `quant/convert.py` 和 `quant/cli.py` 要求路径参数化，研究脚本例外）。

后续若接入正式策略（`plots/channel_entry_signals.py` 加 `--threshold-mode` 开关），核心算法从这里的 04/05 提取。
