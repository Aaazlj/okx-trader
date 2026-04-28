"""
持仓相关 API
"""
import traceback
from fastapi import APIRouter

from exchange.okx_client import OKXClient
from utils.logger import get_logger

logger = get_logger("API.positions")

router = APIRouter(prefix="/api/positions", tags=["positions"])

_client: OKXClient | None = None


def set_client(client: OKXClient):
    global _client
    _client = client


@router.get("")
async def get_positions():
    """获取当前所有持仓"""
    if _client is None:
        return []

    try:
        positions = _client.get_positions()
        result = []
        for p in positions:
            result.append({
                "symbol": p.get("instId", ""),
                "direction": "long" if float(p.get("pos", 0)) > 0 else "short",
                "quantity": abs(float(p.get("pos", 0))),
                "entry_price": float(p.get("avgPx", 0) or 0),
                "unrealized_pnl": float(p.get("upl", 0) or 0),
                "leverage": int(p.get("lever", 0) or 0),
                "margin_mode": p.get("mgnMode", ""),
            })
        return result
    except Exception as e:
        logger.error(f"获取持仓失败: {e}\n{traceback.format_exc()}")
        return []
