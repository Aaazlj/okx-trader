"""
Smart Money Concepts (SMC) detector — Order Blocks, Fair Value Gaps, Liquidity Sweeps.
Pure pandas implementation, no external dependencies beyond pandas/numpy.
"""
import numpy as np
import pandas as pd

from indicators.technical import calc_atr

# Minimum bars required for any meaningful analysis
_MIN_BARS = 30


class SMCDetector:
    """Detect institutional footprint: Order Blocks, FVGs, and Liquidity Sweeps."""

    def __init__(self):
        pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect(
        self,
        df_1h: pd.DataFrame,
        df_4h: pd.DataFrame = None,
        funding_rate: float = None,
    ) -> dict:
        """Run full SMC detection on 1h (and optional 4h) candle data.

        Args:
            df_1h: 1h candles with columns ts, open, high, low, close, vol.
            df_4h: Optional 4h candles for higher-timeframe order blocks.
            funding_rate: Optional current funding rate (e.g. 0.0001 = 0.01%).

        Returns:
            dict with keys: order_blocks, fair_value_gaps, liquidity_sweeps,
                            confidence, analysis
        """
        result = {
            "order_blocks": [],
            "fair_value_gaps": [],
            "liquidity_sweeps": [],
            "confidence": 0,
            "analysis": "",
        }

        if df_1h is None or len(df_1h) < _MIN_BARS:
            result["analysis"] = "Insufficient 1h data for SMC detection"
            return result

        df_1h = df_1h.copy().reset_index(drop=True)

        # ATR on 1h
        atr_1h = self._calc_atr_series(df_1h, period=14)
        current_atr = atr_1h.iloc[-1] if not np.isnan(atr_1h.iloc[-1]) else 0

        # Order blocks: prefer 4h if available, fall back to 1h
        obs = []
        if df_4h is not None and len(df_4h) >= _MIN_BARS:
            df_4h = df_4h.copy().reset_index(drop=True)
            atr_4h = self._calc_atr_series(df_4h, period=14)
            obs = self._detect_order_blocks(df_4h, atr_4h)
        obs += self._detect_order_blocks(df_1h, atr_1h)
        result["order_blocks"] = obs[:6]  # cap total at 6

        # FVGs on 1h
        result["fair_value_gaps"] = self._detect_fvgs(df_1h, current_atr)

        # Liquidity sweeps on 1h
        result["liquidity_sweeps"] = self._detect_liquidity_sweeps(df_1h)

        # Confidence
        result["confidence"] = self._compute_confidence(
            df_1h, result["order_blocks"], result["fair_value_gaps"],
            result["liquidity_sweeps"], funding_rate,
        )

        result["analysis"] = self._build_analysis(result)
        return result

    # ------------------------------------------------------------------
    # Order Blocks
    # ------------------------------------------------------------------

    def _detect_order_blocks(
        self, df: pd.DataFrame, atr: pd.Series
    ) -> list[dict]:
        """Detect bullish/bearish order blocks.

        Bullish OB: last bearish candle before a rally > 1.5x ATR14.
        Bearish OB: last bullish candle before a drop > 1.5x ATR14.
        Up to 3 active per direction.
        """
        n = len(df)
        if n < 5:
            return []

        opens = df["open"].values
        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values
        vols = df["vol"].values
        atr_vals = atr.values

        bullish_obs: list[dict] = []
        bearish_obs: list[dict] = []

        for i in range(n - 2):
            cur_atr = atr_vals[i]
            if np.isnan(cur_atr) or cur_atr <= 0:
                continue

            # Bullish OB: bar i is bearish, then price rallies
            is_bearish_bar = closes[i] < opens[i]
            if is_bearish_bar:
                # Check subsequent rally strength (bars i+1 .. i+3)
                max_gain = 0.0
                for j in range(i + 1, min(i + 4, n)):
                    gain = (closes[j] - closes[i]) / cur_atr
                    if gain > max_gain:
                        max_gain = gain
                if max_gain > 1.5:
                    # Check OB hasn't been invalidated (price traded through it)
                    invalidated = False
                    for j in range(i + 1, n):
                        if closes[j] < lows[i]:
                            invalidated = True
                            break
                    if not invalidated:
                        bullish_obs.append({
                            "type": "bullish",
                            "high": float(highs[i]),
                            "low": float(lows[i]),
                            "volume": float(vols[i]),
                            "age_bars": n - 1 - i,
                            "strength": round(min(max_gain / 1.5, 3.0), 2),
                            "bar_index": i,
                        })

            # Bearish OB: bar i is bullish, then price drops
            is_bullish_bar = closes[i] > opens[i]
            if is_bullish_bar:
                max_drop = 0.0
                for j in range(i + 1, min(i + 4, n)):
                    drop = (closes[i] - closes[j]) / cur_atr
                    if drop > max_drop:
                        max_drop = drop
                if max_drop > 1.5:
                    invalidated = False
                    for j in range(i + 1, n):
                        if closes[j] > highs[i]:
                            invalidated = True
                            break
                    if not invalidated:
                        bearish_obs.append({
                            "type": "bearish",
                            "high": float(highs[i]),
                            "low": float(lows[i]),
                            "volume": float(vols[i]),
                            "age_bars": n - 1 - i,
                            "strength": round(min(max_drop / 1.5, 3.0), 2),
                            "bar_index": i,
                        })

        # Keep the 3 most recent (closest to current price) per direction
        bullish_obs.sort(key=lambda x: x["age_bars"])
        bearish_obs.sort(key=lambda x: x["age_bars"])
        return bullish_obs[:3] + bearish_obs[:3]

    # ------------------------------------------------------------------
    # Fair Value Gaps
    # ------------------------------------------------------------------

    def _detect_fvgs(self, df: pd.DataFrame, current_atr: float) -> list[dict]:
        """Detect Fair Value Gaps on the given timeframe.

        Bullish FVG: candle[N].low > candle[N-2].high
        Bearish FVG: candle[N].high < candle[N-2].low
        Minimum gap: 0.3 * ATR14.
        """
        n = len(df)
        if n < 3 or current_atr <= 0:
            return []

        highs = df["high"].values
        lows = df["low"].values
        min_gap = 0.3 * current_atr
        fvgs: list[dict] = []

        for i in range(2, n):
            # Bullish FVG
            gap_bottom = highs[i - 2]
            gap_top = lows[i]
            if gap_top > gap_bottom and (gap_top - gap_bottom) >= min_gap:
                # Check if still unfilled (price hasn't traded back into it)
                filled = False
                for j in range(i + 1, n):
                    if lows[j] <= gap_bottom:
                        filled = True
                        break
                if not filled:
                    fvgs.append({
                        "type": "bullish",
                        "top": float(gap_top),
                        "bottom": float(gap_bottom),
                        "size_pct": round((gap_top - gap_bottom) / current_atr * 100, 2),
                        "age_bars": n - 1 - i,
                    })

            # Bearish FVG
            gap_top_b = lows[i - 2]
            gap_bottom_b = highs[i]
            if gap_top_b > gap_bottom_b and (gap_top_b - gap_bottom_b) >= min_gap:
                filled = False
                for j in range(i + 1, n):
                    if highs[j] >= gap_top_b:
                        filled = True
                        break
                if not filled:
                    fvgs.append({
                        "type": "bearish",
                        "top": float(gap_top_b),
                        "bottom": float(gap_bottom_b),
                        "size_pct": round((gap_top_b - gap_bottom_b) / current_atr * 100, 2),
                        "age_bars": n - 1 - i,
                    })

        # Keep most recent 5
        fvgs.sort(key=lambda x: x["age_bars"])
        return fvgs[:5]

    # ------------------------------------------------------------------
    # Liquidity Sweeps
    # ------------------------------------------------------------------

    def _detect_liquidity_sweeps(self, df: pd.DataFrame) -> list[dict]:
        """Detect liquidity sweeps: wick beyond recent swing H/L but close inside.

        Requires volume > 1.5x 20-period average at sweep candle.
        """
        n = len(df)
        if n < 25:
            return []

        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values
        vols = df["vol"].values

        sweeps: list[dict] = []

        # Pre-compute 20-period volume average
        vol_avg = pd.Series(vols).rolling(20, min_periods=10).mean().values

        # Find recent swing highs and lows (5-bar lookback)
        swing_highs = self._find_swings(highs, n, swing_type="high")
        swing_lows = self._find_swings(lows, n, swing_type="low")

        # Scan last 10 bars for sweeps
        for i in range(max(n - 10, 5), n):
            if np.isnan(vol_avg[i]) or vol_avg[i] <= 0:
                continue
            vol_ratio = vols[i] / vol_avg[i]

            # High sweep: wick above swing high but close below
            for sh_idx, sh_val in swing_highs:
                if sh_idx >= i:
                    continue
                if highs[i] > sh_val and closes[i] < sh_val and vol_ratio > 1.5:
                    sweeps.append({
                        "type": "high_sweep",
                        "level": float(sh_val),
                        "wick_high": float(highs[i]),
                        "wick_low": float(lows[i]),
                        "close": float(closes[i]),
                        "volume_ratio": round(float(vol_ratio), 2),
                        "bar_index": i,
                    })
                    break  # one sweep per bar

            # Low sweep: wick below swing low but close above
            for sl_idx, sl_val in swing_lows:
                if sl_idx >= i:
                    continue
                if lows[i] < sl_val and closes[i] > sl_val and vol_ratio > 1.5:
                    sweeps.append({
                        "type": "low_sweep",
                        "level": float(sl_val),
                        "wick_high": float(highs[i]),
                        "wick_low": float(lows[i]),
                        "close": float(closes[i]),
                        "volume_ratio": round(float(vol_ratio), 2),
                        "bar_index": i,
                    })
                    break

        return sweeps

    # ------------------------------------------------------------------
    # Confidence Scoring
    # ------------------------------------------------------------------

    def _compute_confidence(
        self,
        df: pd.DataFrame,
        order_blocks: list[dict],
        fvgs: list[dict],
        sweeps: list[dict],
        funding_rate: float = None,
    ) -> int:
        """Compute 0-100 confidence score per SKILL.md spec.

        Dimensions:
          - Market structure alignment (25 pts)
          - OB quality (20 pts)
          - FVG presence (25 pts)
          - Liquidity sweep recency (20 pts)
          - Funding rate health (10 pts)
        """
        score = 0
        n = len(df)
        closes = df["close"].values
        current_price = closes[-1] if n > 0 else 0

        # --- Market structure alignment (25 pts) ---
        # Simple proxy: count how many obs support the current direction
        bullish_obs = [o for o in order_blocks if o["type"] == "bullish"]
        bearish_obs = [o for o in order_blocks if o["type"] == "bearish"]
        bullish_count = len(bullish_obs)
        bearish_count = len(bearish_obs)

        if bullish_count > 0 and bearish_count > 0:
            # Both present — check which is closer / stronger
            nearest_bull = min(bullish_obs, key=lambda x: x["age_bars"])
            nearest_bear = min(bearish_obs, key=lambda x: x["age_bars"])
            if nearest_bull["strength"] > nearest_bear["strength"]:
                score += 12
            else:
                score += 12
        elif bullish_count > 0 or bearish_count > 0:
            score += 25  # single direction dominates
        else:
            score += 0

        # --- OB quality (20 pts) ---
        if order_blocks:
            best_ob = max(order_blocks, key=lambda x: x["strength"])
            # Strength > 2 means volume was significant
            if best_ob["strength"] >= 2.0:
                score += 20
            elif best_ob["strength"] >= 1.5:
                score += 12
            else:
                score += 5

        # --- FVG presence (25 pts) ---
        # Check if price is inside any active FVG
        in_fvg = False
        fvg_bonus = 0
        for fvg in fvgs:
            if fvg["bottom"] <= current_price <= fvg["top"]:
                in_fvg = True
                break

        if in_fvg:
            score += 20
            # Bonus: FVG inside an OB (dual confirmation)
            for fvg in fvgs:
                for ob in order_blocks:
                    if (fvg["type"] == ob["type"]
                            and fvg["bottom"] >= ob["low"]
                            and fvg["top"] <= ob["high"]):
                        fvg_bonus = 5
                        break
            score += fvg_bonus
        elif fvgs:
            score += 10  # FVGs exist but price not in one

        # --- Liquidity sweep recency (20 pts) ---
        if sweeps:
            most_recent_bar = max(s["bar_index"] for s in sweeps)
            recency = n - 1 - most_recent_bar
            if recency <= 3:
                score += 20
            elif recency <= 6:
                score += 10

        # --- Funding rate health (10 pts) ---
        if funding_rate is not None:
            abs_rate = abs(funding_rate)
            if abs_rate < 0.0005:
                score += 10
            elif abs_rate < 0.0008:
                score += 5

        return min(score, 100)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _calc_atr_series(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Compute ATR and return as a Series aligned with df index."""
        atr_arr = calc_atr(
            df["high"].values.astype(float),
            df["low"].values.astype(float),
            df["close"].values.astype(float),
            period=period,
        )
        return pd.Series(atr_arr, index=df.index)

    @staticmethod
    def _find_swings(values: np.ndarray, n: int, swing_type: str = "high",
                     lookback: int = 5) -> list[tuple[int, float]]:
        """Find swing highs or lows in the data.

        A swing high: bar i's value is the max in [i-lookback, i+lookback].
        A swing low: bar i's value is the min in the same range.
        Returns list of (index, value).
        """
        swings = []
        for i in range(lookback, n - lookback):
            window = values[i - lookback: i + lookback + 1]
            if swing_type == "high" and values[i] == np.max(window):
                swings.append((i, float(values[i])))
            elif swing_type == "low" and values[i] == np.min(window):
                swings.append((i, float(values[i])))
        return swings

    @staticmethod
    def _build_analysis(result: dict) -> str:
        """Build a human-readable summary string."""
        obs = result["order_blocks"]
        fvgs = result["fair_value_gaps"]
        sweeps = result["liquidity_sweeps"]
        conf = result["confidence"]

        parts = []
        parts.append(f"Confidence: {conf}/100")

        if obs:
            bull = [o for o in obs if o["type"] == "bullish"]
            bear = [o for o in obs if o["type"] == "bearish"]
            parts.append(f"Order Blocks: {len(bull)} bullish, {len(bear)} bearish")
        else:
            parts.append("Order Blocks: none")

        if fvgs:
            parts.append(f"FVGs: {len(fvgs)} active")
        else:
            parts.append("FVGs: none")

        if sweeps:
            parts.append(f"Liquidity Sweeps: {len(sweeps)} detected")
        else:
            parts.append("Liquidity Sweeps: none")

        if conf >= 75:
            parts.append("Signal: HIGH confidence — standard position allowed")
        elif conf >= 55:
            parts.append("Signal: MEDIUM confidence — half position")
        else:
            parts.append("Signal: LOW confidence — skip this cycle")

        return " | ".join(parts)
