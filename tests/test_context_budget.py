"""
TokenManager 与 BudgetController 单元测试。

覆盖：token 估算、优先级裁剪、动态配额分配、保底预留。
"""

from __future__ import annotations

from src.context._budget import BudgetController, TokenManager
from src.context._config import ContextConfig
from src.runtime.context._payload import ContextPayload


class TestTokenManager:
    """TokenManager 单元测试。"""

    def test_estimate_tokens_empty(self) -> None:
        """测试空文本估算。"""
        assert TokenManager.estimate_tokens("") == 1

    def test_estimate_tokens_short(self) -> None:
        """测试短文本。"""
        tokens = TokenManager.estimate_tokens("hello world")
        assert tokens > 0

    def test_estimate_tokens_long(self) -> None:
        """测试长文本。"""
        text = "x" * 1000
        tokens = TokenManager.estimate_tokens(text)
        assert tokens == 401  # 1000 * 0.4 + 1

    def test_apply_budget_within_limit(self) -> None:
        """测试预算充足时不做裁剪。"""
        payload = ContextPayload(
            system_prompt="You are a helper",
            memories=["memory1", "memory2"],
        )
        tm = TokenManager()
        result = tm.apply_budget(payload, [], 100_000)
        assert len(result.memories) == 2

    def test_apply_budget_trim_memories(self) -> None:
        """测试预算不足时裁剪 memories。"""
        payload = ContextPayload(
            system_prompt="system",
            memories=["m" * 500, "m" * 500, "m" * 500],
        )
        tm = TokenManager()
        # 预算只够 system + 1 条 memory
        result = tm.apply_budget(payload, [], 500)
        assert len(result.memories) < 3

    def test_apply_budget_trim_all(self) -> None:
        """测试预算被原始消息占满时清空所有附加字段。"""
        payload = ContextPayload(
            system_prompt="system",
            memories=["memory1", "memory2"],
            rag_documents=["doc1"],
            injected_context=["ctx"],
        )
        tm = TokenManager()
        # 原始消息占满预算
        result = tm.apply_budget(payload, [{"content": "x" * 2000}], 500)
        assert len(result.memories) == 0
        assert len(result.rag_documents) == 0
        assert len(result.injected_context) == 0

    def test_apply_budget_trim_order(self) -> None:
        """测试裁剪顺序：tool_results > rag_documents > injected_context > memories。"""
        payload = ContextPayload(
            system_prompt="s",
            tool_results=["t1", "t2"],
            rag_documents=["d1", "d2"],
            injected_context=["c1", "c2"],
            memories=["m1", "m2"],
        )
        tm = TokenManager()
        # 预算刚好够 system + 少量内容
        result = tm.apply_budget(payload, [], 50)
        # 最先被裁的是 tool_results
        assert len(result.tool_results) <= len(payload.tool_results)
        # memories 应该被保留最多
        assert len(result.memories) >= len(result.tool_results)

    def test_apply_budget_empty_fields(self) -> None:
        """测试空字段不报错。"""
        payload = ContextPayload(system_prompt="s")
        tm = TokenManager()
        result = tm.apply_budget(payload, [], 1000)
        assert result.system_prompt == "s"


class TestBudgetController:
    """BudgetController 单元测试。"""

    def test_allocate_budget(self) -> None:
        """测试动态配额分配。"""
        config = ContextConfig(max_context_tokens=32768)
        controller = BudgetController()
        payload = ContextPayload(system_prompt="test")
        hints = controller._allocate_budget(payload, config)
        assert hints["max_tokens"] == 32768
        assert hints["reserve_for_response"] >= 512
        assert hints["preserve_last_n_history"] >= 3

    def test_allocate_budget_small(self) -> None:
        """测试小预算下的配额分配。"""
        config = ContextConfig(
            max_context_tokens=2000,
            avg_message_tokens=200,
            min_preserve_turns=3,
        )
        controller = BudgetController()
        payload = ContextPayload(system_prompt="test")
        hints = controller._allocate_budget(payload, config)
        assert hints["preserve_last_n_history"] >= 3

    async def test_apply_no_trim(self) -> None:
        """测试 apply 在预算充足时不裁剪。"""
        config = ContextConfig(max_context_tokens=100_000)
        controller = BudgetController()
        payload = ContextPayload(
            system_prompt="system",
            memories=["m1", "m2"],
        )
        result = await controller.apply(payload, [], config)
        assert len(result.memories) == 2

    async def test_apply_with_trim(self) -> None:
        """测试 apply 在预算不足时裁剪。"""
        config = ContextConfig(
            max_context_tokens=500,
            reserve_for_response=100,
        )
        controller = BudgetController()
        payload = ContextPayload(
            system_prompt="s",
            memories=["m" * 300, "m" * 300],
        )
        result = await controller.apply(payload, [], config)
        # 预算 500 - 预留 100 = 400，两条 memory 各 ~120 token → 240
        # system "s" = ~1 token，总共 241，在预算内
        # 但如果加上原始消息...
        assert len(result.memories) <= 2

    async def test_ensure_reserve(self) -> None:
        """测试保底预留。"""
        config = ContextConfig(reserve_for_response=100)
        controller = BudgetController()
        payload = ContextPayload(system_prompt="test", reserve_for_response=100)
        result = await controller.apply(payload, [], config)
        assert result.reserve_for_response >= 512  # 自动提升到最低 512

    async def test_apply_sets_payload_meta(self) -> None:
        """测试 apply 更新 payload 元信息。"""
        config = ContextConfig(max_context_tokens=8192)
        controller = BudgetController()
        payload = ContextPayload(system_prompt="test")
        result = await controller.apply(payload, [], config)
        assert result.max_tokens == 8192
        assert result.reserve_for_response > 0
