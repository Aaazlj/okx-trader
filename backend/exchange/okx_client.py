"""
OKX 交易所客户端封装
基于 python-okx SDK，支持多交易对
"""
import time
from datetime import timedelta, timezone

import pandas as pd
from okx import MarketData, Account, Trade

import config
from utils.logger import get_logger

logger = get_logger("OKXClient")

BEIJING_TZ = timezone(timedelta(hours=8))


class OKXClient:
    """OKX 交易所 API 客户端，支持多交易对"""

    def __init__(self):
        flag = "1" if config.OKX_DEMO else "0"
        proxy = config.HTTPS_PROXY or config.HTTP_PROXY or None

        kwargs = dict(
            api_key=config.OKX_API_KEY,
            api_secret_key=config.OKX_SECRET_KEY,
            passphrase=config.OKX_PASSPHRASE,
            flag=flag,
            debug=False,
        )
        if proxy:
            kwargs["proxy"] = proxy

        market_kwargs = {"flag": flag, "debug": False}
        if proxy:
            market_kwargs["proxy"] = proxy
        self.market = MarketData.MarketAPI(**market_kwargs)
        self.account = Account.AccountAPI(**kwargs)
        self.trade = Trade.TradeAPI(**kwargs)

        # 合约面值缓存: inst_id -> ct_val
        self._ct_val_cache: dict[str, float] = {}

        logger.info(f"OKX 客户端初始化完成 | 模式: {'模拟盘' if config.OKX_DEMO else '实盘'}")

    # ═══════════════════════════════════════════
    # 合约信息
    # ═══════════════════════════════════════════

    def get_contract_value(self, inst_id: str) -> float:
        """获取合约面值（带缓存）"""
        if inst_id in self._ct_val_cache:
            return self._ct_val_cache[inst_id]

        result = self.account.get_instruments(instType="SWAP", instId=inst_id)
        if result["code"] != "0" or not result["data"]:
            logger.warning(f"获取合约信息失败: {inst_id}, 使用默认面值 0.1")
            return 0.1

        ct_val = float(result["data"][0]["ctVal"])
        self._ct_val_cache[inst_id] = ct_val
        logger.info(f"合约面值: {inst_id} = {ct_val}")
        return ct_val

    def get_available_symbols(self) -> list[dict]:
        """获取所有可用的永续合约交易对"""
        result = self.account.get_instruments(instType="SWAP")
        if result["code"] != "0":
            logger.error(f"获取交易对列表失败: {result['msg']}")
            return []

        symbols = []
        for item in result["data"]:
            if item.get("instId", "").endswith("-USDT-SWAP"):
                symbols.append({
                    "inst_id": item["instId"],
                    "base": item.get("ctValCcy", ""),
                    "ct_val": float(item.get("ctVal", 0)),
                    "min_sz": item.get("minSz", "1"),
                    "state": item.get("state", ""),
                })
        return symbols

    # ═══════════════════════════════════════════
    # 行情数据
    # ═══════════════════════════════════════════

    def get_candles(
        self, inst_id: str, bar: str = "1m", limit: int = None
    ) -> pd.DataFrame:
        """获取最新 K 线数据"""
        limit = limit or config.CANDLE_FETCH_LIMIT

        result = self.market.get_candlesticks(
            instId=inst_id, bar=bar, limit=str(limit)
        )
        if result["code"] != "0":
            logger.error(f"获取K线失败 {inst_id}: {result['msg']}")
            return pd.DataFrame()

        df = pd.DataFrame(
            result["data"],
            columns=[
                "ts", "open", "high", "low", "close",
                "vol", "volCcy", "volCcyQuote", "confirm",
            ],
        )
        for col in ["open", "high", "low", "close", "vol", "volCcy", "volCcyQuote"]:
            df[col] = df[col].astype(float)
        df["ts"] = pd.to_datetime(
            df["ts"].astype(int), unit="ms", utc=True
        ).dt.tz_convert("Asia/Shanghai")
        df["confirm"] = df["confirm"].astype(int)
        df = df.sort_values("ts").reset_index(drop=True)
        return df

    def get_history_candles(
        self,
        inst_id: str,
        bar: str = "1m",
        after: str = None,
        before: str = None,
        limit: int = 100,
    ) -> list:
        """获取历史 K 线数据（单次请求）"""
        params = {"instId": inst_id, "bar": bar, "limit": str(limit)}
        if after:
            params["after"] = after
        if before:
            params["before"] = before

        result = self.market.get_history_candlesticks(**params)
        if result["code"] != "0":
            logger.error(f"获取历史K线失败 {inst_id}: {result['msg']}")
            return []
        return result["data"]

    # ═══════════════════════════════════════════
    # 账户操作
    # ═══════════════════════════════════════════

    def get_balance(self, ccy: str = "USDT") -> float:
        """获取指定币种余额"""
        result = self.account.get_account_balance(ccy=ccy)
        if result["code"] != "0":
            logger.error(f"获取余额失败: {result['msg']}")
            return 0.0
        try:
            details = result["data"][0]["details"]
            for d in details:
                if d["ccy"] == ccy:
                    return float(d["availBal"])
        except (IndexError, KeyError):
            pass
        return 0.0

    @staticmethod
    def _safe_float(val, default: float = 0.0) -> float:
        """安全转换为 float（OKX API 常返回空字符串）"""
        if val is None or val == "":
            return default
        try:
            return float(val)
        except (ValueError, TypeError):
            return default

    def get_account_info(self) -> dict:
        """获取账户完整信息"""
        result = self.account.get_account_balance()
        if result["code"] != "0":
            logger.error(f"获取账户信息失败: {result['msg']}")
            return {}
        try:
            data = result["data"][0]
            return {
                "total_equity": self._safe_float(data.get("totalEq")),
                "available_balance": self._safe_float(
                    next(
                        (d["availBal"] for d in data.get("details", []) if d["ccy"] == "USDT"),
                        0,
                    )
                ),
                "unrealized_pnl": self._safe_float(data.get("upl")),
            }
        except (IndexError, KeyError):
            return {}

    def set_leverage(
        self, inst_id: str, lever: int, mgn_mode: str = "cross"
    ) -> bool:
        """设置杠杆倍数"""
        result = self.account.set_leverage(
            instId=inst_id, lever=str(lever), mgnMode=mgn_mode
        )
        if result["code"] != "0":
            logger.error(f"设置杠杆失败 {inst_id}: {result['msg']}")
            return False
        logger.info(f"杠杆已设置: {inst_id} {lever}x ({mgn_mode})")
        return True

    # ═══════════════════════════════════════════
    # 交易操作
    # ═══════════════════════════════════════════

    def place_market_order(
        self, inst_id: str, side: str, sz: str, td_mode: str = None
    ) -> dict | None:
        """市价下单 (side: 'buy' 或 'sell')"""
        td_mode = td_mode or config.DEFAULT_MGN_MODE
        params = {
            "instId": inst_id,
            "tdMode": td_mode,
            "side": side,
            "ordType": "market",
            "sz": sz,
        }

        result = self.trade.place_order(**params)
        if result["code"] != "0":
            logger.error(f"下单失败 {inst_id} {side}: {result['msg']}")
            return None

        order_id = result["data"][0]["ordId"]
        logger.info(f"✅ 下单成功 | {inst_id} {side} | 订单ID: {order_id} | 张数: {sz}")
        return result["data"][0]

    def wait_order_filled(
        self, ord_id: str, inst_id: str, timeout_sec: int = 8, poll_interval: float = 0.5
    ) -> dict | None:
        """等待订单成交"""
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            result = self.trade.get_order(instId=inst_id, ordId=ord_id)
            if result.get("code") != "0":
                time.sleep(poll_interval)
                continue

            data = result.get("data") or []
            if not data:
                time.sleep(poll_interval)
                continue

            order = data[0]
            state = order.get("state", "")
            acc_fill_sz = float(order.get("accFillSz", "0") or 0)

            if state == "filled" or acc_fill_sz > 0:
                fill_px = float(order.get("avgPx", "0") or 0)
                logger.info(
                    f"✅ 订单已成交 | ordId: {ord_id} | 成交张数: {acc_fill_sz} | 均价: {fill_px}"
                )
                return order

            if state in {"canceled", "mmp_canceled"}:
                logger.error(f"订单已取消 | ordId: {ord_id}")
                return None

            time.sleep(poll_interval)

        logger.error(f"等待订单成交超时 | ordId: {ord_id}")
        return None

    def place_oco(
        self,
        inst_id: str,
        tp_price: float,
        sl_price: float,
        sz: str,
        side: str,
        td_mode: str = None,
    ) -> dict | None:
        """设置 OCO 保护单（止盈+止损）"""
        td_mode = td_mode or config.DEFAULT_MGN_MODE

        result = self.trade.place_algo_order(
            instId=inst_id,
            tdMode=td_mode,
            side=side,
            ordType="oco",
            sz=sz,
            reduceOnly="true",
            tpTriggerPx=str(round(tp_price, 2)),
            tpOrdPx="-1",
            slTriggerPx=str(round(sl_price, 2)),
            slOrdPx="-1",
        )
        if result.get("code") != "0":
            logger.error(f"设置止盈止损失败 {inst_id}: {result.get('msg', '')}")
            return None

        data = (result.get("data") or [{}])[0]
        if data.get("sCode") not in (None, "0"):
            logger.error(f"设置止盈止损失败: {data.get('sMsg', '')}")
            return None

        algo_id = data.get("algoId", "unknown")
        logger.info(f"✅ 止盈止损已设置 | {inst_id} | TP: {tp_price} | SL: {sl_price} | AlgoID: {algo_id}")
        return data

    def get_positions(self, inst_id: str = None) -> list:
        """获取当前持仓"""
        kwargs = {}
        if inst_id:
            kwargs["instId"] = inst_id
        result = self.account.get_positions(**kwargs)
        if result["code"] != "0":
            logger.error(f"获取持仓失败: {result['msg']}")
            return []
        return [p for p in result["data"] if float(p.get("pos", "0")) != 0]

    def close_position(self, inst_id: str, td_mode: str = None) -> bool:
        """市价平仓"""
        td_mode = td_mode or config.DEFAULT_MGN_MODE
        result = self.trade.close_positions(instId=inst_id, mgnMode=td_mode)
        if result["code"] != "0":
            logger.error(f"平仓失败 {inst_id}: {result['msg']}")
            return False
        logger.info(f"✅ 已市价平仓 {inst_id}")
        return True

    def calc_contract_size(
        self, inst_id: str, usdt_amount: float, price: float, leverage: int
    ) -> int:
        """计算合约张数"""
        ct_val = self.get_contract_value(inst_id)
        sz = int((usdt_amount * leverage) / (price * ct_val))
        return max(sz, 1)
