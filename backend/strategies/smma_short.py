"""
SMMA 压制做空策略
从 okx-smma-trader/smma_strategy.py 移植
"""
import numpy as np
import pandas as pd

from strategies.base import IStrategy
from indicators.technical import calc_smma, calc_sma, calc_ema, aggregate_to_htf


class SMMAShortStrategy(IStrategy):
    """
    SMMA 压制 + 放量阴线短线做空策略

    开仓条件：
    1. SMMA 趋势向下: current_smma <= prev_smma
    2. 价格在 SMMA 下方 % (pctThreshold) 范围内
    3. 当前K线为阴线（close < open）
    4. 阴线实体占比 >= bodyPercent
    5. 成交量 > avgVol * volMultiplier 且 > volMinAbs
    6. 1m 价格低于 EMA200（偏置过滤）
    7. 5m EMA20 < EMA50（大周期方向过滤）
    """

    @property
    def name(self) -> str:
        return "SMMA 压制做空"

    @property
    def direction(self) -> str:
        return "short"

    def check_signal(self, df: pd.DataFrame, params: dict) -> dict | None:
        period = params.get("smma_period", 170)
        vol_min_abs = params.get("vol_min_abs", 1000)
        vol_multiplier = params.get("vol_multiplier", 6)
        body_percent = params.get("body_percent", 60.0)
        pct_threshold = params.get("pct_threshold", 1.0)
        tp_type = params.get("tp_type", "fixed_pct")
        stop_offset = params.get("stop_offset", 0.3)
        fixed_tp = params.get("fixed_tp", 1.4)
        rr_ratio = params.get("rr_ratio", 2.0)
        enable_htf_filter = params.get("enable_htf_filter", True)
        htf_bar = params.get("htf_bar", "5m")
        htf_fast_ema = params.get("htf_fast_ema", 20)
        htf_slow_ema = params.get("htf_slow_ema", 50)
        enable_ema_bias_filter = params.get("enable_ema_bias_filter", True)
        ema_bias_period = params.get("ema_bias_period", 200)

        min_len = max(period + 1, 51, ema_bias_period + 1)
        if len(df) < min_len:
            return None

        closes = df["close"].values
        opens = df["open"].values
        highs = df["high"].values
        lows = df["low"].values
        volumes = df["volCcy"].values if "volCcy" in df.columns else df["vol"].values

        smma = calc_smma(closes, period)
        avg_vol = calc_sma(volumes, 50)
        ema_bias = calc_ema(closes, ema_bias_period)

        # 使用最后一根已确认 K 线
        if "confirm" in df.columns:
            confirmed = df[df["confirm"] == 1]
            idx = confirmed.index[-1] if len(confirmed) > 0 else len(df) - 2
        else:
            idx = len(df) - 1

        if idx < 1:
            return None

        current_close = closes[idx]
        current_open = opens[idx]
        current_high = highs[idx]
        current_vol = volumes[idx]
        current_smma = smma[idx]
        prev_smma = smma[idx - 1]
        current_avg_vol = avg_vol[idx]
        current_ema_bias = ema_bias[idx]

        if np.isnan(current_smma) or np.isnan(current_avg_vol):
            return None

        # 条件检查
        is_trending_down = current_smma <= prev_smma

        ema_bias_ok = True
        if enable_ema_bias_filter:
            ema_bias_ok = not np.isnan(current_ema_bias) and current_close < current_ema_bias

        htf_trend_ok = True
        if enable_htf_filter:
            htf_trend_ok = self._check_htf_trend(df.iloc[:idx + 1], htf_bar, htf_fast_ema, htf_slow_ema)

        is_high_vol = (current_vol > current_avg_vol * vol_multiplier) and (current_vol > vol_min_abs)

        candle_range = current_high - lows[idx]
        body_size = abs(current_open - current_close)
        is_solid_body = candle_range > 0 and (body_size / candle_range) * 100 >= body_percent

        distance_pct = ((current_smma - current_close) / current_smma) * 100
        is_within_range = (current_close < current_smma) and (distance_pct <= pct_threshold)
        is_bearish = current_close < current_open

        if not (is_bearish and is_high_vol and is_solid_body and is_within_range
                and is_trending_down and ema_bias_ok and htf_trend_ok):
            return None

        # 计算止盈止损
        stop_price = current_high + stop_offset
        risk = stop_price - current_close
        if tp_type == "rr_ratio":
            tp_price = current_close - (risk * rr_ratio)
        else:
            tp_price = current_close * (1 - fixed_tp / 100)

        return {
            "direction": "short",
            "price": round(current_close, 2),
            "tp_price": round(tp_price, 2),
            "sl_price": round(stop_price, 2),
            "reason": (
                f"🔴 做空 | SMMA({period})={current_smma:.2f} | "
                f"价格={current_close:.2f} | 放量={current_vol:.0f}"
            ),
        }

    def compute_indicators(self, df: pd.DataFrame, params: dict) -> dict:
        period = params.get("smma_period", 170)
        ema_bias_period = params.get("ema_bias_period", 200)

        closes = df["close"].values
        volumes = df["volCcy"].values if "volCcy" in df.columns else df["vol"].values

        smma = calc_smma(closes, period)
        ema200 = calc_ema(closes, ema_bias_period)
        avg_vol = calc_sma(volumes, 50)

        idx = len(df) - 1
        price = closes[idx]
        smma_val = smma[idx] if not np.isnan(smma[idx]) else 0
        dist_pct = ((smma_val - price) / smma_val * 100) if smma_val > 0 else 0

        return {
            "price": round(price, 2),
            "smma": round(smma_val, 2),
            "ema200": round(ema200[idx], 2) if not np.isnan(ema200[idx]) else 0,
            "distance_smma_pct": round(dist_pct, 2),
            "volume": round(volumes[idx], 0),
            "avg_volume_50": round(avg_vol[idx], 0) if not np.isnan(avg_vol[idx]) else 0,
            "is_bearish": bool(closes[idx] < df["open"].values[idx]),
        }

    @staticmethod
    def _check_htf_trend(df: pd.DataFrame, htf_bar: str, fast_period: int, slow_period: int) -> bool:
        htf_df = aggregate_to_htf(df, htf_bar)
        if len(htf_df) == 0:
            return False
        htf_closes = htf_df["close"].values
        htf_fast = calc_ema(htf_closes, fast_period)
        htf_slow = calc_ema(htf_closes, slow_period)
        return (
            not np.isnan(htf_fast[-1])
            and not np.isnan(htf_slow[-1])
            and htf_fast[-1] < htf_slow[-1]
        )
