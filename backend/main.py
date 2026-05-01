"""
OKX 自动交易系统 — FastAPI 入口
"""
import asyncio
import traceback
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

import config
from utils.logger import get_logger
from exchange.okx_client import OKXClient
from db.database import get_db, close_db
from ws import ws_manager

from api import account, positions, strategies, market, settings, auth

logger = get_logger("main")

# 全局 OKX 客户端
okx_client: OKXClient | None = None
# 全局策略调度器
strategy_runner = None


# ═══════════════════════════════════════════
# 全局异常捕获中间件
# ═══════════════════════════════════════════

class ErrorLoggingMiddleware(BaseHTTPMiddleware):
    """捕获所有未处理异常并写入日志"""

    async def dispatch(self, request: Request, call_next):
        try:
            response = await call_next(request)
            return response
        except Exception as e:
            logger.error(
                f"未捕获异常 | {request.method} {request.url.path} | "
                f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
            )
            return JSONResponse(
                status_code=500,
                content={"detail": f"服务器内部错误: {type(e).__name__}: {str(e)}"},
            )


# ═══════════════════════════════════════════
# 生命周期管理
# ═══════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    global okx_client, strategy_runner

    logger.info("=" * 60)
    logger.info("OKX 自动交易系统启动")
    logger.info(f"模式: {'模拟盘' if config.OKX_DEMO else '实盘'}")
    logger.info("=" * 60)

    # 初始化数据库
    await get_db()

    # 初始化 OKX 客户端
    try:
        okx_client = OKXClient()

        # 注入客户端到 API 模块
        account.set_client(okx_client)
        positions.set_client(okx_client)
        market.set_client(okx_client)
        strategies.set_client(okx_client)
    except Exception as e:
        logger.error(f"OKX 客户端初始化失败: {e}\n{traceback.format_exc()}")

    # 初始化策略调度器
    try:
        from core.strategy_runner import StrategyRunner
        strategy_runner = StrategyRunner(okx_client)
        strategies.set_runner(strategy_runner)
        await strategy_runner.start()
    except Exception as e:
        logger.error(f"策略调度器启动失败: {e}\n{traceback.format_exc()}")

    logger.info("系统初始化完成")

    yield

    # 关闭
    logger.info("系统关闭中...")
    if strategy_runner:
        await strategy_runner.stop()
    await close_db()
    logger.info("系统已关闭")


app = FastAPI(
    title="OKX 自动交易系统",
    version="1.0.0",
    lifespan=lifespan,
)

# 全局异常日志中间件（必须在 CORS 之前添加）
app.add_middleware(ErrorLoggingMiddleware)
app.add_middleware(auth.PanelAuthMiddleware)

# CORS（开发阶段允许前端跨域）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(account.router)
app.include_router(positions.router)
app.include_router(strategies.router)
app.include_router(market.router)
app.include_router(settings.router)
app.include_router(auth.router)


# 全局异常处理器（捕获路由内抛出的异常）
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(
        f"请求异常 | {request.method} {request.url.path} | "
        f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
    )
    return JSONResponse(
        status_code=500,
        content={"detail": f"服务器内部错误: {type(exc).__name__}: {str(exc)}"},
    )


# WebSocket 端点
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    auth_expires_at = auth.session_expires_at(websocket.cookies)
    if auth.is_auth_enabled() and auth_expires_at is None:
        await websocket.close(code=1008)
        return
    await ws_manager.connect(websocket)
    try:
        while True:
            timeout = None
            if auth_expires_at is not None:
                timeout = auth_expires_at - auth._now()
                if timeout <= 0:
                    await websocket.close(code=1008)
                    return
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=timeout)
            except asyncio.TimeoutError:
                await websocket.close(code=1008)
                return
            if auth.is_auth_enabled() and auth.session_expires_at(websocket.cookies) is None:
                await websocket.close(code=1008)
                return
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WebSocket 异常: {e}")
    finally:
        ws_manager.disconnect(websocket)


# 健康检查
@app.get("/api/health")
async def health_check():
    return {"status": "ok", "mode": "模拟盘" if config.OKX_DEMO else "实盘"}


# 生产环境托管前端静态文件（SPA history mode）
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    # 静态资源（JS/CSS/图片等）
    app.mount("/assets", StaticFiles(directory=str(static_dir / "assets")), name="assets")

    # SPA fallback: 所有非 /api、/ws 路径都返回 index.html
    from fastapi.responses import FileResponse

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        file_path = static_dir / full_path
        if file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(static_dir / "index.html"))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=config.PORT,
        reload=True,
        log_level="info",
    )
