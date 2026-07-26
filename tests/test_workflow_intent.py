"""
WorkflowLoop 意图路由测试。

覆盖：
  - add_intent_route() 内部展开验证（正常路由 / 未匹配降级）
  - RuleClassifier 分类逻辑
  - WorkflowLoop.run() 端到端意图路由全链路
  - 序列化 round-trip（to_dict / from_dict 含意图路由元信息）
"""

from __future__ import annotations

from typing import Any

from src.intent import HybridClassifier, LLMClassifier, RuleClassifier
from src.runtime.context._context import RuntimeContext
from src.runtime.loops import (
    ConditionNode,
    FixedNode,
    WorkflowDefinition,
    WorkflowLoop,
)
from tests.test_loops import make_mock_executor

# ============ 辅助函数 ============


def make_runtime_context(
    messages: list[dict] | None = None,
    services: dict | None = None,
) -> RuntimeContext:
    """创建测试用 RuntimeContext。"""
    from src.runtime.context._context import RuntimeContext as RC

    return RC(
        session_id="test-session",
        agent_id="test-agent",
        messages=tuple(messages or []),
        services=services or {},
    )  # type: ignore[arg-type]


def make_agent_runtime() -> Any:
    """创建测试用 AgentRuntime。"""
    from src.runtime._runtime import AgentRuntime

    runtime = AgentRuntime(system_prompt="test助手")
    runtime.set_llm_executor(make_mock_executor("ok"))
    return runtime


# ============ RuleClassifier 测试 ============


class TestRuleClassifier:
    """RuleClassifier 单元测试。"""

    async def test_basic_matching(self) -> None:
        """基本关键词匹配。"""
        classifier = RuleClassifier(
            rules={
                "qa": ["什么", "为什么", "如何"],
                "coding": ["代码", "bug", "函数"],
            },
            default="chat",
        )
        ctx = make_runtime_context(
            messages=[{"role": "user", "content": "如何实现登录功能"}],
        )
        intent = await classifier.classify(ctx)
        assert intent == "qa"

    async def test_coding_match(self) -> None:
        """编码意图匹配。"""
        classifier = RuleClassifier(
            rules={
                "qa": ["什么", "为什么"],
                "coding": ["代码", "bug", "函数"],
            },
            default="chat",
        )
        ctx = make_runtime_context(
            messages=[{"role": "user", "content": "这段代码有 bug"}],
        )
        intent = await classifier.classify(ctx)
        assert intent == "coding"

    async def test_fallback_to_default(self) -> None:
        """未匹配任何规则时返回默认意图。"""
        classifier = RuleClassifier(
            rules={"qa": ["什么", "为什么"]},
            default="chat",
        )
        ctx = make_runtime_context(
            messages=[{"role": "user", "content": "你好，今天天气不错"}],
        )
        intent = await classifier.classify(ctx)
        assert intent == "chat"

    async def test_case_insensitive_matching(self) -> None:
        """关键词匹配大小写不敏感。"""
        classifier = RuleClassifier(
            rules={"coding": ["BUG", "FIX"]},
            default="chat",
        )
        ctx = make_runtime_context(
            messages=[{"role": "user", "content": "帮我 fix 这个 bug"}],
        )
        intent = await classifier.classify(ctx)
        assert intent == "coding"

    async def test_empty_messages(self) -> None:
        """空消息时返回默认意图。"""
        classifier = RuleClassifier(
            rules={"qa": ["什么"]},
            default="chat",
        )
        ctx = make_runtime_context(messages=[])
        intent = await classifier.classify(ctx)
        assert intent == "chat"

    async def test_no_user_message(self) -> None:
        """没有 user 消息时返回默认意图。"""
        classifier = RuleClassifier(
            rules={"qa": ["什么"]},
            default="chat",
        )
        ctx = make_runtime_context(
            messages=[{"role": "assistant", "content": "你好"}],
        )
        intent = await classifier.classify(ctx)
        assert intent == "chat"


# ============ LLMClassifier 测试 ============


class TestLLMClassifier:
    """LLMClassifier 单元测试。"""

    async def test_llm_classification(self) -> None:
        """LLM 正常返回分类结果。"""

        async def mock_llm(prompt: str) -> str:
            return "coding"

        classifier = LLMClassifier(
            llm=mock_llm,
            categories=["qa", "coding", "chat"],
            default="chat",
        )
        ctx = make_runtime_context(
            messages=[{"role": "user", "content": "实现一个排序算法"}],
        )
        intent = await classifier.classify(ctx)
        assert intent == "coding"

    async def test_llm_returns_invalid_category(self) -> None:
        """LLM 返回无效分类时使用默认。"""

        async def mock_llm(prompt: str) -> str:
            return "invalid"

        classifier = LLMClassifier(
            llm=mock_llm,
            categories=["qa", "coding", "chat"],
            default="chat",
        )
        ctx = make_runtime_context(
            messages=[{"role": "user", "content": "你好"}],
        )
        intent = await classifier.classify(ctx)
        assert intent == "chat"


# ============ HybridClassifier 测试 ============


class TestHybridClassifier:
    """HybridClassifier 单元测试。"""

    async def test_rule_high_confidence(self) -> None:
        """规则匹配达到 threshold 时走规则。"""

        async def mock_llm(prompt: str) -> str:
            return "chat"

        classifier = HybridClassifier(
            rules={"coding": ["代码", "实现", "bug", "函数"]},
            llm=mock_llm,
            categories=["qa", "coding", "chat"],
            threshold=2,
        )
        ctx = make_runtime_context(
            messages=[{"role": "user", "content": "这段代码有 bug"}],
        )
        intent = await classifier.classify(ctx)
        assert intent == "coding"

    async def test_low_confidence_falls_to_llm(self) -> None:
        """规则匹配不足时走 LLM。"""

        async def mock_llm(prompt: str) -> str:
            return "qa"

        classifier = HybridClassifier(
            rules={"coding": ["代码", "实现", "bug"]},
            llm=mock_llm,
            categories=["qa", "coding", "chat"],
            threshold=3,
        )
        ctx = make_runtime_context(
            messages=[{"role": "user", "content": "这个代码它"}],
        )
        # 只匹配了 1 个关键词 "代码"，低于 threshold=3，走 LLM
        intent = await classifier.classify(ctx)
        assert intent == "qa"


# ============ add_intent_route 单元测试 ============


class TestAddIntentRoute:
    """WorkflowDefinition.add_intent_route() 单元测试。"""

    def test_add_intent_route_creates_nodes(self) -> None:
        """add_intent_route 应创建分类节点和路由节点。"""

        async def classifier(ctx):
            return "qa"

        wf = WorkflowDefinition()
        wf.add_node(FixedNode("agent_qa", handler=lambda ctx: ""))
        wf.add_node(FixedNode("agent_chat", handler=lambda ctx: ""))
        wf.add_intent_route(
            classifier=classifier,
            routes={"qa": "agent_qa"},
            default="agent_chat",
        )

        assert wf.has_node("intent_classify")
        assert wf.has_node("intent_classify_route")

        classify_node = wf.get_node("intent_classify")
        assert isinstance(classify_node, FixedNode)

        route_node = wf.get_node("intent_classify_route")
        assert isinstance(route_node, ConditionNode)

    def test_add_intent_route_creates_edge(self) -> None:
        """add_intent_route 应创建 classify → route 的边。"""

        async def classifier(ctx):
            return "qa"

        wf = WorkflowDefinition()
        wf.add_node(FixedNode("agent_qa", handler=lambda ctx: ""))
        wf.add_node(FixedNode("agent_chat", handler=lambda ctx: ""))
        wf.add_intent_route(
            classifier=classifier,
            routes={"qa": "agent_qa"},
            default="agent_chat",
        )

        assert wf.next_node("intent_classify") == "intent_classify_route"

    def test_add_intent_route_creates_conditions(self) -> None:
        """add_intent_route 应创建条件分支（含 fallback）。"""

        async def classifier(ctx):
            return "qa"

        wf = WorkflowDefinition()
        wf.add_node(FixedNode("agent_qa", handler=lambda ctx: ""))
        wf.add_node(FixedNode("agent_chat", handler=lambda ctx: ""))
        wf.add_intent_route(
            classifier=classifier,
            routes={"qa": "agent_qa"},
            default="agent_chat",
        )

        assert "intent_classify_route" in wf.conditions
        branches = wf.conditions["intent_classify_route"].branches
        assert branches["qa"] == "agent_qa"
        assert branches["__default__"] == "agent_chat"

    def test_add_intent_route_custom_node_id(self) -> None:
        """add_intent_route 支持自定义 node_id。"""

        async def classifier(ctx):
            return "qa"

        wf = WorkflowDefinition()
        wf.add_node(FixedNode("agent_qa", handler=lambda ctx: ""))
        wf.add_node(FixedNode("agent_chat", handler=lambda ctx: ""))
        wf.add_intent_route(
            classifier=classifier,
            routes={"qa": "agent_qa"},
            default="agent_chat",
            node_id="my_classify",
        )

        assert wf.has_node("my_classify")
        assert wf.has_node("my_classify_route")
        assert wf.next_node("my_classify") == "my_classify_route"

    def test_add_intent_route_no_default(self) -> None:
        """不传 default 时不添加 __default__ 分支。"""

        async def classifier(ctx):
            return "qa"

        wf = WorkflowDefinition()
        wf.add_node(FixedNode("agent_qa", handler=lambda ctx: ""))
        wf.add_intent_route(
            classifier=classifier,
            routes={"qa": "agent_qa"},
        )

        branches = wf.conditions["intent_classify_route"].branches
        assert "qa" in branches
        assert "__default__" not in branches


# ============ 端到端测试 ============


class TestWorkflowLoopIntentE2E:
    """WorkflowLoop 端到端意图路由测试。"""

    async def test_intent_routing_qa(self) -> None:
        """qa 意图路由到 qa 节点。"""
        runtime = make_agent_runtime()

        path: list[str] = []

        async def classifier(ctx):
            return "qa"

        wf = WorkflowDefinition()
        wf.add_node(FixedNode("agent_qa", handler=lambda ctx: path.append("qa")))
        wf.add_node(FixedNode("agent_chat", handler=lambda ctx: path.append("chat")))
        wf.add_intent_route(
            classifier=classifier,
            routes={"qa": "agent_qa"},
            default="agent_chat",
        )
        wf.start_node_id = "intent_classify"

        runtime.set_loop_strategy(
            WorkflowLoop(
                hooks=runtime._hooks,
                step_runner=runtime._step_runner,
                controller=runtime._controller,
                workflow_definition=wf,
            )
        )
        await runtime.run("intent_test_qa")
        assert path == ["qa"]

    async def test_intent_routing_default(self) -> None:
        """未匹配意图时走 default 分支。"""
        runtime = make_agent_runtime()

        path: list[str] = []

        async def classifier(ctx):
            return "unknown"

        wf = WorkflowDefinition()
        wf.add_node(FixedNode("agent_qa", handler=lambda ctx: path.append("qa")))
        wf.add_node(FixedNode("agent_chat", handler=lambda ctx: path.append("chat")))
        wf.add_intent_route(
            classifier=classifier,
            routes={"qa": "agent_qa"},
            default="agent_chat",
        )
        wf.start_node_id = "intent_classify"

        runtime.set_loop_strategy(
            WorkflowLoop(
                hooks=runtime._hooks,
                step_runner=runtime._step_runner,
                controller=runtime._controller,
                workflow_definition=wf,
            )
        )
        await runtime.run("intent_test_default")
        assert path == ["chat"]

    async def test_intent_routing_with_rule_classifier(self) -> None:
        """使用 RuleClassifier 进行意图路由。"""
        runtime = make_agent_runtime()

        path: list[str] = []

        classifier = RuleClassifier(
            rules={"qa": ["什么", "为什么", "如何"]},
            default="chat",
        )

        wf = WorkflowDefinition()
        wf.add_node(FixedNode("agent_qa", handler=lambda ctx: path.append("qa")))
        wf.add_node(FixedNode("agent_chat", handler=lambda ctx: path.append("chat")))
        wf.add_intent_route(
            classifier=classifier,
            routes={"qa": "agent_qa"},
            default="agent_chat",
        )

        # 设置起始节点为 intent_classify（add_intent_route 添加的节点）
        wf.start_node_id = "intent_classify"

        runtime.set_loop_strategy(
            WorkflowLoop(
                hooks=runtime._hooks,
                step_runner=runtime._step_runner,
                controller=runtime._controller,
                workflow_definition=wf,
            )
        )
        # 触发 qa 匹配——"什么"在 qa 规则中
        result = await runtime.run("什么是意图路由")
        assert path == ["qa"], (
            f"path={path}, result.status={result.status}, result.content={result.content}"
        )

    async def test_intent_routing_chained_nodes(self) -> None:
        """意图路由后继续执行后续节点。"""
        runtime = make_agent_runtime()

        path: list[str] = []

        async def classifier(ctx):
            return "qa"

        wf = WorkflowDefinition()
        wf.add_node(FixedNode("agent_qa", handler=lambda ctx: path.append("qa")))
        wf.add_node(FixedNode("agent_chat", handler=lambda ctx: path.append("chat")))
        wf.add_node(FixedNode("summary", handler=lambda ctx: path.append("summary")))
        wf.add_intent_route(
            classifier=classifier,
            routes={"qa": "agent_qa"},
            default="agent_chat",
        )
        wf.add_edge("agent_qa", "summary")
        wf.start_node_id = "intent_classify"

        runtime.set_loop_strategy(
            WorkflowLoop(
                hooks=runtime._hooks,
                step_runner=runtime._step_runner,
                controller=runtime._controller,
                workflow_definition=wf,
            )
        )
        await runtime.run("intent_test_chain")
        assert path == ["qa", "summary"]


# ============ 序列化测试 ============


class TestWorkflowIntentSerialization:
    """意图路由序列化测试。"""

    def test_to_dict_includes_intent_routes(self) -> None:
        """to_dict 应包含 intent_routes 元信息。"""

        async def classifier(ctx):
            return "qa"

        wf = WorkflowDefinition()
        wf.add_node(FixedNode("agent_qa", handler=lambda ctx: ""))
        wf.add_node(FixedNode("agent_chat", handler=lambda ctx: ""))
        wf.add_intent_route(
            classifier=classifier,
            routes={"qa": "agent_qa"},
            default="agent_chat",
        )

        data = wf.to_dict()
        assert "intent_routes" in data
        assert len(data["intent_routes"]) == 1
        route_info = data["intent_routes"][0]
        assert route_info["classify_node_id"] == "intent_classify"
        assert route_info["route_node_id"] == "intent_classify_route"
        assert route_info["routes"] == {"qa": "agent_qa"}
        assert route_info["default"] == "agent_chat"

    def test_to_dict_roundtrip_preserves_intent_routes(self) -> None:
        """to_dict → from_dict round-trip 应保留 intent_routes 元信息。"""

        async def classifier(ctx):
            return "qa"

        original = WorkflowDefinition()
        original.add_node(FixedNode("agent_qa", handler=lambda ctx: ""))
        original.add_node(FixedNode("agent_chat", handler=lambda ctx: ""))
        original.add_intent_route(
            classifier=classifier,
            routes={"qa": "agent_qa"},
            default="agent_chat",
        )

        data = original.to_dict()
        restored = WorkflowDefinition.from_dict(data)

        assert restored.intent_routes == original.intent_routes
        assert restored.has_node("intent_classify")
        assert restored.has_node("intent_classify_route")
        assert "intent_classify_route" in restored.conditions
        assert restored.next_node("intent_classify") == "intent_classify_route"

    def test_multiple_intent_routes(self) -> None:
        """支持多个意图路由配置。"""

        async def classifier1(ctx):
            return "qa"

        async def classifier2(ctx):
            return "coding"

        wf = WorkflowDefinition()
        wf.add_node(FixedNode("agent_qa", handler=lambda ctx: ""))
        wf.add_node(FixedNode("agent_coding", handler=lambda ctx: ""))
        wf.add_node(FixedNode("agent_chat", handler=lambda ctx: ""))
        wf.add_intent_route(
            classifier=classifier1,
            routes={"qa": "agent_qa"},
            default="agent_chat",
            node_id="route1",
        )
        wf.add_intent_route(
            classifier=classifier2,
            routes={"coding": "agent_coding"},
            default="agent_chat",
            node_id="route2",
        )

        assert len(wf.intent_routes) == 2
        data = wf.to_dict()
        assert len(data["intent_routes"]) == 2

        restored = WorkflowDefinition.from_dict(data)
        assert len(restored.intent_routes) == 2
        assert restored.has_node("route1")
        assert restored.has_node("route1_route")
        assert restored.has_node("route2")
        assert restored.has_node("route2_route")

    def test_no_intent_routes(self) -> None:
        """没有意图路由时 intent_routes 为空列表。"""
        wf = WorkflowDefinition()
        wf.add_node(FixedNode("start", handler=lambda ctx: ""))

        assert wf.intent_routes == []
        data = wf.to_dict()
        assert data["intent_routes"] == []

        restored = WorkflowDefinition.from_dict(data)
        assert restored.intent_routes == []
