"""
SQLite 数据库管理
策略配置 + 交易记录持久化
"""
import json
import aiosqlite
from pathlib import Path

import config
from utils.logger import get_logger

logger = get_logger("Database")

_db: aiosqlite.Connection | None = None


async def get_db() -> aiosqlite.Connection:
    """获取数据库连接（单例）"""
    global _db
    if _db is None:
        _db = await aiosqlite.connect(str(config.DB_PATH))
        _db.row_factory = aiosqlite.Row
        await _db.execute("PRAGMA journal_mode=WAL")
        await _db.execute("PRAGMA foreign_keys=ON")
        await _init_tables(_db)
        logger.info(f"数据库连接已建立: {config.DB_PATH}")
    return _db


async def close_db():
    """关闭数据库连接"""
    global _db
    if _db:
        await _db.close()
        _db = None
        logger.info("数据库连接已关闭")


async def _ensure_column(db: aiosqlite.Connection, table: str, column: str, col_type: str):
    """安全添加列（已存在则跳过）"""
    try:
        await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
        await db.commit()
    except Exception:
        pass  # 列已存在


async def _init_tables(db: aiosqlite.Connection):
    """初始化表结构"""
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS strategies (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            strategy_type TEXT NOT NULL,
            is_active INTEGER DEFAULT 0,
            symbols TEXT DEFAULT '[]',
            decision_mode TEXT DEFAULT 'technical',
            leverage INTEGER DEFAULT 10,
            order_amount_usdt REAL DEFAULT 50,
            mgn_mode TEXT DEFAULT 'cross',
            poll_interval INTEGER DEFAULT 5,
            params TEXT DEFAULT '{}',
            ai_min_confidence INTEGER DEFAULT 70,
            ai_prompt TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            direction TEXT NOT NULL,
            entry_price REAL NOT NULL,
            exit_price REAL,
            quantity REAL NOT NULL,
            leverage INTEGER NOT NULL,
            tp_price REAL,
            sl_price REAL,
            pnl REAL,
            fee REAL,
            status TEXT DEFAULT 'open',
            reason TEXT,
            peak_pnl REAL DEFAULT 0,
            trough_pnl REAL DEFAULT 0,
            entry_time TEXT DEFAULT (datetime('now')),
            exit_time TEXT,
            FOREIGN KEY (strategy_id) REFERENCES strategies(id)
        );

        CREATE TABLE IF NOT EXISTS positions (
            symbol TEXT PRIMARY KEY,
            strategy_id TEXT NOT NULL,
            direction TEXT NOT NULL,
            entry_price REAL NOT NULL,
            quantity REAL NOT NULL,
            leverage INTEGER NOT NULL,
            tp_price REAL,
            sl_price REAL,
            order_id TEXT,
            algo_id TEXT,
            peak_pnl REAL DEFAULT 0,
            trough_pnl REAL DEFAULT 0,
            open_time TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (strategy_id) REFERENCES strategies(id)
        );

        CREATE TABLE IF NOT EXISTS strategy_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            direction TEXT,
            confidence INTEGER,
            reasoning TEXT,
            indicators TEXT,
            decision_mode TEXT,
            result TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (strategy_id) REFERENCES strategies(id)
        );
    """)
    await db.commit()

    # 兼容旧库：给 trades 表补充 peak_pnl/trough_pnl 列
    await _ensure_column(db, "trades", "peak_pnl", "REAL DEFAULT 0")
    await _ensure_column(db, "trades", "trough_pnl", "REAL DEFAULT 0")
    await _ensure_column(db, "positions", "peak_pnl", "REAL DEFAULT 0")
    await _ensure_column(db, "positions", "trough_pnl", "REAL DEFAULT 0")

    # 预置默认策略（如果不存在）
    cursor = await db.execute("SELECT COUNT(*) FROM strategies")
    row = await cursor.fetchone()
    if row[0] == 0:
        await _seed_default_strategies(db)


async def _seed_default_strategies(db: aiosqlite.Connection):
    """插入默认策略配置"""
    defaults = [
        # ═══════════════════════════════════════════
        # okx-smma-trader 纯技术指标策略
        # ═══════════════════════════════════════════
        {
            "id": "smma_short",
            "name": "SMMA 压制做空",
            "strategy_type": "smma_short",
            "decision_mode": "technical",
            "symbols": json.dumps(["ETH-USDT-SWAP"]),
            "leverage": 10,
            "order_amount_usdt": 50,
            "poll_interval": 5,
            "params": json.dumps({
                "smma_period": 170,
                "vol_min_abs": 1000,
                "vol_multiplier": 6,
                "body_percent": 60.0,
                "pct_threshold": 1.0,
                "tp_type": "fixed_pct",
                "stop_offset": 0.3,
                "fixed_tp": 1.4,
                "rr_ratio": 2.0,
                "enable_htf_filter": True,
                "htf_bar": "5m",
                "htf_fast_ema": 20,
                "htf_slow_ema": 50,
                "enable_ema_bias_filter": True,
                "ema_bias_period": 200,
            }),
        },
        {
            "id": "smma_long",
            "name": "SMMA 支撑做多",
            "strategy_type": "smma_long",
            "decision_mode": "technical",
            "symbols": json.dumps(["ETH-USDT-SWAP"]),
            "leverage": 10,
            "order_amount_usdt": 50,
            "poll_interval": 5,
            "params": json.dumps({
                "smma_period": 170,
                "vol_min_abs": 1000,
                "vol_multiplier": 6,
                "body_percent": 60.0,
                "pct_threshold": 1.0,
                "tp_type": "fixed_pct",
                "stop_offset": 0.3,
                "fixed_tp": 1.4,
                "rr_ratio": 2.0,
                "enable_htf_filter": True,
                "htf_bar": "5m",
                "htf_fast_ema": 20,
                "htf_slow_ema": 50,
                "enable_ema_bias_filter": True,
                "ema_bias_period": 200,
            }),
        },
        {
            "id": "spike_fade",
            "name": "脉冲急拉做空",
            "strategy_type": "spike_fade",
            "decision_mode": "technical",
            "symbols": json.dumps([]),
            "leverage": 10,
            "order_amount_usdt": 50,
            "poll_interval": 10,
            "params": json.dumps({
                "bar": "1m",
                "spike_single_pct": 1.2,
                "spike_3bar_pct": 2.0,
                "ema_deviation_pct": 1.0,
                "boll_period": 20,
                "boll_std": 2.0,
                "new_high_lookback": 15,
                "vol_shrink_pct": 30,
                "upper_wick_min_pct": 50,
                "body_ratio_max": 0.3,
                "tp1_pct": 0.8,
                "tp2_pct": 1.5,
                "tp1_ratio": 0.5,
                "sl_pct": 0.5,
                "breakeven_trigger_pct": 0.5,
                "extreme_tp_pct": 2.0,
                "extreme_tp_sec": 30,
                "time_stop_sec": 300,
                "risk": {
                    "max_concurrent": 3,
                    "max_daily_per_symbol": 3,
                    "max_daily_loss_pct": 3.0,
                },
            }),
        },
        {
            "id": "mean_reversion",
            "name": "均值回归做空",
            "strategy_type": "mean_reversion",
            "decision_mode": "technical",
            "symbols": json.dumps([]),
            "leverage": 10,
            "order_amount_usdt": 50,
            "poll_interval": 10,
            "params": json.dumps({
                "bar": "1m",
                "spike_single_pct": 1.2,
                "spike_3bar_pct": 2.0,
                "ema_deviation_pct": 1.0,
                "boll_period": 20,
                "boll_std": 2.0,
                "new_high_lookback": 15,
                "vol_shrink_pct": 30,
                "upper_wick_min_pct": 50,
                "body_ratio_max": 0.3,
                "tp1_pct": 0.8,
                "tp2_pct": 1.5,
                "tp1_ratio": 0.5,
                "sl_pct": 0.5,
                "breakeven_trigger_pct": 0.5,
                "extreme_tp_pct": 2.0,
                "extreme_tp_sec": 30,
                "time_stop_sec": 300,
                "risk": {
                    "max_concurrent": 3,
                    "max_daily_per_symbol": 3,
                    "max_daily_loss_pct": 3.0,
                },
            }),
        },
        # ═══════════════════════════════════════════
        # BOLL 系列策略
        # ═══════════════════════════════════════════
        {
            "id": "boll_trend_pullback",
            "name": "趋势回踩二次启动",
            "strategy_type": "boll_trend_pullback",
            "decision_mode": "technical",
            "symbols": json.dumps(["BTC-USDT-SWAP", "ETH-USDT-SWAP"]),
            "leverage": 10,
            "order_amount_usdt": 50,
            "poll_interval": 60,
            "params": json.dumps({
                "bar": "15m",
                "htf_bar": "1H",
                "boll_period": 20,
                "boll_std": 2.0,
                "htf_lookback_high": 20,
                "pullback_tolerance_pct": 0.3,
                "vol_multiplier": 1.5,
                "tp_pct": 1.5,
                "sl_offset_pct": 0.2,
            }),
        },
        {
            "id": "boll_midline_reclaim",
            "name": "BOLL 中线收复",
            "strategy_type": "boll_midline_reclaim",
            "decision_mode": "technical",
            "symbols": json.dumps(["BTC-USDT-SWAP", "ETH-USDT-SWAP"]),
            "leverage": 10,
            "order_amount_usdt": 50,
            "poll_interval": 60,
            "params": json.dumps({
                "bar": "15m",
                "boll_period": 20,
                "boll_std": 2.0,
                "suppress_lookback": 5,
                "suppress_count": 3,
                "sl_offset_pct": 0.2,
            }),
        },
        {
            "id": "climax_exhaustion_scalp",
            "name": "高潮衰竭剥头皮",
            "strategy_type": "climax_exhaustion_scalp",
            "decision_mode": "technical",
            "symbols": json.dumps([]),
            "leverage": 10,
            "order_amount_usdt": 50,
            "poll_interval": 10,
            "params": json.dumps({
                "bar": "1m",
                "new_high_lookback": 15,
                "vol_shrink_pct": 30,
                "body_ratio_max": 0.3,
                "tp_pct": 0.5,
                "sl_pct": 0.4,
            }),
        },
        # ═══════════════════════════════════════════
        # ai-bian AI 驱动策略
        # ═══════════════════════════════════════════
        {
            "id": "ai_aggressive_5m",
            "name": "AI 激进短线 (5m)",
            "strategy_type": "ai_aggressive_5m",
            "decision_mode": "ai",
            "symbols": json.dumps(["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP", "DOGE-USDT-SWAP"]),
            "leverage": 3,
            "order_amount_usdt": 50,
            "poll_interval": 300,
            "ai_min_confidence": 70,
            "ai_prompt": "# 激进短线交易策略（先定方向版）\n\n核心目标：捕捉启动与动量，优先单边执行，避免多空摇摆\n\n## 一、方向判定（必须最先执行）\n\n仅使用 EMA 结构强制确定方向：\n\n* EMA7 > EMA50 → **direction = LONG**\n* EMA7 < EMA50 → **direction = SHORT**\n\n### reasoning 必须包含：\n* EMA7 与 EMA50 具体数值\n  示例：EMA7(102.5) > EMA50(100.2)\n\n## 二、入场触发信号（只允许当前方向）\n\n### 若 direction = LONG，仅允许以下触发：\n1. 价格向上突破 EMA20 / EMA50\n2. 回踩 EMA20 后强势反弹\n3. 出现向上大实体动量K线\n\n### 若 direction = SHORT，仅允许以下触发：\n1. 价格向下跌破 EMA20 / EMA50\n2. 反弹触碰 EMA20 后承压回落\n3. 出现向下大实体动量K线\n\n👉 **必须满足 ≥1 项，否则直接 IDLE**\n\n## 三、方向评分（只计算当前方向）\n\n### LONG 评分项\n* RSI ∈ [30,50] 且上升 → +1\n* 成交量放大 → +1\n* EMA 多头结构（EMA7>EMA20>EMA50）→ +1\n\n### SHORT 评分项\n* RSI ∈ [50,70] 且下降 → +1\n* 成交量放大 → +1\n* EMA 空头结构（EMA7<EMA20<EMA50）→ +1\n\n## 四、执行规则\n* score ≥ 2 → 允许开仓\n\n## 五、强约束\n* ❌ 禁止多空同时判断\n* ❌ 禁止无触发直接开仓\n* ❌ 禁止使用模糊描述（必须有数值）",
            "params": json.dumps({
                "ema_periods": [7, 20, 50],
                "rsi_period": 14,
                "adx_period": 14,
                "atr_period": 14,
                "vol_compare_period": 20,
                "bar": "5m",
                "stop_loss_atr_multiplier": 2.0,
                "take_profit_ratios": [1.5, 2.5],
                "max_daily_trades": 8,
                "max_hold_time_minutes": 120,
            }),
        },
        {
            "id": "ai_trend_15m",
            "name": "AI 中短线趋势 (15m)",
            "strategy_type": "ai_trend_15m",
            "decision_mode": "ai",
            "symbols": json.dumps(["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP", "DOGE-USDT-SWAP"]),
            "leverage": 3,
            "order_amount_usdt": 50,
            "poll_interval": 900,
            "ai_min_confidence": 70,
            "ai_prompt": "你是一个理性的中短线交易员，追求稳定胜率和趋势交易机会。\n\n请重点分析：\n\n1. 趋势方向（EMA20/120排列）\n   - 多头：EMA20 > EMA120 → direction = LONG\n   - 空头：EMA20 < EMA120 → direction = SHORT\n\n2. 趋势强度（ADX）\n   - ADX > 25：趋势有效\n   - ADX > 30：趋势较强\n   - ADX < 20：震荡，避免交易\n\n3. 回调入场机会\n   - 多头趋势中价格回踩EMA20或EMA50\n   - 空头趋势中价格反弹至EMA20或EMA50\n   - 严格规则：价格必须在EMA50附近（±0.5%以内）\n\n4. RSI辅助判断\n   - 多头：RSI不应过高（<65）\n   - 空头：RSI不应过低（>35）\n\n交易原则：\n- 只做顺势单，不做逆势抄底/摸顶\n- 必须有\"趋势 + 回调 + 指标确认\"三要素\n- 当三要素不同时满足时，宁可错过，不可开仓",
            "params": json.dumps({
                "ema_periods": [20, 50, 120],
                "rsi_period": 14,
                "adx_period": 14,
                "atr_period": 14,
                "macd_params": {"fast": 12, "slow": 26, "signal": 9},
                "vol_compare_period": 20,
                "bar": "15m",
                "stop_loss_atr_multiplier": 2.2,
                "take_profit_ratios": [2, 3],
                "max_daily_trades": 5,
                "max_hold_time_minutes": 360,
                "trailing_stop": True,
            }),
        },
        {
            "id": "ai_steady_1h",
            "name": "AI 稳健趋势 (1h)",
            "strategy_type": "ai_steady_1h",
            "decision_mode": "ai",
            "symbols": json.dumps(["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP", "DOGE-USDT-SWAP"]),
            "leverage": 3,
            "order_amount_usdt": 50,
            "poll_interval": 1200,
            "ai_min_confidence": 70,
            "ai_prompt": "## 角色\n你是一个理性的稳健型趋势交易员，只能基于规则做机械决策，禁止主观判断或自我推翻。\n\n## 方向判断（硬规则，先给明确方向）\n- LONG: EMA50 > EMA200\n- SHORT: EMA50 < EMA200\n- reasoning 必须写具体数值，例：EMA50(102.5) > EMA200(100.2)\n\n## 入场条件\n### 必须全部满足\n1. **EMA200偏离 ≤ 1.60%**：需说明偏离百分比\n2. **预计成交量 ≥ 前一根K线 × 1.8倍**：需说明倍数\n\n### 辅助条件（至少满足1项）\n- A. **EMA50接近**：价格偏离 ≤ 1.00%\n- B. **RSI有效区间**：LONG: RSI 35~65 / SHORT: RSI 35~65\n- C. **K线确认**：方向一致 + 影线 ≤ 0.90%\n\n## 决策\n硬条件全满足 + 辅助条件≥1 → 允许交易",
            "params": json.dumps({
                "ema_periods": [50, 120, 200],
                "rsi_period": 14,
                "adx_period": 14,
                "atr_period": 14,
                "macd_params": {"fast": 12, "slow": 26, "signal": 9},
                "vol_compare_period": 20,
                "bar": "1h",
                "stop_loss_atr_multiplier": 3.0,
                "take_profit_ratios": [2.5, 4],
                "max_daily_trades": 2,
                "max_hold_time_minutes": 1440,
                "trailing_stop": True,
            }),
        },
        {
            "id": "ai_ema_cross_15m",
            "name": "AI EMA交叉预判 (15m)",
            "strategy_type": "ai_ema_cross_15m",
            "decision_mode": "ai",
            "symbols": json.dumps(["SOL-USDT-SWAP", "DOGE-USDT-SWAP"]),
            "leverage": 3,
            "order_amount_usdt": 50,
            "poll_interval": 900,
            "ai_min_confidence": 90,
            "ai_prompt": "## 一、死叉预判 · 开多信号\n满足**全部以下条件**，判定预判死叉，直接开多，信号置信度96\n1. 当前价格＜EMA120均线\n2. EMA7均线＞EMA120均线\n3. EMA7与EMA120价格差值距离＜0.2%\n\n## 二、金叉预判 · 开空信号\n满足**全部以下条件**，判定预判金叉，直接开空，信号置信度96\n1. 当前价格＞EMA120均线\n2. EMA7均线＜EMA120均线\n3. EMA7与EMA120价格差值距离＜0.2%\n\n## 三、执行规则\n- **任意一条条件不满足 → 直接输出 IDLE**\n- 如果满足信号，置信度给96，不浮动调整\n- 仅贴合EMA7、EMA120价格位置与间距阈值判定，不叠加其他指标\n- 禁止脑补多空方向、禁止额外补充行情逻辑\n- 无完全匹配信号，绝不生成开仓指令",
            "params": json.dumps({
                "ema_periods": [7, 120],
                "adx_period": 14,
                "bar": "15m",
                "stop_loss_atr_multiplier": 2.5,
                "take_profit_ratios": [3, 5],
                "max_daily_trades": 2,
                "max_hold_time_minutes": 1440,
            }),
        },
    ]

    for s in defaults:
        columns = list(s.keys())
        placeholders = ", ".join(f":{k}" for k in columns)
        col_names = ", ".join(columns)
        await db.execute(
            f"INSERT INTO strategies ({col_names}) VALUES ({placeholders})",
            s,
        )
    await db.commit()
    logger.info(f"已插入 {len(defaults)} 个默认策略配置")

