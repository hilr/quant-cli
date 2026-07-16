# fund_pair_compare — 两只标的双轴价格 + 滚动相关系数柱状

`fund_pair_compare.py` 的完整文档。任意两只基金/ETF/指数（前复权口径）的对比视图。

## 用法

```bash
# 默认：588170 科创半导 vs 512800 银行ETF，过去 60 交易日
uv run python plots/fund_pair_compare.py

# 自定义两只标的 + 窗口
uv run python plots/fund_pair_compare.py --code-a 588170 --code-b 159525 \
  --window 120 --corr-window 10 \
  --output /mnt/dataset/fund_pair_588170_159525.png
```

| 参数 | 说明 | 默认 |
|------|------|------|
| `--input-dir` | 前复权行情目录 | /mnt/dataset/fund_quote_adjusted |
| `--code-a` | 标的 A 代码 | 588170 |
| `--code-b` | 标的 B 代码 | 512800 |
| `--window` | 回看交易日数 | 60 |
| `--corr-window` | 滚动相关窗口（交易日） | 5 |
| `--output` | 输出 PNG 路径 | /mnt/dataset/fund_pair_compare.png |

**输出：** 双栏 PNG（上=两标的前复权收盘价双轴；下=滚动相关系数柱状，负红/正蓝，全程相关系数虚线）。

## 算法

- 上面板：两只标的各自真实前复权收盘价，**不归一化**，各占一个 y 轴——价格量级不同时双轴比归一化更能保留水位信息
- 下面板：日收益率 `r[t]=close[t]/close[t-1]-1` 的 N 日滚动 Pearson，向量化展开 `cov/(σa·σb)`
- 相关用**日收益率**而非价格：价格带漂移会虚高相关，收益相关才衡量「涨跌是否同步」
- 全程相关系数 = 窗口内全部日收益的 Pearson，作为柱状图的参考基准虚线

## 怎么读

| 信号 | 含义 |
|---|---|
| 上图两线反向 | 涨跌节奏相反，风格/板块背离 |
| 下图红柱深且持续 | 负相关走强，可作为对冲组合 |
| 虚线 vs 柱体 | 柱体持续低于虚线 = 近期负相关比历史更深 |

## 数据源

- `fund_quote_adjusted/{code}.parquet`：前复权日行情（含 `date`/`close`/`name`）。

## 复现

```bash
uv run python plots/fund_pair_compare.py --code-a 588170 --code-b 512800 \
  --window 60 --corr-window 5
```
