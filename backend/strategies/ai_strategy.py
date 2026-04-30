"""
AI 驱动策略（通用）
来自 ai-bian 的 4 个 AI 策略，决策完全由 LLM 驱动
这些策略的 check_signal 始终返回 None（因为纯规则无法执行 AI prompt）
实际信号生成在 strategy_runner._ai_decide 中完成
"""
import numpy as np
import pandas as pd

from strategies.base import IStrategy
from indicators.technical import calc_ema, calc_rsi, calc_adx, calc_atr, calc_macd, calc_sma


class AIStrategy(IStrategy):
    """
    AI 驱动策略基类
    不执行纯技术指标信号检测，仅计算指标供 AI 分析使用
    """

    def __init__(self, name: str, direction: str = "both"):
        self._name = name
        self._direction = direction

    @property
    def name(self) -> str:
        return self._name

    @property
    def direction(self) -> str:
        return self._direction

    def check_signal(self, df: pd.DataFrame, params: dict) -> dict | None:
        """hybrid 模式：指标预筛（快速过滤无信号场景，减少 LLM 调用）"""
        pre_filter = params.get("pre_filter")
        if not pre_filter:
            return None

        closes = df["close"].values
        highs = df["high"].values
        lows = df["low"].values
        idx = len(df) - 1

        # ADX 趋势强度过滤
        adx_min = pre_filter.get("adx_min", 0)
        if adx_min > 0:
            adx = calc_adx(highs, lows, closes, params.get("adx_period", 14))
            if np.isnan(adx[idx]) or adx[idx] < adx_min:
                return None

        # EMA 方向过滤
        ema_direction = pre_filter.get("ema_direction")
        if ema_direction:
            ema_periods = params.get("ema_periods", [7, 20, 50])
            fast_p = ema_periods[0] if len(ema_periods) > 0 else 7
            slow_p = ema_periods[-1] if len(ema_periods) > 1 else 50
            fast_ema = calc_ema(closes, fast_p)
            slow_ema = calc_ema(closes, slow_p)

            if ema_direction is True:
                # Just check there's a clear direction (not flat)
                if abs(fast_ema[idx] - slow_ema[idx]) / slow_ema[idx] < 0.001:
                    return None
            elif ema_direction == "long":
                if fast_ema[idx] <= slow_ema[idx]:
                    return None
            elif ema_direction == "short":
                if fast_ema[idx] >= slow_ema[idx]:
                    return None

        # RSI 区间过滤
        rsi_range = pre_filter.get("rsi_range")
        if rsi_range:
            rsi = calc_rsi(closes, params.get("rsi_period", 14))
            rsi_val = rsi[idx]
            if np.isnan(rsi_val) or rsi_val < rsi_range[0] or rsi_val > rsi_range[1]:
                return None

        # 通过所有过滤器 → 返回占位信号（方向由 AI 决定）
        price = closes[idx]
        return {
            "direction": "long",
            "price": round(price, 4),
            "tp_price": 0,
            "sl_price": 0,
            "reason": "📊 指标预筛通过",
        }

    def compute_indicators(self, df: pd.DataFrame, params: dict, oi_data: dict = None) -> dict:
        """计算全量指标供 AI 分析"""
        closes = df["close"].values
        highs = df["high"].values
        lows = df["low"].values
        opens = df["open"].values
        volumes = df["volCcy"].values if "volCcy" in df.columns else df["vol"].values

        idx = len(df) - 1
        result = {"price": round(closes[idx], 4)}

        # 可配置的指标开关
        enabled = params.get("indicators", ["EMA", "RSI", "ADX", "ATR", "MACD"])

        # EMA 多周期
        if "EMA" in enabled:
            ema_periods = params.get("ema_periods", [7, 20, 50, 120, 200])
            for p in ema_periods:
                ema = calc_ema(closes, p)
                val = ema[idx]
                result[f"EMA{p}"] = round(val, 4) if not np.isnan(val) else None

        # RSI
        if "RSI" in enabled:
            rsi = calc_rsi(closes, params.get("rsi_period", 14))
            result["RSI"] = round(rsi[idx], 2) if not np.isnan(rsi[idx]) else None

        # ADX
        if "ADX" in enabled:
            adx = calc_adx(highs, lows, closes, params.get("adx_period", 14))
            result["ADX"] = round(adx[idx], 2) if not np.isnan(adx[idx]) else None

        # ATR
        if "ATR" in enabled:
            atr = calc_atr(highs, lows, closes, params.get("atr_period", 14))
            result["ATR"] = round(atr[idx], 4) if not np.isnan(atr[idx]) else None

        # MACD
        if "MACD" in enabled:
            macd_params = params.get("macd_params", {"fast": 12, "slow": 26, "signal": 9})
            macd_line, signal_line, histogram = calc_macd(
                closes,
                macd_params.get("fast", 12),
                macd_params.get("slow", 26),
                macd_params.get("signal", 9),
            )
            result["MACD"] = round(macd_line[idx], 4) if not np.isnan(macd_line[idx]) else None
            result["MACD_Signal"] = round(signal_line[idx], 4) if not np.isnan(signal_line[idx]) else None
            result["MACD_Histogram"] = round(histogram[idx], 4) if not np.isnan(histogram[idx]) else None

        # 成交量（始终计算）
        avg_vol = calc_sma(volumes, params.get("vol_compare_period", 20))
        result["volume"] = round(volumes[idx], 2)
        result["avg_volume"] = round(avg_vol[idx], 2) if not np.isnan(avg_vol[idx]) else None
        if result["avg_volume"] and result["avg_volume"] > 0:
            result["volume_ratio"] = round(volumes[idx] / avg_vol[idx], 2)

        # K线形态（始终计算）
        body = closes[idx] - opens[idx]
        candle_range = highs[idx] - lows[idx]
        result["candle_type"] = "阳线" if body > 0 else "阴线"
        if candle_range > 0:
            result["upper_wick_pct"] = round((highs[idx] - max(opens[idx], closes[idx])) / candle_range * 100, 2)
            result["lower_wick_pct"] = round((min(opens[idx], closes[idx]) - lows[idx]) / candle_range * 100, 2)

        # 前一根 K 线成交量（用于预估成交量比较）
        if idx > 0:
            result["prev_volume"] = round(volumes[idx - 1], 2)

        # OI 数据
        if oi_data:
            result["OI"] = round(oi_data.get("oi", 0), 2)
            result["OI_ccy"] = round(oi_data.get("oiCcy", 0), 2)

        return result
