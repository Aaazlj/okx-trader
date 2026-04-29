"""
高潮衰竭剥头皮策略（纯做空）
捕捉暴涨币种的多头高潮衰竭信号，量价背离 + 长上影滞涨
带状态：内部维护涨幅榜驻留追踪器
"""
import time

import numpy as np
import pandas as pd

from strategies.base import IStrategy
from utils.logger import get_logger

logger = get_logger("ClimaxExhaustion")


class ClimaxExhaustionScalpStrategy(IStrategy):
    """
    高潮衰竭剥头皮 — 超短线反转做空

    标的筛选：OKX 涨幅榜前 N 名 + 持续 10 分钟 + 流动性过滤
    入场：1m K 线创 15 根新高 + 成交量缩 30%+ + 实体/振幅 ≤ 0.3
    止盈：0.3%~1% | 止损：0.3%~0.5%
    """

    def __init__(self):
        # 涨幅榜驻留追踪：inst_id -> 首次进入前 N 的时间戳
        self._rank_tracker: dict[str, float] = {}

    @property
    def name(self) -> str:
        return "高潮衰竭剥头皮"

    @property
    def direction(self) -> str:
        return "short"

    def scan_candidates(self, client) -> list[str]:
        """
        动态扫描候选标的（由 strategy_runner 调用）

        筛选逻辑：
        1. 涨幅榜前 rank_top_n 名
        2. 连续在榜 rank_duration_min 分钟
        3. 24h 成交额 >= min_vol_24h
        4. 买卖点差 <= max_spread_pct
        """
        try:
            tickers = client.get_tickers()
        except Exception as e:
            logger.error(f"获取 tickers 失败: {e}")
            return []

        if not tickers:
            return []

        # 按涨幅排序，取前 N
        rank_top_n = 8
        sorted_tickers = sorted(tickers, key=lambda t: t["chg_pct"], reverse=True)
        top_n = sorted_tickers[:rank_top_n]
        top_ids = {t["inst_id"] for t in top_n}

        now = time.time()
        rank_duration_sec = 10 * 60  # 10 分钟
        min_vol_24h = 50_000_000  # 5000 万 USDT
        max_spread_pct = 0.08

        # 更新驻留追踪器
        # 新进入的添加时间戳
        for inst_id in top_ids:
            if inst_id not in self._rank_tracker:
                self._rank_tracker[inst_id] = now

        # 移除已不在前 N 的
        expired = [k for k in self._rank_tracker if k not in top_ids]
        for k in expired:
            del self._rank_tracker[k]

        candidates = []
        ticker_map = {t["inst_id"]: t for t in top_n}

        for inst_id, first_seen in self._rank_tracker.items():
            # 持续性过滤
            if now - first_seen < rank_duration_sec:
                continue

            t = ticker_map.get(inst_id)
            if not t:
                continue

            # 流动性过滤：24h 成交额
            if t["vol_ccy_24h"] < min_vol_24h:
                continue

            # 点差过滤
            bid = t["bid_px"]
            ask = t["ask_px"]
            if bid > 0 and ask > 0:
                spread_pct = (ask - bid) / bid * 100
                if spread_pct > max_spread_pct:
                    continue

            candidates.append(inst_id)

        if candidates:
            logger.info(f"📊 剥头皮候选标的: {candidates}")

        return candidates

    def check_signal(self, df: pd.DataFrame, params: dict) -> dict | None:
        # ── 参数 ──
        new_high_lookback = params.get("new_high_lookback", 15)
        vol_shrink_pct = params.get("vol_shrink_pct", 30)
        body_ratio_max = params.get("body_ratio_max", 0.3)
        tp_pct = params.get("tp_pct", 0.5)
        sl_pct = params.get("sl_pct", 0.4)

        if len(df) < new_high_lookback + 2:
            return None

        closes = df["close"].values
        opens = df["open"].values
        highs = df["high"].values
        lows = df["low"].values
        volumes = df["volCcy"].values if "volCcy" in df.columns else df["vol"].values

        # 使用最后已确认 K 线
        if "confirm" in df.columns:
            confirmed = df[df["confirm"] == 1]
            idx = confirmed.index[-1] if len(confirmed) > 0 else len(df) - 2
        else:
            idx = len(df) - 1

        if idx < new_high_lookback + 1:
            return None

        cur_high = highs[idx]
        cur_close = closes[idx]
        cur_open = opens[idx]
        cur_low = lows[idx]
        cur_vol = volumes[idx]
        prev_vol = volumes[idx - 1]

        # ── 条件 1：创近 N 根 K 线新高 ──
        lookback_highs = highs[idx - new_high_lookback : idx]
        if cur_high <= np.max(lookback_highs):
            return None

        # ── 条件 2：成交量缩小 30%+ ──
        if prev_vol <= 0:
            return None
        vol_shrink = (prev_vol - cur_vol) / prev_vol * 100
        if vol_shrink < vol_shrink_pct:
            return None

        # ── 条件 3：实体/振幅 ≤ body_ratio_max ──
        candle_range = cur_high - cur_low
        if candle_range <= 0:
            return None
        body = abs(cur_close - cur_open)
        body_ratio = body / candle_range
        if body_ratio > body_ratio_max:
            return None

        # ── 止盈止损 ──
        tp_price = cur_close * (1 - tp_pct / 100)
        sl_price = cur_close * (1 + sl_pct / 100)

        return {
            "direction": "short",
            "price": round(cur_close, 4),
            "tp_price": round(tp_price, 4),
            "sl_price": round(sl_price, 4),
            "reason": (
                f"🔴 高潮衰竭做空 | 创{new_high_lookback}根新高 | "
                f"量缩{vol_shrink:.0f}% | 实体比={body_ratio:.2f}"
            ),
        }

    def compute_indicators(self, df: pd.DataFrame, params: dict) -> dict:
        closes = df["close"].values
        opens = df["open"].values
        highs = df["high"].values
        lows = df["low"].values
        volumes = df["volCcy"].values if "volCcy" in df.columns else df["vol"].values
        idx = len(df) - 1

        candle_range = highs[idx] - lows[idx]
        body = abs(closes[idx] - opens[idx])

        result = {
            "price": round(closes[idx], 4),
            "volume": round(volumes[idx], 2),
            "body_ratio": round(body / candle_range, 4) if candle_range > 0 else 0,
        }

        if idx > 0 and volumes[idx - 1] > 0:
            result["vol_shrink_pct"] = round(
                (volumes[idx - 1] - volumes[idx]) / volumes[idx - 1] * 100, 2
            )
            result["prev_volume"] = round(volumes[idx - 1], 2)

        # 近 15 根最高价
        lookback = min(15, idx)
        result["recent_high"] = round(float(np.max(highs[idx - lookback : idx + 1])), 4)
        result["is_new_high"] = bool(highs[idx] >= result["recent_high"])

        return result
