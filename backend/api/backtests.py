"""
策略回测 API。
"""
import asyncio
import json
import time
from typing import Any

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from core.martingale_backtester import run_martingale_backtest
from db.database import get_db
from exchange.okx_client import OKXClient
from strategies.martingale_contract import normalize_martingale_params
from utils.logger import get_logger

logger = get_logger("API.backtests")

router = APIRouter(prefix="/api/backtests", tags=["backtests"])

_client: OKXClient | None = None


class MartingaleBacktestRequest(BaseModel):
    strategy_id: str = "martingale_contract"
    symbol: str
    cycle: str = "medium"
    bar: str | None = None
    start: str | None = None
    end: str | None = None
    params: dict = Field(default_factory=dict)
    leverage: int = Field(default=3, ge=1, le=100)
    base_order_usdt: float = Field(default=20, gt=0)
    fee_rate: float = Field(default=0.0005, ge=0, le=0.01)
    slippage_pct: float = Field(default=0.02, ge=0, le=2)


class CandleDownloadRequest(BaseModel):
    symbol: str
    cycle: str = "medium"
    bar: str | None = None
    start: str
    end: str | None = None


def set_client(client: OKXClient):
    global _client
    _client = client


@router.post("/candles/download")
async def download_backtest_candles(data: CandleDownloadRequest):
    """按时间范围下载并缓存回测 K 线。"""
    if _client is None:
        raise HTTPException(status_code=503, detail="OKX 客户端未初始化")

    symbol = _normalize_symbol(data.symbol)
    params = _normalized_cycle_params(data.cycle, data.bar)
    bar = params["bar"]
    start_ms, end_ms = _resolve_range(data.start, data.end, bar)

    try:
        candles = await _download_history_df(symbol, bar, start_ms, end_ms)
    except Exception as e:
        logger.error(f"下载回测K线失败 {symbol} {bar}: {e}")
        raise HTTPException(status_code=502, detail="下载 K 线失败，请稍后重试") from e

    if candles.empty:
        raise HTTPException(status_code=502, detail="下载到的 K 线为空，请调整时间范围后重试")

    db = await get_db()
    saved_count = await _save_cached_candles(db, symbol, bar, candles)
    coverage = await _build_coverage_response(db, symbol, params, start_ms, end_ms)
    return {
        "symbol": symbol,
        "cycle": params["cycle"],
        "bar": bar,
        "requested_start": _ms_to_text(start_ms),
        "requested_end": _ms_to_text(end_ms),
        "downloaded_count": len(candles),
        "saved_count": saved_count,
        "coverage": coverage,
    }


@router.get("/candles/coverage")
async def get_backtest_candle_coverage(
    symbol: str,
    cycle: str = "medium",
    bar: str | None = None,
    start: str | None = None,
    end: str | None = None,
):
    """查询本地回测 K 线缓存覆盖情况。"""
    normalized_symbol = _normalize_symbol(symbol)
    params = _normalized_cycle_params(cycle, bar)
    start_ms, end_ms = _resolve_range(start, end, params["bar"])
    db = await get_db()
    return await _build_coverage_response(db, normalized_symbol, params, start_ms, end_ms)


@router.get("/martingale/records")
async def list_martingale_backtest_records(
    symbol: str | None = None,
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """查询马丁格尔回测历史记录。"""
    db = await get_db()
    where = ""
    params: list[Any] = []
    if symbol:
        where = "WHERE symbol = ?"
        params.append(_normalize_symbol(symbol))

    cursor = await db.execute(
        f"""
        SELECT id, strategy_id, symbol, cycle, bar, start_ts, end_ts,
               candle_count, summary_json, created_at
        FROM martingale_backtest_records
        {where}
        ORDER BY created_at DESC, id DESC
        LIMIT ? OFFSET ?
        """,
        (*params, limit, offset),
    )
    rows = await cursor.fetchall()
    total_cursor = await db.execute(
        f"SELECT COUNT(*) AS total FROM martingale_backtest_records {where}",
        params,
    )
    total = (await total_cursor.fetchone())["total"]
    return {
        "items": [_record_summary(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/martingale/records/{record_id}")
async def get_martingale_backtest_record(record_id: int):
    """查询单条马丁格尔回测记录详情。"""
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM martingale_backtest_records WHERE id = ?",
        (record_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="回测记录不存在")
    return _record_detail(row)


@router.post("/martingale")
async def backtest_martingale(data: MartingaleBacktestRequest):
    """运行单币种马丁格尔回测。"""
    symbol = _normalize_symbol(data.symbol)
    params = dict(data.params or {})
    params["cycle"] = data.cycle
    if data.bar:
        params["bar"] = data.bar
    params = normalize_martingale_params(params)
    start_ms, end_ms = _resolve_range(data.start, data.end, params["bar"])

    db = await get_db()
    coverage = await _build_coverage_response(db, symbol, params, start_ms, end_ms)
    if coverage["missing_reason"]:
        raise HTTPException(status_code=400, detail=coverage["missing_reason"])

    candles = await _load_cached_df(db, symbol, params["bar"], start_ms, end_ms)
    if candles.empty:
        raise HTTPException(status_code=400, detail="本地 K 线为空，请先下载所选时间范围的 K 线")

    try:
        result = run_martingale_backtest(
            candles,
            symbol=symbol,
            params=params,
            leverage=data.leverage,
            base_order_usdt=data.base_order_usdt,
            fee_rate=data.fee_rate,
            slippage_pct=data.slippage_pct,
        )
        if result.get("message"):
            raise HTTPException(status_code=400, detail=result["message"])
        result["candle_range"] = {
            "start": _ms_to_text(start_ms),
            "end": _ms_to_text(end_ms),
            "bar": params["bar"],
            "candle_count": len(candles),
        }
        record_id = await _save_backtest_record(
            db,
            strategy_id=data.strategy_id,
            symbol=symbol,
            params=params,
            start_ms=start_ms,
            end_ms=end_ms,
            candle_count=len(candles),
            result=result,
        )
        result["record_id"] = record_id
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"马丁格尔回测失败 {symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"回测失败: {type(e).__name__}") from e


def _normalized_cycle_params(cycle: str, bar: str | None = None) -> dict:
    params: dict[str, Any] = {"cycle": cycle}
    if bar:
        params["bar"] = bar
    return normalize_martingale_params(params)


def _normalize_symbol(symbol: str) -> str:
    value = (symbol or "").strip().upper()
    if not value:
        raise HTTPException(status_code=400, detail="交易对不能为空")
    return value


async def _download_history_df(symbol: str, bar: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    def load() -> pd.DataFrame:
        if _client is None:
            return pd.DataFrame()

        rows: list[Any] = []
        cursor = str(end_ms)
        expected_pages = max(1, _expected_candle_count(start_ms, end_ms, bar) // 100 + 2)
        max_pages = min(300, max(10, expected_pages))

        for _ in range(max_pages):
            batch = _client.get_history_candles(
                inst_id=symbol,
                bar=bar,
                after=cursor,
                limit=100,
            )
            if isinstance(batch, pd.DataFrame):
                batch = batch.to_dict("records")
            if not batch:
                break
            rows.extend(batch)
            timestamps = [_row_ts(item) for item in batch if _row_ts(item) is not None]
            if not timestamps:
                break
            min_ts = min(timestamps)
            if start_ms is not None and min_ts <= start_ms:
                break
            next_cursor = str(min_ts - 1)
            if next_cursor == cursor:
                break
            cursor = next_cursor

        df = _rows_to_df(rows)
        if df.empty:
            return df
        start_ts = pd.to_datetime(start_ms, unit="ms", utc=True).tz_convert("Asia/Shanghai")
        end_ts = pd.to_datetime(end_ms, unit="ms", utc=True).tz_convert("Asia/Shanghai")
        df = df[(df["ts"] >= start_ts) & (df["ts"] <= end_ts)]
        return df.sort_values("ts").reset_index(drop=True)

    return await asyncio.to_thread(load)


async def _save_cached_candles(db, symbol: str, bar: str, df: pd.DataFrame) -> int:
    rows = [
        (
            symbol,
            bar,
            _timestamp_ms(row["ts"]),
            _to_float(row.get("open"), 0),
            _to_float(row.get("high"), 0),
            _to_float(row.get("low"), 0),
            _to_float(row.get("close"), 0),
            _to_float(row.get("vol"), 0),
            _to_float(row.get("volCcy"), 0),
            _to_float(row.get("volCcyQuote"), 0),
            int(_to_float(row.get("confirm"), 1)),
        )
        for row in df.to_dict("records")
    ]
    if not rows:
        return 0

    await db.executemany(
        """
        INSERT INTO backtest_candles (
            symbol, bar, ts, open, high, low, close,
            vol, vol_ccy, vol_ccy_quote, confirm
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(symbol, bar, ts) DO UPDATE SET
            open = excluded.open,
            high = excluded.high,
            low = excluded.low,
            close = excluded.close,
            vol = excluded.vol,
            vol_ccy = excluded.vol_ccy,
            vol_ccy_quote = excluded.vol_ccy_quote,
            confirm = excluded.confirm,
            updated_at = datetime('now')
        """,
        rows,
    )
    await db.commit()
    return len(rows)


async def _load_cached_df(db, symbol: str, bar: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    cursor = await db.execute(
        """
        SELECT ts, open, high, low, close, vol, vol_ccy, vol_ccy_quote, confirm
        FROM backtest_candles
        WHERE symbol = ? AND bar = ? AND ts BETWEEN ? AND ?
        ORDER BY ts ASC
        """,
        (symbol, bar, start_ms, end_ms),
    )
    rows = await cursor.fetchall()
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame([dict(row) for row in rows])
    df = df.rename(columns={"vol_ccy": "volCcy", "vol_ccy_quote": "volCcyQuote"})
    df["ts"] = pd.to_datetime(df["ts"].astype("int64"), unit="ms", utc=True).dt.tz_convert("Asia/Shanghai")
    for col in ["open", "high", "low", "close", "vol", "volCcy", "volCcyQuote"]:
        if col in df.columns:
            df[col] = df[col].astype(float)
    if "confirm" in df.columns:
        df["confirm"] = df["confirm"].astype(int)
    return df.sort_values("ts").reset_index(drop=True)


async def _build_coverage_response(db, symbol: str, params: dict, start_ms: int, end_ms: int) -> dict[str, Any]:
    bar = params["bar"]
    coverage = await _cached_coverage(db, symbol, bar, start_ms, end_ms)
    required_count = _required_candle_count(params)
    expected_count = _expected_candle_count(start_ms, end_ms, bar)
    missing_reason = _coverage_missing_reason(coverage, start_ms, end_ms, bar, required_count)
    return {
        "symbol": symbol,
        "cycle": params["cycle"],
        "bar": bar,
        "requested_start": _ms_to_text(start_ms),
        "requested_end": _ms_to_text(end_ms),
        "requested_start_ts": start_ms,
        "requested_end_ts": end_ms,
        "cached_count": coverage["cached_count"],
        "cached_start": _ms_to_text(coverage["cached_start_ts"]) if coverage["cached_start_ts"] else None,
        "cached_end": _ms_to_text(coverage["cached_end_ts"]) if coverage["cached_end_ts"] else None,
        "cached_start_ts": coverage["cached_start_ts"],
        "cached_end_ts": coverage["cached_end_ts"],
        "required_count": required_count,
        "expected_count": expected_count,
        "is_sufficient": missing_reason is None,
        "missing_reason": missing_reason,
    }


async def _cached_coverage(db, symbol: str, bar: str, start_ms: int, end_ms: int) -> dict[str, Any]:
    cursor = await db.execute(
        """
        SELECT COUNT(*) AS cached_count, MIN(ts) AS cached_start_ts, MAX(ts) AS cached_end_ts
        FROM backtest_candles
        WHERE symbol = ? AND bar = ? AND ts BETWEEN ? AND ?
        """,
        (symbol, bar, start_ms, end_ms),
    )
    row = await cursor.fetchone()
    return {
        "cached_count": int(row["cached_count"] or 0),
        "cached_start_ts": row["cached_start_ts"],
        "cached_end_ts": row["cached_end_ts"],
    }


def _coverage_missing_reason(
    coverage: dict[str, Any],
    start_ms: int,
    end_ms: int,
    bar: str,
    required_count: int,
) -> str | None:
    count = coverage["cached_count"]
    if count <= 0:
        return "本地没有所选范围的 K 线，请先下载 K 线后再回测"
    if count < required_count:
        return f"本地 K 线数量不足：需要至少 {required_count} 根，当前 {count} 根，请下载更长时间范围"

    tolerance = _bar_ms(bar)
    cached_start = coverage["cached_start_ts"]
    cached_end = coverage["cached_end_ts"]
    if cached_start is None or cached_end is None:
        return "本地 K 线覆盖范围异常，请重新下载"
    if cached_start > start_ms + tolerance:
        return "本地 K 线未覆盖所选开始时间，请先下载完整时间范围"
    if cached_end < end_ms - tolerance:
        return "本地 K 线未覆盖所选结束时间，请先下载完整时间范围"
    return None


async def _save_backtest_record(
    db,
    *,
    strategy_id: str,
    symbol: str,
    params: dict,
    start_ms: int,
    end_ms: int,
    candle_count: int,
    result: dict[str, Any],
) -> int:
    cursor = await db.execute(
        """
        INSERT INTO martingale_backtest_records (
            strategy_id, symbol, cycle, bar, start_ts, end_ts, candle_count,
            params_json, summary_json, result_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            strategy_id,
            symbol,
            params["cycle"],
            params["bar"],
            start_ms,
            end_ms,
            candle_count,
            json.dumps(params, ensure_ascii=False, default=str),
            json.dumps(result.get("summary") or {}, ensure_ascii=False, default=str),
            json.dumps(result, ensure_ascii=False, default=str),
        ),
    )
    await db.commit()
    return int(cursor.lastrowid)


def _rows_to_df(rows: list[Any]) -> pd.DataFrame:
    if isinstance(rows, pd.DataFrame):
        return rows
    normalized = []
    for item in rows:
        if isinstance(item, dict):
            normalized.append(item)
        elif isinstance(item, (list, tuple)) and len(item) >= 6:
            normalized.append({
                "ts": item[0],
                "open": item[1],
                "high": item[2],
                "low": item[3],
                "close": item[4],
                "vol": item[5],
                "volCcy": item[6] if len(item) > 6 else 0,
                "volCcyQuote": item[7] if len(item) > 7 else 0,
                "confirm": item[8] if len(item) > 8 else 1,
            })
    if not normalized:
        return pd.DataFrame()
    df = pd.DataFrame(normalized)
    for col in ["open", "high", "low", "close", "vol", "volCcy", "volCcyQuote"]:
        if col in df.columns:
            df[col] = df[col].astype(float)
    if pd.api.types.is_datetime64_any_dtype(df["ts"]):
        df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert("Asia/Shanghai")
    else:
        df["ts"] = pd.to_datetime(df["ts"].astype("int64"), unit="ms", utc=True).dt.tz_convert("Asia/Shanghai")
    if "confirm" in df.columns:
        df["confirm"] = df["confirm"].astype(int)
    return df.drop_duplicates(subset=["ts"]).sort_values("ts").reset_index(drop=True)


def _parse_ms(value: str | None) -> int | None:
    if not value:
        return None
    ts = pd.to_datetime(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("Asia/Shanghai")
    else:
        ts = ts.tz_convert("Asia/Shanghai")
    return int(ts.timestamp() * 1000)


def _resolve_range(start: str | None, end: str | None, bar: str) -> tuple[int, int]:
    end_ms = _parse_ms(end) or int(time.time() * 1000)
    start_ms = _parse_ms(start)
    if start_ms is None:
        start_ms = end_ms - _bar_ms(bar) * 300
    if start_ms >= end_ms:
        raise HTTPException(status_code=400, detail="开始时间必须早于结束时间")
    return start_ms, end_ms


def _bar_ms(bar: str) -> int:
    unit = bar[-1]
    try:
        value = int(bar[:-1])
    except ValueError:
        value = 1
    if unit == "m":
        return value * 60 * 1000
    if unit == "H":
        return value * 60 * 60 * 1000
    if unit == "D":
        return value * 24 * 60 * 60 * 1000
    return 60 * 60 * 1000


def _expected_candle_count(start_ms: int, end_ms: int, bar: str) -> int:
    return max(1, int((end_ms - start_ms) // _bar_ms(bar)) + 1)


def _required_candle_count(params: dict) -> int:
    return 2


def _timestamp_ms(value: Any) -> int:
    if isinstance(value, pd.Timestamp):
        ts = value
    else:
        ts = pd.to_datetime(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("Asia/Shanghai")
    else:
        ts = ts.tz_convert("Asia/Shanghai")
    return int(ts.timestamp() * 1000)


def _ms_to_text(value: int) -> str:
    return pd.to_datetime(int(value), unit="ms", utc=True).tz_convert("Asia/Shanghai").strftime("%Y-%m-%d %H:%M:%S")


def _to_float(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _record_summary(row) -> dict[str, Any]:
    summary = json.loads(row["summary_json"] or "{}")
    return {
        "id": row["id"],
        "strategy_id": row["strategy_id"],
        "symbol": row["symbol"],
        "cycle": row["cycle"],
        "bar": row["bar"],
        "start": _ms_to_text(row["start_ts"]),
        "end": _ms_to_text(row["end_ts"]),
        "candle_count": row["candle_count"],
        "created_at": row["created_at"],
        "total_pnl": summary.get("total_pnl", 0),
        "return_pct": summary.get("return_pct", 0),
        "max_drawdown": summary.get("max_drawdown", 0),
        "total_trades": summary.get("total_trades", 0),
        "win_rate": summary.get("win_rate", 0),
        "max_add_count": summary.get("max_add_count", 0),
    }


def _record_detail(row) -> dict[str, Any]:
    item = _record_summary(row)
    item["params"] = json.loads(row["params_json"] or "{}")
    item["summary"] = json.loads(row["summary_json"] or "{}")
    item["result"] = json.loads(row["result_json"] or "{}")
    return item


def _row_ts(item: Any) -> int | None:
    try:
        if isinstance(item, dict):
            ts = item.get("ts")
            if isinstance(ts, pd.Timestamp):
                return int(ts.timestamp() * 1000)
            return int(ts)
        return int(item[0])
    except (TypeError, ValueError, IndexError):
        return None
