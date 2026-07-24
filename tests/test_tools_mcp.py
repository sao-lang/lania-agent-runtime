"""
测试 MCP 原语：MCPServerConfig、MCPClient、MCPToolAdapter、MCPServerManager。
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.tools._mcp import MCPClient, MCPServerConfig, MCPServerManager, MCPToolAdapter
from src.tools._spec import ToolSpec


# ============ Test MCPServerConfig ============


class TestMCPServerConfig:
    """测试 MCPServerConfig 数据类。"""

    def test_stdio_config(self) -> None:
        config = MCPServerConfig(
            name="fs",
            transport="stdio",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
        )
        assert config.name == "fs"
        assert config.transport == "stdio"
        assert config.command == "npx"
        assert len(config.args) == 3
        assert config.auto_connect is True

    def test_sse_config(self) -> None:
        config = MCPServerConfig(
            name="remote",
            transport="sse",
            url="http://localhost:8080/mcp",
            auto_connect=False,
        )
        assert config.transport == "sse"
        assert config.url == "http://localhost:8080/mcp"
        assert config.auto_connect is False

    def test_default_values(self) -> None:
        config = MCPServerConfig(name="test", transport="stdio")
        assert config.args == []
        assert config.env == {}
        assert config.url == ""
        assert config.auto_connect is True


# ============ Test MCPToolAdapter ============


class TestMCPToolAdapter:
    """测试 MCPToolAdapter——将 MCP tool 适配为 ToolSpec。"""

    @pytest.mark.asyncio
    async def test_tool_spec_creation(self) -> None:
        client = MCPClient()
        adapter = MCPToolAdapter(
            client=client,
            server_name="fs",
            tool_name="read_file",
            mcp_description="Read a file from the filesystem",
            mcp_input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"},
                },
                "required": ["path"],
            },
        )

        spec = adapter.tool_spec
        assert isinstance(spec, ToolSpec)
        assert spec.name == "mcp_fs_read_file"
        assert "[MCP:fs]" in spec.description
        assert "Read a file" in spec.description
        assert "path" in spec.parameters.get("properties", {})

    @pytest.mark.asyncio
    async def test_tool_spec_openai_schema(self) -> None:
        client = MCPClient()
        adapter = MCPToolAdapter(
            client=client,
            server_name="github",
            tool_name="get_pr",
            mcp_description="Get PR details",
            mcp_input_schema={"properties": {"pr": {"type": "integer"}}},
        )

        schema = adapter.tool_spec.to_openai_schema()
        assert schema["function"]["name"] == "mcp_github_get_pr"
        assert "MCP:github" in schema["function"]["description"]

    def test_mcp_tool_name(self) -> None:
        client = MCPClient()
        adapter = MCPToolAdapter(
            client=client,
            server_name="test",
            tool_name="my_tool",
            mcp_description="",
            mcp_input_schema={},
        )
        assert adapter.mcp_tool_name == "my_tool"

    @pytest.mark.asyncio
    async def test_parse_result_list(self) -> None:
        result = [
            {"type": "text", "text": "Hello"},
            {"type": "text", "text": "World"},
        ]
        parsed = MCPToolAdapter._parse_result(result)
        assert parsed == "Hello\nWorld"

    @pytest.mark.asyncio
    async def test_parse_result_single_text(self) -> None:
        result = [{"type": "text", "text": "Single result"}]
        parsed = MCPToolAdapter._parse_result(result)
        assert parsed == "Single result"

    @pytest.mark.asyncio
    async def test_parse_result_non_list(self) -> None:
        result = "plain string result"
        parsed = MCPToolAdapter._parse_result(result)
        assert parsed == "plain string result"

    @pytest.mark.asyncio
    async def test_parse_result_empty_list(self) -> None:
        parsed = MCPToolAdapter._parse_result([])
        assert parsed == ""


# ============ Test MCPServerManager ============


class TestMCPServerManager:
    """测试 MCPServerManager 生命周期管理。"""

    @pytest.mark.asyncio
    async def test_initial_state(self) -> None:
        manager = MCPServerManager()
        assert len(manager) == 0
        assert manager.connected_servers == []
        assert manager.get_all_tools() == []

    @pytest.mark.asyncio
    async def test_connect_failure_graceful(self) -> None:
        """连接失败应 graceful 处理，不抛异常。"""
        manager = MCPServerManager()
        config = MCPServerConfig(
            name="nonexistent",
            transport="stdio",
            command="nonexistent_command_xyz",
        )
        tools = await manager.connect(config)
        assert tools == []  # graceful: 返回空列表
        assert len(manager) == 0  # 未注册

    @pytest.mark.asyncio
    async def test_get_all_tools_empty(self) -> None:
        manager = MCPServerManager()
        assert manager.get_all_tools() == []

    @pytest.mark.asyncio
    async def test_is_connected_not_connected(self) -> None:
        manager = MCPServerManager()
        assert manager.is_connected("nonexistent") is False

    @pytest.mark.asyncio
    async def test_get_tool_adapter_not_found(self) -> None:
        manager = MCPServerManager()
        assert manager.get_tool_adapter("mcp_nonexistent_tool") is None

    @pytest.mark.asyncio
    async def test_execute_not_found(self) -> None:
        manager = MCPServerManager()
        with pytest.raises(KeyError, match="未找到"):
            await manager.execute("mcp_nonexistent_tool")

    @pytest.mark.asyncio
    async def test_disconnect_not_connected(self) -> None:
        """断开未连接的 Server 不应抛异常。"""
        manager = MCPServerManager()
        await manager.disconnect("nonexistent")  # 不抛异常

    @pytest.mark.asyncio
    async def test_disconnect_all_empty(self) -> None:
        manager = MCPServerManager()
        await manager.disconnect_all()  # 不抛异常


# ============ Test MCPClient ============


class TestMCPClient:
    """测试 MCPClient 的基础行为。"""

    @pytest.mark.asyncio
    async def test_initial_state(self) -> None:
        client = MCPClient()
        assert client.is_connected is False

    @pytest.mark.asyncio
    async def test_list_tools_not_connected(self) -> None:
        client = MCPClient()
        with pytest.raises(RuntimeError, match="未连接"):
            await client.list_tools()

    @pytest.mark.asyncio
    async def test_call_tool_not_connected(self) -> None:
        client = MCPClient()
        with pytest.raises(RuntimeError, match="未连接"):
            await client.call_tool("test", {})

    @pytest.mark.asyncio
    async def test_disconnect_not_connected(self) -> None:
        """未连接时断开不抛异常。"""
        client = MCPClient()
        await client.disconnect()  # 不抛异常

    @pytest.mark.asyncio
    async def test_connect_stdio_bad_command(self) -> None:
        """无效命令应抛 RuntimeError。"""
        client = MCPClient()
        with pytest.raises(RuntimeError, match="MCP stdio 连接失败"):
            await client.connect_stdio("nonexistent_cmd_xyz")

    @pytest.mark.asyncio
    async def test_connect_sse_bad_url(self) -> None:
        """无效 URL 应抛 RuntimeError。"""
        client = MCPClient()
        with pytest.raises(RuntimeError, match="MCP SSE 连接失败"):
            await client.connect_sse("http://nonexistent-localhost:1/mcp")

    # ============ Mock-based client tests ============

    @pytest.mark.asyncio
    async def test_list_tools_success_mocked(self) -> None:
        """mock _send_request 测试 list_tools。"""
        client = MCPClient()
        client._connected = True
        client._process = MagicMock()  # 模拟 stdio 传输通道

        with patch.object(client, "_send_request", new=AsyncMock()) as mock_send:
            mock_send.return_value = {
                "tools": [
                    {"name": "read_file", "description": "读文件", "inputSchema": {}},
                ],
            }
            tools = await client.list_tools()
            assert len(tools) == 1
            assert tools[0]["name"] == "read_file"
            mock_send.assert_called_once_with("tools/list", {})

    @pytest.mark.asyncio
    async def test_call_tool_success_mocked(self) -> None:
        """mock _send_request 测试 call_tool 成功。"""
        client = MCPClient()
        client._connected = True
        client._process = MagicMock()

        with patch.object(client, "_send_request", new=AsyncMock()) as mock_send:
            mock_send.return_value = {
                "content": [{"type": "text", "text": "文件内容"}],
                "isError": False,
            }
            result = await client.call_tool("read_file", {"path": "/tmp/test.txt"})
            assert result == [{"type": "text", "text": "文件内容"}]
            mock_send.assert_called_once_with(
                "tools/call",
                {"name": "read_file", "arguments": {"path": "/tmp/test.txt"}},
            )

    @pytest.mark.asyncio
    async def test_call_tool_with_error_mocked(self) -> None:
        """mock _send_request 测试 call_tool 返回 isError。"""
        client = MCPClient()
        client._connected = True
        client._process = MagicMock()

        with patch.object(client, "_send_request", new=AsyncMock()) as mock_send:
            mock_send.return_value = {
                "content": [{"type": "text", "text": "Permission denied"}],
                "isError": True,
            }
            with pytest.raises(RuntimeError, match="执行错误"):
                await client.call_tool("read_file", {"path": "/etc/passwd"})

    @pytest.mark.asyncio
    async def test_send_request_no_transport(self) -> None:
        """已连接但无传输通道应抛错误。"""
        client = MCPClient()
        client._connected = True
        # _process=None 且没有 _http_client
        with pytest.raises(RuntimeError, match="无可用传输通道"):
            await client._send_request("test", {})

    @pytest.mark.asyncio
    async def test_send_via_stdio_timeout(self) -> None:
        """stdio 响应超时。"""
        import asyncio

        client = MCPClient()
        client._connected = True
        client._writer = AsyncMock()
        client._reader = AsyncMock()  # 确保 reader 不为 None

        async def mock_wait_for(coro, timeout):
            raise asyncio.TimeoutError

        with patch("asyncio.wait_for", mock_wait_for):
            with pytest.raises(RuntimeError, match="响应超时"):
                await client._send_via_stdio(
                    {"jsonrpc": "2.0", "id": 1, "method": "test", "params": {}}
                )

    @pytest.mark.asyncio
    async def test_send_via_stdio_json_rpc_error(self) -> None:
        """stdio 返回 JSON-RPC 错误。"""
        client = MCPClient()
        client._connected = True
        client._writer = AsyncMock()
        client._reader = AsyncMock()
        error_response = json.dumps({
            "jsonrpc": "2.0", "id": 1,
            "error": {"code": -32601, "message": "Method not found"},
        })

        # 构造逐字节读取的 mock：返回 JSON + 换行
        data_bytes = error_response.encode("utf-8") + b"\n"
        idx = [0]

        async def byte_by_byte(n: int) -> bytes:
            if idx[0] >= len(data_bytes):
                return b""
            result = data_bytes[idx[0]:idx[0] + 1]
            idx[0] += 1
            return result

        client._reader.read = byte_by_byte  # type: ignore[method-assign]

        with pytest.raises(RuntimeError, match="MCP 请求错误"):
            await client._send_via_stdio(
                {"jsonrpc": "2.0", "id": 1, "method": "nonexistent", "params": {}}
            )

    @pytest.mark.asyncio
    async def test_send_via_sse_json_rpc_error(self) -> None:
        """SSE 返回 JSON-RPC 错误。"""
        import httpx

        client = MCPClient()
        client._connected = True
        client._sse_url = "http://localhost/mcp"
        client._http_client = AsyncMock(spec=httpx.AsyncClient)

        error_response = MagicMock(spec=httpx.Response)
        error_response.status_code = 200
        error_response.json.return_value = {
            "jsonrpc": "2.0", "id": 1,
            "error": {"code": -32601, "message": "Method not found"},
        }
        error_response.raise_for_status = MagicMock()
        client._http_client.post = AsyncMock(return_value=error_response)

        with pytest.raises(RuntimeError, match="MCP 请求错误"):
            await client._send_via_sse(
                {"jsonrpc": "2.0", "id": 1, "method": "test", "params": {}}
            )

    @pytest.mark.asyncio
    async def test_send_via_sse_http_error(self) -> None:
        """SSE HTTP 请求异常。"""
        import httpx

        client = MCPClient()
        client._connected = True
        client._sse_url = "http://localhost/mcp"
        client._http_client = AsyncMock(spec=httpx.AsyncClient)
        client._http_client.post = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "404 Not Found", request=MagicMock(), response=MagicMock()
            )
        )

        with pytest.raises(RuntimeError, match="MCP SSE 请求失败"):
            await client._send_via_sse(
                {"jsonrpc": "2.0", "id": 1, "method": "test", "params": {}}
            )

    @pytest.mark.asyncio
    async def test_disconnect_active_stdio_mocked(self) -> None:
        """断开活跃 stdio 连接。"""
        client = MCPClient()
        process_mock = MagicMock()
        process_mock.terminate = MagicMock()
        process_mock.wait = AsyncMock(return_value=0)
        process_mock.kill = MagicMock()
        client._process = process_mock
        client._writer = MagicMock()
        client._reader = MagicMock()
        client._connected = True

        await client.disconnect()
        assert client.is_connected is False
        assert client._process is None
        process_mock.terminate.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect_timeout_kill(self) -> None:
        """断开时 wait 超时应调用 kill。"""
        import asyncio

        client = MCPClient()
        process_mock = MagicMock()
        process_mock.terminate = MagicMock()
        process_mock.wait = AsyncMock(side_effect=asyncio.TimeoutError)
        process_mock.kill = MagicMock()
        client._process = process_mock
        client._writer = MagicMock()
        client._reader = MagicMock()
        client._connected = True

        await client.disconnect()
        process_mock.terminate.assert_called_once()
        process_mock.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect_active_sse(self) -> None:
        """断开活跃 SSE 连接。"""
        import httpx

        client = MCPClient()
        client._connected = True
        http_client = AsyncMock(spec=httpx.AsyncClient)
        http_client.aclose = AsyncMock()
        client._http_client = http_client

        await client.disconnect()
        assert client.is_connected is False
        http_client.aclose.assert_called_once()


class TestMCPServerManagerMocked:
    """MCPServerManager 的 mock 测试。"""

    @pytest.mark.asyncio
    async def test_connect_stdio_success_mocked(self) -> None:
        """mock client 测试 connect stdio 成功。"""
        manager = MCPServerManager()

        with patch("src.tools._mcp._manager.MCPClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.connect_stdio = AsyncMock()
            mock_client.list_tools = AsyncMock(return_value=[
                {"name": "read_file", "description": "读文件", "inputSchema": {}},
                {"name": "write_file", "description": "写文件", "inputSchema": {}},
            ])
            mock_client.is_connected = True
            mock_client_cls.return_value = mock_client

            config = MCPServerConfig(
                name="test",
                transport="stdio",
                command="echo",
            )
            tools = await manager.connect(config)

            assert len(tools) == 2
            assert tools[0].name == "mcp_test_read_file"
            assert tools[1].name == "mcp_test_write_file"
            assert len(manager) == 1
            assert manager.is_connected("test") is True
            mock_client.connect_stdio.assert_called_once_with(
                command="echo", args=[], env=None,
            )

    @pytest.mark.asyncio
    async def test_connect_sse_success_mocked(self) -> None:
        """mock client 测试 connect sse 成功。"""
        manager = MCPServerManager()

        with patch("src.tools._mcp._manager.MCPClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.connect_sse = AsyncMock()
            mock_client.list_tools = AsyncMock(return_value=[
                {"name": "get_data", "description": "获取数据", "inputSchema": {}},
            ])
            mock_client_cls.return_value = mock_client

            config = MCPServerConfig(
                name="remote",
                transport="sse",
                url="http://localhost:8080/mcp",
            )
            tools = await manager.connect(config)

            assert len(tools) == 1
            assert tools[0].name == "mcp_remote_get_data"
            mock_client.connect_sse.assert_called_once_with("http://localhost:8080/mcp")

    @pytest.mark.asyncio
    async def test_connect_unsupported_transport(self) -> None:
        """不支持的传输类型 graceful 处理。"""
        manager = MCPServerManager()
        config = MCPServerConfig(name="bad", transport="ws")
        tools = await manager.connect(config)
        assert tools == []

    @pytest.mark.asyncio
    async def test_connect_duplicate_skip(self) -> None:
        """重复连接同一 server 应跳过。"""
        manager = MCPServerManager()

        with patch("src.tools._mcp._manager.MCPClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.connect_stdio = AsyncMock()
            mock_client.list_tools = AsyncMock(return_value=[
                {"name": "tool1", "description": "", "inputSchema": {}},
            ])
            mock_client_cls.return_value = mock_client

            config = MCPServerConfig(name="dup", transport="stdio", command="echo")
            tools1 = await manager.connect(config)
            assert len(tools1) == 1

            # 第二次连接同一名称
            tools2 = await manager.connect(config)
            assert len(tools2) == 1
            # connect_stdio 只被调用一次
            mock_client.connect_stdio.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect_active_server_mocked(self) -> None:
        """断开活跃 server 后工具列表应清空。"""
        manager = MCPServerManager()

        with patch("src.tools._mcp._manager.MCPClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.connect_stdio = AsyncMock()
            mock_client.list_tools = AsyncMock(return_value=[
                {"name": "tool1", "description": "", "inputSchema": {}},
            ])
            mock_client.disconnect = AsyncMock()
            mock_client_cls.return_value = mock_client

            config = MCPServerConfig(name="test", transport="stdio", command="echo")
            await manager.connect(config)
            assert len(manager) == 1

            await manager.disconnect("test")
            assert len(manager) == 0
            assert manager.get_tool_adapter("mcp_test_tool1") is None
            mock_client.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_success_mocked(self) -> None:
        """通过 mock 测试 execute。"""
        manager = MCPServerManager()

        with patch("src.tools._mcp._manager.MCPClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.connect_stdio = AsyncMock()
            mock_client.list_tools = AsyncMock(return_value=[
                {"name": "echo", "description": "回声", "inputSchema": {
                    "properties": {"msg": {"type": "string"}},
                }},
            ])
            mock_client.call_tool = AsyncMock(return_value=[{"type": "text", "text": "hello"}])
            mock_client_cls.return_value = mock_client

            config = MCPServerConfig(name="test", transport="stdio", command="echo")
            await manager.connect(config)

            result = await manager.execute("mcp_test_echo", msg="hello")
            assert result == "hello"

    @pytest.mark.asyncio
    async def test_get_all_tools_with_tools_mocked(self) -> None:
        """多个 server 的工具全部返回。"""
        manager = MCPServerManager()

        with patch("src.tools._mcp._manager.MCPClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.connect_stdio = AsyncMock()
            mock_client.list_tools = AsyncMock(return_value=[
                {"name": "t1", "description": "", "inputSchema": {}},
            ])
            mock_client_cls.return_value = mock_client

            await manager.connect(
                MCPServerConfig(name="s1", transport="stdio", command="echo")
            )
            await manager.connect(
                MCPServerConfig(name="s2", transport="stdio", command="echo")
            )

            all_tools = manager.get_all_tools()
            assert len(all_tools) == 2
            names = {t.name for t in all_tools}
            assert names == {"mcp_s1_t1", "mcp_s2_t1"}

    @pytest.mark.asyncio
    async def test_connect_exception_graceful(self) -> None:
        """连接时 client 创建失败也应 graceful。"""
        manager = MCPServerManager()

        with patch("src.tools._mcp._manager.MCPClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.connect_stdio = AsyncMock(side_effect=RuntimeError("连接失败"))
            mock_client.disconnect = AsyncMock()
            mock_client_cls.return_value = mock_client

            config = MCPServerConfig(name="bad", transport="stdio", command="fail")
            tools = await manager.connect(config)
            assert tools == []
            assert len(manager) == 0
            # 失败后应调用 disconnect 清理
            mock_client.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect_all_mocked(self) -> None:
        """断开所有连接。"""
        manager = MCPServerManager()

        with patch("src.tools._mcp._manager.MCPClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.connect_stdio = AsyncMock()
            mock_client.list_tools = AsyncMock(return_value=[
                {"name": "t1", "description": "", "inputSchema": {}},
            ])
            mock_client.disconnect = AsyncMock()
            mock_client_cls.return_value = mock_client

            config = MCPServerConfig(name="s1", transport="stdio", command="echo")
            await manager.connect(config)
            assert len(manager) == 1

            await manager.disconnect_all()
            assert len(manager) == 0
            mock_client.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_connected_servers_property(self) -> None:
        """connected_servers 属性返回名称列表。"""
        manager = MCPServerManager()

        with patch("src.tools._mcp._manager.MCPClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.connect_stdio = AsyncMock()
            mock_client.list_tools = AsyncMock(return_value=[])
            mock_client_cls.return_value = mock_client

            await manager.connect(
                MCPServerConfig(name="s1", transport="stdio", command="echo")
            )
            assert manager.connected_servers == ["s1"]


class TestToolDispatcherMCPIntegration:
    """测试 ToolDispatcher 与 MCP 的集成。"""

    @pytest.mark.asyncio
    async def test_dispatch_mcp_execute_error(self) -> None:
        """MCP 工具执行时抛异常应返回友好错误。"""
        from src.runtime.context._context import RuntimeContext
        from src.tools._dispatcher import ToolDispatcher
        from src.tools._registry import ToolRegistry

        registry = ToolRegistry()
        dispatcher = ToolDispatcher(tool_registry=registry)

        # mock MCPServerManager.execute 使其抛出异常
        with patch.object(dispatcher._mcp, "execute") as mock_exec:
            mock_exec.side_effect = RuntimeError("connection lost")

            ctx = RuntimeContext(
                messages=(
                    {"role": "assistant", "content": "", "tool_calls": [
                        {"id": "c1", "type": "function", "function": {
                            "name": "mcp_test_echo",
                            "arguments": '{"msg": "hello"}',
                        }},
                    ]},
                ),
            )
            result = await dispatcher.dispatch(ctx)
            assert result is not None
            assert "执行错误" in result["content"]
