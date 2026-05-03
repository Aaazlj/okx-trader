import sys
import asyncio
from pathlib import Path

import aiosqlite
import pandas as pd


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _candles(length: int = 180, start: float = 100.0, step: float = 1.0) -> pd.DataFrame:
    rows = []
    price = start
    for i in range(length):
        open_price = price
        close_price = price + step
        rows.append({
            "ts": pd.Timestamp("2026-01-01") + pd.Timedelta(hours=i),
            "open": open_price,
            "high": close_price + 1,
            "low": open_price - 1,
            "close": close_price,
            "vol": 100 + i,
            "volCcy": 0,
            "volCcyQuote": 0,
            "confirm": 1,
        })
        price = close_price
    return pd.DataFrame(rows)


class FakeOKXClient:
    def __init__(self, one_hour_length: int = 180):
        self.one_hour_length = one_hour_length

    def get_contract_value(self, inst_id: str) -> float:
        assert inst_id == "BTC-USDT-SWAP"
        return 0.01

    def get_candles(self, inst_id: str, bar: str, limit: int):
        if bar == "1H":
            return _candles(self.one_hour_length)
        if bar == "1D":
            return _candles(120, 80, 2)
        if bar == "4H":
            return _candles(120, 90, 1.5)
        return _candles(120, 250, 0.2)

    def get_ticker(self, inst_id: str):
        return {"last": 280.0, "open24h": 260.0, "chg_pct": 7.6923, "high24h": 282.0, "low24h": 250.0}

    def get_funding_rate(self, inst_id: str):
        return {"funding_rate": 0.0002, "next_funding_rate": None}

    def get_funding_rate_history(self, inst_id: str, limit: int = 30):
        return [{"funding_rate": 0.0001, "funding_time": i} for i in range(limit)]

    def get_open_interest_history(self, inst_id: str, period: str = "1H"):
        return [{"ts": i, "oi": 1000 + 25 - i, "oi_ccy": 0, "oi_usd": 1000 + 25 - i} for i in range(30)]

    def get_long_short_account_ratio(self, ccy: str, period: str = "1H"):
        return [{"ts": i, "ratio": 1.1} for i in range(30)]

    def get_long_short_position_ratio(self, inst_id: str, period: str = "1H"):
        return [{"ts": i, "ratio": 1.2} for i in range(30)]

    def get_orderbook_depth(self, inst_id: str, sz: str = "20"):
        return {
            "asks": [["281", "10", "0", "1"], ["282", "2", "0", "1"]],
            "bids": [["279", "8", "0", "1"], ["278", "3", "0", "1"]],
        }

    def get_recent_trades(self, inst_id: str, limit: int = 100):
        return [
            {"side": "buy", "size": 2, "price": 280, "ts": 1},
            {"side": "sell", "size": 1, "price": 279, "ts": 2},
        ]


def test_perpetual_analysis_build_returns_p0_sections():
    from analysis.perpetual import PerpetualAnalysisEngine

    result = PerpetualAnalysisEngine(FakeOKXClient()).build("btc-usdt-swap")

    assert result["symbol"] == "BTC-USDT-SWAP"
    assert result["summary"]["current_price"] == 280.0
    assert result["summary"]["opportunity_grade"] in {"S", "A", "B", "C", "D"}
    assert len(result["scores"]["dimensions"]) == 7
    assert result["trend_analysis"]["indicators"]["ma20"] is not None
    assert result["support_resistance"]["resistance_levels"]
    assert result["support_resistance"]["support_levels"]
    assert result["funding_rate_analysis"]["available"] is True
    assert result["open_interest_analysis"]["available"] is True
    assert result["multi_timeframe_analysis"]["directions"]["1H"] is not None
    assert result["sentiment_analysis"]["long_short_account_ratio"] == 1.1
    assert result["sentiment_analysis"]["long_short_position_ratio"] == 1.2
    assert result["orderbook_depth_analysis"]["imbalance"] in {"买盘强", "卖盘强", "平衡"}
    assert result["institutional_behavior"]["type"]
    assert result["market_phase"]["phase"]
    assert result["strategy_match"]["recommended"]
    assert result["risk_reward_analysis"]["current_price"] == 280.0
    assert len(result["role_advice"]) == 5
    assert "direction" in result["trading_plan"]
    assert any(rule["name"] == "均线多头排列" for rule in result["quant_rules"])
    assert result["ai_report"] is None


def test_perpetual_analysis_records_insufficient_kline_note():
    from analysis.perpetual import PerpetualAnalysisEngine

    result = PerpetualAnalysisEngine(FakeOKXClient(one_hour_length=40)).build("BTC-USDT-SWAP")

    assert "K 线数量不足，部分指标不可用" in result["data_quality_notes"]
    assert result["trend_analysis"]["ma_structure"] == "数据不足"


def _history_analysis(symbol: str, created_at: str, score: float, price: float) -> dict:
    return {
        "symbol": symbol,
        "created_at": created_at,
        "summary": {
            "current_price": price,
            "overall_score": score,
            "opportunity_grade": "A",
            "risk_level": "中",
            "trend": "上涨",
        },
        "scores": {"dimensions": [{"key": "trend", "score": score}]},
        "trend_analysis": {"indicators": {"rsi": 55}},
        "support_resistance": {
            "support_levels": [{"price": price - 10}],
            "resistance_levels": [{"price": price + 10}],
            "key_breakdown_price": price - 12,
            "key_breakout_price": price + 12,
        },
        "risk_reward_analysis": {
            "stop_zone": price - 8,
            "target1": price + 15,
            "target2": price + 25,
        },
        "trading_plan": {
            "entry_observation_zone": [price - 2, price + 2],
            "stop_loss": price - 8,
        },
        "ai_report": "AI report body",
    }


def test_analysis_history_records_snapshot_filters_notes_and_score_series():
    from analysis.history import (
        build_price_comparison,
        delete_analysis_record,
        get_analysis_record,
        get_score_series,
        init_analysis_history_table,
        list_analysis_records,
        save_analysis_record,
        update_analysis_record,
    )

    async def run():
        db = await aiosqlite.connect(":memory:")
        db.row_factory = aiosqlite.Row
        await init_analysis_history_table(db)

        first_id = await save_analysis_record(
            db,
            _history_analysis("BTC-USDT-SWAP", "2026-05-01 10:00:00", 72, 100),
        )
        second_id = await save_analysis_record(
            db,
            _history_analysis("BTC-USDT-SWAP", "2026-05-02 10:00:00", 81, 110),
        )
        await save_analysis_record(
            db,
            _history_analysis("ETH-USDT-SWAP", "2026-05-02 11:00:00", 60, 200),
        )

        listed = await list_analysis_records(db, symbol="btc-usdt-swap", start="2026-05-02", end="2026-05-02")
        assert listed["total"] == 1
        assert listed["items"][0]["id"] == second_id

        updated = await update_analysis_record(db, second_id, note="等待突破确认")
        assert updated["note"] == "等待突破确认"

        detail = await get_analysis_record(db, first_id)
        assert detail["snapshot"]["ai_report"] == "AI report body"
        assert detail["snapshot"]["scores"]["dimensions"][0]["score"] == 72

        series = await get_score_series(db, "BTC-USDT-SWAP")
        assert [item["id"] for item in series] == [first_id, second_id]
        assert series[0]["score_change"] is None
        assert series[1]["score_change"] == 9

        comparison = build_price_comparison(detail, 115)
        assert comparison["analysis_price"] == 100
        assert comparison["current_price"] == 115
        assert comparison["price_delta_pct"] == 15

        assert await delete_analysis_record(db, second_id) is True
        assert await get_analysis_record(db, second_id) is None
        after_delete = await list_analysis_records(db, symbol="BTC-USDT-SWAP")
        assert after_delete["total"] == 1
        assert await delete_analysis_record(db, second_id) is False

        await db.close()

    asyncio.run(run())


def test_perpetual_analysis_api_saves_completed_snapshot(monkeypatch):
    async def run():
        from analysis.history import get_analysis_record, init_analysis_history_table
        from api import perpetual_analysis

        db = await aiosqlite.connect(":memory:")
        db.row_factory = aiosqlite.Row
        await init_analysis_history_table(db)

        async def fake_get_db():
            return db

        async def fake_report(self, analysis):
            return "generated report"

        monkeypatch.setattr(perpetual_analysis, "get_db", fake_get_db)
        monkeypatch.setattr(perpetual_analysis.AIAnalyzer, "generate_perpetual_report", fake_report)
        perpetual_analysis.set_client(FakeOKXClient())

        response = await perpetual_analysis.analyze_perpetual(
            perpetual_analysis.PerpetualAnalysisRequest(symbol="BTC-USDT-SWAP"),
        )

        assert response["history_id"] > 0
        saved = await get_analysis_record(db, response["history_id"])
        assert saved["snapshot"]["symbol"] == "BTC-USDT-SWAP"
        assert saved["snapshot"]["ai_report"] == "generated report"
        assert saved["snapshot"]["scores"]["dimensions"]

        await db.close()

    asyncio.run(run())


def test_analysis_history_replay_checks_key_level_hits():
    from analysis.history import build_replay_result, normalize_history_candles

    analysis = _history_analysis("BTC-USDT-SWAP", "2026-05-01 10:00:00", 72, 100)
    candles = normalize_history_candles([
        ["1777600800000", "100", "108", "98", "106", "10"],
        ["1777604400000", "106", "116", "104", "114", "12"],
    ])

    replay = build_replay_result(analysis, candles)
    levels = {(item["name"], item["type"], item["price"]): item for item in replay["levels"]}

    assert replay["bar_count"] == 2
    assert levels[("压力", "resistance", 110)]["hit"] is True
    assert levels[("第一目标", "target", 115)]["hit"] is True
    assert levels[("第二目标", "target", 125)]["hit"] is False
    assert replay["summary"]["hit_levels"] >= 2
