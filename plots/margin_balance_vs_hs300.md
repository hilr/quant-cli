# 全市场融资余额 / 融券余额 vs 沪深300（全部历史，日频）

对应脚本：`plots/margin_balance_vs_hs300.py`
输出：`/mnt/dataset/margin_balance_vs_hs300.png`

## 图说明

- **左轴（蓝）**：全市场融资余额（margin_buy_total 合计），单位亿元。
- **第三轴（橙）**：全市场融券余额（short_sell_total 合计），单位亿元。融券规模比融资小两个数量级，故单独坐标轴。
- **右轴（黑）**：沪深300 日收盘。

## 怎么读

| 现象 | 含义 |
|------|------|
| 融资余额持续走高 | 杠杆资金加仓，情绪偏热 |
| 融资余额回落 | 杠杆资金偿还/离场 |
| 融券余额骤降 | 监管收紧限制做空（如 2024 转融通限制） |

## 数据源

- `/mnt/dataset/margin_trade_history/{code}.parquet`：个股融资融券历史，按日分别 `sum(margin_buy_total)` 与 `sum(short_sell_total)` 聚合。
- `index_quote_history/000300.parquet`：日收盘。

## 运行

```bash
uv run python plots/margin_balance_vs_hs300.py
# 可选：--data-path <path> --index-file <path> --output <path>
```
