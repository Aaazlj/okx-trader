"""
合约网格回测引擎。

纯计算模块，不访问交易所，不写数据库。
"""
from dataclasses import dataclass
from typing import Any

import pandas as pd

from strategies.contract_grid import normalize_contract_grid_params


@dataclass
class GridLeg:
    direction: str
    level_index: int
    entry_time: str
    entry_price: float
    quantity: float
    margin_usdt: float


def run_contract_grid_backtest(
    df: pd.DataFrame,
    *,
    symbol: str,
    params: dict | None,
    leverage: int | None = None,
    fee_rate: float | None = None,
    slippage_pct: float | None = None,
) -> dict[str, Any]:
    params = normalize_contract_grid_params(params)
    if leverage is not None:
        params["leverage"] = max(1, min(100, int(leverage)))
    if fee_rate is not None:
        params["fee_rate"] = max(0.0, min(0.01, float(fee_rate)))
    if slippage_pct is not None:
        params["slippage_pct"] = max(0.0, min(2.0, float(slippage_pct)))

    candles = _prepare_candles(df)
    if len(candles) < 2:
        return _empty_result(symbol, params, f"K线数量不足：需要至少 2 根，当前 {len(candles)} 根", len(candles))
    if params["lower_price"] <= 0 or params["upper_price"] <= params["lower_price"]:
        return _empty_result(symbol, params, "网格价格区间无效，请设置有效的下沿和上沿", len(candles))

    levels = _build_levels(params["lower_price"], params["upper_price"], params["grid_count"])
    grid_margin = params["per_grid_margin_usdt"]
    leverage_value = params["leverage"]
    fee_rate_value = params["fee_rate"]
    slippage_value = params["slippage_pct"]
    total_budget = params["total_margin_usdt"]

    open_legs: dict[tuple[str, int], GridLeg] = {}
    trades: list[dict[str, Any]] = []
    equity_curve: list[dict[str, Any]] = []
    cumulative_pnl = 0.0
    peak_equity = 0.0
    max_drawdown = 0.0
    max_open_legs = 0
    max_used_margin = 0.0
    stopped_reason: str | None = None

    for i in range(len(candles)):
        row = candles.iloc[i]
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        time = _time_str(row["ts"])

        stop_price = None
        if params["stop_lower_price"] > 0 and low <= params["stop_lower_price"]:
            stop_price = params["stop_lower_price"]
            stopped_reason = "跌破网格下沿止损"
        elif params["stop_upper_price"] > 0 and high >= params["stop_upper_price"]:
            stop_price = params["stop_upper_price"]
            stopped_reason = "突破网格上沿止损"

        if stop_price is not None:
            for key, leg in list(open_legs.items()):
                trade = _close_leg(leg, stop_price, time, stopped_reason, fee_rate_value, slippage_value)
                cumulative_pnl += trade["pnl"]
                trades.append(trade)
                del open_legs[key]
            equity_curve.append(_equity_point(time, cumulative_pnl, 0.0))
            break

        # 先处理上一根之前已打开网格的退出，再处理本根新开仓，避免同根开平。
        for key, leg in list(open_legs.items()):
            target = _target_price(leg, levels)
            if leg.direction == "long" and high >= target:
                trade = _close_leg(leg, target, time, "网格止盈", fee_rate_value, slippage_value)
            elif leg.direction == "short" and low <= target:
                trade = _close_leg(leg, target, time, "网格止盈", fee_rate_value, slippage_value)
            else:
                continue
            cumulative_pnl += trade["pnl"]
            trades.append(trade)
            del open_legs[key]

        used_margin = sum(leg.margin_usdt for leg in open_legs.values())
        for direction, level_index in _entry_candidates(params["grid_mode"], levels, low, high):
            key = (direction, level_index)
            if key in open_legs:
                continue
            if used_margin + grid_margin > total_budget + 1e-9:
                continue
            entry_price = levels[level_index]
            fill_price = _apply_slippage(entry_price, direction, "entry", slippage_value)
            if fill_price <= 0:
                continue
            quantity = grid_margin * leverage_value / fill_price
            open_legs[key] = GridLeg(direction, level_index, time, fill_price, quantity, grid_margin)
            used_margin += grid_margin

        used_margin = sum(leg.margin_usdt for leg in open_legs.values())
        max_open_legs = max(max_open_legs, len(open_legs))
        max_used_margin = max(max_used_margin, used_margin)
        unrealized = sum(_raw_pnl(leg, close) for leg in open_legs.values())
        equity = cumulative_pnl + unrealized
        peak_equity = max(peak_equity, equity)
        max_drawdown = min(max_drawdown, equity - peak_equity)
        equity_curve.append(_equity_point(time, cumulative_pnl, unrealized))

    if open_legs:
        last = candles.iloc[-1]
        exit_price = float(last["close"])
        exit_time = _time_str(last["ts"])
        for key, leg in list(open_legs.items()):
            trade = _close_leg(leg, exit_price, exit_time, "回测结束强制平仓", fee_rate_value, slippage_value)
            cumulative_pnl += trade["pnl"]
            trades.append(trade)
            del open_legs[key]

    wins = sum(1 for trade in trades if trade["pnl"] > 0)
    losses = sum(1 for trade in trades if trade["pnl"] < 0)
    total = wins + losses
    return {
        "symbol": symbol,
        "params": params,
        "summary": {
            "total_pnl": round(cumulative_pnl, 4),
            "return_pct": round(cumulative_pnl / max(params["total_margin_usdt"], 1) * 100, 2),
            "max_drawdown": round(max_drawdown, 4),
            "total_trades": len(trades),
            "win_rate": round(wins / total * 100, 1) if total else 0,
            "max_open_legs": max_open_legs,
            "max_used_margin_usdt": round(max_used_margin, 4),
            "bar_count": len(candles),
            "stopped_reason": stopped_reason,
        },
        "equity_curve": equity_curve,
        "trades": trades,
        "message": "未产生完整网格交易，请检查时间范围和参数" if not trades else None,
    }


def _prepare_candles(df: pd.DataFrame) -> pd.DataFrame:
    candles = df.copy()
    if "ts" not in candles.columns:
        candles["ts"] = candles.index
    for col in ["open", "high", "low", "close"]:
        candles[col] = candles[col].astype(float)
    return candles.sort_values("ts").reset_index(drop=True)


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
            "max_open_legs": 0,
            "max_used_margin_usdt": 0,
            "bar_count": bar_count,
            "stopped_reason": None,
        },
        "equity_curve": [],
        "trades": [],
        "message": message,
    }


def _build_levels(lower: float, upper: float, grid_count: int) -> list[float]:
    step = (upper - lower) / grid_count
    return [lower + step * i for i in range(grid_count + 1)]


def _entry_candidates(grid_mode: str, levels: list[float], low: float, high: float) -> list[tuple[str, int]]:
    candidates: list[tuple[str, int]] = []
    if grid_mode in {"neutral", "long"}:
        for i, price in enumerate(levels[:-1]):
            if low <= price <= high:
                candidates.append(("long", i))
    if grid_mode in {"neutral", "short"}:
        for i, price in enumerate(levels[1:], start=1):
            if low <= price <= high:
                candidates.append(("short", i))
    return candidates


def _target_price(leg: GridLeg, levels: list[float]) -> float:
    if leg.direction == "long":
        return levels[min(leg.level_index + 1, len(levels) - 1)]
    return levels[max(leg.level_index - 1, 0)]


def _close_leg(
    leg: GridLeg,
    exit_price: float,
    exit_time: str,
    reason: str,
    fee_rate: float,
    slippage_pct: float,
) -> dict[str, Any]:
    filled_exit = _apply_slippage(exit_price, leg.direction, "exit", slippage_pct)
    gross_pnl = _raw_pnl(leg, filled_exit)
    fee = (leg.entry_price * leg.quantity + filled_exit * leg.quantity) * fee_rate
    pnl = gross_pnl - fee
    return {
        "entry_time": leg.entry_time,
        "exit_time": exit_time,
        "direction": leg.direction,
        "level_index": leg.level_index,
        "entry_price": round(leg.entry_price, 8),
        "exit_price": round(filled_exit, 8),
        "quantity": round(leg.quantity, 8),
        "margin_usdt": round(leg.margin_usdt, 4),
        "pnl": round(pnl, 4),
        "fee": round(fee, 4),
        "reason": reason,
    }


def _raw_pnl(leg: GridLeg, price: float) -> float:
    if leg.direction == "short":
        return (leg.entry_price - price) * leg.quantity
    return (price - leg.entry_price) * leg.quantity


def _apply_slippage(price: float, direction: str, action: str, slippage_pct: float) -> float:
    slip = slippage_pct / 100
    if action == "entry":
        return price * (1 + slip) if direction == "long" else price * (1 - slip)
    return price * (1 - slip) if direction == "long" else price * (1 + slip)


def _equity_point(time: str, realized: float, unrealized: float) -> dict[str, Any]:
    equity = realized + unrealized
    return {
        "time": time,
        "equity": round(equity, 4),
        "realized": round(realized, 4),
        "unrealized": round(unrealized, 4),
    }


def _time_str(value: Any) -> str:
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return str(value)
