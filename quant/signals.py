"""Signal 层 —— 在 tag 之上组合出买卖信号（布尔日序列）。

设计要点
--------
- 一个 ``Signal`` = 多个 tag 经 ``combiner``（``all``=AND / ``any``=OR）合成一条布尔日序列。
- 买入、卖出各自一个 ``Signal``，互相独立 —— 一个策略的买卖不必对称。
- 有状态离场（移动止损 / breakdown）不在本层，由 ``strategy`` 引擎的 ``Stop`` 处理，
  与 ``sell`` Signal 成 OR 关系：实际卖出 = sell_signal OR 触及 stop。

tag 复用 ``quant.tags.TAG_FUNCS``；带参数的 tag（如 ``boll_lower``）用 ``TagSpec`` 传参，
只读默认值的也可直接传字符串名。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Union

import polars as pl

from quant.tags import TAG_FUNCS


@dataclass
class TagSpec:
    """一个 tag 调用：名字 + 参数。"""

    name: str
    params: dict = field(default_factory=dict)


# Signal.tags 元素既可以是 TagSpec（带参），也可以是裸字符串（用默认参数）
TagLike = Union[str, TagSpec]


@dataclass
class Signal:
    """买卖信号：多个 tag 经 combiner 合成。"""

    tags: list[TagLike]
    combiner: str = "all"  # "all"=全部命中 | "any"=任一命中

    def __post_init__(self) -> None:
        if self.combiner not in ("all", "any"):
            raise ValueError(f"combiner must be 'all' or 'any', got {self.combiner!r}")


@dataclass
class Stop:
    """有状态离场（引擎层，与 sell Signal 成 OR）。

    - ``trail``：移动止损，close < 持仓峰值 high − m·σ(window) 时出场
    - ``breakdown``：close 先收盘站上上轨(MA+k·σ)，之后连续 confirm 日收回上轨之下时出场
    """

    kind: str  # "trail" | "breakdown"
    m: float = 1.5  # trail
    window: int = 120  # σ / 通道窗口
    k: float = 1.5  # breakdown 上轨倍数
    confirm: int = 1  # breakdown 确认期


def _spec(t: TagLike) -> TagSpec:
    return t if isinstance(t, TagSpec) else TagSpec(name=t)


def eval_signal(df: pl.DataFrame, signal: Signal) -> pl.Series:
    """对 df 应用 signal 中的全部 tag，返回名为 ``_signal`` 的布尔 Series。

    空 tags → 恒 False（供「卖出全靠 Stop」的场景用）。
    """
    if not signal.tags:
        return pl.Series("_signal", [False] * df.height)

    out = df
    names: list[str] = []
    for t in signal.tags:
        s = _spec(t)
        if s.name not in TAG_FUNCS:
            raise ValueError(
                f"Unknown tag: {s.name}. Available: {list(TAG_FUNCS.keys())}"
            )
        out = TAG_FUNCS[s.name](out, **s.params)
        names.append(f"tag_{s.name}")

    if signal.combiner == "all":
        expr = pl.lit(True)
        for c in names:
            expr = expr & pl.col(c)
    else:  # any
        expr = pl.lit(False)
        for c in names:
            expr = expr | pl.col(c)
    return out.with_columns(expr.alias("_signal")).get_column("_signal")
