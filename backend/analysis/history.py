from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import aiosqlite

BEIJING_TZ = timezone(timedelta(hours=8))


async def init_analysis_history_table(db: aiosqlite.Connection) -> None:
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS perpetual_analysis_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            created_at TEXT NOT NULL,
            analysis_price REAL,
            overall_score REAL,
            opportunity_grade TEXT,
            risk_level TEXT,
            trend TEXT,
            ai_report TEXT,
            snapshot_json TEXT NOT NULL,
            note TEXT DEFAULT '',
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_perpetual_analysis_history_symbol_created
            ON perpetual_analysis_history(symbol, created_at DESC);

        CREATE INDEX IF NOT EXISTS idx_perpetual_analysis_history_created
            ON perpetual_analysis_history(created_at DESC);
    """)
    await db.commit()


async def save_analysis_record(db: aiosqlite.Connection, analysis: dict[str, Any]) -> int:
    summary = analysis.get("summary") or {}
    snapshot = json.dumps(analysis, ensure_ascii=False, default=str)
    cursor = await db.execute(
        """
        INSERT INTO perpetual_analysis_history (
            symbol,
            created_at,
            analysis_price,
            overall_score,
            opportunity_grade,
            risk_level,
            trend,
            ai_report,
            snapshot_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            analysis.get("symbol") or "",
            analysis.get("created_at") or _now_text(),
            _to_float(summary.get("current_price")),
            _to_float(summary.get("overall_score")),
            summary.get("opportunity_grade"),
            summary.get("risk_level"),
            summary.get("trend"),
            analysis.get("ai_report"),
            snapshot,
        ),
    )
    await db.commit()
    return int(cursor.lastrowid)


async def list_analysis_records(
    db: aiosqlite.Connection,
    *,
    symbol: str | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    where, params = _history_filters(symbol=symbol, start=start, end=end)
    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    cursor = await db.execute(
        f"""
        SELECT
            id,
            symbol,
            created_at,
            analysis_price,
            overall_score,
            opportunity_grade,
            risk_level,
            trend,
            note,
            updated_at
        FROM perpetual_analysis_history
        {where}
        ORDER BY created_at DESC, id DESC
        LIMIT ? OFFSET ?
        """,
        (*params, limit, offset),
    )
    rows = await cursor.fetchall()

    count_cursor = await db.execute(
        f"SELECT COUNT(*) AS total FROM perpetual_analysis_history {where}",
        params,
    )
    total = (await count_cursor.fetchone())["total"]

    return {
        "items": [_summary_from_row(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


async def get_analysis_record(db: aiosqlite.Connection, record_id: int) -> dict[str, Any] | None:
    cursor = await db.execute(
        "SELECT * FROM perpetual_analysis_history WHERE id = ?",
        (record_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return _detail_from_row(row)


async def update_analysis_record(
    db: aiosqlite.Connection,
    record_id: int,
    *,
    note: str | None = None,
) -> dict[str, Any] | None:
    updates = []
    params: list[Any] = []

    if note is not None:
        updates.append("note = ?")
        params.append(note[:2000])

    if updates:
        updates.append("updated_at = datetime('now')")
        params.append(record_id)
        await db.execute(
            f"UPDATE perpetual_analysis_history SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        await db.commit()

    return await get_analysis_record(db, record_id)


async def delete_analysis_record(db: aiosqlite.Connection, record_id: int) -> bool:
    cursor = await db.execute(
        "DELETE FROM perpetual_analysis_history WHERE id = ?",
        (record_id,),
    )
    await db.commit()
    return cursor.rowcount > 0


async def get_score_series(
    db: aiosqlite.Connection,
    symbol: str,
    *,
    limit: int = 30,
) -> list[dict[str, Any]]:
    limit = max(2, min(limit, 200))
    cursor = await db.execute(
        """
        SELECT id, symbol, created_at, overall_score, opportunity_grade, risk_level, trend, analysis_price
        FROM perpetual_analysis_history
        WHERE symbol = ?
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        (symbol.strip().upper(), limit),
    )
    rows = await cursor.fetchall()
    items = [_score_from_row(row) for row in reversed(rows)]
    previous_score = None
    for item in items:
        score = item.get("overall_score")
        item["score_change"] = None if previous_score is None or score is None else round(score - previous_score, 2)
        previous_score = score
    return items


def build_price_comparison(record: dict[str, Any], current_price: float | None) -> dict[str, Any]:
    analysis_price = _to_float(record.get("analysis_price"))
    if analysis_price is None or current_price is None:
        return {
            "analysis_price": analysis_price,
            "current_price": current_price,
            "price_delta": None,
            "price_delta_pct": None,
        }

    delta = current_price - analysis_price
    return {
        "analysis_price": analysis_price,
        "current_price": current_price,
        "price_delta": delta,
        "price_delta_pct": (delta / analysis_price * 100) if analysis_price else None,
    }


def normalize_history_candles(raw_candles: list[Any]) -> list[dict[str, Any]]:
    candles = []
    for item in raw_candles or []:
        try:
            ts = int(item[0])
            candles.append({
                "ts": ts,
                "time": datetime.fromtimestamp(ts / 1000, BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S"),
                "open": float(item[1]),
                "high": float(item[2]),
                "low": float(item[3]),
                "close": float(item[4]),
                "volume": float(item[5]) if len(item) > 5 and item[5] not in (None, "") else None,
            })
        except (TypeError, ValueError, IndexError):
            continue
    return sorted(candles, key=lambda item: item["ts"])


def build_replay_result(analysis: dict[str, Any], candles: list[dict[str, Any]]) -> dict[str, Any]:
    levels = _extract_key_levels(analysis)
    replay_levels = [_evaluate_level(level, candles) for level in levels]
    hit_count = sum(1 for item in replay_levels if item["hit"])

    return {
        "symbol": analysis.get("symbol"),
        "analysis_created_at": analysis.get("created_at"),
        "bar_count": len(candles),
        "candles": candles,
        "levels": replay_levels,
        "summary": {
            "total_levels": len(replay_levels),
            "hit_levels": hit_count,
            "missed_levels": max(len(replay_levels) - hit_count, 0),
        },
    }


def analysis_time_ms(analysis: dict[str, Any]) -> int | None:
    created_at = analysis.get("created_at")
    if not created_at:
        return None
    try:
        dt = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S").replace(tzinfo=BEIJING_TZ)
    except ValueError:
        return None
    return int(dt.timestamp() * 1000)


def _history_filters(
    *,
    symbol: str | None,
    start: str | None,
    end: str | None,
) -> tuple[str, tuple[Any, ...]]:
    clauses = []
    params: list[Any] = []

    if symbol:
        clauses.append("symbol = ?")
        params.append(symbol.strip().upper())
    if start:
        clauses.append("created_at >= ?")
        params.append(_date_bound(start, end_of_day=False))
    if end:
        clauses.append("created_at <= ?")
        params.append(_date_bound(end, end_of_day=True))
    if not clauses:
        return "", tuple(params)
    return "WHERE " + " AND ".join(clauses), tuple(params)


def _summary_from_row(row: aiosqlite.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "symbol": row["symbol"],
        "created_at": row["created_at"],
        "analysis_price": row["analysis_price"],
        "overall_score": row["overall_score"],
        "opportunity_grade": row["opportunity_grade"],
        "risk_level": row["risk_level"],
        "trend": row["trend"],
        "note": row["note"] or "",
        "updated_at": row["updated_at"],
    }


def _detail_from_row(row: aiosqlite.Row) -> dict[str, Any]:
    item = _summary_from_row(row)
    item["snapshot"] = json.loads(row["snapshot_json"])
    item["ai_report"] = row["ai_report"]
    return item


def _score_from_row(row: aiosqlite.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "symbol": row["symbol"],
        "created_at": row["created_at"],
        "overall_score": row["overall_score"],
        "opportunity_grade": row["opportunity_grade"],
        "risk_level": row["risk_level"],
        "trend": row["trend"],
        "analysis_price": row["analysis_price"],
    }


def _extract_key_levels(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    levels: list[dict[str, Any]] = []
    support_resistance = analysis.get("support_resistance") or {}
    trading_plan = analysis.get("trading_plan") or {}
    risk_reward = analysis.get("risk_reward_analysis") or {}

    for level in support_resistance.get("support_levels") or []:
        _append_level(levels, "支撑", "support", level.get("price"))
    for level in support_resistance.get("resistance_levels") or []:
        _append_level(levels, "压力", "resistance", level.get("price"))

    _append_level(levels, "关键下破价", "breakdown", support_resistance.get("key_breakdown_price"))
    _append_level(levels, "关键突破价", "breakout", support_resistance.get("key_breakout_price"))
    _append_level(levels, "止损", "stop", trading_plan.get("stop_loss") or risk_reward.get("stop_zone"))
    _append_level(levels, "第一目标", "target", risk_reward.get("target1"))
    _append_level(levels, "第二目标", "target", risk_reward.get("target2"))

    for price in trading_plan.get("entry_observation_zone") or []:
        _append_level(levels, "观察区间", "entry", price)

    seen = set()
    unique_levels = []
    for level in levels:
        key = (level["name"], level["type"], round(level["price"], 8))
        if key in seen:
            continue
        seen.add(key)
        unique_levels.append(level)
    return unique_levels


def _append_level(levels: list[dict[str, Any]], name: str, level_type: str, price: Any) -> None:
    value = _to_float(price)
    if value is None or value <= 0:
        return
    levels.append({"name": name, "type": level_type, "price": value})


def _evaluate_level(level: dict[str, Any], candles: list[dict[str, Any]]) -> dict[str, Any]:
    price = level["price"]
    level_type = level["type"]
    hit_candle = None
    for candle in candles:
        high = candle.get("high")
        low = candle.get("low")
        if high is None or low is None:
            continue
        if level_type in {"resistance", "breakout", "target"} and high >= price:
            hit_candle = candle
            break
        if level_type in {"support", "breakdown", "stop"} and low <= price:
            hit_candle = candle
            break
        if level_type == "entry" and low <= price <= high:
            hit_candle = candle
            break

    return {
        **level,
        "hit": hit_candle is not None,
        "hit_time": hit_candle["time"] if hit_candle else None,
        "hit_close": hit_candle["close"] if hit_candle else None,
    }


def _date_bound(value: str, *, end_of_day: bool) -> str:
    value = value.strip()
    if len(value) == 10:
        return f"{value} {'23:59:59' if end_of_day else '00:00:00'}"
    return value


def _now_text() -> str:
    return datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
