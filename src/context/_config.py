"""
上下文管理配置——ContextConfig 定义。

控制选取策略、分层降级阈值、记忆检索参数和预算分配等行为。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ContextConfig:
    """
    上下文管理配置。

    控制 ContextManager 五阶段管线的全部可调参数：
    选取策略（滑动窗口）、分层降级阈值、记忆检索、预算分配。
    """

    # ── 预算 ──

    max_context_tokens: int = 32768
    """上下文总 token 上限。"""

    reserve_for_response: int = 0
    """留给 LLM 回复的 token 数。0 表示自动（max_context_tokens 的 10%）。"""

    avg_message_tokens: int = 500
    """单轮消息平均 token 数（用于动态配额计算）。"""

    # ── 滑动窗口 ──

    preserve_turns: int = 10
    """保留的原始对话轮次数。"""

    min_preserve_turns: int = 3
    """即使 token 超限也至少保留的轮次数。"""

    preserve_tool_context: bool = True
    """是否将工具调用与结果成对保留（不拆分）。"""

    # ── 分层降级 ──

    level1_threshold: int = 20000
    """token > 20K 时使用 L1（原始消息 + 摘要 + 实体 + 行为）。"""

    level2_threshold: int = 8000
    """token > 8K 时使用 L2（摘要 + 实体 + 行为）。"""

    level3_threshold: int = 2000
    """token > 2K 时使用 L3（事实 + 行为）。token ≤ 2K 使用 L4（仅行为）。"""

    # ── 记忆检索 ──

    max_memories: int = 15
    """最多注入记忆条数。"""

    min_memory_importance: float = 0.3
    """最小重要性阈值，低于此值的记忆不注入。"""

    cross_session_memory: bool = True
    """是否跨 Session 检索记忆。"""

    # ── 用于 Serialize 阶段 ──

    max_memories_in_system: int = 5
    """序列化时 system prompt 中最多包含的记忆条数（对应现有硬编码 5 条）。"""
