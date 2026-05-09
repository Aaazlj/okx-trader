"""
Thin wrapper around the kline-indicator skill's IndicatorEngine.

Accepts a pandas DataFrame with columns [ts, open, high, low, close, vol]
and returns indicator results as a plain dict. Two modes:

  - "summary": condensed key values from trend/momentum/volume/volatility/patterns
    (suitable for injection into AI prompts)
  - "full": every computed indicator across all categories

Dependencies: pandas (project already depends on it), stdlib-only IndicatorEngine.
"""

import os
from typing import Dict

import pandas as pd

# ---------------------------------------------------------------------------
# Import IndicatorEngine from the kline-indicator skill script (stdlib only).
# The script has a trailing bare identifier (`EXT_INDICATORS_ENGINE`) that
# raises NameError on normal import.  We use importlib to load the module
# and catch that error -- the class is already defined by that point.
# ---------------------------------------------------------------------------
import importlib.util
import logging

logger = logging.getLogger(__name__)

# Try to load IndicatorEngine from the kline-indicator skill script.
# In Docker / CI the .claude/skills/ directory may not exist — degrade gracefully.
IndicatorEngine = None

try:
    _SKILL_SCRIPTS_DIR = os.path.normpath(os.path.join(
        os.path.dirname(__file__),
        os.pardir, ".claude", "skills", "kline-indicator", "scripts",
    ))
    _script_path = os.path.join(_SKILL_SCRIPTS_DIR, "kline_ext_indicators.py")
    if os.path.isfile(_script_path):
        _spec = importlib.util.spec_from_file_location(
            "kline_ext_indicators", _script_path,
        )
        _mod = importlib.util.module_from_spec(_spec)
        try:
            _spec.loader.exec_module(_mod)
        except NameError:
            pass  # trailing sentinel token; class already loaded
        IndicatorEngine = _mod.IndicatorEngine
    else:
        logger.info("kline_ext_indicators.py not found at %s — extended indicators disabled", _script_path)
except Exception as exc:
    logger.warning("Failed to load kline_ext_indicators: %s — extended indicators disabled", exc)


def _df_to_candles(df: pd.DataFrame) -> list:
    """Convert a DataFrame to the list-of-lists format expected by IndicatorEngine.

    Required columns: ts, open, high, low, close, vol
    Each row becomes [ts, open, high, low, close, vol].
    """
    rows = []
    for _, r in df.iterrows():
        rows.append([
            float(r["ts"]),
            float(r["open"]),
            float(r["high"]),
            float(r["low"]),
            float(r["close"]),
            float(r["vol"]),
        ])
    return rows


# Keys to pick per category when building a summary dict.  Chosen to cover
# the most decision-relevant values without bloating the prompt.
_SUMMARY_KEYS: Dict[str, list] = {
    "trend": [
        "ema_20", "ema_50", "sma_200",
        "supertrend_14_2", "adx_14", "plus_di_14", "minus_di_14",
        "ichimoku", "parabolic_sar",
    ],
    "momentum": [
        "rsi_14", "macd_12_26_9", "macd_signal_12_26_9", "macd_hist_12_26_9",
        "stoch_k_14", "stoch_d_14", "cci_14", "williams_r_14",
        "roc_14", "ultimate_osc",
    ],
    "volume": [
        "obv", "vwap", "mfi_14", "cmf_20", "relative_volume",
        "vol_ratio_20",
    ],
    "volatility": [
        "atr_14", "natr_14",
        "bb_upper_20_2.0", "bb_mid_20_2.0", "bb_lower_20_2.0", "bb_pctb_20_2.0",
        "true_range",
    ],
    "patterns": None,  # kept whole -- it's already compact
}


def _pick_summary(engine: IndicatorEngine) -> dict:
    """Run the five core categories and extract key values for a compact summary."""
    trend = engine.compute_trend()
    momentum = engine.compute_momentum()
    volume = engine.compute_volume()
    volatility = engine.compute_volatility()
    patterns = engine.compute_patterns()

    def _select(src: dict, keys: list | None) -> dict:
        if keys is None:
            return src
        return {k: src[k] for k in keys if k in src}

    return {
        "trend": _select(trend, _SUMMARY_KEYS["trend"]),
        "momentum": _select(momentum, _SUMMARY_KEYS["momentum"]),
        "volume": _select(volume, _SUMMARY_KEYS["volume"]),
        "volatility": _select(volatility, _SUMMARY_KEYS["volatility"]),
        "patterns": patterns,
    }


def _pick_full(engine: IndicatorEngine) -> dict:
    """Run all indicator categories and return everything."""
    return engine.compute_all()


class KlineEngine:
    """Wrapper that turns a pandas OHLCV DataFrame into indicator results.

    Usage::

        engine = KlineEngine()
        result = engine.compute_extended(df, mode="summary")
    """

    def __init__(self) -> None:
        pass

    def compute_extended(
        self,
        df: pd.DataFrame,
        mode: str = "summary",
    ) -> dict:
        """Compute indicators from *df* and return results as a dict.

        Parameters
        ----------
        df : pd.DataFrame
            Must contain columns: ts, open, high, low, close, vol.
        mode : {"summary", "full"}
            "summary" returns condensed key values across the five core
            categories (trend, momentum, volume, volatility, patterns).
            "full" returns every computed indicator (including divergence,
            structure, advanced volatility, alpha101, alpha191).

        Returns
        -------
        dict
            Categorized indicator values, or an error dict on bad input.
        """
        if IndicatorEngine is None:
            return {"error": "IndicatorEngine not available (skill script not loaded)"}

        # --- validate input ---
        if df is None or df.empty:
            return {"error": "empty DataFrame"}

        required = {"ts", "open", "high", "low", "close", "vol"}
        missing = required - set(df.columns)
        if missing:
            return {"error": f"missing columns: {sorted(missing)}"}

        if len(df) < 5:
            return {"error": "need at least 5 candles", "count": len(df)}

        # --- convert & compute ---
        candles = _df_to_candles(df)
        engine = IndicatorEngine(candles)

        if mode == "full":
            return _pick_full(engine)
        # default to summary
        return _pick_summary(engine)
