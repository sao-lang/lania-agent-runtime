# Loop 策略技术方案

> ⚠️ **本文档是 `agent-runtime-design.md` 的子文档**。
> 阅读前请确保已理解主文档中的 **Hook Point 体系**、**5 种原语类型** 和 **Runtime 核心状态**。
> 主文档 [`agent-runtime-design.md`](agent-runtime-design.md) → §6.4 `set_loop_executor` → §11 关联设计文档。

## 一、概述

将 Agent Runtime 的执行循环从 `AgentRuntime._step_loop()` 中提取为可插拔的 `LoopStrategy` 组件。每种 Agent 工作方式对应一个 LoopStrategy 实现，共享同一套基础设施（Hook / LLMExecutor / Memory / Context）。

设计原则：
- **架构现有入口**：HookRegistry 已预留 `set_loop_executor()`，本方案将其真正用起来
- **不引入新概念**：三种策略覆盖所有需求，Multi-Agent / HITL 通过现有机制（Agent-as-tool / Intercept pause）实现
- **单一职责**：策略只管"循环怎么走"，不管"单步怎么做"——单步逻辑（hook 编排、LLM 调用、工具执行）由 `StepRunner` 封装

### StepRunner —— 单步执行单元

`StepRunner` 封装"一次 LLM 调用 + 可能的工具调用"的完整单步逻辑，被三种 LoopStrategy 共享：

```
LoopStrategy 只管:
    while not done:
        before_step hooks     (Memory Bank 读取)
        step = step_runner.run_step(ctx)   ← 单步逻辑委托给 StepRunner
        after_step hooks      (Memory Bank 写入, Replan)

StepRunner 管单步内部:
    before_llm hooks  (Transform → Intercept)
    LLM Execute
    after_llm hooks   (Intercept → Observe)
    for each tool_call:
        before_tool hooks → Tool Execute → after_tool hooks
```

**这样 Hook 执行的所有权就清晰了**：
- 步级 hook（`before_step` / `after_step`）由 **LoopStrategy** 调用
- LLM/Tool 级 hook（`before_llm` / `after_llm` / `before_tool` / `after_tool`）由 **StepRunner** 调用
- 两者不重叠、不遗漏

---

## 二、三种 LoopStrategy

### 2.1 ReActLoop — 边思考边行动

**文件**: `src/lania_agent_runtime/loops/react.py`

**循环结构**:
```
for _ in range(max_iterations):
    # 步级 hook（由 LoopStrategy 调用）
    before_step_hooks()                     # Memory Bank 读取

    # 单步逻辑（委托给 StepRunner）
    step = step_runner.run_step(ctx)

    # 根据结果判断是否继续
    if step.status == "blocked":
        break
    elif step.status == "tool_calls":
        pass                                # 继续下一步
    elif step.finish_reason in ("stop", "length"):
        if router and router(ctx) == "continue":
            continue                        # Router 可覆盖默认结束
        break
    elif step.finish_reason == "tool_calls":
        continue

    after_step_hooks()                      # Memory Bank 写入
```

> **Router 的定位**：Router 不是 HookRegistry 中的组件，而是通过 `set_router()` 注入 Runtime 的可选决策函数。
> LoopStrategy 通过 `self._router`（由 Runtime 在构造时传入）检查是否有自定义路由逻辑，
> 而非通过 `HookRegistry.has_router()`。默认行为由 `finish_reason` 决定。

**对应当前代码**: `AgentRuntime._step_loop()` 的现有逻辑，直接迁移。

**适用场景**: 通用对话、简单工具调用、单步决策。

**关键行为**:
- 每步委托 `StepRunner.run_step()` 执行一次 LLM 调用 + 可能的工具调用
- `before_step` / `after_step` hooks 由 LoopStrategy 直接管理
- Router 作为可选的 `_router` 注入，不经过 HookRegistry

---

### 2.2 PlanExecuteLoop — 先规划再执行

**文件**: `src/lania_agent_runtime/loops/plan_execute.py`

**循环结构**:
```
# Phase 1: 规划（Planner 本质也是一次 LLM 调用，必须经过 hook 管线）
before_step_hooks()
step_runner.run_llm_only(ctx, planner_prompt)   # 走 before_llm → LLM → after_llm 完整管线
plan = extract_plan_from_response(ctx.messages[-1])
ctx.set_plan(plan)

# Phase 2: 执行（使用 while 循环配合 index，支持运行时 replan）
step_index = 0
max_replans = 3
replan_count = 0

while step_index < len(plan.steps):
    if paused/error/ended/cancelled: break

    step = plan.steps[step_index]
    ctx.context_payload.injected_context.append(step.description)

    step_result = step_runner.run_step(ctx)     # 通过 StepRunner 走完整单步

    after_step_hooks()                          # Memory Bank 写入

    # Phase 3 (可选): Replan
    if should_replan() and replan_count < max_replans:
        step_runner.run_llm_only(ctx, replanner_prompt)  # 同样经过 hook 管线
        plan = extract_plan_from_response(ctx.messages[-1])
        ctx.set_plan(plan)
        replan_count += 1
        step_index = find_current_step_index(plan, ctx)  # 定位到新 plan 的对应进度
        continue

    step_index += 1
```

> **为什么用 `while` 而不是 `for step in plan.steps`？**  
> 因为 Replan 会替换 `plan` 对象——`for` 循环在迭代开始时固定了迭代器，
> 替换 `plan` 变量不会影响循环。`while` + 手动 `step_index` 确保 replan 后的新步骤能被正确执行。

**Planner 格式**:
```json
{
  "steps": [
    {"id": "step_1", "description": "分析需求", "depends_on": []},
    {"id": "step_2", "description": "编写代码", "depends_on": ["step_1"]},
    {"id": "step_3", "description": "审查代码", "depends_on": ["step_2"]}
  ]
}
```

**适用场景**: 复杂任务需要预先拆解、多步骤流水线、代码生成、数据分析。

**关键设计**:
- Planner 和 Replanner 本质也是 LLM 调用，**必须走完整的 `StepRunner.run_llm_only()` 管线**（含 before_llm/after_llm hooks），不能直接调 `llm_executor()`，否则治理组件会有盲区
- `depends_on` 支持依赖关系（当前实现按序执行，拓扑排序为扩展预留）
- `should_replan()` 内置规则（如连续 tool call 失败、LLM 输出明显偏离 plan）
- Replan 有 `max_replans` 上限，避免无限循环
- `find_current_step_index()` 在新 plan 中定位当前进度：按 step description 匹配或从第一个未完成的 step 开始

---

### 2.3 WorkflowLoop — 固定 DAG + Agent 决策节点

**文件**: `src/lania_agent_runtime/loops/workflow.py`

**节点类型**:
```python
class NodeType(Enum):
    FIXED     = "fixed"       # 固定逻辑节点
    AGENT     = "agent"       # Agent 决策节点
    CONDITION = "condition"   # 条件分支节点

# 接口
class WorkflowNode(ABC):
    node_id: str
    depends_on: list[str]
    result: Any
    async def execute(self, ctx: RuntimeContext, step_runner: StepRunner) -> Any:

class FixedNode(WorkflowNode):
    """执行预定义 handler 函数"""
    def __init__(self, node_id: str, handler: Callable[[RuntimeContext], Any]):
        ...

class AgentNode(WorkflowNode):
    """
    Agent 决策节点：使用 StepRunner 执行一次完整的 LLM 调用 + 工具调用。
    内部调用 step_runner.run_step(ctx)，与 ReActLoop/PlanExecuteLoop 复用同一套单步逻辑。
    """
    def __init__(self, node_id: str, system_prompt: str = ""):
        ...

class ConditionNode(WorkflowNode):
    """
    条件分支节点：根据 condition_fn 的返回值选择后续路径。

    condition_fn 由 WorkflowDefinition.add_condition() 注入。
    返回值为分支名称（如 "branch_a"），WorkflowLoop 根据名称查找下一个节点。
    """
    def __init__(self, node_id: str, condition_fn: Callable[[RuntimeContext], Awaitable[str]]):
        ...
```

**循环结构**:
```
workflow = WorkflowDefinition()
workflow.add_node(FixedNode("classify", handler=classify_intent))
workflow.add_node(AgentNode("generate", system_prompt="..."))
workflow.add_node(ConditionNode("route", condition_fn=my_condition))
workflow.add_edge("classify", "route")
workflow.add_condition("route", {"qa": "answer_node", "escalate": "human_node"})

# 执行 —— 运行时遍历，无需预排序
current_node_id = workflow.start_node_id     # 由 WorkflowDefinition 指定
visited = set()

while current_node_id and not (paused/error/ended/cancelled):
    node = workflow.get_node(current_node_id)

    # 前置依赖检查
    if not all(dep in visited for dep in node.depends_on):
        raise WorkflowError(f"依赖未就绪: {node.node_id} 需要 {node.depends_on}")

    result = await node.execute(ctx, step_runner)
    node.result = result
    visited.add(current_node_id)

    after_step_hooks()

    # 决定下一个节点
    if isinstance(node, ConditionNode):
        branch = result               # condition_fn 的返回值
        current_node_id = workflow.conditions[node.node_id].get(branch)
    else:
        current_node_id = workflow.next_node(node.node_id)   # 默认顺序
```

> **为什么不用拓扑排序？**  
> ConditionNode 的分支选择在运行时才能确定，预排序无法处理动态分支。
> WorkflowLoop 采用**运行时图遍历**：从 `start_node_id` 开始，按边（edge）和条件（condition）跳转，
> 通过 `depends_on` 做前置校验而非排序。这同时支持了线性、分支和循环图结构。

**适用场景**: 客服流程、审批流程、数据处理 Pipeline、有固定业务流程的场景。

**关键设计**:
- `WorkflowDefinition` 是纯数据类，可序列化/反序列化（支持从配置文件加载）
- `AgentNode` 内部使用 `StepRunner.run_step()`，与 ReActLoop 复用同一套单步逻辑
- `ConditionNode` 的 `condition_fn` 通过 `WorkflowDefinition.add_condition()` 注入
- 运行时图遍历替代拓扑排序，天然支持分支和条件跳转
- `visited` 集合做依赖检查（确保前置节点已执行），同时防止循环图中无限循环

---

## 三、Multi-Agent 和 HumanInTheLoop 为什么不作为独立 LoopStrategy

### 3.1 Multi-Agent → 通过 Agent-as-tool 实现

**设计依据**: 设计文档 §九-4 "Agent-as-tool 是 Execute 的递归"

```
协调器 (使用 ReActLoop / PlanExecuteLoop 等任意策略)
  │
  ├── LLM 决定调用 delegate_to_agent 工具
  │     ├── 工具内部: 启动子 Runtime（独立 LoopStrategy）
  │     ├── 子 Runtime 继承父 Runtime 的 Observe hooks
  │     └── 子 Runtime 完成后结果通过 ToolResult 返回
  │
  └── 协调器拿到结果后继续自己的循环
```

**组件定义**:
```python
@dataclass
class SubAgentSpec:
    agent_id: str
    name: str
    description: str
    loop_strategy_name: str = "react"     # 子 Agent 可用不同策略
    llm_executor: LLMExecutor | None = None
    hooks: HookRegistry | None = None     # 与父 hooks 合并（非替换）
    system_prompt: str = ""

class AgentTool:
    """Agent-as-tool 工具实现。

    每次调用创建一个新的子 Runtime，执行完毕后释放。
    不缓存 Runtime 实例（子 Agent 通常低频调用，创建开销可接受）。
    如需高频调用场景，可在外层做 Runtime 池化。
    """
    def __init__(self, registry: dict[str, SubAgentSpec], parent_hooks: HookRegistry):
        self._registry = registry
        self._parent_hooks = parent_hooks

    async def execute(self, agent_id: str, task: str, context: Any) -> dict:
        spec = self._registry.get(agent_id)
        if not spec:
            raise ValueError(f"Unknown agent: {agent_id}")

        # 合并 hooks：子 Agent 的 hooks 与父 hooks 合并，而非替换
        merged_hooks = self._parent_hooks.copy()
        if spec.hooks:
            for info in spec.hooks.list():
                merged_hooks.register(info.point, info.handler, primitive=info.primitive, name=info.name, priority=info.priority)

        sub_runtime = AgentRuntime(
            loop_strategy_name=spec.loop_strategy_name,
            llm_executor=spec.llm_executor,
            hooks=merged_hooks,
        )
        result = await sub_runtime.run(task)
        return {"agent_id": agent_id, "result": result.content}
```

**实现位置**: 不需要新的 LoopStrategy。在 Tool 层实现 `delegate_to_agent` 工具，通过现有 ToolRegistry 注册即可。

### 3.2 HumanInTheLoop → 通过 Intercept pause 实现

**设计依据**: 设计文档 §九-3 "Human approval 是 Intercept 原语的 pause 状态"

```
before_tool Intercept:
  ├── 检查工具名/参数/预算 → 需要审批?
  │     ├── 不需要 → allow（放行）
  │     ├── notify 模式 → 通知 + allow
  │     └── 审批模式 → pause（挂起）
  │
  ├── pause 时:
  │     ├── ctx.pause_state 写入待审批列表
  │     ├── ctx.status = "paused"
  │     ├── checkpoint 保存工作记忆
  │     └── return（退出 step loop）
  │
  └── 外部恢复时:
        ├── Runtime.resume() 被调用
        ├── 清空 pause_state
        └── 重新走 before_tool → allow（审批通过后）
```

**审批策略**（配置化的 Interceptor）:
```python
class ApprovalPolicy(ABC):
    async def needs_approval(self, ctx, tool_name, arguments) -> tuple[bool, str]:

class ToolNamePolicy(ApprovalPolicy):       # 按工具名匹配
class BudgetThresholdPolicy(ApprovalPolicy): # 按 token/step 阈值
class RegexContentPolicy(ApprovalPolicy):    # 按参数内容匹配

class CompoundPolicy(ApprovalPolicy):
    """组合策略——默认 ANY（任一策略触发即审批），可通过 strategy="all" 切换为 ALL。"""
    def __init__(self, policies: list[ApprovalPolicy], strategy: str = "any"):
        self.policies = policies
        self.strategy = strategy  # "any" | "all"
```

**实现位置**: 不需要新的 LoopStrategy。在 Hook 层实现 `HumanApprovalInterceptor`，注册到 `before_tool` 即可。

```
hooks.intercept(BEFORE_TOOL, HumanApprovalInterceptor(
    policy=CompoundPolicy([
        ToolNamePolicy(["deploy", "delete_db"]),
        BudgetThresholdPolicy(token_threshold=50000),
    ], strategy="any"),             # 任一条件触发即审批
    mode="async_deferred",          # sync_blocking / async_deferred / notify_only
))
```

**Resume 防护**：从 pause 恢复后重新走 `before_tool` 时，`HumanApprovalInterceptor` 必须识别出"这是同一个审批通过的请求"并自动放行，避免审批死循环。

实现方式：`HumanApprovalInterceptor` 内部维护一个 `approved_ids: set[str]` 集合。
恢复时 Runtime 传入 `approval_id`，Interceptor 检查该 ID 是否已审批通过，
如是则跳过审批直接 `allow`。

---

## 四、LoopStrategyFactory

```python
class LoopStrategyFactory:
    _registry: dict[str, type[LoopStrategy]] = {}

    @classmethod
    def register(cls, name: str, strategy_cls: type[LoopStrategy]) -> None:
        cls._registry[name] = strategy_cls

    @classmethod
    def create(cls, name: str, **kwargs) -> LoopStrategy:
        """
        通过工厂创建策略实例。
        各策略所需的参数不同，通过 **kwargs 传入：
        - react: hooks, step_runner, router=None
        - plan_and_execute: hooks, step_runner, router=None, planner_prompt="", max_replans=3
        - workflow: hooks, step_runner, workflow_definition
        """
        if name not in cls._registry:
            raise ValueError(f"Unknown strategy: {name}")
        return cls._registry[name](**kwargs)

    @classmethod
    def available(cls) -> list[str]:
        return list(cls._registry.keys())
```

注册方式（**不在模块级自动注册**，避免循环导入）:
```python
# 在 AgentRuntime.__init__ 或包初始化函数中显式注册
from lania_agent_runtime.loops.react import ReActLoop
from lania_agent_runtime.loops.plan_execute import PlanExecuteLoop
from lania_agent_runtime.loops.workflow import WorkflowLoop

LoopStrategyFactory.register("react", ReActLoop)
LoopStrategyFactory.register("plan_and_execute", PlanExecuteLoop)
LoopStrategyFactory.register("workflow", WorkflowLoop)
```

> **为什么不在模块级自动注册？** 模块加载时执行 `register()` 会导致
> `loops/__init__.py` 与 `loops/react.py` 之间可能的循环导入。
> 改为在 `AgentRuntime.__init__` 或一个显式的 `register_all_strategies()` 函数中注册。
> WorkflowLoop 因需要注入 `WorkflowDefinition`，通常直接注入实例而非通过工厂创建。

---

## 五、AgentRuntime 的改动

```python
class AgentRuntime:
    def __init__(
        self,
        ...,
        # 新增:
        loop_strategy: LoopStrategy | None = None,          # 直接注入实例
        loop_strategy_name: str = "react",                  # 或通过工厂创建
    ):
        ...
        # StepRunner 作为 Runtime 内部组件，被所有 LoopStrategy 共享
        self._step_runner = StepRunner(
            hooks=self._hooks,
            llm_executor=self._llm_executor,
            tool_executor=self._tool_executor,
        )

        if loop_strategy is not None:
            self._loop = loop_strategy
        else:
            self._loop = LoopStrategyFactory.create(
                loop_strategy_name,
                hooks=self._hooks,
                step_runner=self._step_runner,
                router=self._router,
            )

    # _step_loop 和 _step_loop_stream 替换为:
    async def run(self, ...) -> RunResult:
        ...
        await self._loop.run(self._ctx)     # 代替 self._step_loop()
        return self._collect_result()

    async def run_stream(self, ...) -> AsyncIterator[StreamEvent]:
        ...
        async for event in self._loop.run_stream(self._ctx):
            yield event
```

**向后兼容**：`loop_strategy_name="react"` 为默认值，行为与当前完全一致。

---

## 六、用例速览

```python
# ReAct（默认）
runtime = AgentRuntime(llm_executor=executor)

# Plan-and-Execute
runtime = AgentRuntime(llm_executor=executor, loop_strategy_name="plan_and_execute")

# Workflow
from lania_agent_runtime.loops.workflow import WorkflowDefinition, FixedNode, AgentNode
wf = WorkflowDefinition([
    FixedNode("classify", handler=classify_intent),
    AgentNode("generate", system_prompt="Generate response"),
])
wf.add_edge("classify", "generate")
runtime = AgentRuntime(
    llm_executor=executor,
    loop_strategy=WorkflowLoop(hooks=hooks, workflow=wf),
)

# Multi-Agent（无需新 LoopStrategy）
runtime = AgentRuntime(llm_executor=coordinator_executor)
runtime.register_tool("delegate_to_agent", AgentTool(agent_registry))

# Human-in-the-loop（无需新 LoopStrategy）
hooks.intercept(BEFORE_TOOL, HumanApprovalInterceptor(
    policy=ToolNamePolicy(["deploy"]),
))
runtime = AgentRuntime(llm_executor=executor, hooks=hooks)
```
