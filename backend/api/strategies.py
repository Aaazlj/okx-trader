"""
策略管理 API — CRUD + 启停 + 交易对配置
"""
import json
from fastapi import APIRouter

from db.database import get_db
from models import StrategyResponse, StrategyUpdate

router = APIRouter(prefix="/api/strategies", tags=["strategies"])

# 策略调度器引用（在 main.py 启动时注入）
_runner = None
_client = None


def set_runner(runner):
    global _runner
    _runner = runner


def set_client(client):
    global _client
    _client = client


def _row_to_strategy(row) -> dict:
    """将数据库行转换为策略响应"""
    return {
        "id": row["id"],
        "name": row["name"],
        "strategy_type": row["strategy_type"],
        "is_active": bool(row["is_active"]),
        "symbols": json.loads(row["symbols"]),
        "decision_mode": row["decision_mode"],
        "leverage": row["leverage"],
        "order_amount_usdt": row["order_amount_usdt"],
        "mgn_mode": row["mgn_mode"],
        "poll_interval": row["poll_interval"],
        "params": json.loads(row["params"]),
        "ai_min_confidence": row["ai_min_confidence"],
        "ai_prompt": row["ai_prompt"],
    }


@router.get("", response_model=list[StrategyResponse])
async def list_strategies():
    """获取所有策略"""
    db = await get_db()
    cursor = await db.execute("SELECT * FROM strategies ORDER BY created_at")
    rows = await cursor.fetchall()
    return [_row_to_strategy(row) for row in rows]


@router.get("/stats")
async def get_strategies_stats():
    """批量获取所有策略的聚合统计（PnL、胜率、交易数、持仓数）"""
    db = await get_db()

    # 1. 交易统计：按 strategy_id 聚合
    cursor = await db.execute(
        """SELECT strategy_id,
                  COALESCE(SUM(pnl), 0) AS total_pnl,
                  COUNT(*) AS total_trades,
                  SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS wins,
                  SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) AS losses
           FROM trades GROUP BY strategy_id"""
    )
    trade_rows = await cursor.fetchall()

    # 2. 活跃持仓数：按 strategy_id 计数
    cursor = await db.execute(
        "SELECT strategy_id, COUNT(*) AS pos_count FROM positions GROUP BY strategy_id"
    )
    pos_rows = await cursor.fetchall()

    # 组装结果
    stats = {}
    for row in trade_rows:
        sid = row["strategy_id"]
        total = row["wins"] + row["losses"]
        stats[sid] = {
            "total_pnl": round(row["total_pnl"], 4),
            "total_trades": row["total_trades"],
            "win_rate": round(row["wins"] / total * 100, 1) if total > 0 else 0,
            "active_positions": 0,
        }
    for row in pos_rows:
        sid = row["strategy_id"]
        if sid not in stats:
            stats[sid] = {
                "total_pnl": 0, "total_trades": 0, "win_rate": 0, "active_positions": 0,
            }
        stats[sid]["active_positions"] = row["pos_count"]

    return stats


@router.get("/{strategy_id}", response_model=StrategyResponse)
async def get_strategy(strategy_id: str):
    """获取单个策略详情"""
    db = await get_db()
    cursor = await db.execute("SELECT * FROM strategies WHERE id = ?", (strategy_id,))
    row = await cursor.fetchone()
    if not row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="策略不存在")
    return _row_to_strategy(row)


@router.patch("/{strategy_id}", response_model=StrategyResponse)
async def update_strategy(strategy_id: str, update: StrategyUpdate):
    """更新策略配置"""
    db = await get_db()

    # 构建动态 SET 子句
    updates = {}
    if update.name is not None:
        updates["name"] = update.name
    if update.symbols is not None:
        updates["symbols"] = json.dumps(update.symbols)
    if update.decision_mode is not None:
        updates["decision_mode"] = update.decision_mode
    if update.leverage is not None:
        updates["leverage"] = update.leverage
    if update.order_amount_usdt is not None:
        updates["order_amount_usdt"] = update.order_amount_usdt
    if update.mgn_mode is not None:
        updates["mgn_mode"] = update.mgn_mode
    if update.poll_interval is not None:
        updates["poll_interval"] = update.poll_interval
    if update.params is not None:
        updates["params"] = json.dumps(update.params)
    if update.ai_min_confidence is not None:
        updates["ai_min_confidence"] = update.ai_min_confidence
    if update.ai_prompt is not None:
        updates["ai_prompt"] = update.ai_prompt

    if not updates:
        return await get_strategy(strategy_id)

    updates["updated_at"] = "datetime('now')"

    set_clause = ", ".join(
        f"{k} = :{k}" if k != "updated_at" else f"{k} = datetime('now')"
        for k in updates
    )
    params = {k: v for k, v in updates.items() if k != "updated_at"}
    params["id"] = strategy_id

    await db.execute(f"UPDATE strategies SET {set_clause} WHERE id = :id", params)
    await db.commit()

    return await get_strategy(strategy_id)


@router.post("/{strategy_id}/start")
async def start_strategy(strategy_id: str):
    """启动策略"""
    db = await get_db()
    await db.execute(
        "UPDATE strategies SET is_active = 1, updated_at = datetime('now') WHERE id = ?",
        (strategy_id,),
    )
    await db.commit()

    # 通知 StrategyRunner 启动
    if _runner:
        await _runner.start_strategy(strategy_id)

    from ws import ws_manager
    await ws_manager.broadcast("strategy_status", {"id": strategy_id, "is_active": True})

    return {"message": f"策略 {strategy_id} 已启动", "is_active": True}


@router.post("/{strategy_id}/stop")
async def stop_strategy(strategy_id: str):
    """暂停策略"""
    db = await get_db()
    await db.execute(
        "UPDATE strategies SET is_active = 0, updated_at = datetime('now') WHERE id = ?",
        (strategy_id,),
    )
    await db.commit()

    # 通知 StrategyRunner 停止
    if _runner:
        await _runner.stop_strategy(strategy_id)

    from ws import ws_manager
    await ws_manager.broadcast("strategy_status", {"id": strategy_id, "is_active": False})

    return {"message": f"策略 {strategy_id} 已暂停", "is_active": False}


@router.get("/{strategy_id}/positions")
async def get_strategy_positions(strategy_id: str):
    """获取策略关联的持仓（含实时价格、最高/最低盈亏）"""
    import time as _time
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM positions WHERE strategy_id = ?", (strategy_id,)
    )
    rows = await cursor.fetchall()
    if not rows:
        return []

    # 获取实时价格
    price_map = {}
    if _client:
        try:
            tickers = _client.get_tickers()
            price_map = {t["inst_id"]: t["last"] for t in tickers if t.get("last")}
        except Exception:
            pass

    result = []
    now = _time.time()
    for row in rows:
        d = dict(row)
        symbol = d.get("symbol", "")
        current = price_map.get(symbol, d.get("entry_price", 0))
        d["current_price"] = current

        # TP/SL 距离
        tp = d.get("tp_price") or 0
        sl = d.get("sl_price") or 0
        d["tp_distance_pct"] = round((tp - current) / current * 100, 2) if tp > 0 and current > 0 else None
        d["sl_distance_pct"] = round((sl - current) / current * 100, 2) if sl > 0 and current > 0 else None

        # 持仓时长
        from api.positions import _parse_open_time
        open_ts = _parse_open_time(d.get("open_time", ""))
        d["holding_seconds"] = int(now - open_ts) if open_ts > 0 else 0

        result.append(d)
    return result


@router.get("/{strategy_id}/signals")
async def get_strategy_signals(strategy_id: str, limit: int = 200):
    """获取策略最近的信号/AI分析记录"""
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM strategy_signals WHERE strategy_id = ? ORDER BY created_at DESC LIMIT ?",
        (strategy_id, limit),
    )
    rows = await cursor.fetchall()
    result = []
    for row in rows:
        d = dict(row)
        # indicators 是 JSON 字符串
        if d.get("indicators"):
            try:
                d["indicators"] = json.loads(d["indicators"])
            except (json.JSONDecodeError, TypeError):
                pass
        result.append(d)
    return result


@router.get("/{strategy_id}/pnl")
async def get_strategy_pnl(strategy_id: str):
    """获取策略收益曲线数据"""
    db = await get_db()
    cursor = await db.execute(
        """SELECT entry_time, exit_time, pnl, peak_pnl, trough_pnl, symbol, direction
           FROM trades WHERE strategy_id = ? ORDER BY entry_time ASC""",
        (strategy_id,),
    )
    rows = await cursor.fetchall()

    points = []
    cumulative = 0.0
    total_wins = 0
    total_losses = 0
    max_drawdown = 0.0
    peak_equity = 0.0

    for row in rows:
        trade_pnl = row["pnl"] or 0
        cumulative += trade_pnl
        peak_equity = max(peak_equity, cumulative)
        drawdown = cumulative - peak_equity
        max_drawdown = min(max_drawdown, drawdown)

        if trade_pnl > 0:
            total_wins += 1
        elif trade_pnl < 0:
            total_losses += 1

        points.append({
            "time": row["exit_time"] or row["entry_time"],
            "pnl": round(cumulative, 4),
            "trade_pnl": round(trade_pnl, 4),
            "symbol": row["symbol"],
            "direction": row["direction"],
            "peak_pnl": row["peak_pnl"] or 0,
            "trough_pnl": row["trough_pnl"] or 0,
        })

    total = total_wins + total_losses
    return {
        "points": points,
        "total_pnl": round(cumulative, 4),
        "total_trades": len(rows),
        "win_rate": round(total_wins / total * 100, 1) if total > 0 else 0,
        "max_drawdown": round(max_drawdown, 4),
    }
