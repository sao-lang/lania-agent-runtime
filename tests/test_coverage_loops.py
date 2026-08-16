"""
Loop 策略覆盖率补测。

针对 PlanExecuteLoop / ReActLoop / WorkflowLoop 中未被既有测试覆盖的
分支路径：状态中断、拦截、Router 结束、Replan、流式执行、节点类型序列化等。
"""

from __future__ import annotations

from typing import Any

import pytest

from src.runtime._runtime import AgentRuntime
from src.runtime._types import BlockAction, HookPoint, PrimitiveType, RuntimeStatus
from src.runtime.llm._models import FinishReason, LLMResponse, LLMUsage, ToolCall
from src.runtime.loops import (
    AgentNode,
    ConditionNode,
    FixedNode,
    PlanExecuteLoop,
    ReActLoop,
    StepResult,
    StepStatus,
    WorkflowDefinition,
    WorkflowLoop,
)
from src.runtime.loops._workflow import WorkflowError

PLAN_JSON = '{"steps": [{"id": "s1", "description": "第一步", "depends_on": []}]}'
REPLAN_JSON = '{"steps": [{"id": "s2", "description": "重试", "depends_on": []}]}'
REPLAN_SAME_JSON = '{"steps": [{"id": "s1", "description": "同一步", "depends_on": []}]}'


def llm_plan(json_text: str) -> LLMResponse:
    """包装计划 JSON 为 LLMResponse（run_llm_only 返回类型）。"""
    return LLMResponse(content=json_text, finish_reason=FinishReason.STOP, usage=LLMUsage())


class StubStepRunner:
    """可编程 StepRunner 替身（覆盖 run_step / run_llm_only）。"""

    def __init__(
        self,
        run_step_result: StepResult | None = None,
        llm_responses: list[Any] | None = None,
    ) -> None:
        self._run_step_result = run_step_result
        self._llm_responses = list(llm_responses or [])
        self.run_step_calls = 0
        self.run_llm_calls = 0

    async def run_step(self, ctx: Any, ctl: Any) -> StepResult:
        self.run_step_calls += 1
        if self._run_step_result is None:
            return StepResult(content="ok")
        return self._run_step_result

    async def run_llm_only(self, ctx: Any, ctl: Any) -> Any:
        self.run_llm_calls += 1
        if not self._llm_responses:
            return None
        if len(self._llm_responses) == 1:
            return self._llm_responses[0]
        return self._llm_responses.pop(0)


def make_runtime(loop_strategy_name: str = "react") -> AgentRuntime:
    """构造带指定 loop 的 Runtime，并置为 RUNNING（直接调用 loop 需模拟 run() 状态）。"""
    runtime = AgentRuntime(system_prompt="助手", loop_strategy_name=loop_strategy_name)
    runtime.status = RuntimeStatus.RUNNING
    return runtime


async def _async_end_router(ctx: Any) -> str:
    """异步 Router：返回 end 结束循环。"""
    return "end"


def make_plan_loop(
    runtime: AgentRuntime,
    stub: StubStepRunner,
    *,
    max_replans: int = 3,
    max_iterations: int = 20,
    router: Any = None,
) -> PlanExecuteLoop:
    """直接构造 PlanExecuteLoop（绕过 runtime 的循环，便于注入 stub）。"""
    return PlanExecuteLoop(
        hooks=runtime._hooks,
        step_runner=stub,
        controller=runtime._controller,
        router=router,
        max_replans=max_replans,
        max_iterations=max_iterations,
    )


class TestPlanExecuteCoverage:
    """PlanExecuteLoop 未覆盖分支。"""

    async def test_before_step_blocked(self) -> None:
        runtime = make_runtime("plan_and_execute")

        @runtime.on(HookPoint.BEFORE_STEP, primitive=PrimitiveType.INTERCEPT)
        async def block(data: Any, ctx: Any) -> BlockAction:
            return BlockAction(reason="block")

        loop = make_plan_loop(runtime, StubStepRunner(llm_responses=[llm_plan(PLAN_JSON)]))
        await loop.run(runtime._build_context())
        assert runtime.status == RuntimeStatus.ERROR

    async def test_planner_returns_none(self) -> None:
        runtime = make_runtime("plan_and_execute")
        loop = make_plan_loop(runtime, StubStepRunner(llm_responses=[None]))
        await loop.run(runtime._build_context())
        assert runtime.status == RuntimeStatus.ERROR

    async def test_planner_invalid_json(self) -> None:
        runtime = make_runtime("plan_and_execute")
        loop = make_plan_loop(runtime, StubStepRunner(llm_responses=[llm_plan("不是 JSON")]))
        await loop.run(runtime._build_context())
        assert runtime.status == RuntimeStatus.ERROR

    async def test_planner_code_block_json(self) -> None:
        runtime = make_runtime("plan_and_execute")
        stub = StubStepRunner(
            run_step_result=StepResult(content="完成"),
            llm_responses=[llm_plan(f"```json\n{PLAN_JSON}\n```")],
        )
        loop = make_plan_loop(runtime, stub)
        await loop.run(runtime._build_context())
        assert runtime.status != RuntimeStatus.ERROR
        assert stub.run_step_calls == 1

    async def test_status_not_running_breaks(self) -> None:
        runtime = make_runtime("plan_and_execute")
        loop = make_plan_loop(runtime, StubStepRunner(llm_responses=[llm_plan(PLAN_JSON)]))
        runtime.status = RuntimeStatus.PAUSED
        await loop.run(runtime._build_context())
        assert runtime.status == RuntimeStatus.PAUSED

    async def test_max_iterations_breaks(self) -> None:
        runtime = make_runtime("plan_and_execute")
        plan_3_steps = (
            '{"steps": [{"id": "a", "description": "a", "depends_on": []},'
            '{"id": "b", "description": "b", "depends_on": []},'
            '{"id": "c", "description": "c", "depends_on": []}]}'
        )
        loop = make_plan_loop(
            runtime,
            StubStepRunner(llm_responses=[llm_plan(plan_3_steps)]),
            max_iterations=1,
        )
        await loop.run(runtime._build_context())
        assert runtime.status == RuntimeStatus.RUNNING
        assert runtime._controller.budget.step_count == 1

    async def test_router_end_breaks(self) -> None:
        runtime = make_runtime("plan_and_execute")
        loop = make_plan_loop(
            runtime,
            StubStepRunner(llm_responses=[llm_plan(PLAN_JSON)]),
            router=_async_end_router,
        )
        await loop.run(runtime._build_context())
        assert runtime._controller.budget.step_count == 0

    async def test_blocked_step_breaks(self) -> None:
        runtime = make_runtime("plan_and_execute")
        loop = make_plan_loop(
            runtime,
            StubStepRunner(
                run_step_result=StepResult(status=StepStatus.BLOCKED),
                llm_responses=[llm_plan(PLAN_JSON)],
            ),
        )
        await loop.run(runtime._build_context())
        assert runtime._controller.budget.step_count == 1

    async def test_paused_step_breaks(self) -> None:
        runtime = make_runtime("plan_and_execute")
        loop = make_plan_loop(
            runtime,
            StubStepRunner(
                run_step_result=StepResult(status=StepStatus.PAUSED),
                llm_responses=[llm_plan(PLAN_JSON)],
            ),
        )
        await loop.run(runtime._build_context())
        assert runtime._controller.budget.step_count == 1

    async def test_error_step_breaks(self) -> None:
        runtime = make_runtime("plan_and_execute")
        loop = make_plan_loop(
            runtime,
            StubStepRunner(
                run_step_result=StepResult(status=StepStatus.ERROR),
                llm_responses=[llm_plan(PLAN_JSON)],
            ),
        )
        await loop.run(runtime._build_context())
        assert runtime._controller.budget.step_count == 1

    async def test_replan_on_empty_content(self) -> None:
        runtime = make_runtime("plan_and_execute")
        stub = StubStepRunner(
            run_step_result=StepResult(content="", finish_reason=FinishReason.STOP),
            llm_responses=[llm_plan(PLAN_JSON), llm_plan(REPLAN_JSON)],
        )
        loop = make_plan_loop(runtime, stub, max_replans=1)
        await loop.run(runtime._build_context())
        assert stub.run_llm_calls == 2  # planner + replanner
        assert loop._replan_count == 1

    async def test_replan_find_same_step(self) -> None:
        runtime = make_runtime("plan_and_execute")
        stub = StubStepRunner(
            run_step_result=StepResult(content="", finish_reason=FinishReason.STOP),
            llm_responses=[llm_plan(PLAN_JSON), llm_plan(REPLAN_SAME_JSON)],
        )
        loop = make_plan_loop(runtime, stub, max_replans=1)
        await loop.run(runtime._build_context())
        assert loop._replan_count == 1

    async def test_replan_replanner_fails(self) -> None:
        runtime = make_runtime("plan_and_execute")
        stub = StubStepRunner(
            run_step_result=StepResult(content="", finish_reason=FinishReason.STOP),
            llm_responses=[llm_plan(PLAN_JSON), None],
        )
        loop = make_plan_loop(runtime, stub, max_replans=1)
        await loop.run(runtime._build_context())
        assert loop._replan_count == 0
        assert stub.run_step_calls == 1

    async def test_create_step_result_non_llm(self) -> None:
        runtime = make_runtime("plan_and_execute")
        loop = make_plan_loop(runtime, StubStepRunner())
        result = loop._create_step_result("hello")
        assert result.content == "hello"
        assert result.status == StepStatus.SUCCESS

    async def test_run_stream_basic(self) -> None:
        runtime = make_runtime("plan_and_execute")
        stub = StubStepRunner(
            run_step_result=StepResult(content="流式结果"),
            llm_responses=[llm_plan(PLAN_JSON)],
        )
        loop = make_plan_loop(runtime, stub)
        events = [e async for e in loop.run_stream(runtime._build_context())]
        types = [e["type"] for e in events]
        assert "plan_start" in types
        assert "plan_ready" in types
        assert "step_start" in types
        assert {"type": "text", "content": "流式结果"} in events

    async def test_run_stream_planner_none(self) -> None:
        runtime = make_runtime("plan_and_execute")
        loop = make_plan_loop(runtime, StubStepRunner(llm_responses=[None]))
        events = [e async for e in loop.run_stream(runtime._build_context())]
        assert any(e["type"] == "error" and "规划失败" in e["error"] for e in events)

    async def test_run_stream_before_step_blocked(self) -> None:
        runtime = make_runtime("plan_and_execute")

        @runtime.on(HookPoint.BEFORE_STEP, primitive=PrimitiveType.INTERCEPT)
        async def block(data: Any, ctx: Any) -> BlockAction:
            return BlockAction(reason="block")

        loop = make_plan_loop(runtime, StubStepRunner(llm_responses=[llm_plan(PLAN_JSON)]))
        events = [e async for e in loop.run_stream(runtime._build_context())]
        assert any(e["type"] == "error" and "拦截" in e["error"] for e in events)

    async def test_run_stream_tool_events(self) -> None:
        runtime = make_runtime("plan_and_execute")
        step_result = StepResult(
            tool_calls=[ToolCall(id="t1", name="search", arguments={})],
        )
        loop = make_plan_loop(
            runtime,
            StubStepRunner(run_step_result=step_result, llm_responses=[llm_plan(PLAN_JSON)]),
        )
        events = [e async for e in loop.run_stream(runtime._build_context())]
        types = [e["type"] for e in events]
        assert "tool_start" in types
        assert "tool_end" in types

    async def test_run_stream_replan(self) -> None:
        runtime = make_runtime("plan_and_execute")
        stub = StubStepRunner(
            run_step_result=StepResult(content="", finish_reason=FinishReason.STOP),
            llm_responses=[llm_plan(PLAN_JSON), llm_plan(REPLAN_JSON)],
        )
        loop = make_plan_loop(runtime, stub, max_replans=1)
        events = [e async for e in loop.run_stream(runtime._build_context())]
        types = [e["type"] for e in events]
        assert "replan_start" in types
        assert "replan_ready" in types

    async def test_parse_plan_empty(self) -> None:
        runtime = make_runtime("plan_and_execute")
        loop = make_plan_loop(runtime, StubStepRunner())
        assert loop._parse_plan("") is None
        assert loop._parse_plan("no json here") is None


class TestReActCoverage:
    """ReActLoop 未覆盖分支。"""

    async def test_status_not_running_breaks(self) -> None:
        runtime = make_runtime("react")
        runtime.status = RuntimeStatus.PAUSED
        loop = ReActLoop(
            hooks=runtime._hooks,
            step_runner=StubStepRunner(),
            controller=runtime._controller,
        )
        await loop.run(runtime._build_context())
        assert runtime._controller.budget.step_count == 0

    async def test_before_step_blocked(self) -> None:
        runtime = make_runtime("react")

        @runtime.on(HookPoint.BEFORE_STEP, primitive=PrimitiveType.INTERCEPT)
        async def block(data: Any, ctx: Any) -> BlockAction:
            return BlockAction(reason="block")

        loop = ReActLoop(
            hooks=runtime._hooks,
            step_runner=StubStepRunner(),
            controller=runtime._controller,
        )
        await loop.run(runtime._build_context())
        assert runtime.status == RuntimeStatus.ERROR

    async def test_router_end(self) -> None:
        runtime = make_runtime("react")
        loop = ReActLoop(
            hooks=runtime._hooks,
            step_runner=StubStepRunner(),
            controller=runtime._controller,
            router=_async_end_router,
        )
        await loop.run(runtime._build_context())
        assert runtime._controller.budget.step_count == 0

    async def test_blocked_step_breaks(self) -> None:
        runtime = make_runtime("react")
        loop = ReActLoop(
            hooks=runtime._hooks,
            step_runner=StubStepRunner(run_step_result=StepResult(status=StepStatus.BLOCKED)),
            controller=runtime._controller,
        )
        await loop.run(runtime._build_context())
        assert runtime._controller.budget.step_count == 1

    async def test_paused_step_breaks(self) -> None:
        runtime = make_runtime("react")
        loop = ReActLoop(
            hooks=runtime._hooks,
            step_runner=StubStepRunner(run_step_result=StepResult(status=StepStatus.PAUSED)),
            controller=runtime._controller,
        )
        await loop.run(runtime._build_context())
        assert runtime._controller.budget.step_count == 1

    async def test_error_step_breaks(self) -> None:
        runtime = make_runtime("react")
        loop = ReActLoop(
            hooks=runtime._hooks,
            step_runner=StubStepRunner(run_step_result=StepResult(status=StepStatus.ERROR)),
            controller=runtime._controller,
        )
        await loop.run(runtime._build_context())
        assert runtime._controller.budget.step_count == 1

    async def test_router_continue_then_stop(self) -> None:
        """Router 返回 continue 后下一轮返回 end。"""
        runtime = make_runtime("react")
        decisions = iter(["continue", "end"])

        async def router_fn(ctx: Any) -> str:
            return next(decisions)

        loop = ReActLoop(
            hooks=runtime._hooks,
            step_runner=StubStepRunner(),
            controller=runtime._controller,
            router=router_fn,
        )
        await loop.run(runtime._build_context())
        assert runtime._controller.budget.step_count >= 1

    async def test_max_iterations_for_else(self) -> None:
        """tool_calls 持续返回直到 max_iterations 耗尽（for-else）。"""
        runtime = make_runtime("react")
        loop = ReActLoop(
            hooks=runtime._hooks,
            step_runner=StubStepRunner(
                run_step_result=StepResult(
                    finish_reason=FinishReason.TOOL_CALLS,
                    tool_calls=[ToolCall(id="t", name="tool", arguments={})],
                )
            ),
            controller=runtime._controller,
            max_iterations=2,
        )
        await loop.run(runtime._build_context())
        assert runtime._controller.budget.step_count == 2

    async def test_run_stream_basic(self) -> None:
        runtime = make_runtime("react")
        loop = ReActLoop(
            hooks=runtime._hooks,
            step_runner=StubStepRunner(run_step_result=StepResult(content="hi")),
            controller=runtime._controller,
        )
        events = [e async for e in loop.run_stream(runtime._build_context())]
        types = [e["type"] for e in events]
        assert "llm_start" in types
        assert {"type": "text", "content": "hi"} in events

    async def test_run_stream_tool_events(self) -> None:
        runtime = make_runtime("react")
        loop = ReActLoop(
            hooks=runtime._hooks,
            step_runner=StubStepRunner(
                run_step_result=StepResult(
                    tool_calls=[ToolCall(id="t1", name="search", arguments={})]
                )
            ),
            controller=runtime._controller,
        )
        events = [e async for e in loop.run_stream(runtime._build_context())]
        types = [e["type"] for e in events]
        assert "tool_start" in types
        assert "tool_end" in types

    async def test_run_stream_before_step_blocked(self) -> None:
        runtime = make_runtime("react")

        @runtime.on(HookPoint.BEFORE_STEP, primitive=PrimitiveType.INTERCEPT)
        async def block(data: Any, ctx: Any) -> BlockAction:
            return BlockAction(reason="block")

        loop = ReActLoop(
            hooks=runtime._hooks,
            step_runner=StubStepRunner(),
            controller=runtime._controller,
        )
        events = [e async for e in loop.run_stream(runtime._build_context())]
        assert any(e["type"] == "error" and "拦截" in e["error"] for e in events)

    async def test_run_stream_router_end(self) -> None:
        runtime = make_runtime("react")
        loop = ReActLoop(
            hooks=runtime._hooks,
            step_runner=StubStepRunner(),
            controller=runtime._controller,
            router=_async_end_router,
        )
        events = [e async for e in loop.run_stream(runtime._build_context())]
        assert events == []

    async def test_create_step_result_non_llm(self) -> None:
        runtime = make_runtime("react")
        loop = ReActLoop(
            hooks=runtime._hooks,
            step_runner=StubStepRunner(),
            controller=runtime._controller,
        )
        result = loop._create_step_result("hi")
        assert result.content == "hi"


class TestWorkflowCoverage:
    """WorkflowLoop 未覆盖分支。"""

    async def test_run_stream_linear(self) -> None:
        runtime = make_runtime("react")

        async def mock_llm(ctx: Any) -> LLMResponse:
            return LLMResponse(content="ok", finish_reason=FinishReason.STOP)

        runtime.set_llm_executor(mock_llm)
        wf = WorkflowDefinition()
        wf.add_node(FixedNode("s1", handler=lambda ctx: "r1"))
        wf.add_node(FixedNode("s2", handler=lambda ctx: "r2"))
        wf.add_edge("s1", "s2")
        wf.start_node_id = "s1"
        loop = WorkflowLoop(
            hooks=runtime._hooks,
            step_runner=runtime._step_runner,
            controller=runtime._controller,
            workflow_definition=wf,
        )
        events = [e async for e in loop.run_stream(runtime._build_context())]
        types = [e["type"] for e in events]
        assert types.count("node_start") == 2
        assert types.count("node_end") == 2

    async def test_run_stream_dependency_error(self) -> None:
        runtime = make_runtime("react")
        wf = WorkflowDefinition()
        wf.add_node(FixedNode("b", handler=lambda ctx: "", depends_on=["a"]))
        wf.start_node_id = "b"
        loop = WorkflowLoop(
            hooks=runtime._hooks,
            step_runner=StubStepRunner(),
            controller=runtime._controller,
            workflow_definition=wf,
        )
        events = [e async for e in loop.run_stream(runtime._build_context())]
        assert any("依赖未就绪" in e.get("error", "") for e in events)

    async def test_run_status_not_running_breaks(self) -> None:
        runtime = make_runtime("react")
        runtime.status = RuntimeStatus.PAUSED
        wf = WorkflowDefinition()
        wf.add_node(FixedNode("a", handler=lambda ctx: ""))
        wf.start_node_id = "a"
        loop = WorkflowLoop(
            hooks=runtime._hooks,
            step_runner=StubStepRunner(),
            controller=runtime._controller,
            workflow_definition=wf,
        )
        await loop.run(runtime._build_context())
        assert runtime.status == RuntimeStatus.PAUSED

    async def test_condition_without_mapping(self) -> None:
        runtime = make_runtime("react")
        wf = WorkflowDefinition()
        wf.add_node(ConditionNode("route", condition_fn=lambda ctx: "x"))
        wf.start_node_id = "route"
        loop = WorkflowLoop(
            hooks=runtime._hooks,
            step_runner=StubStepRunner(),
            controller=runtime._controller,
            workflow_definition=wf,
        )
        await loop.run(runtime._build_context())
        assert runtime._controller.budget.step_count == 1

    async def test_condition_branch_missing(self) -> None:
        runtime = make_runtime("react")
        wf = WorkflowDefinition()
        wf.add_node(FixedNode("a", handler=lambda ctx: ""))
        wf.add_node(ConditionNode("route", condition_fn=lambda ctx: "missing"))
        wf.add_edge("a", "route")
        wf.add_condition("route", {"known": "a"})
        wf.start_node_id = "a"
        loop = WorkflowLoop(
            hooks=runtime._hooks,
            step_runner=StubStepRunner(),
            controller=runtime._controller,
            workflow_definition=wf,
        )
        await loop.run(runtime._build_context())
        assert runtime._controller.budget.step_count == 2

    async def test_agent_node_with_system_prompt(self) -> None:
        runtime = make_runtime("react")

        async def mock_agent(ctx: Any) -> LLMResponse:
            return LLMResponse(content="agent", finish_reason=FinishReason.STOP)

        runtime.set_llm_executor(mock_agent)
        wf = WorkflowDefinition()
        wf.add_node(AgentNode("agent", system_prompt="定制提示词"))
        wf.start_node_id = "agent"
        loop = WorkflowLoop(
            hooks=runtime._hooks,
            step_runner=runtime._step_runner,
            controller=runtime._controller,
            workflow_definition=wf,
        )
        await loop.run(runtime._build_context())
        assert runtime._controller.budget.step_count == 1

    async def test_create_step_result(self) -> None:
        runtime = make_runtime("react")
        loop = WorkflowLoop(
            hooks=runtime._hooks,
            step_runner=StubStepRunner(),
            controller=runtime._controller,
            workflow_definition=WorkflowDefinition(),
        )
        sr = StepResult(content="passthrough")
        assert loop._create_step_result(sr) is sr
        converted = loop._create_step_result("text")
        assert converted.content == "text"

    def test_to_dict_all_types(self) -> None:
        wf = WorkflowDefinition()
        wf.add_node(FixedNode("f", handler=lambda ctx: ""))
        wf.add_node(AgentNode("a"))
        wf.add_node(ConditionNode("c", condition_fn=lambda ctx: "x"))
        d = wf.to_dict()
        types = {n["id"]: n["type"] for n in d["nodes"]}
        assert types == {"f": "fixed", "a": "agent", "c": "condition"}

    def test_from_dict_unknown_type_falls_back_to_fixed(self) -> None:
        data = {
            "start_node_id": "x",
            "nodes": [{"id": "x", "type": "unknown", "depends_on": []}],
            "edges": [],
            "conditions": {},
        }
        wf = WorkflowDefinition.from_dict(data)
        assert isinstance(wf.get_node("x"), FixedNode)

    def test_from_dict_default_start_node(self) -> None:
        data = {
            "nodes": [{"id": "n1", "type": "fixed", "depends_on": []}],
            "edges": [],
            "conditions": {},
        }
        wf = WorkflowDefinition.from_dict(data)
        assert wf.start_node_id == "n1"

    def test_next_node_none(self) -> None:
        wf = WorkflowDefinition()
        wf.add_node(FixedNode("solo", handler=lambda ctx: ""))
        assert wf.next_node("solo") is None

    def test_add_condition_invalid_target(self) -> None:
        wf = WorkflowDefinition()
        wf.add_node(ConditionNode("route", condition_fn=lambda ctx: "x"))
        with pytest.raises(WorkflowError, match="分支目标节点"):
            wf.add_condition("route", {"x": "missing"})
