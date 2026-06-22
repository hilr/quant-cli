"""行业相关图表的共享数据加载与常量。

供 industry_spectrum.py / industry_turnover_stack.py 复用：
- 行业分类表（中证 1-4 级）：/mnt/readonly_dataset/csindex/industry/{date}.xlsx
- 当日全 A 行情：/mnt/readonly_dataset/{finance_sina,eastmoney}/stock_quote/{date}.csv
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import polars as pl
from matplotlib.colors import LinearSegmentedColormap

INDUSTRY_DIR_NAME = "csindex/industry"
# 行情目录候选：finance_sina 是实时源，eastmoney 是历史归档（2025-11 后停更）。靠前的优先。
QUOTE_DIR_CANDIDATES = ["finance_sina/stock_quote", "eastmoney/stock_quote"]

MIN_FULL_ROWS = 4000
COLOR_LIMIT = 0.05

CJK_FONTS = [
    "Noto Sans SC", "WenQuanYi Zen Hei", "Source Han Sans SC",
    "Noto Sans CJK SC", "SimHei", "Microsoft YaHei", "Arial Unicode MS",
]

RED_GREEN_CMAP = LinearSegmentedColormap.from_list(
    "a_share_rg",
    ["#13795b", "#5fa583", "#c8e0d4", "#f5f5f5", "#e6c5c1", "#cf6b60", "#c0392b"],
)

OLE_MAGIC = b"\xd0\xcf\x11\xe0"


def _read_sheet(path: Path) -> list[list]:
    """用 calamine 读 xls/xlsx，处理 OLE .xls 伪装成 .xlsx 的情况。"""
    from python_calamine import CalamineWorkbook

    with open(path, "rb") as f:
        magic = f.read(4)
    if magic == OLE_MAGIC and path.suffix == ".xlsx":
        with tempfile.NamedTemporaryFile(suffix=".xls", delete=False) as tmp:
            shutil.copyfileobj(open(path, "rb"), tmp)
            tmp_path = tmp.name
        try:
            wb = CalamineWorkbook.from_path(tmp_path)
        finally:
            Path(tmp_path).unlink(missing_ok=True)
    else:
        wb = CalamineWorkbook.from_path(str(path))
    ws = wb.get_sheet_by_name(wb.sheet_names[0])
    return ws.to_python()


def load_industry(data_path: Path, level: int) -> pl.DataFrame:
    """最新一份行业分类表 → [code, industry]。level=1/2/3/4 对应中证一/二/三/四级行业简称。"""
    ind_dir = data_path / INDUSTRY_DIR_NAME
    files = sorted(ind_dir.glob("*.xlsx"))
    if not files:
        raise FileNotFoundError(f"找不到行业分类 xlsx: {ind_dir}")
    rows = _read_sheet(files[-1])
    col_industry = 1 + level * 2

    records = []
    for r in rows[1:]:
        if len(r) <= col_industry:
            continue
        code, industry = r[0], r[col_industry]
        if code and industry:
            records.append({"code": str(code), "industry": industry})
    return pl.DataFrame(records)


def _find_quote_file(data_path: Path, target_date: str) -> Path:
    """在候选目录里找指定日期的行情文件，靠前的目录优先。"""
    for name in QUOTE_DIR_CANDIDATES:
        f = data_path / name / f"{target_date}.csv"
        if f.exists():
            return f
    raise FileNotFoundError(f"找不到 {target_date} 行情文件，已搜: {QUOTE_DIR_CANDIDATES}")


def load_quote(data_path: Path, target_date: str) -> pl.DataFrame:
    """指定日期行情 → [code(6位字符串), turnover, pct_chg]。"""
    f = _find_quote_file(data_path, target_date)
    df = pl.read_csv(f, infer_schema_length=10000)
    return (
        df.with_columns([
            pl.col("code").cast(pl.Utf8).str.zfill(6).alias("code"),
            ((pl.col("close") - pl.col("prev_close")) / pl.col("prev_close")).alias("pct_chg"),
        ])
        .filter(pl.col("turnover") > 0)
        .filter(pl.col("pct_chg").is_not_null() & pl.col("pct_chg").is_finite())
        .select(["code", "turnover", "pct_chg"])
    )


def pick_latest_full_date(data_path: Path) -> str:
    """扫描所有行情候选目录，取最新一份行数 >= MIN_FULL_ROWS 的日期。"""
    by_date: dict[str, Path] = {}
    for name in QUOTE_DIR_CANDIDATES:
        d = data_path / name
        if not d.exists():
            continue
        for f in d.glob("*.csv"):
            by_date.setdefault(f.stem, f)  # 候选列表靠前的目录优先
    for date in sorted(by_date, reverse=True):
        with open(by_date[date], "rb") as fp:
            n = sum(1 for _ in fp)
        if n >= MIN_FULL_ROWS:
            return date
    raise RuntimeError(f"找不到行数 >= {MIN_FULL_ROWS} 的完整行情文件")
