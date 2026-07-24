"""
MCPClient——MCP 协议客户端。

支持 stdio（子进程 stdin/stdout）和 sse（HTTP SSE）两种传输方式。
实现 JSON-RPC 2.0 协议，提供 initialize、tools/list、tools/call 三个核心方法。
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class MCPClient:
    """
    MCP 协议客户端。

    通过 JSON-RPC 2.0 与 MCP Server 通信，支持 stdio 和 sse 两种传输。
    管理连接生命周期：connect → initialize → (list_tools / call_tool) → disconnect。

    Usage:
        client = MCPClient()
        await client.connect_stdio("npx", ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"])
        tools = await client.list_tools()
        result = await client.call_tool("read_file", {"path": "/tmp/test.txt"})
        await client.disconnect()
    """

    def __init__(self) -> None:
        """初始化 MCP 客户端。"""
        self._process: Any = None  # asyncio.subprocess.Process
        self._reader: Any = None  # 用于读取子进程 stdout
        self._writer: Any = None  # 用于写入子进程 stdin
        self._connected: bool = False
        self._request_id: int = 0

    # ============ 连接管理 ============

    async def connect_stdio(
        self,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        """
        通过 stdio 连接到 MCP Server（启动子进程）。

        Args:
            command: 启动命令。
            args: 命令行参数。
            env: 环境变量覆盖。

        Raises:
            RuntimeError: 连接失败时抛出。
        """
        import asyncio

        try:
            merged_env = None
            if env:
                merged_env = dict(__import__("os").environ)
                merged_env.update(env)

            self._process = await asyncio.create_subprocess_exec(
                command,
                *(args or []),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=merged_env,
            )

            self._writer = self._process.stdin
            self._reader = self._process.stdout
            self._connected = True

            # 发送初始化请求
            init_result = await self._send_request("initialize", {
                "protocolVersion": "0.1.0",
                "capabilities": {},
                "clientInfo": {
                    "name": "lania-agent-runtime",
                    "version": "0.1.0",
                },
            })
            logger.info("MCP Client 已连接（stdio），初始化结果: %s", init_result)
        except Exception as e:
            raise RuntimeError(f"MCP stdio 连接失败: {e}") from e

    async def connect_sse(self, url: str) -> None:
        """
        通过 SSE 连接到 MCP Server。

        Args:
            url: SSE 端点 URL。

        Raises:
            RuntimeError: 连接失败时抛出。
        """
        try:
            import httpx

            self._sse_url = url
            self._http_client = httpx.AsyncClient(timeout=30.0)
            self._connected = True

            # 发送初始化请求
            init_result = await self._send_request("initialize", {
                "protocolVersion": "0.1.0",
                "capabilities": {},
                "clientInfo": {
                    "name": "lania-agent-runtime",
                    "version": "0.1.0",
                },
            })
            logger.info("MCP Client 已连接（SSE），初始化结果: %s", init_result)
        except Exception as e:
            raise RuntimeError(f"MCP SSE 连接失败: {e}") from e

    async def disconnect(self) -> None:
        """
        断开连接，清理资源。

        终止子进程（stdio）或关闭 HTTP 会话（sse）。
        """
        self._connected = False

        # 关闭子进程
        if self._process is not None:
            try:
                self._process.terminate()
                import asyncio

                try:
                    await asyncio.wait_for(self._process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    self._process.kill()
                    await self._process.wait()
            except Exception as e:
                logger.warning("MCP 子进程关闭异常: %s", e)
            self._process = None
            self._writer = None
            self._reader = None

        # 关闭 HTTP 客户端
        if hasattr(self, "_http_client") and self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

        logger.info("MCP Client 已断开")

    @property
    def is_connected(self) -> bool:
        """检查是否已连接。"""
        return self._connected

    # ============ MCP 协议方法 ============

    async def list_tools(self) -> list[dict]:
        """
        获取 Server 提供的工具列表。

        Returns:
            工具描述字典列表，每项包含 name、description、inputSchema 等字段。
        """
        result = await self._send_request("tools/list", {})
        return result.get("tools", [])

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """
        调用 Server 上的工具。

        Args:
            tool_name: 工具名称。
            arguments: 工具参数。

        Returns:
            工具执行结果（CallToolResult 的 content 字段）。
        """
        result = await self._send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        })
        # 提取 content 字段，兼容 MCP 协议格式
        content = result.get("content", "")
        is_error = result.get("isError", False)
        if is_error:
            error_content = (
                content[0].get("text", str(content))
                if isinstance(content, list) else str(content)
            )
            raise RuntimeError(f"MCP 工具 '{tool_name}' 执行错误: {error_content}")
        return content

    # ============ 内部方法 ============

    async def _send_request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """
        发送 JSON-RPC 请求并等待响应。

        Args:
            method: JSON-RPC 方法名。
            params: 请求参数。

        Returns:
            响应结果字典。

        Raises:
            RuntimeError: 请求失败或返回错误时抛出。
        """
        if not self._connected:
            raise RuntimeError("MCP Client 未连接")

        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }

        if self._process is not None:
            return await self._send_via_stdio(request)
        elif hasattr(self, "_http_client") and self._http_client is not None:
            return await self._send_via_sse(request)
        else:
            raise RuntimeError("MCP Client 无可用传输通道")

    async def _send_via_stdio(self, request: dict) -> dict:
        """
        通过 stdio 发送 JSON-RPC 请求。

        Args:
            request: JSON-RPC 请求字典。

        Returns:
            响应结果字典。
        """
        import asyncio

        if self._writer is None or self._reader is None:
            raise RuntimeError("stdio 管道未初始化")

        # 发送请求（JSON 行尾加换行）
        raw_request = json.dumps(request, ensure_ascii=False) + "\n"
        self._writer.write(raw_request.encode("utf-8"))
        await self._writer.drain()

        # 读取响应（逐行读取 JSON）
        async def read_line() -> str:
            data = b""
            while True:
                chunk = await self._reader.read(1)
                if not chunk:
                    break
                if chunk == b"\n":
                    break
                data += chunk
            # 尝试 UTF-8 解码（含 BOM 处理），失败时使用 latin-1 兜底
            try:
                return data.decode("utf-8-sig")
            except UnicodeDecodeError:
                return data.decode("latin-1")

        try:
            line = await asyncio.wait_for(read_line(), timeout=30.0)
            if not line:
                raise RuntimeError("MCP stdio 无响应数据")
            response = json.loads(line)
        except asyncio.TimeoutError:
            raise RuntimeError("MCP stdio 响应超时") from None

        if "error" in response:
            err = response["error"]
            err_msg = f"MCP 请求错误 [{err.get('code', -1)}]: {err.get('message', '未知错误')}"
            raise RuntimeError(err_msg)

        return response.get("result", {})

    async def _send_via_sse(self, request: dict) -> dict:
        """
        通过 SSE（HTTP POST）发送 JSON-RPC 请求。

        Args:
            request: JSON-RPC 请求字典。

        Returns:
            响应结果字典。
        """
        try:
            response = await self._http_client.post(
                self._sse_url,
                json=request,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            data = response.json()

            if "error" in data:
                err = data["error"]
                err_msg = f"MCP 请求错误 [{err.get('code', -1)}]: {err.get('message', '未知错误')}"
                raise RuntimeError(err_msg)

            return data.get("result", {})
        except Exception as e:
            if not isinstance(e, RuntimeError):
                raise RuntimeError(f"MCP SSE 请求失败: {e}") from e
            raise
