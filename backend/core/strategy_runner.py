"""
策略调度器
管理所有策略实例的生命周期：启动、停止、定时扫描
"""
import asyncio
import json
import time

from exchange.okx_client import OKXClient
from db.database import get_db
from strategies.registry import get_strategy
from core.trade_executor import TradeExecutor
from core.risk_manager import RiskManager
from core.position_monitor import PositionMonitor
from core.martingale_manager import MartingaleManager
from ws import ws_manager
from utils.logger import get_logger

logger = get_logger("StrategyRunner")


class StrategyRunner:
    """策略调度器 — 管理所有策略实例的运行"""

    def __init__(self, client: OKXClient):
        self.client = client
        self.executor = TradeExecutor(client)
        self.risk_manager = RiskManager()
        self.position_monitor = PositionMonitor(client, self.risk_manager)
        self.martingale_manager = MartingaleManager(client, self.risk_manager)
        self.tasks: dict[str, asyncio.Task] = {}
        self._running = False
        # 仓位互斥锁: symbol -> strategy_id
        self._symbol_locks: dict[str, str] = {}

    async def start(self):
        """启动所有激活策略"""
        self._running = True
        db = await get_db()
        cursor = await db.execute("SELECT * FROM strategies WHERE is_active = 1")
        rows = await cursor.fetchall()

        for row in rows:
            strategy_id = row["id"]
            await self._start_task(strategy_id)

        # 启动持仓监控器
        await self.position_monitor.start()

        logger.info(f"策略调度器已启动，运行中策略: {len(self.tasks)}")

    async def stop(self):
        """停止所有策略"""
        self._running = False
        for task in self.tasks.values():
            task.cancel()
        self.tasks.clear()
        await self.position_monitor.stop()
        logger.info("策略调度器已停止")

    async def start_strategy(self, strategy_id: str):
        """启动单个策略"""
        if strategy_id in self.tasks:
            logger.warning(f"策略 {strategy_id} 已在运行中")
            return
        await self._start_task(strategy_id)

    async def stop_strategy(self, strategy_id: str):
        """停止单个策略"""
        if strategy_id in self.tasks:
            self.tasks[strategy_id].cancel()
            del self.tasks[strategy_id]
            # 释放该策略锁定的所有 symbol
            self._symbol_locks = {
                s: sid for s, sid in self._symbol_locks.items() if sid != strategy_id
            }
            logger.info(f"策略 {strategy_id} 已停止")

    async def _start_task(self, strategy_id: str):
        """创建并启动策略扫描任务"""
        task = asyncio.create_task(self._scan_loop(strategy_id))
        self.tasks[strategy_id] = task
        logger.info(f"策略 {strategy_id} 已启动")

    async def _scan_loop(self, strategy_id: str):
        """单个策略的扫描循环"""
        try:
            while self._running:
                try:
                    await self._scan_once(strategy_id)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error(f"策略 {strategy_id} 扫描异常: {e}")
                    await ws_manager.broadcast("error", {
                        "strategy_id": strategy_id,
                        "message": str(e),
                    })

                # 从数据库读取 poll_interval
                db = await get_db()
                cursor = await db.execute(
                    "SELECT poll_interval FROM strategies WHERE id = ?", (strategy_id,)
                )
                row = await cursor.fetchone()
                interval = row["poll_interval"] if row else 5
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            logger.info(f"策略 {strategy_id} 扫描循环已取消")

    async def _scan_once(self, strategy_id: str):
        """执行一次策略扫描"""
        db = await get_db()
        cursor = await db.execute("SELECT * FROM strategies WHERE id = ?", (strategy_id,))
        row = await cursor.fetchone()
        if not row or not row["is_active"]:
            return

        strategy_type = row["strategy_type"]
        is_martingale = strategy_type == "martingale_contract"
        symbols = json.loads(row["symbols"])
        decision_mode = row["decision_mode"]
        if is_martingale:
            decision_mode = "technical"
        params = json.loads(row["params"])
        leverage = row["leverage"]
        order_amount = row["order_amount_usdt"]
        if is_martingale:
            order_amount = params.get("initial_margin_usdt", order_amount)
        mgn_mode = row["mgn_mode"]

        strategy = get_strategy(strategy_type)
        if not strategy:
            logger.error(f"策略类型未注册: {strategy_type}")
            return

        # 动态标的扫描（如高潮衰竭剥头皮）：symbols 为空时调用策略自身的扫描
        if not symbols and hasattr(strategy, "scan_candidates"):
            symbols = strategy.scan_candidates(self.client)

        # K 线周期：优先使用策略 params 中的 bar 配置
        bar = params.get("bar", "1m")
        # 多周期策略的高周期 K 线配置
        htf_bar = params.get("htf_bar")

        for symbol in symbols:
            # 仓位互斥检查
            if symbol in self._symbol_locks and self._symbol_locks[symbol] != strategy_id:
                continue

            # 检查是否已有持仓 → 更新 peak/trough
            positions = self.client.get_positions(inst_id=symbol)
            if positions:
                if is_martingale:
                    await self.martingale_manager.evaluate(
                        strategy_id=strategy_id,
                        symbol=symbol,
                        row=row,
                        okx_pos=positions[0],
                    )
                else:
                    await self._update_position_pnl(strategy_id, symbol, positions[0])
                continue
            if is_martingale:
                await self.martingale_manager.cleanup_missing_position(strategy_id, symbol)

            try:
                # 获取主周期 K 线
                df = self.client.get_candles(symbol, bar=bar, limit=500)
                if df.empty or len(df) < 30:
                    continue

                # 注入高周期数据到 params（多周期策略使用）
                scan_params = dict(params)
                if htf_bar:
                    df_htf = self.client.get_candles(symbol, bar=htf_bar, limit=100)
                    if not df_htf.empty:
                        scan_params["df_htf"] = df_htf

                signal = None
                indicators_snapshot = None

                if decision_mode == "ai":
                    # 纯 AI 决策
                    signal = await self._ai_decide(strategy, df, scan_params, row, symbol)
                    try:
                        indicators_snapshot = strategy.compute_indicators(df, scan_params)
                    except Exception:
                        pass
                elif decision_mode == "hybrid":
                    # 混合模式：技术指标预筛 → AI 二次确认
                    tech_signal = strategy.check_signal(df, scan_params)
                    try:
                        indicators_snapshot = strategy.compute_indicators(df, scan_params)
                    except Exception:
                        indicators_snapshot = None

                    if tech_signal:
                        logger.info(f"📊 技术信号 | {symbol} | {tech_signal['direction']} | {tech_signal['reason'][:40]}")
                        signal = await self._ai_decide_hybrid(
                            strategy, df, scan_params, row, symbol, tech_signal
                        )
                    else:
                        signal = None
                else:
                    # 纯技术指标决策
                    signal = strategy.check_signal(df, scan_params)
                    try:
                        indicators_snapshot = strategy.compute_indicators(df, scan_params)
                    except Exception:
                        pass

                # 记录信号到 strategy_signals 表
                await self._record_signal(
                    db, strategy_id, symbol, decision_mode, signal, indicators_snapshot
                )

                if signal:
                    logger.info(f"📡 信号检测 | {symbol} | {signal['reason']}")

                    # 风控检查
                    risk_params = scan_params.get("risk", {})
                    can_open, deny_reason = self.risk_manager.can_open(
                        strategy_id, symbol, risk_params
                    )
                    if not can_open:
                        logger.info(f"⛔ 风控拦截 | {symbol} | {deny_reason}")
                        continue

                    # 广播信号
                    await ws_manager.broadcast("signal", {
                        "strategy_id": strategy_id,
                        "symbol": symbol,
                        "signal": signal,
                        "time": time.strftime("%H:%M:%S"),
                    })

                    # 执行交易
                    result = await self.executor.execute(
                        strategy_id=strategy_id,
                        symbol=symbol,
                        signal=signal,
                        leverage=leverage,
                        order_amount=order_amount,
                        mgn_mode=mgn_mode,
                    )

                    if result:
                        # 记录开仓到风控
                        self.risk_manager.record_open(strategy_id, symbol)

                        if is_martingale and signal.get("martingale"):
                            await self.martingale_manager.register_entry(
                                strategy_id=strategy_id,
                                symbol=symbol,
                                direction=signal["direction"],
                                fill_price=result["fill_price"],
                                fill_sz=result["fill_sz"],
                                leverage=leverage,
                                base_order_usdt=order_amount,
                                mgn_mode=result["mgn_mode"],
                                params=scan_params,
                            )
                        # managed_exit 策略注册到持仓监控器
                        elif signal.get("managed_exit"):
                            self.position_monitor.register(
                                symbol=symbol,
                                strategy_id=strategy_id,
                                direction=signal["direction"],
                                entry_price=result["fill_price"],
                                quantity=result["fill_sz"],
                                mgn_mode=result["mgn_mode"],
                                exit_rules=signal.get("exit_rules", {}),
                            )

                    # 锁定 symbol
                    self._symbol_locks[symbol] = strategy_id

            except Exception as e:
                logger.error(f"扫描 {symbol} 异常: {e}")

    async def _record_signal(self, db, strategy_id, symbol, decision_mode, signal, indicators):
        """记录信号到 strategy_signals 表"""
        try:
            direction = signal.get("direction") if signal else "idle"
            confidence = signal.get("confidence", 0) if signal else 0
            reasoning = signal.get("reason", "") if signal else ""
            result = "signal" if signal else "idle"

            await db.execute(
                """INSERT INTO strategy_signals
                   (strategy_id, symbol, direction, confidence, reasoning, indicators, decision_mode, result)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    strategy_id, symbol, direction, confidence, reasoning,
                    json.dumps(indicators, ensure_ascii=False) if indicators else None,
                    decision_mode, result,
                ),
            )
            await db.commit()

            # 自动清理超过 500 条的旧记录
            await db.execute(
                """DELETE FROM strategy_signals WHERE id IN (
                    SELECT id FROM strategy_signals WHERE strategy_id = ?
                    ORDER BY created_at DESC LIMIT -1 OFFSET 500
                )""",
                (strategy_id,),
            )
            await db.commit()
        except Exception as e:
            logger.error(f"记录信号失败: {e}")

    async def _update_position_pnl(self, strategy_id: str, symbol: str, okx_pos: dict):
        """更新持仓的最高/最低盈亏"""
        try:
            upl = float(okx_pos.get("upl", 0) or 0)
            db = await get_db()

            cursor = await db.execute(
                "SELECT peak_pnl, trough_pnl FROM positions WHERE symbol = ? AND strategy_id = ?",
                (symbol, strategy_id),
            )
            row = await cursor.fetchone()
            if not row:
                return

            peak = max(row["peak_pnl"] or 0, upl)
            trough = min(row["trough_pnl"] or 0, upl)

            await db.execute(
                "UPDATE positions SET peak_pnl = ?, trough_pnl = ? WHERE symbol = ? AND strategy_id = ?",
                (peak, trough, symbol, strategy_id),
            )
            await db.commit()
        except Exception as e:
            logger.error(f"更新持仓盈亏失败: {e}")


    async def _ai_decide(self, strategy, df, params, row, symbol) -> dict | None:
        """AI 决策模式"""
        try:
            from ai.analyzer import AIAnalyzer
            analyzer = AIAnalyzer()

            # 获取 OI 数据（失败不影响主流程）
            oi_data = None
            try:
                oi_data = self.client.get_open_interest(symbol)
            except Exception:
                pass

            indicators = strategy.compute_indicators(df, params, oi_data=oi_data)
            ai_prompt = row["ai_prompt"] or ""
            min_confidence = row["ai_min_confidence"]

            result = await analyzer.analyze(
                symbol=symbol,
                indicators=indicators,
                strategy_name=strategy.name,
                custom_prompt=ai_prompt,
            )

            if not result:
                return None

            direction = result.get("direction", "idle").lower()
            confidence = result.get("confidence", 0)
            reasoning = result.get("reasoning", "")

            logger.info(
                f"🤖 AI 分析 | {symbol} | 方向: {direction} | "
                f"置信度: {confidence}% | 理由: {reasoning[:50]}"
            )

            if direction == "idle" or confidence < min_confidence:
                return None

            # 使用策略计算止盈止损
            closes = df["close"].values
            price = closes[-1]
            atr_pct = params.get("fixed_tp", 1.4)
            if direction == "short":
                tp_price = price * (1 - atr_pct / 100)
                sl_price = price * (1 + atr_pct * 0.7 / 100)
            else:
                tp_price = price * (1 + atr_pct / 100)
                sl_price = price * (1 - atr_pct * 0.7 / 100)

            def fmt_price(p: float) -> float:
                if p >= 1:
                    return round(p, 4)
                elif p >= 0.01:
                    return round(p, 6)
                else:
                    return round(p, 8)

            return {
                "direction": direction,
                "price": fmt_price(price),
                "tp_price": fmt_price(tp_price),
                "sl_price": fmt_price(sl_price),
                "reason": f"🤖 AI {direction.upper()} | 置信度 {confidence}% | {reasoning[:30]}",
            }
        except Exception as e:
            logger.error(f"AI 决策失败: {e}")
            return None

    async def _ai_decide_hybrid(self, strategy, df, params, row, symbol, tech_signal) -> dict | None:
        """混合决策模式：技术信号 + AI 二次确认"""
        try:
            from ai.analyzer import AIAnalyzer
            analyzer = AIAnalyzer()

            oi_data = None
            try:
                oi_data = self.client.get_open_interest(symbol)
            except Exception:
                pass

            indicators = strategy.compute_indicators(df, params, oi_data=oi_data)
            ai_prompt = row["ai_prompt"] or ""
            min_confidence = row["ai_min_confidence"]

            result = await analyzer.analyze_with_signal(
                symbol=symbol,
                indicators=indicators,
                strategy_name=strategy.name,
                technical_signal=tech_signal,
                custom_prompt=ai_prompt,
            )

            if not result:
                return None

            direction = result.get("direction", "idle").lower()
            confidence = result.get("confidence", 0)
            reasoning = result.get("reasoning", "")

            logger.info(
                f"🤖 AI 确认 | {symbol} | 技术:{tech_signal['direction']} → AI:{direction} | "
                f"置信度: {confidence}% | {reasoning[:50]}"
            )

            if direction == "idle" or confidence < min_confidence:
                return None

            closes = df["close"].values
            price = closes[-1]
            atr_pct = params.get("fixed_tp", 1.4)

            if direction == tech_signal.get("direction"):
                tp_price = tech_signal.get("tp_price", 0) or price * (1 + atr_pct / 100)
                sl_price = tech_signal.get("sl_price", 0) or price * (1 - atr_pct * 0.7 / 100)
            else:
                if direction == "short":
                    tp_price = price * (1 - atr_pct / 100)
                    sl_price = price * (1 + atr_pct * 0.7 / 100)
                else:
                    tp_price = price * (1 + atr_pct / 100)
                    sl_price = price * (1 - atr_pct * 0.7 / 100)

            def fmt_price(p: float) -> float:
                if p >= 1:
                    return round(p, 4)
                elif p >= 0.01:
                    return round(p, 6)
                else:
                    return round(p, 8)

            return {
                "direction": direction,
                "price": fmt_price(price),
                "tp_price": fmt_price(tp_price),
                "sl_price": fmt_price(sl_price),
                "reason": f"🔀 HYBRID {direction.upper()} | 技术:{tech_signal['direction']}→AI:{direction} | 置信度 {confidence}% | {reasoning[:30]}",
            }
        except Exception as e:
            logger.error(f"混合决策失败: {e}")
            return None
