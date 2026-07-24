"""
EngineSettersMixin——AgentRuntime 的引擎替换 + 组件管理方法集。

提取自 AgentRuntime，职责：替换 LLM/Tool/Loop 执行器、管理组件生命周期。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.runtime._types import ExecutorFn, RouterFn

if TYPE_CHECKING:
    from src.runtime.loops._base import LoopStrategy
    from src.runtime.plugins._plugin import PluggableComponent


class EngineSettersMixin:
    """引擎替换 + 组件管理方法集。"""

    # ============ 引擎替换 ============

    def set_router(self, router: RouterFn) -> None:
        """
        替换 _next() 行为——如 Chain / Router / Parallel / Orch / Handoff。

        Args:
            router: Router 函数。
        """
        self._router = router

    def set_llm_executor(self, executor: ExecutorFn | Any) -> None:
        """
        替换 LLM 调用实现——如 OpenAI → Claude 切换。

        同时兼容两种接口：
          - LLMExecutor 对象（新）：自动调用 executor.execute(ctx)
          - ExecutorFn 函数（旧）：直接 executor(ctx)

        Args:
            executor: LLMExecutor 实例或 ExecutorFn 函数。
        """
        self._llm_executor = executor
        # 同步更新 StepRunner（保持引用一致）
        self._step_runner._llm_executor = executor

    def set_tool_executor(self, executor: ExecutorFn) -> None:
        """
        替换工具执行实现。

        Args:
            executor: Tool Executor 函数。
        """
        self._tool_executor = executor
        # 同步更新 StepRunner（保持引用一致）
        self._step_runner._tool_executor = executor

    def set_loop_executor(self, executor: ExecutorFn) -> None:
        """
        替换 Step Loop 实现——如 ReAct → PlanExecute → Workflow。

        Args:
            executor: Loop Executor 函数（旧接口）。
        """
        self._loop_executor = executor
        self._loop = None

    # TODO: Multi-Agent Agent-as-tool
    # register_tool() 方法将在 tools 体系设计完成后添加。
    # 当前工具通过 set_tool_executor() 注入单一执行器。
    # 详见 tools 体系设计文档（待实现）。
    # 设计参考: docs/design/loop-strategy-design.md §3.1

    def set_loop_strategy(self, strategy: "LoopStrategy") -> None:
        """
        设置 LoopStrategy（新接口）。

        替换当前循环策略，如 ReActLoop → PlanExecuteLoop → WorkflowLoop。

        Args:
            strategy: LoopStrategy 实例。
        """
        self._loop = strategy
        self._loop_executor = None

    # ============ 组件管理 ============

    async def use(self, component: "PluggableComponent") -> str:
        """
        挂载一个组件/插件到 Runtime。

        统一入口处理所有模块的集成。
        调用 component.on_attach(self) 让组件自行注册 hooks/executors。

        Args:
            component: 要挂载的组件。

        Returns:
            component.name，用于后续管理。
        """
        await component.on_attach(self)
        self._components[component.name] = component
        return component.name

    async def remove_component(self, name: str) -> None:
        """
        卸载指定名称的组件。

        Args:
            name: 组件名称。
        """
        component = self._components.pop(name, None)
        if component is not None:
            await component.on_detach()
