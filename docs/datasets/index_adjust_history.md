[← 数据集索引](../../README.md#数据集索引)

# index_adjust_history — 指数成份调整历史

| 项 | 内容 |
|---|------|
| 命令 | `uv run python -m quant.cli index-adjust-history <data_path> <output_dir>` |
| 输入 | `{data_path}/csindex/index_adjust_raw/*/*.xlsx`（调入/调出 sheet）<br>`{data_path}/csindex/csindex_data/csindex_news/*/{*.xlsx,*.pdf}`（公告附件） |
| 输出 | `{output_dir}/index_adjust_history/{year}.parquet`（按生效年分文件，便于追加） |
| 覆盖 | 2015 ~ 2026（12 年），沪深300/中证500 每年 6/12 月定期调整 + 临时调整 |
| 产出 | ~38.5 万条调整事件 |

**字段：**
| 字段 | 含义 |
|------|------|
| index_code | 指数代码（000300 沪深300、000905 中证500、000852 中证1000…） |
| index_name | 指数简称 |
| announce_date | 公告日（csindex_news 取 meta.json；index_adjust_raw 取文件名日） |
| effective_date | 生效日（PDF/xlsx 从正文「于 YYYY年MM月DD日生效」提取；index_adjust_raw 无正文，= 公告日近似） |
| constituent_code | 成份券代码（6 位） |
| constituent_name | 成份券名称 |
| direction | `in` 调入 / `out` 调出 |
| source | `adjust_raw` / `news_xlsx` / `news_pdf` |

**合并与去重：**

三个来源合并，**xlsx 优先于 PDF**（结构化更可靠），PDF 仅补 xlsx 未覆盖的 2023-2026 定期调整：

| source | 来源 | 覆盖 | 格式 |
|---|---|---|---|
| `adjust_raw` | index_adjust_raw | 2015-12 ~ 2022-12 | xlsx 调入/调出 sheet |
| `news_xlsx` | csindex_news xlsx 附件 | 2020 ~ 2025 | xlsx（多种结构） |
| `news_pdf` | csindex_news PDF 附件 | 2023 ~ 2026 定期 | PDF「调出\|调入」双列对 |

去重键 `(index_code, effective_date 年月, constituent_code, direction)`，**source 优先级 `news_xlsx > adjust_raw > news_pdf`**。2020-2022 重叠期同一调整只保留一行。

**PDF 解析：** pdfplumber 提表格 → 跳表头行 → 数据行左列=调出、右列=调入 → 按正文「XX指数更换N只」的顺序切分 → 指数名经子串模糊匹配到代码（应对「其中沪深300」等前缀）。

**已知边界：**
- index_adjust_raw 无正文，effective_date 用公告日近似（定期调整实际生效在 6/12 月中，差几天）
- 中证A50/A100/A500 等 2023+ 新指数，若历史 xlsx 未出现过则代码可能为空（名称保留）
