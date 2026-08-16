"""
Loop 策略模块——可插拔的执行循环策略。

提供三种内置 LoopStrategy 实现，共享同一套基础设施（Hook / StepRunner / Context）：
  - ReActLoop：边思考边行动（默认）
  - PlanExecuteLoop：先规划再执行
  - WorkflowLoop：固定 DAG + Agent 决策节点

内置三种之外，可通过 LoopStrategyFactory 注册自定义策略（策略类或工厂函数），
按名创建时支持透传策略构造参数：

使用方式：
    from src.runtime.loops import LoopStrategyFactory

    # 注册策略类或工厂函数
    LoopStrategyFactory.register("react", ReActLoop)
    LoopStrategyFactory.register("my_loop", lambda **kw: MyLoop(**kw))

    # 通过工厂创建（extra 参数透传给策略构造函数）
    strategy = LoopStrategyFactory.create("my_loop", hooks=hooks, step_runner=runner, extra=1)
"""

from src.intent import HybridClassifier, LLMClassifier, RuleClassifier
from src.intent._protocols import IntentClassifier
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
    "IntentClassifier",
    "RuleClassifier",
    "LLMClassifier",
    "HybridClassifier",
]
