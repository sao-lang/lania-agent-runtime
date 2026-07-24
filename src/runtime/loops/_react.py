"""
ReActLoop —— 边思考边行动策略。

对应设计文档 §2.1 ReActLoop。
每步通过 StepRunner.run_step() 执行一次 LLM 调用 + 可能的工具调用，
由 finish_reason 决定循环终止条件。
Router 可覆盖默认的结束行为。
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, AsyncIterator

from src.runtime.loops._base import LoopStrategy
from src.runtime.loops._types import StepResult, StepStatus

if TYPE_CHECKING:
    from src.runtime.context._context import RuntimeContext


class ReActLoop(LoopStrategy):
    """
    边思考边行动策略。

    最通用的 Agent 循环结构：
      1. before_step hooks（Memory Bank 读取）
      2. StepRunner.run_step() 执行一次 LLM 调用 + 可能的工具调用
      3. after_step hooks（Memory Bank 写入）
      4. 根据结果判断是否继续

    适用场景：通用对话、简单工具调用、单步决策。
    """

    def __init__(
        self,
        hooks: Any,
        step_runner: Any,
        controller: Any,
        router: Any | None = None,
        max_iterations: int = 10,
    ) -> None:
        """
        初始化 ReActLoop。

        Args:
            hooks: HookRegistry 实例。
            step_runner: StepRunner 实例。
            controller: RuntimeController 实例。
            router: 可选的路由函数，每次 LLM 结束后调用决定是否继续。
            max_iterations: 最大执行步数，默认 10。
        """
        super().__init__(hooks, step_runner, controller, router)
        self._max_iterations = max_iterations

    async def run(self, ctx: RuntimeContext) -> None:
        """
        非流式执行 ReAct 循环。

        从 ctx 关联的 Runtime 中获取状态并更新。
        循环条件：
          - step.status == "blocked" → break
          - step.finish_reason in ("stop", "length") → 检查 Router 后 break
          - step.finish_reason == "tool_calls" → continue（继续下一步）
          - step.finish_reason == "error" → break

        Args:
            ctx: RuntimeContext 实例。
        """
        ctl = self._controller

        for iteration in range(self._max_iterations):
            # 检查 Runtime 状态
            if ctl.status != "running":
                break

            # 步前 hook：Interceptor → Transformer → Observer
            if await self._run_before_step_hooks(ctx):
                ctl.status = "error"
                break  # 被 Interceptor 阻断

            # Router：决定步骤类型（默认走 LLM）
            next_step_type = await self._get_router_decision(ctx)
            if next_step_type == "end":
                break

            # 更新 step 计数
            ctl.step_index += 1
            ctl.timeout["step_start_at"] = int(time.time() * 1000)
            ctx = ctl.build_context()

            # 执行单步（委托给 StepRunner，传入 controller）
            step_result: StepResult = await self._step_runner.run_step(ctx, ctl)

            # 步后 hook：Transformer → Observer
            await self._run_after_step_hooks(ctx)
            ctl.budget.step_count += 1

            # 记录 step history
            ctl.step_history.append({
                "step_index": ctl.step_index,
                "step_id": f"react_{iteration}",
                "timestamp": time.time(),
                "finish_reason": step_result.finish_reason.value,
            })

            # 根据结果判断是否继续
            if step_result.is_blocked:
                break
            if step_result.status == StepStatus.PAUSED:
                break
            if step_result.status == StepStatus.ERROR:
                break
            if step_result.finish_reason.value in ("stop", "length"):
                # 有 Router 时由 Router 决定是否继续
                if self._router is not None:
                    router_decision = await self._router(ctx)
                    if router_decision == "continue":
                        continue
                break
            # finish_reason == "tool_calls"：继续循环
            if step_result.finish_reason.value == "tool_calls":
                continue
        else:
            # 循环正常结束（达到 max_iterations）
            pass

    async def run_stream(self, ctx: RuntimeContext) -> AsyncIterator[dict]:
        """
        流式执行 ReAct 循环，逐事件产出。

        Args:
            ctx: RuntimeContext 实例。

        Yields:
            流式事件字典。
        """
        ctl = self._controller

        for iteration in range(self._max_iterations):
            if ctl.status != "running":
                break

            # 流式场景也执行步前 hook
            if await self._run_before_step_hooks(ctx):
                ctl.status = "error"
                yield {"type": "error", "error": "before_step 拦截"}
                break

            next_step_type = await self._get_router_decision(ctx)
            if next_step_type == "end":
                break

            ctl.step_index += 1
            ctx = ctl.build_context()

            # 流式 LLM 执行
            yield {"type": "llm_start", "step": iteration}

            step_result: StepResult = await self._step_runner.run_step(ctx, runtime)

            # 产出文本事件
            if step_result.content:
                yield {"type": "text", "content": step_result.content}

            # 产出工具事件
            for tc in step_result.tool_calls:
                yield {"type": "tool_start", "name": tc.name}
                yield {"type": "tool_end", "name": tc.name}

            # 步后 hook
            await self._run_after_step_hooks(ctx)
            runtime._budget.step_count += 1

            if step_result.is_blocked or step_result.status in (
                StepStatus.PAUSED, StepStatus.ERROR
            ):
                break
            if step_result.finish_reason.value in ("stop", "length"):
                if self._router is not None:
                    router_decision = await self._router(ctx)
                    if router_decision == "continue":
                        continue
                break

    async def _get_router_decision(self, ctx: RuntimeContext) -> str:
        """
        获取 Router 决策结果。

        无 Router 时默认返回 "llm"。

        Args:
            ctx: RuntimeContext 实例。

        Returns:
            步骤类型（"llm" | "end" | 其他自定义类型）。
        """
        if self._router is not None:
            return await self._router(ctx)
        return "llm"

    def _create_step_result(self, response: Any) -> StepResult:
        """将 LLM 响应封装为 StepResult。"""
        from src.runtime.llm._models import LLMResponse

        if isinstance(response, LLMResponse):
            return StepResult(
                finish_reason=response.finish_reason,
                status=StepStatus.SUCCESS,
                content=response.content,
                tool_calls=list(response.tool_calls),
            )
        return StepResult(
            finish_reason=__import__(
                "src.runtime.llm._models", fromlist=["FinishReason"]
            ).FinishReason.STOP,  # type: ignore
            status=StepStatus.SUCCESS,
            content=str(response),
        )
