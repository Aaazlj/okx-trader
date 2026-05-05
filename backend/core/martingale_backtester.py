"""
马丁格尔回测引擎。

纯计算模块，不访问交易所，不写数据库。
"""
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from strategies.martingale_contract import (
    estimate_liquidation_price,
    martingale_exit_prices,
    martingale_next_add_price,
    martingale_pnl_pct,
    normalize_martingale_params,
)


@dataclass
class BacktestLeg:
    level: int
    time: str
    price: float
    quantity: float
    margin_usdt: float
    reason: str


@dataclass
class BacktestPosition:
    symbol: str
    direction: str
    entry_time: str
    leverage: int
    avg_price: float
    quantity: float
    total_margin_usdt: float
    level: int
    legs: list[BacktestLeg] = field(default_factory=list)


def run_martingale_backtest(
    df: pd.DataFrame,
    *,
    symbol: str,
    params: dict | None,
    leverage: int,
    base_order_usdt: float,
    fee_rate: float,
    slippage_pct: float,
) -> dict[str, Any]:
    params = normalize_martingale_params(params)
    fee_rate = max(0.0, float(fee_rate))
    slippage_pct = max(0.0, float(slippage_pct))
    leverage = max(1, int(leverage))
    base_order_usdt = max(0.0, float(params.get("initial_margin_usdt", base_order_usdt)))

    candles = _prepare_candles(df)
    required_count = 2
    if len(candles) < required_count:
        return _empty_result(
            symbol,
            params,
            f"K线数量不足：需要至少 {required_count} 根，当前 {len(candles)} 根",
            len(candles),
        )

    position: BacktestPosition | None = None
    trades: list[dict[str, Any]] = []
    equity_curve: list[dict[str, Any]] = []
    cumulative_pnl = 0.0
    peak_equity = 0.0
    max_drawdown = 0.0
    cooldown_until = -1
    max_level_seen = 0
    max_margin_seen = 0.0

    for i in range(len(candles)):
        row = candles.iloc[i]
        price = float(row["close"])
        time = _time_str(row["ts"])
        closed_this_bar = False

        if position:
            close_trade = _evaluate_exit(position, row, params, fee_rate, slippage_pct)
            if close_trade:
                cumulative_pnl += close_trade["pnl"]
                trades.append(close_trade)
                position = None
                cooldown_until = i + params["cooldown_bars"]
                closed_this_bar = True
            else:
                _maybe_add_leg(
                    position,
                    row,
                    params,
                    leverage,
                    base_order_usdt,
                    slippage_pct,
                )
                max_level_seen = max(max_level_seen, position.level)
                max_margin_seen = max(max_margin_seen, position.total_margin_usdt)

        if not position and not closed_this_bar and i >= cooldown_until:
            position = _open_initial_position(
                symbol,
                row,
                params,
                leverage,
                base_order_usdt,
                slippage_pct,
            )
            if position:
                max_level_seen = max(max_level_seen, position.level)
                max_margin_seen = max(max_margin_seen, position.total_margin_usdt)

        unrealized = 0.0
        if position:
            unrealized = _raw_pnl(position, price)
        equity = cumulative_pnl + unrealized
        peak_equity = max(peak_equity, equity)
        max_drawdown = min(max_drawdown, equity - peak_equity)
        equity_curve.append({
            "time": time,
            "equity": round(equity, 4),
            "realized": round(cumulative_pnl, 4),
            "unrealized": round(unrealized, 4),
        })

    if position:
        last = candles.iloc[-1]
        close_trade = _close_position(
            position,
            float(last["close"]),
            _time_str(last["ts"]),
            "回测结束强制平仓",
            fee_rate,
            slippage_pct,
        )
        cumulative_pnl += close_trade["pnl"]
        trades.append(close_trade)

    wins = sum(1 for trade in trades if trade["pnl"] > 0)
    losses = sum(1 for trade in trades if trade["pnl"] < 0)
    total = wins + losses
    initial_margin = max(params.get("initial_margin_usdt", base_order_usdt), 1)

    return {
        "symbol": symbol,
        "params": params,
        "summary": {
            "total_pnl": round(cumulative_pnl, 4),
            "return_pct": round(cumulative_pnl / initial_margin * 100, 2),
            "max_drawdown": round(max_drawdown, 4),
            "total_trades": len(trades),
            "win_rate": round(wins / total * 100, 1) if total else 0,
            "max_level": max_level_seen,
            "max_add_count": max(0, max_level_seen - 1),
            "max_position_usdt": round(max_margin_seen, 4),
            "bar_count": len(candles),
        },
        "equity_curve": equity_curve,
        "trades": trades,
        "message": "未产生完整交易，请检查时间范围和参数" if not trades else None,
    }


def _prepare_candles(df: pd.DataFrame) -> pd.DataFrame:
    candles = df.copy()
    if "ts" not in candles.columns:
        candles["ts"] = candles.index
    for col in ["open", "high", "low", "close"]:
        candles[col] = candles[col].astype(float)
    candles = candles.sort_values("ts").reset_index(drop=True)
    return candles


def _empty_result(symbol: str, params: dict, message: str, bar_count: int = 0) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "params": params,
        "summary": {
            "total_pnl": 0,
            "return_pct": 0,
            "max_drawdown": 0,
            "total_trades": 0,
            "win_rate": 0,
            "max_level": 0,
            "max_add_count": 0,
            "max_position_usdt": 0,
            "bar_count": bar_count,
        },
        "equity_curve": [],
        "trades": [],
        "message": message,
    }


def _open_initial_position(
    symbol: str,
    row: pd.Series,
    params: dict,
    leverage: int,
    base_order_usdt: float,
    slippage_pct: float,
) -> BacktestPosition | None:
    direction = params["direction"] if params.get("direction") in ("long", "short") else "long"
    price = float(row["close"])
    fill_price = _apply_slippage(price, direction, "entry", slippage_pct)
    margin = min(base_order_usdt, params["max_position_usdt"])
    if margin <= 0 or fill_price <= 0:
        return None

    quantity = margin * leverage / fill_price
    position = BacktestPosition(
        symbol=symbol,
        direction=direction,
        entry_time=_time_str(row["ts"]),
        leverage=leverage,
        avg_price=fill_price,
        quantity=quantity,
        total_margin_usdt=margin,
        level=1,
    )
    position.legs.append(BacktestLeg(1, _time_str(row["ts"]), fill_price, quantity, margin, "回测首单"))
    return position


def _maybe_add_leg(
    position: BacktestPosition,
    row: pd.Series,
    params: dict,
    leverage: int,
    base_order_usdt: float,
    slippage_pct: float,
) -> None:
    if position.level >= params["max_levels"]:
        return

    high = float(row["high"])
    low = float(row["low"])
    trigger = martingale_next_add_price(position.avg_price, position.direction, position.level, params)
    if position.direction == "long" and low > trigger:
        return
    if position.direction == "short" and high < trigger:
        return

    remaining_budget = params["max_position_usdt"] - position.total_margin_usdt
    if remaining_budget <= 0:
        return

    requested_margin = params["add_margin_usdt"]
    margin = min(requested_margin, remaining_budget)
    if margin <= 0:
        return

    fill_price = _apply_slippage(trigger, position.direction, "entry", slippage_pct)
    quantity = margin * leverage / fill_price
    new_qty = position.quantity + quantity
    position.avg_price = (position.avg_price * position.quantity + fill_price * quantity) / new_qty
    position.quantity = new_qty
    position.total_margin_usdt += margin
    position.level += 1
    position.legs.append(
        BacktestLeg(
            position.level,
            _time_str(row["ts"]),
            fill_price,
            quantity,
            margin,
            f"第 {position.level} 层补仓",
        )
    )


def _evaluate_exit(
    position: BacktestPosition,
    row: pd.Series,
    params: dict,
    fee_rate: float,
    slippage_pct: float,
) -> dict[str, Any] | None:
    high = float(row["high"])
    low = float(row["low"])
    tp_price, sl_price = martingale_exit_prices(
        position.avg_price, position.direction, params, position.quantity
    )
    time = _time_str(row["ts"])

    if position.direction == "long":
        if low <= sl_price:
            return _close_position(position, sl_price, time, "硬止损", fee_rate, slippage_pct)
        if high >= tp_price:
            return _close_position(position, tp_price, time, "整体止盈", fee_rate, slippage_pct)
    else:
        if high >= sl_price:
            return _close_position(position, sl_price, time, "硬止损", fee_rate, slippage_pct)
        if low <= tp_price:
            return _close_position(position, tp_price, time, "整体止盈", fee_rate, slippage_pct)
    return None


def _close_position(
    position: BacktestPosition,
    exit_price: float,
    exit_time: str,
    reason: str,
    fee_rate: float,
    slippage_pct: float,
) -> dict[str, Any]:
    filled_exit = _apply_slippage(exit_price, position.direction, "exit", slippage_pct)
    gross_pnl = _raw_pnl(position, filled_exit)
    leveraged_entry_notional = sum(leg.price * leg.quantity for leg in position.legs)
    exit_notional = filled_exit * position.quantity
    fee = (leveraged_entry_notional + exit_notional) * fee_rate
    pnl = gross_pnl - fee
    return {
        "entry_time": position.entry_time,
        "exit_time": exit_time,
        "symbol": position.symbol,
        "direction": position.direction,
        "entry_price": round(position.legs[0].price, 8),
        "avg_price": round(position.avg_price, 8),
        "exit_price": round(filled_exit, 8),
        "liquidation_price": round(estimate_liquidation_price(position.avg_price, position.direction, position.leverage), 8),
        "quantity": round(position.quantity, 8),
        "levels": position.level,
        "margin_usdt": round(position.total_margin_usdt, 4),
        "pnl": round(pnl, 4),
        "pnl_pct": round(martingale_pnl_pct(position.avg_price, filled_exit, position.direction), 2),
        "fee": round(fee, 4),
        "reason": reason,
        "legs": [
            {
                "level": leg.level,
                "time": leg.time,
                "price": round(leg.price, 8),
                "quantity": round(leg.quantity, 8),
                "margin_usdt": round(leg.margin_usdt, 4),
                "reason": leg.reason,
            }
            for leg in position.legs
        ],
    }


def _raw_pnl(position: BacktestPosition, price: float) -> float:
    if position.direction == "short":
        return (position.avg_price - price) * position.quantity
    return (price - position.avg_price) * position.quantity


def _apply_slippage(price: float, direction: str, action: str, slippage_pct: float) -> float:
    slip = slippage_pct / 100
    if action == "entry":
        return price * (1 + slip) if direction == "long" else price * (1 - slip)
    return price * (1 - slip) if direction == "long" else price * (1 + slip)


def _time_str(value: Any) -> str:
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return str(value)
