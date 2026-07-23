"""
Loop 策略抽象基类——LoopStrategy ABC。

定义所有 LoopStrategy 的共同接口：
  - run() / run_stream() 两种执行模式
  - 共享的步级 hook 调用（before_step / after_step）
  - 运行时状态检查（pause / cancel / error）
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, AsyncIterator

from src.runtime.loops._types import StepResult

if TYPE_CHECKING:
    from src.runtime.context._context import RuntimeContext
    from src.runtime._steps._step_runner import StepRunner
    from src.runtime.hooks._registry import HookRegistry


class LoopStrategy(ABC):
    """
    循环策略抽象基类。

    所有 LoopStrategy 实现（ReActLoop / PlanExecuteLoop / WorkflowLoop）
    必须继承此类并实现 run() 和 run_stream() 方法。

    职责：管理"循环的节奏"——
      - 步级 hook（before_step / after_step）调用
      - 循环终止条件判断
      - 执行状态维护（pause / cancel / error 响应）
    单步逻辑委托给 StepRunner。
    """

    def __init__(
        self,
        hooks: HookRegistry,
        step_runner: StepRunner,
        router: Any | None = None,
    ) -> None:
        """
        初始化 LoopStrategy。

        Args:
            hooks: HookRegistry 实例，用于调用步级 hook。
            step_runner: StepRunner 实例，封装单步执行逻辑。
            router: 可选的路由函数，用于覆盖默认的结束判断。
        """
        self._hooks = hooks
        self._step_runner = step_runner
        self._router = router

    # ============ 公共接口 ============

    @abstractmethod
    async def run(self, ctx: RuntimeContext) -> None:
        """
        主入口：非流式执行循环。

        修改 ctx 关联的 Runtime 内部状态（messages / budget 等），
        不返回值——调用方通过 Runtime._make_result() 构造 RunResult。

        Args:
            ctx: RuntimeContext 实例（含会话 ID、消息列表、预算等）。
        """
        ...

    @abstractmethod
    async def run_stream(
        self,
        ctx: RuntimeContext,
    ) -> AsyncIterator[dict]:
        """
        主入口：流式执行循环，逐事件产出。

        Args:
            ctx: RuntimeContext 实例。

        Yields:
            流式事件字典，兼容现有 StreamEvent 格式。
        """
        ...  # pragma: no cover
        if False:
            yield  # 使方法成为生成器

    # ============ 步级 hook 帮助方法 ============

    async def _run_before_step_hooks(self, ctx: RuntimeContext) -> bool:
        """
        执行完整步前 hook 管线：Interceptor → Transformer → Observer。

        Interceptor 可阻断/暂停当前步骤；Transformer 做上下文注入；
        Observer 记录步骤开始事件（日志/监控）。

        Args:
            ctx: RuntimeContext 实例。

        Returns:
            True 表示被 Interceptor 阻断，False 表示正常通过。
        """
        from src.runtime._types import BlockAction, HookPoint

        # before_step interceptor（先阻断检查，再执行 Transform）
        intercept_result = await self._hooks.run_interceptors(HookPoint.BEFORE_STEP, {}, ctx)
        if isinstance(intercept_result, BlockAction):
            return True  # 被阻断，调用方应停止执行

        # before_step transformers（上下文注入、RAG 等）
        await self._hooks.run_transformers(HookPoint.BEFORE_STEP, {}, ctx)

        # before_step observers（日志/监控）
        await self._hooks.run_observers(
            HookPoint.BEFORE_STEP,
            {"type": "before_step", "step_index": ctx.step_index},
            ctx,
        )
        return False  # 正常通过

    async def _run_after_step_hooks(self, ctx: RuntimeContext) -> None:
        """
        执行完整步后 hook 管线：Transformer → Observer。

        Transformer 处理步骤结果（Memory Bank 写入等）；
        Observer 记录步骤完成事件（日志/监控）。

        Args:
            ctx: RuntimeContext 实例。
        """
        from src.runtime._types import HookPoint

        # after_step transformers（处理步骤结果）
        await self._hooks.run_transformers(HookPoint.AFTER_STEP, {}, ctx)

        # after_step observers（日志/监控）
        await self._hooks.run_observers(
            HookPoint.AFTER_STEP,
            {"type": "after_step", "step_index": ctx.step_index},
            ctx,
        )

    # ============ 运行时状态检查 ============

    def _should_stop(self, ctx: RuntimeContext) -> bool:
        """
        检查是否需要提前停止循环。

        检查项：
          - Runtime 状态变为非 running
          - 已取消
          - 已暂停
          - 已出错

        Args:
            ctx: RuntimeContext 实例。

        Returns:
            True 表示需要停止，False 表示继续。
        """
        # 通过 ctx 无法直接访问 Runtime 的 status/cancelled，
        # 这些状态由 Runtime 内部字段维护，LoopStrategy 通过
        # Runtime 传递的检查器来判断。
        # 子类自行在 run() 中维护一个 `_running` 状态。
        return False  # 基类提供空实现，子类覆写

    @abstractmethod
    def _create_step_result(self, response: Any) -> StepResult:
        """
        将 LLM 响应或执行结果封装为 StepResult。

        Args:
            response: LLM 执行结果。

        Returns:
            标准化的 StepResult 实例。
        """
        ...
