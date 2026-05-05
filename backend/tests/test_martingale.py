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


def _frame(closes: list[float]) -> pd.DataFrame:
    rows = []
    for i, close in enumerate(closes):
        open_price = closes[i - 1] if i > 0 else close
        high = max(open_price, close) + 0.2
        low = min(open_price, close) - 0.2
        rows.append({
            "ts": pd.Timestamp("2026-01-01") + pd.Timedelta(minutes=15 * i),
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "vol": 100,
            "volCcy": 100,
            "volCcyQuote": 100,
            "confirm": 1,
        })
    return pd.DataFrame(rows)


def test_martingale_strategy_triggers_long_on_oversold_band_break():
    from strategies.martingale_contract import MartingaleContractStrategy

    df = _frame([100] * 30 + [95, 90, 82])
    signal = MartingaleContractStrategy().check_signal(df, {
        "boll_period": 20,
        "boll_std": 2,
        "rsi_period": 14,
        "long_rsi_max": 35,
        "direction": "both",
    })

    assert signal is not None
    assert signal["direction"] == "long"
    assert signal["managed_exit"] is True
    assert signal["martingale"] is True


def test_martingale_strategy_triggers_short_on_overbought_band_break():
    from strategies.martingale_contract import MartingaleContractStrategy

    df = _frame([100] * 30 + [105, 110, 118])
    signal = MartingaleContractStrategy().check_signal(df, {
        "boll_period": 20,
        "boll_std": 2,
        "rsi_period": 14,
        "short_rsi_min": 65,
        "direction": "both",
    })

    assert signal is not None
    assert signal["direction"] == "short"


def test_martingale_backtest_adds_leg_and_closes_trade():
    from core.martingale_backtester import run_martingale_backtest

    df = _frame([100, 99, 100])

    result = run_martingale_backtest(
        df,
        symbol="BTC-USDT-SWAP",
        params={
            "cycle": "short",
            "direction": "long",
            "add_trigger_type": "pct",
            "add_trigger_value": 1.0,
            "take_profit_type": "pct",
            "take_profit_value": 0.4,
            "initial_margin_usdt": 20,
            "add_margin_usdt": 20,
            "max_add_count": 2,
            "hard_stop_pct": 10,
            "cooldown_bars": 0,
        },
        leverage=3,
        base_order_usdt=20,
        fee_rate=0,
        slippage_pct=0,
    )

    assert result["summary"]["total_trades"] == 1
    assert result["summary"]["max_level"] == 2
    assert result["summary"]["max_add_count"] == 1
    assert result["trades"][0]["levels"] == 2
    assert result["trades"][0]["liquidation_price"] > 0
    assert result["trades"][0]["pnl"] > 0


def test_ai_generated_martingale_params_are_clamped(monkeypatch):
    from api import martingale
    from ai.analyzer import AIAnalyzer

    async def fake_generate(self, request):
        return {
            "cycle": "medium",
            "direction": "both",
            "add_trigger_type": "pct",
            "add_trigger_value": 0.001,
            "take_profit_type": "pct",
            "take_profit_value": 999999,
            "hard_stop_pct": 0.1,
            "max_position_usdt": 300,
            "initial_margin_usdt": 0,
            "add_margin_usdt": 0,
            "max_add_count": 999,
            "risk": {"max_concurrent": 0, "max_daily_per_symbol": 999, "max_daily_loss_pct": 0.1},
        }

    monkeypatch.setattr(AIAnalyzer, "generate_martingale_params", fake_generate)
    response = asyncio.run(martingale.generate_martingale_params(
        martingale.MartingaleParamGenerateRequest(symbol="btc-usdt-swap")
    ))

    params = response["params"]
    assert params["cycle"] == "medium"
    assert params["bar"] == "4H"
    assert params["add_trigger_value"] == 0.01
    assert params["take_profit_value"] == 5.0
    assert params["take_profit_pct"] == 5.0
    assert params["hard_stop_pct"] == 1.0
    assert params["initial_margin_usdt"] == 1.0
    assert params["add_margin_usdt"] == 1.0
    assert params["max_add_count"] == 100
    assert params["max_levels"] == 101
    assert params["max_position_usdt"] == 101.0
    assert params["risk"]["max_concurrent"] == 1
    assert params["risk"]["max_daily_per_symbol"] == 50


def test_backtest_candle_cache_upserts_and_loads():
    from api import backtests
    from db.database import _init_tables

    async def run():
        db = await aiosqlite.connect(":memory:")
        db.row_factory = aiosqlite.Row
        await _init_tables(db)
        df = _frame([100, 101, 102, 103, 104])
        start_ms = backtests._timestamp_ms(df.iloc[0]["ts"])
        end_ms = backtests._timestamp_ms(df.iloc[-1]["ts"])

        saved_first = await backtests._save_cached_candles(db, "BTC-USDT-SWAP", "1H", df)
        saved_second = await backtests._save_cached_candles(db, "BTC-USDT-SWAP", "1H", df)
        loaded = await backtests._load_cached_df(db, "BTC-USDT-SWAP", "1H", start_ms, end_ms)
        coverage = await backtests._build_coverage_response(
            db,
            "BTC-USDT-SWAP",
            backtests._normalized_cycle_params("short"),
            start_ms,
            end_ms,
        )
        await db.close()
        return saved_first, saved_second, loaded, coverage

    saved_first, saved_second, loaded, coverage = asyncio.run(run())
    assert saved_first == 5
    assert saved_second == 5
    assert len(loaded) == 5
    assert coverage["cached_count"] == 5


def test_martingale_backtest_uses_cached_candles_and_saves_record(monkeypatch):
    from api import backtests
    from db.database import _init_tables

    async def run():
        db = await aiosqlite.connect(":memory:")
        db.row_factory = aiosqlite.Row
        await _init_tables(db)

        df = _frame([100, 99, 100])
        await backtests._save_cached_candles(db, "BTC-USDT-SWAP", "1H", df)

        async def fake_get_db():
            return db

        monkeypatch.setattr(backtests, "get_db", fake_get_db)
        result = await backtests.backtest_martingale(backtests.MartingaleBacktestRequest(
            symbol="BTC-USDT-SWAP",
            cycle="short",
            start=df.iloc[0]["ts"].isoformat(),
            end=df.iloc[-1]["ts"].isoformat(),
            params={
                "cycle": "short",
                "direction": "long",
                "add_trigger_type": "pct",
                "add_trigger_value": 1.0,
                "take_profit_type": "pct",
                "take_profit_value": 0.4,
                "initial_margin_usdt": 20,
                "add_margin_usdt": 20,
                "max_add_count": 2,
                "hard_stop_pct": 10,
                "cooldown_bars": 0,
            },
            leverage=3,
            base_order_usdt=20,
            fee_rate=0,
            slippage_pct=0,
        ))
        records = await backtests.list_martingale_backtest_records(
            symbol="BTC-USDT-SWAP",
            limit=20,
            offset=0,
        )
        detail = await backtests.get_martingale_backtest_record(result["record_id"])
        await db.close()
        return result, records, detail

    result, records, detail = asyncio.run(run())
    assert result["record_id"] > 0
    assert result["summary"]["total_trades"] == 1
    assert records["total"] == 1
    assert records["items"][0]["id"] == result["record_id"]
    assert detail["result"]["summary"]["total_trades"] == 1


def test_martingale_backtest_rejects_insufficient_cached_candles(monkeypatch):
    from api import backtests
    from db.database import _init_tables

    async def run():
        db = await aiosqlite.connect(":memory:")
        db.row_factory = aiosqlite.Row
        await _init_tables(db)
        df = _frame([100])
        await backtests._save_cached_candles(db, "BTC-USDT-SWAP", "1H", df)

        async def fake_get_db():
            return db

        monkeypatch.setattr(backtests, "get_db", fake_get_db)
        with pytest.raises(HTTPException) as exc:
            await backtests.backtest_martingale(backtests.MartingaleBacktestRequest(
                symbol="BTC-USDT-SWAP",
                cycle="short",
                start=df.iloc[0]["ts"].isoformat(),
                end=(df.iloc[-1]["ts"] + pd.Timedelta(hours=1)).isoformat(),
                params={"cycle": "short"},
            ))
        await db.close()
        return exc.value

    exc = asyncio.run(run())
    assert exc.status_code == 400
    assert "K 线数量不足" in exc.detail
