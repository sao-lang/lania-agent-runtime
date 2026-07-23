"""
Loop 策略模块——可插拔的执行循环策略。

提供三种 LoopStrategy 实现，共享同一套基础设施（Hook / StepRunner / Context）：
  - ReActLoop：边思考边行动（默认）
  - PlanExecuteLoop：先规划再执行
  - WorkflowLoop：固定 DAG + Agent 决策节点

使用方式：
    from src.runtime.loops import ReActLoop, PlanExecuteLoop, WorkflowLoop, LoopStrategyFactory

    # 注册策略
    LoopStrategyFactory.register("react", ReActLoop)
    LoopStrategyFactory.register("plan_and_execute", PlanExecuteLoop)

    # 通过工厂创建
    strategy = LoopStrategyFactory.create("react", hooks=hooks, step_runner=runner)
"""

from src.runtime.loops._base import LoopStrategy
from src.runtime.loops._factory import LoopStrategyFactory
from src.runtime.loops._plan_execute import PlanExecuteLoop
from src.runtime.loops._react import ReActLoop
from src.runtime.loops._types import Plan, PlanStep, StepResult, StepStatus
from src.runtime.loops._workflow import (
    AgentNode,
    ConditionNode,
    FixedNode,
    WorkflowDefinition,
    WorkflowLoop,
    WorkflowNode,
)

__all__ = [
    "LoopStrategy",
    "LoopStrategyFactory",
    "ReActLoop",
    "PlanExecuteLoop",
    "WorkflowLoop",
    "WorkflowDefinition",
    "WorkflowNode",
    "FixedNode",
    "AgentNode",
    "ConditionNode",
    "StepResult",
    "StepStatus",
    "Plan",
    "PlanStep",
]
