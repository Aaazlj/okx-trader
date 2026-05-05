"""
AI 分析器
使用 OpenAI 兼容 API 分析市场指标，输出交易方向和置信度
"""
import json

import httpx

import config
from utils.logger import get_logger

logger = get_logger("AIAnalyzer")

SYSTEM_PROMPT = """你是一个专业的加密货币永续合约交易分析师。
你需要根据提供的技术指标数据，分析当前市场状况，给出交易建议。

你必须严格按以下 JSON 格式输出（不要包含其他内容）：
{
    "direction": "long" | "short" | "idle",
    "confidence": 0-100,
    "reasoning": "简洁的分析理由（一句话）"
}

规则：
- "idle" 表示当前不适合开仓
- confidence 代表对方向判断的置信度（0~100）
- 只在有明确趋势信号时给出 long/short，不确定时给 idle
- reasoning 用中文简洁描述"""


class AIAnalyzer:
    """AI 交易分析器"""

    def __init__(self):
        self.api_key = config.OPENAI_API_KEY
        self.api_url = config.OPENAI_API_URL
        self.model = config.OPENAI_MODEL

    async def analyze(
        self,
        symbol: str,
        indicators: dict,
        strategy_name: str,
        custom_prompt: str = "",
    ) -> dict | None:
        """
        调用 LLM 分析市场指标

        Returns:
            {"direction": "long"|"short"|"idle", "confidence": 0~100, "reasoning": "..."}
        """
        if not self.api_key:
            logger.warning("AI API Key 未配置，跳过 AI 分析")
            return None

        user_prompt = self._build_user_prompt(symbol, indicators, strategy_name, custom_prompt)

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    f"{self.api_url}/chat/completions",
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self.api_key}",
                    },
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": user_prompt},
                        ],
                        "temperature": 0.3,
                        "max_tokens": 200,
                        "response_format": {"type": "json_object"},
                    },
                )

            if response.status_code != 200:
                logger.error(f"AI API 请求失败: HTTP {response.status_code} {response.text[:200]}")
                return None

            result = response.json()
            content = result.get("choices", [{}])[0].get("message", {}).get("content", "{}")

            # 解析 JSON（兼容 markdown 代码块包裹）
            content = self._extract_json(content)
            parsed = json.loads(content)

            direction = parsed.get("direction", "idle")
            if direction not in ("long", "short", "idle"):
                direction = "idle"

            return {
                "direction": direction,
                "confidence": int(parsed.get("confidence", 0)),
                "reasoning": parsed.get("reasoning", ""),
            }
        except json.JSONDecodeError:
            logger.error(f"AI 返回的 JSON 解析失败: {content[:200]}")
            return None
        except Exception as e:
            logger.error(f"AI 分析异常: {e}")
            return None

    async def analyze_with_signal(
        self,
        symbol: str,
        indicators: dict,
        strategy_name: str,
        technical_signal: dict,
        custom_prompt: str = "",
    ) -> dict | None:
        """带技术信号参考的 AI 分析（hybrid 模式用）"""
        if not self.api_key:
            logger.warning("AI API Key 未配置，跳过 AI 分析")
            return None

        user_prompt = self._build_hybrid_prompt(
            symbol, indicators, strategy_name, technical_signal, custom_prompt
        )

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    f"{self.api_url}/chat/completions",
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self.api_key}",
                    },
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": user_prompt},
                        ],
                        "temperature": 0.3,
                        "max_tokens": 200,
                        "response_format": {"type": "json_object"},
                    },
                )

            if response.status_code != 200:
                logger.error(f"AI API 请求失败: HTTP {response.status_code} {response.text[:200]}")
                return None

            result = response.json()
            content = result.get("choices", [{}])[0].get("message", {}).get("content", "{}")
            content = self._extract_json(content)
            parsed = json.loads(content)

            direction = parsed.get("direction", "idle")
            if direction not in ("long", "short", "idle"):
                direction = "idle"

            return {
                "direction": direction,
                "confidence": int(parsed.get("confidence", 0)),
                "reasoning": parsed.get("reasoning", ""),
            }
        except json.JSONDecodeError:
            logger.error(f"AI 返回的 JSON 解析失败: {content[:200]}")
            return None
        except Exception as e:
            logger.error(f"AI 分析异常: {e}")
            return None

    async def generate_perpetual_report(self, analysis: dict) -> str | None:
        """根据永续合约结构化分析生成自然语言报告。"""
        if not self.api_key:
            logger.warning("AI API Key 未配置，跳过永续合约自然语言报告")
            return None

        user_prompt = self._build_perpetual_report_prompt(analysis)

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    f"{self.api_url}/chat/completions",
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self.api_key}",
                    },
                    json={
                        "model": self.model,
                        "messages": [
                            {
                                "role": "system",
                                "content": "你是专业、理性、风控优先的加密货币永续合约量化分析师。",
                            },
                            {"role": "user", "content": user_prompt},
                        ],
                        "temperature": 0.25,
                        "max_tokens": 2600,
                    },
                )

            if response.status_code != 200:
                logger.error(f"AI 报告请求失败: HTTP {response.status_code} {response.text[:200]}")
                return None

            result = response.json()
            return result.get("choices", [{}])[0].get("message", {}).get("content", "").strip() or None
        except Exception as e:
            logger.error(f"AI 报告生成异常: {e}")
            return None

    async def generate_martingale_params(self, request: dict) -> dict | None:
        """生成马丁格尔策略参数 JSON。"""
        if not self.api_key:
            logger.warning("AI API Key 未配置，无法生成马丁格尔参数")
            return None

        prompt = self._build_martingale_params_prompt(request)
        try:
            async with httpx.AsyncClient(timeout=45) as client:
                response = await client.post(
                    f"{self.api_url}/chat/completions",
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self.api_key}",
                    },
                    json={
                        "model": self.model,
                        "messages": [
                            {
                                "role": "system",
                                "content": "你是风控优先的加密货币永续合约量化参数助手，只输出 JSON。",
                            },
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0.2,
                        "max_tokens": 800,
                        "response_format": {"type": "json_object"},
                    },
                )

            if response.status_code != 200:
                logger.error(f"AI 参数请求失败: HTTP {response.status_code} {response.text[:200]}")
                return None

            result = response.json()
            content = result.get("choices", [{}])[0].get("message", {}).get("content", "{}")
            return json.loads(self._extract_json(content))
        except json.JSONDecodeError:
            logger.error("AI 马丁格尔参数 JSON 解析失败")
            return None
        except Exception as e:
            logger.error(f"AI 马丁格尔参数生成异常: {e}")
            return None

    def _build_hybrid_prompt(
        self, symbol: str, indicators: dict, strategy_name: str,
        technical_signal: dict, custom_prompt: str
    ) -> str:
        lines = [
            f"## 交易对: {symbol}",
            f"## 策略: {strategy_name}",
            "",
            "## 当前技术指标:",
        ]

        for key, value in indicators.items():
            lines.append(f"- {key}: {value}")

        lines.append("")
        lines.append("## 技术指标预筛信号:")
        lines.append(f"- 方向: {technical_signal.get('direction', 'unknown')}")
        lines.append(f"- 理由: {technical_signal.get('reason', '')}")

        if custom_prompt:
            lines.append("")
            lines.append("## 策略规则:")
            lines.append(custom_prompt)

        lines.append("")
        lines.append("技术指标已给出方向信号，请结合指标数据和策略规则进行二次确认。")
        lines.append("如果你认为技术指标的判断正确且置信度足够高，保持相同方向。")
        lines.append("如果你认为技术指标判断有误或存在风险，返回 idle 或调整方向。")

        return "\n".join(lines)

    def _build_user_prompt(
        self, symbol: str, indicators: dict, strategy_name: str, custom_prompt: str
    ) -> str:
        lines = [
            f"## 交易对: {symbol}",
            f"## 策略: {strategy_name}",
            "",
            "## 当前技术指标:",
        ]

        for key, value in indicators.items():
            lines.append(f"- {key}: {value}")

        if custom_prompt:
            lines.append("")
            lines.append("## 额外分析要求:")
            lines.append(custom_prompt)

        lines.append("")
        lines.append("请分析以上指标，给出交易建议。")

        return "\n".join(lines)

    def _build_perpetual_report_prompt(self, analysis: dict) -> str:
        symbol = analysis.get("symbol", "")
        summary = analysis.get("summary", {})
        data = {
            "trendAnalysis": analysis.get("trend_analysis"),
            "multiTimeframeAnalysis": analysis.get("multi_timeframe_analysis"),
            "supportResistanceAnalysis": analysis.get("support_resistance"),
            "fundingRateAnalysis": analysis.get("funding_rate_analysis"),
            "openInterestAnalysis": analysis.get("open_interest_analysis"),
            "volumeAnalysis": analysis.get("volume_analysis"),
            "sentimentAnalysis": analysis.get("sentiment_analysis"),
            "orderbookDepthAnalysis": analysis.get("orderbook_depth_analysis"),
            "institutionalBehavior": analysis.get("institutional_behavior"),
            "marketPhase": analysis.get("market_phase"),
            "strategyMatch": analysis.get("strategy_match"),
            "riskRewardAnalysis": analysis.get("risk_reward_analysis"),
            "roleAdvice": analysis.get("role_advice"),
            "conflictAnalysis": analysis.get("conflict_analysis"),
            "tradingPlan": analysis.get("trading_plan"),
            "strategyParameterAdvice": analysis.get("strategy_parameter_advice"),
            "quantRuleBreakdown": analysis.get("quant_rules"),
            "scorePanel": analysis.get("scores"),
            "dataQualityNotes": analysis.get("data_quality_notes"),
        }
        structured_json = json.dumps(data, ensure_ascii=False, default=str)
        return f"""
你是一位专业的加密货币量化分析师，请根据以下结构化分析数据，生成一份完整的永续合约分析报告。

交易对：{symbol}
当前价格：{summary.get("current_price")}
24H 涨跌幅：{summary.get("price_change_24h")}
分析时间：{analysis.get("created_at")}

[综合评分数据]
综合评分：{summary.get("overall_score")}
交易机会等级：{summary.get("opportunity_grade")}
风险等级：{summary.get("risk_level")}

[各模块分析数据]
{structured_json}

请按照以下结构生成报告，语言风格要求：专业、理性、风控优先、逻辑清晰、不夸大、不预测必涨必跌：

【{symbol} 永续合约深度分析报告】
分析时间：{analysis.get("created_at")}

一、综合结论
二、趋势分析
三、多周期共振
四、支撑压力位
五、资金费率分析
六、OI 持仓量分析
七、成交量分析
八、多空情绪分析
九、订单簿深度分析
十、机构行为判断
十一、市场阶段识别
十二、策略匹配
十三、风险收益比
十四、多角色交易建议
十五、信号冲突与注意事项
十六、网格与马丁格尔参数建议
十七、综合评分说明
十八、交易计划草稿
十九、最终操作建议

【风险免责声明】
本分析报告基于公开市场数据和量化模型推演，仅作为市场状态和风险参考，不构成任何形式的投资建议。加密货币市场波动剧烈，过往规律不代表未来表现，请根据自身风险承受能力谨慎决策，自行承担交易风险。

输出要求：
1. 禁止使用“必涨”“必跌”“稳赚”“无风险”“一定”等确定性表达。
2. 所有建议以风险控制为核心，先说风险再说机会。
3. 若某项数据缺失或置信度低，在对应章节明确说明，不强行推断。
4. 报告要有内在逻辑连贯性，各章节结论不可自相矛盾。
5. 每个章节 2-5 句话，重点突出，不堆砌数据。
""".strip()

    def _build_martingale_params_prompt(self, request: dict) -> str:
        return f"""
请为 OKX USDT 永续合约 DCA/马丁格尔策略生成一组简洁、保守参数。

输入：
- symbol: {request.get("symbol")}
- cycle: {request.get("cycle")}
- risk_profile: {request.get("risk_profile")}
- max_position_usdt: {request.get("max_position_usdt")}

只输出 JSON 对象，字段必须包含：
cycle, direction, add_trigger_type, add_trigger_value, take_profit_type, take_profit_value,
max_position_usdt, initial_margin_usdt, add_margin_usdt, max_add_count, fee_rate, slippage_pct, risk。

约束：
- cycle 只能是 "short"、"medium" 或 "long"。
- direction 只能是 "long"、"short" 或 "both"。
- add_trigger_type 和 take_profit_type 只能是 "pct" 或 "usdt"。
- 若使用 pct，add_trigger_value 建议 0.5-8，take_profit_value 建议 0.2-5。
- initial_margin_usdt + add_margin_usdt * max_add_count 不应明显超过 max_position_usdt。
- max_add_count 建议 3-8。
- risk 必须包含 max_concurrent, max_daily_per_symbol, max_daily_loss_pct。
- 不要输出说明文字。
""".strip()

    @staticmethod
    def _extract_json(content: str) -> str:
        """提取 JSON（兼容 markdown ```json``` 包裹）"""
        import re
        match = re.search(r"```json\s*([\s\S]*?)\s*```", content)
        if match:
            return match.group(1)
        match = re.search(r"```\s*([\s\S]*?)\s*```", content)
        if match:
            return match.group(1)
        return content
