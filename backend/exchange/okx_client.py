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

        try:
            result = self.public.get_instruments(instType="SWAP", instId=inst_id)
        except Exception as e:
            raise ValueError(f"查询品种失败 {inst_id}: {e}") from e
        if result["code"] != "0" or not result["data"]:
            raise ValueError(f"品种不存在: {inst_id}")

        ct_val = float(result["data"][0]["ctVal"])
        self._ct_val_cache[inst_id] = ct_val
        logger.info(f"合约面值: {inst_id} = {ct_val}")
        return ct_val

    def get_max_leverage(self, inst_id: str) -> int:
        """获取交易对支持的最大杠杆。"""
        result = self.public.get_instruments(instType="SWAP", instId=inst_id)
        if result["code"] != "0" or not result["data"]:
            raise ValueError(f"品种不存在: {inst_id}")
        try:
            return max(1, int(float(result["data"][0].get("lever", 100) or 100)))
        except (TypeError, ValueError):
            return 100

    def get_available_symbols(self) -> list[dict]:
        """获取所有可用的永续合约交易对"""
        result = self.public.get_instruments(instType="SWAP")
        if result["code"] != "0":
            logger.error(f"获取交易对列表失败: {result['msg']}")
            return []

        symbols = []
        for item in result["data"]:
            if item.get("instId", "").endswith("-USDT-SWAP"):
                try:
                    max_leverage = int(float(item.get("lever", 100) or 100))
                except (TypeError, ValueError):
                    max_leverage = 100
                symbols.append({
                    "inst_id": item["instId"],
                    "base": item.get("ctValCcy", ""),
                    "ct_val": float(item.get("ctVal", 0)),
                    "max_leverage": max_leverage,
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
        try:
            result = self.account.set_leverage(
                instId=inst_id, lever=str(lever), mgnMode=mgn_mode
            )
        except Exception as e:
            logger.error(f"设置杠杆异常 {inst_id}: {e}")
            return False
        if result["code"] != "0":
            logger.error(f"设置杠杆失败 {inst_id}: code={result['code']} msg={result['msg']}")
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

        try:
            result = self.trade.place_order(**params)
        except Exception as e:
            logger.error(f"下单异常 {inst_id} {side} sz={sz} tdMode={td_mode}: {type(e).__name__}: {e}")
            return None

        if result["code"] != "0":
            logger.error(
                f"下单失败 {inst_id} {side} sz={sz} tdMode={td_mode}: "
                f"code={result['code']} msg={result['msg']}"
            )
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

        try:
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
        except Exception as e:
            logger.error(f"设置止盈止损异常 {inst_id}: {e}")
            return None
        if result.get("code") != "0":
            logger.error(
                f"设置止盈止损失败 {inst_id}: code={result.get('code')} msg={result.get('msg', '')} "
                f"TP={tp_price} SL={sl_price} sz={sz} side={side} tdMode={td_mode}"
            )
            return None

        data = (result.get("data") or [{}])[0]
        if data.get("sCode") not in (None, "0"):
            logger.error(
                f"设置止盈止损失败 {inst_id}: sCode={data.get('sCode')} sMsg={data.get('sMsg', '')} "
                f"TP={tp_price} SL={sl_price} sz={sz} side={side}"
            )
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

    def close_position(self, inst_id: str, td_mode: str = None, pos_side: str = None) -> bool:
        """市价平仓"""
        td_mode = td_mode or config.DEFAULT_MGN_MODE
        params = {"instId": inst_id, "mgnMode": td_mode}
        if pos_side and pos_side != "net":
            params["posSide"] = pos_side
        try:
            result = self.trade.close_positions(**params)
        except Exception as e:
            logger.error(f"平仓异常 {inst_id}: {e}")
            return False
        if result["code"] != "0":
            logger.error(f"平仓失败 {inst_id}: {result['msg']}")
            return False
        logger.info(f"✅ 已市价平仓 {inst_id}{f' {pos_side}' if pos_side else ''}")
        return True

    def close_partial(
        self, inst_id: str, direction: str, sz: str, td_mode: str = None
    ) -> bool:
        """市价部分平仓（减仓指定张数）"""
        td_mode = td_mode or config.DEFAULT_MGN_MODE
        # 平仓方向与持仓方向相反
        side = "buy" if direction == "short" else "sell"
        try:
            result = self.trade.place_order(
                instId=inst_id,
                tdMode=td_mode,
                side=side,
                ordType="market",
                sz=sz,
                reduceOnly=True,
            )
        except Exception as e:
            logger.error(f"部分平仓异常 {inst_id}: {e}")
            return False
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

    def _public_get(self, path: str, params: dict, retries: int = 3) -> list:
        """调用 OKX 公共 REST 接口，内置 429/限频重试。"""
        url = f"https://www.okx.com{path}"
        proxy = config.HTTPS_PROXY or config.HTTP_PROXY or None
        last_error = ""

        for attempt in range(retries):
            try:
                with httpx.Client(proxy=proxy, timeout=10) as client:
                    resp = client.get(url, params=params)

                if resp.status_code == 429:
                    last_error = "HTTP 429"
                    time.sleep(1.2 * (attempt + 1))
                    continue

                resp.raise_for_status()
                result = resp.json()
                if result.get("code") == "0":
                    return result.get("data", [])

                last_error = f"code={result.get('code')} msg={result.get('msg', '')}"
                if result.get("code") == "50011":
                    time.sleep(1.2 * (attempt + 1))
                    continue
                break
            except Exception as e:
                last_error = str(e)
                time.sleep(0.4 * (attempt + 1))

        logger.warning(f"OKX 公共接口请求失败 {path}: {last_error}")
        return []

    def get_ticker(self, inst_id: str) -> dict | None:
        """获取单个交易对 ticker。"""
        data = self._public_get("/api/v5/market/ticker", {"instId": inst_id})
        if not data:
            return None
        ticker = data[0]
        last = self._safe_float(ticker.get("last"))
        open_24h = self._safe_float(ticker.get("open24h"))
        chg_pct = ((last - open_24h) / open_24h * 100) if last is not None and open_24h else 0
        return {
            "inst_id": ticker.get("instId", inst_id),
            "last": last,
            "open24h": open_24h,
            "high24h": self._safe_float(ticker.get("high24h")),
            "low24h": self._safe_float(ticker.get("low24h")),
            "chg_pct": round(chg_pct, 4),
            "vol24h": self._safe_float(ticker.get("vol24h")),
            "vol_ccy_24h": self._safe_float(ticker.get("volCcy24h")),
            "bid_px": self._safe_float(ticker.get("bidPx")),
            "ask_px": self._safe_float(ticker.get("askPx")),
            "ts": int(ticker.get("ts", 0) or 0),
        }

    def get_funding_rate(self, inst_id: str) -> dict | None:
        """获取当前资金费率。"""
        data = self._public_get("/api/v5/public/funding-rate", {"instId": inst_id})
        if not data:
            return None
        item = data[0]
        return {
            "funding_rate": self._safe_float(item.get("fundingRate")),
            "next_funding_rate": self._safe_float(item.get("nextFundingRate"), None),
            "sett_funding_rate": self._safe_float(item.get("settFundingRate"), None),
            "funding_time": int(item.get("fundingTime", 0) or 0),
            "next_funding_time": int(item.get("nextFundingTime", 0) or 0),
            "ts": int(item.get("ts", 0) or 0),
        }

    def get_funding_rate_history(self, inst_id: str, limit: int = 30) -> list[dict]:
        """获取历史资金费率。"""
        data = self._public_get(
            "/api/v5/public/funding-rate-history",
            {"instId": inst_id, "limit": str(limit)},
        )
        return [
            {
                "funding_rate": self._safe_float(item.get("fundingRate")),
                "realized_rate": self._safe_float(item.get("realizedRate")),
                "funding_time": int(item.get("fundingTime", 0) or 0),
            }
            for item in data
        ]

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

    def get_orderbook_depth(self, inst_id: str, sz: str = "20") -> dict:
        """获取订单簿前 N 档深度。"""
        data = self._public_get("/api/v5/market/books", {"instId": inst_id, "sz": sz})
        if not data:
            return {"asks": [], "bids": []}
        item = data[0]
        return {"asks": item.get("asks", []), "bids": item.get("bids", []), "ts": int(item.get("ts", 0) or 0)}

    def get_recent_trades(self, inst_id: str, limit: int = 100) -> list[dict]:
        """获取最近成交明细。"""
        data = self._public_get("/api/v5/market/trades", {"instId": inst_id, "limit": str(limit)})
        return [
            {
                "side": item.get("side", ""),
                "size": self._safe_float(item.get("sz")),
                "price": self._safe_float(item.get("px")),
                "ts": int(item.get("ts", 0) or 0),
            }
            for item in data
        ]

    def get_long_short_account_ratio(self, ccy: str, period: str = "1H") -> list[dict]:
        """获取多空账户比历史。数据格式: [ts, ratio]。"""
        data = self._public_get(
            "/api/v5/rubik/stat/contracts/long-short-account-ratio",
            {"ccy": ccy, "period": period},
        )
        history = []
        for item in data:
            if len(item) < 2:
                continue
            history.append({"ts": int(item[0]), "ratio": self._safe_float(item[1])})
        return history

    def get_long_short_position_ratio(self, inst_id: str, period: str = "1H") -> list[dict]:
        """获取精英交易员多空持仓比历史。数据格式: [ts, ratio]。"""
        data = self._public_get(
            "/api/v5/rubik/stat/contracts/long-short-position-ratio-contract-top-trader",
            {"instId": inst_id, "period": period},
        )
        history = []
        for item in data:
            if len(item) < 2:
                continue
            history.append({"ts": int(item[0]), "ratio": self._safe_float(item[1])})
        return history

    def get_open_interest_history(self, inst_id: str, period: str = "1H") -> list[dict]:
        """获取合约持仓量历史。数据格式: [ts, oi, oiCcy, oiUsd]。"""
        data = self._public_get(
            "/api/v5/rubik/stat/contracts/open-interest-history",
            {"instId": inst_id, "period": period},
        )
        history = []
        for item in data:
            if len(item) < 4:
                continue
            history.append({
                "ts": int(item[0]),
                "oi": self._safe_float(item[1]),
                "oi_ccy": self._safe_float(item[2]),
                "oi_usd": self._safe_float(item[3]),
            })
        return history

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

