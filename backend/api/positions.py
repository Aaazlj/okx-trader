"""
持仓相关 API
"""
import time
import traceback
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter

from db.database import get_db
from exchange.okx_client import OKXClient
from utils.logger import get_logger

logger = get_logger("API.positions")

router = APIRouter(prefix="/api/positions", tags=["positions"])

_client: OKXClient | None = None


def set_client(client: OKXClient):
    global _client
    _client = client


def _parse_open_time(raw: str) -> float:
    """将 open_time 字符串解析为 Unix 时间戳（秒）"""
    if not raw:
        return 0
    try:
        # 格式: 2026-04-29 10:30:00 或 ISO 格式
        raw = raw.replace("T", " ").split("+")[0].split(".")[0]
        dt = datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S")
        return dt.replace(tzinfo=timezone(timedelta(hours=8))).timestamp()
    except Exception:
        return 0


@router.get("")
async def get_positions():
    """获取当前所有持仓（含实时价格、TP/SL 距离、持仓时长）"""
    if _client is None:
        return []

    try:
        # 调用 OKX 获取实际持仓（区分"无持仓"和"API 失败"）
        okx_ok = False
        try:
            okx_positions = _client.get_positions()
            okx_ok = True
        except Exception:
            okx_positions = []

        # 拉取 ticker 获取实时价格
        price_map = {}
        try:
            tickers = _client.get_tickers()
            price_map = {t["inst_id"]: t["last"] for t in tickers if t.get("last")}
        except Exception:
            pass

        # 拉取历史持仓（含精确 PnL/fee）
        pos_history_map: dict[str, dict] = {}
        try:
            for h in _client.get_positions_history():
                sym = h.get("instId", "")
                if sym and sym not in pos_history_map:
                    pos_history_map[sym] = h
        except Exception:
            pass

        # 从本地 DB 获取所有持仓记录
        db = await get_db()
        cursor = await db.execute(
            "SELECT symbol, tp_price, sl_price, open_time, strategy_id FROM positions"
        )
        db_rows = await cursor.fetchall()
        db_map = {row["symbol"]: dict(row) for row in db_rows}

        # 清理已平仓的 DB 记录 + 同步交易历史（仅当 OKX 正常返回时才清理，避免 API 故障误删）
        okx_symbols = {p.get("instId", "") for p in okx_positions}
        stale_symbols = [s for s in db_map if s not in okx_symbols]
        if stale_symbols and okx_ok:
            # 批量拉取成交明细（按 symbol 拉取，避免一次拉太多）
            fills_cache: dict[str, list] = {}
            for sym in stale_symbols:
                try:
                    fills_cache[sym] = _client.get_fills(inst_id=sym)
                except Exception:
                    fills_cache[sym] = []

            for sym in stale_symbols:
                sid = db_map[sym].get("strategy_id", "")
                logger.info(f"🧹 同步清理已平仓记录 | {sym} | strategy={sid}")

                # 从 positions 表读取 peak/trough（删除前）
                pos_peak = db_map[sym].get("peak_pnl") or 0
                pos_trough = db_map[sym].get("trough_pnl") or 0

                # 同步更新对应的 open trade 为 closed
                cursor = await db.execute(
                    "SELECT id, entry_price, quantity, leverage, direction, entry_time FROM trades WHERE symbol = ? AND status = 'open' ORDER BY entry_time DESC LIMIT 1",
                    (sym,),
                )
                trade_row = await cursor.fetchone()
                if trade_row:
                    entry = trade_row["entry_price"] or 0
                    qty = trade_row["quantity"] or 0
                    direction = trade_row["direction"]

                    # 优先用 positions_history（含 realizedPnl、fee、closeAvgPx、pnlRatio）
                    ph = pos_history_map.get(sym)
                    if ph:
                        pnl = float(ph.get("realizedPnl", 0) or 0)
                        fee = abs(float(ph.get("fee", 0) or 0))
                        pnl_ratio = round(float(ph.get("pnlRatio", 0) or 0) * 100, 2)
                        exit_px = float(ph.get("closeAvgPx", 0) or 0) or price_map.get(sym, entry)
                        close_ts = ph.get("uTime", "")
                        if close_ts:
                            exit_time = time.strftime(
                                "%Y-%m-%d %H:%M:%S",
                                time.localtime(int(close_ts) / 1000),
                            )
                        else:
                            exit_time = time.strftime("%Y-%m-%d %H:%M:%S")
                    else:
                        # fallback: 用 fills
                        pnl_ratio = None
                        all_fills = fills_cache.get(sym, [])
                        close_fills = [f for f in all_fills if f.get("subType") == "2"]
                        if all_fills:
                            total_fill_pnl = sum(float(f.get("fillPnl", 0) or 0) for f in all_fills)
                            fee = sum(abs(float(f.get("fee", 0) or 0)) for f in all_fills)
                            ref_fill = close_fills[0] if close_fills else all_fills[0]
                            exit_px = float(ref_fill.get("fillPx", 0) or 0)
                            fill_ts = ref_fill.get("ts", "")
                            if fill_ts:
                                exit_time = time.strftime(
                                    "%Y-%m-%d %H:%M:%S",
                                    time.localtime(int(fill_ts) / 1000),
                                )
                            else:
                                exit_time = time.strftime("%Y-%m-%d %H:%M:%S")
                            pnl = total_fill_pnl
                        else:
                            exit_px = price_map.get(sym, entry)
                            fee = 0
                            exit_time = time.strftime("%Y-%m-%d %H:%M:%S")
                            try:
                                ct_val = _client.get_contract_value(sym)
                            except Exception:
                                ct_val = 0.01
                            if direction == "long":
                                pnl = (exit_px - entry) * qty * ct_val
                            else:
                                pnl = (entry - exit_px) * qty * ct_val

                    await db.execute(
                        """UPDATE trades SET status = 'closed', exit_price = ?,
                           pnl = ?, fee = ?, exit_time = ?,
                           peak_pnl = ?, trough_pnl = ?, pnl_ratio = ?,
                           reason = reason || ' | OKX平仓同步'
                           WHERE id = ?""",
                        (round(exit_px, 4), round(pnl, 4), round(fee, 6), exit_time,
                         round(pos_peak, 4), round(pos_trough, 4), pnl_ratio, trade_row["id"]),
                    )
                    logger.info(
                        f"📝 同步交易记录 | {sym} | 入场:{entry} 出场:{exit_px} "
                        f"PnL:{pnl:.4f} 手续费:{fee:.6f} {'(history)' if ph else '(fills)'}"
                    )

            placeholders = ",".join("?" for _ in stale_symbols)
            await db.execute(
                f"DELETE FROM positions WHERE symbol IN ({placeholders})",
                stale_symbols,
            )
            await db.commit()

        # 清理历史遗留：trades 为 open 但对应 symbol 不在 DB positions 中（已平仓但未同步）
        if okx_ok:
            cursor = await db.execute(
                "SELECT symbol FROM trades WHERE status = 'open'"
            )
            open_trades = await cursor.fetchall()
            orphan_symbols = list({r["symbol"] for r in open_trades} - set(db_map.keys()))
            if orphan_symbols:
                # 拉取这些 symbol 的成交明细
                orphan_fills: dict[str, list] = {}
                for sym in orphan_symbols:
                    try:
                        orphan_fills[sym] = _client.get_fills(inst_id=sym)
                    except Exception:
                        orphan_fills[sym] = []

                for sym in orphan_symbols:
                    cursor = await db.execute(
                        "SELECT id, entry_price, quantity, leverage, direction FROM trades WHERE symbol = ? AND status = 'open' ORDER BY entry_time DESC LIMIT 1",
                        (sym,),
                    )
                    row = await cursor.fetchone()
                    if not row:
                        continue

                    entry = row["entry_price"] or 0
                    qty = row["quantity"] or 0
                    direction = row["direction"]

                    # 优先用 positions_history
                    ph = pos_history_map.get(sym)
                    if ph:
                        pnl = float(ph.get("realizedPnl", 0) or 0)
                        fee = abs(float(ph.get("fee", 0) or 0))
                        pnl_ratio = round(float(ph.get("pnlRatio", 0) or 0) * 100, 2)
                        exit_px = float(ph.get("closeAvgPx", 0) or 0) or price_map.get(sym, 0)
                        close_ts = ph.get("uTime", "")
                        if close_ts:
                            exit_time = time.strftime(
                                "%Y-%m-%d %H:%M:%S",
                                time.localtime(int(close_ts) / 1000),
                            )
                        else:
                            exit_time = time.strftime("%Y-%m-%d %H:%M:%S")
                    else:
                        # fallback: fills
                        pnl_ratio = None
                        all_fills = orphan_fills.get(sym, [])
                        close_fills = [f for f in all_fills if f.get("subType") == "2"]
                        if all_fills:
                            total_fill_pnl = sum(float(f.get("fillPnl", 0) or 0) for f in all_fills)
                            fee = sum(abs(float(f.get("fee", 0) or 0)) for f in all_fills)
                            ref_fill = close_fills[0] if close_fills else all_fills[0]
                            exit_px = float(ref_fill.get("fillPx", 0) or 0)
                            fill_ts = ref_fill.get("ts", "")
                            if fill_ts:
                                exit_time = time.strftime(
                                    "%Y-%m-%d %H:%M:%S",
                                    time.localtime(int(fill_ts) / 1000),
                                )
                            else:
                                exit_time = time.strftime("%Y-%m-%d %H:%M:%S")
                            pnl = total_fill_pnl
                        else:
                            exit_px = price_map.get(sym, 0)
                            if exit_px <= 0:
                                continue
                            fee = 0
                            exit_time = time.strftime("%Y-%m-%d %H:%M:%S")
                            try:
                                ct_val = _client.get_contract_value(sym)
                            except Exception:
                                ct_val = 0.01
                            if direction == "long":
                                pnl = (exit_px - entry) * qty * ct_val
                            else:
                                pnl = (entry - exit_px) * qty * ct_val

                    await db.execute(
                        """UPDATE trades SET status = 'closed', exit_price = ?,
                           pnl = ?, fee = ?, exit_time = ?, pnl_ratio = ?,
                           reason = reason || ' | 历史同步'
                           WHERE id = ?""",
                        (round(exit_px, 4), round(pnl, 4), round(fee, 6), exit_time, pnl_ratio, row["id"]),
                    )
                    logger.info(
                        f"📝 历史同步 | {sym} | 入场:{entry} 出场:{exit_px} "
                        f"PnL:{pnl:.4f} 手续费:{fee:.6f} {'(history)' if ph else '(fills)'}"
                    )
                await db.commit()

        # 补填历史交易的手续费和盈亏（用 positions_history 的 realizedPnl）
        if okx_ok and pos_history_map:
            cursor = await db.execute(
                "SELECT id, symbol FROM trades WHERE status = 'closed' AND (fee IS NULL OR pnl_ratio IS NULL) LIMIT 30"
            )
            fix_trades = await cursor.fetchall()
            fixed = 0
            for trade in fix_trades:
                ph = pos_history_map.get(trade["symbol"])
                if ph:
                    realized = float(ph.get("realizedPnl", 0) or 0)
                    fee = abs(float(ph.get("fee", 0) or 0))
                    pnl_ratio = round(float(ph.get("pnlRatio", 0) or 0) * 100, 2)
                    await db.execute(
                        "UPDATE trades SET pnl = ?, fee = ?, pnl_ratio = ? WHERE id = ?",
                        (round(realized, 4), round(fee, 6), pnl_ratio, trade["id"]),
                    )
                    fixed += 1
            if fixed > 0:
                await db.commit()
                logger.info(f"📝 补填盈亏(含费) | 更新 {fixed} 条记录")

        if not okx_positions:
            return []

        now = time.time()
        result = []
        for p in okx_positions:
            symbol = p.get("instId", "")
            entry = float(p.get("avgPx", 0) or 0)
            current = price_map.get(symbol, entry)

            # TP/SL 距离百分比
            db_info = db_map.get(symbol, {})
            tp = db_info.get("tp_price") or 0
            sl = db_info.get("sl_price") or 0
            tp_dist = round((tp - current) / current * 100, 2) if tp > 0 else None
            sl_dist = round((sl - current) / current * 100, 2) if sl > 0 else None

            # 持仓时长
            open_ts = _parse_open_time(db_info.get("open_time", ""))
            holding_sec = int(now - open_ts) if open_ts > 0 else 0

            result.append({
                "symbol": symbol,
                "direction": "long" if float(p.get("pos", 0)) > 0 else "short",
                "quantity": abs(float(p.get("pos", 0))),
                "entry_price": entry,
                "current_price": current,
                "unrealized_pnl": float(p.get("upl", 0) or 0),
                "leverage": int(p.get("lever", 0) or 0),
                "liquidation_price": float(p.get("liqPx", 0) or 0) or None,
                "margin_mode": p.get("mgnMode", ""),
                "tp_price": tp or None,
                "sl_price": sl or None,
                "tp_distance_pct": tp_dist,
                "sl_distance_pct": sl_dist,
                "holding_seconds": holding_sec,
                "strategy_id": db_info.get("strategy_id"),
            })
        return result
    except Exception as e:
        logger.error(f"获取持仓失败: {e}\n{traceback.format_exc()}")
        return []
