"""
技术指标计算 — SMMA / EMA / SMA / RSI / ADX / MACD / ATR / 量能分析
从 okx-smma-trader 移植 + ai-bian 需求扩展，纯 numpy 实现
"""
import numpy as np
import pandas as pd


def calc_smma(closes: np.ndarray, period: int) -> np.ndarray:
    """计算 SMMA (Smoothed Moving Average) / RMA"""
    n = len(closes)
    smma = np.full(n, np.nan)
    if n < period:
        return smma

    smma[period - 1] = np.mean(closes[:period])
    for i in range(period, n):
        smma[i] = (smma[i - 1] * (period - 1) + closes[i]) / period
    return smma


def calc_sma(values: np.ndarray, period: int) -> np.ndarray:
    """计算简单移动平均"""
    ret = np.cumsum(values, dtype=float)
    ret[period:] = ret[period:] - ret[:-period]
    res = ret[period - 1:] / period
    pad = np.full(period - 1, np.nan)
    return np.concatenate((pad, res))


def calc_ema(values: np.ndarray, period: int) -> np.ndarray:
    """计算指数移动平均 EMA"""
    n = len(values)
    ema = np.full(n, np.nan)
    if n < period:
        return ema

    alpha = 2 / (period + 1)
    ema[period - 1] = np.mean(values[:period])
    for i in range(period, n):
        ema[i] = alpha * values[i] + (1 - alpha) * ema[i - 1]
    return ema


def calc_rsi(closes: np.ndarray, period: int = 14) -> np.ndarray:
    """计算 RSI (Relative Strength Index)"""
    n = len(closes)
    rsi = np.full(n, np.nan)
    if n < period + 1:
        return rsi

    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    if avg_loss == 0:
        rsi[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        rsi[period] = 100 - 100 / (1 + rs)

    for i in range(period, n - 1):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsi[i + 1] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi[i + 1] = 100 - 100 / (1 + rs)

    return rsi


def calc_atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> np.ndarray:
    """计算 ATR (Average True Range)"""
    n = len(closes)
    atr = np.full(n, np.nan)
    if n < period + 1:
        return atr

    tr = np.zeros(n)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )

    atr[period] = np.mean(tr[1:period + 1])
    for i in range(period + 1, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period

    return atr


def calc_adx(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> np.ndarray:
    """计算 ADX (Average Directional Index)"""
    n = len(closes)
    adx = np.full(n, np.nan)
    if n < period * 2 + 1:
        return adx

    tr = np.zeros(n)
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)

    for i in range(1, n):
        h_diff = highs[i] - highs[i - 1]
        l_diff = lows[i - 1] - lows[i]
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        plus_dm[i] = h_diff if h_diff > l_diff and h_diff > 0 else 0
        minus_dm[i] = l_diff if l_diff > h_diff and l_diff > 0 else 0

    # Smoothed averages
    atr_s = np.mean(tr[1:period + 1])
    plus_dm_s = np.mean(plus_dm[1:period + 1])
    minus_dm_s = np.mean(minus_dm[1:period + 1])

    dx_values = []
    for i in range(period + 1, n):
        atr_s = (atr_s * (period - 1) + tr[i]) / period
        plus_dm_s = (plus_dm_s * (period - 1) + plus_dm[i]) / period
        minus_dm_s = (minus_dm_s * (period - 1) + minus_dm[i]) / period

        plus_di = 100 * plus_dm_s / atr_s if atr_s > 0 else 0
        minus_di = 100 * minus_dm_s / atr_s if atr_s > 0 else 0
        di_sum = plus_di + minus_di
        dx = 100 * abs(plus_di - minus_di) / di_sum if di_sum > 0 else 0
        dx_values.append(dx)

        if len(dx_values) == period:
            adx[i] = np.mean(dx_values)
        elif len(dx_values) > period:
            adx[i] = (adx[i - 1] * (period - 1) + dx) / period

    return adx


def calc_macd(
    closes: np.ndarray,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    计算 MACD

    Returns:
        (macd_line, signal_line, histogram)
    """
    fast_ema = calc_ema(closes, fast_period)
    slow_ema = calc_ema(closes, slow_period)
    macd_line = fast_ema - slow_ema

    # signal line = EMA of macd_line
    n = len(closes)
    signal_line = np.full(n, np.nan)

    # 找到 macd_line 第一个非 NaN 的位置
    valid_start = slow_period - 1
    valid_macd = macd_line[valid_start:]
    if len(valid_macd) >= signal_period:
        signal_ema = calc_ema(valid_macd, signal_period)
        signal_line[valid_start:] = signal_ema

    histogram = macd_line - signal_line

    return macd_line, signal_line, histogram


import re

# pandas 2.x 频率后缀兼容映射
_FREQ_COMPAT = {
    "m": "min",     # 5m -> 5min
    "h": "h",       # 1h -> 1h (不变)
    "d": "D",       # 1d -> 1D
}


def _normalize_freq(rule: str) -> str:
    """将 OKX 风格频率 (5m, 1h, 1d) 转为 pandas 2.x 兼容格式"""
    match = re.match(r'^(\d+)([a-zA-Z]+)$', rule)
    if not match:
        return rule
    num, unit = match.groups()
    return num + _FREQ_COMPAT.get(unit.lower(), unit)


def aggregate_to_htf(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """将 1m K 线聚合为高周期 K 线"""
    frame = df.copy()
    frame["ts"] = pd.to_datetime(frame["ts"])
    agg_map = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "vol": "sum",
    }
    if "volCcy" in frame.columns:
        agg_map["volCcy"] = "sum"

    freq = _normalize_freq(rule)
    return (
        frame.set_index("ts")
        .resample(freq, label="right", closed="right")
        .agg(agg_map)
        .dropna(subset=["open", "high", "low", "close"])
        .reset_index()
    )


