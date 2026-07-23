"""
WorkflowLoop —— 固定 DAG + Agent 决策节点策略。

对应设计文档 §2.3 WorkflowLoop。
支持三种节点类型：
  - FixedNode：固定逻辑节点（执行预定义 handler 函数）
  - AgentNode：Agent 决策节点（使用 StepRunner 执行 LLM 调用）
  - ConditionNode：条件分支节点（根据 condition_fn 选择后续路径）

运行时图遍历替代拓扑排序，天然支持分支和条件跳转。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable

from src.runtime.loops._base import LoopStrategy
from src.runtime.loops._types import StepResult, StepStatus

if TYPE_CHECKING:
    from src.runtime.context._context import RuntimeContext
    from src.runtime._steps._step_runner import StepRunner


class NodeType(Enum):
    """工作流节点类型枚举。"""

    FIXED = "fixed"
    """固定逻辑节点，执行预定义 handler 函数。"""
    AGENT = "agent"
    """Agent 决策节点，通过 StepRunner 执行 LLM 调用。"""
    CONDITION = "condition"
    """条件分支节点，根据 condition_fn 返回值选择后续路径。"""


# TODO: Multi-Agent Agent-as-tool
# SubAgentSpec 和 AgentTool 将在 tools 体系设计完成后实现。
# 当前通过 StepRunner.run_step() 单步执行，不支持子 Agent 委托。
# 设计参考: docs/design/loop-strategy-design.md §3.1
# 预期组件:
#   - SubAgentSpec: 子 Agent 规格定义
#   - AgentTool: 作为 Tool 注册到 Runtime，内部创建子 Runtime 执行


class WorkflowError(Exception):
    """工作流执行异常。"""


class WorkflowNode(ABC):
    """
    工作流节点抽象基类。

    所有节点类型（FixedNode / AgentNode / ConditionNode）
    继承此类并实现 execute 方法。
    """

    def __init__(self, node_id: str, depends_on: list[str] | None = None) -> None:
        """
        初始化节点。

        Args:
            node_id: 节点唯一标识。
            depends_on: 依赖的上游节点 ID 列表。
        """
        self.node_id: str = node_id
        """节点唯一标识。"""
        self.depends_on: list[str] = depends_on or []
        """依赖的上游节点 ID 列表。"""
        self.result: Any = None
        """节点执行结果。"""

    @abstractmethod
    async def execute(self, ctx: RuntimeContext, step_runner: StepRunner) -> Any:
        """
        执行节点逻辑。

        Args:
            ctx: RuntimeContext 实例。
            step_runner: StepRunner 实例。

        Returns:
            节点执行结果。
        """
        ...


class FixedNode(WorkflowNode):
    """
    固定逻辑节点。

    执行预定义的 handler 函数，handler 接收 RuntimeContext 返回任意结果。
    用于数据预处理、分类、转换等确定性逻辑。
    """

    def __init__(
        self,
        node_id: str,
        handler: Callable[[RuntimeContext], Any],
        depends_on: list[str] | None = None,
    ) -> None:
        """
        初始化固定逻辑节点。

        Args:
            node_id: 节点唯一标识。
            handler: 接收 RuntimeContext 返回执行结果的函数。
            depends_on: 依赖的上游节点 ID 列表。
        """
        super().__init__(node_id, depends_on)
        self._handler = handler

    async def execute(self, ctx: RuntimeContext, step_runner: StepRunner) -> Any:
        """
        执行 handler 函数。

        Args:
            ctx: RuntimeContext 实例。
            step_runner: StepRunner 实例（固定节点不使用）。

        Returns:
            handler 的返回值。
        """
        import inspect

        if inspect.iscoroutinefunction(self._handler):
            result = await self._handler(ctx)
        else:
            result = self._handler(ctx)
        self.result = result
        return result


class AgentNode(WorkflowNode):
    """
    Agent 决策节点。

    使用 StepRunner 执行一次完整的 LLM 调用 + 工具调用。
    与 ReActLoop/PlanExecuteLoop 复用同一套单步逻辑。
    """

    def __init__(
        self,
        node_id: str,
        system_prompt: str = "",
        depends_on: list[str] | None = None,
    ) -> None:
        """
        初始化 Agent 决策节点。

        Args:
            node_id: 节点唯一标识。
            system_prompt: 节点级别的 system prompt 覆盖。
            depends_on: 依赖的上游节点 ID 列表。
        """
        super().__init__(node_id, depends_on)
        self._system_prompt = system_prompt

    async def execute(self, ctx: RuntimeContext, step_runner: StepRunner) -> StepResult:
        """
        执行完整的 LLM 调用 + 工具调用。

        通过 ctx.services["_runtime"] 获取 Runtime 引用后执行单步。

        Args:
            ctx: RuntimeContext 实例。
            step_runner: StepRunner 实例。

        Returns:
            StepResult 实例。
        """
        runtime = ctx.services.get("_runtime")
        if runtime is None:
            raise WorkflowError("AgentNode 需要 Runtime 通过 ctx.services['_runtime'] 注入")

        # 可选：注入节点级别的 system prompt
        if self._system_prompt:
            runtime._context_payload.injected_context.append(self._system_prompt)

        # 更新 step 计数
        runtime._step_index += 1

        # 构建新的上下文
        ctx = runtime._build_context()

        # 委托给 StepRunner
        step_result = await step_runner.run_step(ctx, runtime)
        self.result = step_result
        return step_result


class ConditionNode(WorkflowNode):
    """
    条件分支节点。

    根据 condition_fn 的返回值选择后续路径。
    condition_fn 由 WorkflowDefinition.add_condition() 注入。
    返回值为分支名称，WorkflowLoop 根据名称查找下一个节点。
    """

    def __init__(
        self,
        node_id: str,
        condition_fn: Callable[[RuntimeContext], Any],
        depends_on: list[str] | None = None,
    ) -> None:
        """
        初始化条件分支节点。

        Args:
            node_id: 节点唯一标识。
            condition_fn: 条件判断函数，接收 RuntimeContext 返回分支名称。
            depends_on: 依赖的上游节点 ID 列表。
        """
        super().__init__(node_id, depends_on)
        self._condition_fn = condition_fn

    async def execute(self, ctx: RuntimeContext, step_runner: StepRunner) -> str:
        """
        执行条件判断。

        Args:
            ctx: RuntimeContext 实例。
            step_runner: StepRunner 实例（条件节点不使用）。

        Returns:
            分支名称字符串。
        """
        import inspect

        if inspect.iscoroutinefunction(self._condition_fn):
            result = await self._condition_fn(ctx)
        else:
            result = self._condition_fn(ctx)
        self.result = result
        return str(result)


@dataclass
class Edge:
    """工作流边定义。"""

    from_node: str
    """起始节点 ID。"""
    to_node: str
    """目标节点 ID。"""


@dataclass
class ConditionMapping:
    """条件分支映射。"""

    node_id: str
    """条件节点 ID。"""
    branches: dict[str, str] = field(default_factory=dict)
    """分支名称 → 目标节点 ID 的映射。"""


class WorkflowDefinition:
    """
    工作流定义——纯数据类，可序列化/反序列化。

    管理节点集合、边集合和条件映射。
    支持从配置文件加载（JSON/YAML）。
    """

    def __init__(
        self,
        nodes: list[WorkflowNode] | None = None,
        start_node_id: str = "",
    ) -> None:
        """
        初始化工作流定义。

        Args:
            nodes: 节点列表。
            start_node_id: 起始节点 ID。
        """
        self._nodes: dict[str, WorkflowNode] = {}
        self._edges: dict[str, list[str]] = {}  # from_node → [to_nodes]
        self._conditions: dict[str, ConditionMapping] = {}
        self._start_node_id: str = ""

        if nodes:
            for node in nodes:
                self.add_node(node)

        self._start_node_id = start_node_id or (nodes[0].node_id if nodes else "")

    @property
    def start_node_id(self) -> str:
        """起始节点 ID。"""
        return self._start_node_id

    @start_node_id.setter
    def start_node_id(self, node_id: str) -> None:
        """设置起始节点 ID。"""
        if node_id not in self._nodes:
            raise WorkflowError(f"起始节点 '{node_id}' 不在工作流定义中")
        self._start_node_id = node_id

    def add_node(self, node: WorkflowNode) -> WorkflowDefinition:
        """
        添加一个节点。

        Args:
            node: WorkflowNode 实例。

        Returns:
            self（支持链式调用）。
        """
        if node.node_id in self._nodes:
            raise WorkflowError(f"节点 '{node.node_id}' 已存在")
        self._nodes[node.node_id] = node
        return self

    def add_edge(self, from_node: str, to_node: str) -> WorkflowDefinition:
        """
        添加一条边。

        Args:
            from_node: 起始节点 ID。
            to_node: 目标节点 ID。

        Returns:
            self（支持链式调用）。

        Raises:
            WorkflowError: 如果任一节点不存在。
        """
        if from_node not in self._nodes:
            raise WorkflowError(f"起始节点 '{from_node}' 不在工作流定义中")
        if to_node not in self._nodes:
            raise WorkflowError(f"目标节点 '{to_node}' 不在工作流定义中")

        if from_node not in self._edges:
            self._edges[from_node] = []
        self._edges[from_node].append(to_node)
        return self

    def add_condition(
        self, node_id: str, branches: dict[str, str]
    ) -> WorkflowDefinition:
        """
        为条件节点添加分支映射。

        Args:
            node_id: 条件节点 ID。
            branches: 分支名称 → 目标节点 ID 的映射。

        Returns:
            self（支持链式调用）。

        Raises:
            WorkflowError: 如果节点不存在或不是条件节点。
        """
        if node_id not in self._nodes:
            raise WorkflowError(f"节点 '{node_id}' 不在工作流定义中")
        if not isinstance(self._nodes[node_id], ConditionNode):
            raise WorkflowError(f"节点 '{node_id}' 不是条件节点")

        for branch_name, target_id in branches.items():
            if target_id not in self._nodes:
                raise WorkflowError(f"分支目标节点 '{target_id}' 不在工作流定义中")

        self._conditions[node_id] = ConditionMapping(node_id=node_id, branches=branches)
        return self

    def get_node(self, node_id: str) -> WorkflowNode:
        """
        获取节点实例。

        Args:
            node_id: 节点 ID。

        Returns:
            WorkflowNode 实例。

        Raises:
            WorkflowError: 如果节点不存在。
        """
        node = self._nodes.get(node_id)
        if node is None:
            raise WorkflowError(f"节点 '{node_id}' 不在工作流定义中")
        return node

    def next_node(self, node_id: str) -> str | None:
        """
        获取节点的默认下一个节点。

        仅对 FixedNode 和 AgentNode 有效（走边定义）。
        ConditionNode 的下一个节点由条件判断结果决定。

        Args:
            node_id: 当前节点 ID。

        Returns:
            下一个节点 ID，或 None（无后续节点）。
        """
        edges = self._edges.get(node_id, [])
        if edges:
            return edges[0]
        return None

    def has_node(self, node_id: str) -> bool:
        """
        检查节点是否存在。

        Args:
            node_id: 节点 ID。

        Returns:
            是否存在。
        """
        return node_id in self._nodes

    @property
    def nodes(self) -> dict[str, WorkflowNode]:
        """所有节点的只读视图。"""
        return dict(self._nodes)

    @property
    def edges(self) -> dict[str, list[str]]:
        """所有边的只读视图。"""
        return dict(self._edges)

    @property
    def conditions(self) -> dict[str, ConditionMapping]:
        """所有条件映射的只读视图。"""
        return dict(self._conditions)

    def to_dict(self) -> dict:
        """
        序列化为字典（支持 JSON 导出）。

        Returns:
            可序列化的字典。
        """
        return {
            "start_node_id": self._start_node_id,
            "nodes": [
                {
                    "id": n.node_id,
                    "type": (
                        "fixed"
                        if isinstance(n, FixedNode)
                        else "agent" if isinstance(n, AgentNode) else "condition"
                    ),
                    "depends_on": list(n.depends_on),
                }
                for n in self._nodes.values()
            ],
            "edges": [
                {"from": k, "to": v}
                for k, targets in self._edges.items()
                for v in targets
            ],
            "conditions": {
                cid: cm.branches for cid, cm in self._conditions.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> WorkflowDefinition:
        """
        从字典反序列化创建 WorkflowDefinition。

        支持由 to_dict() 或 JSON/YAML 配置文件产生的数据。
        FixedNode 和 AgentNode 需要手动构建后通过 add_node 添加；
        from_dict 仅重建结构骨架（节点类型/ID/边/条件），
        具体 handler/condition_fn 需在反序列化后注入。

        Args:
            data: 包含 nodes/edges/conditions/start_node_id 的字典。

        Returns:
            WorkflowDefinition 实例。
        """
        wf = cls()

        # 重建节点（仅骨架，handler 需后续注入）
        node_type_map = {"fixed": FixedNode, "agent": AgentNode, "condition": ConditionNode}
        for node_data in data.get("nodes", []):
            node_id = node_data["id"]
            node_type = node_type_map.get(node_data.get("type", "fixed"))
            depends_on = node_data.get("depends_on", [])

            if node_type is ConditionNode:
                # 条件节点需要先创建占位，condition_fn 后续注入
                node = ConditionNode(
                    node_id=node_id,
                    condition_fn=lambda _: "",
                    depends_on=depends_on,
                )
            elif node_type is AgentNode:
                node = AgentNode(
                    node_id=node_id,
                    system_prompt=node_data.get("system_prompt", ""),
                    depends_on=depends_on,
                )
            else:
                # FixedNode 默认 handler 为空操作，后续可通过 replace 替换
                node = FixedNode(
                    node_id=node_id,
                    handler=lambda _: None,
                    depends_on=depends_on,
                )
            wf.add_node(node)

        # 重建边
        for edge_data in data.get("edges", []):
            wf.add_edge(edge_data["from"], edge_data["to"])

        # 重建条件分支
        for cond_node_id, branches in data.get("conditions", {}).items():
            if wf.has_node(cond_node_id):
                wf.add_condition(cond_node_id, branches)

        # 设置起始节点
        start_id = data.get("start_node_id", "")
        if start_id and wf.has_node(start_id):
            wf.start_node_id = start_id
        elif wf._nodes:
            # 默认取第一个节点
            first_id = next(iter(wf._nodes))
            wf._start_node_id = first_id

        return wf


class WorkflowLoop(LoopStrategy):
    """
    固定 DAG + Agent 决策节点策略。

    运行时图遍历——从 start_node_id 开始，按边和条件跳转，
    通过 depends_on 做前置校验而非排序。

    适用场景：客服流程、审批流程、数据处理 Pipeline、有固定业务流程的场景。
    """

    def __init__(
        self,
        hooks: Any,
        step_runner: Any,
        workflow_definition: WorkflowDefinition,
        router: Any | None = None,
    ) -> None:
        """
        初始化 WorkflowLoop。

        Args:
            hooks: HookRegistry 实例。
            step_runner: StepRunner 实例。
            workflow_definition: 工作流定义。
            router: 可选的路由函数。
        """
        super().__init__(hooks, step_runner, router)
        self._workflow = workflow_definition

    async def run(self, ctx: RuntimeContext) -> None:
        """
        执行工作流。

        从 start_node_id 开始运行时图遍历，支持线性、分支和循环图结构。

        Args:
            ctx: RuntimeContext 实例。
        """
        runtime = self._get_runtime(ctx)
        current_node_id: str | None = self._workflow.start_node_id
        visited: set[str] = set()

        while current_node_id is not None:
            if runtime.status != "running":
                break

            node = self._workflow.get_node(current_node_id)

            # 前置依赖检查
            for dep in node.depends_on:
                if dep not in visited:
                    raise WorkflowError(
                        f"依赖未就绪: {node.node_id} 需要 {dep}"
                    )

            # 步前 hook：Interceptor → Transformer → Observer
            if await self._run_before_step_hooks(ctx):
                runtime.status = "error"
                break

            # 执行节点
            result = await node.execute(ctx, self._step_runner)
            node.result = result
            visited.add(current_node_id)

            # 步后 hook：Transformer → Observer
            await self._run_after_step_hooks(ctx)
            runtime._budget.step_count += 1
            ctx = runtime._build_context()
            node.result = result
            visited.add(current_node_id)

            # 步后 hook：Transformer → Observer
            await self._run_after_step_hooks(ctx)
            runtime._budget.step_count += 1
            ctx = runtime._build_context()

            # 决定下一个节点
            if isinstance(node, ConditionNode):
                branch = str(result)
                condition = self._workflow.conditions.get(node.node_id)
                if condition is not None:
                    current_node_id = condition.branches.get(branch)
                else:
                    current_node_id = None
            else:
                current_node_id = self._workflow.next_node(node.node_id)

    async def run_stream(self, ctx: RuntimeContext) -> AsyncIterator[dict]:
        """
        流式执行工作流。

        Args:
            ctx: RuntimeContext 实例。

        Yields:
            流式事件字典。
        """
        runtime = self._get_runtime(ctx)
        current_node_id: str | None = self._workflow.start_node_id
        visited: set[str] = set()

        while current_node_id is not None:
            if runtime.status != "running":
                break

            node = self._workflow.get_node(current_node_id)

            yield {"type": "node_start", "node_id": current_node_id}

            # 前置依赖检查
            for dep in node.depends_on:
                if dep not in visited:
                    yield {"type": "error", "error": f"依赖未就绪: {node.node_id} 需要 {dep}"}
                    return

            # 执行节点
            result = await node.execute(ctx, self._step_runner)
            node.result = result
            visited.add(current_node_id)

            yield {"type": "node_end", "node_id": current_node_id, "result": str(result)[:200]}

            await self._run_after_step_hooks(ctx)
            runtime._budget.step_count += 1
            ctx = runtime._build_context()

            # 决定下一个节点
            if isinstance(node, ConditionNode):
                branch = str(result)
                condition = self._workflow.conditions.get(node.node_id)
                current_node_id = condition.branches.get(branch) if condition else None
            else:
                current_node_id = self._workflow.next_node(node.node_id)

    def _get_runtime(self, ctx: RuntimeContext) -> Any:
        """
        从 RuntimeContext 获取关联的 AgentRuntime 实例。

        Args:
            ctx: RuntimeContext 实例。

        Returns:
            AgentRuntime 实例。

        Raises:
            WorkflowError: 如果 Runtime 引用未注入。
        """
        runtime = ctx.services.get("_runtime")
        if runtime is None:
            raise WorkflowError(
                "WorkflowLoop 需要 Runtime 通过 ctx.services['_runtime'] 注入自身引用"
            )
        return runtime

    def _create_step_result(self, response: Any) -> StepResult:
        """将执行结果封装为 StepResult。"""
        if isinstance(response, StepResult):
            return response
        return StepResult(
            finish_reason=__import__(
                "src.runtime.llm._models", fromlist=["FinishReason"]
            ).FinishReason.STOP,
            status=StepStatus.SUCCESS,
            content=str(response),
        )

