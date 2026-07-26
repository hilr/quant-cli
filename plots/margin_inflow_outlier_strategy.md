# 融资净买入异常值择时策略 + 网格搜索

对应脚本：`plots/margin_inflow_outlier_strategy.py`
输出：`/mnt/dataset/margin_inflow_outlier_strategy.png`

## 策略逻辑

当某日全市场融资净流入出现统计异常值时择时：

```
inflow[t] = balance[t] − balance[t−1]                     # 日净流入
mu[t]     = mean(inflow[t−N .. t−1])                       # 过去 N 日均值（排除当日）
sigma[t]  = std(inflow[t−N .. t−1])                        # 过去 N 日标准差（排除当日）

买入信号[t] = inflow[t] > 0 且 inflow[t] > mu[t] + k·sigma[t]
卖出信号[t] = inflow[t] < 0 且 inflow[t] < mu[t] − k·sigma[t]
```

- **仓位**：买入后持有标的指数，直到卖出信号出现才平仓转为空仓（长/空仓切换）。
- **避免前视**：融资数据盘后公布，信号 T 日收盘后可得、**T+1 日**才生效。
- **成本**：单边万分之五（买卖各扣一次），可通过 `--cost-rate` 调整。

## 网格搜索

两个参数做网格，以**年化夏普比率**找最优：

| 参数 | 含义 | 默认网格 |
|------|------|---------|
| `window` (N) | 回看窗口（交易日） | 10, 15, 20, 25, 30, 40, 60 |
| `k` | 标准差倍数 | 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0 |

共 49 组合。通过 `--windows` / `--k-values` 自定义。

## 图说明（三面板）

1. **顶部 NAV**：最优策略 vs 买入持有，绿↑买入、红↓卖出标记。
2. **中部净流入**：日融资净流入柱状（红负/蓝正）+ 买卖信号点。
3. **底部热力图**：夏普比率在 (N × k) 网格上的分布，黑框标最优格。

## 数据源

- `/mnt/dataset/margin_trade_history/{code}.parquet`：个股融资融券历史，按日 `sum(margin_buy_total)` 聚合全市场余额，再差分得日净流入。
- `--index-file`：标的指数行情（默认 `index_quote_history/000300.parquet` 沪深300）。

## 运行

```bash
# 默认沪深300
uv run python plots/margin_inflow_outlier_strategy.py

# 换标的（如中证500）
uv run python plots/margin_inflow_outlier_strategy.py \
  --index-file /mnt/dataset/index_quote_history/000905.parquet \
  --output /mnt/dataset/margin_inflow_outlier_strategy_000905.png

# 自定义网格 / 成本
uv run python plots/margin_inflow_outlier_strategy.py \
  --windows 20,30,60 --k-values 2.0,3.0,4.0 --cost-rate 0.0003
```

## 注意

- 网格搜索在历史样本上寻优，存在过拟合风险；优选参数应落在稳健区（邻近格夏普接近）而非孤立高点。
- 极低 k（如 1.0）会产生大量交易，虽有成本扣除但换手极高，需结合 `n_trades` 判断稳健性。
