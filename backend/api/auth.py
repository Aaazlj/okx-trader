"""
面板登录认证接口
"""
import hashlib
import hmac
import time
from collections.abc import Mapping

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

import config

router = APIRouter(prefix="/api/auth", tags=["auth"])

COOKIE_NAME = "okx_trader_auth"
COOKIE_MAX_AGE = 7 * 24 * 60 * 60
TOKEN_MESSAGE = b"okx-trader-panel"


class LoginRequest(BaseModel):
    password: str


def _admin_password() -> str:
    return config.ADMIN_PASSWORD.strip()


def is_auth_enabled() -> bool:
    return bool(_admin_password())


def _now() -> int:
    return int(time.time())


def _sign(expires_at: int) -> str:
    return hmac.new(
        _admin_password().encode("utf-8"),
        str(expires_at).encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


def _session_token() -> str:
    expires_at = _now() + COOKIE_MAX_AGE
    return f"{expires_at}.{_sign(expires_at)}"


def session_expires_at(cookies: Mapping[str, str]) -> int | None:
    if not is_auth_enabled():
        return None
    try:
        expires_at_text, signature = cookies.get(COOKIE_NAME, "").split(".", 1)
        expires_at = int(expires_at_text)
        signature_bytes = signature.encode("ascii")
    except (ValueError, UnicodeEncodeError):
        return None
    if expires_at <= _now():
        return None
    if not hmac.compare_digest(signature_bytes, _sign(expires_at).encode("ascii")):
        return None
    return expires_at


def is_cookie_authenticated(cookies: Mapping[str, str]) -> bool:
    if not is_auth_enabled():
        return True
    return session_expires_at(cookies) is not None


def is_request_authenticated(request: Request) -> bool:
    return is_cookie_authenticated(request.cookies)


@router.get("/status")
async def auth_status(request: Request):
    return {"enabled": is_auth_enabled(), "authenticated": is_request_authenticated(request)}


@router.post("/login")
async def login(data: LoginRequest, response: Response):
    if not is_auth_enabled():
        return {"authenticated": True}
    if not hmac.compare_digest(
        data.password.encode("utf-8"),
        _admin_password().encode("utf-8"),
    ):
        raise HTTPException(status_code=401, detail="密码错误")
    response.set_cookie(
        COOKIE_NAME,
        _session_token(),
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    return {"authenticated": True}


class PanelAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if _should_skip_auth(request):
            return await call_next(request)
        if is_request_authenticated(request):
            return await call_next(request)
        return JSONResponse(status_code=401, content={"detail": "未登录"})


def _should_skip_auth(request: Request) -> bool:
    path = request.url.path
    return (
        not is_auth_enabled()
        or request.method == "OPTIONS"
        or not path.startswith("/api")
        or path.startswith("/api/auth")
        or path == "/api/health"
    )
