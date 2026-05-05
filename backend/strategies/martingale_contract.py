"""
马丁格尔合约策略

首单使用均值回归技术信号，后续补仓与退出由 MartingaleManager 管理。
"""
from copy import deepcopy
from typing import Any

import numpy as np
import pandas as pd

from indicators.technical import calc_boll, calc_rsi
from strategies.base import IStrategy


DEFAULT_MARTINGALE_PARAMS: dict[str, Any] = {
    "cycle": "medium",
    "bar": "4H",
    "direction": "long",
    "add_trigger_type": "pct",
    "add_trigger_value": 1.2,
    "take_profit_type": "pct",
    "take_profit_value": 0.6,
    "max_position_usdt": 300.0,
    "initial_margin_usdt": 20.0,
    "add_margin_usdt": 20.0,
    "max_add_count": 5,
    "boll_period": 20,
    "boll_std": 2.0,
    "rsi_period": 14,
    "long_rsi_max": 30.0,
    "short_rsi_min": 70.0,
    "max_levels": 6,
    "price_step_pct": 1.2,
    "size_multiplier": 1.0,
    "take_profit_pct": 0.6,
    "hard_stop_pct": 8.0,
    "cooldown_bars": 10,
    "fee_rate": 0.0005,
    "slippage_pct": 0.02,
    "risk": {
        "max_concurrent": 1,
        "max_daily_per_symbol": 3,
        "max_daily_loss_pct": 3.0,
    },
}

CYCLE_PRESETS: dict[str, dict[str, Any]] = {
    "short": {
        "label": "短期",
        "bar": "1H",
        "boll_period": 20,
        "boll_std": 2.0,
        "rsi_period": 14,
        "long_rsi_max": 32.0,
        "short_rsi_min": 68.0,
    },
    "medium": {
        "label": "中期",
        "bar": "4H",
        "boll_period": 20,
        "boll_std": 2.0,
        "rsi_period": 14,
        "long_rsi_max": 30.0,
        "short_rsi_min": 70.0,
    },
    "long": {
        "label": "长期",
        "bar": "1D",
        "boll_period": 20,
        "boll_std": 2.2,
        "rsi_period": 14,
        "long_rsi_max": 28.0,
        "short_rsi_min": 72.0,
    },
}


_RANGES = {
    "add_trigger_value": (0.01, 100000.0, float),
    "take_profit_value": (0.01, 100000.0, float),
    "max_position_usdt": (5.0, 100000.0, float),
    "initial_margin_usdt": (1.0, 100000.0, float),
    "add_margin_usdt": (1.0, 100000.0, float),
    "max_add_count": (0, 100, int),
    "boll_period": (10, 100, int),
    "boll_std": (1.0, 4.0, float),
    "rsi_period": (6, 50, int),
    "long_rsi_max": (10.0, 45.0, float),
    "short_rsi_min": (55.0, 90.0, float),
    "max_levels": (1, 101, int),
    "price_step_pct": (0.2, 10.0, float),
    "size_multiplier": (1.0, 3.0, float),
    "take_profit_pct": (0.1, 5.0, float),
    "hard_stop_pct": (1.0, 30.0, float),
    "cooldown_bars": (0, 100, int),
    "fee_rate": (0.0, 0.01, float),
    "slippage_pct": (0.0, 2.0, float),
}

_VALID_BARS = {"1m", "3m", "5m", "15m", "30m", "1H", "2H", "4H", "6H", "12H", "1D"}
_VALID_DIRECTIONS = {"long", "short", "both"}
_VALID_CYCLES = set(CYCLE_PRESETS)
_VALID_VALUE_TYPES = {"pct", "usdt"}


def normalize_martingale_params(params: dict | None) -> dict[str, Any]:
    """合并默认参数并限制到可执行范围。"""
    normalized = deepcopy(DEFAULT_MARTINGALE_PARAMS)
    if params:
        for key, value in params.items():
            if key == "risk" and isinstance(value, dict):
                normalized["risk"].update(value)
            else:
                normalized[key] = value

    if params and params.get("cycle") in _VALID_CYCLES:
        normalized["cycle"] = params["cycle"]
    elif params and params.get("bar"):
        normalized["cycle"] = _cycle_from_bar(params.get("bar"))
    elif normalized.get("cycle") not in _VALID_CYCLES:
        normalized["cycle"] = "medium"
    preset = CYCLE_PRESETS[normalized["cycle"]]
    for key in ("bar", "boll_period", "boll_std", "rsi_period", "long_rsi_max", "short_rsi_min"):
        normalized[key] = preset[key]

    normalized["bar"] = normalized["bar"] if normalized.get("bar") in _VALID_BARS else preset["bar"]
    normalized["direction"] = (
        normalized["direction"] if normalized.get("direction") in _VALID_DIRECTIONS else "long"
    )
    normalized["add_trigger_type"] = (
        normalized["add_trigger_type"] if normalized.get("add_trigger_type") in _VALID_VALUE_TYPES else "pct"
    )
    normalized["take_profit_type"] = (
        normalized["take_profit_type"] if normalized.get("take_profit_type") in _VALID_VALUE_TYPES else "pct"
    )
    if "price_step_pct" in normalized and "add_trigger_value" not in (params or {}):
        normalized["add_trigger_value"] = normalized["price_step_pct"]
        normalized["add_trigger_type"] = "pct"
    if "take_profit_pct" in normalized and "take_profit_value" not in (params or {}):
        normalized["take_profit_value"] = normalized["take_profit_pct"]
        normalized["take_profit_type"] = "pct"

    for key, (min_val, max_val, caster) in _RANGES.items():
        try:
            value = caster(normalized.get(key, DEFAULT_MARTINGALE_PARAMS[key]))
        except (TypeError, ValueError):
            value = caster(DEFAULT_MARTINGALE_PARAMS[key])
        normalized[key] = max(min_val, min(max_val, value))

    if normalized["add_trigger_type"] == "pct":
        normalized["add_trigger_value"] = max(0.01, min(10.0, normalized["add_trigger_value"]))
    if normalized["take_profit_type"] == "pct":
        normalized["take_profit_value"] = max(0.01, min(5.0, normalized["take_profit_value"]))

    normalized["price_step_pct"] = (
        normalized["add_trigger_value"] if normalized["add_trigger_type"] == "pct" else DEFAULT_MARTINGALE_PARAMS["price_step_pct"]
    )
    normalized["take_profit_pct"] = (
        normalized["take_profit_value"] if normalized["take_profit_type"] == "pct" else DEFAULT_MARTINGALE_PARAMS["take_profit_pct"]
    )
    normalized["size_multiplier"] = 1.0
    normalized["max_levels"] = normalized["max_add_count"] + 1
    min_total = normalized["initial_margin_usdt"] + normalized["add_margin_usdt"] * normalized["max_add_count"]
    normalized["max_position_usdt"] = min_total
    normalized["planned_position_usdt"] = min_total

    risk = normalized.get("risk") if isinstance(normalized.get("risk"), dict) else {}
    normalized["risk"] = {
        "max_concurrent": int(max(1, min(10, risk.get("max_concurrent", 1)))),
        "max_daily_per_symbol": int(max(1, min(50, risk.get("max_daily_per_symbol", 3)))),
        "max_daily_loss_pct": float(max(0.5, min(100.0, risk.get("max_daily_loss_pct", 3.0)))),
    }
    return normalized


def _cycle_from_bar(bar: str | None) -> str:
    if bar == "1D":
        return "long"
    if bar == "4H":
        return "medium"
    return "short"


def martingale_exit_prices(
    avg_price: float,
    direction: str,
    params: dict,
    quantity: float | None = None,
    contract_value: float = 1.0,
) -> tuple[float, float]:
    """返回整体止盈价和硬止损价。"""
    if params.get("take_profit_type") == "usdt" and quantity and quantity > 0 and contract_value > 0:
        take_profit_delta = params.get("take_profit_value", 0.6) / (quantity * contract_value)
    else:
        take_profit_delta = avg_price * params.get("take_profit_pct", 0.6) / 100
    hard_stop_pct = params.get("hard_stop_pct", 8.0) / 100
    if direction == "short":
        return avg_price - take_profit_delta, avg_price * (1 + hard_stop_pct)
    return avg_price + take_profit_delta, avg_price * (1 - hard_stop_pct)


def martingale_next_add_price(avg_price: float, direction: str, level: int, params: dict) -> float:
    """根据当前均价和已成交层数计算下一层触发价。"""
    if params.get("add_trigger_type") == "usdt":
        distance = params.get("add_trigger_value", 1.2)
    else:
        distance = avg_price * params.get("price_step_pct", 1.2) / 100
    if direction == "short":
        return avg_price + distance
    return avg_price - distance


def martingale_pnl_pct(avg_price: float, current_price: float, direction: str) -> float:
    if avg_price <= 0:
        return 0.0
    if direction == "short":
        return (avg_price - current_price) / avg_price * 100
    return (current_price - avg_price) / avg_price * 100


def estimate_liquidation_price(
    avg_price: float,
    direction: str,
    leverage: int,
    maintenance_margin_rate: float = 0.005,
) -> float:
    """按逐仓线性合约粗略估算强平价，实盘以 OKX 返回 liqPx 为准。"""
    if avg_price <= 0:
        return 0.0
    leverage = max(1, int(leverage or 1))
    margin_rate = 1 / leverage
    if direction == "short":
        return max(0.0, avg_price * (1 + margin_rate - maintenance_margin_rate))
    return max(0.0, avg_price * (1 - margin_rate + maintenance_margin_rate))


def _fmt_price(price: float) -> float:
    if price >= 100:
        return round(price, 2)
    if price >= 1:
        return round(price, 4)
    if price >= 0.01:
        return round(price, 6)
    return round(price, 8)


class MartingaleContractStrategy(IStrategy):
    """均值回归马丁格尔合约策略。"""

    @property
    def name(self) -> str:
        return "马丁格尔合约"

    @property
    def direction(self) -> str:
        return "both"

    def check_signal(self, df: pd.DataFrame, params: dict) -> dict | None:
        params = normalize_martingale_params(params)
        if df.empty:
            return None

        min_len = max(params["boll_period"], params["rsi_period"] + 1)
        if len(df) < min_len:
            return None

        closes = df["close"].values.astype(float)
        idx = len(df) - 1
        upper, middle, lower = calc_boll(closes, params["boll_period"], params["boll_std"])
        rsi = calc_rsi(closes, params["rsi_period"])

        if np.isnan(upper[idx]) or np.isnan(lower[idx]) or np.isnan(rsi[idx]):
            return None

        price = float(closes[idx])
        direction_cfg = params["direction"]
        direction = None
        reason = ""

        if direction_cfg in ("long", "both") and price < lower[idx] and rsi[idx] <= params["long_rsi_max"]:
            direction = "long"
            reason = (
                f"马丁格尔均值回归 LONG | close={price:.4f} <= BOLL下轨={lower[idx]:.4f}, "
                f"RSI={rsi[idx]:.1f}"
            )
        elif direction_cfg in ("short", "both") and price > upper[idx] and rsi[idx] >= params["short_rsi_min"]:
            direction = "short"
            reason = (
                f"马丁格尔均值回归 SHORT | close={price:.4f} >= BOLL上轨={upper[idx]:.4f}, "
                f"RSI={rsi[idx]:.1f}"
            )

        if not direction:
            return None

        tp_price, sl_price = martingale_exit_prices(price, direction, params)
        return {
            "direction": direction,
            "price": _fmt_price(price),
            "tp_price": _fmt_price(tp_price),
            "sl_price": _fmt_price(sl_price),
            "confidence": 80,
            "managed_exit": True,
            "martingale": True,
            "exit_rules": params,
            "reason": reason,
        }

    def compute_indicators(self, df: pd.DataFrame, params: dict) -> dict:
        params = normalize_martingale_params(params)
        if df.empty:
            return {}

        closes = df["close"].values.astype(float)
        idx = len(df) - 1
        upper, middle, lower = calc_boll(closes, params["boll_period"], params["boll_std"])
        rsi = calc_rsi(closes, params["rsi_period"])
        price = float(closes[idx])
        return {
            "price": _fmt_price(price),
            "BOLL_upper": _fmt_price(float(upper[idx])) if not np.isnan(upper[idx]) else None,
            "BOLL_middle": _fmt_price(float(middle[idx])) if not np.isnan(middle[idx]) else None,
            "BOLL_lower": _fmt_price(float(lower[idx])) if not np.isnan(lower[idx]) else None,
            "RSI": round(float(rsi[idx]), 2) if not np.isnan(rsi[idx]) else None,
            "cycle": params["cycle"],
            "direction": params["direction"],
            "add_trigger_type": params["add_trigger_type"],
            "add_trigger_value": params["add_trigger_value"],
            "take_profit_type": params["take_profit_type"],
            "take_profit_value": params["take_profit_value"],
            "initial_margin_usdt": params["initial_margin_usdt"],
            "add_margin_usdt": params["add_margin_usdt"],
            "max_add_count": params["max_add_count"],
            "hard_stop_pct": params["hard_stop_pct"],
        }
