"""
重试策略模块——RetryPolicy 定义。

为 LLMExecutor 提供指数退避重试的配置与控制。
可重试的异常类型由 policy 统一管理。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RetryPolicy:
    """重试策略——控制 LLM 调用失败后的退避重试行为。

    Attributes:
        max_retries: 最大重试次数（默认 3）。
        backoff_base: 指数退避基数秒数（默认 1.0）。
        backoff_max: 最大退避秒数（默认 30.0）。
        retryable_exceptions: 可重试的异常类型元组。
    """

    max_retries: int = 3
    """最大重试次数。"""

    backoff_base: float = 1.0
    """指数退避基数秒数。"""

    backoff_max: float = 30.0
    """最大退避秒数。"""

    retryable_exceptions: tuple[type[Exception], ...] = field(default_factory=tuple)
    """可重试的异常类型元组。"""

    def get_backoff(self, attempt: int) -> float:
        """计算第 attempt 次重试的退避秒数。

        Args:
            attempt: 当前重试序号（0-based）。

        Returns:
            需要等待的秒数。
        """
        delay = self.backoff_base * (2**attempt)
        return min(delay, self.backoff_max)

    async def sleep(self, attempt: int) -> None:
        """执行退避等待。

        Args:
            attempt: 当前重试序号。
        """
        await asyncio.sleep(self.get_backoff(attempt))

    def is_retryable(self, exc: Exception) -> bool:
        """判断异常是否可重试。

        Args:
            exc: 要检查的异常。

        Returns:
            True 表示可重试，False 表示不应重试。
        """
        return isinstance(exc, self.retryable_exceptions)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式。

        Returns:
            策略的字典表示。
        """
        return {
            "max_retries": self.max_retries,
            "backoff_base": self.backoff_base,
            "backoff_max": self.backoff_max,
        }
