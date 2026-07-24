"""
MCPServerConfig——MCP Server 连接配置。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MCPServerConfig:
    """
    MCP Server 连接配置。

    定义 MCP 服务器的连接方式，支持 stdio（子进程）和 sse（HTTP）两种传输协议。

    Attributes:
        name: Server 标识，也用于 tool 名前缀（mcp_{name}_{tool}）。
        transport: 传输协议类型，"stdio" 或 "sse"。
        command: stdio 模式下启动子进程的命令。
        args: stdio 模式下的命令行参数。
        env: stdio 模式下的环境变量覆盖。
        url: sse 模式下的 HTTP 端点 URL。
        auto_connect: Runtime 启动时是否自动连接此 Server。
    """

    name: str
    """Server 标识，也用于 tool 名前缀。"""

    transport: str
    """传输协议："stdio" | "sse"。"""

    command: str = ""
    """stdio: 启动子进程的命令。"""

    args: list[str] = field(default_factory=list)
    """stdio: 命令行参数。"""

    env: dict[str, str] = field(default_factory=dict)
    """stdio: 环境变量覆盖。"""

    url: str = ""
    """sse: HTTP SSE 端点 URL。"""

    auto_connect: bool = True
    """Runtime 启动时是否自动连接。"""
