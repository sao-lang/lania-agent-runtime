# Loop 策略技术方案

## 一、概述

将 Agent Runtime 的执行循环从 `AgentRuntime._step_loop()` 中提取为可插拔的 `LoopStrategy` 组件。每种 Agent 工作方式对应一个 LoopStrategy 实现，共享同一套基础设施（Hook / LLMExecutor / Memory / Context）。

设计原则：
- **架构现有入口**：HookRegistry 已预留 `set_loop_executor()`，本方案将其真正用起来
- **不引入新概念**：三种策略覆盖所有需求，Multi-Agent / HITL 通过现有机制（Agent-as-tool / Intercept pause）实现
- **单一职责**：策略只管"循环怎么走"，不管"单步怎么做"（单步逻辑由 StepRunner 封装）

---

## 二、三种 LoopStrategy

### 2.1 ReActLoop — 边思考边行动

**文件**: `src/lania_agent_runtime/loops/react.py`

**循环结构**:
```
for _ in range(max_iterations):
    before_step_hooks()
    router_check()              # 可选: HookRegistry.has_router()
    before_llm_hooks()
    response = llm_executor()
    append_assistant_message()
    after_llm_hooks()
    for tc in response.tool_calls:
        execute_tool(tc)        # 含 before_tool / after_tool hooks
    after_step_hooks()
    if router() == "end": break
    elif finish_reason in ("stop", "length"): break
    elif finish_reason == "tool_calls": continue
```

**对应当前代码**: `AgentRuntime._step_loop()` 的现有逻辑，直接迁移。

**适用场景**: 通用对话、简单工具调用、单步决策。

**关键行为**:
- 每步调用一次 LLM，按返回的 `finish_reason` 判断是否继续
- 支持 Router 覆盖默认的结束判断
- `tool_calls` 循环紧跟在 LLM 调用之后

---

### 2.2 PlanExecuteLoop — 先规划再执行

**文件**: `src/lania_agent_runtime/loops/plan_execute.py`

**循环结构**:
```
# Phase 1: 规划
before_step_hooks()
plan = planner(task)            # 调用 LLM 生成 Plan JSON
ctx.set_plan(plan)

# Phase 2: 执行
for step in plan.steps:
    if paused/error/ended: break

    # 注入步骤上下文
    ctx.context_payload.injected_context.append(step_context)

    before_llm_hooks()
    response = llm_executor()
    append_assistant_message()
    after_llm_hooks()
    for tc in response.tool_calls:
        execute_tool(tc)
    after_step_hooks()

    # Phase 3 (可选): Replan
    if should_replan():
        plan = replanner(ctx)   # 调用 LLM 重新生成 plan
        ctx.set_plan(plan)
```

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
- Planner 和 Replanner 共享同一个 prompt 模板（可配置）
- `depends_on` 支持依赖关系（当前实现按序执行，拓扑排序为扩展预留）
- `should_replan()` 判断逻辑：可以通过 Hook Router 触发，也可以通过内置规则（偏差检测）
- Replan 有次数上限，避免无限循环

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
    async def execute(ctx, loop) -> Any

class FixedNode(WorkflowNode):      # 执行预定义 handler 函数
class AgentNode(WorkflowNode):      # 调用 LLM + 工具
class ConditionNode(WorkflowNode):  # 根据条件选择分支
```

**循环结构**:
```
workflow = WorkflowDefinition([node1, node2, ...])
workflow.add_edge("node1", "node2")
workflow.add_condition("cond_node", {"branch_a": "node3", "branch_b": "node4"})

# 执行
sorted_nodes = topological_sort(workflow)
for node in sorted_nodes:
    if paused/error/ended: break
    result = execute_node(node)
    # ConditionNode 会根据 selected_branch 自动跳转
    after_step_hooks()
```

**适用场景**: 客服流程、审批流程、数据处理 Pipeline、有固定业务流程的场景。

**关键设计**:
- `WorkflowDefinition` 是纯数据类，可序列化/反序列化（支持从配置文件加载）
- `AgentNode` 内部使用 StepRunner 的单步逻辑（复用了 before_llm → LLM → after_llm → tool_calls）
- `ConditionNode` 的 `condition_fn` 是注入的异步函数，不依赖特定实现
- 拓扑排序确保依赖顺序执行

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
    hooks: HookRegistry | None = None     # 可选覆盖父 hooks
    system_prompt: str = ""

class AgentTool:
    """Agent-as-tool 工具实现。"""
    async def execute(self, agent_id: str, task: str, context: Any) -> dict:
        spec = registry.get(agent_id)
        sub_runtime = AgentRuntime(
            loop_strategy_name=spec.loop_strategy_name,
            llm_executor=spec.llm_executor,
            hooks=spec.hooks or parent_hooks,
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
    async def needs_approval(ctx, tool_name, arguments) -> tuple[bool, str]:

class ToolNamePolicy(ApprovalPolicy):       # 按工具名匹配
class BudgetThresholdPolicy(ApprovalPolicy): # 按 token/step 阈值
class RegexContentPolicy(ApprovalPolicy):    # 按参数内容匹配
class CompoundPolicy(ApprovalPolicy):        # 组合策略
```

**实现位置**: 不需要新的 LoopStrategy。在 Hook 层实现 `HumanApprovalInterceptor`，注册到 `before_tool` 即可。

```
hooks.intercept(BEFORE_TOOL, HumanApprovalInterceptor(
    policy=CompoundPolicy([
        ToolNamePolicy(["deploy", "delete_db"]),
        BudgetThresholdPolicy(token_threshold=50000),
    ]),
    mode="async_deferred",     # sync_blocking / async_deferred / notify_only
))
```

---

## 四、LoopStrategyFactory

```python
class LoopStrategyFactory:
    _registry: dict[str, type[LoopStrategy]] = {}

    @classmethod
    def register(cls, name: str, strategy_cls: type[LoopStrategy]) -> None:
        cls._registry[name] = strategy_cls

    @classmethod
    def create(cls, name: str, hooks, llm_executor=None, memory=None) -> LoopStrategy:
        if name not in cls._registry:
            raise ValueError(f"Unknown strategy: {name}")
        return cls._registry[name](hooks=hooks, llm_executor=llm_executor, memory=memory)

    @classmethod
    def available(cls) -> list[str]:
        return list(cls._registry.keys())
```

自动注册（模块级）:
```python
# react.py
LoopStrategyFactory.register("react", ReActLoop)

# plan_execute.py
LoopStrategyFactory.register("plan_and_execute", PlanExecuteLoop)

# workflow.py
LoopStrategyFactory.register("workflow", WorkflowLoop)
```

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
        if loop_strategy is not None:
            self._loop = loop_strategy
        else:
            self._loop = LoopStrategyFactory.create(
                loop_strategy_name,
                hooks=self._hooks,
                llm_executor=self._llm_executor,
                memory=self._memory,
            )

    # _step_loop 和 _step_loop_stream 替换为:
    async def run(self, ...) -> RunResult:
        ...
        await self._loop.async_loop(self._ctx)     # 代替 self._step_loop()
        return self._collect_result()

    async def run_stream(self, ...) -> AsyncIterator[StreamEvent]:
        ...
        async for event in self._loop.async_loop_stream(self._ctx):
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
