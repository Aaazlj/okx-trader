"""
合约网格策略辅助 API。
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ai.analyzer import AIAnalyzer
from strategies.contract_grid import normalize_contract_grid_params

router = APIRouter(prefix="/api/contract-grid", tags=["contract-grid"])


class ContractGridParamGenerateRequest(BaseModel):
    symbol: str
    cycle: str = "medium"
    grid_mode: str = "neutral"
    risk_profile: str = "balanced"
    total_margin_usdt: float = Field(default=300.0, gt=0)


@router.post("/params/generate")
async def generate_contract_grid_params(data: ContractGridParamGenerateRequest):
    """使用 AI 生成一份可保存的静态合约网格参数。"""
    raw = await AIAnalyzer().generate_contract_grid_params(data.model_dump())
    if not raw:
        raise HTTPException(status_code=400, detail="AI 参数生成失败，请检查 OPENAI_API_KEY / OPENAI_API_URL 配置")

    raw.setdefault("cycle", data.cycle)
    raw.setdefault("grid_mode", data.grid_mode)
    raw.setdefault("total_margin_usdt", data.total_margin_usdt)
    params = normalize_contract_grid_params(raw)
    return {
        "symbol": data.symbol.upper(),
        "params": params,
        "raw_params": raw,
    }
