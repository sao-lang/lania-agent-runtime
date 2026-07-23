"""
ToolDispatcher——三种原语的统一调度入口。

当前版本仅实现了 Tool 原语的路由（路由到 ToolRegistry），
MCP 前缀路由（mcp_）留作占位，将在后续迭代中实现。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from src.tools._registry import ToolRegistry
from src.tools._spec import ToolSpec

if TYPE_CHECKING:
    from src.runtime.context._context import RuntimeContext


class ToolDispatcher:
    """
    三种原语的统一调度入口。

    LLM 调用 tool 时，按 name 前缀路由到不同后端。
    当前仅实现本地 ToolRegistry 路由，MCP 路由为占位。

    路由规则:
      - "mcp_{server}_{tool}" → MCP（待实现）
      - 其他 → ToolRegistry

    Usage:
        >>> dispatcher = ToolDispatcher(tool_registry=registry)
        >>> all_tools = dispatcher.all_tools()
        >>> result = await dispatcher.dispatch(ctx)
    """

    def __init__(
        self,
        tool_registry: ToolRegistry,
    ) -> None:
        """
        初始化统一调度器。

        Args:
            tool_registry: ToolRegistry 实例。
        """
        self._tools: ToolRegistry = tool_registry

    def all_tools(self) -> list[ToolSpec]:
        """
        合并所有来源的工具描述列表。

        当前仅返回 ToolRegistry 中的工具。
        后续迭代将合并 MCP 工具。

        Returns:
            ToolSpec 列表。
        """
        return self._tools.list_specs()

    async def dispatch(self, ctx: "RuntimeContext") -> Any:
        """
        统一分派——从 RuntimeContext 中提取 tool_call 并执行。

        设计为 ExecutorFn 签名（接收 RuntimeContext），
        因此可直接作为 tool_executor 注入 Runtime。

        从 ctx 的最近一条 assistant 消息中提取 tool_calls，
        解析 OpenAI 标准格式（function.name + function.arguments JSON），
        执行工具并返回工具结果消息。

        Args:
            ctx: RuntimeContext 实例。

        Returns:
            工具执行结果消息字典，或 None（无待执行工具时）。
        """
        # 从最近一条 assistant 消息提取 tool_call
        tool_call = self._extract_tool_call(ctx)
        if tool_call is None:
            return None

        # 兼容两种 tool_call 格式：
        #   1. OpenAI 标准格式：name 和 arguments 在 function 嵌套对象中
        #   2. 直接格式：name 和 arguments 在顶层（测试/手动构造场景）
        func = tool_call.get("function", {})
        if func:
            name = func.get("name", "")
            raw_args = func.get("arguments", "{}")
            if isinstance(raw_args, str):
                args = json.loads(raw_args)
            else:
                args = raw_args
        else:
            name = tool_call.get("name", "")
            args = tool_call.get("arguments", {})

        # 路由：按 name 前缀分发
        if name.startswith("mcp_"):
            # TODO: 后续迭代实现 MCP 路由
            # result = await self._dispatch_mcp(name, args)
            result = {"error": f"MCP 工具 '{name}' 暂未实现"}
        else:
            result = await self._tools.execute(name, **args)

        return {
            "role": "tool",
            "tool_call_id": tool_call.get("id", ""),
            "content": str(result),
        }

    @staticmethod
    def _extract_tool_call(ctx: "RuntimeContext") -> dict | None:
        """
        从 RuntimeContext 的消息中提取最后一个待处理的 tool_call。

        按 role="assistant" 且包含 tool_calls 字段的消息反向查找，
        返回第一个 tool_call 条目。

        Args:
            ctx: RuntimeContext 实例。

        Returns:
            tool_call 字典（OpenAI 标准格式），或 None。
        """
        messages = ctx.messages
        for msg in reversed(messages):
            if msg.get("role") == "assistant" and "tool_calls" in msg:
                tool_calls = msg["tool_calls"]
                if tool_calls and len(tool_calls) > 0:
                    return tool_calls[0]
        return None
