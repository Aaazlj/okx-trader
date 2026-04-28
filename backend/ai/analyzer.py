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
