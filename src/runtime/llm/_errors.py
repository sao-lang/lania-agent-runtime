"""
LLM 执行错误定义。

LLMExecutionError 是 LLMExecutor 执行的统一错误类型，
携带最后一次错误信息和重试上下文。
"""

from __future__ import annotations

from typing import Any


class LLMExecutionError(Exception):
    """LLM 执行错误——重试耗尽后的统一异常。

    携带最后一次错误信息和当前错误上下文，供 Runtime 的 on_error hook 处理。

    Attributes:
        last_error: 最后一次原始异常。
        consecutive_errors: 当前会话连续错误次数。
        model: 出错的模型名。
    """

    def __init__(
        self,
        last_error: Exception | None = None,
        consecutive_errors: int = 0,
        model: str = "",
    ) -> None:
        """初始化 LLMExecutionError。

        Args:
            last_error: 最后一次原始异常。
            consecutive_errors: 当前会话连续错误次数。
            model: 出错的模型名。
        """
        self.last_error = last_error
        self.consecutive_errors = consecutive_errors
        self.model = model
        msg = f"LLM 执行失败 (模型: {model}, 连续错误: {consecutive_errors})"
        if last_error:
            msg += f": {last_error!s}"
        super().__init__(msg)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式，便于序列化和日志记录。

        Returns:
            包含错误信息的字典。
        """
        return {
            "error_type": "LLMExecutionError",
            "message": str(self),
            "last_error": repr(self.last_error) if self.last_error else None,
            "consecutive_errors": self.consecutive_errors,
            "model": self.model,
        }
