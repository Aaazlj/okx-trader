"""
动态仓位计算器
支持 Fixed Fractional / ATR-based / Kelly Criterion 三种 sizing 方法。
从 position-sizer skill 提取，适配策略执行管线。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from utils.logger import get_logger

logger = get_logger("PositionSizer")


@dataclass
class SizingInput:
    """仓位计算输入参数"""
    account_size: float          # 账户总权益 (USDT)
    entry_price: float           # 入场价格
    stop_price: float | None = None
    risk_pct: float = 1.0        # 单笔风险百分比
    atr: float | None = None     # 当前 ATR 值
    atr_multiplier: float = 2.0  # ATR 止损倍数
    win_rate: float | None = None
    avg_win: float | None = None
    avg_loss: float | None = None
    max_position_pct: float = 10.0  # 单仓位最大占比
    side: str = "long"
    leverage: int = 10
    mmr: float = 0.004           # OKX 维持保证金率 (Tier 1)
    fee_rate: float = 0.0005     # Taker 手续费率
    contract_value: float = 0.01 # OKX ctVal (如 BTC-USDT-SWAP=0.01)


def calculate_fixed_fractional(inp: SizingInput) -> dict:
    """固定风险百分比仓位计算。

    dollar_risk = account_size * risk_pct / 100
    risk_per_unit = abs(entry - stop)
    contracts = int(dollar_risk / (risk_per_unit * contract_value))
    """
    if inp.stop_price is None:
        return {"method": "fixed_fractional", "quantity": 0, "error": "stop_price required"}

    risk_per_unit = abs(inp.entry_price - inp.stop_price)
    if risk_per_unit <= 0:
        return {"method": "fixed_fractional", "quantity": 0, "error": "stop equals entry"}

    dollar_risk = inp.account_size * inp.risk_pct / 100
    risk_per_contract = risk_per_unit * inp.contract_value
    if risk_per_contract <= 0:
        return {"method": "fixed_fractional", "quantity": 0, "error": "risk_per_contract=0"}

    contracts = int(dollar_risk / risk_per_contract)
    return {
        "method": "fixed_fractional",
        "quantity": contracts,
        "dollar_risk": round(dollar_risk, 2),
        "risk_per_unit": round(risk_per_unit, 4),
        "stop_price": inp.stop_price,
    }


def calculate_atr_based(inp: SizingInput) -> dict:
    """ATR 止损仓位计算。stop_distance = ATR * multiplier。"""
    if inp.atr is None or inp.atr <= 0:
        return {"method": "atr_based", "quantity": 0, "error": "atr required"}

    stop_distance = inp.atr * inp.atr_multiplier
    if inp.side == "long":
        stop_price = inp.entry_price - stop_distance
    else:
        stop_price = inp.entry_price + stop_distance

    dollar_risk = inp.account_size * inp.risk_pct / 100
    risk_per_contract = stop_distance * inp.contract_value
    if risk_per_contract <= 0:
        return {"method": "atr_based", "quantity": 0, "error": "risk_per_contract=0"}

    contracts = int(dollar_risk / risk_per_contract)
    return {
        "method": "atr_based",
        "quantity": contracts,
        "stop_price": round(stop_price, 8),
        "stop_distance": round(stop_distance, 8),
        "dollar_risk": round(dollar_risk, 2),
        "atr": inp.atr,
        "atr_multiplier": inp.atr_multiplier,
    }


def calculate_kelly(inp: SizingInput) -> dict:
    """Kelly Criterion 仓位计算（half-kelly + 杠杆调整）。

    kelly_pct = W - (1-W)/R
    half_kelly = kelly / 2
    adjusted = half_kelly / leverage
    """
    if inp.win_rate is None or inp.avg_win is None or inp.avg_loss is None:
        return {"method": "kelly", "quantity": 0, "error": "win_rate/avg_win/avg_loss required"}
    if inp.avg_loss <= 0:
        return {"method": "kelly", "quantity": 0, "error": "avg_loss must be positive"}

    w = inp.win_rate
    r = inp.avg_win / inp.avg_loss
    kelly_pct = max(0.0, w - (1 - w) / r) * 100
    half_kelly_pct = kelly_pct / 2

    adjusted_pct = half_kelly_pct
    if inp.leverage > 1:
        adjusted_pct = half_kelly_pct / inp.leverage

    budget = inp.account_size * adjusted_pct / 100

    # 有止损时按风险精确计算张数
    if inp.stop_price and inp.stop_price != inp.entry_price:
        risk_per_unit = abs(inp.entry_price - inp.stop_price)
        risk_per_contract = risk_per_unit * inp.contract_value
        if risk_per_contract > 0:
            contracts = int(budget / risk_per_contract)
        else:
            contracts = int(budget / (inp.entry_price * inp.contract_value))
    else:
        contracts = int(budget / (inp.entry_price * inp.contract_value)) if inp.contract_value > 0 else 0

    return {
        "method": "kelly",
        "quantity": max(0, contracts),
        "kelly_pct": round(kelly_pct, 2),
        "half_kelly_pct": round(half_kelly_pct, 2),
        "adjusted_pct": round(adjusted_pct, 2),
        "budget": round(budget, 2),
    }


def calculate_liquidation_price(
    entry: float, contracts: int, contract_value: float,
    leverage: int, side: str, mmr: float = 0.004, fee_rate: float = 0.0005,
) -> float | None:
    """OKX 逐仓强平价估算。

    Long:  liq = (margin - ctVal*N*entry) / (ctVal*N*(mmr+fee-1))
    Short: liq = (margin + ctVal*N*entry) / (ctVal*N*(mmr+fee+1))
    """
    n = abs(contracts)
    if n == 0 or contract_value <= 0 or leverage <= 0:
        return None

    denom_base = contract_value * n
    notional = denom_base * entry
    margin = notional / leverage

    if side == "long":
        denom = denom_base * (mmr + fee_rate - 1)
        if denom == 0:
            return None
        liq = (margin - denom_base * entry) / denom
    else:
        denom = denom_base * (mmr + fee_rate + 1)
        if denom == 0:
            return None
        liq = (margin + denom_base * entry) / denom

    return max(0.0, liq)


def apply_max_position_constraint(
    quantity: int, entry_price: float, contract_value: float,
    account_size: float, max_position_pct: float,
) -> int:
    """单仓位占比上限约束。"""
    max_value = account_size * max_position_pct / 100
    max_by_pos = int(max_value / (entry_price * contract_value)) if entry_price > 0 and contract_value > 0 else quantity
    return max(0, min(quantity, max_by_pos))


def calculate_order_size(
    sizing_method: str,
    inp: SizingInput,
) -> dict:
    """统一入口：根据 sizing_method 计算最终合约张数。

    Returns:
        {"quantity": int, "method": str, "details": dict}
    """
    if sizing_method == "fixed_fractional":
        result = calculate_fixed_fractional(inp)
    elif sizing_method == "atr_based":
        result = calculate_atr_based(inp)
    elif sizing_method == "kelly":
        result = calculate_kelly(inp)
    else:
        # "fixed" — 不动态计算，返回 0（由调用方使用原 order_amount）
        return {"quantity": 0, "method": "fixed", "details": {}}

    if result.get("error"):
        logger.warning(f"sizing {sizing_method} 失败: {result['error']}，回退固定仓位")
        return {"quantity": 0, "method": sizing_method, "details": result}

    qty = result["quantity"]

    # 约束：单仓位最大占比
    if inp.max_position_pct and inp.max_position_pct > 0:
        qty = apply_max_position_constraint(
            qty, inp.entry_price, inp.contract_value,
            inp.account_size, inp.max_position_pct,
        )

    result["quantity"] = max(0, qty)
    return {"quantity": result["quantity"], "method": sizing_method, "details": result}
