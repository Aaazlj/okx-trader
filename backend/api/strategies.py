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


def set_runner(runner):
    global _runner
    _runner = runner


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
    """获取策略关联的持仓（含最高/最低盈亏）"""
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM positions WHERE strategy_id = ?", (strategy_id,)
    )
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


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
