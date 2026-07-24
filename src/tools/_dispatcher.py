"""
ToolDispatcher——三种原语的统一调度入口。

按 name 前缀路由到不同后端：
  - "mcp_{server}_{tool}" → MCPServerManager
  - 其他 → ToolRegistry
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

from src.tools._mcp._manager import MCPServerManager
from src.tools._registry import ToolRegistry
from src.tools._spec import ToolSpec

if TYPE_CHECKING:
    from src.runtime.context._context import RuntimeContext

logger = logging.getLogger(__name__)


class ToolDispatcher:
    """
    三种原语的统一调度入口。

    LLM 调用 tool 时，按 name 前缀路由到不同后端：
      - "mcp_{server}_{tool}" → MCPServerManager
      - 其他 → ToolRegistry

    Usage:
        >>> dispatcher = ToolDispatcher(tool_registry=registry, mcp_manager=mcp)
        >>> all_tools = dispatcher.all_tools()
        >>> result = await dispatcher.dispatch(ctx)
    """

    def __init__(
        self,
        tool_registry: ToolRegistry,
        mcp_manager: MCPServerManager | None = None,
    ) -> None:
        """
        初始化统一调度器。

        Args:
            tool_registry: ToolRegistry 实例。
            mcp_manager: 可选的 MCPServerManager 实例。
        """
        self._tools: ToolRegistry = tool_registry
        self._mcp: MCPServerManager = mcp_manager or MCPServerManager()

    @property
    def mcp_manager(self) -> MCPServerManager:
        """获取 MCP Server 管理器。"""
        return self._mcp

    def all_tools(self) -> list[ToolSpec]:
        """
        合并所有来源的工具描述列表。

        合并 ToolRegistry 中的本地工具和 MCPServerManager 中的 MCP 工具。

        Returns:
            所有可用工具的 ToolSpec 列表。
        """
        local_tools = self._tools.list_specs()
        mcp_tools = self._mcp.get_all_tools()
        return local_tools + mcp_tools

    async def dispatch(self, ctx: "RuntimeContext") -> Any:
        """
        统一分派——从 RuntimeContext 中提取 tool_call 并执行。

        设计为 ExecutorFn 签名（接收 RuntimeContext），
        因此可直接作为 tool_executor 注入 Runtime。

        从 ctx 的最近一条 assistant 消息中提取 tool_calls，
        解析 OpenAI 标准格式（function.name + function.arguments JSON），
        按 name 前缀路由到对应后端执行。

        Args:
            ctx: RuntimeContext 实例。

        Returns:
            工具执行结果消息字典，或 None（无待执行工具时）。
        """
        # 从最近一条 assistant 消息提取所有待执行的 tool_calls
        tool_calls = self._extract_tool_calls(ctx)
        if not tool_calls:
            return None

        # 并行执行所有 tool_calls
        results = await asyncio.gather(
            *(self._execute_single_tool_call(tc) for tc in tool_calls),
            return_exceptions=True,
        )

        # 返回最后一条结果（兼容单 tool_call 场景的返回值格式）
        # 实际所有结果会通过 _runtime 的 messages 追加写入
        for tc, result in zip(tool_calls, results):
            if isinstance(result, Exception):
                logger.error(
                    "Tool %s failed: %s", tc.get("name", ""), result,
                    exc_info=True,
                )

        # 取最后一条结果作为返回值（旧接口兼容）
        last_result = results[-1] if results else None
        if isinstance(last_result, Exception):
            return {
                "role": "tool",
                "tool_call_id": tool_calls[-1].get("id", ""),
                "content": f"Tool execution error: {last_result}",
            }
        return last_result

    async def _execute_single_tool_call(self, tool_call: dict) -> dict:
        """
        执行单个 tool_call。

        Args:
            tool_call: OpenAI 标准格式的 tool_call 字典。

        Returns:
            工具执行结果消息字典。
        """
        # 兼容两种 tool_call 格式：
        #   1. OpenAI 标准格式：name 和 arguments 在 function 嵌套对象中
        #   2. 直接格式：name 和 arguments 在顶层（测试/手动构造场景）
        func = tool_call.get("function", {})
        if func:
            name = func.get("name", "")
            raw_args = func.get("arguments", "{}")
            if isinstance(raw_args, str):
                if len(raw_args) > 65536:
                    raise ValueError(f"Tool '{name}' 参数过长 ({len(raw_args)} chars)")
                args = json.loads(raw_args)
            else:
                args = raw_args
        else:
            name = tool_call.get("name", "")
            args = tool_call.get("arguments", {})

        # 路由：按 name 前缀分发
        if name.startswith("mcp_"):
            try:
                result = await self._mcp.execute(name, **args)
            except KeyError as e:
                result = f"MCP 工具 '{name}' 未找到: {e}"
            except Exception as e:
                result = f"MCP 工具 '{name}' 执行错误: {e}"
        else:
            result = await self._tools.execute(name, **args)

        return {
            "role": "tool",
            "tool_call_id": tool_call.get("id", ""),
            "content": str(result),
        }

    @staticmethod
    def _extract_tool_calls(ctx: "RuntimeContext") -> list[dict]:
        """
        从 RuntimeContext 的消息中提取所有待处理的 tool_calls。

        按 role="assistant" 且包含 tool_calls 字段的消息反向查找，
        返回所有 tool_call 条目。

        Args:
            ctx: RuntimeContext 实例。

        Returns:
            tool_call 字典列表（OpenAI 标准格式），可能为空。
        """
        messages = ctx.messages
        for msg in reversed(messages):
            if msg.get("role") == "assistant" and "tool_calls" in msg:
                tool_calls = msg["tool_calls"]
                if tool_calls:
                    return tool_calls
        return []
