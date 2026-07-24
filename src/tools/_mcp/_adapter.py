"""
MCPToolAdapter——将 MCP Server 的工具适配为 ToolSpec。
"""

from __future__ import annotations

from typing import Any

from src.tools._mcp._client import MCPClient
from src.tools._spec import ToolSpec


class MCPToolAdapter:
    """
    将 MCP Server 的一个 tool 适配为 ToolSpec。

    name 格式: mcp_{server_name}_{tool_name}
    保证全局唯一，方便 LLM 区分工具来源，也便于 ToolDispatcher 按前缀路由。

    Attributes:
        server_name: MCP Server 名称。
        tool_name: MCP 工具名称。
    """

    def __init__(
        self,
        client: MCPClient,
        server_name: str,
        tool_name: str,
        mcp_description: str,
        mcp_input_schema: dict[str, Any],
        timeout: float = 30.0,
    ) -> None:
        """
        初始化适配器。

        Args:
            client: MCPClient 实例，用于远程调用。
            server_name: Server 名称。
            tool_name: MCP 工具名称。
            mcp_description: MCP 工具描述。
            mcp_input_schema: MCP 工具输入 JSON Schema。
            timeout: 执行超时秒数。
        """
        self._client: MCPClient = client
        self._server_name: str = server_name
        self._tool_name: str = tool_name
        self._mcp_description: str = mcp_description
        self._mcp_input_schema: dict[str, Any] = mcp_input_schema
        self._timeout: float = timeout

    @property
    def mcp_tool_name(self) -> str:
        """获取原始的 MCP 工具名称（不含前缀）。"""
        return self._tool_name

    @property
    def tool_spec(self) -> ToolSpec:
        """
        获取适配后的 ToolSpec。

        name 格式为 mcp_{server}_{tool}，handler 通过 MCP Client 远程调用。

        Returns:
            ToolSpec 实例。
        """
        return ToolSpec(
            name=f"mcp_{self._server_name}_{self._tool_name}",
            description=f"[MCP:{self._server_name}] {self._mcp_description}",
            parameters=self._mcp_input_schema,
            handler=self._execute,
            timeout=self._timeout,
        )

    async def _execute(self, **kwargs: Any) -> Any:
        """
        通过 MCP Client 远程调用工具。

        Args:
            kwargs: 工具参数。

        Returns:
            MCP 工具执行结果。
        """
        result = await self._client.call_tool(self._tool_name, kwargs)
        return self._parse_result(result)

    @staticmethod
    def _parse_result(result: Any) -> Any:
        """
        解析 MCP CallToolResult 的 content 为可读字符串。

        MCP 返回的 content 通常是一个列表：
            [{"type": "text", "text": "结果内容"}, ...]
        如果是非列表格式，直接返回原始结果。

        Args:
            result: MCP 工具调用结果。

        Returns:
            解析后的可读结果。
        """
        if isinstance(result, list):
            if not result:
                return ""
            texts: list[str] = []
            for item in result:
                if isinstance(item, dict):
                    text = item.get("text", "")
                    if text:
                        texts.append(text)
            return "\n".join(texts) if texts else str(result)
        return str(result)
