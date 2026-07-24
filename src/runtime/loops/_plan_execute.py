"""
PlanExecuteLoop —— 先规划再执行策略。

对应设计文档 §2.2 PlanExecuteLoop。
分三阶段：
  1. 规划（Planner）：LLM 生成执行计划
  2. 执行（Execute）：按序执行计划步骤
  3. 重新规划（Replan）：可选，在必要时调整计划

Planner 和 Replanner 均走完整的 StepRunner hook 管线。
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any, AsyncIterator

from src.runtime.llm._models import FinishReason
from src.runtime.loops._base import LoopStrategy
from src.runtime.loops._types import Plan, PlanStep, StepResult, StepStatus

if TYPE_CHECKING:
    from src.runtime.context._context import RuntimeContext


class PlanExecuteLoop(LoopStrategy):
    """
    先规划再执行策略。

    循环结构：
      Phase 1: Planner 生成计划（走 LLM hook 管线）
      Phase 2: 按序执行计划步骤
      Phase 3 (可选): Replan 调整计划

    适用场景：复杂任务需要预先拆解、多步骤流水线、代码生成、数据分析。
    """

    def __init__(
        self,
        hooks: Any,
        step_runner: Any,
        controller: Any,
        router: Any | None = None,
        planner_prompt: str = "",
        max_replans: int = 3,
        max_iterations: int = 20,
    ) -> None:
        """
        初始化 PlanExecuteLoop。

        Args:
            hooks: HookRegistry 实例。
            step_runner: StepRunner 实例。
            controller: RuntimeController 实例。
            router: 可选的路由函数。
            planner_prompt: Planner 的系统提示词模板。
            max_replans: 最大重新规划次数，默认 3。
            max_iterations: 最大总执行步数，默认 20。
        """
        super().__init__(hooks, step_runner, controller, router)
        self._planner_prompt = planner_prompt or self._default_planner_prompt()
        self._max_replans = max_replans
        self._max_iterations = max_iterations
        self._replan_count = 0

    @staticmethod
    def _default_planner_prompt() -> str:
        """默认 Planner 提示词。"""
        return (
            "请将以下任务拆解为多个执行步骤。"
            "返回 JSON 格式："
            '{"steps": [{"id": "step_1", "description": "...", "depends_on": []}]}'
        )

    async def run(self, ctx: RuntimeContext) -> None:
        """
        非流式执行 Plan-and-Execute 循环。

        流程：
          Phase 1: Planner 生成计划
          Phase 2: 按序执行计划步骤（while + step_index，支持 replan）
          Phase 3: 可选 Replan

        Args:
            ctx: RuntimeContext 实例。
        """
        ctl = self._controller

        # === Phase 1: 规划 ===
        if await self._run_before_step_hooks(ctx):
            ctl.status = "error"
            return

        plan = await self._run_planner(ctx, ctl)
        if plan is None:
            ctl.status = "error"
            return

        # 保存计划到 Runtime
        ctl.plan = self._plan_to_dict(plan)
        ctx = ctl.build_context()

        await self._run_after_step_hooks(ctx)

        # === Phase 2: 执行 ===
        step_index = 0
        total_steps = 0

        while step_index < len(plan.steps):
            if ctl.status != "running":
                break
            if total_steps >= self._max_iterations:
                break

            step = plan.steps[step_index]

            # 步前 hook：Interceptor → Transformer → Observer
            if await self._run_before_step_hooks(ctx):
                ctl.status = "error"
                break

            # Router 检查
            next_step_type = await self._get_router_decision(ctx)
            if next_step_type == "end":
                break

            # 注入 step description 到 context（每次执行前清理，防止跨循环累积）
            if total_steps == 0 and step_index == 0:
                ctl.context_payload.injected_context.clear()
            ctl.context_payload.injected_context.append(step.description)
            ctx = ctl.build_context()

            # 更新 step 计数
            ctl.step_index += 1
            ctl.timeout["step_start_at"] = int(time.time() * 1000)
            total_steps += 1

            # 执行单步
            step_result: StepResult = await self._step_runner.run_step(ctx, ctl)

            # 步后 hook：Transformer → Observer
            await self._run_after_step_hooks(ctx)
            ctl.budget.step_count += 1
            ctx = ctl.build_context()

            # 记录 step history
            ctl.step_history.append({
                "step_index": ctl.step_index,
                "step_id": step.id,
                "description": step.description,
                "timestamp": time.time(),
                "finish_reason": step_result.finish_reason.value,
            })

            # 检查是否被阻断
            if step_result.is_blocked or step_result.status == StepStatus.PAUSED:
                break
            if step_result.status == StepStatus.ERROR:
                break

            # === Phase 3: Replan ===
            replan_needed = self._should_replan(step_result, step_index, plan)
            if replan_needed and self._replan_count < self._max_replans:
                new_plan = await self._run_replanner(ctx, ctl, plan, step_index)
                if new_plan is not None:
                    plan = new_plan
                    ctl.plan = self._plan_to_dict(plan)
                    self._replan_count += 1
                    # 在新计划中定位当前进度
                    step_index = self._find_current_step_index(plan, ctx)
                    ctx = ctl.build_context()
                    continue

            step_index += 1

    async def run_stream(self, ctx: RuntimeContext) -> AsyncIterator[dict]:
        """
        流式执行 Plan-and-Execute 循环。

        Args:
            ctx: RuntimeContext 实例。

        Yields:
            流式事件字典。
        """
        ctl = self._controller

        # Phase 1: 规划
        yield {"type": "plan_start"}

        if await self._run_before_step_hooks(ctx):
            yield {"type": "error", "error": "before_step 拦截"}
            return

        plan = await self._run_planner(ctx, ctl)
        if plan is None:
            yield {"type": "error", "error": "规划失败"}
            return

        ctl.plan = self._plan_to_dict(plan)
        ctx = ctl.build_context()
        await self._run_after_step_hooks(ctx)

        yield {"type": "plan_ready", "plan": self._plan_to_dict(plan)}

        # Phase 2: 执行
        step_index = 0
        total_steps = 0

        while step_index < len(plan.steps):
            if ctl.status != "running":
                break
            if total_steps >= self._max_iterations:
                break

            yield {"type": "step_start", "step_id": plan.steps[step_index].id}

            if total_steps == 1 and step_index == 0:
                ctl.context_payload.injected_context.clear()
            ctl.context_payload.injected_context.append(plan.steps[step_index].description)
            ctl.step_index += 1
            ctx = ctl.build_context()
            total_steps += 1

            step_result = await self._step_runner.run_step(ctx, ctl)

            if step_result.content:
                yield {"type": "text", "content": step_result.content}

            for tc in step_result.tool_calls:
                yield {"type": "tool_start", "name": tc.name}
                yield {"type": "tool_end", "name": tc.name}

            await self._run_after_step_hooks(ctx)
            ctl.budget.step_count += 1
            ctx = ctl.build_context()

            if step_result.is_blocked or step_result.status in (
                StepStatus.PAUSED, StepStatus.ERROR,
            ):
                break

            # Replan
            replan_needed = self._should_replan(step_result, step_index, plan)
            if replan_needed and self._replan_count < self._max_replans:
                yield {"type": "replan_start"}

                new_plan = await self._run_replanner(ctx, ctl, plan, step_index)
                if new_plan is not None:
                    plan = new_plan
                    ctl.plan = self._plan_to_dict(plan)
                    self._replan_count += 1
                    step_index = self._find_current_step_index(plan, ctx)
                    ctx = ctl.build_context()

                    yield {"type": "replan_ready", "plan": self._plan_to_dict(plan)}
                    continue

            step_index += 1

    async def _run_planner(self, ctx: RuntimeContext, ctl: Any) -> Plan | None:
        """
        执行规划步骤。

        通过 StepRunner.run_llm_only() 走完整 hook 管线，
        从 LLM 回复中解析出 Plan。

        Args:
            ctx: RuntimeContext 实例。
            ctl: RuntimeController 实例。

        Returns:
            解析后的 Plan，或 None（规划失败）。
        """
        # 注入规划提示词
        ctl.context_payload.injected_context.append(self._planner_prompt)
        ctx = ctl.build_context()

        # 走完整 LLM hook 管线
        llm_response = await self._step_runner.run_llm_only(ctx, ctl)
        if llm_response is None:
            return None

        # 从 LLM 回复中解析 Plan
        return self._parse_plan(llm_response.content)

    async def _run_replanner(
        self, ctx: RuntimeContext, ctl: Any, current_plan: Plan, current_index: int
    ) -> Plan | None:
        """
        执行重新规划步骤。

        Args:
            ctx: RuntimeContext 实例。
            ctl: RuntimeController 实例。
            current_plan: 当前计划。
            current_index: 当前执行的步骤索引。

        Returns:
            新的 Plan，或 None（重新规划失败）。
        """
        replanner_prompt = (
            f"当前计划: {json.dumps(self._plan_to_dict(current_plan), ensure_ascii=False)}\n"
            f"已完成步骤索引: {current_index}\n"
            "请根据执行进度重新调整计划。"
            '返回 JSON 格式：'
            '{"steps": [{"id": "...", "description": "...", "depends_on": []}]}'
        )

        ctl.context_payload.injected_context.append(replanner_prompt)
        ctx = ctl.build_context()

        llm_response = await self._step_runner.run_llm_only(ctx, ctl)
        if llm_response is None:
            return None

        return self._parse_plan(llm_response.content)

    def _parse_plan(self, content: str) -> Plan | None:
        """
        从 LLM 回复文本中解析 Plan。

        支持纯 JSON 和带代码块标记的 JSON。

        Args:
            content: LLM 回复文本。

        Returns:
            解析后的 Plan，或 None。
        """
        import re

        if not content:
            return None

        # 策略 1：提取 ```json ... ``` 代码块
        json_block_match = re.search(
            r"```(?:json)?\s*\n?([\s\S]*?)```", content, re.DOTALL
        )
        json_str = json_block_match.group(1).strip() if json_block_match else content.strip()

        # 策略 2：提取最外层 { 和 } 之间的内容
        start = json_str.find("{")
        end = json_str.rfind("}")
        if start != -1 and end != -1:
            json_str = json_str[start : end + 1]

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return None

        steps_data = data.get("steps", [])
        steps = [
            PlanStep(
                id=s.get("id", f"step_{i}"),
                description=s.get("description", ""),
                depends_on=s.get("depends_on", []),
            )
            for i, s in enumerate(steps_data)
        ]

        return Plan(
            steps=steps,
            reasoning=data.get("reasoning", ""),
        )

    def _plan_to_dict(self, plan: Plan) -> dict:
        """
        将 Plan 转换为可序列化的字典。

        Args:
            plan: Plan 实例。

        Returns:
            字典表示。
        """
        return {
            "steps": [
                {
                    "id": s.id,
                    "description": s.description,
                    "depends_on": list(s.depends_on),
                }
                for s in plan.steps
            ],
            "reasoning": plan.reasoning,
        }

    def _should_replan(self, step_result: StepResult, step_index: int, plan: Plan) -> bool:
        """
        判断是否需要重新规划。

        内置触发条件：
          - 连续工具调用失败
          - LLM finish_reason 为 error
          - 步骤内容为空（LLM 无有效回复）

        Args:
            step_result: 步骤执行结果。
            step_index: 当前步骤索引。
            plan: 当前计划。

        Returns:
            True 表示需要重新规划。
        """
        if step_result.status == StepStatus.ERROR:
            return True
        if step_result.finish_reason.value == "error":
            return True
        if not step_result.content and not step_result.has_tool_calls:
            return True
        return False

    def _find_current_step_index(self, plan: Plan, ctx: RuntimeContext) -> int:
        """
        在新计划中定位当前执行进度。

        按 step description 匹配，匹配不上则从头开始。

        Args:
            plan: 新计划。
            ctx: RuntimeContext 实例。

        Returns:
            当前应继续的步骤索引。
        """
        if not plan.steps:
            return 0

        # 从 controller 的 step_history 中找最后执行的 step_id
        if self._controller.step_history:
            last_step_id = self._controller.step_history[-1].get("step_id", "")
            for i, step in enumerate(plan.steps):
                if step.id == last_step_id:
                    return i + 1  # 从下一个步骤开始

        return 0

    async def _get_router_decision(self, ctx: RuntimeContext) -> str:
        """
        获取 Router 决策结果。

        Args:
            ctx: RuntimeContext 实例。

        Returns:
            步骤类型。
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
            finish_reason=FinishReason.STOP,
            status=StepStatus.SUCCESS,
            content=str(response),
        )
