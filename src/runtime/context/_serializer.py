"""
消息序列化模块——MessageSerializer 接口与默认实现。

定义如何将 ContextPayload 序列化为 LLM 可消费的 messages 列表。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.runtime.context._payload import ContextPayload


@runtime_checkable
class MessageSerializer(Protocol):
    """
    消息序列化接口。

    将 ContextPayload 序列化为 LLM API 可消费的 messages 列表。
    所有自定义序列化器都应兼容此 Protocol。
    """

    async def serialize(self, payload: ContextPayload) -> list[dict]:
        """
        将 ContextPayload 序列化为 messages 列表。

        Args:
            payload: 包含所有上下文信息的 ContextPayload。

        Returns:
            符合 LLM API 格式的 messages 列表。
        """
        ...


class DefaultSerializer:
    """
    默认消息序列化器。

    将 ContextPayload 中的各字段按固定优先级组装为 messages 列表：
    system prompt → memories → rag_documents
    → injected_context → history → tool_results
    仅在 dirty 时执行序列化，否则复用上次序列化结果。
    """

    def __init__(self) -> None:
        """初始化默认序列化器。"""

    async def serialize(self, payload: ContextPayload) -> list[dict]:
        """
        将 ContextPayload 序列化为 messages 列表。

        Args:
            payload: 上下文负载。

        Returns:
            符合 LLM API 格式的 messages 列表。
        """
        messages: list[dict] = []

        # 1. system message
        system_content = payload.system_prompt
        extra_parts: list[str] = []

        if payload.memories:
            memories_str = "\n".join(str(m) for m in payload.memories)
            extra_parts.append(f"[记忆]\n{memories_str}")

        if payload.rag_documents:
            docs_str = "\n---\n".join(str(d) for d in payload.rag_documents)
            extra_parts.append(f"[参考文档]\n{docs_str}")

        if payload.injected_context:
            ctx_str = "\n".join(str(c) for c in payload.injected_context)
            extra_parts.append(f"[附加上下文]\n{ctx_str}")

        if extra_parts:
            system_content += "\n\n" + "\n\n".join(extra_parts)

        messages.append({"role": "system", "content": system_content})

        # 2. 对话历史
        messages.extend(payload.history)

        # 3. 工具结果
        for result in payload.tool_results:
            if isinstance(result, dict):
                messages.append(result)
            else:
                messages.append({"role": "tool", "content": str(result)})

        return messages
