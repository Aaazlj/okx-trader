"""
情绪数据获取。
优先尝试 OKX News REST API，降级用多空比作为代理。
"""
from __future__ import annotations

import time
from typing import Any

import httpx

import config
from utils.logger import get_logger

logger = get_logger("SentimentFetcher")

# 缓存：{symbol: {"data": ..., "ts": ...}}
_cache: dict[str, dict] = {}
_CACHE_TTL = 300  # 5 分钟


class SentimentFetcher:
    """获取币种情绪数据。"""

    def __init__(self, client):
        self.client = client

    def get(self, symbol: str) -> dict[str, Any] | None:
        """
        获取情绪数据。

        Returns:
            {
                "source": "okx_news" | "ls_ratio_proxy",
                "label": "bullish" | "bearish" | "neutral" | "mixed",
                "bullish_ratio": float,
                "bearish_ratio": float,
                "mention_count": int | None,
                "detail": str,
            }
        """
        cache_key = symbol.upper()
        cached = _cache.get(cache_key)
        if cached and time.time() - cached["ts"] < _CACHE_TTL:
            return cached["data"]

        # 尝试 OKX News API
        result = self._fetch_okx_news(symbol)
        if result is None:
            # 降级：用多空比代理
            result = self._fetch_ls_ratio_proxy(symbol)

        if result:
            _cache[cache_key] = {"data": result, "ts": time.time()}
        return result

    def _fetch_okx_news(self, symbol: str) -> dict[str, Any] | None:
        """尝试通过 OKX News API 获取情绪数据。"""
        try:
            base_ccy = symbol.split("-")[0].upper()
            with httpx.Client(timeout=10) as client:
                # OKX News sentiment endpoint
                resp = client.get(
                    f"{config.OPENAI_API_URL.replace('/v1', '')}/api/v5/rubik/insight/news/coin-sentiment",
                    params={"coin": base_ccy},
                    headers={"Content-Type": "application/json"},
                )
                if resp.status_code != 200:
                    return None
                data = resp.json()
                if data.get("code") != "0" or not data.get("data"):
                    return None

                item = data["data"][0] if isinstance(data["data"], list) and data["data"] else data["data"]
                bullish = float(item.get("bullishRatio", 50))
                bearish = float(item.get("bearishRatio", 50))
                mention = int(item.get("mentionCount", 0))

                if bullish > 60:
                    label = "bullish"
                elif bearish > 60:
                    label = "bearish"
                elif abs(bullish - bearish) < 10:
                    label = "neutral"
                else:
                    label = "mixed"

                return {
                    "source": "okx_news",
                    "label": label,
                    "bullish_ratio": bullish,
                    "bearish_ratio": bearish,
                    "mention_count": mention,
                    "detail": f"新闻情绪: {label}, 看多{bullish:.0f}% 看空{bearish:.0f}%, 提及{mention}次",
                }
        except Exception as e:
            logger.debug(f"OKX News API 不可用: {e}")
            return None

    def _fetch_ls_ratio_proxy(self, symbol: str) -> dict[str, Any] | None:
        """降级：用多空比账户数据作为情绪代理。"""
        try:
            base_ccy = symbol.split("-")[0].upper()
            data = self.client.get_long_short_account_ratio(base_ccy, period="1H")
            if not data:
                return None

            latest = data[-1]
            ratio = float(latest.get("ratio", 1.0))

            # ratio = long/short accounts
            if ratio > 1.3:
                label = "bullish"
                bullish_pct = ratio / (1 + ratio) * 100
                bearish_pct = 100 - bullish_pct
            elif ratio < 0.7:
                label = "bearish"
                bullish_pct = ratio / (1 + ratio) * 100
                bearish_pct = 100 - bullish_pct
            elif abs(ratio - 1.0) < 0.1:
                label = "neutral"
                bullish_pct = 50
                bearish_pct = 50
            else:
                label = "mixed"
                bullish_pct = ratio / (1 + ratio) * 100
                bearish_pct = 100 - bullish_pct

            return {
                "source": "ls_ratio_proxy",
                "label": label,
                "bullish_ratio": round(bullish_pct, 1),
                "bearish_ratio": round(bearish_pct, 1),
                "mention_count": None,
                "detail": f"账户多空比代理: {label}, L/S={ratio:.2f}, 多头{bullish_pct:.0f}% 空头{bearish_pct:.0f}%",
            }
        except Exception as e:
            logger.warning(f"多空比代理数据获取失败: {e}")
            return None
