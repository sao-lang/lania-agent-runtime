"""
Selector 单元测试。

覆盖：滑动窗口、tool context 保留、最小保留轮次、去重、边界条件。
"""

from __future__ import annotations

from unittest.mock import MagicMock

from src.context._config import ContextConfig
from src.context._selector import Selector


def _make_ctx(messages: list[dict]) -> MagicMock:
    """创建 mock RuntimeContext。"""
    ctx = MagicMock()
    ctx.messages = tuple(messages)
    ctx.step_index = len(messages)
    ctx.services = {}
    return ctx


class TestSelector:
    """Selector 单元测试。"""

    def _selector(self) -> Selector:
        return Selector()

    def _config(self, **kwargs) -> ContextConfig:
        return ContextConfig(**kwargs)

    # ── 基本滑动窗口 ──

    async def test_empty_messages(self) -> None:
        """测试空消息列表。"""
        ctx = _make_ctx([])
        config = self._config(preserve_turns=10)
        result = await self._selector().select(ctx, config)
        assert result.preserve_message_count == 0
        assert result.keep_from_index == 0
        assert result.cropped_ranges == []

    async def test_only_system(self) -> None:
        """测试只有 system 消息。"""
        ctx = _make_ctx([{"role": "system", "content": "You are a helper"}])
        config = self._config(preserve_turns=10)
        result = await self._selector().select(ctx, config)
        assert result.preserve_message_count == 0
        assert result.keep_from_index == 1  # system 后无内容

    async def test_one_turn(self) -> None:
        """测试 1 轮对话。"""
        ctx = _make_ctx([
            {"role": "system", "content": "You are a helper"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ])
        config = self._config(preserve_turns=10)
        result = await self._selector().select(ctx, config)
        assert result.preserve_message_count == 1
        assert result.keep_from_index == 1  # 保留从 user 开始
        assert result.cropped_ranges == []  # 只有 1 轮，不裁剪

    async def test_preserve_last_n(self) -> None:
        """测试保留最近 N 轮。"""
        messages = [{"role": "system", "content": "You are a helper"}]
        for i in range(10):
            messages.append({"role": "user", "content": f"msg{i}"})
            messages.append({"role": "assistant", "content": f"reply{i}"})

        ctx = _make_ctx(messages)
        config = self._config(preserve_turns=3)
        result = await self._selector().select(ctx, config)

        assert result.preserve_message_count == 3
        # 10 轮对话 = 20 条消息 + 1 system = 21 条
        # 保留最后 3 轮 = 6 条消息，起始索引 = 21 - 6 = 15
        expected_from = 1 + (10 - 3) * 2
        assert result.keep_from_index == expected_from
        assert result.cropped_ranges == [(0, 6)]  # 前 7 轮被裁（0-based）

    async def test_min_preserve_turns(self) -> None:
        """测试最小保留轮次。"""
        messages = [{"role": "system", "content": "You are a helper"}]
        for i in range(3):
            messages.append({"role": "user", "content": f"msg{i}"})
            messages.append({"role": "assistant", "content": f"reply{i}"})

        ctx = _make_ctx(messages)
        # preserve_turns=1, min_preserve_turns=3 但总共只有 3 轮
        config = self._config(preserve_turns=1, min_preserve_turns=3)
        result = await self._selector().select(ctx, config)

        # 总共只有 3 轮，min_preserve=3 但总数限制，应该保留全部
        assert result.preserve_message_count == 3

    async def test_min_preserve_turns_clamp(self) -> None:
        """测试 min_preserve_turns 不超过总轮数。"""
        messages = [{"role": "system", "content": "You are a helper"}]
        for i in range(2):
            messages.append({"role": "user", "content": f"msg{i}"})
            messages.append({"role": "assistant", "content": f"reply{i}"})

        ctx = _make_ctx(messages)
        config = self._config(preserve_turns=1, min_preserve_turns=5)
        result = await self._selector().select(ctx, config)

        # 总共只有 2 轮，即使 min=5 也只能保留 2 轮
        assert result.preserve_message_count == 2

    # ── 工具调用轮次 ──

    async def test_tool_call_turn_preserved(self) -> None:
        """测试工具调用轮次完整保留（assistant + tool result 视为一轮）。"""
        messages = [
            {"role": "system", "content": "You are a helper"},
            {"role": "user", "content": "weather?"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "call_1", "function": {"name": "get_weather"}}],
            },
            {"role": "tool", "content": "sunny", "tool_call_id": "call_1"},
        ]
        ctx = _make_ctx(messages)
        config = self._config(preserve_turns=1, preserve_tool_context=True)
        result = await self._selector().select(ctx, config)

        assert result.preserve_message_count == 1
        # 应该保留 user + assistant(tool_calls) + tool result
        assert result.keep_from_index == 1  # 从 user 开始

    async def test_tool_call_multiple_results(self) -> None:
        """测试多个 tool result 与一个 assistant 绑定。"""
        messages = [
            {"role": "system", "content": "You are a helper"},
            {"role": "user", "content": "weather and news?"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call_1", "function": {"name": "get_weather"}},
                    {"id": "call_2", "function": {"name": "get_news"}},
                ],
            },
            {"role": "tool", "content": "sunny", "tool_call_id": "call_1"},
            {"role": "tool", "content": "headlines", "tool_call_id": "call_2"},
        ]
        ctx = _make_ctx(messages)
        config = self._config(preserve_turns=1, preserve_tool_context=True)
        result = await self._selector().select(ctx, config)

        assert result.preserve_message_count == 1
        assert result.keep_from_index == 1  # 所有消息都保留

    async def test_tool_context_disabled(self) -> None:
        """测试 preserve_tool_context=False 时 tool result 独立处理。"""
        messages = [
            {"role": "system", "content": "You are a helper"},
            {"role": "user", "content": "weather?"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "call_1", "function": {"name": "get_weather"}}],
            },
            {"role": "tool", "content": "sunny", "tool_call_id": "call_1"},
        ]
        ctx = _make_ctx(messages)
        config = self._config(preserve_turns=1, preserve_tool_context=False)
        result = await self._selector().select(ctx, config)

        # tool context disabled 时，tool result 可能会被单独裁剪
        assert result.keep_from_index >= 1

    # ── 去重 ──

    async def test_dedup_turn_indices(self) -> None:
        """测试去重 turn_indices。"""
        messages = [{"role": "system", "content": "You are a helper"}]
        for i in range(5):
            messages.append({"role": "user", "content": f"msg{i}"})
            messages.append({"role": "assistant", "content": f"reply{i}"})

        ctx = _make_ctx(messages)
        config = self._config(preserve_turns=2)
        result = await self._selector().select(ctx, config)

        # 保留最后 2 轮（turn 3, 4），这些 turn 需要去重
        assert 3 in result.dedup_turn_indices
        assert 4 in result.dedup_turn_indices
        # 被裁的 turn 不在去重集合中
        assert 0 not in result.dedup_turn_indices
        assert 1 not in result.dedup_turn_indices

    # ── 边界条件 ──

    async def test_mixed_roles(self) -> None:
        """测试混合角色消息。"""
        ctx = _make_ctx([
            {"role": "system", "content": "system"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
            {"role": "user", "content": "what?"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "c1", "function": {"name": "f1"}}],
            },
            {"role": "tool", "content": "result", "tool_call_id": "c1"},
        ])
        config = self._config(preserve_turns=2)
        result = await self._selector().select(ctx, config)

        # 2 轮完整对话，应该全部保留
        assert result.preserve_message_count == 2
        assert result.keep_from_index == 1  # 从第一条 user 开始
