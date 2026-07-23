"""
Loop 策略共享类型定义。

为 LoopStrategy 族群提供独立的共享类型，避免循环导入。
包含 RunResult / StreamEvent 的别名或补充类型，以及执行步骤状态。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from src.runtime.llm._models import FinishReason


class StepStatus(str, Enum):
    """单步执行结果状态枚举。"""

    SUCCESS = "success"
    """步骤正常完成。"""
    BLOCKED = "blocked"
    """步骤被拦截阻断。"""
    PAUSED = "paused"
    """步骤被暂停（HumanInTheLoop）。"""
    ERROR = "error"
    """步骤执行出错。"""
    CANCELLED = "cancelled"
    """步骤被取消。"""


@dataclass
class StepResult:
    """
    单步（run_step）执行结果。

    LoopStrategy 根据此结果决定下一步动作：
    - finish_reason == "tool_calls" → 继续循环执行工具
    - finish_reason in ("stop", "length") → 结束循环（除非 Router 覆盖）
    - status == "blocked" → 结束循环
    """

    finish_reason: FinishReason = FinishReason.STOP
    """LLM 结束原因。"""
    status: StepStatus = StepStatus.SUCCESS
    """步骤状态。"""
    content: str = ""
    """LLM 回复文本内容。"""
    tool_calls: list[Any] = field(default_factory=list)
    """LLM 请求的工具调用列表。"""
    error: str | None = None
    """错误信息（status 为 ERROR 时）。"""

    @property
    def is_blocked(self) -> bool:
        """是否被阻断。"""
        return self.status == StepStatus.BLOCKED

    @property
    def has_tool_calls(self) -> bool:
        """是否包含工具调用。"""
        return len(self.tool_calls) > 0 or self.finish_reason == FinishReason.TOOL_CALLS


@dataclass
class PlanStep:
    """PlanExecuteLoop 的计划步骤——单步任务描述。"""

    id: str = ""
    """步骤唯一标识。"""
    description: str = ""
    """步骤描述。"""
    depends_on: list[str] = field(default_factory=list)
    """依赖的上一步 ID 列表。"""


@dataclass
class Plan:
    """PlanExecuteLoop 的完整执行计划。"""

    steps: list[PlanStep] = field(default_factory=list)
    """步骤列表。"""
    reasoning: str = ""
    """规划推理过程。"""
