"""
OKX 交易所客户端封装
基于 python-okx SDK，支持多交易对
"""
import time
from datetime import timedelta, timezone

import httpx
import pandas as pd
from okx import MarketData, PublicData, Account, Trade

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

        # 行情数据永远用实盘 flag="0"（模拟盘端点不稳定）
        market_kwargs = {"flag": "0", "debug": False}
        if proxy:
            market_kwargs["proxy"] = proxy
        self.market = MarketData.MarketAPI(**market_kwargs)
        # 公共数据（品种信息等）也用实盘，无需凭证
        public_kwargs = {"flag": "0", "debug": False}
        if proxy:
            public_kwargs["proxy"] = proxy
        self.public = PublicData.PublicAPI(**public_kwargs)
        self.account = Account.AccountAPI(**kwargs)
        self.trade = Trade.TradeAPI(**kwargs)

        # 合约面值缓存: inst_id -> ct_val
        self._ct_val_cache: dict[str, float] = {}

        logger.info(f"OKX 客户端初始化完成 | 模式: {'模拟盘' if config.OKX_DEMO else '实盘'}")

    # ═══════════════════════════════════════════
    # 合约信息
    # ═══════════════════════════════════════════

    def get_contract_value(self, inst_id: str) -> float:
        """获取合约面值（带缓存），品种不存在时抛异常"""
        if inst_id in self._ct_val_cache:
            return self._ct_val_cache[inst_id]

        result = self.public.get_instruments(instType="SWAP", instId=inst_id)
        if result["code"] != "0" or not result["data"]:
            raise ValueError(f"品种不存在: {inst_id}")

        ct_val = float(result["data"][0]["ctVal"])
        self._ct_val_cache[inst_id] = ct_val
        logger.info(f"合约面值: {inst_id} = {ct_val}")
        return ct_val

    def get_available_symbols(self) -> list[dict]:
        """获取所有可用的永续合约交易对"""
        result = self.public.get_instruments(instType="SWAP")
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

    @staticmethod
    def _normalize_bar(bar: str) -> str:
        """修正 bar 参数格式（OKX: m 小写, H/D/W/M 大写）"""
        if not bar or len(bar) < 2:
            return bar
        suffix = bar[-1]
        # h/d/w 需要大写；m 是分钟（小写），M 是月份（大写）— 不动
        if suffix in ('h', 'd', 'w'):
            return bar[:-1] + suffix.upper()
        return bar

    def get_candles(
        self, inst_id: str, bar: str = "1m", limit: int = None
    ) -> pd.DataFrame:
        """获取最新 K 线数据"""
        limit = limit or config.CANDLE_FETCH_LIMIT
        original_bar = bar
        bar = self._normalize_bar(bar)
        if original_bar != bar:
            logger.info(f"bar 参数已修正: {original_bar} -> {bar}")

        result = self.market.get_candlesticks(
            instId=inst_id, bar=bar, limit=str(limit)
        )
        if result["code"] != "0":
            logger.error(f"获取K线失败 {inst_id} (bar={bar}): {result['msg']}")
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
        bar = self._normalize_bar(bar)
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
            # 顶层 upl 有时为空，从 details 中累加更可靠
            upl = self._safe_float(data.get("upl"))
            if upl == 0:
                upl = sum(
                    self._safe_float(d.get("upl"))
                    for d in data.get("details", [])
                )
            return {
                "total_equity": self._safe_float(data.get("totalEq")),
                "available_balance": self._safe_float(
                    next(
                        (d["availBal"] for d in data.get("details", []) if d["ccy"] == "USDT"),
                        0,
                    )
                ),
                "unrealized_pnl": upl,
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

    @staticmethod
    def _format_price(price: float) -> str:
        """格式化价格，保留足够精度"""
        if price >= 100:
            return str(round(price, 2))
        elif price >= 1:
            return str(round(price, 4))
        elif price >= 0.01:
            return str(round(price, 6))
        else:
            return str(round(price, 8))

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
            tpTriggerPx=self._format_price(tp_price),
            tpOrdPx="-1",
            slTriggerPx=self._format_price(sl_price),
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
            # 51001 = 品种不存在，查询特定 symbol 时常见，不打 error
            if result["code"] == "51001" and inst_id:
                return []
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

    def close_partial(
        self, inst_id: str, direction: str, sz: str, td_mode: str = None
    ) -> bool:
        """市价部分平仓（减仓指定张数）"""
        td_mode = td_mode or config.DEFAULT_MGN_MODE
        # 平仓方向与持仓方向相反
        side = "buy" if direction == "short" else "sell"
        result = self.trade.place_order(
            instId=inst_id,
            tdMode=td_mode,
            side=side,
            ordType="market",
            sz=sz,
            reduceOnly=True,
        )
        if result.get("code") != "0":
            logger.error(f"部分平仓失败 {inst_id}: {result.get('msg', '')}")
            return False
        logger.info(f"✅ 部分平仓 | {inst_id} {side} | 张数: {sz}")
        return True

    def calc_contract_size(
        self, inst_id: str, usdt_amount: float, price: float, leverage: int
    ) -> int:
        """计算合约张数"""
        ct_val = self.get_contract_value(inst_id)
        sz = int((usdt_amount * leverage) / (price * ct_val))
        return max(sz, 1)

    def get_fills(self, inst_id: str = None, inst_type: str = "SWAP") -> list:
        """获取成交明细（近3天），用于同步平仓价格和手续费"""
        kwargs = {"instType": inst_type}
        if inst_id:
            kwargs["instId"] = inst_id
        result = self.trade.get_fills(**kwargs)
        if result.get("code") != "0":
            logger.warning(f"获取成交明细失败: {result.get('msg', '')}")
            return []
        return result.get("data", [])

    def get_positions_history(self, inst_id: str = None, inst_type: str = "SWAP") -> list:
        """获取历史持仓（含 realizedPnl、fee、pnl），比 fills 更准确"""
        kwargs = {"instType": inst_type}
        if inst_id:
            kwargs["instId"] = inst_id
        result = self.account.get_positions_history(**kwargs)
        if result.get("code") != "0":
            logger.warning(f"获取历史持仓失败: {result.get('msg', '')}")
            return []
        return result.get("data", [])

    # ═══════════════════════════════════════════
    # 行情数据（扩展）
    # ═══════════════════════════════════════════

    def get_tickers(self) -> list[dict]:
        """获取所有 SWAP ticker（含涨跌幅、24h 成交额）"""
        result = self.market.get_tickers(instType="SWAP")
        if result.get("code") != "0":
            logger.error(f"获取 tickers 失败: {result.get('msg', '')}")
            return []
        tickers = []
        for t in result.get("data", []):
            inst_id = t.get("instId", "")
            if not inst_id.endswith("-USDT-SWAP"):
                continue
            last = self._safe_float(t.get("last"))
            open_24h = self._safe_float(t.get("open24h"))
            chg_pct = ((last - open_24h) / open_24h * 100) if open_24h > 0 else 0
            tickers.append({
                "inst_id": inst_id,
                "last": last,
                "chg_pct": round(chg_pct, 4),
                "vol_ccy_24h": self._safe_float(t.get("volCcy24h")),
                "bid_px": self._safe_float(t.get("bidPx")),
                "ask_px": self._safe_float(t.get("askPx")),
            })
        return tickers

    def get_orderbook(self, inst_id: str, sz: str = "1") -> dict:
        """获取盘口数据（用于计算买卖点差）"""
        result = self.market.get_orderbook(instId=inst_id, sz=sz)
        if result.get("code") != "0":
            logger.error(f"获取盘口失败 {inst_id}: {result.get('msg', '')}")
            return {}
        data = result.get("data", [{}])[0]
        asks = data.get("asks", [])
        bids = data.get("bids", [])
        return {
            "ask": float(asks[0][0]) if asks else 0,
            "bid": float(bids[0][0]) if bids else 0,
        }

    def get_open_interest(self, inst_id: str) -> dict | None:
        """获取合约持仓量（Open Interest）

        调用 OKX Rubik Stat 接口，返回最新 OI 数据。
        数据格式: [ts, oi, oiCcy, oiUsd]
        """
        url = "https://www.okx.com/api/v5/rubik/stat/contracts/open-interest-history"
        params = {"instId": inst_id}

        try:
            proxy = config.HTTPS_PROXY or config.HTTP_PROXY or None
            with httpx.Client(proxy=proxy, timeout=10) as client:
                resp = client.get(url, params=params)
                resp.raise_for_status()
                result = resp.json()

            if result.get("code") != "0":
                logger.warning(f"获取OI失败 {inst_id}: {result.get('msg', '')}")
                return None

            data = result.get("data", [])
            if not data:
                logger.warning(f"OI数据为空 {inst_id}")
                return None

            latest = data[0]
            return {
                "oi": float(latest[1]),
                "oiCcy": float(latest[2]),
                "ts": int(latest[0]),
            }
        except Exception as e:
            logger.warning(f"获取OI异常 {inst_id}: {e}")
            return None

