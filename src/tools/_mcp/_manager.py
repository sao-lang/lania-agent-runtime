"""
MCPServerManager——MCP Server 生命周期管理器。

管理多个 MCP Server 的连接、工具发现、断开等生命周期操作。
连接失败采用 graceful 策略（记录日志不崩溃）。
"""

from __future__ import annotations

import logging
from typing import Any

from src.tools._mcp._adapter import MCPToolAdapter
from src.tools._mcp._client import MCPClient
from src.tools._mcp._config import MCPServerConfig
from src.tools._spec import ToolSpec

logger = logging.getLogger(__name__)


class MCPServerManager:
    """
    MCP Server 生命周期管理器。

    职责:
      - 管理多个 MCP Server 的连接和断开
      - 将 MCP 工具自动适配为 ToolSpec
      - 采用 graceful 策略：连接失败只记日志，不影响整体运行

    Usage:
        manager = MCPServerManager()
        tools = await manager.connect(config)
        all_tools = manager.get_all_tools()
        result = await manager.execute("mcp_fs_read_file", path="/tmp/test.txt")
        await manager.disconnect_all()
    """

    def __init__(self) -> None:
        """初始化 MCP Server 管理器。"""
        self._clients: dict[str, MCPClient] = {}
        self._adapters: dict[str, MCPToolAdapter] = {}
        self._tool_map: dict[str, str] = {}
        """tool_name → server_name 的映射，用于路由。"""

    async def connect(self, config: MCPServerConfig) -> list[ToolSpec]:
        """
        连接 MCP Server，返回其暴露的所有工具（已适配为 ToolSpec）。

        连接失败只记日志，不影响 Runtime 启动（graceful 策略）。

        Args:
            config: MCPServerConfig 实例。

        Returns:
            适配后的 ToolSpec 列表，连接失败返回空列表。
        """
        if config.name in self._clients:
            logger.warning("MCP Server '%s' 已连接，跳过重复连接", config.name)
            return self._get_server_tools(config.name)

        client = MCPClient()

        try:
            if config.transport == "stdio":
                await client.connect_stdio(
                    command=config.command,
                    args=config.args,
                    env=config.env if config.env else None,
                )
            elif config.transport == "sse":
                await client.connect_sse(config.url)
            else:
                raise ValueError(f"不支持的传输类型: {config.transport}")

            # 发现工具
            raw_tools = await client.list_tools()
            specs: list[ToolSpec] = []

            for raw_tool in raw_tools:
                tool_name = raw_tool.get("name", "")
                if not tool_name:
                    continue

                adapter = MCPToolAdapter(
                    client=client,
                    server_name=config.name,
                    tool_name=tool_name,
                    mcp_description=raw_tool.get("description", ""),
                    mcp_input_schema=raw_tool.get("inputSchema", {}),
                )

                prefixed_name = f"mcp_{config.name}_{tool_name}"
                self._adapters[prefixed_name] = adapter
                self._tool_map[prefixed_name] = config.name
                specs.append(adapter.tool_spec)

            self._clients[config.name] = client
            logger.info(
                "MCP Server '%s' 已连接，发现 %d 个工具", config.name, len(specs),
            )
            return specs

        except Exception as e:
            logger.error(
                "连接 MCP Server '%s' 失败: %s", config.name, e,
                exc_info=True,
            )
            # graceful：连接失败时关闭 client 资源
            await client.disconnect()
            return []

    async def disconnect(self, name: str) -> None:
        """
        断开指定 Server 的连接。

        Args:
            name: Server 名称。
        """
        client = self._clients.pop(name, None)
        if client is None:
            logger.warning("MCP Server '%s' 未连接或已断开", name)
            return

        await client.disconnect()

        # 清理该 Server 的适配器
        prefix = f"mcp_{name}_"
        keys_to_remove = [k for k in self._adapters if k.startswith(prefix)]
        for k in keys_to_remove:
            del self._adapters[k]
            self._tool_map.pop(k, None)

        logger.info("MCP Server '%s' 已断开", name)

    async def disconnect_all(self) -> None:
        """断开所有已连接的 Server。"""
        names = list(self._clients.keys())
        for name in names:
            await self.disconnect(name)
        self._adapters.clear()
        self._tool_map.clear()

    def get_all_tools(self) -> list[ToolSpec]:
        """
        获取所有已连接 Server 的工具列表。

        Returns:
            所有已适配的 ToolSpec 列表。
        """
        return [adapter.tool_spec for adapter in self._adapters.values()]

    def get_tool_adapter(self, prefixed_name: str) -> MCPToolAdapter | None:
        """
        按带前缀的工具名获取适配器。

        Args:
            prefixed_name: 带 mcp_ 前缀的工具名。

        Returns:
            MCPToolAdapter 实例，未找到时返回 None。
        """
        return self._adapters.get(prefixed_name)

    async def execute(self, prefixed_name: str, **kwargs: Any) -> Any:
        """
        执行一个 MCP 工具。

        Args:
            prefixed_name: 带 mcp_ 前缀的工具名。
            kwargs: 工具参数。

        Returns:
            工具执行结果。

        Raises:
            KeyError: 工具未找到时抛出。
        """
        adapter = self._adapters.get(prefixed_name)
        if adapter is None:
            raise KeyError(f"MCP 工具 '{prefixed_name}' 未找到")
        return await adapter._execute(**kwargs)

    def is_connected(self, name: str) -> bool:
        """
        检查指定 Server 是否已连接。

        Args:
            name: Server 名称。

        Returns:
            已连接返回 True。
        """
        return name in self._clients and self._clients[name].is_connected

    @property
    def connected_servers(self) -> list[str]:
        """返回所有已连接的 Server 名称列表。"""
        return list(self._clients.keys())

    def __len__(self) -> int:
        """返回已连接的 Server 数量。"""
        return len(self._clients)

    def _get_server_tools(self, server_name: str) -> list[ToolSpec]:
        """获取指定 Server 的所有工具。"""
        prefix = f"mcp_{server_name}_"
        return [
            adapter.tool_spec
            for key, adapter in self._adapters.items()
            if key.startswith(prefix)
        ]
