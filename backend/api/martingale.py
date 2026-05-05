"""
马丁格尔策略辅助 API。
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ai.analyzer import AIAnalyzer
from strategies.martingale_contract import normalize_martingale_params

router = APIRouter(prefix="/api/martingale", tags=["martingale"])


class MartingaleParamGenerateRequest(BaseModel):
    symbol: str
    cycle: str = "medium"
    risk_profile: str = "balanced"
    max_position_usdt: float = 300.0


@router.post("/params/generate")
async def generate_martingale_params(data: MartingaleParamGenerateRequest):
    """使用 AI 生成一份可保存的静态马丁格尔参数。"""
    raw = await AIAnalyzer().generate_martingale_params(data.model_dump())
    if not raw:
        raise HTTPException(status_code=400, detail="AI 参数生成失败，请检查 OPENAI_API_KEY / OPENAI_API_URL 配置")

    raw.setdefault("cycle", data.cycle)
    raw.setdefault("max_position_usdt", data.max_position_usdt)
    params = normalize_martingale_params(raw)
    return {
        "symbol": data.symbol.upper(),
        "params": params,
        "raw_params": raw,
    }
