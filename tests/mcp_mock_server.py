"""
MCP Mock Server —— 模拟 MCP Server 的 stdio 协议交互。

通过 stdin 读取 JSON-RPC 请求，通过 stdout 写入 JSON-RPC 响应。
用于集成测试 MCPClient 的 stdio 传输层。
"""

from __future__ import annotations

import json
import sys


def main() -> None:
    """主循环：逐行读取 JSON-RPC 请求，返回预设响应。"""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue

        request_id = request.get("id", 0)
        method = request.get("method", "")
        request_id = request.get("id", 0)

        if method == "initialize":
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": "0.1.0",
                    "capabilities": {
                        "tools": {},
                    },
                    "serverInfo": {
                        "name": "mock-server",
                        "version": "1.0.0",
                    },
                },
            }
        elif method == "tools/list":
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "tools": [
                        {
                            "name": "echo",
                            "description": "回显输入参数",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "message": {
                                        "type": "string",
                                        "description": "要回显的消息",
                                    },
                                },
                                "required": ["message"],
                            },
                        },
                        {
                            "name": "add",
                            "description": "两数相加",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "a": {"type": "integer", "description": "数字 A"},
                                    "b": {"type": "integer", "description": "数字 B"},
                                },
                                "required": ["a", "b"],
                            },
                        },
                    ],
                },
            }
        elif method == "tools/call":
            params = request.get("params", {})
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})

            if tool_name == "echo":
                content = [{"type": "text", "text": f"ECHO: {arguments.get('message', '')}"}]
            elif tool_name == "add":
                a = arguments.get("a", 0)
                b = arguments.get("b", 0)
                content = [{"type": "text", "text": str(a + b)}]
            else:
                content = [{"type": "text", "text": f"未知工具: {tool_name}"}]

            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": content,
                    "isError": False,
                },
            }
        else:
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }

        raw = json.dumps(response, ensure_ascii=False) + "\n"
        sys.stdout.buffer.write(raw.encode("utf-8"))
        sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
