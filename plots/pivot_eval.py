"""价格枢轴评估公用模块。

提供回溯式 ZigZag 枢轴检测 + 信号对枢轴的命中评估，供多个研究脚本复用：
  - zigzag_pivots: 在 high/low 序列上找阶段高/低点（反转 ≥ pct 才确认）
  - find_nearest_pivot: 给一个信号位置，找半径内最近的枢轴
  - pivot_gap_metrics: 一批信号对一批枢轴的命中统计（天数/价格差距）

ZigZag 是回顾式的：枢轴在真实峰值日，但「确认」存在滞后（需等反转）。
因此最后一个未确认极值不返回——实时不可知。做信号评估时这是「正确答案」，
但做实时决策时不能直接用（含未来函数）。
"""
from __future__ import annotations

import bisect

import numpy as np


def zigzag_pivots(highs: list, lows: list, pct: float) -> list[tuple[int, float, str]]:
    """回溯式 ZigZag 枢轴点。返回 [(idx, price, 'H'|'L'), ...]。

    pct = 最小反转幅度（如 0.08 = 8%）。上升段跟踪最高 high，下降段跟踪最低 low；
    反方向移动 ≥ pct 才确认枢轴。最后一个未确认的极值**不**返回（实时不可知）。
    """
    n = len(highs)
    if n < 2:
        return []
    pivots: list[tuple[int, float, str]] = []
    direction = 0
    i = 1
    seed_h, seed_l = highs[0], lows[0]
    ext_idx, ext_val = 0, highs[0]
    while i < n and direction == 0:
        if highs[i] >= seed_l * (1 + pct):
            direction = 1
            pivots.append((0, lows[0], "L"))
            ext_idx, ext_val = i, highs[i]
        elif lows[i] <= seed_h * (1 - pct):
            direction = -1
            pivots.append((0, highs[0], "H"))
            ext_idx, ext_val = i, lows[i]
        i += 1
    if direction == 0:
        return []
    while i < n:
        if direction == 1:
            if highs[i] > ext_val:
                ext_idx, ext_val = i, highs[i]
            if lows[i] <= ext_val * (1 - pct):
                pivots.append((ext_idx, ext_val, "H"))
                direction = -1
                ext_idx, ext_val = i, lows[i]
        else:
            if lows[i] < ext_val:
                ext_idx, ext_val = i, lows[i]
            if highs[i] >= ext_val * (1 + pct):
                pivots.append((ext_idx, ext_val, "L"))
                direction = 1
                ext_idx, ext_val = i, highs[i]
        i += 1
    return pivots


def find_nearest_pivot(
    idx: int, pivot_idxs: list[int], max_look: int
) -> tuple[int, int] | None:
    """找离 idx 绝对距离最近（≤ max_look）的 pivot 位置。

    返回 (pivot_idx, signed_gap)，gap>0 = pivot 在未来，<0 = 在过去。None = 半径内无 pivot。
    """
    if not pivot_idxs:
        return None
    j = bisect.bisect_left(pivot_idxs, idx)
    candidates: list[tuple[int, int]] = []
    if j < len(pivot_idxs):
        candidates.append((pivot_idxs[j], pivot_idxs[j] - idx))
    if j > 0:
        candidates.append((pivot_idxs[j - 1], pivot_idxs[j - 1] - idx))
    candidates.sort(key=lambda x: abs(x[1]))
    pivot_idx, gap = candidates[0]
    if abs(gap) > max_look:
        return None
    return pivot_idx, gap


def pivot_gap_metrics(
    signal_idxs: list[int],
    pivot_idxs: list[int],
    closes: list,
    max_look: int,
) -> dict | None:
    """一批信号对一批枢轴的命中统计。

    返回 dict：
      n_total, n_matched,
      day_gaps (list[int]), price_gaps (list[float]),  # signed
      day_abs_med, price_abs_med,
      pct_within_5d, pct_within_15d, pct_within_30d,
      pct_within_2pct, pct_within_5pct_price,
      n_lead (pivot 在未来), n_lag (在过去), n_same
    无匹配信号时返回 None。
    """
    if not signal_idxs:
        return None
    sorted_pivots = sorted(pivot_idxs)
    day_gaps: list[int] = []
    price_gaps: list[float] = []
    no_match = 0
    for bi in signal_idxs:
        m = find_nearest_pivot(bi, sorted_pivots, max_look)
        if m is None:
            no_match += 1
            continue
        pi, gap = m
        day_gaps.append(gap)
        price_gaps.append(closes[pi] / closes[bi] - 1)
    matched = len(day_gaps)
    if matched == 0:
        return {
            "n_total": len(signal_idxs),
            "n_matched": 0,
            "no_match": no_match,
            "day_abs_med": None,
            "price_abs_med": None,
            "pct_within_5d": None,
            "pct_within_15d": None,
            "pct_within_30d": None,
            "pct_within_2pct": None,
            "pct_within_5pct_price": None,
            "n_lead": 0,
            "n_lag": 0,
            "n_same": 0,
        }
    day_arr = np.array(day_gaps)
    price_arr = np.array(price_gaps)
    return {
        "n_total": len(signal_idxs),
        "n_matched": matched,
        "no_match": no_match,
        "day_abs_med": int(np.median(np.abs(day_arr))),
        "price_abs_med": float(np.median(np.abs(price_arr))),
        "pct_within_5d": float((np.abs(day_arr) <= 5).mean()),
        "pct_within_15d": float((np.abs(day_arr) <= 15).mean()),
        "pct_within_30d": float((np.abs(day_arr) <= 30).mean()),
        "pct_within_2pct": float((np.abs(price_arr) <= 0.02).mean()),
        "pct_within_5pct_price": float((np.abs(price_arr) <= 0.05).mean()),
        "n_lead": int((day_arr > 0).sum()),
        "n_lag": int((day_arr < 0).sum()),
        "n_same": int((day_arr == 0).sum()),
    }
