"""
MCP 原语包——通过 Model Context Protocol 连接外部进程的工具集。

提供 MCP Server 的连接配置、协议客户端、工具适配和生命周期管理。
"""

from src.tools._mcp._adapter import MCPToolAdapter
from src.tools._mcp._client import MCPClient
from src.tools._mcp._config import MCPServerConfig
from src.tools._mcp._manager import MCPServerManager

__all__ = [
    "MCPServerConfig",
    "MCPClient",
    "MCPToolAdapter",
    "MCPServerManager",
]

