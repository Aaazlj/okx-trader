"""
Order flow analysis wrapper.

Wraps the OrderFlowEngine from the kline-indicator skill to accept
OKXClient data directly and return clean analysis results.
"""
import sys
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Try to import OrderFlowEngine from the kline-indicator skill script.
# In Docker / CI the .claude/skills/ directory may not exist — degrade gracefully.
OrderFlowEngine = None

try:
    _SKILL_SCRIPTS_DIR = os.path.abspath(os.path.join(
        os.path.dirname(__file__),
        "..", ".claude", "skills", "kline-indicator", "scripts",
    ))
    _script_path = os.path.join(_SKILL_SCRIPTS_DIR, "kline_orderflow.py")
    if os.path.isfile(_script_path):
        if _SKILL_SCRIPTS_DIR not in sys.path:
            sys.path.insert(0, _SKILL_SCRIPTS_DIR)
        from kline_orderflow import OrderFlowEngine  # noqa: E402
    else:
        logger.info("kline_orderflow.py not found at %s — order flow analysis disabled", _script_path)
except Exception as exc:
    logger.warning("Failed to load kline_orderflow: %s — order flow analysis disabled", exc)


def _build_orderbook_for_engine(raw_orderbook: dict) -> dict:
    """Convert OKXClient orderbook format to what OrderFlowEngine expects.

    OKXClient returns: {"asks": [[price_str, qty_str, ...], ...],
                        "bids": [[price_str, qty_str, ...], ...], "ts": int}
    OrderFlowEngine._extract_levels reads data["asks"] / data["bids"]
    and casts to float -- the OKXClient format is already compatible.
    """
    return raw_orderbook


def _build_trades_for_engine(raw_trades: list) -> dict:
    """Convert OKXClient trades format to what OrderFlowEngine expects.

    OKXClient returns: [{"side": "buy", "size": 0.5, "price": 50000.0, "ts": 123}, ...]
    OrderFlowEngine._extract_trades expects: {"data": [{"px": ..., "sz": ..., "side": ..., "ts": ...}, ...]}
    or a list of dicts with px/sz keys.
    """
    converted = []
    for t in raw_trades:
        converted.append({
            "px": str(t.get("price", 0)),
            "sz": str(t.get("size", 0)),
            "side": t.get("side", ""),
            "ts": t.get("ts", 0),
        })
    return {"data": converted}


def _build_funding_for_engine(raw_funding: Optional[dict]) -> dict:
    """Convert OKXClient funding format to what OrderFlowEngine expects.

    OKXClient returns: {"funding_rate": 0.0001, "funding_time": 123, ...}
    OrderFlowEngine expects: {"data": [{"fundingRate": "0.0001", "fundingTime": "123", ...}]}
    or a top-level dict with fundingRate key.
    """
    if not raw_funding:
        return {}
    return {
        "fundingRate": str(raw_funding.get("funding_rate", 0)),
        "fundingTime": str(raw_funding.get("funding_time", "")),
    }


def _build_oi_for_engine(raw_oi: Optional[dict]) -> dict:
    """Convert OKXClient OI format to what OrderFlowEngine expects.

    OKXClient returns: {"oi": 12345.67, "oiCcy": 12345.67, "ts": 123}
    OrderFlowEngine expects: {"data": [{"oi": "12345.67", "oiUsd": "...", "ts": "..."}]}
    or a top-level dict with oi key.
    """
    if not raw_oi:
        return {}
    return {
        "oi": str(raw_oi.get("oi", 0)),
        "oiCcy": str(raw_oi.get("oiCcy", 0)),
        "ts": str(raw_oi.get("ts", "")),
    }


def compute_order_flow_score(client, symbol: str) -> Optional[dict]:
    """Run full order flow analysis for a symbol using OKXClient data.

    Args:
        client: OKXClient instance with market data methods.
        symbol: Instrument ID, e.g. "BTC-USDT-SWAP".

    Returns:
        dict with keys: score (0-100), verdict, orderbook_summary,
        trade_flow_summary, signals.
        Returns None on failure or when skill script is unavailable.
    """
    if OrderFlowEngine is None:
        return None

    try:
        # Fetch raw data from OKXClient
        raw_orderbook = client.get_orderbook_depth(symbol, sz="20")
        raw_trades = client.get_recent_trades(symbol, limit=100)
        raw_funding = client.get_funding_rate(symbol)
        raw_oi = client.get_open_interest(symbol)
    except Exception as e:
        logger.error("Failed to fetch order flow data for %s: %s", symbol, e)
        return None

    # Convert to engine format
    orderbook = _build_orderbook_for_engine(raw_orderbook)
    trades = _build_trades_for_engine(raw_trades)
    funding = _build_funding_for_engine(raw_funding)
    oi = _build_oi_for_engine(raw_oi)

    # Extract coin name from symbol (e.g. "BTC-USDT-SWAP" -> "BTC")
    coin = symbol.split("-")[0] if symbol else "BTC"

    try:
        engine = OrderFlowEngine(orderbook, trades, funding, oi, coin=coin)
        result = engine.run()
    except Exception as e:
        logger.error("OrderFlowEngine failed for %s: %s", symbol, e)
        return None

    scoring = result.get("scoring", {})
    return {
        "score": scoring.get("score", 0),
        "verdict": scoring.get("verdict", "neutral"),
        "orderbook_summary": result.get("orderbook", {}),
        "trade_flow_summary": result.get("trade_flow", {}),
        "signals": scoring.get("signals", []),
    }
