"""
流式数据收集器——AsyncStreamCollector。

逐步从 stream chunk 中累加 content + tool_calls delta，
最终 assemble() 出完整的原始响应，用于 _to_response()。
"""

from __future__ import annotations

import json
from typing import Any


class AsyncStreamCollector:
    """流式数据收集器。

    从 OpenAI 流式 API 的逐 chunk 响应中累加数据，
    最终 assemble() 出完整的响应结构，兼容非流式响应的字段格式。

    使用方式：
        collector = AsyncStreamCollector()
        async for chunk in stream:
            collector.collect(chunk.to_dict())
        assembled = collector.assemble()
    """

    def __init__(self) -> None:
        """初始化空的流收集器。"""
        self._content_chunks: list[str] = []
        self._tool_call_chunks: dict[int, dict[str, Any]] = {}
        self._usage: dict[str, int] = {}
        self._model: str = ""

    def collect(self, chunk: dict[str, Any]) -> None:
        """收集一个 chunk 的数据。

        Args:
            chunk: OpenAI 流式 chunk 的字典表示。
        """
        choices = chunk.get("choices")
        if not choices:
            # 最后一个 usage chunk（stream_options={"include_usage": True}）
            if chunk.get("usage"):
                usage = chunk["usage"]
                self._usage = {
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                }
            if chunk.get("model"):
                self._model = chunk["model"]
            return

        delta = choices[0].get("delta", {})
        if not delta:
            return

        # 累加 content
        content = delta.get("content")
        if content:
            self._content_chunks.append(content)

        # 累加 tool_calls delta
        tool_calls_delta = delta.get("tool_calls")
        if tool_calls_delta:
            for tc_delta in tool_calls_delta:
                idx = tc_delta.get("index", 0)
                if idx not in self._tool_call_chunks:
                    self._tool_call_chunks[idx] = {
                        "id": "",
                        "function": {"name": "", "arguments": ""},
                    }
                tc = self._tool_call_chunks[idx]
                if tc_delta.get("id"):
                    tc["id"] = tc_delta["id"]
                func = tc_delta.get("function")
                if func:
                    if func.get("name"):
                        tc["function"]["name"] += func["name"]
                    if func.get("arguments"):
                        tc["function"]["arguments"] += func["arguments"]

    def assemble(self) -> dict[str, Any]:
        """组装为 OpenAI 原始响应格式（模拟非流式响应）。

        Returns:
            结构上兼容 ChatCompletion 响应字典的对象。
        """
        return {
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": self.full_content or None,
                        "tool_calls": self.tool_calls if self.tool_calls else None,
                    },
                    "finish_reason": "stop" if not self.tool_calls else "tool_calls",
                }
            ],
            "usage": self._usage or None,
            "model": self._model,
        }

    @property
    def full_content(self) -> str:
        """已累积的完整文本内容。"""
        return "".join(self._content_chunks)

    @property
    def tool_calls(self) -> list[dict[str, Any]]:
        """已累积的完整工具调用列表（OpenAI 原始格式）。"""
        if not self._tool_call_chunks:
            return []
        return [
            {
                "id": tc["id"],
                "type": "function",
                "function": {
                    "name": tc["function"]["name"],
                    "arguments": tc["function"]["arguments"],
                },
            }
            for tc in sorted(self._tool_call_chunks.values(), key=lambda x: x["id"])
        ]

    @property
    def usage_dict(self) -> dict[str, int]:
        """已累积的用量信息。"""
        return dict(self._usage)

    def to_json(self) -> str:
        """序列化为 JSON 字符串（用于日志/调试）。"""
        return json.dumps(
            {
                "content": self.full_content,
                "tool_calls": self.tool_calls,
                "usage": self._usage,
                "model": self._model,
            },
            ensure_ascii=False,
        )
