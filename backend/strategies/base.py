"""
策略接口定义
所有策略必须实现此接口
"""
from abc import ABC, abstractmethod
import pandas as pd


class IStrategy(ABC):
    """策略接口"""

    @property
    @abstractmethod
    def name(self) -> str:
        """策略名称"""
        ...

    @property
    @abstractmethod
    def direction(self) -> str:
        """策略方向: 'short' / 'long' / 'both'"""
        ...

    @abstractmethod
    def check_signal(self, df: pd.DataFrame, params: dict) -> dict | None:
        """
        检测交易信号

        Args:
            df: K线 DataFrame，列: ts, open, high, low, close, vol, volCcy, confirm
            params: 策略参数字典

        Returns:
            信号字典 {'direction': 'short'|'long', 'price': float, 'tp_price': float, 'sl_price': float, 'reason': str}
            或 None（无信号）
        """
        ...

    @abstractmethod
    def compute_indicators(self, df: pd.DataFrame, params: dict) -> dict:
        """
        计算技术指标（供 AI 决策模式使用）

        Returns:
            指标字典，例如 {'smma': 1820.5, 'ema200': 1815.0, 'rsi': 45, ...}
        """
        ...
