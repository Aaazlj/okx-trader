import asyncio
import sys
from pathlib import Path

import aiosqlite
import pandas as pd
import pytest
from fastapi import HTTPException


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _frame(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "ts": pd.Timestamp("2026-01-01") + pd.Timedelta(hours=i),
            "open": item[0],
            "high": item[1],
            "low": item[2],
            "close": item[3],
            "vol": 100,
            "volCcy": 100,
            "volCcyQuote": 100,
            "confirm": 1,
        }
        for i, item in enumerate(rows)
    ])


def _params(mode: str) -> dict:
    return {
        "cycle": "medium",
        "grid_mode": mode,
        "lower_price": 99,
        "upper_price": 101,
        "grid_count": 2,
        "total_margin_usdt": 100,
        "leverage": 2,
        "stop_lower_price": 97,
        "stop_upper_price": 103,
        "fee_rate": 0,
        "slippage_pct": 0,
    }


def test_contract_grid_params_are_normalized_and_clamped():
    from strategies.contract_grid import normalize_contract_grid_params

    params = normalize_contract_grid_params({
        "cycle": "short",
        "grid_mode": "bad",
        "lower_price": 100,
        "upper_price": 110,
        "grid_count": 999,
        "total_margin_usdt": 1,
        "leverage": 999,
        "stop_lower_price": 105,
        "stop_upper_price": 101,
        "fee_rate": 1,
        "slippage_pct": 20,
        "risk": {"max_concurrent": 0, "max_daily_per_symbol": 999, "max_daily_loss_pct": 0.1},
    })

    assert params["bar"] == "15m"
    assert params["grid_mode"] == "neutral"
    assert params["grid_count"] == 200
    assert params["total_margin_usdt"] == 5.0
    assert params["leverage"] == 100
    assert params["stop_lower_price"] < params["lower_price"]
    assert params["stop_upper_price"] > params["upper_price"]
    assert params["fee_rate"] == 0.01
    assert params["slippage_pct"] == 2.0
    assert params["risk"]["max_concurrent"] == 1
    assert params["risk"]["max_daily_per_symbol"] == 50


@pytest.mark.parametrize("mode", ["neutral", "long", "short"])
def test_contract_grid_backtest_trades_for_all_modes(mode):
    from core.contract_grid_backtester import run_contract_grid_backtest

    if mode == "short":
        df = _frame([
            (100.8, 101.0, 100.8, 101.0),
            (101.0, 101.0, 99.9, 100.0),
        ])
    else:
        df = _frame([
            (100.0, 100.0, 99.0, 99.2),
            (99.2, 100.1, 99.2, 100.0),
        ])

    result = run_contract_grid_backtest(
        df,
        symbol="BTC-USDT-SWAP",
        params=_params(mode),
        leverage=2,
        fee_rate=0,
        slippage_pct=0,
    )

    assert result["summary"]["total_trades"] >= 1
    assert result["summary"]["total_pnl"] > 0
    assert result["trades"][0]["direction"] in {"long", "short"}


def test_contract_grid_backtest_stops_outside_range():
    from core.contract_grid_backtester import run_contract_grid_backtest

    df = _frame([
        (100.0, 100.0, 99.0, 99.2),
        (99.2, 99.3, 96.5, 97.0),
    ])

    result = run_contract_grid_backtest(
        df,
        symbol="BTC-USDT-SWAP",
        params=_params("long"),
        leverage=2,
        fee_rate=0,
        slippage_pct=0,
    )

    assert result["summary"]["stopped_reason"] == "跌破网格下沿止损"
    assert result["summary"]["total_trades"] >= 1


def test_ai_generated_contract_grid_params_are_clamped(monkeypatch):
    from api import contract_grid
    from ai.analyzer import AIAnalyzer

    async def fake_generate(self, request):
        return {
            "cycle": "long",
            "grid_mode": "short",
            "lower_price": 100,
            "upper_price": 110,
            "grid_count": 999,
            "total_margin_usdt": 1,
            "leverage": 999,
            "stop_lower_price": 200,
            "stop_upper_price": 101,
            "risk": {"max_concurrent": 0, "max_daily_per_symbol": 999, "max_daily_loss_pct": 0.1},
        }

    monkeypatch.setattr(AIAnalyzer, "generate_contract_grid_params", fake_generate)
    response = asyncio.run(contract_grid.generate_contract_grid_params(
        contract_grid.ContractGridParamGenerateRequest(symbol="btc-usdt-swap")
    ))

    params = response["params"]
    assert params["cycle"] == "long"
    assert params["bar"] == "4H"
    assert params["grid_mode"] == "short"
    assert params["grid_count"] == 200
    assert params["total_margin_usdt"] == 5.0
    assert params["leverage"] == 100
    assert params["stop_lower_price"] < 100
    assert params["stop_upper_price"] > 110


def test_contract_grid_backtest_uses_cached_candles_and_saves_record(monkeypatch):
    from api import backtests
    from db.database import _init_tables

    async def run():
        db = await aiosqlite.connect(":memory:")
        db.row_factory = aiosqlite.Row
        await _init_tables(db)

        df = _frame([
            (100.0, 100.0, 99.0, 99.2),
            (99.2, 100.1, 99.2, 100.0),
        ])
        await backtests._save_cached_candles(db, "BTC-USDT-SWAP", "1H", df)

        async def fake_get_db():
            return db

        monkeypatch.setattr(backtests, "get_db", fake_get_db)
        result = await backtests.backtest_contract_grid(backtests.ContractGridBacktestRequest(
            symbol="BTC-USDT-SWAP",
            cycle="medium",
            start=df.iloc[0]["ts"].isoformat(),
            end=df.iloc[-1]["ts"].isoformat(),
            params=_params("long"),
            leverage=2,
            fee_rate=0,
            slippage_pct=0,
        ))
        records = await backtests.list_contract_grid_backtest_records(
            symbol="BTC-USDT-SWAP",
            limit=20,
            offset=0,
        )
        detail = await backtests.get_contract_grid_backtest_record(result["record_id"])
        await db.close()
        return result, records, detail

    result, records, detail = asyncio.run(run())
    assert result["record_id"] > 0
    assert result["summary"]["total_trades"] >= 1
    assert records["total"] == 1
    assert detail["result"]["summary"]["total_trades"] >= 1


def test_contract_grid_strategy_cannot_start(monkeypatch):
    from api import strategies
    from db.database import _init_tables

    async def run():
        db = await aiosqlite.connect(":memory:")
        db.row_factory = aiosqlite.Row
        await _init_tables(db)

        async def fake_get_db():
            return db

        monkeypatch.setattr(strategies, "get_db", fake_get_db)
        with pytest.raises(HTTPException) as exc:
            await strategies.start_strategy("contract_grid")
        await db.close()
        return exc.value

    exc = asyncio.run(run())
    assert exc.status_code == 400
    assert "仅支持参数配置和回测" in exc.detail
