"""
WebSocket 连接管理器
广播实时状态、信号和日志到所有前端客户端
"""
import json
from fastapi import WebSocket
from utils.logger import get_logger

logger = get_logger("WebSocket")


class WSManager:
    """WebSocket 连接管理器"""

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket 客户端已连接，当前连接数: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info(f"WebSocket 客户端已断开，当前连接数: {len(self.active_connections)}")

    async def broadcast(self, event: str, data: dict):
        """广播消息给所有客户端"""
        message = json.dumps({"event": event, "data": data}, ensure_ascii=False, default=str)
        dead = []
        for conn in self.active_connections:
            try:
                await conn.send_text(message)
            except Exception:
                dead.append(conn)
        for conn in dead:
            self.disconnect(conn)


# 全局单例
ws_manager = WSManager()
