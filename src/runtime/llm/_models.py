"""
LLMExecutor 数据模型。

定义 LLM 调用的统一返回格式、工具调用请求、Token 用量等数据结构。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class FinishReason(str, Enum):
    """LLM 调用结束原因枚举——统一各文档和 LoopStrategy 的判断引用。"""

    STOP = "stop"
    """LLM 正常结束回复。"""
    TOOL_CALLS = "tool_calls"
    """LLM 请求调用工具。"""
    LENGTH = "length"
    """回复达到 max_tokens 上限被截断。"""
    ERROR = "error"
    """LLM 调用过程中发生错误。"""


@dataclass
class LLMUsage:
    """Token 用量统计。"""

    prompt_tokens: int = 0
    """提示词 token 数量。"""
    completion_tokens: int = 0
    """补全 token 数量。"""

    @property
    def total_tokens(self) -> int:
        """总 token 消耗。"""
        return self.prompt_tokens + self.completion_tokens


@dataclass
class ToolCall:
    """LLM 返回的工具调用请求。"""

    id: str = ""
    """工具调用 ID（tool_call_id）。"""
    name: str = ""
    """工具名称。"""
    arguments: dict[str, Any] = field(default_factory=dict)
    """解析后的参数字典。"""
    raw_arguments: str = ""
    """原始 JSON 字符串（用于日志/审计）。"""


@dataclass
class LLMResponse:
    """LLM 调用的统一返回格式。

    Attributes:
        content: 文本回复（tool_calls 时可能为空）。
        tool_calls: LLM 请求调用的工具列表。
        usage: Token 消耗统计。
        finish_reason: 结束原因枚举。
        model: 实际使用的模型名。
    """

    content: str = ""
    """文本回复（tool_calls 时可能为空）。"""
    tool_calls: list[ToolCall] = field(default_factory=list)
    """LLM 请求调用的工具列表。"""
    usage: LLMUsage = field(default_factory=LLMUsage)
    """Token 消耗统计。"""
    finish_reason: FinishReason = FinishReason.STOP
    """结束原因枚举。"""
    model: str = ""
    """实际使用的模型名。"""


@dataclass
class LLMMessage:
    """单条消息，LLMExecutor 消费的输入格式。

    与 Runtime 侧的 messages dict 格式对应，提供类型安全的访问。
    """

    role: str = ""
    """消息角色："system" | "user" | "assistant" | "tool"。"""
    content: str | None = None
    """文本内容。"""
    tool_calls: list[ToolCall] | None = None
    """assistant 消息可能带 tool_calls。"""
    tool_call_id: str | None = None
    """tool 消息对应的 tool_call_id。"""
    name: str | None = None
    """tool 消息对应的工具名。"""
