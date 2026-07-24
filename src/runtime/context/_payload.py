"""
上下文负载模块——ContextPayload 定义。

ContextPayload 是上下文中间层，Hook 操作此对象，Runtime 负责序列化为 messages。
引入脏标记（dirty flag）避免重复序列化。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ContextPayload:
    """
    上下文中间层——Hook 操作此对象，Runtime 负责序列化为 messages。

    多源上下文有优先级和编排逻辑，不同 LLM provider 的 messages 格式不同，
    因此引入此中间层解耦 Hook 与具体传输格式。

    Attributes:
        system_prompt: 系统提示词，不可被任意 Hook 覆盖。
        memories: Memory Bank 注入的记忆。
        rag_documents: RAG 检索结果。
        injected_context: 其他 Hook 注入的额外上下文。
        history: 最近 N 轮对话历史。
        tool_call_request: 本轮要调用的工具请求。
        tool_results: 历史工具结果。
        max_tokens: 总 token 上限。
        preserve_last_n_history: 至少保留最近 N 轮对话。
        reserve_for_response: 留给 LLM 回复的 token 数量。
    """

    system_prompt: str = ""
    """System prompt，不可被任意 Hook 覆盖。"""

    memories: list = field(default_factory=list)
    """Memory Bank 注入的记忆片段列表。"""

    rag_documents: list = field(default_factory=list)
    """RAG 检索结果文档列表。"""

    injected_context: list = field(default_factory=list)
    """其他 Hook 注入的额外上下文列表。"""

    history: list = field(default_factory=list)
    """对话历史，每条为 dict（含 role, content 等字段）。"""

    tool_call_request: dict | None = None
    """本轮要调用的工具请求信息。"""

    tool_results: list = field(default_factory=list)
    """历史工具结果列表。"""

    max_tokens: int = 0
    """总 token 上限，0 表示不限制。"""

    preserve_last_n_history: int = 10
    """至少保留最近 N 轮对话。"""

    reserve_for_response: int = 1024
    """留给 LLM 回复的 token 数量。"""

    assembled_messages: list | None = None
    """ContextAssemblerHook 预组装的 LLM 消息列表。

    不为 None 时，Runtime 的 _execute_llm_step 直接使用此字段，
    跳过 BEFORE_SERIALIZE 和 serialize 步骤，避免重复序列化。
    """

    _dirty: bool = True
    """脏标记——避免重复序列化。"""

    @property
    def is_dirty(self) -> bool:
        """
        检查是否自上次序列化后有过修改。

        Returns:
            如果有未序列化的修改返回 True，否则 False。
        """
        return self._dirty

    def mark_dirty(self) -> None:
        """标记为已修改，下次序列化必须重新生成。"""
        self._dirty = True

    def mark_clean(self) -> None:
        """标记为已序列化，下次若非 dirty 则跳过序列化。"""
        self._dirty = False
