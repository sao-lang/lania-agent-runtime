# 编排组件技术方案

## 一、概念定位

根据之前的分析，编排组件（Planner / Replan / Reflection / 自我批评 / 双重验证 / CoT / 子任务拆解）与基础设施组件（Memory / Context / LLMExecutor / Tools）的关系是 **"消费者与提供者"**：

```
编排组件 (Orchestration Components)
    消费者，使用基础设施完成特定编排逻辑
          │
          ▼
基础设施组件 (Infrastructure Components)
    Memory / Context / LLMExecutor / Tools
    提供者，被编排组件调用
```

---

## 二、七个编排组件的技术方案

### 2.1 Chain of Thought (CoT)

**定位**: LLM 配置层，不属于架构组件。

**技术实现**:
```python
@dataclass
class LLMExecutorConfig:
    ...
    reasoning_instruction: str = ""   # 新增字段

    # 预设模式
    @classmethod
    def with_cot(cls, **overrides) -> "LLMExecutorConfig":
        """启用 CoT 的快捷配置。"""
        return cls(
            reasoning_instruction="Let's think step by step.",
            temperature=0.7,
            **overrides,
        )

    @classmethod
    def with_deep_reasoning(cls, **overrides) -> "LLMExecutorConfig":
        """启用深度推理的快捷配置。"""
        return cls(
            reasoning_instruction=(
                "You are a reasoning expert. Before answering, "
                "break down the problem, analyze each part, "
                "and synthesize your findings."
            ),
            temperature=0.5,
            **overrides,
        )
```

**序列化时机**: `RuntimeContext.serialize_for_llm()` 将 `reasoning_instruction` 追加到 system message 末尾。

**变更点**:
- `LLMExecutorConfig` 新增 `reasoning_instruction` 字段
- `ContextPayload.serialize_to_system_message()` 追加该字段

---

### 2.2 子任务拆解 (Sub-task Decomposition)

**定位**: 两种模式，分别嵌入不同的 LoopStrategy。

#### 模式 A：隐式拆解（ReAct 原生）

**不需要任何组件**。ReAct 循环本身就是一种拆解——每一步，LLM 选择一个工具/回复，逐步逼近目标。

```python
# 已经存在，不需要额外代码
class ReActLoop(LoopStrategy):
    async def async_loop(self, ctx):
        # LLM 在每一步自然地拆解任务
        # "先查资料" → "再分析" → "最后回答"
        ...
```

#### 模式 B：显式拆解（Planner 驱动）

**由 Planner 组件完成**（见 2.3）。

**选择依据**:

| 判断条件 | 选隐式拆解 | 选显式拆解 |
|---------|-----------|-----------|
| 任务复杂度 | 低～中 | 中～高 |
| 步骤数量 | 1～5 步 | 5+ 步 |
| 步骤间依赖 | 线性 | 有 fork/join |
| 需要步骤可见性 | 不需要 | 需要（展示给用户） |
| 中途可以重新规划 | 可以（但不必要） | 必要 |

---

### 2.3 Planner

**定位**: PlanExecuteLoop 的内置阶段。也可作为独立 Tool 被其他策略使用。

#### 用法 1：PlanExecuteLoop 的内置阶段

```python
class PlanExecuteLoop(LoopStrategy):
    """PlanExecuteLoop 的一个内置阶段。"""

    def __init__(self, ..., planner_prompt: str | None = None):
        self._planner_prompt = planner_prompt or DEFAULT_PLANNER_PROMPT

    async def _generate_plan(self, ctx: RuntimeContext) -> list[Step]:
        """Phase 1: 生成执行计划。"""
        planning_messages = [
            {"role": "system", "content": self._planner_prompt},
            *self._extract_user_messages(ctx),
        ]
        # 临时替换 messages 调用 LLM
        response = await self._call_llm_with(planning_messages, ctx)
        return self._parse_plan(response.content)

DEFAULT_PLANNER_PROMPT = """
You are a planner. Break down the user's request into a step-by-step plan.
Return a JSON array of steps:
[
  {"id": "step_1", "description": "What to do in this step", "depends_on": []},
  {"id": "step_2", "description": "Next step", "depends_on": ["step_1"]}
]
Only return the JSON array, nothing else.
"""
```

**Planner 的输入输出**:

```
Input:  ctx.messages（用户输入 + 历史）
Output: ctx.plan（JSON steps 结构）

ctx.plan = {
    "strategy": "plan_and_execute",
    "steps": [
        {"id": "step_1", "description": "分析需求", "status": "pending", "depends_on": []},
        {"id": "step_2", "description": "编写代码", "status": "pending", "depends_on": ["step_1"]},
    ]
}
```

#### 用法 2：独立 Tool（供 ReAct 等策略使用）

```python
class PlannerTool:
    """作为 Tool 的 Planner，可以被任何 LoopStrategy 使用。"""

    name = "generate_plan"
    description = "Generate a step-by-step plan for a complex task"
    parameters = {
        "type": "object",
        "properties": {
            "task": {"type": "string", "description": "The task to plan for"},
        },
        "required": ["task"],
    }

    def __init__(self, llm_executor: LLMExecutor, prompt: str = DEFAULT_PLANNER_PROMPT):
        self._llm = llm_executor
        self._prompt = prompt

    async def execute(self, task: str, ctx: RuntimeContext) -> dict:
        """生成计划。"""
        messages = [
            {"role": "system", "content": self._prompt},
            {"role": "user", "content": task},
        ]
        # 临时创建子 context 调用 LLM
        response = await self._llm.execute(
            self._build_sub_context(ctx, messages)
        )
        return {"plan": self._parse_plan(response.content)}
```

---

### 2.4 Replan

**定位**: PlanExecuteLoop 的内置阶段（Phase 3），或作为 Hook 被其他策略使用。

#### 用法 1：PlanExecuteLoop 的内置阶段

```python
class PlanExecuteLoop(LoopStrategy):
    def __init__(self, ..., replan_enabled: bool = True, max_replans: int = 3):
        self._replan_enabled = replan_enabled
        self._max_replans = max_replans
        self._replan_count = 0

    async def _should_replan(self, ctx: RuntimeContext) -> bool:
        """判断是否需要重新规划。"""
        if not self._replan_enabled:
            return False
        if self._replan_count >= self._max_replans:
            return False

        # 判断条件（可配置）:
        # 1. Router 返回 "replan"
        if self._hooks.has_router():
            result = await self._hooks.run_router(ctx)
            if result == "replan":
                self._replan_count += 1
                return True

        # 2. (可选) 内置启发式：连续错误、token 超限等
        if self._detect_deviation(ctx):
            self._replan_count += 1
            return True

        return False

    def _detect_deviation(self, ctx: RuntimeContext) -> bool:
        """内置偏差检测（可选）。"""
        return (
            ctx.error_state.consecutive_errors >= 2
            or ctx.budget.token_used > ctx.budget.token_limit * 0.8
        )

    async def _replan(self, ctx: RuntimeContext) -> None:
        """执行重新规划。"""
        # 注入 replan 上下文（包含已有进度）
        ctx.context_payload.injected_context.append(
            f"[Replan #{self._replan_count}] "
            f"Current progress: {self._get_progress_summary()}"
        )
        new_plan = await self._generate_plan(ctx)
        ctx.set_plan({
            "strategy": "plan_and_execute",
            "replanned": True,
            "replan_count": self._replan_count,
            "steps": new_plan,
        })
```

#### 用法 2：after_step Hook（供 ReAct 等策略使用）

```python
class ReplanHook:
    """作为 Hook 的 Replan，可挂到任何 LoopStrategy 的 after_step。"""

    def __init__(self, llm_executor: LLMExecutor, max_replans: int = 3):
        self._llm = llm_executor
        self._max_replans = max_replans
        self._count: dict[str, int] = defaultdict(int)

    async def __call__(self, step_result: dict, ctx: RuntimeContext) -> dict:
        """作为 Transform Hook 运行。"""
        session_id = ctx.session_id
        if self._count[session_id] >= self._max_replans:
            return step_result

        if await self._needs_replan(ctx):
            self._count[session_id] += 1
            new_plan = await self._generate_replan(ctx)
            ctx.set_plan(new_plan)

        return step_result

# 注册到任意 LoopStrategy:
hooks.transform(AFTER_STEP, ReplanHook(llm_executor))
```

---

### 2.5 Reflection / 自我批评 / 双重验证

**定位**: 三者本质上是同一模式的不同变体——**"用 LLM 检查 LLM 的输出"**。作为 Hook 实现。

**三种变体**:

```python
# ── 变体 1: 单模型自我批评 ──
# 生成模型和批评模型是同一个
class SelfCritiqueHook:
    """自我批评：生成后用同一模型检查。"""

    def __init__(
        self,
        llm_executor: LLMExecutor,
        critique_prompt: str = DEFAULT_CRITIQUE_PROMPT,
        max_retries: int = 1,
    ):
        self._llm = llm_executor
        self._critique_prompt = critique_prompt
        self._max_retries = max_retries
        self._attempts: dict[str, int] = defaultdict(int)

    async def __call__(self, response: LLMResponse, ctx: RuntimeContext) -> LLMResponse:
        """Transform: 检查 LLM 输出，不合格则 retry。"""
        if not response.content:
            return response

        session_id = ctx.session_id
        self._attempts[session_id] = self._attempts.get(session_id, 0) + 1

        if self._attempts[session_id] > self._max_retries + 1:
            return response

        # 调用批评 LLM
        critique = await self._critique(response.content, ctx)
        if critique.is_acceptable:
            return response

        # 不合格：替换 response，触发重试
        ctx.append_message({
            "role": "user",
            "content": (
                f"[Self-Critique Feedback]\n"
                f"Issues found:\n{critique.issues}\n"
                f"Please improve your response."
            ),
        })
        # 通过修改 finish_reason 让 ReActLoop 继续循环
        response.finish_reason = "tool_calls"  # 强制继续
        return response


# ── 变体 2: 双模型批评 ──
# 生成模型和批评模型分开
class DualModelCritiqueHook:
    """双重验证：生成模型 + 批评模型分开。"""

    def __init__(
        self,
        generator: LLMExecutor,     # 生成模型（可能就是 loop 的 executor）
        critic: LLMExecutor,        # 批评模型（另一个实例，不同配置/model）
        critique_prompt: str = DEFAULT_CRITIQUE_PROMPT,
    ):
        self._generator = generator
        self._critic = critic
        self._critique_prompt = critique_prompt

    async def __call__(self, response: LLMResponse, ctx: RuntimeContext) -> LLMResponse:
        """after_llm Transform: 用批评模型检查生成模型的输出。"""
        if not response.content:
            return response

        critique = await self._critique(response.content, ctx)
        if critique.is_acceptable:
            return response

        # 不合格 → 尝试修正
        corrected = await self._correct(response.content, critique, ctx)
        response.content = corrected.content
        return response


# ── 变体 3: Intercept 模式 ──
# 不合格直接 block（触发 on_error）
class CritiqueInterceptor:
    """批评拦截器：不合格直接 block。"""

    async def __call__(self, response: LLMResponse, ctx: RuntimeContext) -> InterceptResult:
        critique = await self._critique(response.content, ctx)
        if critique.is_acceptable:
            return InterceptResult(action="allow")
        return InterceptResult(
            action="block",
            reason=f"Critique failed: {critique.issues[:200]}",
        )
```

**CritiquePrompt 模板**:

```python
DEFAULT_CRITIQUE_PROMPT = """
You are a critical reviewer. Analyze the following response and identify:

1. Factual errors or hallucination
2. Logical inconsistencies
3. Missing important information
4. Unclear or ambiguous statements

Response to review:
{response}

Output JSON:
{
  "is_acceptable": true/false,
  "issues": ["issue1", "issue2"],
  "suggestions": ["suggestion1"]
}
"""
```

**三种变体对比**:

| 变体 | 拦截方式 | 模型数 | 适用场景 |
|------|---------|--------|---------|
| SelfCritiqueHook | Transform（重试） | 1个 | 轻量自查，适合通用场景 |
| DualModelCritiqueHook | Transform（修正） | 2个 | 严格验证，适合代码生成/文档 |
| CritiqueInterceptor | Intercept（block） | 2个 | 安全关键场景，零容忍 |

**注册示例**:

```python
# 轻量自查
hooks.transform(AFTER_LLM, SelfCritiqueHook(llm_executor, max_retries=1))

# 严格双重验证
hooks.transform(AFTER_LLM, DualModelCritiqueHook(
    generator=llm_executor,
    critic=another_executor,  # 不同 model / 不同配置
))

# 安全拦截
hooks.intercept(AFTER_LLM, CritiqueInterceptor(critic_executor))
```

---

## 三、组件依赖矩阵（完整版）

```
                     依赖                       提供方
编排组件     Memory  Context  LLMExecutor  Tools    来源
──────────────────────────────────────────────────────────
CoT           ❌      ✅(改)      ✅       ❌      LLMExecutorConfig
子任务拆解(隐) ❌      ✅        ✅       ✅(执行)  ReActLoop（内置）
子任务拆解(显) ❌      ✅        ✅       ❌      PlanExecuteLoop（内置）
Planner       ❌      ✅        ✅       ❌      PlanExecuteLoop / Tool
Replan       ⚠️可选   ✅        ✅       ❌      PlanExecuteLoop / Hook
SelfCritique  ❌      ✅        ✅       ❌      Hook（Transform）
DualCritique  ❌      ✅        ✅(×2)   ❌      Hook（Transform）
Critique拦截  ❌      ✅        ✅       ❌      Hook（Intercept）
```

---

## 四、实现优先级

```
Phase 1（核心）:
  └── LoopStrategy 框架 (base.py + factory)
  └── ReActLoop（当前 _step_loop 迁移）
  └── CoT（LLMExecutorConfig.reasoning_instruction）

Phase 2（规划能力）:
  └── PlanExecuteLoop（含 Planner + Replan 内置）
  └── PlannerTool（可选，供 ReAct 使用）

Phase 3（质量保障）:
  └── SelfCritiqueHook（单模型自我批评）
  └── DualModelCritiqueHook（双模型双重验证）

Phase 4（高级模式）:
  └── WorkflowLoop（DAG 编排）
  └── AgentTool（Multi-Agent 支持）
  └── CritiqueInterceptor（安全拦截）
```

---

## 五、代码文件组织

```
src/lania_agent_runtime/
  ├── loops/                          # 新建
  │   ├── __init__.py                 # 导出所有 LoopStrategy
  │   ├── base.py                     # LoopStrategy ABC + LoopStrategyFactory
  │   ├── react.py                    # ReActLoop
  │   ├── plan_execute.py             # PlanExecuteLoop（含 Planner/Replan 内置）
  │   └── workflow.py                 # WorkflowLoop + WorkflowDefinition + 节点类型
  │
  ├── hooks/                          # 已有，新增文件
  │   ├── critique_hook.py            # SelfCritiqueHook / DualModelCritiqueHook
  │   ├── replan_hook.py              # ReplanHook（作为 Hook 的变体）
  │   └── approval_hook.py            # HumanApprovalInterceptor + ApprovalPolicy
  │
  ├── executor.py                     # CoT: LLMExecutorConfig.reasoning_instruction 字段
  └── runtime.py                      # 使用 LoopStrategy 替代 _step_loop
```
