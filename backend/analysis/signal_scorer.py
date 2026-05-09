"""
6 维信号评分框架。
基于 trading-plan-generator skill 的 signal-framework.md。

输出 composite_score: -100 ~ +100
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

logger = get_logger("SignalScorer")

# 维度权重（清算数据不可用时按比例重分配）
DIMENSION_WEIGHTS = {
    "oi_trend": 20,
    "ls_ratio": 20,
    "funding_rate": 15,
    "liquidation": 15,  # 不可用
    "whale_position": 15,
    "technical": 15,
}


class SignalScorer:
    """6 维信号评分器。"""

    def __init__(self, client):
        self.client = client

    def score(self, symbol: str) -> dict[str, Any]:
        """
        计算综合信号评分。

        Returns:
            {
                "composite_score": int (-100~+100),
                "label": str,
                "breakdown": {dimension: {"score": int, "detail": str}},
            }
        """
        base_ccy = symbol.split("-")[0]
        inst_id = symbol if symbol.endswith("-USDT-SWAP") else f"{symbol}-USDT-SWAP"

        # 获取数据
        oi_data = self._fetch_oi(inst_id)
        ls_data = self._fetch_ls_ratio(base_ccy)
        funding_data = self._fetch_funding(inst_id)
        whale_data = self._fetch_whale_position(inst_id)
        tech_data = self._fetch_technical(inst_id)

        # 各维度评分
        breakdown = {}
        total = 0
        active_weight = 0

        # OI 趋势
        s, detail = self._score_oi(oi_data if not isinstance(oi_data, Exception) else None)
        breakdown["oi_trend"] = {"score": s, "detail": detail}
        total += s * DIMENSION_WEIGHTS["oi_trend"] / 20
        active_weight += DIMENSION_WEIGHTS["oi_trend"]

        # 多空比
        s, detail = self._score_ls_ratio(ls_data if not isinstance(ls_data, Exception) else None)
        breakdown["ls_ratio"] = {"score": s, "detail": detail}
        total += s * DIMENSION_WEIGHTS["ls_ratio"] / 20
        active_weight += DIMENSION_WEIGHTS["ls_ratio"]

        # 资金费率
        s, detail = self._score_funding(funding_data if not isinstance(funding_data, Exception) else None)
        breakdown["funding_rate"] = {"score": s, "detail": detail}
        total += s * DIMENSION_WEIGHTS["funding_rate"] / 15
        active_weight += DIMENSION_WEIGHTS["funding_rate"]

        # 清算数据（不可用）
        breakdown["liquidation"] = {"score": 0, "detail": "数据不可用，权重已重分配"}

        # 大户持仓
        s, detail = self._score_whale(whale_data if not isinstance(whale_data, Exception) else None)
        breakdown["whale_position"] = {"score": s, "detail": detail}
        total += s * DIMENSION_WEIGHTS["whale_position"] / 15
        active_weight += DIMENSION_WEIGHTS["whale_position"]

        # 技术指标
        s, detail = self._score_technical(tech_data if not isinstance(tech_data, Exception) else None)
        breakdown["technical"] = {"score": s, "detail": detail}
        total += s * DIMENSION_WEIGHTS["technical"] / 15
        active_weight += DIMENSION_WEIGHTS["technical"]

        # 归一化到 -100~+100
        composite = int(max(-100, min(100, total))) if active_weight > 0 else 0

        label = self._score_label(composite)

        return {
            "composite_score": composite,
            "label": label,
            "breakdown": breakdown,
        }

    # ── 数据获取 ──

    def _fetch_oi(self, inst_id: str) -> list[dict]:
        try:
            return self.client.get_open_interest_history(inst_id, period="1H") or []
        except Exception as e:
            logger.warning(f"OI 数据获取失败: {e}")
            return []

    def _fetch_ls_ratio(self, ccy: str) -> list[dict]:
        try:
            return self.client.get_long_short_account_ratio(ccy, period="1H") or []
        except Exception as e:
            logger.warning(f"多空比数据获取失败: {e}")
            return []

    def _fetch_funding(self, inst_id: str) -> dict | None:
        try:
            return self.client.get_funding_rate(inst_id)
        except Exception as e:
            logger.warning(f"资金费率获取失败: {e}")
            return None

    def _fetch_whale_position(self, inst_id: str) -> list[dict]:
        try:
            return self.client.get_long_short_position_ratio(inst_id, period="1H") or []
        except Exception as e:
            logger.warning(f"大户持仓数据获取失败: {e}")
            return []

    def _fetch_technical(self, inst_id: str) -> dict | None:
        try:
            import pandas as pd
            df = self.client.get_candles(inst_id, bar="1D", limit=30)
            if df is None or (hasattr(df, "empty") and df.empty):
                return None
            closes = df["close"].to_numpy(dtype=float)
            from indicators.technical import calc_rsi, calc_macd
            rsi = calc_rsi(closes)
            macd_line, signal_line, hist = calc_macd(closes)
            return {
                "rsi": float(rsi[-1]) if rsi is not None and len(rsi) > 0 else None,
                "macd": float(macd_line[-1]) if macd_line is not None and len(macd_line) > 0 else None,
                "signal": float(signal_line[-1]) if signal_line is not None and len(signal_line) > 0 else None,
                "hist": float(hist[-1]) if hist is not None and len(hist) > 0 else None,
                "prev_macd": float(macd_line[-2]) if macd_line is not None and len(macd_line) > 1 else None,
                "prev_signal": float(signal_line[-2]) if signal_line is not None and len(signal_line) > 1 else None,
            }
        except Exception as e:
            logger.warning(f"技术指标获取失败: {e}")
            return None

    # ── 维度评分 ──

    @staticmethod
    def _score_oi(data: list | None) -> tuple[int, str]:
        if not data or len(data) < 2:
            return 0, "数据不足"
        try:
            first = float(data[0].get("oi", 0))
            last = float(data[-1].get("oi", 0))
            if first == 0:
                return 0, "OI 数据异常"
            change_pct = (last - first) / first * 100

            if change_pct > 5:
                return 20, f"OI 上升 {change_pct:.1f}%（趋势强化）"
            if change_pct > 1:
                return 8, f"OI 小幅上升 {change_pct:.1f}%"
            if change_pct < -5:
                return -20, f"OI 下降 {change_pct:.1f}%（多头止损/空头回补）"
            if change_pct < -1:
                return -8, f"OI 小幅下降 {change_pct:.1f}%"
            return 0, f"OI 横盘 {change_pct:.1f}%"
        except (ValueError, TypeError, IndexError):
            return 0, "OI 数据解析失败"

    @staticmethod
    def _score_ls_ratio(data: list | None) -> tuple[int, str]:
        if not data:
            return 0, "数据不足"
        try:
            ratio = float(data[-1].get("ratio", 1.0))
            if ratio > 1.5:
                return -15, f"L/S={ratio:.2f}（多头极度拥挤，反转风险）"
            if ratio > 1.2:
                return -8, f"L/S={ratio:.2f}（多头偏多）"
            if ratio < 0.7:
                return 20, f"L/S={ratio:.2f}（空头极度拥挤，轧空机会）"
            if ratio < 0.9:
                return 8, f"L/S={ratio:.2f}（空头偏多）"
            return 0, f"L/S={ratio:.2f}（均衡）"
        except (ValueError, TypeError, IndexError):
            return 0, "多空比数据解析失败"

    @staticmethod
    def _score_funding(data: dict | None) -> tuple[int, str]:
        if not data:
            return 0, "数据不足"
        try:
            rate = float(data.get("fundingRate", 0))
            rate_pct = rate * 100
            if rate_pct > 0.1:
                return -15, f"资金费率 {rate_pct:.4f}%（做多成本极高，市场过热）"
            if rate_pct > 0.05:
                return -8, f"资金费率 {rate_pct:.4f}%（偏多拥挤）"
            if rate_pct < -0.05:
                return 15, f"资金费率 {rate_pct:.4f}%（做空过热，强烈看多信号）"
            if rate_pct < -0.01:
                return 8, f"资金费率 {rate_pct:.4f}%（做多成本低）"
            return 0, f"资金费率 {rate_pct:.4f}%（正常区间）"
        except (ValueError, TypeError):
            return 0, "资金费率解析失败"

    @staticmethod
    def _score_whale(data: list | None) -> tuple[int, str]:
        if not data or len(data) < 2:
            return 0, "数据不足"
        try:
            first = float(data[0].get("ratio", 1.0))
            last = float(data[-1].get("ratio", 1.0))
            if first == 0:
                return 0, "大户数据异常"
            change_pct = (last - first) / first * 100

            if change_pct > 5:
                return 15, f"大户净多头增加 {change_pct:.1f}%"
            if change_pct > 1:
                return 8, f"大户净多头小幅增加 {change_pct:.1f}%"
            if change_pct < -5:
                return -15, f"大户净空头增加 {abs(change_pct):.1f}%"
            if change_pct < -1:
                return -8, f"大户净空头小幅增加 {abs(change_pct):.1f}%"
            return 0, f"大户持仓变化不明显 {change_pct:.1f}%"
        except (ValueError, TypeError, IndexError):
            return 0, "大户数据解析失败"

    @staticmethod
    def _score_technical(data: dict | None) -> tuple[int, str]:
        if not data:
            return 0, "数据不足"
        rsi = data.get("rsi")
        hist = data.get("hist")
        prev_hist = data.get("prev_hist") or data.get("prev_macd")
        prev_signal = data.get("prev_signal")
        macd = data.get("macd")
        signal = data.get("signal")

        if rsi is None:
            return 0, "RSI 数据不足"

        # MACD 金叉/死叉判断
        macd_cross = None
        if hist is not None and prev_hist is not None:
            if prev_hist <= 0 and hist > 0:
                macd_cross = "golden"
            elif prev_hist >= 0 and hist < 0:
                macd_cross = "death"

        if rsi < 30 and macd_cross == "golden":
            return 15, f"RSI={rsi:.0f} 超卖 + MACD 金叉"
        if rsi > 70 and macd_cross == "death":
            return -15, f"RSI={rsi:.0f} 超买 + MACD 死叉"
        if rsi < 40 or macd_cross == "golden":
            return 8, f"RSI={rsi:.0f}" + (" + MACD 金叉" if macd_cross == "golden" else " 偏超卖")
        if rsi > 60 or macd_cross == "death":
            return -8, f"RSI={rsi:.0f}" + (" + MACD 死叉" if macd_cross == "death" else " 偏超买")
        return 0, f"RSI={rsi:.0f} 中性区间"

    @staticmethod
    def _score_label(score: int) -> str:
        if score >= 60:
            return "强势看多"
        if score >= 30:
            return "看多"
        if score > -30:
            return "震荡中性"
        if score > -60:
            return "看空"
        return "强势看空"
