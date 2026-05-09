"""
交易日志统计
从 trades 表查询：胜率、盈亏比、总 PnL、最大回撤、连续亏损。
滚动窗口：20/50/100 笔。
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

logger = get_logger("TradeJournal")


class TradeJournal:
    """交易统计分析器，为 Kelly Criterion 等 sizing 方法提供历史数据。"""

    def __init__(self, db):
        self.db = db

    async def get_stats(
        self, strategy_id: str, window: int = 50
    ) -> dict[str, Any]:
        """
        获取策略的滚动窗口交易统计。

        Returns:
            {
                "total_trades": int,
                "wins": int,
                "losses": int,
                "win_rate": float,
                "avg_win": float,
                "avg_loss": float,
                "profit_factor": float,
                "total_pnl": float,
                "max_drawdown": float,
                "max_consecutive_losses": int,
                "window": int,
            }
        """
        cursor = await self.db.execute(
            """SELECT pnl, status FROM trades
               WHERE strategy_id = ? AND status = 'closed' AND pnl IS NOT NULL
               ORDER BY exit_time DESC
               LIMIT ?""",
            (strategy_id, window),
        )
        rows = await cursor.fetchall()

        if not rows:
            return self._empty_stats(window)

        pnls = [float(r["pnl"]) for r in rows]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        total = len(pnls)
        win_count = len(wins)
        loss_count = len(losses)
        win_rate = win_count / total if total > 0 else 0

        avg_win = sum(wins) / win_count if win_count > 0 else 0
        avg_loss = abs(sum(losses) / loss_count) if loss_count > 0 else 0
        profit_factor = (sum(wins) / abs(sum(losses))) if losses and sum(losses) != 0 else float("inf")

        total_pnl = sum(pnls)
        max_dd = self._calc_max_drawdown(pnls)
        max_consec = self._calc_max_consecutive_losses(pnls)

        return {
            "total_trades": total,
            "wins": win_count,
            "losses": loss_count,
            "win_rate": round(win_rate, 4),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "profit_factor": round(profit_factor, 2),
            "total_pnl": round(total_pnl, 2),
            "max_drawdown": round(max_dd, 2),
            "max_consecutive_losses": max_consec,
            "window": window,
        }

    async def get_stats_all_windows(
        self, strategy_id: str
    ) -> dict[str, dict]:
        """获取 20/50/100 笔窗口的统计。"""
        return {
            "w20": await self.get_stats(strategy_id, 20),
            "w50": await self.get_stats(strategy_id, 50),
            "w100": await self.get_stats(strategy_id, 100),
        }

    @staticmethod
    def _calc_max_drawdown(pnls: list[float]) -> float:
        """计算最大回撤（累计 PnL 的最大峰谷差）。"""
        if not pnls:
            return 0.0
        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        # pnls 是从新到旧排列，反转为时间顺序
        for p in reversed(pnls):
            cumulative += p
            peak = max(peak, cumulative)
            dd = peak - cumulative
            max_dd = max(max_dd, dd)
        return max_dd

    @staticmethod
    def _calc_max_consecutive_losses(pnls: list[float]) -> int:
        """计算最大连续亏损次数。"""
        max_streak = 0
        current = 0
        for p in pnls:
            if p <= 0:
                current += 1
                max_streak = max(max_streak, current)
            else:
                current = 0
        return max_streak

    @staticmethod
    def _empty_stats(window: int) -> dict:
        return {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "profit_factor": 0.0,
            "total_pnl": 0.0,
            "max_drawdown": 0.0,
            "max_consecutive_losses": 0,
            "window": window,
        }
