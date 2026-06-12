# quant

基于 Polars 的命令行量化数据处理工具。

## 代码提交流程

提交代码必须通过 **issue + PR**，不能直接提交到主分支。

## 路径参数不得硬编码

所有文件夹路径和数据集路径必须作为参数传入函数/CLI，不能写死默认值。

- convert.py 中的函数：路径参数（`data_path`, `input_dir`, `output_dir` 等）必须无默认值
- cli.py 中的命令：路径参数必须无默认值，用户运行时必须提供
- source 等非路径参数可以保留默认值

## 数据集路径约定

- **只读原始数据**: `/mnt/readonly_dataset`（单数）
- **生成数据集**: `/mnt/dataset`（单数）

新增数据集时，input_dir 默认值使用 `/mnt/dataset/xxx`，data_path 默认值使用 `/mnt/readonly_dataset`，output_dir 默认值使用 `/mnt/dataset/xxx`。

## 项目结构

- `quant/convert.py` — 数据转换逻辑（核心）
- `quant/cli.py` — Typer CLI 入口
- `README.md` — 数据集文档（保持与代码同步）

## 记忆规范

所有需要跨会话记忆的内容统一保存在 `CLAUDE.md` 中，不使用 memory 目录。

## 命名规范

- 数据集列名（属性名）独立于函数名/CLI命令名，改数据集名称时不要改动列名
- 示例：`ma5`、`turnover_ma5`、`boll_mid20` 等属性名即使 CLI 命令从 `ma` 改为 `ta` 也不变
