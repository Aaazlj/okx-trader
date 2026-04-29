"""
BOLL 中线收复策略（纯做多）
价格从 BOLL 中轨下方收回上方，确认空转多反转信号
"""
import numpy as np
import pandas as pd

from strategies.base import IStrategy
from indicators.technical import calc_boll, calc_sma


class BollMidlineReclaimStrategy(IStrategy):
    """
    BOLL 中线收复 — 均值回归 + 趋势反转

    前置：价格此前被 BOLL 中轨持续压制
    入场：15m K 线收盘从中轨下方收回上方
    止损：收复阳线低点或中轨下方
    止盈：BOLL 上轨附近
    """

    @property
    def name(self) -> str:
        return "BOLL 中线收复"

    @property
    def direction(self) -> str:
        return "long"

    def check_signal(self, df: pd.DataFrame, params: dict) -> dict | None:
        # ── 参数 ──
        boll_period = params.get("boll_period", 20)
        boll_std = params.get("boll_std", 2.0)
        suppress_lookback = params.get("suppress_lookback", 5)
        suppress_count = params.get("suppress_count", 3)
        sl_offset_pct = params.get("sl_offset_pct", 0.2)

        min_len = max(boll_period + suppress_lookback + 2, 30)
        if len(df) < min_len:
            return None

        closes = df["close"].values
        opens = df["open"].values
        lows = df["low"].values

        upper, mid, _ = calc_boll(closes, boll_period, boll_std)

        # 使用最后已确认 K 线
        if "confirm" in df.columns:
            confirmed = df[df["confirm"] == 1]
            idx = confirmed.index[-1] if len(confirmed) > 0 else len(df) - 2
        else:
            idx = len(df) - 1

        if idx < suppress_lookback + 1:
            return None

        cur_mid = mid[idx]
        prev_mid = mid[idx - 1]
        cur_upper = upper[idx]
        if any(np.isnan(v) for v in [cur_mid, prev_mid, cur_upper]):
            return None

        cur_close = closes[idx]
        prev_close = closes[idx - 1]
        cur_open = opens[idx]
        cur_low = lows[idx]

        # ── 前置状态：此前被中轨压制 ──
        # 前 suppress_lookback 根 K 线中，至少 suppress_count 根收盘低于中轨
        below_count = 0
        for i in range(idx - suppress_lookback, idx):
            if i >= 0 and not np.isnan(mid[i]) and closes[i] < mid[i]:
                below_count += 1

        if below_count < suppress_count:
            return None

        # ── 收复信号：前一根收盘 < 中轨，当前根收盘 > 中轨 ──
        if not (prev_close < prev_mid and cur_close > cur_mid):
            return None

        # 当前 K 线是阳线
        if cur_close <= cur_open:
            return None

        # ── 止盈止损 ──
        sl_price = min(cur_low, cur_mid) * (1 - sl_offset_pct / 100)
        tp_price = cur_upper  # 目标 BOLL 上轨

        return {
            "direction": "long",
            "price": round(cur_close, 4),
            "tp_price": round(tp_price, 4),
            "sl_price": round(sl_price, 4),
            "reason": (
                f"🟢 BOLL中线收复 | 中轨={cur_mid:.4f} | "
                f"价格={cur_close:.4f} | 压制{below_count}/{suppress_lookback}根"
            ),
        }

    def compute_indicators(self, df: pd.DataFrame, params: dict) -> dict:
        boll_period = params.get("boll_period", 20)
        closes = df["close"].values
        idx = len(df) - 1

        upper, mid, lower = calc_boll(closes, boll_period)

        # 统计最近被压制情况
        suppress_lookback = params.get("suppress_lookback", 5)
        below_count = 0
        for i in range(max(0, idx - suppress_lookback), idx):
            if not np.isnan(mid[i]) and closes[i] < mid[i]:
                below_count += 1

        return {
            "price": round(closes[idx], 4),
            "boll_upper": round(upper[idx], 4) if not np.isnan(upper[idx]) else None,
            "boll_mid": round(mid[idx], 4) if not np.isnan(mid[idx]) else None,
            "boll_lower": round(lower[idx], 4) if not np.isnan(lower[idx]) else None,
            "below_mid_count": below_count,
            "is_above_mid": bool(closes[idx] > mid[idx]) if not np.isnan(mid[idx]) else None,
            "is_bullish": bool(closes[idx] > df["open"].values[idx]),
        }
