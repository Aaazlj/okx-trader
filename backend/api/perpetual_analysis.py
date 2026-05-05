"""
永续合约智能分析 API
"""
import asyncio
import traceback
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ai.analyzer import AIAnalyzer
from analysis.history import (
    analysis_time_ms,
    build_price_comparison,
    build_replay_result,
    delete_analysis_record,
    get_analysis_record,
    get_score_series,
    list_analysis_records,
    normalize_history_candles,
    save_analysis_record,
    update_analysis_record,
)
from analysis.perpetual import AnalysisDataError, PerpetualAnalysisEngine, UnknownInstrumentError
from db.database import get_db
from exchange.okx_client import OKXClient
from utils.logger import get_logger

logger = get_logger("API.perpetual_analysis")

router = APIRouter(prefix="/api/perpetual-analysis", tags=["perpetual-analysis"])

_client: OKXClient | None = None


class PerpetualAnalysisRequest(BaseModel):
    symbol: str


class PerpetualAnalysisHistoryUpdate(BaseModel):
    note: str | None = None


def set_client(client: OKXClient):
    global _client
    _client = client


@router.post("")
async def analyze_perpetual(data: PerpetualAnalysisRequest):
    """生成永续合约结构化分析与 AI 自然语言报告。"""
    if _client is None:
        raise HTTPException(status_code=503, detail="OKX 客户端未初始化")

    engine = PerpetualAnalysisEngine(_client)
    try:
        analysis = await asyncio.to_thread(engine.build, data.symbol)
    except UnknownInstrumentError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except AnalysisDataError as e:
        raise HTTPException(status_code=502, detail=f"数据加载失败，请重试：{e}") from e
    except Exception as e:
        logger.error(f"永续合约分析失败: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="数据加载失败，请重试") from e

    report = await AIAnalyzer().generate_perpetual_report(analysis)
    if report:
        analysis["ai_report"] = report
    else:
        analysis["ai_report_error"] = "AI 报告生成失败，请刷新重试"

    db = await get_db()
    history_id = await save_analysis_record(db, analysis)
    analysis["history_id"] = history_id
    return analysis


@router.get("/history")
async def get_analysis_history(
    symbol: str | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """查询永续分析历史记录。"""
    db = await get_db()
    return await list_analysis_records(
        db,
        symbol=symbol,
        start=start,
        end=end,
        limit=limit,
        offset=offset,
    )


@router.get("/history/score-series")
async def get_history_score_series(
    symbol: str,
    limit: int = Query(30, ge=2, le=200),
):
    """查询同一交易对多次分析评分变化。"""
    db = await get_db()
    return {"items": await get_score_series(db, symbol, limit=limit)}


@router.get("/history/{record_id}")
async def get_analysis_history_detail(record_id: int):
    """查询完整历史分析快照，并附带当前实时价格对比。"""
    db = await get_db()
    record = await get_analysis_record(db, record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="历史分析记录不存在")

    current_price = await _load_current_price(record["symbol"])
    record["price_comparison"] = build_price_comparison(record, current_price)
    return record


@router.patch("/history/{record_id}")
async def patch_analysis_history(record_id: int, data: PerpetualAnalysisHistoryUpdate):
    """更新历史记录备注。"""
    db = await get_db()
    record = await update_analysis_record(
        db,
        record_id,
        note=data.note,
    )
    if record is None:
        raise HTTPException(status_code=404, detail="历史分析记录不存在")
    record["price_comparison"] = build_price_comparison(record, await _load_current_price(record["symbol"]))
    return record


@router.delete("/history/{record_id}")
async def delete_analysis_history(record_id: int):
    """删除历史分析记录。"""
    db = await get_db()
    deleted = await delete_analysis_record(db, record_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="历史分析记录不存在")
    return {"deleted": True}


@router.get("/history/{record_id}/replay")
async def replay_analysis_history(
    record_id: int,
    bar: str = Query("1H", pattern="^(1m|3m|5m|15m|30m|1H|2H|4H|6H|12H|1D)$"),
    limit: int = Query(100, ge=10, le=300),
):
    """拉取分析时间点后的 K 线，并检验当时关键价位是否触达。"""
    if _client is None:
        raise HTTPException(status_code=503, detail="OKX 客户端未初始化")

    db = await get_db()
    record = await get_analysis_record(db, record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="历史分析记录不存在")

    snapshot = record["snapshot"]
    since_ms = analysis_time_ms(snapshot)
    raw_candles = await _load_history_candles(record["symbol"], bar, since_ms, limit)
    candles = normalize_history_candles(raw_candles)
    if since_ms is not None:
        candles = [item for item in candles if item["ts"] >= since_ms]
    return build_replay_result(snapshot, candles)


async def _load_current_price(symbol: str) -> float | None:
    if _client is None:
        return None

    def load() -> float | None:
        ticker = _client.get_ticker(symbol)
        return _to_float(ticker.get("last") if isinstance(ticker, dict) else None)

    try:
        return await asyncio.to_thread(load)
    except Exception as e:
        logger.warning(f"获取当前价格失败 {symbol}: {e}")
        return None


async def _load_history_candles(symbol: str, bar: str, since_ms: int | None, limit: int) -> list[Any]:
    if _client is None:
        return []

    def load() -> list[Any]:
        params = {"inst_id": symbol, "bar": bar, "limit": limit}
        if since_ms is not None:
            params["before"] = str(since_ms)
        candles = _client.get_history_candles(**params)
        if candles:
            return candles
        if since_ms is not None:
            params.pop("before", None)
            return _client.get_history_candles(**params)
        return []

    try:
        return await asyncio.to_thread(load)
    except Exception as e:
        logger.warning(f"获取复盘K线失败 {symbol}: {e}")
        return []


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
