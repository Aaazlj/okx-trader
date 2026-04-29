"""
脉冲急拉做空 + 均值回归策略（纯做空）
动态扫描涨幅榜 → 脉冲拉升 + EMA/BOLL 偏离 + 量价背离 + 上影滞涨
同时注册为 spike_fade 和 mean_reversion
"""
import time

import numpy as np
import pandas as pd

from strategies.base import IStrategy
from indicators.technical import calc_ema, calc_boll, calc_sma
from utils.logger import get_logger

logger = get_logger("SpikeFadeMR")


class SpikeFadeMRStrategy(IStrategy):
    """
    脉冲急拉做空 + 均值回归

    标的筛选：涨幅榜前 20 + 连续在榜 5 分钟 + 流动性 + 波动率
    入场（全部满足）：
      ① 1m 涨幅 ≥ 1.2% 或连续 3 根累计 ≥ 2.0%
      ② EMA20 正向偏离 ≥ 1.0% 且触碰 BOLL 上轨
      ③ 创 15 根新高 K 线量缩 ≥ 30%
      ④ 上影线占比 ≥ 50%，实体/振幅 ≤ 0.3
    """

    def __init__(self):
        self._rank_tracker: dict[str, float] = {}

    @property
    def name(self) -> str:
        return "脉冲急拉做空+均值回归"

    @property
    def direction(self) -> str:
        return "short"

    # ═══════════════════════════════════════════
    # 动态标的扫描
    # ═══════════════════════════════════════════

    def scan_candidates(self, client) -> list[str]:
        """动态扫描涨幅榜候选标的"""
        try:
            tickers = client.get_tickers()
        except Exception as e:
            logger.error(f"获取 tickers 失败: {e}")
            return []

        if not tickers:
            return []

        rank_top_n = 20
        rank_duration_sec = 5 * 60  # 5 分钟
        min_vol_24h = 50_000_000
        max_spread_pct = 0.08
        min_volatility_pct = 3.0

        # 按涨幅排序取前 N
        sorted_tickers = sorted(tickers, key=lambda t: t["chg_pct"], reverse=True)
        top_n = sorted_tickers[:rank_top_n]
        top_ids = {t["inst_id"] for t in top_n}

        now = time.time()

        # 更新驻留追踪器
        for inst_id in top_ids:
            if inst_id not in self._rank_tracker:
                self._rank_tracker[inst_id] = now

        expired = [k for k in self._rank_tracker if k not in top_ids]
        for k in expired:
            del self._rank_tracker[k]

        candidates = []
        ticker_map = {t["inst_id"]: t for t in top_n}

        for inst_id, first_seen in self._rank_tracker.items():
            if now - first_seen < rank_duration_sec:
                continue

            t = ticker_map.get(inst_id)
            if not t:
                continue

            # 24h 成交额
            if t["vol_ccy_24h"] < min_vol_24h:
                continue

            # 点差
            bid, ask = t["bid_px"], t["ask_px"]
            if bid > 0 and ask > 0:
                spread_pct = (ask - bid) / bid * 100
                if spread_pct > max_spread_pct:
                    continue

            # 24h 波动率 (用涨跌幅绝对值近似)
            if abs(t["chg_pct"]) < min_volatility_pct:
                continue

            candidates.append(inst_id)

        if candidates:
            logger.info(f"📊 脉冲策略候选: {candidates}")

        return candidates

    # ═══════════════════════════════════════════
    # 信号检测
    # ═══════════════════════════════════════════

    def check_signal(self, df: pd.DataFrame, params: dict) -> dict | None:
        # ── 参数 ──
        spike_single_pct = params.get("spike_single_pct", 1.2)
        spike_3bar_pct = params.get("spike_3bar_pct", 2.0)
        ema_deviation_pct = params.get("ema_deviation_pct", 1.0)
        boll_period = params.get("boll_period", 20)
        boll_std = params.get("boll_std", 2.0)
        new_high_lookback = params.get("new_high_lookback", 15)
        vol_shrink_pct = params.get("vol_shrink_pct", 30)
        upper_wick_min_pct = params.get("upper_wick_min_pct", 50)
        body_ratio_max = params.get("body_ratio_max", 0.3)
        tp1_pct = params.get("tp1_pct", 0.8)
        sl_pct = params.get("sl_pct", 0.5)

        min_len = max(boll_period + 2, new_high_lookback + 3, 30)
        if len(df) < min_len:
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

        if idx < new_high_lookback + 2:
            return None

        cur_close = closes[idx]
        cur_open = opens[idx]
        cur_high = highs[idx]
        cur_low = lows[idx]
        cur_vol = volumes[idx]
        prev_vol = volumes[idx - 1]

        # ═══ 条件 ① 脉冲涨幅 ═══
        # 单根 1m 涨幅 >= spike_single_pct
        single_chg = (cur_close - opens[idx]) / opens[idx] * 100 if opens[idx] > 0 else 0
        # 连续 3 根累计涨幅
        cum_chg = 0
        if idx >= 2:
            cum_chg = (cur_close - opens[idx - 2]) / opens[idx - 2] * 100 if opens[idx - 2] > 0 else 0

        if single_chg < spike_single_pct and cum_chg < spike_3bar_pct:
            return None

        # ═══ 条件 ② EMA20 偏离 + 触碰 BOLL 上轨 ═══
        ema20 = calc_ema(closes, 20)
        upper, mid, _ = calc_boll(closes, boll_period, boll_std)

        if np.isnan(ema20[idx]) or np.isnan(upper[idx]):
            return None

        ema_dev = (cur_close - ema20[idx]) / ema20[idx] * 100
        if ema_dev < ema_deviation_pct:
            return None

        # 触碰 BOLL 上轨：最高价 >= 上轨
        if cur_high < upper[idx]:
            return None

        # ═══ 条件 ③ 创 15 根新高 + 量缩 30% ═══
        lookback_highs = highs[idx - new_high_lookback : idx]
        if cur_high <= np.max(lookback_highs):
            return None

        if prev_vol <= 0:
            return None
        vol_shrink = (prev_vol - cur_vol) / prev_vol * 100
        if vol_shrink < vol_shrink_pct:
            return None

        # ═══ 条件 ④ 上影线占比 + 实体/振幅 ═══
        candle_range = cur_high - cur_low
        if candle_range <= 0:
            return None

        body = abs(cur_close - cur_open)
        body_ratio = body / candle_range
        if body_ratio > body_ratio_max:
            return None

        upper_wick = cur_high - max(cur_close, cur_open)
        upper_wick_pct = upper_wick / candle_range * 100
        if upper_wick_pct < upper_wick_min_pct:
            return None

        # ── 止盈止损 ──
        tp_price = cur_close * (1 - tp1_pct / 100)
        sl_price = cur_close * (1 + sl_pct / 100)

        return {
            "direction": "short",
            "price": round(cur_close, 4),
            "tp_price": round(tp_price, 4),
            "sl_price": round(sl_price, 4),
            "managed_exit": True,
            "exit_rules": {
                "tp1_pct": params.get("tp1_pct", 0.8),
                "tp2_pct": params.get("tp2_pct", 1.5),
                "tp1_ratio": params.get("tp1_ratio", 0.5),
                "sl_pct": params.get("sl_pct", 0.5),
                "breakeven_trigger_pct": params.get("breakeven_trigger_pct", 0.5),
                "extreme_tp_pct": params.get("extreme_tp_pct", 2.0),
                "extreme_tp_sec": params.get("extreme_tp_sec", 30),
                "time_stop_sec": params.get("time_stop_sec", 300),
            },
            "reason": (
                f"🔴 脉冲做空 | 涨幅={max(single_chg, cum_chg):.2f}% | "
                f"EMA偏离={ema_dev:.2f}% | 量缩={vol_shrink:.0f}% | "
                f"实体比={body_ratio:.2f}"
            ),
        }

    def compute_indicators(self, df: pd.DataFrame, params: dict) -> dict:
        closes = df["close"].values
        opens = df["open"].values
        highs = df["high"].values
        lows = df["low"].values
        volumes = df["volCcy"].values if "volCcy" in df.columns else df["vol"].values
        idx = len(df) - 1

        ema20 = calc_ema(closes, 20)
        upper, mid, lower = calc_boll(closes, params.get("boll_period", 20))

        candle_range = highs[idx] - lows[idx]
        body = abs(closes[idx] - opens[idx])

        result = {
            "price": round(closes[idx], 4),
            "ema20": round(ema20[idx], 4) if not np.isnan(ema20[idx]) else None,
            "boll_upper": round(upper[idx], 4) if not np.isnan(upper[idx]) else None,
            "boll_mid": round(mid[idx], 4) if not np.isnan(mid[idx]) else None,
            "volume": round(volumes[idx], 2),
            "body_ratio": round(body / candle_range, 4) if candle_range > 0 else 0,
        }

        # EMA 偏离
        if not np.isnan(ema20[idx]) and ema20[idx] > 0:
            result["ema_deviation_pct"] = round(
                (closes[idx] - ema20[idx]) / ema20[idx] * 100, 2
            )

        # 单根涨幅
        if opens[idx] > 0:
            result["single_chg_pct"] = round(
                (closes[idx] - opens[idx]) / opens[idx] * 100, 2
            )

        # 量缩
        if idx > 0 and volumes[idx - 1] > 0:
            result["vol_shrink_pct"] = round(
                (volumes[idx - 1] - volumes[idx]) / volumes[idx - 1] * 100, 2
            )

        # 上影线占比
        if candle_range > 0:
            upper_wick = highs[idx] - max(closes[idx], opens[idx])
            result["upper_wick_pct"] = round(upper_wick / candle_range * 100, 2)

        return result
