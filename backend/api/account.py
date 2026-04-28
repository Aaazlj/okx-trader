"""
账户相关 API
"""
import traceback
from fastapi import APIRouter
from fastapi.responses import JSONResponse

import config
from exchange.okx_client import OKXClient
from models import AccountResponse
from utils.logger import get_logger

logger = get_logger("API.account")

router = APIRouter(prefix="/api/account", tags=["account"])

# 全局 OKX 客户端实例（在 main.py 启动时注入）
_client: OKXClient | None = None


def set_client(client: OKXClient):
    global _client
    _client = client


def get_client() -> OKXClient:
    if _client is None:
        raise RuntimeError("OKX 客户端未初始化")
    return _client


@router.get("/balance", response_model=AccountResponse)
async def get_balance():
    """获取账户余额"""
    try:
        client = get_client()
        info = client.get_account_info()
        return AccountResponse(
            total_equity=info.get("total_equity", 0),
            available_balance=info.get("available_balance", 0),
            unrealized_pnl=info.get("unrealized_pnl", 0),
            mode="模拟盘" if config.OKX_DEMO else "实盘",
        )
    except Exception as e:
        logger.error(f"获取余额失败: {e}\n{traceback.format_exc()}")
        return AccountResponse(
            total_equity=0, available_balance=0, unrealized_pnl=0,
            mode="模拟盘" if config.OKX_DEMO else "实盘",
        )
