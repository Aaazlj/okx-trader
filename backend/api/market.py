"""
交易对 + 交易历史 API
"""
import traceback
from fastapi import APIRouter

from exchange.okx_client import OKXClient
from db.database import get_db
from utils.logger import get_logger

logger = get_logger("API.market")

router = APIRouter(prefix="/api", tags=["market"])

_client: OKXClient | None = None


def set_client(client: OKXClient):
    global _client
    _client = client


@router.get("/symbols")
async def get_symbols():
    """获取可用交易对列表"""
    if _client is None:
        return []
    try:
        symbols = _client.get_available_symbols()
        return symbols
    except Exception as e:
        logger.error(f"获取交易对失败: {e}\n{traceback.format_exc()}")
        return []


@router.get("/trades/history")
async def get_trade_history(limit: int = 50, strategy_id: str = None):
    """获取交易历史"""
    try:
        db = await get_db()

        if strategy_id:
            cursor = await db.execute(
                "SELECT * FROM trades WHERE strategy_id = ? ORDER BY entry_time DESC LIMIT ?",
                (strategy_id, limit),
            )
        else:
            cursor = await db.execute(
                "SELECT * FROM trades ORDER BY entry_time DESC LIMIT ?",
                (limit,),
            )

        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"获取交易历史失败: {e}\n{traceback.format_exc()}")
        return []
