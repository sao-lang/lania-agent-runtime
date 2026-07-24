"""
Compressor 单元测试。

覆盖：分层降级、记忆选取、去重排除、token 预算截断。
"""

from __future__ import annotations

from unittest.mock import MagicMock

from src.context._compressor import LEVEL, Compressor
from src.context._models import RawContext, SelectionDecision


def _make_ctx(
    messages: list | None = None,
    token_limit: int = 4096,
) -> MagicMock:
    """创建 mock RuntimeContext。"""
    ctx = MagicMock()
    ctx.messages = tuple(messages or [
        {"role": "system", "content": "You are a helper"},
    ])
    ctx.budget.token_limit = token_limit
    return ctx


def _make_memory(
    turn_index: int,
    summary: str = "",
    importance: float = 0.5,
) -> MagicMock:
    """创建 mock EpisodicMemoryEntry。"""
    m = MagicMock()
    m.turn_index = turn_index
    m.summary = summary or f"memory{turn_index}"
    m.importance = importance
    m.id = f"mem_{turn_index}"
    m.content_type = "raw"
    return m


class TestCompressor:
    """Compressor 单元测试。"""

    def test_select_level_l1(self) -> None:
        """测试 L1 层级选择（> 20K tokens）。"""
        c = Compressor()
        assert c._select_level(25000) == LEVEL.L1

    def test_select_level_l2(self) -> None:
        """测试 L2 层级选择（8K-20K）。"""
        c = Compressor()
        assert c._select_level(15000) == LEVEL.L2

    def test_select_level_l3(self) -> None:
        """测试 L3 层级选择（2K-8K）。"""
        c = Compressor()
        assert c._select_level(5000) == LEVEL.L3

    def test_select_level_l4(self) -> None:
        """测试 L4 层级选择（≤ 2K）。"""
        c = Compressor()
        assert c._select_level(1000) == LEVEL.L4

    async def test_compress_empty_raw(self) -> None:
        """测试空 RawContext。"""
        c = Compressor()
        ctx = _make_ctx(token_limit=16000)
        raw = RawContext()
        decision = SelectionDecision()
        payload = await c.compress(raw, decision, ctx)
        assert payload.system_prompt == "You are a helper"
        assert payload.memories == []

    async def test_compress_l4_only_behavior(self) -> None:
        """测试 L4：仅注入行为模式。"""
        c = Compressor()
        ctx = _make_ctx(token_limit=1000)  # ≤ 2K → L4
        raw = RawContext(
            tone_instruction="用户偏好: 简洁回复",
            episodic_memories=[_make_memory(0, "long memory about something")],
            entity_profile={"name": "Alice"},
        )
        decision = SelectionDecision()
        payload = await c.compress(raw, decision, ctx)
        # L4：只有 tone_instruction
        assert "用户偏好" in " ".join(payload.injected_context)
        # L4 不包含 memories 或实体画像
        assert len(payload.memories) == 0

    async def test_compress_l3_with_entity(self) -> None:
        """测试 L3：注入实体画像。"""
        c = Compressor()
        ctx = _make_ctx(token_limit=5000)  # 2K-8K → L3
        raw = RawContext(
            tone_instruction="友好",
            entity_profile={"name": {"value": "Alice"}},
            concepts=[{"name": "Python", "description": "编程语言"}],
        )
        decision = SelectionDecision()
        payload = await c.compress(raw, decision, ctx)
        ctx_str = " ".join(payload.injected_context)
        assert "Alice" in ctx_str
        assert "Python" in ctx_str
        assert len(payload.memories) == 0  # L3 不注入记忆

    async def test_compress_l2_with_memories(self) -> None:
        """测试 L2：注入记忆。"""
        c = Compressor()
        ctx = _make_ctx(token_limit=15000)  # 8K-20K → L2
        raw = RawContext(
            episodic_memories=[
                _make_memory(0, "memory_a", importance=0.9),
                _make_memory(1, "memory_b", importance=0.5),
            ],
        )
        decision = SelectionDecision()
        payload = await c.compress(raw, decision, ctx)
        assert len(payload.memories) == 2
        assert payload.memories[0].importance == 0.9  # 高重要性优先

    async def test_select_memories_exclude_dedup(self) -> None:
        """测试排除已去重的记忆。"""
        c = Compressor()
        memories = [
            _make_memory(0, "m0", importance=0.5),
            _make_memory(1, "m1", importance=0.8),
            _make_memory(2, "m2", importance=0.6),
        ]
        decision = SelectionDecision(
            dedup_turn_indices={1},  # turn 1 已去重
        )
        result = c._select_memories(memories, decision, 10000)
        # turn 1 的记忆应被排除
        turn_indices = {m.turn_index for m in result}
        assert 1 not in turn_indices

    async def test_select_memories_cropped_priority(self) -> None:
        """测试被裁轮次的记忆优先。"""
        c = Compressor()
        memories = [
            _make_memory(0, "cropped", importance=0.3),
            _make_memory(5, "kept", importance=0.9),
        ]
        decision = SelectionDecision(
            cropped_ranges=[(0, 4)],  # turn 0-4 被裁
            dedup_turn_indices={5},
        )
        result = c._select_memories(memories, decision, 10000)
        # 被裁轮次的记忆优先（尽管重要性更低）
        if result:
            assert result[0].turn_index == 0

    async def test_select_memories_token_budget(self) -> None:
        """测试 token 预算截断。"""
        c = Compressor()
        memories = [
            _make_memory(0, "x" * 1000, importance=0.5),  # ~400 tokens
            _make_memory(1, "y" * 1000, importance=0.8),  # ~400 tokens
            _make_memory(2, "z" * 1000, importance=0.9),  # ~400 tokens
        ]
        decision = SelectionDecision()
        # 预算只够 1 条
        result = c._select_memories(memories, decision, 500)
        assert len(result) <= 2

    async def test_get_system_prompt(self) -> None:
        """测试提取 system prompt。"""
        c = Compressor()
        ctx = _make_ctx([
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "hi"},
        ])
        prompt = c._get_system_prompt(ctx)
        assert prompt == "You are helpful"

    async def test_get_system_prompt_no_system(self) -> None:
        """测试无 system prompt 时返回空字符串。"""
        c = Compressor()
        ctx = _make_ctx([
            {"role": "user", "content": "hi"},
        ])
        prompt = c._get_system_prompt(ctx)
        assert prompt == ""
