"""
Pydantic 数据模型
"""
from pydantic import BaseModel


class StrategyResponse(BaseModel):
    id: str
    name: str
    strategy_type: str
    is_active: bool
    symbols: list[str]
    decision_mode: str
    leverage: int
    order_amount_usdt: float
    mgn_mode: str
    poll_interval: int
    params: dict
    ai_min_confidence: int
    ai_prompt: str


class StrategyUpdate(BaseModel):
    name: str | None = None
    symbols: list[str] | None = None
    decision_mode: str | None = None
    leverage: int | None = None
    order_amount_usdt: float | None = None
    mgn_mode: str | None = None
    poll_interval: int | None = None
    params: dict | None = None
    ai_min_confidence: int | None = None
    ai_prompt: str | None = None


class TradeResponse(BaseModel):
    id: int
    strategy_id: str
    symbol: str
    direction: str
    entry_price: float
    exit_price: float | None
    quantity: float
    leverage: int
    tp_price: float | None
    sl_price: float | None
    pnl: float | None
    status: str
    reason: str | None
    entry_time: str
    exit_time: str | None


class PositionResponse(BaseModel):
    symbol: str
    strategy_id: str
    direction: str
    entry_price: float
    quantity: float
    leverage: int
    tp_price: float | None
    sl_price: float | None
    unrealized_pnl: float | None = None


class AccountResponse(BaseModel):
    total_equity: float
    available_balance: float
    unrealized_pnl: float
    mode: str  # "模拟盘" / "实盘"
