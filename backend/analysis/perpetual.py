"""
OKX 永续合约智能分析。

只做市场诊断与报告生成，不触发任何下单行为。
"""
from __future__ import annotations

import math
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import numpy as np
import pandas as pd

from indicators.technical import calc_atr, calc_boll, calc_ema, calc_macd, calc_rsi, calc_sma

BEIJING_TZ = timezone(timedelta(hours=8))


class AnalysisDataError(Exception):
    """分析所需行情数据不可用。"""


class UnknownInstrumentError(Exception):
    """OKX 未找到对应交易对。"""


class PerpetualAnalysisEngine:
    """构建永续合约结构化分析数据。"""

    def __init__(self, client):
        self.client = client

    def build(self, symbol: str) -> dict[str, Any]:
        symbol = symbol.strip().upper()
        if not symbol:
            raise UnknownInstrumentError("交易对不能为空")

        self._validate_symbol(symbol)
        candles = self._fetch_candles(symbol)
        one_hour = candles.get("1H", pd.DataFrame())
        if one_hour.empty:
            raise AnalysisDataError("K 线数据为空")

        notes = []
        if len(one_hour) < 60:
            notes.append("K 线数量不足，部分指标不可用")

        ticker = self._retry(
            "ticker",
            lambda: self.client.get_ticker(symbol),
            lambda data: bool(data),
        ) or {}
        funding_current = self._retry(
            "funding_rate",
            lambda: self.client.get_funding_rate(symbol),
            lambda data: data is not None,
        )
        funding_history = self._retry(
            "funding_rate_history",
            lambda: self.client.get_funding_rate_history(symbol, limit=30),
            lambda data: isinstance(data, list),
        ) or []
        oi_history = self._retry(
            "open_interest_history",
            lambda: self.client.get_open_interest_history(symbol, period="1H"),
            lambda data: isinstance(data, list),
        ) or []
        base_ccy = symbol.split("-")[0]
        long_short_history = self._retry(
            "long_short_account_ratio",
            lambda: self.client.get_long_short_account_ratio(base_ccy, period="1H"),
            lambda data: isinstance(data, list),
        ) or []
        long_short_position_history = self._retry(
            "long_short_position_ratio",
            lambda: self.client.get_long_short_position_ratio(symbol, period="1H"),
            lambda data: isinstance(data, list),
        ) or []
        orderbook = self._retry(
            "orderbook_depth",
            lambda: self.client.get_orderbook_depth(symbol, sz="20"),
            lambda data: isinstance(data, dict),
        ) or {"asks": [], "bids": []}
        recent_trades = self._retry(
            "recent_trades",
            lambda: self.client.get_recent_trades(symbol, limit=100),
            lambda data: isinstance(data, list),
        ) or []

        trend = self._trend_analysis(one_hour)
        timeframe = self._timeframe_snapshot(candles)
        volume = self._volume_analysis(one_hour)
        funding = self._funding_analysis(funding_current, funding_history)
        oi = self._oi_analysis(oi_history, one_hour)
        support_resistance = self._support_resistance(one_hour, trend)
        multi_timeframe = self._multi_timeframe_analysis(timeframe)
        sentiment = self._sentiment_analysis(long_short_history, long_short_position_history, recent_trades)
        orderbook_analysis = self._orderbook_analysis(orderbook)
        institutional = self._institutional_behavior(trend, volume, funding, oi)
        market_phase = self._market_phase(trend, volume, funding, oi)
        strategy_match = self._strategy_match(trend, funding, market_phase, sentiment)
        rules = self._quant_rules(trend, volume, funding, oi, timeframe, sentiment)
        scores = self._score_panel(trend, volume, funding, oi, timeframe, sentiment, institutional)
        volatility_warning = self._volatility_warning(candles.get("5m", pd.DataFrame()))

        current_price = self._safe_float(ticker.get("last")) or trend["current_price"]
        price_change_24h = self._safe_float(ticker.get("chg_pct")) or 0.0
        risk_reward = self._risk_reward(current_price, trend["direction"], support_resistance)
        risk_reward_analysis = self._risk_reward_analysis(current_price, risk_reward, trend)
        conflicts = self._conflict_analysis(trend, funding, volume, oi, timeframe, scores, sentiment)
        role_advice = self._role_advice(trend, support_resistance, funding, risk_reward)
        trading_plan = self._trading_plan(current_price, trend, support_resistance, risk_reward, conflicts)
        summary = self._summary(
            current_price,
            price_change_24h,
            trend,
            funding,
            scores,
            risk_reward,
            volatility_warning,
            timeframe,
        )
        strategy_parameter_advice = self._strategy_parameter_advice(
            current_price,
            trend,
            support_resistance,
            summary,
            timeframe,
        )

        return {
            "symbol": symbol,
            "created_at": datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S"),
            "data_quality_notes": notes,
            "volatility_warning": volatility_warning,
            "ticker": {
                "current_price": current_price,
                "price_change_24h": price_change_24h,
                "high_24h": self._safe_float(ticker.get("high24h")),
                "low_24h": self._safe_float(ticker.get("low24h")),
                "volume_24h": self._safe_float(ticker.get("vol24h")),
            },
            "summary": summary,
            "scores": scores,
            "quant_rules": rules,
            "trend_analysis": trend,
            "multi_timeframe_analysis": multi_timeframe,
            "support_resistance": support_resistance,
            "funding_rate_analysis": funding,
            "open_interest_analysis": oi,
            "volume_analysis": volume,
            "sentiment_analysis": sentiment,
            "orderbook_depth_analysis": orderbook_analysis,
            "institutional_behavior": institutional,
            "market_phase": market_phase,
            "strategy_match": strategy_match,
            "risk_reward_analysis": risk_reward_analysis,
            "role_advice": role_advice,
            "conflict_analysis": conflicts,
            "trading_plan": trading_plan,
            "strategy_parameter_advice": strategy_parameter_advice,
            "timeframe_snapshot": timeframe,
            "ai_report": None,
            "ai_report_error": None,
        }

    def _validate_symbol(self, symbol: str) -> None:
        try:
            self.client.get_contract_value(symbol)
        except Exception as exc:
            raise UnknownInstrumentError("未找到该交易对，请确认名称") from exc

    def _fetch_candles(self, symbol: str) -> dict[str, pd.DataFrame]:
        bars = {"5m": 120, "1H": 180, "4H": 120, "1D": 120}
        candles = {}
        for bar, limit in bars.items():
            data = self._retry(
                f"candles:{bar}",
                lambda bar=bar, limit=limit: self.client.get_candles(symbol, bar=bar, limit=limit),
                lambda data: isinstance(data, pd.DataFrame) and not data.empty,
            )
            candles[bar] = data if isinstance(data, pd.DataFrame) else pd.DataFrame()
        return candles

    @staticmethod
    def _retry(label: str, func: Callable[[], Any], accept: Callable[[Any], bool], retries: int = 3) -> Any:
        last_result = None
        for attempt in range(retries):
            try:
                last_result = func()
                if accept(last_result):
                    return last_result
            except Exception:
                last_result = None
            if attempt < retries - 1:
                time.sleep(0.4 * (attempt + 1))
        return last_result

    def _trend_analysis(self, df: pd.DataFrame) -> dict[str, Any]:
        closes = df["close"].to_numpy(dtype=float)
        highs = df["high"].to_numpy(dtype=float)
        lows = df["low"].to_numpy(dtype=float)

        ma5 = calc_sma(closes, 5)
        ma20 = calc_sma(closes, 20)
        ma60 = calc_sma(closes, 60)
        ema20 = calc_ema(closes, 20)
        ema50 = calc_ema(closes, 50)
        macd_line, signal_line, histogram = calc_macd(closes)
        rsi = calc_rsi(closes)
        boll_upper, boll_middle, boll_lower = calc_boll(closes)
        atr = calc_atr(highs, lows, closes)

        current = float(closes[-1])
        indicator = {
            "ma5": self._last_number(ma5),
            "ma20": self._last_number(ma20),
            "ma60": self._last_number(ma60),
            "ema20": self._last_number(ema20),
            "ema50": self._last_number(ema50),
            "macd": self._last_number(macd_line),
            "macd_signal": self._last_number(signal_line),
            "macd_histogram": self._last_number(histogram),
            "rsi": self._last_number(rsi),
            "boll_upper": self._last_number(boll_upper),
            "boll_middle": self._last_number(boll_middle),
            "boll_lower": self._last_number(boll_lower),
            "atr": self._last_number(atr),
        }

        ma_structure = self._ma_structure(current, indicator["ma20"], indicator["ma60"])
        macd_status = self._macd_status(macd_line, signal_line)
        rsi_status = self._rsi_status(indicator["rsi"])
        boll_position = self._boll_position(current, indicator)
        atr_pct = (indicator["atr"] / current * 100) if current and indicator["atr"] else None
        atr_level = self._atr_level(atr_pct)

        direction = "震荡"
        if ma_structure == "多头排列" and (indicator["macd_histogram"] or 0) >= 0:
            direction = "偏多"
        elif ma_structure == "空头排列" and (indicator["macd_histogram"] or 0) <= 0:
            direction = "偏空"

        strength = self._trend_strength(direction, current, indicator)
        overheated = rsi_status == "超买" or boll_position == "上轨附近"
        reversal_risk = overheated or (
            direction == "偏多" and macd_status in {"死叉", "偏空"}
        ) or (
            direction == "偏空" and macd_status in {"金叉", "偏多"}
        )

        return {
            "current_price": current,
            "direction": direction,
            "strength": strength,
            "ma_structure": ma_structure,
            "macd_status": macd_status,
            "rsi_value": indicator["rsi"],
            "rsi_status": rsi_status,
            "boll_position": boll_position,
            "atr_value": indicator["atr"],
            "atr_pct": atr_pct,
            "atr_level": atr_level,
            "is_overheated": overheated,
            "has_reversal_risk": reversal_risk,
            "indicators": indicator,
            "analysis": self._trend_text(direction, strength, ma_structure, macd_status, rsi_status, boll_position, atr_level, overheated, reversal_risk),
        }

    @staticmethod
    def _ma_structure(price: float, ma20: float | None, ma60: float | None) -> str:
        if ma20 is None or ma60 is None:
            return "数据不足"
        if price > ma20 > ma60:
            return "多头排列"
        if price < ma20 < ma60:
            return "空头排列"
        return "混乱"

    @classmethod
    def _macd_status(cls, macd_line: np.ndarray, signal_line: np.ndarray) -> str:
        current_macd = cls._last_number(macd_line)
        current_signal = cls._last_number(signal_line)
        prev_macd = cls._last_number(macd_line[:-1])
        prev_signal = cls._last_number(signal_line[:-1])
        if current_macd is None or current_signal is None:
            return "中性"
        if prev_macd is not None and prev_signal is not None:
            if prev_macd <= prev_signal and current_macd > current_signal:
                return "金叉"
            if prev_macd >= prev_signal and current_macd < current_signal:
                return "死叉"
        if current_macd > current_signal:
            return "偏多"
        if current_macd < current_signal:
            return "偏空"
        return "中性"

    @staticmethod
    def _rsi_status(value: float | None) -> str:
        if value is None:
            return "数据不足"
        if value > 75:
            return "超买"
        if value < 25:
            return "超卖"
        if 50 <= value <= 70:
            return "中性偏强"
        return "中性"

    @staticmethod
    def _boll_position(price: float, indicator: dict[str, float | None]) -> str:
        upper = indicator.get("boll_upper")
        middle = indicator.get("boll_middle")
        lower = indicator.get("boll_lower")
        if upper is None or middle is None or lower is None:
            return "数据不足"
        if abs(price - upper) / price < 0.005:
            return "上轨附近"
        if abs(price - lower) / price < 0.005:
            return "下轨附近"
        if price >= middle:
            return "中上轨区间"
        return "中下轨区间"

    @staticmethod
    def _atr_level(atr_pct: float | None) -> str:
        if atr_pct is None:
            return "数据不足"
        if atr_pct < 0.6:
            return "低"
        if atr_pct < 1.8:
            return "中"
        return "高"

    @staticmethod
    def _trend_strength(direction: str, price: float, indicator: dict[str, float | None]) -> str:
        if direction == "震荡":
            return "弱"
        ma20 = indicator.get("ma20")
        if not ma20:
            return "弱"
        distance_pct = abs(price - ma20) / price * 100
        histogram = abs(indicator.get("macd_histogram") or 0)
        if distance_pct >= 1.2 and histogram > 0:
            return "强"
        if distance_pct >= 0.4:
            return "中等"
        return "弱"

    @staticmethod
    def _trend_text(
        direction: str,
        strength: str,
        ma_structure: str,
        macd_status: str,
        rsi_status: str,
        boll_position: str,
        atr_level: str,
        overheated: bool,
        reversal_risk: bool,
    ) -> str:
        risk_text = "存在过热或反转风险" if (overheated or reversal_risk) else "暂未出现明显过热信号"
        return (
            f"1H 当前趋势为{direction}，强度{strength}；均线结构为{ma_structure}，"
            f"MACD {macd_status}，RSI 处于{rsi_status}，价格位于布林带{boll_position}。"
            f"ATR 波动率为{atr_level}，{risk_text}。"
        )

    def _timeframe_snapshot(self, candles: dict[str, pd.DataFrame]) -> dict[str, Any]:
        frames = {}
        for bar in ("1D", "4H", "1H", "5m"):
            frames[bar] = self._timeframe_direction(candles.get(bar, pd.DataFrame()))

        valid = [item["direction"] for item in frames.values() if item["direction"] in {"偏多", "偏空", "震荡"}]
        conflicts = len(set(valid)) > 1
        bullish = valid.count("偏多")
        bearish = valid.count("偏空")
        if bullish >= 3 and bearish == 0:
            conclusion = "共振偏多"
        elif bearish >= 3 and bullish == 0:
            conclusion = "共振偏空"
        elif conflicts:
            conclusion = "周期冲突"
        else:
            conclusion = "震荡或信号不足"

        return {
            "directions": frames,
            "conclusion": conclusion,
            "has_conflict": conflicts,
        }

    @staticmethod
    def _multi_timeframe_analysis(timeframe: dict[str, Any]) -> dict[str, Any]:
        directions = timeframe["directions"]
        valid = [item["direction"] for item in directions.values() if item["direction"] in {"偏多", "偏空", "震荡"}]
        if not valid:
            score = 0
        else:
            dominant = max(set(valid), key=valid.count)
            score = int(valid.count(dominant) / len(valid) * 100)

        daily = directions.get("1D", {}).get("direction")
        four_hour = directions.get("4H", {}).get("direction")
        one_hour = directions.get("1H", {}).get("direction")
        five_min = directions.get("5m", {}).get("direction")

        if daily == "偏多" and four_hour == "偏多" and one_hour == "震荡":
            entry = "大周期偏多，1H 回调或震荡时以低吸观察为主。"
        elif daily == "偏空" and four_hour == "偏空" and one_hour == "震荡":
            entry = "大周期偏空，1H 反弹时以做空观察为主。"
        elif timeframe["conclusion"] == "周期冲突":
            entry = "周期方向相互冲突，等待 1H 与 4H 重新同向。"
        elif timeframe["conclusion"] in {"共振偏多", "共振偏空"}:
            entry = "多周期方向一致，信号可信度较高，但仍需等待关键位确认。"
        else:
            entry = "共振不足，优先观察，不追逐短线波动。"

        conflict_notice = "存在周期冲突，建议降低仓位或等待确认。" if timeframe["has_conflict"] else ""
        return {
            "directions": {
                "1D": daily,
                "4H": four_hour,
                "1H": one_hour,
                "5m": five_min,
            },
            "consistency_score": score,
            "conclusion": timeframe["conclusion"],
            "entry_timing_advice": entry,
            "conflict_notice": conflict_notice,
        }

    def _timeframe_direction(self, df: pd.DataFrame) -> dict[str, Any]:
        if df.empty or len(df) < 60:
            return {"direction": "数据不足", "strength": "弱", "price": None}
        closes = df["close"].to_numpy(dtype=float)
        price = float(closes[-1])
        ma20 = self._last_number(calc_sma(closes, 20))
        ma60 = self._last_number(calc_sma(closes, 60))
        macd_line, signal_line, _ = calc_macd(closes)
        macd = self._last_number(macd_line)
        signal = self._last_number(signal_line)

        direction = "震荡"
        if ma20 is not None and ma60 is not None and macd is not None and signal is not None:
            if price > ma20 > ma60 and macd >= signal:
                direction = "偏多"
            elif price < ma20 < ma60 and macd <= signal:
                direction = "偏空"

        strength = "强" if direction != "震荡" and ma20 and abs(price - ma20) / price >= 0.012 else "中等"
        if direction == "震荡":
            strength = "弱"
        return {"direction": direction, "strength": strength, "price": price}

    def _volume_analysis(self, df: pd.DataFrame) -> dict[str, Any]:
        if df.empty or len(df) < 21:
            return {
                "volume": None,
                "average_volume_20": None,
                "volume_ratio": None,
                "status": "数据不足",
                "price_change_pct": None,
                "relation": "数据不足",
                "supports_trend": False,
                "analysis": "K 线数量不足，无法判断成交量状态。",
            }

        volumes = df["vol"].to_numpy(dtype=float)
        closes = df["close"].to_numpy(dtype=float)
        current_volume = float(volumes[-1])
        avg20 = float(np.mean(volumes[-21:-1]))
        ratio = current_volume / avg20 if avg20 > 0 else 0
        price_change_pct = self._pct_change(closes[-1], closes[-2])

        if ratio >= 1.5:
            status = "放量"
        elif ratio <= 0.7:
            status = "缩量"
        else:
            status = "正常"

        if status == "放量" and price_change_pct > 0:
            relation = "放量上涨"
            supports = True
        elif status == "缩量" and price_change_pct > 0:
            relation = "缩量上涨"
            supports = False
        elif status == "放量" and price_change_pct < 0:
            relation = "放量下跌"
            supports = True
        elif status == "缩量" and price_change_pct < 0:
            relation = "缩量下跌"
            supports = False
        else:
            relation = "量价中性"
            supports = False

        return {
            "volume": current_volume,
            "average_volume_20": avg20,
            "volume_ratio": ratio,
            "status": status,
            "price_change_pct": price_change_pct,
            "relation": relation,
            "supports_trend": supports,
            "analysis": f"当前成交量为近 20 周期均量的 {ratio:.2f} 倍，量价关系为{relation}。",
        }

    def _sentiment_analysis(
        self,
        account_ratio_history: list[dict],
        position_ratio_history: list[dict],
        trades: list[dict],
    ) -> dict[str, Any]:
        account_ratio = account_ratio_history[0].get("ratio") if account_ratio_history else None
        position_ratio = position_ratio_history[0].get("ratio") if position_ratio_history else None
        buy_volume = sum((trade.get("size") or 0) for trade in trades if trade.get("side") == "buy")
        sell_volume = sum((trade.get("size") or 0) for trade in trades if trade.get("side") == "sell")
        total = buy_volume + sell_volume
        active_buy_pct = buy_volume / total * 100 if total > 0 else None
        active_sell_pct = sell_volume / total * 100 if total > 0 else None

        direction = "中性"
        if account_ratio is not None and account_ratio > 1.2:
            direction = "偏多"
        elif account_ratio is not None and account_ratio < 0.8:
            direction = "偏空"
        if position_ratio is not None and position_ratio > 1.2:
            direction = "偏多"
        elif position_ratio is not None and position_ratio < 0.8:
            direction = "偏空"
        if active_buy_pct is not None and active_buy_pct > 60:
            direction = "偏多"
        elif active_sell_pct is not None and active_sell_pct > 60:
            direction = "偏空"

        one_sided = bool(
            (account_ratio is not None and (account_ratio > 2 or account_ratio < 0.5))
            or (position_ratio is not None and (position_ratio > 2 or position_ratio < 0.5))
            or (active_buy_pct is not None and max(active_buy_pct, active_sell_pct or 0) > 70)
        )
        long_squeeze_risk = bool(
            (account_ratio is not None and account_ratio > 2)
            or (position_ratio is not None and position_ratio > 2)
        )
        short_squeeze_risk = bool(
            (account_ratio is not None and account_ratio < 0.5)
            or (position_ratio is not None and position_ratio < 0.5)
        )
        if not account_ratio_history:
            text = "暂无多空账户比数据，情绪判断主要参考最近成交主动方向。"
        elif one_sided:
            text = "情绪明显偏向一侧，需警惕一致性交易带来的反向波动。"
        else:
            text = "多空情绪未出现极端拥挤，暂以中性到轻微偏向解读。"

        return {
            "long_short_account_ratio": account_ratio,
            "long_short_position_ratio": position_ratio,
            "active_buy_pct": active_buy_pct,
            "active_sell_pct": active_sell_pct,
            "direction": direction,
            "one_sided_risk": one_sided,
            "long_liquidation_chain_risk": long_squeeze_risk,
            "short_squeeze_risk": short_squeeze_risk,
            "analysis": text,
        }

    @staticmethod
    def _funding_analysis(current: dict | None, history: list[dict]) -> dict[str, Any]:
        if not current:
            return {
                "available": False,
                "current_rate": None,
                "predicted_rate": None,
                "history_average": None,
                "level": "暂无资金费率数据",
                "long_crowded": False,
                "short_crowded": False,
                "analysis": "暂无资金费率数据，该模块不纳入评分。",
            }

        rate = current.get("funding_rate")
        predicted = current.get("next_funding_rate")
        values = [item["funding_rate"] for item in history if item.get("funding_rate") is not None]
        avg = sum(values) / len(values) if values else None

        if rate is None:
            level = "暂无资金费率数据"
        elif rate > 0.002:
            level = "极高"
        elif rate > 0.001:
            level = "偏高"
        elif rate < 0:
            level = "负值"
        elif abs(rate) < 0.0001:
            level = "低"
        else:
            level = "正常"

        long_crowded = bool(rate is not None and rate > 0.001)
        short_crowded = bool(rate is not None and rate < -0.0005)
        if long_crowded:
            text = "资金费率偏高，多头持仓成本上升，追多性价比下降。"
        elif short_crowded:
            text = "资金费率显著为负，空头拥挤时需要警惕轧空风险。"
        else:
            text = "资金费率处于相对平衡区间，持仓成本压力不突出。"

        return {
            "available": True,
            "current_rate": rate,
            "predicted_rate": predicted,
            "history_average": avg,
            "level": level,
            "long_crowded": long_crowded,
            "short_crowded": short_crowded,
            "analysis": text,
        }

    def _oi_analysis(self, history: list[dict], df: pd.DataFrame) -> dict[str, Any]:
        if not history:
            return {
                "available": False,
                "current_oi": None,
                "oi_change_1h_pct": None,
                "oi_change_24h_pct": None,
                "trend": "暂无 OI 数据",
                "signal": "暂无 OI 数据",
                "meaning": "暂无 OI 数据，跳过 OI 相关分析。",
                "score_impact": 0,
            }

        latest = history[0]
        current_oi = latest.get("oi_usd") or latest.get("oi") or 0
        oi_1h = self._pct_change(current_oi, history[1].get("oi_usd") or history[1].get("oi")) if len(history) > 1 else None
        oi_24h = self._pct_change(current_oi, history[24].get("oi_usd") or history[24].get("oi")) if len(history) > 24 else None
        closes = df["close"].to_numpy(dtype=float)
        price_change = self._pct_change(closes[-1], closes[-2]) if len(closes) >= 2 else 0

        if oi_1h is None or abs(oi_1h) < 0.3:
            trend = "平稳"
        elif oi_1h > 0:
            trend = "上升"
        else:
            trend = "下降"

        signal = "持仓平稳"
        meaning = "OI 变化不明显，暂未形成明确持仓信号。"
        score_impact = 0
        if price_change > 0 and oi_1h is not None and oi_1h > 0.3:
            signal = "新多头进场"
            meaning = "价格上涨且 OI 上升，多头主动建仓，趋势真实性增强。"
            score_impact = 12
        elif price_change > 0 and oi_1h is not None and oi_1h < -0.3:
            signal = "空头回补"
            meaning = "价格上涨但 OI 下降，可能由空头平仓推动，动能持续性有限。"
            score_impact = 5
        elif price_change < 0 and oi_1h is not None and oi_1h > 0.3:
            signal = "空头加仓"
            meaning = "价格下跌且 OI 上升，空头主动进场，下行压力增强。"
            score_impact = -12
        elif price_change < 0 and oi_1h is not None and oi_1h < -0.3:
            signal = "多头离场"
            meaning = "价格下跌且 OI 下降，多头止损离场，趋势走弱。"
            score_impact = -12

        return {
            "available": True,
            "current_oi": current_oi,
            "oi_change_1h_pct": oi_1h,
            "oi_change_24h_pct": oi_24h,
            "trend": trend,
            "signal": signal,
            "meaning": meaning,
            "score_impact": score_impact,
        }

    def _support_resistance(self, df: pd.DataFrame, trend: dict[str, Any]) -> dict[str, Any]:
        price = trend["current_price"]
        indicators = trend["indicators"]
        pressures = []
        supports = []

        recent = df.tail(80)
        for value in sorted(recent["high"].dropna().unique(), reverse=True)[:8]:
            self._add_level(pressures, float(value), price, "近期高点", above=True)
        for value in sorted(recent["low"].dropna().unique())[:8]:
            self._add_level(supports, float(value), price, "近期低点", above=False)

        for name, key in (("MA20", "ma20"), ("MA60", "ma60"), ("EMA50", "ema50")):
            level = indicators.get(key)
            if level:
                self._add_level(pressures, level, price, name, above=True)
                self._add_level(supports, level, price, name, above=False)

        self._add_level(pressures, indicators.get("boll_upper"), price, "布林带上轨", above=True)
        self._add_level(supports, indicators.get("boll_lower"), price, "布林带下轨", above=False)

        for level in self._round_number_levels(price):
            self._add_level(pressures, level, price, "整数关口", above=True)
            self._add_level(supports, level, price, "整数关口", above=False)

        pressures = self._dedupe_levels(pressures, price, reverse=False)[:3]
        supports = self._dedupe_levels(supports, price, reverse=False)[:3]

        return {
            "resistance_levels": pressures,
            "support_levels": supports,
            "key_breakdown_price": supports[0]["price"] if supports else None,
            "key_breakout_price": pressures[0]["price"] if pressures else None,
            "analysis": "上方优先关注最近压力位突破有效性，下方优先关注最近支撑失守后的趋势转弱风险。",
        }

    def _orderbook_analysis(self, orderbook: dict[str, Any]) -> dict[str, Any]:
        asks = self._parse_depth(orderbook.get("asks", []))
        bids = self._parse_depth(orderbook.get("bids", []))
        best_ask = asks[0]["price"] if asks else None
        best_bid = bids[0]["price"] if bids else None
        spread = (best_ask - best_bid) if best_ask is not None and best_bid is not None else None
        mid = (best_ask + best_bid) / 2 if best_ask is not None and best_bid is not None else None
        spread_pct = spread / mid * 100 if spread is not None and mid else None
        bid_depth = sum(item["size"] for item in bids)
        ask_depth = sum(item["size"] for item in asks)
        if bid_depth > ask_depth * 1.2:
            imbalance = "买盘强"
        elif ask_depth > bid_depth * 1.2:
            imbalance = "卖盘强"
        else:
            imbalance = "平衡"
        bid_wall = max(bids, key=lambda item: item["size"], default=None)
        ask_wall = max(asks, key=lambda item: item["size"], default=None)
        return {
            "spread": spread,
            "spread_pct": spread_pct,
            "bid_depth": bid_depth,
            "ask_depth": ask_depth,
            "imbalance": imbalance,
            "largest_bid_wall": bid_wall,
            "largest_ask_wall": ask_wall,
            "short_term_support": bid_wall["price"] if bid_wall else None,
            "short_term_resistance": ask_wall["price"] if ask_wall else None,
            "analysis": f"盘口前 20 档呈现{imbalance}，短线支撑/压力优先参考最大挂单墙。",
        }

    @staticmethod
    def _parse_depth(rows: list) -> list[dict[str, float]]:
        parsed = []
        for row in rows:
            if len(row) < 2:
                continue
            try:
                price = float(row[0])
                size = float(row[1])
            except (TypeError, ValueError):
                continue
            parsed.append({"price": price, "size": size})
        return parsed

    @staticmethod
    def _add_level(levels: list[dict], level: float | None, price: float, source: str, above: bool) -> None:
        if level is None or not math.isfinite(level) or level <= 0:
            return
        if above and level <= price:
            return
        if not above and level >= price:
            return
        levels.append({
            "price": float(level),
            "source": source,
            "distance_pct": abs(level - price) / price * 100,
        })

    @staticmethod
    def _round_number_levels(price: float) -> list[float]:
        if price >= 20000:
            step = 1000
        elif price >= 1000:
            step = 100
        elif price >= 100:
            step = 10
        elif price >= 10:
            step = 1
        else:
            step = 0.1
        base = math.floor(price / step) * step
        return [base - step, base, base + step, base + 2 * step]

    @staticmethod
    def _dedupe_levels(levels: list[dict], price: float, reverse: bool) -> list[dict]:
        result = []
        for item in sorted(levels, key=lambda value: value["distance_pct"], reverse=reverse):
            if all(abs(item["price"] - existing["price"]) / price > 0.002 for existing in result):
                result.append({
                    "price": round(item["price"], 8),
                    "source": item["source"],
                    "distance_pct": round(item["distance_pct"], 3),
                })
        return result

    def _quant_rules(
        self,
        trend: dict[str, Any],
        volume: dict[str, Any],
        funding: dict[str, Any],
        oi: dict[str, Any],
        timeframe: dict[str, Any],
        sentiment: dict[str, Any],
    ) -> list[dict[str, Any]]:
        current = trend["current_price"]
        indicators = trend["indicators"]
        rules = []

        def add(name: str, triggered: bool, delta: int, description: str, available: bool = True) -> None:
            rules.append({
                "name": name,
                "triggered": bool(triggered and available),
                "score_delta": delta if triggered and available else 0,
                "description": description,
                "available": available,
            })

        ma20 = indicators.get("ma20")
        ma60 = indicators.get("ma60")
        add("均线多头排列", ma20 is not None and ma60 is not None and current > ma20 > ma60, 15, "趋势结构健康")
        add("均线空头排列", ma20 is not None and ma60 is not None and current < ma20 < ma60, -15, "趋势结构偏弱")
        add("MACD 金叉", trend["macd_status"] == "金叉", 10, "动能转强信号")
        add("MACD 死叉", trend["macd_status"] == "死叉", -10, "动能转弱信号")
        add("RSI 超买", (trend["rsi_value"] or 0) > 75, -12, "追多风险加大")
        add("RSI 超卖", trend["rsi_value"] is not None and trend["rsi_value"] < 25, 12, "超跌反弹机会")
        add("RSI 中性偏强", trend["rsi_value"] is not None and 50 <= trend["rsi_value"] <= 70, 8, "动能健康")
        add("成交量放大上涨", volume["volume_ratio"] is not None and volume["volume_ratio"] > 1.5 and (volume["price_change_pct"] or 0) > 0, 10, "量价配合，趋势真实")
        add("成交量放大下跌", volume["volume_ratio"] is not None and volume["volume_ratio"] > 1.5 and (volume["price_change_pct"] or 0) < 0, -10, "卖压明显")
        add("量价背离（上涨）", self._volume_divergence_up(volume), -8, "价格创新高但成交量萎缩，趋势持续性存疑")
        add("OI 同步上升", oi["available"] and (oi["oi_change_1h_pct"] or 0) > 2 and oi["signal"] == "新多头进场", 12, "新多头进场，趋势真实")
        add("OI 同步下降", oi["available"] and (oi["oi_change_1h_pct"] or 0) < -2 and oi["signal"] == "多头离场", -12, "多头离场，趋势走弱")
        add("空头回补上涨", oi["available"] and oi["signal"] == "空头回补", 5, "空头平仓推动，动能有限")
        add("资金费率过高", funding["available"] and (funding["current_rate"] or 0) > 0.001, -10, "多头成本高，追多性价比低")
        add("资金费率极高", funding["available"] and (funding["current_rate"] or 0) > 0.002, -18, "多头拥挤，回调风险大")
        add("资金费率为负", funding["available"] and funding["current_rate"] is not None and funding["current_rate"] < -0.0005, -8, "空头拥挤，注意轧空风险")
        upper = indicators.get("boll_upper")
        lower = indicators.get("boll_lower")
        add("布林带上轨附近", upper is not None and abs(current - upper) / current < 0.005, -8, "短线超买区")
        add("布林带下轨附近", lower is not None and abs(current - lower) / current < 0.005, 8, "短线超卖区")
        account_ratio = sentiment.get("long_short_account_ratio")
        add("多空账户比过高", account_ratio is not None and account_ratio > 2.0, -8, "散户情绪过度偏多", available=account_ratio is not None)
        add("多空账户比过低", account_ratio is not None and account_ratio < 0.5, 8, "散户情绪过度偏空", available=account_ratio is not None)

        daily_direction = timeframe["directions"].get("1D", {}).get("direction")
        add("大周期趋势支撑", daily_direction == trend["direction"] and daily_direction in {"偏多", "偏空"}, 10, "大周期背景支撑")
        add("大周期趋势压制", daily_direction in {"偏多", "偏空"} and trend["direction"] in {"偏多", "偏空"} and daily_direction != trend["direction"], -10, "大周期背景压制")
        return rules

    @staticmethod
    def _volume_divergence_up(volume: dict[str, Any]) -> bool:
        return (
            volume.get("price_change_pct") is not None
            and volume["price_change_pct"] > 0
            and volume.get("volume_ratio") is not None
            and volume["volume_ratio"] < 0.7
        )

    def _score_panel(
        self,
        trend: dict[str, Any],
        volume: dict[str, Any],
        funding: dict[str, Any],
        oi: dict[str, Any],
        timeframe: dict[str, Any],
        sentiment: dict[str, Any],
        institutional: dict[str, Any],
    ) -> dict[str, Any]:
        trend_score = self._trend_score(trend)
        volume_score = self._volume_score(volume)
        funding_score = self._funding_score(funding)
        oi_score = self._oi_score(oi)
        sentiment_score = self._sentiment_score(sentiment)
        institutional_score = self._institutional_score(institutional)
        timeframe_score = self._timeframe_score(timeframe)

        dimensions = [
            ("trend", "趋势评分", 25, trend_score, f"1H 趋势{trend['direction']}，强度{trend['strength']}"),
            ("volume", "量能评分", 15, volume_score, volume["analysis"]),
            ("funding", "资金费率风险", 15, funding_score, funding["analysis"]),
            ("oi", "OI 持仓评分", 15, oi_score, oi["meaning"]),
            ("sentiment", "多空情绪评分", 10, sentiment_score, sentiment["analysis"]),
            ("institution", "机构行为评分", 10, institutional_score, institutional["operation_hint"]),
            ("timeframe", "多周期共振评分", 10, timeframe_score, timeframe["conclusion"]),
        ]
        items = [
            {"key": key, "name": name, "weight": weight, "score": int(round(score)), "explanation": explanation}
            for key, name, weight, score, explanation in dimensions
        ]
        overall = sum(item["score"] * item["weight"] / 100 for item in items)
        return {
            "overall_score": int(round(self._clamp(overall, 0, 100))),
            "dimensions": items,
            "interpretation": "0-40 偏弱，40-60 中性，60-80 偏强，80-100 极强或过热，需结合风险项判断。",
        }

    @staticmethod
    def _trend_score(trend: dict[str, Any]) -> float:
        if trend["direction"] == "偏多":
            score = 68
        elif trend["direction"] == "偏空":
            score = 32
        else:
            score = 50
        if trend["strength"] == "强":
            score += 10 if trend["direction"] == "偏多" else -10 if trend["direction"] == "偏空" else 0
        if trend["is_overheated"]:
            score -= 8
        if trend["rsi_status"] == "超卖":
            score += 8
        return PerpetualAnalysisEngine._clamp(score, 0, 100)

    @staticmethod
    def _volume_score(volume: dict[str, Any]) -> float:
        relation = volume.get("relation")
        mapping = {
            "放量上涨": 70,
            "缩量上涨": 52,
            "放量下跌": 35,
            "缩量下跌": 45,
            "量价中性": 50,
        }
        return mapping.get(relation, 50)

    @staticmethod
    def _funding_score(funding: dict[str, Any]) -> float:
        mapping = {
            "极高": 25,
            "偏高": 40,
            "负值": 45,
            "低": 65,
            "正常": 70,
        }
        return mapping.get(funding.get("level"), 50)

    @staticmethod
    def _oi_score(oi: dict[str, Any]) -> float:
        mapping = {
            "新多头进场": 68,
            "空头回补": 58,
            "空头加仓": 35,
            "多头离场": 30,
            "持仓平稳": 50,
        }
        return mapping.get(oi.get("signal"), 50)

    @staticmethod
    def _institutional_proxy_score(volume: dict[str, Any], funding: dict[str, Any], oi: dict[str, Any]) -> float:
        score = 50
        if oi.get("signal") == "新多头进场" and volume.get("status") == "放量" and not funding.get("long_crowded"):
            score += 15
        if oi.get("signal") in {"空头加仓", "多头离场"} and volume.get("status") == "放量":
            score -= 12
        if funding.get("long_crowded"):
            score -= 8
        return PerpetualAnalysisEngine._clamp(score, 0, 100)

    @staticmethod
    def _sentiment_score(sentiment: dict[str, Any]) -> float:
        if sentiment.get("one_sided_risk"):
            return 38
        if sentiment.get("direction") == "偏多":
            return 62
        if sentiment.get("direction") == "偏空":
            return 42
        return 50

    @staticmethod
    def _institutional_score(institutional: dict[str, Any]) -> float:
        mapping = {
            "疑似吸筹": 68,
            "空头挤压": 62,
            "疑似派发": 38,
            "多杀多": 32,
            "假突破": 35,
            "清算狩猎": 45,
            "无明显信号": 50,
        }
        return mapping.get(institutional.get("type"), 50)

    @staticmethod
    def _institutional_behavior(
        trend: dict[str, Any],
        volume: dict[str, Any],
        funding: dict[str, Any],
        oi: dict[str, Any],
    ) -> dict[str, Any]:
        behavior = "无明显信号"
        confidence = "低"
        basis = []
        price_change = volume.get("price_change_pct") or 0
        volume_up = volume.get("status") == "放量"
        oi_signal = oi.get("signal")
        funding_high = funding.get("level") in {"偏高", "极高"}

        if trend["direction"] == "震荡" and oi.get("trend") == "上升" and volume.get("status") in {"正常", "放量"} and not funding_high:
            behavior = "疑似吸筹"
            confidence = "中"
            basis = ["价格震荡", "OI 上升", "成交量温和或放大", "资金费率不高"]
        elif trend["is_overheated"] and volume_up and funding_high:
            behavior = "疑似派发"
            confidence = "中"
            basis = ["价格处于过热区", "成交量放大", "资金费率偏高"]
        elif price_change > 0 and oi_signal == "空头回补" and volume_up:
            behavior = "空头挤压"
            confidence = "高"
            basis = ["价格上涨", "OI 下降", "成交量放大"]
        elif price_change < 0 and oi_signal == "多头离场" and volume_up:
            behavior = "多杀多"
            confidence = "高"
            basis = ["价格下跌", "OI 下降", "成交量放大"]
        elif trend["boll_position"] == "上轨附近" and volume.get("volume_ratio") is not None and volume["volume_ratio"] < 1:
            behavior = "假突破"
            confidence = "低"
            basis = ["价格接近上轨", "成交量未持续放大"]
        elif trend["boll_position"] == "下轨附近" and price_change > 0:
            behavior = "清算狩猎"
            confidence = "低"
            basis = ["价格靠近下轨后回升", "短线可能刺破支撑后反弹"]

        hint = {
            "疑似吸筹": "不追涨，关注区间下沿和 OI 是否继续温和抬升。",
            "疑似派发": "降低追多意愿，等待放量跌破或重新站稳确认。",
            "空头挤压": "上涨动能可能偏短线，避免在过热位置追高。",
            "多杀多": "下跌链条中优先控制风险，等待止跌确认。",
            "假突破": "突破有效性不足，需等待成交量二次确认。",
            "清算狩猎": "仅把反弹视作观察信号，不直接替代入场依据。",
            "无明显信号": "机构行为特征不明确，按常规趋势和风险项处理。",
        }[behavior]
        return {"type": behavior, "confidence": confidence, "basis": basis, "operation_hint": hint}

    @staticmethod
    def _market_phase(
        trend: dict[str, Any],
        volume: dict[str, Any],
        funding: dict[str, Any],
        oi: dict[str, Any],
    ) -> dict[str, Any]:
        phase = "震荡洗盘"
        basis = []
        if trend["ma_structure"] == "空头排列":
            phase = "下跌阶段"
            basis = ["均线空头排列", "趋势偏弱"]
        elif trend["direction"] == "偏多" and oi.get("trend") == "上升" and volume.get("status") == "放量":
            phase = "拉升阶段"
            basis = ["价格偏多", "OI 上升", "成交量放大"]
        elif trend["is_overheated"] and funding.get("level") in {"偏高", "极高"}:
            phase = "高位诱多"
            basis = ["技术指标过热", "资金费率偏高"]
        elif trend["atr_level"] == "高" and volume.get("status") == "放量":
            phase = "趋势加速"
            basis = ["ATR 扩大", "成交量放大"]
        elif trend["direction"] == "震荡" and oi.get("trend") == "上升":
            phase = "吸筹阶段"
            basis = ["价格震荡", "OI 缓慢上升"]
        elif trend["boll_position"] == "下轨附近" and trend["rsi_status"] == "超卖":
            phase = "低位诱空"
            basis = ["价格靠近下轨", "RSI 超卖"]
        elif trend["direction"] == "震荡" and volume.get("status") == "放量":
            phase = "派发阶段"
            basis = ["高量震荡", "趋势延续不足"]

        risks = {
            "吸筹阶段": "区间时间可能较长，过早追涨容易被洗盘。",
            "拉升阶段": "上涨末端容易出现过热和回撤。",
            "派发阶段": "高位震荡下跌破位风险较高。",
            "下跌阶段": "反弹可能受均线压制。",
            "震荡洗盘": "假突破和来回止损风险较高。",
            "趋势加速": "波动扩张，追单滑点和回撤都会放大。",
            "高位诱多": "一致看多后回调风险上升。",
            "低位诱空": "空头追击容易遇到快速反弹。",
        }[phase]
        strategy = {
            "吸筹阶段": "适合小仓位区间观察，不适合追涨。",
            "拉升阶段": "适合趋势跟随或回调低吸。",
            "派发阶段": "适合降低仓位，等待方向确认。",
            "下跌阶段": "适合反弹做空观察。",
            "震荡洗盘": "适合区间震荡或观望等待。",
            "趋势加速": "适合轻仓顺势，严格移动止损。",
            "高位诱多": "不适合追多，优先风控。",
            "低位诱空": "不适合追空，等待企稳确认。",
        }[phase]
        return {"phase": phase, "basis": basis, "risk_notice": risks, "strategy_fit": strategy}

    @staticmethod
    def _strategy_match(
        trend: dict[str, Any],
        funding: dict[str, Any],
        market_phase: dict[str, Any],
        sentiment: dict[str, Any],
    ) -> dict[str, Any]:
        recommended = []
        unsuitable = []
        phase = market_phase["phase"]
        if trend["direction"] in {"偏多", "偏空"} and trend["strength"] in {"中等", "强"}:
            recommended.append({"name": "趋势跟随", "reason": "趋势方向较明确，适合顺大方向等待确认。"})
        if trend["direction"] == "偏多":
            recommended.append({"name": "回调低吸", "reason": "偏多结构下优先等待支撑区确认。"})
        if trend["direction"] == "震荡":
            recommended.append({"name": "区间震荡", "reason": "趋势不清晰时，高抛低吸优于追单。"})
            recommended.append({"name": "网格策略", "reason": "低波动震荡阶段可用网格，但需控制区间失效风险。"})
        if funding.get("level") in {"偏高", "极高"}:
            recommended.append({"name": "资金费率套利", "reason": "费率偏离时可观察套利空间，但需对冲价格风险。"})
            unsuitable.append({"name": "追多", "reason": "资金费率偏高，多头持仓成本和回撤风险上升。"})
        if sentiment.get("one_sided_risk"):
            unsuitable.append({"name": "单边重仓", "reason": "情绪过度一致，容易触发反向波动。"})
        if phase in {"高位诱多", "派发阶段"}:
            unsuitable.append({"name": "突破追涨", "reason": "高位阶段突破失败风险更高。"})
        if not recommended:
            recommended.append({"name": "观望等待", "reason": "信号不足，等待趋势或关键价位确认。"})
        return {"recommended": recommended[:2], "unsuitable": unsuitable[:2] or [{"name": "高杠杆短线", "reason": "报告仅作风险参考，不适合放大未确认信号。"}]}

    @staticmethod
    def _timeframe_score(timeframe: dict[str, Any]) -> float:
        conclusion = timeframe.get("conclusion")
        if conclusion == "共振偏多":
            return 75
        if conclusion == "共振偏空":
            return 30
        if conclusion == "周期冲突":
            return 45
        return 50

    def _summary(
        self,
        current_price: float,
        price_change_24h: float,
        trend: dict[str, Any],
        funding: dict[str, Any],
        scores: dict[str, Any],
        risk_reward: dict[str, Any],
        volatility_warning: dict[str, Any],
        timeframe: dict[str, Any],
    ) -> dict[str, Any]:
        risk_level = self._risk_level(trend, funding, volatility_warning, timeframe)
        market_state = self._market_state(trend, funding, volatility_warning)
        grade = self._opportunity_grade(scores["overall_score"], risk_level, risk_reward, funding, trend)
        advice = self._one_sentence_advice(trend, risk_level, grade)
        return {
            "current_price": current_price,
            "price_change_24h": price_change_24h,
            "trend": trend["direction"],
            "market_state": market_state,
            "overall_score": scores["overall_score"],
            "opportunity_grade": grade,
            "risk_level": risk_level,
            "one_sentence_advice": advice,
            "risk_reward": risk_reward,
        }

    @staticmethod
    def _risk_level(trend: dict[str, Any], funding: dict[str, Any], volatility_warning: dict[str, Any], timeframe: dict[str, Any]) -> str:
        points = 0
        if volatility_warning["triggered"]:
            points += 2
        if trend["atr_level"] == "高":
            points += 1
        if trend["is_overheated"] or trend["has_reversal_risk"]:
            points += 1
        if funding.get("level") in {"极高", "偏高"}:
            points += 1
        if timeframe.get("has_conflict"):
            points += 1
        if points >= 4:
            return "极高"
        if points >= 2:
            return "高"
        if points == 1:
            return "中"
        return "低"

    @staticmethod
    def _market_state(trend: dict[str, Any], funding: dict[str, Any], volatility_warning: dict[str, Any]) -> str:
        states = []
        if trend["direction"] == "震荡":
            states.append("震荡行情")
        else:
            states.append("趋势行情")
        if volatility_warning["triggered"] or trend["atr_level"] == "高":
            states.append("高波动")
        if funding.get("long_crowded"):
            states.append("多头拥挤")
        if funding.get("short_crowded"):
            states.append("空头拥挤")
        return " / ".join(states)

    @staticmethod
    def _opportunity_grade(
        score: int,
        risk_level: str,
        risk_reward: dict[str, Any],
        funding: dict[str, Any],
        trend: dict[str, Any],
    ) -> str:
        ratio = risk_reward.get("target2_ratio") or risk_reward.get("target1_ratio") or 0
        funding_normal = funding.get("level") in {"低", "正常", "负值"}
        if trend["direction"] != "震荡" and score >= 80 and funding_normal and ratio >= 3 and risk_level in {"低", "中"}:
            return "S"
        if trend["direction"] != "震荡" and score >= 65 and ratio >= 2 and risk_level != "极高":
            return "A"
        if score >= 50 and risk_level != "极高":
            return "B"
        if score >= 35:
            return "C"
        return "D"

    @staticmethod
    def _one_sentence_advice(trend: dict[str, Any], risk_level: str, grade: str) -> str:
        if risk_level in {"高", "极高"}:
            return "风险项偏多，优先等待波动和冲突信号收敛后再评估。"
        if grade in {"C", "D"} or trend["direction"] == "震荡":
            return "信号不够清晰，当前更适合观望或等待关键位确认。"
        if trend["direction"] == "偏多":
            return "仅在回踩支撑且量价未转弱时观察轻仓做多机会。"
        return "仅在反弹承压且风险收益比足够时观察轻仓做空机会。"

    @staticmethod
    def _risk_reward(price: float, direction: str, support_resistance: dict[str, Any]) -> dict[str, Any]:
        supports = support_resistance["support_levels"]
        resistances = support_resistance["resistance_levels"]
        if direction == "偏空":
            stop = resistances[0]["price"] if resistances else None
            target1 = supports[0]["price"] if supports else None
            target2 = supports[1]["price"] if len(supports) > 1 else None
            risk = (stop - price) / price if stop and stop > price else None
            reward1 = (price - target1) / price if target1 and target1 < price else None
            reward2 = (price - target2) / price if target2 and target2 < price else None
        else:
            stop = supports[0]["price"] if supports else None
            target1 = resistances[0]["price"] if resistances else None
            target2 = resistances[1]["price"] if len(resistances) > 1 else None
            risk = (price - stop) / price if stop and stop < price else None
            reward1 = (target1 - price) / price if target1 and target1 > price else None
            reward2 = (target2 - price) / price if target2 and target2 > price else None

        return {
            "stop_price": stop,
            "target1": target1,
            "target2": target2,
            "risk_pct": risk * 100 if risk is not None else None,
            "reward1_pct": reward1 * 100 if reward1 is not None else None,
            "reward2_pct": reward2 * 100 if reward2 is not None else None,
            "target1_ratio": reward1 / risk if risk and reward1 else None,
            "target2_ratio": reward2 / risk if risk and reward2 else None,
        }

    @staticmethod
    def _risk_reward_analysis(price: float, risk_reward: dict[str, Any], trend: dict[str, Any]) -> dict[str, Any]:
        ratio2 = risk_reward.get("target2_ratio")
        ratio1 = risk_reward.get("target1_ratio")
        best_ratio = ratio2 or ratio1
        if trend["direction"] == "震荡":
            evaluation = "趋势方向不明确，风险收益比只能作为观察参考。"
        elif best_ratio is None:
            evaluation = "关键支撑/压力不足，暂无法形成可靠风险收益比。"
        elif best_ratio >= 2:
            evaluation = "风险收益比达到基础观察标准，但仍需等待入场确认。"
        else:
            evaluation = "风险收益比不足，当前参与性价比偏低。"
        return {
            "current_price": price,
            "stop_zone": risk_reward.get("stop_price"),
            "target1": risk_reward.get("target1"),
            "target2": risk_reward.get("target2"),
            "loss_pct": risk_reward.get("risk_pct"),
            "profit_pct_target1": risk_reward.get("reward1_pct"),
            "profit_pct_target2": risk_reward.get("reward2_pct"),
            "risk_reward_target1": ratio1,
            "risk_reward_target2": ratio2,
            "evaluation": evaluation,
        }

    @staticmethod
    def _role_advice(
        trend: dict[str, Any],
        support_resistance: dict[str, Any],
        funding: dict[str, Any],
        risk_reward: dict[str, Any],
    ) -> list[dict[str, Any]]:
        support = support_resistance["support_levels"][0]["price"] if support_resistance["support_levels"] else None
        resistance = support_resistance["resistance_levels"][0]["price"] if support_resistance["resistance_levels"] else None
        direction = trend["direction"]
        base_fit = direction != "震荡" and trend["has_reversal_risk"] is False
        funding_risk = "资金费率偏高，不建议持仓过夜。" if funding.get("long_crowded") else "关注费率变化。"
        return [
            {
                "role": "短线交易员",
                "suitable": base_fit,
                "watch_price": resistance if direction == "偏多" else support,
                "main_risk": funding_risk,
                "position_advice": "单次轻仓，等待 5m/1H 确认。",
                "leverage_advice": "不超过 5x",
                "stop_loss_advice": "跌破/突破最近关键位后退出。",
            },
            {
                "role": "波段交易员",
                "suitable": direction in {"偏多", "偏空"},
                "watch_price": support if direction == "偏多" else resistance,
                "main_risk": "4H/1D 方向冲突时不要提前重仓。",
                "position_advice": "分批等待回调或反弹确认。",
                "leverage_advice": "不超过 3x",
                "stop_loss_advice": "以 4H 关键位失守为失效条件。",
            },
            {
                "role": "保守型用户",
                "suitable": risk_reward.get("target1_ratio") is not None and risk_reward["target1_ratio"] >= 2,
                "watch_price": support,
                "main_risk": "信号冲突和高波动。",
                "position_advice": "单笔风险不超过账户 1%。",
                "leverage_advice": "杠杆 <= 3x",
                "stop_loss_advice": "使用硬止损，不追高。",
            },
            {
                "role": "激进型用户",
                "suitable": direction != "震荡",
                "watch_price": resistance if direction == "偏多" else support,
                "main_risk": "高杠杆下滑点和假突破。",
                "position_advice": "单笔风险不超过账户 3%。",
                "leverage_advice": "杠杆 <= 10x",
                "stop_loss_advice": "入场前先确定失效价。",
            },
            {
                "role": "量化用户",
                "suitable": True,
                "watch_price": trend["current_price"],
                "main_risk": "阈值漂移和样本不足。",
                "position_advice": "关注 OI 变化率、资金费率和 ATR 动态止损。",
                "leverage_advice": "由策略风险预算决定",
                "stop_loss_advice": "使用 ATR 或关键位动态止损。",
            },
        ]

    @staticmethod
    def _conflict_analysis(
        trend: dict[str, Any],
        funding: dict[str, Any],
        volume: dict[str, Any],
        oi: dict[str, Any],
        timeframe: dict[str, Any],
        scores: dict[str, Any],
        sentiment: dict[str, Any],
    ) -> list[dict[str, Any]]:
        conflicts = []

        def add(signal_a: str, signal_b: str, reason: str, dominant: str, advice: str, condition: str) -> None:
            conflicts.append({
                "signal_a": signal_a,
                "signal_b": signal_b,
                "reason": reason,
                "dominant_signal": dominant,
                "advice": advice,
                "confirmation_condition": condition,
            })

        if trend["direction"] == "偏多" and funding.get("level") in {"偏高", "极高"}:
            add("技术面偏多", "资金费率过热", "做多结构与持仓成本冲突", "资金费率风险权重更高", "轻仓或等待回调", "费率回落且价格守住支撑")
        if volume.get("relation") == "缩量上涨":
            add("价格上涨", "成交量不足", "上涨缺少量能确认", "量能确认更高", "等待放量突破", "成交量大于近 20 周期均量")
        if oi.get("trend") == "上升" and volume.get("price_change_pct") is not None and abs(volume["price_change_pct"]) < 0.1:
            add("OI 上升", "价格不涨", "可能有反向力量累积", "价格行为更高", "观望", "价格放量突破或跌破区间")
        if timeframe.get("has_conflict"):
            add("小周期方向", "大周期方向", "周期方向不一致", "大周期趋势更高", "等待确认", "1H 与 4H 重新同向")
        if scores.get("overall_score", 0) >= 70 and sentiment.get("one_sided_risk"):
            add("综合评分偏高", "情绪极端", "单一极端风险可能压制机会", "极端风险更高", "降低仓位", "情绪指标回到中性区")
        return conflicts

    @staticmethod
    def _trading_plan(
        price: float,
        trend: dict[str, Any],
        support_resistance: dict[str, Any],
        risk_reward: dict[str, Any],
        conflicts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        direction = "暂观望"
        if trend["direction"] == "偏多" and not conflicts:
            direction = "做多"
        elif trend["direction"] == "偏空" and not conflicts:
            direction = "做空"
        supports = support_resistance["support_levels"]
        resistances = support_resistance["resistance_levels"]
        if direction == "做多" and supports:
            entry = [supports[0]["price"], price]
        elif direction == "做空" and resistances:
            entry = [price, resistances[0]["price"]]
        else:
            entry = None
        return {
            "direction": direction,
            "entry_observation_zone": entry,
            "stop_loss": risk_reward.get("stop_price"),
            "take_profit_1": risk_reward.get("target1"),
            "take_profit_2": risk_reward.get("target2"),
            "max_loss_pct": 1 if direction == "暂观望" else 2,
            "position_pct": 0 if direction == "暂观望" else 10,
            "leverage": 1 if direction == "暂观望" else 3,
            "invalid_condition": "出现信号冲突、关键位失守或资金费率极端扩张时计划作废。",
            "disclaimer": "仅为计划草稿，不可直接代替用户下单，所有参数需用户自行确认。",
        }

    @classmethod
    def _strategy_parameter_advice(
        cls,
        price: float,
        trend: dict[str, Any],
        support_resistance: dict[str, Any],
        summary: dict[str, Any],
        timeframe: dict[str, Any],
    ) -> dict[str, Any]:
        atr_pct = cls._normalized_atr_pct(trend)
        risk_level = summary.get("risk_level") or "中"
        return {
            "grid_trading": cls._grid_trading_parameters(
                price,
                trend,
                support_resistance,
                atr_pct,
                risk_level,
                timeframe,
            ),
            "martingale_contract": cls._martingale_contract_parameters(
                price,
                trend,
                atr_pct,
                risk_level,
                timeframe,
            ),
            "disclaimer": "参数为分析快照下的保守配置草稿，不会自动下单；保存策略前需按账户资金、交易所限制和个人风险重新确认。",
        }

    @classmethod
    def _grid_trading_parameters(
        cls,
        price: float,
        trend: dict[str, Any],
        support_resistance: dict[str, Any],
        atr_pct: float,
        risk_level: str,
        timeframe: dict[str, Any],
    ) -> dict[str, Any]:
        support = cls._nearest_price(support_resistance.get("support_levels"))
        resistance = cls._nearest_price(support_resistance.get("resistance_levels"))
        half_range_pct = cls._clamp(atr_pct * 2.2, 1.5, 8.0)
        max_half_range_pct = cls._clamp(half_range_pct * 2.2, 4.0, 14.0)

        lower = support if support and support < price else price * (1 - half_range_pct / 100)
        upper = resistance if resistance and resistance > price else price * (1 + half_range_pct / 100)
        lower_distance_pct = (price - lower) / price * 100 if price else 0
        upper_distance_pct = (upper - price) / price * 100 if price else 0
        if lower_distance_pct < half_range_pct or lower_distance_pct > max_half_range_pct:
            lower = price * (1 - half_range_pct / 100)
        if upper_distance_pct < half_range_pct or upper_distance_pct > max_half_range_pct:
            upper = price * (1 + half_range_pct / 100)
        if lower <= 0 or upper <= lower:
            lower = price * 0.97
            upper = price * 1.03

        range_width_pct = (upper - lower) / price * 100 if price else 0
        target_spacing_pct = cls._clamp(atr_pct * 0.45, 0.3, 1.2)
        grid_count = int(round(cls._clamp(range_width_pct / target_spacing_pct, 6, 80)))
        spacing_pct = range_width_pct / grid_count if grid_count else None
        buffer_pct = cls._clamp(atr_pct, 0.8, 3.0)
        leverage = cls._conservative_leverage(risk_level, atr_pct, cap=3)

        if risk_level in {"高", "极高"}:
            suitability = "不建议"
        elif trend.get("direction") == "震荡" and not timeframe.get("has_conflict"):
            suitability = "适合"
        else:
            suitability = "谨慎"

        mode = {
            "偏多": "偏多低吸网格",
            "偏空": "偏空反弹网格",
        }.get(trend.get("direction"), "中性区间网格")
        return {
            "suitability": suitability,
            "mode": mode,
            "lower_price": cls._round_price(lower),
            "upper_price": cls._round_price(upper),
            "price_range": [cls._round_price(lower), cls._round_price(upper)],
            "grid_count": grid_count,
            "grid_spacing_pct": round(spacing_pct, 2) if spacing_pct is not None else None,
            "grid_spacing_price": cls._round_price((upper - lower) / grid_count) if grid_count else None,
            "leverage": leverage,
            "margin_mode": "cross",
            "stop_lower_price": cls._round_price(lower * (1 - buffer_pct / 100)),
            "stop_upper_price": cls._round_price(upper * (1 + buffer_pct / 100)),
            "range_basis": "最近支撑压力位 + 1H ATR 波动率",
            "notes": [
                "价格离开区间或 1H 趋势单边加速时停止补单。",
                "每格资金建议等额分配，单格成交额按账户预算自行缩放。",
            ],
        }

    @classmethod
    def _martingale_contract_parameters(
        cls,
        price: float,
        trend: dict[str, Any],
        atr_pct: float,
        risk_level: str,
        timeframe: dict[str, Any],
    ) -> dict[str, Any]:
        direction = {
            "偏多": "long",
            "偏空": "short",
        }.get(trend.get("direction"), "both")
        direction_label = {
            "long": "只做多",
            "short": "只做空",
            "both": "双向",
        }[direction]

        if risk_level in {"高", "极高"} or trend.get("atr_level") == "高" or timeframe.get("has_conflict"):
            cycle, bar = "short", "1H"
        elif timeframe.get("conclusion") in {"共振偏多", "共振偏空"} and risk_level == "低" and atr_pct < 1.2:
            cycle, bar = "long", "1D"
        else:
            cycle, bar = "medium", "4H"

        add_trigger_pct = round(cls._clamp(atr_pct * 0.85, 0.6, 4.0), 2)
        take_profit_pct = round(cls._clamp(add_trigger_pct * 0.45, 0.3, 1.8), 2)
        if risk_level in {"高", "极高"} or atr_pct >= 2.5:
            max_add_count = 3
        elif risk_level == "中" or atr_pct >= 1.3:
            max_add_count = 4
        else:
            max_add_count = 5

        initial_margin = 20.0
        add_margin = 20.0
        max_position = initial_margin + add_margin * max_add_count
        hard_stop_pct = round(cls._clamp(add_trigger_pct * (max_add_count + 2), 6.0, 20.0), 2)
        leverage = cls._conservative_leverage(risk_level, atr_pct, cap=3)
        suitability = "不建议" if risk_level == "极高" else "谨慎" if risk_level == "高" else "可观察"
        return {
            "suitability": suitability,
            "cycle": cycle,
            "bar": bar,
            "direction": direction,
            "direction_label": direction_label,
            "add_trigger_type": "pct",
            "add_trigger_value": add_trigger_pct,
            "add_trigger_price_delta": cls._round_price(price * add_trigger_pct / 100),
            "take_profit_type": "pct",
            "take_profit_value": take_profit_pct,
            "take_profit_price_delta": cls._round_price(price * take_profit_pct / 100),
            "initial_margin_usdt": initial_margin,
            "add_margin_usdt": add_margin,
            "max_add_count": max_add_count,
            "max_position_usdt": max_position,
            "leverage": leverage,
            "hard_stop_pct": hard_stop_pct,
            "fee_rate": 0.0005,
            "slippage_pct": 0.02,
            "risk": {
                "max_concurrent": 1,
                "max_daily_per_symbol": 2 if risk_level in {"高", "极高"} else 3,
                "max_daily_loss_pct": 2.0 if risk_level in {"高", "极高"} else 3.0,
            },
            "notes": [
                "保证金为模板值，保存策略前按账户资金等比例缩放。",
                "补仓后实际强平价以 OKX 持仓返回值为准。",
            ],
        }

    @staticmethod
    def _volatility_warning(df: pd.DataFrame) -> dict[str, Any]:
        if df.empty or len(df) < 2:
            return {"triggered": False, "change_pct": None, "message": ""}
        closes = df["close"].to_numpy(dtype=float)
        change_pct = PerpetualAnalysisEngine._pct_change(closes[-1], closes[-2])
        triggered = abs(change_pct) > 3
        return {
            "triggered": triggered,
            "change_pct": change_pct,
            "message": "当前行情波动剧烈，分析结论参考价值下降，请谨慎操作" if triggered else "",
        }

    @staticmethod
    def _safe_float(value: Any) -> float | None:
        if value is None or value == "":
            return None
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(parsed):
            return None
        return parsed

    @staticmethod
    def _last_number(values: Any) -> float | None:
        arr = np.asarray(values, dtype=float)
        valid = arr[np.isfinite(arr)]
        if len(valid) == 0:
            return None
        return float(valid[-1])

    @staticmethod
    def _pct_change(current: float | None, previous: float | None) -> float:
        if current is None or previous in (None, 0):
            return 0.0
        return (float(current) - float(previous)) / float(previous) * 100

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        return max(low, min(high, value))

    @classmethod
    def _normalized_atr_pct(cls, trend: dict[str, Any]) -> float:
        value = cls._safe_float(trend.get("atr_pct"))
        if value is None or value <= 0:
            return 1.0
        return cls._clamp(value, 0.2, 8.0)

    @classmethod
    def _nearest_price(cls, levels: list[dict[str, Any]] | None) -> float | None:
        if not levels:
            return None
        for level in levels:
            price = cls._safe_float(level.get("price"))
            if price is not None and price > 0:
                return price
        return None

    @staticmethod
    def _round_price(value: float | None) -> float | None:
        if value is None:
            return None
        if value >= 100:
            return round(value, 2)
        if value >= 1:
            return round(value, 4)
        if value >= 0.01:
            return round(value, 6)
        return round(value, 8)

    @staticmethod
    def _conservative_leverage(risk_level: str, atr_pct: float, *, cap: int) -> int:
        if risk_level in {"高", "极高"} or atr_pct >= 2.5:
            return 1
        if risk_level == "中" or atr_pct >= 1.2:
            return min(2, cap)
        return min(3, cap)
