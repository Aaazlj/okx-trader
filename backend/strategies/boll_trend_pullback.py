"""
趋势回踩二次启动策略（纯做多）
大周期（1H）确认强趋势 + 小周期（15m）回踩 BOLL 中轨后放量企稳入场
"""
import numpy as np
import pandas as pd

from strategies.base import IStrategy
from indicators.technical import calc_boll, calc_ema, calc_sma


class BollTrendPullbackStrategy(IStrategy):
    """
    趋势回踩二次启动 — 顺大势、逆小势

    1H 趋势确认：BOLL 开口向上 + EMA 多头排列 + 创阶段新高
    15m 入场：回踩 BOLL 中轨 + 止跌阳线 + 放量
    止损：BOLL 中轨下方
    """

    @property
    def name(self) -> str:
        return "趋势回踩二次启动"

    @property
    def direction(self) -> str:
        return "long"

    def check_signal(self, df: pd.DataFrame, params: dict) -> dict | None:
        # ── 参数 ──
        boll_period = params.get("boll_period", 20)
        boll_std = params.get("boll_std", 2.0)
        htf_lookback_high = params.get("htf_lookback_high", 20)
        pullback_tolerance_pct = params.get("pullback_tolerance_pct", 0.3)
        vol_multiplier = params.get("vol_multiplier", 1.5)
        tp_pct = params.get("tp_pct", 1.5)
        sl_offset_pct = params.get("sl_offset_pct", 0.2)

        # ── 1H 趋势确认 ──
        df_htf = params.get("df_htf")
        if df_htf is None or len(df_htf) < boll_period + 5:
            return None

        htf_closes = df_htf["close"].values
        htf_upper, htf_mid, _ = calc_boll(htf_closes, boll_period, boll_std)

        htf_ema7 = calc_ema(htf_closes, 7)
        htf_ema20 = calc_ema(htf_closes, 20)
        htf_ema50 = calc_ema(htf_closes, 50)

        hi = len(df_htf) - 1
        # 需要足够数据
        if any(np.isnan(v[hi]) for v in [htf_upper, htf_mid, htf_ema7, htf_ema20, htf_ema50]):
            return None

        # BOLL 开口向上：上轨斜率 > 0
        if hi < 1 or htf_upper[hi] <= htf_upper[hi - 1]:
            return None

        # 价格在 BOLL 中轨上方
        if htf_closes[hi] <= htf_mid[hi]:
            return None

        # EMA 多头排列：EMA7 > EMA20 > EMA50
        if not (htf_ema7[hi] > htf_ema20[hi] > htf_ema50[hi]):
            return None

        # 创阶段新高
        lookback = min(htf_lookback_high, hi)
        recent_highs = df_htf["high"].values[hi - lookback : hi]
        if len(recent_highs) > 0 and htf_closes[hi] <= np.max(recent_highs) * 0.998:
            return None

        # ── 15m 回踩入场 ──
        min_len = max(boll_period + 2, 52)
        if len(df) < min_len:
            return None

        closes = df["close"].values
        opens = df["open"].values
        lows = df["low"].values
        volumes = df["volCcy"].values if "volCcy" in df.columns else df["vol"].values

        _, mid_15m, _ = calc_boll(closes, boll_period, boll_std)
        avg_vol = calc_sma(volumes, 50)

        # 使用最后已确认 K 线
        if "confirm" in df.columns:
            confirmed = df[df["confirm"] == 1]
            idx = confirmed.index[-1] if len(confirmed) > 0 else len(df) - 2
        else:
            idx = len(df) - 1

        if idx < 1 or np.isnan(mid_15m[idx]) or np.isnan(avg_vol[idx]):
            return None

        cur_close = closes[idx]
        cur_open = opens[idx]
        cur_low = lows[idx]
        cur_vol = volumes[idx]
        cur_mid = mid_15m[idx]
        cur_avg_vol = avg_vol[idx]

        # 回踩 BOLL 中轨：low 接近中轨（tolerance 内）
        dist_to_mid_pct = abs(cur_low - cur_mid) / cur_mid * 100
        if cur_low > cur_mid * (1 + pullback_tolerance_pct / 100):
            return None  # 未触及中轨区域
        if dist_to_mid_pct > pullback_tolerance_pct and cur_low > cur_mid:
            return None

        # 止跌阳线
        if cur_close <= cur_open:
            return None

        # 收盘在中轨上方（企稳）
        if cur_close <= cur_mid:
            return None

        # 放量
        if cur_avg_vol > 0 and cur_vol < cur_avg_vol * vol_multiplier:
            return None

        # ── 止盈止损 ──
        sl_price = cur_mid * (1 - sl_offset_pct / 100)
        tp_price = cur_close * (1 + tp_pct / 100)

        return {
            "direction": "long",
            "price": round(cur_close, 4),
            "tp_price": round(tp_price, 4),
            "sl_price": round(sl_price, 4),
            "reason": (
                f"🟢 趋势回踩做多 | BOLL中轨={cur_mid:.4f} | "
                f"价格={cur_close:.4f} | 放量={cur_vol:.0f}"
            ),
        }

    def compute_indicators(self, df: pd.DataFrame, params: dict) -> dict:
        boll_period = params.get("boll_period", 20)
        closes = df["close"].values
        volumes = df["volCcy"].values if "volCcy" in df.columns else df["vol"].values
        idx = len(df) - 1

        upper, mid, lower = calc_boll(closes, boll_period)
        avg_vol = calc_sma(volumes, 50)

        return {
            "price": round(closes[idx], 4),
            "boll_upper": round(upper[idx], 4) if not np.isnan(upper[idx]) else None,
            "boll_mid": round(mid[idx], 4) if not np.isnan(mid[idx]) else None,
            "boll_lower": round(lower[idx], 4) if not np.isnan(lower[idx]) else None,
            "volume": round(volumes[idx], 2),
            "avg_volume_50": round(avg_vol[idx], 2) if not np.isnan(avg_vol[idx]) else None,
            "is_bullish": bool(closes[idx] > df["open"].values[idx]),
        }
