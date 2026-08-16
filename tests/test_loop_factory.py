"""
Loop 策略工厂/装配重构测试。

覆盖：
  - 工厂函数注册与 kwargs 透传
  - 内置策略懒注册（clear 后仍可按名创建、不覆盖用户同名注册）
  - AgentRuntime 按名 / 按类 / 实例三种装配方式
  - Builder .loop() 类传参与 kwargs 透传
  - RuntimeConfig.from_config 应用 loop 配置
"""

from __future__ import annotations

from typing import Any

import pytest

from src.runtime import AgentRuntime
from src.runtime._builder import RuntimeBuilder
from src.runtime.config import RuntimeConfig
from src.runtime.loops import (
    FixedNode,
    LoopStrategy,
    LoopStrategyFactory,
    ReActLoop,
    WorkflowDefinition,
    WorkflowLoop,
)


class TestLoopStrategyFactoryCustom:
    """LoopStrategyFactory 自定义策略注册测试。"""

    def setup_method(self) -> None:
        LoopStrategyFactory.clear()

    def test_register_factory_function(self) -> None:
        """注册工厂函数而非策略类，create 后可用。"""

        def make_loop(**kwargs: Any) -> LoopStrategy:
            return ReActLoop(
                hooks=kwargs.get("hooks"),
                step_runner=kwargs.get("step_runner"),
                controller=kwargs.get("controller"),
            )

        LoopStrategyFactory.register("custom_react", make_loop)
        assert "custom_react" in LoopStrategyFactory.available()
        loop = LoopStrategyFactory.create(
            "custom_react", hooks=None, step_runner=None, controller=None
        )
        assert isinstance(loop, ReActLoop)

    def test_create_passes_kwargs_to_factory_function(self) -> None:
        """工厂函数能收到 create 透传的 kwargs。"""
        captured: dict[str, Any] = {}

        def make_loop(**kwargs: Any) -> LoopStrategy:
            captured.update(kwargs)
            return ReActLoop(
                hooks=kwargs.get("hooks"),
                step_runner=kwargs.get("step_runner"),
                controller=kwargs.get("controller"),
            )

        LoopStrategyFactory.register("echo", make_loop)
        LoopStrategyFactory.create("echo", hooks=None, step_runner=None, controller=None, answer=42)
        assert captured["answer"] == 42

    def test_builtins_lazily_registered_after_clear(self) -> None:
        """clear() 后 create 内置名称仍可用（懒注册兜底）。"""
        LoopStrategyFactory.clear()
        loop = LoopStrategyFactory.create("react", hooks=None, step_runner=None, controller=None)
        assert isinstance(loop, ReActLoop)
        assert "react" in LoopStrategyFactory.available()
        assert "workflow" in LoopStrategyFactory.available()

    def test_builtins_do_not_clobber_user_registration(self) -> None:
        """用户注册同名策略优先，内置懒注册不覆盖。"""

        class CustomReAct(ReActLoop):
            """自定义同名策略。"""

        LoopStrategyFactory.register("react", CustomReAct)
        loop = LoopStrategyFactory.create("react", hooks=None, step_runner=None, controller=None)
        assert isinstance(loop, CustomReAct)

    def test_create_unknown_after_clear(self) -> None:
        """clear 后 create 未知名称仍抛 ValueError。"""
        LoopStrategyFactory.clear()
        with pytest.raises(ValueError, match="未知的策略"):
            LoopStrategyFactory.create("not_exist")


class TestAgentRuntimeLoopAssembly:
    """AgentRuntime 三种装配方式测试。"""

    def test_loop_by_name_with_kwargs(self) -> None:
        """按名创建并透传构造参数。"""
        runtime = AgentRuntime(
            system_prompt="助手",
            loop_strategy_name="react",
            loop_kwargs={"max_iterations": 3},
        )
        assert runtime._loop._max_iterations == 3

    def test_loop_by_class_with_kwargs(self) -> None:
        """按类创建并透传构造参数。"""
        wf = WorkflowDefinition()
        wf.add_node(FixedNode("a", handler=lambda ctx: "ok"))
        wf.start_node_id = "a"
        runtime = AgentRuntime(
            system_prompt="助手",
            loop_strategy_cls=WorkflowLoop,
            loop_kwargs={"workflow_definition": wf, "max_iterations": 5},
        )
        assert isinstance(runtime._loop, WorkflowLoop)
        assert runtime._loop._workflow is wf
        assert runtime._loop._max_iterations == 5


class TestBuilderLoopWiring:
    """RuntimeBuilder .loop() 装配测试。"""

    def test_loop_by_class_with_kwargs(self) -> None:
        """.loop(WorkflowLoop, workflow_definition=wf) 类传参可用。"""
        wf = WorkflowDefinition()
        wf.add_node(FixedNode("a", handler=lambda ctx: "ok"))
        wf.start_node_id = "a"
        runtime = (
            RuntimeBuilder()
            .system_prompt("助手")
            .loop(WorkflowLoop, workflow_definition=wf)
            .build()
        )
        assert isinstance(runtime._loop, WorkflowLoop)
        assert runtime._loop._workflow is wf

    def test_loop_by_name_with_kwargs(self) -> None:
        """.loop("plan_and_execute", max_replans=5) kwargs 透传。"""
        runtime = (
            RuntimeBuilder().system_prompt("助手").loop("plan_and_execute", max_replans=5).build()
        )
        assert runtime._loop._max_replans == 5

    def test_loop_by_custom_registered_name(self) -> None:
        """按名使用自定义注册策略并透传 kwargs。"""
        LoopStrategyFactory.clear()

        def make_custom(**kwargs: Any) -> LoopStrategy:
            return ReActLoop(
                hooks=kwargs.get("hooks"),
                step_runner=kwargs.get("step_runner"),
                controller=kwargs.get("controller"),
                max_iterations=int(kwargs.get("max_iterations", 10)),
            )

        LoopStrategyFactory.register("custom", make_custom)
        try:
            runtime = (
                RuntimeBuilder().system_prompt("助手").loop("custom", max_iterations=7).build()
            )
            assert runtime._loop._max_iterations == 7
        finally:
            LoopStrategyFactory.unregister("custom")

    def test_from_config_applies_loop(self) -> None:
        """from_config 真正应用 config.loop（strategy + kwargs）。"""
        config = RuntimeConfig(
            system_prompt="助手",
            loop={"strategy": "plan_and_execute", "max_replans": 4},
        )
        runtime = RuntimeBuilder().from_config(config).build()
        assert runtime._loop._max_replans == 4
