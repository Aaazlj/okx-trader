"""
马丁格尔实盘状态管理器。

负责补仓、整体退出和数据库状态恢复。
"""
import json
import time
from typing import Any

from db.database import get_db
from exchange.okx_client import OKXClient
from strategies.martingale_contract import (
    martingale_exit_prices,
    martingale_next_add_price,
    martingale_pnl_pct,
    normalize_martingale_params,
)
from utils.logger import get_logger
from ws import ws_manager

logger = get_logger("MartingaleManager")


class MartingaleManager:
    def __init__(self, client: OKXClient, risk_manager):
        self.client = client
        self.risk_manager = risk_manager

    async def register_entry(
        self,
        *,
        strategy_id: str,
        symbol: str,
        direction: str,
        fill_price: float,
        fill_sz: float,
        leverage: int,
        base_order_usdt: float,
        mgn_mode: str,
        params: dict,
    ) -> None:
        params = normalize_martingale_params(params)
        try:
            ct_val = self.client.get_contract_value(symbol)
        except Exception:
            ct_val = 1.0
        tp_price, sl_price = martingale_exit_prices(fill_price, direction, params, fill_sz, ct_val)
        db = await get_db()
        await db.execute(
            """INSERT OR REPLACE INTO martingale_states
               (strategy_id, symbol, direction, level, avg_price, total_quantity,
                total_order_usdt, base_order_usdt, leverage, mgn_mode, params,
                status, entry_time, updated_at)
               VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, 'open', datetime('now'), datetime('now'))""",
            (
                strategy_id,
                symbol,
                direction,
                fill_price,
                fill_sz,
                params["initial_margin_usdt"],
                params["initial_margin_usdt"],
                leverage,
                mgn_mode,
                json.dumps(params, ensure_ascii=False),
            ),
        )
        await db.execute(
            """INSERT INTO martingale_legs
               (strategy_id, symbol, level, direction, price, quantity, order_usdt, reason)
               VALUES (?, ?, 1, ?, ?, ?, ?, ?)""",
            (strategy_id, symbol, direction, fill_price, fill_sz, params["initial_margin_usdt"], "首单开仓"),
        )
        await db.execute(
            """UPDATE positions
               SET entry_price = ?, quantity = ?, tp_price = ?, sl_price = ?
               WHERE strategy_id = ? AND symbol = ?""",
            (fill_price, fill_sz, tp_price, sl_price, strategy_id, symbol),
        )
        await db.commit()

        logger.info(
            f"📐 马丁格尔状态创建 | {strategy_id} {symbol} {direction} | "
            f"avg={fill_price} qty={fill_sz}"
        )

    async def evaluate(
        self,
        *,
        strategy_id: str,
        symbol: str,
        row,
        okx_pos: dict,
    ) -> None:
        state = await self._load_state(strategy_id, symbol)
        if not state:
            return

        params = normalize_martingale_params(json.loads(state["params"] or "{}"))
        current_price = self._position_price(okx_pos, symbol)
        if current_price <= 0:
            return

        pnl_pct = martingale_pnl_pct(state["avg_price"], current_price, state["direction"])
        if pnl_pct <= -params["hard_stop_pct"]:
            await self._close_state(state, current_price, pnl_pct, "马丁格尔硬止损")
            return
        try:
            ct_val = self.client.get_contract_value(symbol)
        except Exception:
            ct_val = 1.0
        tp_price, _ = martingale_exit_prices(
            state["avg_price"], state["direction"], params, state["total_quantity"], ct_val
        )
        if state["direction"] == "long" and current_price >= tp_price:
            await self._close_state(state, current_price, pnl_pct, "马丁格尔整体止盈")
            return
        if state["direction"] == "short" and current_price <= tp_price:
            await self._close_state(state, current_price, pnl_pct, "马丁格尔整体止盈")
            return

        if state["level"] >= params["max_levels"]:
            return

        next_price = martingale_next_add_price(
            state["avg_price"], state["direction"], state["level"], params
        )
        if state["direction"] == "long" and current_price > next_price:
            return
        if state["direction"] == "short" and current_price < next_price:
            return

        await self._add_leg(state, current_price, params)

    async def cleanup_missing_position(self, strategy_id: str, symbol: str) -> None:
        state = await self._load_state(strategy_id, symbol)
        if not state:
            return
        db = await get_db()
        await db.execute(
            """UPDATE martingale_states
               SET status = 'closed', updated_at = datetime('now')
               WHERE strategy_id = ? AND symbol = ? AND status = 'open'""",
            (strategy_id, symbol),
        )
        await db.execute(
            "DELETE FROM positions WHERE strategy_id = ? AND symbol = ?",
            (strategy_id, symbol),
        )
        await db.commit()
        logger.warning(f"马丁格尔状态已清理（交易所无持仓）| {strategy_id} {symbol}")

    async def _add_leg(self, state, current_price: float, params: dict) -> None:
        remaining_budget = params["max_position_usdt"] - state["total_order_usdt"]
        if remaining_budget <= 0:
            return

        order_usdt = params["add_margin_usdt"]
        order_usdt = min(order_usdt, remaining_budget)
        if order_usdt < 5:
            logger.info(f"马丁格尔补仓跳过，剩余额度过小 | {state['symbol']} {order_usdt:.2f} USDT")
            return

        side = "buy" if state["direction"] == "long" else "sell"
        sz = self.client.calc_contract_size(
            state["symbol"], order_usdt, current_price, state["leverage"]
        )
        order = self.client.place_market_order(state["symbol"], side, str(sz), state["mgn_mode"])
        if not order:
            return

        filled = self.client.wait_order_filled(order.get("ordId", ""), state["symbol"])
        if not filled:
            return

        fill_price = float(filled.get("avgPx", current_price) or current_price)
        fill_sz = float(filled.get("accFillSz", sz) or sz)
        new_qty = state["total_quantity"] + fill_sz
        new_avg = (
            state["avg_price"] * state["total_quantity"] + fill_price * fill_sz
        ) / new_qty
        new_level = state["level"] + 1
        new_total_usdt = state["total_order_usdt"] + order_usdt
        try:
            ct_val = self.client.get_contract_value(state["symbol"])
        except Exception:
            ct_val = 1.0
        tp_price, sl_price = martingale_exit_prices(new_avg, state["direction"], params, new_qty, ct_val)

        db = await get_db()
        await db.execute(
            """UPDATE martingale_states
               SET level = ?, avg_price = ?, total_quantity = ?, total_order_usdt = ?,
                   updated_at = datetime('now')
               WHERE strategy_id = ? AND symbol = ? AND status = 'open'""",
            (
                new_level,
                new_avg,
                new_qty,
                new_total_usdt,
                state["strategy_id"],
                state["symbol"],
            ),
        )
        await db.execute(
            """INSERT INTO martingale_legs
               (strategy_id, symbol, level, direction, price, quantity, order_usdt, reason)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                state["strategy_id"],
                state["symbol"],
                new_level,
                state["direction"],
                fill_price,
                fill_sz,
                order_usdt,
                f"第 {new_level} 层补仓",
            ),
        )
        await db.execute(
            """UPDATE positions
               SET entry_price = ?, quantity = ?, tp_price = ?, sl_price = ?, order_id = ?
               WHERE strategy_id = ? AND symbol = ?""",
            (
                new_avg,
                new_qty,
                tp_price,
                sl_price,
                order.get("ordId", ""),
                state["strategy_id"],
                state["symbol"],
            ),
        )
        await db.commit()

        await ws_manager.broadcast("trade_update", {
            "strategy_id": state["strategy_id"],
            "symbol": state["symbol"],
            "event": "martingale_add",
            "level": new_level,
            "price": round(fill_price, 8),
            "quantity": fill_sz,
            "time": time.strftime("%H:%M:%S"),
        })
        logger.info(
            f"✅ 马丁格尔补仓 | {state['symbol']} L{new_level} | "
            f"price={fill_price} qty={fill_sz} avg={new_avg}"
        )

    async def _close_state(self, state, current_price: float, pnl_pct: float, reason: str) -> None:
        success = self.client.close_position(state["symbol"], state["mgn_mode"])
        if not success:
            return

        ct_val = self.client.get_contract_value(state["symbol"])
        if state["direction"] == "short":
            pnl = (state["avg_price"] - current_price) * state["total_quantity"] * ct_val
        else:
            pnl = (current_price - state["avg_price"]) * state["total_quantity"] * ct_val

        db = await get_db()
        await db.execute(
            """UPDATE trades
               SET exit_price = ?, pnl = ?, pnl_ratio = ?, status = 'closed',
                   exit_time = datetime('now'), reason = reason || ' | ' || ?
               WHERE strategy_id = ? AND symbol = ? AND status = 'open'
               ORDER BY entry_time DESC LIMIT 1""",
            (
                round(current_price, 8),
                round(pnl, 4),
                round(pnl_pct, 2),
                reason,
                state["strategy_id"],
                state["symbol"],
            ),
        )
        await db.execute(
            """UPDATE martingale_states
               SET status = 'closed', updated_at = datetime('now')
               WHERE strategy_id = ? AND symbol = ? AND status = 'open'""",
            (state["strategy_id"], state["symbol"]),
        )
        await db.execute(
            "DELETE FROM positions WHERE strategy_id = ? AND symbol = ?",
            (state["strategy_id"], state["symbol"]),
        )
        await db.commit()

        self.risk_manager.record_close(state["strategy_id"], state["symbol"], pnl_pct)
        await ws_manager.broadcast("trade_update", {
            "strategy_id": state["strategy_id"],
            "symbol": state["symbol"],
            "event": "closed",
            "reason": reason,
            "pnl_pct": round(pnl_pct, 2),
            "time": time.strftime("%H:%M:%S"),
        })
        logger.info(
            f"✅ 马丁格尔平仓 | {state['symbol']} | {reason} | "
            f"pnl={pnl:+.4f} pnl_pct={pnl_pct:+.2f}%"
        )

    async def _load_state(self, strategy_id: str, symbol: str):
        db = await get_db()
        cursor = await db.execute(
            """SELECT * FROM martingale_states
               WHERE strategy_id = ? AND symbol = ? AND status = 'open'""",
            (strategy_id, symbol),
        )
        return await cursor.fetchone()

    def _position_price(self, okx_pos: dict, symbol: str) -> float:
        for key in ("last", "markPx", "idxPx", "avgPx"):
            value = okx_pos.get(key)
            if value not in (None, ""):
                try:
                    price = float(value)
                    if price > 0:
                        return price
                except (TypeError, ValueError):
                    pass
        ticker = self.client.get_ticker(symbol)
        if isinstance(ticker, dict):
            try:
                return float(ticker.get("last") or 0)
            except (TypeError, ValueError):
                return 0.0
        return 0.0
