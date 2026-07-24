"""
MCP 集成测试 —— 连接真实的 mock MCP Server 进程。

使用 tests/mcp_mock_server.py 作为子进程，测试完整的 stdio 协议交互：
  connect → initialize → list_tools → call_tool → disconnect
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from src.tools._mcp import MCPClient, MCPServerConfig, MCPServerManager


@pytest.mark.asyncio
async def test_mcp_client_real_stdio_connect_and_list() -> None:
    """
    集成测试：connect_stdio → initialize → list_tools。

    启动 mcp_mock_server.py 子进程，验证：
      - 连接成功（is_connected=True）
      - 发现工具列表正确（2 个工具：echo, add）
      - 工具元信息完整
    """
    server_script = str(Path(__file__).parent / "mcp_mock_server.py")
    client = MCPClient()
    try:
        await client.connect_stdio(
            command=sys.executable,
            args=[server_script],
        )
        assert client.is_connected is True

        tools = await client.list_tools()
        assert len(tools) == 2

        tool_names = {t["name"] for t in tools}
        assert tool_names == {"echo", "add"}

        # 验证工具结构
        echo_tool = next(t for t in tools if t["name"] == "echo")
        assert "description" in echo_tool
        assert "inputSchema" in echo_tool
        assert "message" in echo_tool["inputSchema"]["properties"]
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_mcp_client_real_stdio_call_echo() -> None:
    """
    集成测试：call_tool 调用 echo 工具。

    验证：
      - call_tool 正确传递参数
      - 返回结果格式正确
    """
    server_script = str(Path(__file__).parent / "mcp_mock_server.py")
    client = MCPClient()
    try:
        await client.connect_stdio(
            command=sys.executable,
            args=[server_script],
        )
        result = await client.call_tool("echo", {"message": "Hello MCP"})
        assert result is not None
        # MCP 返回格式：列表内含 {"type": "text", "text": "..."}
        if isinstance(result, list):
            text = result[0].get("text", "")
        else:
            text = str(result)
        assert "Hello MCP" in text
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_mcp_client_real_stdio_call_add() -> None:
    """
    集成测试：call_tool 调用 add 工具。

    验证：
      - 参数正确传递
      - 加法结果正确
    """
    server_script = str(Path(__file__).parent / "mcp_mock_server.py")
    client = MCPClient()
    try:
        await client.connect_stdio(
            command=sys.executable,
            args=[server_script],
        )
        result = await client.call_tool("add", {"a": 3, "b": 4})

        text = result[0].get("text", "") if isinstance(result, list) else str(result)
        assert text == "7"
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_mcp_client_real_stdio_twice() -> None:
    """
    集成测试：连续两次 call_tool 调用。

    验证：
      - 同一连接可复用
      - request_id 递增
    """
    server_script = str(Path(__file__).parent / "mcp_mock_server.py")
    client = MCPClient()
    try:
        await client.connect_stdio(
            command=sys.executable,
            args=[server_script],
        )

        # 第一次调用
        r1 = await client.call_tool("echo", {"message": "first"})
        t1 = r1[0].get("text", "") if isinstance(r1, list) else str(r1)
        assert "first" in t1

        # 第二次调用
        r2 = await client.call_tool("add", {"a": 10, "b": 20})
        t2 = r2[0].get("text", "") if isinstance(r2, list) else str(r2)
        assert t2 == "30"
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_mcp_manager_real_stdio_connect() -> None:
    """
    集成测试：MCPServerManager 通过真实子进程连接。

    验证：
      - connect 返回 ToolSpec 列表
      - ToolSpec 名称格式为 mcp_{server}_{tool}
      - get_all_tools 返回正确数量
      - execute 通过 adapter 调用成功
    """
    server_script = str(Path(__file__).parent / "mcp_mock_server.py")
    manager = MCPServerManager()

    config = MCPServerConfig(
        name="mock",
        transport="stdio",
        command=sys.executable,
        args=[server_script],
    )
    tools = await manager.connect(config)
    assert len(tools) == 2

    # 验证工具名称格式
    names = {t.name for t in tools}
    assert names == {"mcp_mock_echo", "mcp_mock_add"}

    # 验证描述前缀
    assert all("[MCP:mock]" in t.description for t in tools)

    # 验证 get_all_tools
    all_tools = manager.get_all_tools()
    assert len(all_tools) == 2

    # 验证 execute
    result = await manager.execute("mcp_mock_add", a=5, b=7)
    assert result == "12"

    result2 = await manager.execute("mcp_mock_echo", message="test")
    assert "test" in result2

    # 验证连接状态
    assert manager.is_connected("mock") is True
    assert manager.connected_servers == ["mock"]
    assert len(manager) == 1

    # 断开
    await manager.disconnect("mock")
    assert manager.is_connected("mock") is False
    assert len(manager) == 0


@pytest.mark.asyncio
async def test_mcp_adapter_real_execute() -> None:
    """
    集成测试：MCPToolAdapter 通过真实连接执行。

    验证 adapter._execute 正确将 kwargs 传递给 MCP Server 的 call_tool。
    """
    from src.tools._mcp._adapter import MCPToolAdapter

    server_script = str(Path(__file__).parent / "mcp_mock_server.py")
    client = MCPClient()
    try:
        await client.connect_stdio(
            command=sys.executable,
            args=[server_script],
        )

        adapter = MCPToolAdapter(
            client=client,
            server_name="mock",
            tool_name="echo",
            mcp_description="回显",
            mcp_input_schema={
                "properties": {"message": {"type": "string"}},
            },
        )

        spec = adapter.tool_spec
        assert spec.name == "mcp_mock_echo"

        # 真实执行
        result = await adapter._execute(message="adapter test")
        assert "adapter test" in result
    finally:
        await client.disconnect()
