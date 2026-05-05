"""
策略注册表 — 按 strategy_type 获取策略实例
"""
from strategies.base import IStrategy
from strategies.smma_short import SMMAShortStrategy
from strategies.smma_long import SMMALongStrategy
from strategies.ai_strategy import AIStrategy
from strategies.boll_trend_pullback import BollTrendPullbackStrategy
from strategies.boll_midline_reclaim import BollMidlineReclaimStrategy
from strategies.climax_exhaustion_scalp import ClimaxExhaustionScalpStrategy
from strategies.spike_fade_mr import SpikeFadeMRStrategy
from strategies.martingale_contract import MartingaleContractStrategy
from strategies.contract_grid import ContractGridStrategy

# 共享实例
_spike_fade_mr = SpikeFadeMRStrategy()

# 策略注册表
_registry: dict[str, IStrategy] = {
    # okx-smma-trader 纯技术指标策略
    "smma_short": SMMAShortStrategy(),
    "smma_long": SMMALongStrategy(),
    # BOLL 系列策略
    "boll_trend_pullback": BollTrendPullbackStrategy(),
    "boll_midline_reclaim": BollMidlineReclaimStrategy(),
    "climax_exhaustion_scalp": ClimaxExhaustionScalpStrategy(),
    "martingale_contract": MartingaleContractStrategy(),
    "contract_grid": ContractGridStrategy(),
    # 脉冲急拉+均值回归（两个 ID 共享同一实例）
    "spike_fade": _spike_fade_mr,
    "mean_reversion": _spike_fade_mr,
    # ai-bian AI 驱动策略
    "ai_aggressive_5m": AIStrategy("激进短线 (5m)", "both"),
    "ai_trend_15m": AIStrategy("中短线趋势 (15m)", "both"),
    "ai_steady_1h": AIStrategy("稳健趋势 (1h)", "both"),
    "ai_ema_cross_15m": AIStrategy("EMA交叉预判 (15m)", "both"),
}


def get_strategy(strategy_type: str) -> IStrategy | None:
    """根据策略类型获取实例"""
    return _registry.get(strategy_type)


def get_all_strategy_types() -> list[str]:
    """获取所有已注册的策略类型"""
    return list(_registry.keys())
