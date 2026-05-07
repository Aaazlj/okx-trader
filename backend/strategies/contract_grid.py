"""
合约网格策略参数。

v1 只用于配置和回测，不进入实盘下单调度。
"""
from copy import deepcopy
from typing import Any

import pandas as pd

from strategies.base import IStrategy


DEFAULT_CONTRACT_GRID_PARAMS: dict[str, Any] = {
    "cycle": "medium",
    "bar": "1H",
    "grid_mode": "neutral",
    "lower_price": 0.0,
    "upper_price": 0.0,
    "grid_count": 20,
    "total_margin_usdt": 300.0,
    "leverage": 3,
    "mgn_mode": "isolated",
    "stop_lower_price": 0.0,
    "stop_upper_price": 0.0,
    "fee_rate": 0.0005,
    "slippage_pct": 0.02,
    "risk": {
        "max_concurrent": 1,
        "max_daily_per_symbol": 1,
        "max_daily_loss_pct": 3.0,
    },
}

CYCLE_PRESETS: dict[str, dict[str, Any]] = {
    "short": {"label": "短期", "bar": "15m"},
    "medium": {"label": "中期", "bar": "1H"},
    "long": {"label": "长期", "bar": "4H"},
}

_VALID_CYCLES = set(CYCLE_PRESETS)
_VALID_BARS = {"1m", "3m", "5m", "15m", "30m", "1H", "2H", "4H", "6H", "12H", "1D"}
_VALID_GRID_MODES = {"neutral", "long", "short"}
_VALID_MARGIN_MODES = {"cross", "isolated"}

_RANGES = {
    "lower_price": (0.0, 1_000_000_000.0, float),
    "upper_price": (0.0, 1_000_000_000.0, float),
    "grid_count": (2, 200, int),
    "total_margin_usdt": (5.0, 1_000_000.0, float),
    "leverage": (1, 100, int),
    "stop_lower_price": (0.0, 1_000_000_000.0, float),
    "stop_upper_price": (0.0, 1_000_000_000.0, float),
    "fee_rate": (0.0, 0.01, float),
    "slippage_pct": (0.0, 2.0, float),
}


def normalize_contract_grid_params(params: dict | None) -> dict[str, Any]:
    """合并默认参数并限制到回测可用范围。"""
    raw = params or {}
    normalized = deepcopy(DEFAULT_CONTRACT_GRID_PARAMS)
    for key, value in raw.items():
        if key == "risk" and isinstance(value, dict):
            normalized["risk"].update(value)
        else:
            normalized[key] = value

    if raw.get("cycle") in _VALID_CYCLES:
        normalized["cycle"] = raw["cycle"]
    elif raw.get("bar"):
        normalized["cycle"] = _cycle_from_bar(raw.get("bar"))
    elif normalized.get("cycle") not in _VALID_CYCLES:
        normalized["cycle"] = "medium"

    preset = CYCLE_PRESETS[normalized["cycle"]]
    normalized["bar"] = preset["bar"]
    if raw.get("bar") in _VALID_BARS and raw.get("cycle") not in _VALID_CYCLES:
        normalized["bar"] = raw["bar"]

    normalized["grid_mode"] = (
        normalized["grid_mode"] if normalized.get("grid_mode") in _VALID_GRID_MODES else "neutral"
    )
    normalized["mgn_mode"] = (
        normalized["mgn_mode"] if normalized.get("mgn_mode") in _VALID_MARGIN_MODES else "isolated"
    )

    for key, (min_val, max_val, caster) in _RANGES.items():
        try:
            value = caster(normalized.get(key, DEFAULT_CONTRACT_GRID_PARAMS[key]))
        except (TypeError, ValueError):
            value = caster(DEFAULT_CONTRACT_GRID_PARAMS[key])
        normalized[key] = max(min_val, min(max_val, value))

    lower = normalized["lower_price"]
    upper = normalized["upper_price"]
    if lower > 0 and upper > lower:
        if normalized["stop_lower_price"] <= 0 or normalized["stop_lower_price"] >= lower:
            normalized["stop_lower_price"] = lower * 0.98
        if normalized["stop_upper_price"] <= upper:
            normalized["stop_upper_price"] = upper * 1.02
        normalized["grid_spacing_price"] = (upper - lower) / normalized["grid_count"]
        mid = (upper + lower) / 2
        normalized["grid_spacing_pct"] = (
            normalized["grid_spacing_price"] / mid * 100 if mid > 0 else 0.0
        )
    else:
        normalized["stop_lower_price"] = 0.0
        normalized["stop_upper_price"] = 0.0
        normalized["grid_spacing_price"] = 0.0
        normalized["grid_spacing_pct"] = 0.0

    normalized["per_grid_margin_usdt"] = normalized["total_margin_usdt"] / normalized["grid_count"]

    risk = normalized.get("risk") if isinstance(normalized.get("risk"), dict) else {}
    normalized["risk"] = {
        "max_concurrent": int(max(1, min(10, risk.get("max_concurrent", 1)))),
        "max_daily_per_symbol": int(max(1, min(50, risk.get("max_daily_per_symbol", 1)))),
        "max_daily_loss_pct": float(max(0.5, min(100.0, risk.get("max_daily_loss_pct", 3.0)))),
    }
    return normalized


def _cycle_from_bar(bar: str | None) -> str:
    if bar in {"4H", "6H", "12H", "1D"}:
        return "long"
    if bar in {"1H", "2H"}:
        return "medium"
    return "short"


class ContractGridStrategy(IStrategy):
    """配置/回测专用合约网格策略。"""

    @property
    def name(self) -> str:
        return "合约网格"

    @property
    def direction(self) -> str:
        return "both"

    def check_signal(self, df: pd.DataFrame, params: dict) -> dict | None:
        return None

    def compute_indicators(self, df: pd.DataFrame, params: dict) -> dict:
        normalized = normalize_contract_grid_params(params)
        price = None
        if not df.empty and "close" in df.columns:
            price = float(df["close"].iloc[-1])
        return {
            "price": price,
            "cycle": normalized["cycle"],
            "bar": normalized["bar"],
            "grid_mode": normalized["grid_mode"],
            "lower_price": normalized["lower_price"],
            "upper_price": normalized["upper_price"],
            "grid_count": normalized["grid_count"],
            "grid_spacing_pct": round(normalized["grid_spacing_pct"], 4),
            "total_margin_usdt": normalized["total_margin_usdt"],
        }
