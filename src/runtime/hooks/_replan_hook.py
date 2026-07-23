"""
Replan Hook 模块——作为 Hook 的 Replan 变体。

提供注册到 after_step 的 ReplanHook，
在步骤执行后判断是否需要触发重新规划。

与 PlanExecuteLoop 内置的 replan 逻辑不同，
这个 Hook 允许在任何 LoopStrategy 中独立使用 replan 能力。
"""

from __future__ import annotations

from typing import Any, Callable


class ReplanHook:
    """
    可插拔的重新规划 Hook。

    注册到 after_step 挂载点，在每步执行后触发。
    通过 should_replan() 判断是否需要重新规划，
    需要时通过 replanner_fn 生成新计划并更新 Runtime。

    与 PlanExecuteLoop 内置 replan 的区别：
      - PlanExecuteLoop 的 replan 是策略内部逻辑
      - ReplanHook 是通用 Hook，可搭配任何 LoopStrategy
    """

    def __init__(
        self,
        should_replan: Callable[[Any], bool],
        replanner_fn: Callable[[Any], Any],
        max_replans: int = 3,
    ) -> None:
        """
        初始化 ReplanHook。

        Args:
            should_replan: 判断函数，接收 RuntimeContext 返回是否需重新规划。
            replanner_fn: 重新规划函数，接收 RuntimeContext 返回新计划。
            max_replans: 最大重新规划次数。
        """
        self._should_replan = should_replan
        self._replanner_fn = replanner_fn
        self._max_replans = max_replans
        self._replan_count = 0

    async def __call__(self, data: Any, ctx: Any) -> Any:
        """
        Transformer 调用入口。

        after_step 时触发，判断是否需要重新规划。

        Args:
            data: Transformer 输入数据。
            ctx: RuntimeContext 实例。

        Returns:
            原样返回 data（Transformer 不修改数据流）。
        """
        if self._replan_count >= self._max_replans:
            return data

        runtime = ctx.services.get("_runtime")
        if runtime is None:
            return data

        if self._should_replan(ctx):
            new_plan = await self._replanner_fn(ctx)
            if new_plan is not None:
                runtime._plan = new_plan
                self._replan_count += 1

        return data
