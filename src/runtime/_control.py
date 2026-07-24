"""
RuntimeController——Runtime 的受控接口。

StepRunner 和 LoopStrategy 通过此接口访问 Runtime 状态，
不再直接访问 AgentRuntime 私有字段或通过 services["_runtime"] 后门。

使用方式：
    controller = RuntimeController(runtime)
    controller.step_index += 1
    ctx = controller.build_context()
"""

from __future__ import annotations

from typing import Any

from src.runtime._types import PauseAction
from src.runtime.context._context import RuntimeContext
from src.runtime.context._payload import ContextPayload
from src.runtime.context._serializer import MessageSerializer
from src.runtime.hooks._registry import HookRegistry
from src.runtime.llm._models import LLMResponse


class RuntimeController:
    """
    Runtime 的受控接口——包装 AgentRuntime，只暴露 StepRunner 和
    LoopStrategy 需要的属性和方法。

    替代之前的 services["_runtime"] 后门模式。
    """

    def __init__(self, runtime: Any) -> None:
        """
        初始化 RuntimeController。

        Args:
            runtime: AgentRuntime 实例。通过 Any 避免循环导入。
        """
        self._runtime = runtime

    # ── 状态属性 ──

    @property
    def status(self) -> str:
        """Runtime 状态。"""
        return self._runtime.status

    @status.setter
    def status(self, value: str) -> None:
        self._runtime.status = value

    @property
    def step_index(self) -> int:
        """当前 step 序号。"""
        return self._runtime._step_index

    @step_index.setter
    def step_index(self, value: int) -> None:
        self._runtime._step_index = value

    @property
    def timeout(self) -> dict:
        """超时控制字典。"""
        return self._runtime._timeout

    @property
    def budget(self) -> Any:
        """预算状态。"""
        return self._runtime._budget

    @property
    def step_history(self) -> list[dict]:
        """步骤历史列表。"""
        return self._runtime._step_history

    @property
    def plan(self) -> dict | None:
        """执行计划。"""
        return self._runtime._plan

    @plan.setter
    def plan(self, value: dict | None) -> None:
        self._runtime._plan = value

    @property
    def context_payload(self) -> ContextPayload:
        """上下文负载。"""
        return self._runtime._context_payload

    @property
    def messages(self) -> list[dict]:
        """消息列表。"""
        return self._runtime._messages

    @messages.setter
    def messages(self, value: list[dict]) -> None:
        self._runtime._messages = value

    @property
    def hooks(self) -> HookRegistry:
        """Hook 注册中心。"""
        return self._runtime._hooks

    @property
    def serializer(self) -> MessageSerializer:
        """消息序列化器。"""
        return self._runtime._serializer

    @property
    def last_llm_response(self) -> LLMResponse | None:
        """最后一次 LLM 响应。"""
        return self._runtime._last_llm_response

    @last_llm_response.setter
    def last_llm_response(self, value: LLMResponse | None) -> None:
        self._runtime._last_llm_response = value

    # ── 方法 ──

    def build_context(self) -> RuntimeContext:
        """构建当前 step 的 RuntimeContext 快照。"""
        return self._runtime._build_context()

    async def handle_pause(self, action: PauseAction) -> None:
        """处理暂停请求。"""
        await self._runtime._handle_pause(action)

    def legacy_to_llm_response(self, raw: Any) -> LLMResponse:
        """将旧接口返回值包装为 LLMResponse。"""
        return self._runtime._legacy_to_llm_response(raw)

    def append_llm_response(self, response: LLMResponse) -> None:
        """将 LLMResponse 追加到消息列表。"""
        self._runtime._append_llm_response(response)

    def llm_response_to_dict(self, response: LLMResponse) -> dict:
        """将 LLMResponse 转换为 messages 可用的 dict 格式。"""
        return self._runtime._llm_response_to_dict(response)
