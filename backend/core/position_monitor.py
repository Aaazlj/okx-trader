"""
持仓监控器 — 分批止盈 / 保本止损 / 时间止损 / 极端止盈
用于 managed_exit 策略的动态持仓管理
"""
import asyncio
import time
from dataclasses import dataclass, field

from exchange.okx_client import OKXClient
from core.risk_manager import RiskManager
from db.database import get_db
from ws import ws_manager
from utils.logger import get_logger

logger = get_logger("PositionMonitor")


@dataclass
class ManagedPosition:
    """被管理的持仓状态"""
    symbol: str
    strategy_id: str
    direction: str  # "short" / "long"
    entry_price: float
    total_quantity: float
    remaining_quantity: float
    open_time: float  # time.time()
    mgn_mode: str = "cross"
    tp1_triggered: bool = False
    peak_pnl_pct: float = 0.0
    exit_rules: dict = field(default_factory=dict)


class PositionMonitor:
    """持仓监控器"""

    def __init__(self, client: OKXClient, risk_manager: RiskManager):
        self.client = client
        self.risk_manager = risk_manager
        self._managed: dict[str, ManagedPosition] = {}  # symbol -> ManagedPosition
        self._task: asyncio.Task | None = None

    async def start(self):
        """启动后台监控循环"""
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("持仓监控器已启动")

    async def stop(self):
        """停止监控"""
        if self._task:
            self._task.cancel()
            self._task = None
        logger.info("持仓监控器已停止")

    def register(
        self,
        symbol: str,
        strategy_id: str,
        direction: str,
        entry_price: float,
        quantity: float,
        mgn_mode: str,
        exit_rules: dict,
    ):
        """注册一个由监控器管理的持仓"""
        self._managed[symbol] = ManagedPosition(
            symbol=symbol,
            strategy_id=strategy_id,
            direction=direction,
            entry_price=entry_price,
            total_quantity=quantity,
            remaining_quantity=quantity,
            open_time=time.time(),
            mgn_mode=mgn_mode,
            exit_rules=exit_rules,
        )
        logger.info(
            f"📋 注册持仓监控 | {symbol} {direction} | "
            f"入场={entry_price} | 张数={quantity}"
        )

    async def _monitor_loop(self):
        """每 2 秒检查所有被管理的持仓"""
        try:
            while True:
                if self._managed:
                    await self._check_all()
                await asyncio.sleep(2)
        except asyncio.CancelledError:
            logger.info("持仓监控循环已取消")

    async def _check_all(self):
        """检查所有被管理的持仓"""
        for symbol in list(self._managed.keys()):
            mp = self._managed.get(symbol)
            if not mp:
                continue
            try:
                positions = self.client.get_positions(inst_id=symbol)
                if not positions:
                    # 持仓已不存在（被 OCO 或手动平仓）
                    await self._on_closed(mp, 0, "外部平仓")
                    continue
                await self._evaluate(mp, positions[0])
            except Exception as e:
                logger.error(f"监控 {symbol} 异常: {e}")

    async def _evaluate(self, mp: ManagedPosition, okx_pos: dict):
        """评估是否需要执行退出操作"""
        rules = mp.exit_rules
        entry = mp.entry_price
        elapsed = time.time() - mp.open_time

        # 当前价格
        last_px = float(okx_pos.get("last", 0) or 0)
        if last_px <= 0:
            return

        # 盈亏百分比
        if mp.direction == "short":
            pnl_pct = (entry - last_px) / entry * 100
        else:
            pnl_pct = (last_px - entry) / entry * 100

        # 更新峰值盈亏
        mp.peak_pnl_pct = max(mp.peak_pnl_pct, pnl_pct)

        # ── 1. 极端止盈：N 秒内盈利 >= X% ──
        extreme_tp_pct = rules.get("extreme_tp_pct", 2.0)
        extreme_tp_sec = rules.get("extreme_tp_sec", 30)
        if elapsed <= extreme_tp_sec and pnl_pct >= extreme_tp_pct:
            await self._close_all(mp, pnl_pct, f"极端止盈 {pnl_pct:.2f}% in {elapsed:.0f}s")
            return

        # ── 2. 时间止损：超过 N 秒 ──
        time_stop_sec = rules.get("time_stop_sec", 300)
        if elapsed >= time_stop_sec:
            await self._close_all(mp, pnl_pct, f"时间止损 {elapsed:.0f}s")
            return

        # ── 3. 初始止损：亏损 >= X% ──
        sl_pct = rules.get("sl_pct", 0.5)
        breakeven_trigger = rules.get("breakeven_trigger_pct", 0.5)

        if mp.peak_pnl_pct >= breakeven_trigger:
            # 保本止损：曾盈利过阈值但回落到入场价
            if pnl_pct <= 0:
                await self._close_all(mp, pnl_pct, f"保本止损 (peak={mp.peak_pnl_pct:.2f}%)")
                return
        else:
            # 初始止损
            if pnl_pct <= -sl_pct:
                await self._close_all(mp, pnl_pct, f"初始止损 {pnl_pct:.2f}%")
                return

        # ── 4. TP1：盈利达阈值，平 50% ──
        tp1_pct = rules.get("tp1_pct", 0.8)
        tp1_ratio = rules.get("tp1_ratio", 0.5)
        if not mp.tp1_triggered and pnl_pct >= tp1_pct:
            close_sz = int(mp.total_quantity * tp1_ratio)
            if close_sz >= 1:
                success = self.client.close_partial(
                    mp.symbol, mp.direction, str(close_sz), mp.mgn_mode
                )
                if success:
                    mp.tp1_triggered = True
                    mp.remaining_quantity -= close_sz
                    logger.info(
                        f"✅ TP1 触发 | {mp.symbol} | 平{close_sz}张 | "
                        f"盈利 {pnl_pct:.2f}%"
                    )
                    await ws_manager.broadcast("trade_update", {
                        "strategy_id": mp.strategy_id,
                        "symbol": mp.symbol,
                        "event": "tp1",
                        "pnl_pct": round(pnl_pct, 2),
                        "time": time.strftime("%H:%M:%S"),
                    })
            return

        # ── 5. TP2：盈利达阈值，平剩余 ──
        tp2_pct = rules.get("tp2_pct", 1.5)
        if mp.tp1_triggered and pnl_pct >= tp2_pct:
            await self._close_all(mp, pnl_pct, f"TP2 止盈 {pnl_pct:.2f}%")
            return

    async def _close_all(self, mp: ManagedPosition, pnl_pct: float, reason: str):
        """全部平仓并清理"""
        success = self.client.close_position(mp.symbol, mp.mgn_mode)
        if success:
            logger.info(f"✅ 平仓 | {mp.symbol} | {reason} | 盈亏 {pnl_pct:+.2f}%")

            # 通知风控
            self.risk_manager.record_close(mp.strategy_id, mp.symbol, pnl_pct)

            # 更新数据库交易记录
            await self._update_trade_record(mp, pnl_pct, reason)

            # 广播
            await ws_manager.broadcast("trade_update", {
                "strategy_id": mp.strategy_id,
                "symbol": mp.symbol,
                "event": "closed",
                "reason": reason,
                "pnl_pct": round(pnl_pct, 2),
                "time": time.strftime("%H:%M:%S"),
            })

        await self._on_closed(mp, pnl_pct, reason)

    async def _on_closed(self, mp: ManagedPosition, pnl_pct: float, reason: str):
        """持仓关闭后清理"""
        self._managed.pop(mp.symbol, None)

        # 清理 positions 表
        try:
            db = await get_db()
            await db.execute(
                "DELETE FROM positions WHERE symbol = ? AND strategy_id = ?",
                (mp.symbol, mp.strategy_id),
            )
            await db.commit()
        except Exception as e:
            logger.error(f"清理持仓记录失败: {e}")

    async def _update_trade_record(self, mp: ManagedPosition, pnl_pct: float, reason: str):
        """更新 trades 表的平仓信息"""
        try:
            db = await get_db()
            # 计算实际盈亏金额（近似）
            if mp.direction == "short":
                exit_price = mp.entry_price * (1 - pnl_pct / 100)
            else:
                exit_price = mp.entry_price * (1 + pnl_pct / 100)

            ct_val = self.client.get_contract_value(mp.symbol)
            pnl_usdt = abs(pnl_pct / 100) * mp.total_quantity * ct_val * mp.entry_price
            if pnl_pct < 0:
                pnl_usdt = -pnl_usdt

            await db.execute(
                """UPDATE trades
                   SET exit_price = ?, pnl = ?, status = 'closed',
                       exit_time = datetime('now'), reason = reason || ' | ' || ?
                   WHERE strategy_id = ? AND symbol = ? AND status = 'open'
                   ORDER BY entry_time DESC LIMIT 1""",
                (round(exit_price, 4), round(pnl_usdt, 4), reason,
                 mp.strategy_id, mp.symbol),
            )
            await db.commit()
        except Exception as e:
            logger.error(f"更新交易记录失败: {e}")
