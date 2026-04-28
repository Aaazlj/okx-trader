"""
OKX 自动交易系统 — 配置管理
从 .env 文件和环境变量中加载所有配置参数
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ═══════════════════════════════════════════
# OKX API 凭证
# ═══════════════════════════════════════════
OKX_API_KEY = os.getenv("OKX_API_KEY", "")
OKX_SECRET_KEY = os.getenv("OKX_SECRET_KEY", "")
OKX_PASSPHRASE = os.getenv("OKX_PASSPHRASE", "")
OKX_DEMO = os.getenv("OKX_DEMO", "true").lower() == "true"

# ═══════════════════════════════════════════
# 代理设置
# ═══════════════════════════════════════════
HTTP_PROXY = os.getenv("HTTP_PROXY", "")
HTTPS_PROXY = os.getenv("HTTPS_PROXY", "")

# ═══════════════════════════════════════════
# AI 服务配置 (OpenAI 兼容格式)
# ═══════════════════════════════════════════
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_API_URL = os.getenv("OPENAI_API_URL", "https://api.openai.com/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# ═══════════════════════════════════════════
# 服务配置
# ═══════════════════════════════════════════
PORT = int(os.getenv("PORT", "8000"))

# ═══════════════════════════════════════════
# 数据目录
# ═══════════════════════════════════════════
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "okx_trader.db"

# ═══════════════════════════════════════════
# 默认交易参数
# ═══════════════════════════════════════════
DEFAULT_LEVERAGE = 10
DEFAULT_ORDER_AMOUNT_USDT = 50
DEFAULT_MGN_MODE = "cross"
DEFAULT_POLL_INTERVAL = 5  # 秒
CANDLE_FETCH_LIMIT = 500
