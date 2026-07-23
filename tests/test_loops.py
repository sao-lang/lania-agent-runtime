"""
Loop 策略模块测试。

覆盖：
  - LoopStrategyFactory 注册/创建/异常
  - ReActLoop 循环逻辑（正常/阻断/暂停/Router）
  - PlanExecuteLoop 规划/执行/Replan
  - WorkflowLoop 图遍历/条件分支/依赖检查
  - 类型定义（StepResult / StepStatus / Plan / PlanStep）
"""

from __future__ import annotations

import pytest

from src.runtime._runtime import AgentRuntime
from src.runtime._types import (
    BlockAction,
    HookPoint,
    PauseAction,
    PrimitiveType,
)
from src.runtime.loops import (
    AgentNode,
    ConditionNode,
    FixedNode,
    LoopStrategyFactory,
    Plan,
    ReActLoop,
    StepResult,
    StepStatus,
    WorkflowDefinition,
    WorkflowLoop,
)
from src.runtime.loops._types import PlanStep as PlanStepType
from src.runtime.llm._models import FinishReason, LLMResponse, LLMUsage, ToolCall


# ============ 辅助函数 ============


def make_mock_executor(content: str = "ok") -> callable:
    """创建返回固定内容的 mock LLM executor。"""

    async def mock_llm(ctx):
        return LLMResponse(
            content=content,
            finish_reason=FinishReason.STOP,
            usage=LLMUsage(prompt_tokens=10, completion_tokens=5),
        )

    return mock_llm


def make_mock_tool_executor() -> callable:
    """创建 mock tool executor。"""

    async def mock_tool(ctx):
        return {"role": "tool", "content": "工具结果"}

    return mock_tool


# ============ StepResult / StepStatus 测试 ============


class TestStepResult:
    """StepResult 数据类测试。"""

    def test_default_values(self) -> None:
        result = StepResult()
        assert result.finish_reason == FinishReason.STOP
        assert result.status == StepStatus.SUCCESS
        assert result.content == ""
        assert result.tool_calls == []
        assert result.error is None

    def test_is_blocked(self) -> None:
        assert StepResult(status=StepStatus.BLOCKED).is_blocked is True
        assert StepResult(status=StepStatus.SUCCESS).is_blocked is False

    def test_has_tool_calls(self) -> None:
        assert StepResult(finish_reason=FinishReason.TOOL_CALLS).has_tool_calls is True
        tc = ToolCall(id="call_1", name="test_tool", arguments={})
        assert StepResult(tool_calls=[tc]).has_tool_calls is True
        assert StepResult().has_tool_calls is False


class TestStepStatus:
    """StepStatus 枚举测试。"""

    def test_values(self) -> None:
        assert StepStatus.SUCCESS.value == "success"
        assert StepStatus.BLOCKED.value == "blocked"
        assert StepStatus.PAUSED.value == "paused"
        assert StepStatus.ERROR.value == "error"
        assert StepStatus.CANCELLED.value == "cancelled"


# ============ Plan / PlanStep 测试 ============


class TestPlan:
    """Plan 数据类测试。"""

    def test_default_values(self) -> None:
        plan = Plan()
        assert plan.steps == []
        assert plan.reasoning == ""

    def test_with_steps(self) -> None:
        steps = [
            PlanStepType(id="s1", description="第一步", depends_on=[]),
            PlanStepType(id="s2", description="第二步", depends_on=["s1"]),
        ]
        plan = Plan(steps=steps, reasoning="test")
        assert len(plan.steps) == 2
        assert plan.steps[1].depends_on == ["s1"]
        assert plan.reasoning == "test"


# ============ LoopStrategyFactory 测试 ============


class TestLoopStrategyFactory:
    """LoopStrategyFactory 测试。"""

    def setup_method(self) -> None:
        LoopStrategyFactory.clear()

    def test_register_and_create(self) -> None:
        LoopStrategyFactory.register("react", ReActLoop)
        assert "react" in LoopStrategyFactory.available()

    def test_register_duplicate(self) -> None:
        LoopStrategyFactory.register("react", ReActLoop)
        with pytest.raises(ValueError, match="已注册"):
            LoopStrategyFactory.register("react", ReActLoop)

    def test_create_unknown(self) -> None:
        with pytest.raises(ValueError, match="未知的策略"):
            LoopStrategyFactory.create("unknown")

    def test_unregister(self) -> None:
        LoopStrategyFactory.register("react", ReActLoop)
        LoopStrategyFactory.unregister("react")
        assert "react" not in LoopStrategyFactory.available()

    def test_unregister_unknown(self) -> None:
        with pytest.raises(ValueError, match="未知的策略"):
            LoopStrategyFactory.unregister("unknown")

    def test_clear(self) -> None:
        LoopStrategyFactory.register("react", ReActLoop)
        LoopStrategyFactory.clear()
        assert LoopStrategyFactory.available() == []

    def test_available_empty(self) -> None:
        LoopStrategyFactory.clear()
        assert LoopStrategyFactory.available() == []


# ============ ReActLoop 测试 ============


class TestReActLoop:
    """ReActLoop 循环逻辑测试。"""

    async def test_react_loop_basic(self) -> None:
        """基本 ReAct 循环——正常执行一步后结束。"""
        runtime = AgentRuntime(system_prompt="助手")
        runtime.set_llm_executor(make_mock_executor("你好"))
        result = await runtime.run("hello")
        assert result.status == "ended"
        assert "你好" in result.content

    async def test_react_loop_with_tool_calls(self) -> None:
        """包含工具调用的 ReAct 循环。"""
        runtime = AgentRuntime(system_prompt="助手")
        call_count = 0

        async def mock_llm(ctx):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return LLMResponse(
                    content="",
                    finish_reason=FinishReason.TOOL_CALLS,
                    tool_calls=[ToolCall(id="tc1", name="get_weather", arguments={})],
                    usage=LLMUsage(prompt_tokens=10, completion_tokens=5),
                )
            return LLMResponse(
                content="完成",
                finish_reason=FinishReason.STOP,
                usage=LLMUsage(prompt_tokens=10, completion_tokens=5),
            )

        runtime.set_llm_executor(mock_llm)
        runtime.set_tool_executor(make_mock_tool_executor())
        result = await runtime.run("天气怎么样")
        assert result.status == "ended"
        assert call_count == 2

    async def test_react_loop_blocked(self) -> None:
        """before_llm 阻断时循环终止。"""
        runtime = AgentRuntime(system_prompt="助手")

        @runtime.on(HookPoint.BEFORE_LLM, primitive=PrimitiveType.INTERCEPT)
        async def block_all(data, ctx):
            return BlockAction(reason="测试阻断")

        runtime.set_llm_executor(make_mock_executor("不应到达"))
        result = await runtime.run("test")
        assert "阻断" in result.content
        assert result.status == "error"

    async def test_react_loop_paused(self) -> None:
        """before_llm 暂停时循环返回 paused 状态。"""
        runtime = AgentRuntime(system_prompt="助手")

        @runtime.on(HookPoint.BEFORE_LLM, primitive=PrimitiveType.INTERCEPT)
        async def pause_all(data, ctx):
            return PauseAction(approval_id="pause_1", context={"reason": "test"})

        runtime.set_llm_executor(make_mock_executor("不应到达"))
        result = await runtime.run("test")
        assert result.status == "paused"

    async def test_react_loop_with_router(self) -> None:
        """Router 覆盖默认结束行为。"""
        async def router_fn(ctx):
            return "continue"

        runtime = AgentRuntime(system_prompt="助手", router=router_fn)

        async def mock_llm(ctx):
            return LLMResponse(
                content="继续执行",
                finish_reason=FinishReason.STOP,
                usage=LLMUsage(prompt_tokens=10, completion_tokens=5),
            )

        runtime.set_llm_executor(mock_llm)
        # Router 返回 "continue" 使循环继续，但 max_iterations 限制后结束
        result = await runtime.run("test")
        assert result.status == "ended"


# ============ PlanExecuteLoop 测试 ============


class TestPlanExecuteLoop:
    """PlanExecuteLoop 规划执行测试。"""

    async def test_plan_execute_basic(self) -> None:
        """基本规划执行流程。"""
        runtime = AgentRuntime(
            system_prompt="助手",
            loop_strategy_name="plan_and_execute",
        )

        plan_parsed = False
        step_count = 0

        async def mock_llm(ctx):
            nonlocal plan_parsed, step_count
            step_count += 1
            if step_count == 1:
                # Planner 返回规划
                return LLMResponse(
                    content='{"steps": [{"id": "s1", "description": "第一步", "depends_on": []}]}',
                    finish_reason=FinishReason.STOP,
                    usage=LLMUsage(prompt_tokens=10, completion_tokens=5),
                )
            # 执行步骤
            return LLMResponse(
                content="执行完成",
                finish_reason=FinishReason.STOP,
                usage=LLMUsage(prompt_tokens=10, completion_tokens=5),
            )

        runtime.set_llm_executor(mock_llm)
        result = await runtime.run("请分析数据")
        assert result.status == "ended"

    async def test_plan_execute_with_replan(self) -> None:
        """Replan 路径测试。"""
        runtime = AgentRuntime(
            system_prompt="助手",
            loop_strategy_name="plan_and_execute",
        )

        step_count = 0

        async def mock_llm(ctx):
            nonlocal step_count
            step_count += 1
            if step_count == 1:
                # Planner
                return LLMResponse(
                    content='{"steps": [{"id": "s1", "description": "第一步", "depends_on": []}]}',
                    finish_reason=FinishReason.STOP,
                    usage=LLMUsage(prompt_tokens=10, completion_tokens=5),
                )
            if step_count == 2:
                # 第一步执行——返回错误触发 Replan
                return LLMResponse(
                    content="",
                    finish_reason=FinishReason.ERROR,
                    usage=LLMUsage(prompt_tokens=10, completion_tokens=5),
                )
            if step_count == 3:
                # Replanner
                return LLMResponse(
                    content='{"steps": [{"id": "s2", "description": "重试", "depends_on": []}]}',
                    finish_reason=FinishReason.STOP,
                    usage=LLMUsage(prompt_tokens=10, completion_tokens=5),
                )
            # 重试后执行
            return LLMResponse(
                content="重试成功",
                finish_reason=FinishReason.STOP,
                usage=LLMUsage(prompt_tokens=10, completion_tokens=5),
            )

        runtime.set_llm_executor(mock_llm)
        result = await runtime.run("重试测试")
        assert result.status == "ended"


# ============ WorkflowLoop 测试 ============


class TestWorkflowDefinition:
    """WorkflowDefinition 定义测试。"""

    def test_add_node(self) -> None:
        wf = WorkflowDefinition()
        node = FixedNode("greet", handler=lambda ctx: "hello")
        wf.add_node(node)
        assert wf.has_node("greet")

    def test_add_duplicate_node(self) -> None:
        wf = WorkflowDefinition()
        wf.add_node(FixedNode("n1", handler=lambda ctx: ""))
        with pytest.raises(Exception):
            wf.add_node(FixedNode("n1", handler=lambda ctx: ""))

    def test_add_edge(self) -> None:
        wf = WorkflowDefinition()
        wf.add_node(FixedNode("a", handler=lambda ctx: ""))
        wf.add_node(FixedNode("b", handler=lambda ctx: ""))
        wf.add_edge("a", "b")
        assert wf.next_node("a") == "b"

    def test_add_edge_invalid_node(self) -> None:
        wf = WorkflowDefinition()
        with pytest.raises(Exception):
            wf.add_edge("nonexistent", "b")

    def test_add_condition(self) -> None:
        wf = WorkflowDefinition()
        cn = ConditionNode("route", condition_fn=lambda ctx: "branch_a")
        wf.add_node(cn)
        wf.add_node(FixedNode("branch_a", handler=lambda ctx: ""))
        wf.add_condition("route", {"branch_a": "branch_a"})
        assert "route" in wf.conditions

    def test_add_condition_on_fixed_node(self) -> None:
        wf = WorkflowDefinition()
        fn = FixedNode("fixed", handler=lambda ctx: "")
        wf.add_node(fn)
        with pytest.raises(Exception):
            wf.add_condition("fixed", {"a": "b"})

    def test_get_nonexistent_node(self) -> None:
        wf = WorkflowDefinition()
        with pytest.raises(Exception):
            wf.get_node("nonexistent")

    def test_start_node(self) -> None:
        wf = WorkflowDefinition()
        wf.add_node(FixedNode("start", handler=lambda ctx: ""))
        wf.start_node_id = "start"
        assert wf.start_node_id == "start"

    def test_start_node_invalid(self) -> None:
        wf = WorkflowDefinition()
        with pytest.raises(Exception):
            wf.start_node_id = "nonexistent"

    def test_to_dict(self) -> None:
        wf = WorkflowDefinition(start_node_id="start")
        wf.add_node(FixedNode("start", handler=lambda ctx: ""))
        wf.add_node(FixedNode("end", handler=lambda ctx: ""))
        wf.add_edge("start", "end")
        d = wf.to_dict()
        assert d["start_node_id"] == "start"
        assert len(d["nodes"]) == 2
        assert len(d["edges"]) == 1

    def test_from_dict(self) -> None:
        """from_dict 应重建 WorkflowDefinition。"""
        data = {
            "start_node_id": "step1",
            "nodes": [
                {"id": "step1", "type": "fixed", "depends_on": []},
                {"id": "step2", "type": "fixed", "depends_on": ["step1"]},
                {"id": "route", "type": "condition", "depends_on": ["step2"]},
                {"id": "step3", "type": "agent", "depends_on": ["route"]},
            ],
            "edges": [
                {"from": "step1", "to": "step2"},
                {"from": "step2", "to": "route"},
            ],
            "conditions": {
                "route": {"branch_a": "step3", "branch_b": "step1"},
            },
        }
        wf = WorkflowDefinition.from_dict(data)
        assert wf.start_node_id == "step1"
        assert wf.has_node("step1")
        assert wf.has_node("route")
        assert wf.next_node("step1") == "step2"
        assert "route" in wf.conditions
        assert wf.conditions["route"].branches == {"branch_a": "step3", "branch_b": "step1"}

    def test_from_dict_roundtrip(self) -> None:
        """to_dict → from_dict 应保持结构一致。"""
        original = WorkflowDefinition(start_node_id="start")
        original.add_node(FixedNode("start", handler=lambda ctx: ""))
        original.add_node(FixedNode("end", handler=lambda ctx: ""))
        original.add_edge("start", "end")

        data = original.to_dict()
        restored = WorkflowDefinition.from_dict(data)
        assert restored.start_node_id == original.start_node_id
        assert restored.has_node("start")
        assert restored.has_node("end")
        assert restored.next_node("start") == "end"

    def test_init_with_nodes(self) -> None:
        nodes = [
            FixedNode("a", handler=lambda ctx: ""),
            FixedNode("b", handler=lambda ctx: ""),
        ]
        wf = WorkflowDefinition(nodes=nodes)
        assert wf.has_node("a")
        assert wf.has_node("b")
        assert wf.start_node_id == "a"


class TestWorkflowNodes:
    """WorkflowNode 各节点类型测试。"""

    async def test_fixed_node(self) -> None:
        node = FixedNode("test", handler=lambda ctx: "fixed_result")
        result = await node.execute(None, None)  # type: ignore[arg-type]
        assert result == "fixed_result"
        assert node.result == "fixed_result"

    async def test_agent_node(self) -> None:
        """AgentNode 需要 Runtime 上下文。"""
        runtime = AgentRuntime(system_prompt="助手")
        runtime.set_llm_executor(make_mock_executor("agent_result"))

        node = AgentNode("agent1")
        ctx = runtime._build_context()
        result = await node.execute(ctx, runtime._step_runner)
        assert isinstance(result, StepResult)
        assert node.node_id == "agent1"

    async def test_agent_node_no_runtime(self) -> None:
        """AgentNode 缺少 Runtime 时应报错。"""
        from src.runtime.context._context import RuntimeContext

        node = AgentNode("agent1")
        ctx = RuntimeContext()  # 没有 _runtime 服务
        with pytest.raises(Exception):
            await node.execute(ctx, None)  # type: ignore[arg-type]

    async def test_condition_node(self) -> None:
        node = ConditionNode("route", condition_fn=lambda ctx: "branch_a")
        result = await node.execute(None, None)  # type: ignore[arg-type]
        assert result == "branch_a"
        assert node.result == "branch_a"

    async def test_condition_node_async(self) -> None:
        async def async_condition(ctx):
            return "async_branch"

        node = ConditionNode("async_route", condition_fn=async_condition)
        result = await node.execute(None, None)  # type: ignore[arg-type]
        assert result == "async_branch"


class TestWorkflowLoop:
    """WorkflowLoop 执行测试。"""

    async def test_workflow_linear(self) -> None:
        """线性工作流。"""
        runtime = AgentRuntime(system_prompt="助手")
        runtime.set_llm_executor(make_mock_executor("wf_ok"))

        results: list[str] = []

        wf = WorkflowDefinition()
        wf.add_node(FixedNode("step1", handler=lambda ctx: results.append("s1")))
        wf.add_node(FixedNode("step2", handler=lambda ctx: results.append("s2")))
        wf.add_edge("step1", "step2")
        wf.start_node_id = "step1"

        runtime.set_loop_strategy(WorkflowLoop(
            hooks=runtime._hooks,
            step_runner=runtime._step_runner,
            workflow_definition=wf,
        ))
        await runtime.run("wf_test")
        assert results == ["s1", "s2"]
        assert runtime.status == "ended"

    async def test_workflow_condition(self) -> None:
        """条件分支工作流。"""
        runtime = AgentRuntime(system_prompt="助手")
        runtime.set_llm_executor(make_mock_executor("condition_ok"))

        path: list[str] = []

        wf = WorkflowDefinition()
        wf.add_node(FixedNode("start", handler=lambda ctx: path.append("start")))
        wf.add_node(ConditionNode("route", condition_fn=lambda ctx: "path_a"))
        wf.add_node(FixedNode("path_a", handler=lambda ctx: path.append("path_a")))
        wf.add_node(FixedNode("path_b", handler=lambda ctx: path.append("path_b")))
        wf.add_edge("start", "route")
        wf.add_condition("route", {"path_a": "path_a", "path_b": "path_b"})
        wf.start_node_id = "start"

        runtime.set_loop_strategy(WorkflowLoop(
            hooks=runtime._hooks,
            step_runner=runtime._step_runner,
            workflow_definition=wf,
        ))
        await runtime.run("condition_test")
        assert path == ["start", "path_a"]

    async def test_workflow_dependency_check(self) -> None:
        """依赖未就绪时报错。"""
        runtime = AgentRuntime(system_prompt="助手")

        wf = WorkflowDefinition()
        wf.add_node(FixedNode("step2", handler=lambda ctx: "", depends_on=["step1"]))
        wf.start_node_id = "step2"

        runtime.set_loop_strategy(WorkflowLoop(
            hooks=runtime._hooks,
            step_runner=runtime._step_runner,
            workflow_definition=wf,
        ))
        result = await runtime.run("dep_test")
        assert result.status == "error"
        assert "依赖未就绪" in result.content
