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
        # AI 策略不支持纯技术指标模式，始终返回 None
        # 信号生成由 strategy_runner._ai_decide 完成
        return None

    def compute_indicators(self, df: pd.DataFrame, params: dict) -> dict:
        """计算全量指标供 AI 分析"""
        closes = df["close"].values
        highs = df["high"].values
        lows = df["low"].values
        opens = df["open"].values
        volumes = df["volCcy"].values if "volCcy" in df.columns else df["vol"].values

        idx = len(df) - 1
        result = {"price": round(closes[idx], 4)}

        # EMA 多周期
        ema_periods = params.get("ema_periods", [7, 20, 50, 120, 200])
        for p in ema_periods:
            ema = calc_ema(closes, p)
            val = ema[idx]
            result[f"EMA{p}"] = round(val, 4) if not np.isnan(val) else None

        # RSI
        rsi = calc_rsi(closes, params.get("rsi_period", 14))
        result["RSI"] = round(rsi[idx], 2) if not np.isnan(rsi[idx]) else None

        # ADX
        adx = calc_adx(highs, lows, closes, params.get("adx_period", 14))
        result["ADX"] = round(adx[idx], 2) if not np.isnan(adx[idx]) else None

        # ATR
        atr = calc_atr(highs, lows, closes, params.get("atr_period", 14))
        result["ATR"] = round(atr[idx], 4) if not np.isnan(atr[idx]) else None

        # MACD
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

        # 成交量
        avg_vol = calc_sma(volumes, params.get("vol_compare_period", 20))
        result["volume"] = round(volumes[idx], 2)
        result["avg_volume"] = round(avg_vol[idx], 2) if not np.isnan(avg_vol[idx]) else None
        if result["avg_volume"] and result["avg_volume"] > 0:
            result["volume_ratio"] = round(volumes[idx] / avg_vol[idx], 2)

        # K线形态
        body = closes[idx] - opens[idx]
        candle_range = highs[idx] - lows[idx]
        result["candle_type"] = "阳线" if body > 0 else "阴线"
        if candle_range > 0:
            result["upper_wick_pct"] = round((highs[idx] - max(opens[idx], closes[idx])) / candle_range * 100, 2)
            result["lower_wick_pct"] = round((min(opens[idx], closes[idx]) - lows[idx]) / candle_range * 100, 2)

        # 前一根 K 线成交量（用于预估成交量比较）
        if idx > 0:
            result["prev_volume"] = round(volumes[idx - 1], 2)

        return result
