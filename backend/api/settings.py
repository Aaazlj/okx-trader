"""
系统配置 API — 读写 .env 文件，测试连通性
"""
import os
import httpx
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import config

router = APIRouter(prefix="/api/settings", tags=["settings"])

# 兼容 Docker 容器（代码在 /app/）和本地开发
_base = Path(__file__).parent.parent
ENV_PATH = _base / ".env" if (_base / ".env").exists() else _base.parent / ".env"


# ═══════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════

class SettingsResponse(BaseModel):
    okx_api_key: str
    okx_secret_key: str
    okx_passphrase: str
    okx_demo: bool
    http_proxy: str
    https_proxy: str
    openai_api_key: str
    openai_api_url: str
    openai_model: str
    telegram_bot_token: str
    telegram_chat_id: str


class SettingsUpdate(BaseModel):
    okx_api_key: str | None = None
    okx_secret_key: str | None = None
    okx_passphrase: str | None = None
    okx_demo: bool | None = None
    http_proxy: str | None = None
    https_proxy: str | None = None
    openai_api_key: str | None = None
    openai_api_url: str | None = None
    openai_model: str | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None


class TestResult(BaseModel):
    success: bool
    message: str


# ═══════════════════════════════════════════
# .env 文件读写
# ═══════════════════════════════════════════

def _read_env() -> dict[str, str]:
    """读取 .env 文件为字典"""
    env = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip()
    return env


def _write_env(env: dict[str, str]):
    """将字典写回 .env 文件，保留注释和格式"""
    lines = []
    existing_keys = set()

    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                lines.append(line)
                continue
            if "=" in stripped:
                key, _, _ = stripped.partition("=")
                key = key.strip()
                existing_keys.add(key)
                if key in env:
                    lines.append(f"{key}={env[key]}")
                else:
                    lines.append(line)
            else:
                lines.append(line)

    # 追加新增的 key
    new_keys = set(env.keys()) - existing_keys
    if new_keys:
        lines.append("")
        lines.append("# ═══════════════════════════════════════════")
        lines.append("# 新增配置")
        lines.append("# ═══════════════════════════════════════════")
        for key in sorted(new_keys):
            lines.append(f"{key}={env[key]}")

    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ═══════════════════════════════════════════
# API 端点
# ═══════════════════════════════════════════

@router.get("", response_model=SettingsResponse)
async def get_settings():
    """读取当前配置"""
    env = _read_env()
    return SettingsResponse(
        okx_api_key=env.get("OKX_API_KEY", ""),
        okx_secret_key=env.get("OKX_SECRET_KEY", ""),
        okx_passphrase=env.get("OKX_PASSPHRASE", ""),
        okx_demo=env.get("OKX_DEMO", "true").lower() == "true",
        http_proxy=env.get("HTTP_PROXY", ""),
        https_proxy=env.get("HTTPS_PROXY", ""),
        openai_api_key=env.get("OPENAI_API_KEY", ""),
        openai_api_url=env.get("OPENAI_API_URL", "https://api.openai.com/v1"),
        openai_model=env.get("OPENAI_MODEL", "gpt-4o-mini"),
        telegram_bot_token=env.get("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=env.get("TELEGRAM_CHAT_ID", ""),
    )


@router.put("", response_model=TestResult)
async def update_settings(data: SettingsUpdate):
    """保存配置到 .env 文件并实时生效"""
    env = _read_env()

    field_map = {
        "okx_api_key": "OKX_API_KEY",
        "okx_secret_key": "OKX_SECRET_KEY",
        "okx_passphrase": "OKX_PASSPHRASE",
        "okx_demo": "OKX_DEMO",
        "http_proxy": "HTTP_PROXY",
        "https_proxy": "HTTPS_PROXY",
        "openai_api_key": "OPENAI_API_KEY",
        "openai_api_url": "OPENAI_API_URL",
        "openai_model": "OPENAI_MODEL",
        "telegram_bot_token": "TELEGRAM_BOT_TOKEN",
        "telegram_chat_id": "TELEGRAM_CHAT_ID",
    }

    for field, env_key in field_map.items():
        value = getattr(data, field, None)
        if value is not None:
            env[env_key] = str(value).lower() if isinstance(value, bool) else str(value)

    _write_env(env)

    # 同步更新 config 模块（实时生效）
    config.OKX_API_KEY = env.get("OKX_API_KEY", "")
    config.OKX_SECRET_KEY = env.get("OKX_SECRET_KEY", "")
    config.OKX_PASSPHRASE = env.get("OKX_PASSPHRASE", "")
    config.OKX_DEMO = env.get("OKX_DEMO", "true").lower() == "true"
    config.HTTP_PROXY = env.get("HTTP_PROXY", "")
    config.HTTPS_PROXY = env.get("HTTPS_PROXY", "")
    config.OPENAI_API_KEY = env.get("OPENAI_API_KEY", "")
    config.OPENAI_API_URL = env.get("OPENAI_API_URL", "https://api.openai.com/v1")
    config.OPENAI_MODEL = env.get("OPENAI_MODEL", "gpt-4o-mini")
    config.TELEGRAM_BOT_TOKEN = env.get("TELEGRAM_BOT_TOKEN", "")
    config.TELEGRAM_CHAT_ID = env.get("TELEGRAM_CHAT_ID", "")

    # 同步更新环境变量
    for env_key, value in env.items():
        os.environ[env_key] = value

    return TestResult(success=True, message="配置已保存并生效")


@router.post("/test-ai", response_model=TestResult)
async def test_ai_connection(data: SettingsUpdate):
    """测试 AI 服务连通性"""
    api_key = data.openai_api_key or ""
    api_url = data.openai_api_url or "https://api.openai.com/v1"
    model = data.openai_model or "gpt-4o-mini"

    if not api_key:
        return TestResult(success=False, message="请填写 API Key")

    url = f"{api_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 5,
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code == 200:
                return TestResult(success=True, message=f"连接成功 ({model})")
            else:
                body = resp.text[:200]
                return TestResult(success=False, message=f"HTTP {resp.status_code}: {body}")
    except httpx.ConnectError:
        return TestResult(success=False, message="无法连接到服务器，请检查 URL")
    except httpx.TimeoutException:
        return TestResult(success=False, message="连接超时 (15s)")
    except Exception as e:
        return TestResult(success=False, message=f"错误: {type(e).__name__}: {e}")


@router.post("/test-okx", response_model=TestResult)
async def test_okx_connection(data: SettingsUpdate):
    """测试 OKX API 连通性"""
    api_key = data.okx_api_key or ""
    secret = data.okx_secret_key or ""
    passphrase = data.okx_passphrase or ""
    demo = data.okx_demo if data.okx_demo is not None else True

    if not all([api_key, secret, passphrase]):
        return TestResult(success=False, message="请填写完整的 OKX API 凭证")

    import hmac
    import hashlib
    import base64
    from datetime import datetime, timezone

    # 构造签名
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    method = "GET"
    path = "/api/v5/account/balance"
    message = f"{timestamp}{method}{path}"
    signature = base64.b64encode(
        hmac.new(secret.encode(), message.encode(), hashlib.sha256).digest()
    ).decode()

    base_url = "https://www.okx.com" if not demo else "https://www.okx.com"
    headers = {
        "OK-ACCESS-KEY": api_key,
        "OK-ACCESS-SIGN": signature,
        "OK-ACCESS-TIMESTAMP": timestamp,
        "OK-ACCESS-PASSPHRASE": passphrase,
        "x-simulated-trading": "1" if demo else "0",
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{base_url}{path}", headers=headers)
            body = resp.json()
            if body.get("code") == "0":
                mode = "模拟盘" if demo else "实盘"
                return TestResult(success=True, message=f"连接成功 ({mode})")
            else:
                msg = body.get("msg", str(body))
                return TestResult(success=False, message=f"API 错误: {msg}")
    except httpx.ConnectError:
        return TestResult(success=False, message="无法连接到 OKX，请检查网络或代理")
    except httpx.TimeoutException:
        return TestResult(success=False, message="连接超时")
    except Exception as e:
        return TestResult(success=False, message=f"错误: {type(e).__name__}: {e}")


@router.post("/test-telegram", response_model=TestResult)
async def test_telegram_connection(data: SettingsUpdate):
    """测试 Telegram Bot 连通性"""
    token = data.telegram_bot_token or ""
    chat_id = data.telegram_chat_id or ""

    if not token:
        return TestResult(success=False, message="请填写 Bot Token")
    if not chat_id:
        return TestResult(success=False, message="请填写 Chat ID")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": "✅ OKX Trader 连通性测试成功",
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload)
            body = resp.json()
            if body.get("ok"):
                return TestResult(success=True, message="消息发送成功，请检查 Telegram")
            else:
                desc = body.get("description", str(body))
                return TestResult(success=False, message=f"API 错误: {desc}")
    except httpx.ConnectError:
        return TestResult(success=False, message="无法连接到 Telegram API")
    except httpx.TimeoutException:
        return TestResult(success=False, message="连接超时")
    except Exception as e:
        return TestResult(success=False, message=f"错误: {type(e).__name__}: {e}")
