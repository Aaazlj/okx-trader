"""
交易执行器
负责下单 + 设置 OCO 保护单 + 记录交易
"""
import time

from exchange.okx_client import OKXClient
from db.database import get_db
from ws import ws_manager
from utils.logger import get_logger

logger = get_logger("TradeExecutor")


class TradeExecutor:
    """交易执行器"""

    def __init__(self, client: OKXClient):
        self.client = client

    async def execute(
        self,
        strategy_id: str,
        symbol: str,
        signal: dict,
        leverage: int,
        order_amount: float,
        mgn_mode: str,
    ) -> dict | None:
        """
        执行交易

        Returns:
            开仓结果 dict (fill_price, fill_sz) 或 None
        """
        direction = signal["direction"]
        price = signal["price"]
        tp_price = signal["tp_price"]
        sl_price = signal["sl_price"]
        managed_exit = signal.get("managed_exit", False)

        # 验证品种是否存在
        try:
            ct_val = self.client.get_contract_value(symbol)
        except Exception:
            logger.error(f"❌ 品种不存在或查询失败 | {symbol}")
            return None

        # 设置杠杆
        self.client.set_leverage(symbol, leverage, mgn_mode)

        # 计算张数
        sz = self.client.calc_contract_size(symbol, order_amount, price, leverage)

        # 开仓方向: short -> sell, long -> buy
        side = "sell" if direction == "short" else "buy"

        # 市价下单
        order = self.client.place_market_order(symbol, side, str(sz), mgn_mode)
        if not order:
            logger.error(f"❌ 开仓失败 | {symbol} {direction}")
            return None

        order_id = order.get("ordId", "")

        # 等待成交
        filled = self.client.wait_order_filled(order_id, symbol)
        if not filled:
            logger.error(f"❌ 订单未成交 | {symbol} ordId={order_id}")
            return None

        fill_price = float(filled.get("avgPx", price))
        fill_sz = filled.get("accFillSz", str(sz))

        algo_id = ""

        if not managed_exit:
            # 标准模式：设置 OCO 保护单（止盈+止损）
            oco_side = "buy" if direction == "short" else "sell"
            oco = self.client.place_oco(
                inst_id=symbol,
                tp_price=tp_price,
                sl_price=sl_price,
                sz=fill_sz,
                side=oco_side,
                td_mode=mgn_mode,
            )
            algo_id = oco.get("algoId", "") if oco else ""
        else:
            logger.info(f"📋 managed_exit 模式 | {symbol} | 跳过 OCO，由 PositionMonitor 管理")

        # 记录到数据库
        db = await get_db()
        await db.execute(
            """INSERT INTO trades
               (strategy_id, symbol, direction, entry_price, quantity, leverage, tp_price, sl_price, status, reason)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)""",
            (strategy_id, symbol, direction, fill_price, float(fill_sz), leverage, tp_price, sl_price, signal["reason"]),
        )

        await db.execute(
            """INSERT OR REPLACE INTO positions
               (symbol, strategy_id, direction, entry_price, quantity, leverage, tp_price, sl_price, order_id, algo_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (symbol, strategy_id, direction, fill_price, float(fill_sz), leverage, tp_price, sl_price, order_id, algo_id),
        )
        await db.commit()

        # 广播交易事件
        await ws_manager.broadcast("trade", {
            "strategy_id": strategy_id,
            "symbol": symbol,
            "direction": direction,
            "price": fill_price,
            "quantity": float(fill_sz),
            "tp_price": tp_price,
            "sl_price": sl_price,
            "time": time.strftime("%H:%M:%S"),
        })

        logger.info(
            f"✅ 交易完成 | {symbol} {direction} | "
            f"价格: {fill_price} | 张数: {fill_sz} | "
            f"TP: {tp_price} | SL: {sl_price}"
        )

        return {
            "fill_price": fill_price,
            "fill_sz": float(fill_sz),
            "mgn_mode": mgn_mode,
        }

