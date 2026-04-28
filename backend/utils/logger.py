"""
日志工具 — 基于 loguru
所有异常和运行日志写入 data/logs/ 目录
"""
import sys
from pathlib import Path
from loguru import logger

# 日志目录（使用绝对路径，兼容 Docker）
LOG_DIR = Path(__file__).parent.parent / "data" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# 移除默认 handler，自定义格式
logger.remove()

# 控制台输出
logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <7}</level> | <cyan>{extra[module]:<18}</cyan> | {message}",
    level="INFO",
    filter=lambda record: record["extra"].setdefault("module", "system"),
)

# 文件日志 — 全量（DEBUG 级别）
logger.add(
    str(LOG_DIR / "trader_{time:YYYY-MM-DD}.log"),
    rotation="00:00",
    retention="30 days",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <7} | {extra[module]:<18} | {message}",
    level="DEBUG",
    filter=lambda record: record["extra"].setdefault("module", "system"),
    encoding="utf-8",
)

# 错误日志 — 单独文件，只记录 WARNING 及以上
logger.add(
    str(LOG_DIR / "error_{time:YYYY-MM-DD}.log"),
    rotation="00:00",
    retention="30 days",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <7} | {extra[module]:<18} | {message}",
    level="WARNING",
    filter=lambda record: record["extra"].setdefault("module", "system"),
    encoding="utf-8",
)


def get_logger(module: str):
    """获取带模块名的 logger 实例"""
    return logger.bind(module=module)
