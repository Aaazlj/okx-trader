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
    await _ensure_column(db, "trades", "pnl_ratio", "REAL")
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
            "decision_mode": "hybrid",
            "symbols": json.dumps(["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP", "DOGE-USDT-SWAP"]),
            "leverage": 3,
            "order_amount_usdt": 50,
            "poll_interval": 300,
            "ai_min_confidence": 70,
            "ai_prompt": "# 激进短线交易策略（先定方向版）\n\n核心目标：捕捉启动与动量，优先单边执行，避免多空摇摆\n\n## 一、方向判定（必须最先执行）\n\n仅使用 EMA 结构强制确定方向：\n\n* EMA7 > EMA50 → **direction = LONG**\n* EMA7 < EMA50 → **direction = SHORT**\n\n### reasoning 必须包含：\n* EMA7 与 EMA50 具体数值\n  示例：EMA7(102.5) > EMA50(100.2)\n\n## 二、入场触发信号（只允许当前方向）\n\n### 若 direction = LONG，仅允许以下触发：\n1. 价格向上突破 EMA20 / EMA50\n2. 回踩 EMA20 后强势反弹\n3. 出现向上大实体动量K线\n\n### 若 direction = SHORT，仅允许以下触发：\n1. 价格向下跌破 EMA20 / EMA50\n2. 反弹触碰 EMA20 后承压回落\n3. 出现向下大实体动量K线\n\n👉 **必须满足 ≥1 项，否则直接 IDLE**\n\n## 三、方向评分（只计算当前方向）\n\n### LONG 评分项\n* RSI ∈ [30,50] 且上升 → +1\n* 成交量放大 → +1\n* EMA 多头结构（EMA7>EMA20>EMA50）→ +1\n\n### SHORT 评分项\n* RSI ∈ [50,70] 且下降 → +1\n* 成交量放大 → +1\n* EMA 空头结构（EMA7<EMA20<EMA50）→ +1\n\n## 四、执行规则\n* score ≥ 2 → 允许开仓\n\n## 五、强约束\n* ❌ 禁止多空同时判断\n* ❌ 禁止无触发直接开仓\n* ❌ 禁止使用模糊描述（必须有数值）",
            "params": json.dumps({
                "indicators": ["EMA", "RSI", "ADX", "ATR"],
                "ema_periods": [7, 20, 50],
                "rsi_period": 14,
                "adx_period": 14,
                "atr_period": 14,
                "fixed_tp": 1.4,
                "vol_compare_period": 20,
                "bar": "5m",
                "stop_loss_atr_multiplier": 2.0,
                "take_profit_ratios": [1.5, 2.5],
                "max_daily_trades": 8,
                "max_hold_time_minutes": 120,
                "pre_filter": {
                    "adx_min": 20,
                    "ema_direction": True,
                },
            }),
        },
        {
            "id": "ai_trend_15m",
            "name": "AI 中短线趋势 (15m)",
            "strategy_type": "ai_trend_15m",
            "decision_mode": "hybrid",
            "symbols": json.dumps(["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP", "DOGE-USDT-SWAP"]),
            "leverage": 3,
            "order_amount_usdt": 50,
            "poll_interval": 900,
            "ai_min_confidence": 70,
            "ai_prompt": "强趋势回调交易策略\n一、做多 LONG 完整规则\n1. 趋势方向与强度（必须满足，否则IDLE）\n- 趋势方向：EMA20 > EMA60\n- 强度过滤：ADX(14) > 25，未满足则直接IDLE（不进行任何操作）\n2. 回调入场机会\n价格回调至 [EMA60, EMA20] 区间内，且价格位置接近EMA60（优先选择靠近区间下沿的回调点位）。\n3. 辅助共振确认\n- RSI指标：RSI < 65\n- OI资金共振：持仓量OI变化率 > 0\n- K线信号：在回调入场区域出现反转K线（如看涨吞没形态、锤子线或长下影Pin Bar）\n4. 交易原则\n如果同时满足 \"强趋势（方向+强度）+ 回调区域 + OI资金共振\" 三大核心要素，RSI和K线信号作为辅助确认，就开仓（高置信度）。\n二、做空 SHORT 完整规则\n1. 趋势方向与强度（必须满足，否则IDLE）\n- 趋势方向：EMA20 < EMA60\n- 强度过滤：ADX(14) > 25，未满足则直接IDLE（不进行任何操作）\n2. 回调入场机会\n价格反弹至 [EMA20, EMA60] 区间内，且价格位置接近EMA60（优先选择靠近区间上沿的反弹点位）。\n3. 辅助共振确认\n- RSI指标：RSI > 35\n- OI资金共振：持仓量OI变化率 < 0\n- K线信号：在反弹入场区域出现反转K线（如看跌吞没形态、流星线或长上影Pin Bar）\n4. 交易原则\n如果同时满足 \"强趋势（方向+强度）+ 回调区域 + OI资金共振\" 三大核心要素，RSI和K线信号作为辅助确认，就开仓（高置信度）。",
            "params": json.dumps({
                "indicators": ["EMA", "RSI", "ADX", "MACD", "ATR"],
                "ema_periods": [20, 50, 60, 120],
                "rsi_period": 14,
                "adx_period": 14,
                "atr_period": 14,
                "fixed_tp": 1.4,
                "macd_params": {"fast": 12, "slow": 26, "signal": 9},
                "vol_compare_period": 20,
                "bar": "15m",
                "stop_loss_atr_multiplier": 2.2,
                "take_profit_ratios": [2, 3],
                "max_daily_trades": 5,
                "max_hold_time_minutes": 360,
                "trailing_stop": True,
                "pre_filter": {
                    "adx_min": 25,
                    "ema_direction": True,
                },
            }),
        },
        {
            "id": "ai_steady_1h",
            "name": "AI 稳健趋势 (1h)",
            "strategy_type": "ai_steady_1h",
            "decision_mode": "hybrid",
            "symbols": json.dumps(["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP", "DOGE-USDT-SWAP"]),
            "leverage": 3,
            "order_amount_usdt": 50,
            "poll_interval": 1200,
            "ai_min_confidence": 70,
            "ai_prompt": "机械稳健共振策略\n一、做多 LONG 完整规则\n1. 趋势方向判定 EMA50>EMA200\n2. 入场硬性条件（全部必须满足）\nOI 资金共振：持仓量 OI 变化率 ＞ 0\n价格位置合理：当前价格偏离 EMA200 幅度 ≤ 2.5%\n成交量放大：当前预计成交量 ≥ 前一根 K 线成交量 × 1.5 倍\nATR 波动率过滤：ATR 波动率 ≥ 0.38%\n3. 辅助条件（至少满足 1 项）\nA. RSI 有效区间：\n35<RSI<65\nB. 价格回踩：价格回落至 EMA50 ±1% 区间内\nC. K 线形态确认：收实体阳线，且下影线比例 ≤ 0.9%\n4. 开仓决策\n四项硬性条件全部达标 + 任意 1 项及以上辅助条件满足 → 触发做多开仓置信度95\n二、做空 SHORT 完整规则\n1. 趋势方向判定\nEMA50<EMA200\n2. 入场硬性条件（全部必须满足）\nOI 资金共振：持仓量 OI 变化率 ＜ 0\n价格位置合理：当前价格偏离 EMA200 幅度 ≤ 2.5%\n成交量放大：当前预计成交量 ≥ 前一根 K 线成交量 × 1.5 倍\nATR 波动率过滤：ATR 波动率 ≥ 0.38%\n3. 辅助条件（至少满足 1 项）\nA. RSI 有效区间：\n35<RSI<65\nB. 价格反弹：价格回升至 EMA50 ±1% 区间内\nC. K 线形态确认：收实体阴线，且上影线比例 ≤ 0.9%\n4. 开仓决策\n四项硬性条件全部达标 + 任意 1 项及以上辅助条件满足 → 触发做空开仓置信度95",
            "params": json.dumps({
                "indicators": ["EMA", "RSI", "ADX", "MACD", "ATR"],
                "ema_periods": [20, 50, 200],
                "rsi_period": 14,
                "adx_period": 14,
                "atr_period": 14,
                "fixed_tp": 1.4,
                "macd_params": {"fast": 12, "slow": 26, "signal": 9},
                "vol_compare_period": 20,
                "bar": "1h",
                "stop_loss_atr_multiplier": 3.0,
                "take_profit_ratios": [2.5, 4],
                "max_daily_trades": 2,
                "max_hold_time_minutes": 1440,
                "trailing_stop": True,
                "pre_filter": {
                    "adx_min": 20,
                    "ema_direction": True,
                },
            }),
        },
        {
            "id": "ai_ema_cross_15m",
            "name": "AI EMA交叉预判 (15m)",
            "strategy_type": "ai_ema_cross_15m",
            "decision_mode": "hybrid",
            "symbols": json.dumps(["SOL-USDT-SWAP", "DOGE-USDT-SWAP"]),
            "leverage": 3,
            "order_amount_usdt": 50,
            "poll_interval": 900,
            "ai_min_confidence": 90,
            "ai_prompt": "金叉死叉策略\n一、做空 SHORT 完整规则\n1. 做空预判信号（预判死叉，置信度96）\n核心条件（全部满足，方可直接开多）\n- 当前价格 < EMA120\n- EMA7 > EMA120\n- |EMA7 - EMA120| / EMA120 < 0.18%（EMA7与EMA120极度贴近）\n辅助确认（同步满足，验证下跌动能衰竭）\nRSI(14) < 40 且 成交量 < 前1根K线均量\n2. 执行规则\n- 上述核心条件 + 辅助确认，任意一条不满足，直接输出 IDLE（不进行任何操作）\n- 所有条件全部满足时，严格按做多方向开仓，不做额外主观过滤\n二、做多 LONG 完整规则\n1. 做多预判信号（预判金叉，置信度96）\n核心条件（全部满足，方可直接开空）\n- 当前价格 > EMA120\n- EMA7 < EMA120\n- |EMA7 - EMA120| / EMA120 < 0.18%（EMA7与EMA120极度贴近）\n辅助确认（同步满足，验证上涨动能衰竭）\nRSI(14) > 60 且 成交量 < 前1根K线均量\n2. 执行规则\n- 上述核心条件 + 辅助确认，任意一条不满足，直接输出 IDLE（不进行任何操作）\n- 所有条件全部满足时，严格按做空方向开仓，不做额外主观过滤",
            "params": json.dumps({
                "indicators": ["EMA", "RSI", "ADX"],
                "ema_periods": [7, 120],
                "rsi_period": 14,
                "adx_period": 14,
                "fixed_tp": 1.4,
                "bar": "15m",
                "stop_loss_atr_multiplier": 2.5,
                "take_profit_ratios": [3, 5],
                "max_daily_trades": 2,
                "max_hold_time_minutes": 1440,
                "pre_filter": {
                    "adx_min": 15,
                },
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

