"""
ToolSpec 定义——Tool 原语的数据结构。

ToolSpec 是本地函数工具的完整抽象，包含名称、描述、参数 schema 和执行 handler。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


@dataclass
class ToolSpec:
    """
    Tool 原语：本地函数工具。

    纯函数，无状态，进程内执行。通过 to_openai_schema() 转换为 LLM 可识别的
    function calling 格式，供 LLMExecutor 消费。

    Attributes:
        name: 工具名称，必须唯一。
        description: 工具描述，LLM 据此决定何时调用。
        parameters: JSON Schema 格式的参数定义。
        handler: 异步执行函数，接收 **kwargs 返回任意结果。
        required: 必需参数名称列表。
        timeout: 执行超时时间（秒），默认 30.0。

    Raises:
        ValueError: 如果 name 为空或包含非法字符。
    """

    name: str
    """工具名称，必须全局唯一，须匹配 ^[a-zA-Z0-9_-]+$。"""

    description: str
    """工具描述，LLM 据此决定何时调用。"""

    parameters: dict[str, Any]
    """JSON Schema 格式的参数定义。"""

    handler: Callable[..., Awaitable[Any]]
    """异步执行函数，接收 **kwargs 返回任意结果。"""

    required: list[str] = field(default_factory=list)
    """必需参数名称列表。"""

    timeout: float = 30.0
    """执行超时时间（秒）。"""

    def __post_init__(self) -> None:
        """初始化后校验 name 格式。"""
        if not self.name or not re.match(r"^[a-zA-Z0-9_-]+$", self.name):
            raise ValueError(
                f"Tool name '{self.name}' 格式无效：须匹配 ^[a-zA-Z0-9_-]+$，不能为空"
            )

    def to_openai_schema(self) -> dict:
        """
        转换为 OpenAI tools 参数格式。

        Returns:
            符合 OpenAI function calling 格式的字典。
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.parameters,
                    "required": self.required,
                },
            },
        }
