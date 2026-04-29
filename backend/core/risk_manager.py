"""
风控管理器 — 策略级风控状态管理
内存维护，每日自动重置
"""
import time
from datetime import datetime

from utils.logger import get_logger

logger = get_logger("RiskManager")


class RiskManager:
    """策略级风控管理"""

    def __init__(self):
        # 当日累计盈亏 %（按 strategy_id）
        self._daily_pnl: dict[str, float] = {}
        # 单币种单日开仓次数：strategy_id -> {symbol: count}
        self._daily_trades: dict[str, dict[str, int]] = {}
        # 连续止损次数
        self._consecutive_losses: dict[str, int] = {}
        # 暂停到的时间戳（连续止损触发）
        self._pause_until: dict[str, float] = {}
        # 当前持仓 symbol 集合
        self._concurrent_positions: dict[str, set[str]] = {}
        # 上次重置日期
        self._last_reset_date: str = ""

    def _auto_reset(self):
        """每日自动重置"""
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self._last_reset_date:
            self._daily_pnl.clear()
            self._daily_trades.clear()
            self._consecutive_losses.clear()
            self._pause_until.clear()
            self._last_reset_date = today
            logger.info(f"风控状态已重置 ({today})")

    def can_open(
        self, strategy_id: str, symbol: str, params: dict
    ) -> tuple[bool, str]:
        """
        检查是否允许开仓

        Args:
            params: 风控参数 (max_position_pct, max_concurrent, max_daily_per_symbol, max_daily_loss_pct)

        Returns:
            (允许开仓, 拒绝原因)
        """
        self._auto_reset()

        max_concurrent = params.get("max_concurrent", 3)
        max_daily_per_symbol = params.get("max_daily_per_symbol", 3)
        max_daily_loss_pct = params.get("max_daily_loss_pct", 3.0)

        # 1. 暂停检查（连续止损触发的冷却）
        pause_ts = self._pause_until.get(strategy_id, 0)
        if time.time() < pause_ts:
            remaining = int(pause_ts - time.time())
            return False, f"连续止损冷却中，剩余 {remaining}s"

        # 2. 单日累计亏损检查
        daily_pnl = self._daily_pnl.get(strategy_id, 0)
        if daily_pnl <= -max_daily_loss_pct:
            return False, f"单日亏损已达 {daily_pnl:.2f}%，今日停止"

        # 3. 同时持仓数检查
        current_positions = self._concurrent_positions.get(strategy_id, set())
        if len(current_positions) >= max_concurrent:
            return False, f"同时持仓已达 {len(current_positions)}/{max_concurrent}"

        # 4. 单币种单日开仓次数检查
        symbol_counts = self._daily_trades.get(strategy_id, {})
        count = symbol_counts.get(symbol, 0)
        if count >= max_daily_per_symbol:
            return False, f"{symbol} 今日已开仓 {count}/{max_daily_per_symbol} 次"

        return True, ""

    def record_open(self, strategy_id: str, symbol: str):
        """记录开仓"""
        self._auto_reset()

        # 更新持仓集合
        if strategy_id not in self._concurrent_positions:
            self._concurrent_positions[strategy_id] = set()
        self._concurrent_positions[strategy_id].add(symbol)

        # 更新单币种单日次数
        if strategy_id not in self._daily_trades:
            self._daily_trades[strategy_id] = {}
        self._daily_trades[strategy_id][symbol] = (
            self._daily_trades[strategy_id].get(symbol, 0) + 1
        )

    def record_close(self, strategy_id: str, symbol: str, pnl_pct: float):
        """
        记录平仓结果

        Args:
            pnl_pct: 本笔盈亏百分比（正=盈利，负=亏损）
        """
        self._auto_reset()

        # 移出持仓集合
        positions = self._concurrent_positions.get(strategy_id, set())
        positions.discard(symbol)

        # 更新日累计盈亏
        self._daily_pnl[strategy_id] = self._daily_pnl.get(strategy_id, 0) + pnl_pct

        # 更新连续止损
        if pnl_pct < 0:
            losses = self._consecutive_losses.get(strategy_id, 0) + 1
            self._consecutive_losses[strategy_id] = losses

            if losses >= 3:
                # 连续 3 笔止损，暂停 1 小时
                self._pause_until[strategy_id] = time.time() + 3600
                self._consecutive_losses[strategy_id] = 0
                logger.warning(
                    f"⚠️ 策略 {strategy_id} 连续 {losses} 笔止损，暂停 1 小时"
                )
        else:
            # 盈利则重置连续止损计数
            self._consecutive_losses[strategy_id] = 0

        daily_total = self._daily_pnl.get(strategy_id, 0)
        logger.info(
            f"📊 风控 | {strategy_id} | {symbol} | "
            f"本笔: {pnl_pct:+.2f}% | 日累计: {daily_total:+.2f}%"
        )
