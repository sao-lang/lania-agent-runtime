### 2026-07-23

#### 4. 实现 Tool 原语（ToolSpec + ToolRegistry + ToolDispatcher）

- **时间：** 2026-07-23
- **发起人：** user
- **修改文件：**
  - `src/tools/__init__.py` — 包入口，导出 ToolSpec/ToolRegistry/ToolDispatcher
  - `src/tools/_spec.py` — ToolSpec 数据类（name/description/parameters/handler + to_openai_schema）
  - `src/tools/_registry.py` — ToolRegistry（register/describe/execute，覆盖注册策略）
  - `src/tools/_dispatcher.py` — ToolDispatcher（统一调度入口，当前仅 Tool 路由，MCP 占位）
  - `src/tools/_mcp/__init__.py` — MCP 占位包
  - `src/tools/_skill/__init__.py` — Skill 占位包
  - `src/runtime/_runtime.py` — 集成 ToolDispatcher（tools 参数、_inject_tools_schema Transform、tool_registry property）
  - `src/runtime/_builder.py` — 新增 tool_registry() 链式方法
  - `src/runtime/__init__.py` — 导出 ToolSpec/ToolRegistry/ToolDispatcher
  - `tests/test_tools.py` — 33 个单元测试（ToolSpec/ToolRegistry/ToolDispatcher/Runtime集成/Builder集成）
- **修改内容：** 按照设计文档 tool-mcp-skill-design.md 实现 Tool 原语。ToolSpec 定义工具数据结构，ToolRegistry 管理注册/描述/执行（覆盖注册策略），ToolDispatcher 统一调度（当前仅 Tool 路由，MCP 前缀路由为占位）。通过 tools 参数集成到 AgentRuntime，自动创建 ToolDispatcher 并设为 tool_executor，注册 before_llm Transform 自动刷新 tools_schema。RuntimeBuilder 新增 tool_registry() 方法。MCP 和 Skill 原语预留目录结构，待后续迭代实现。
- **复盘结果：** 366 测试全部通过（原有 333 + 新增 33），tools 包覆盖率 98.96%，ruff lint 零报错。
- **潜在风险：** 无。向后兼容：旧 tool_executor 接口保留，tools 参数可选。

#### 3. 实现 Loop 策略模块（可插拔执行循环）

- **时间：** 2026-07-23
- **发起人：** user
- **修改文件：**
  - `src/runtime/loops/__init__.py` — 包入口，导出全部 Loop 类型
  - `src/runtime/loops/_base.py` — `LoopStrategy` ABC（run/run_stream/步级 hook 接口）
  - `src/runtime/loops/_factory.py` — `LoopStrategyFactory`（注册 + 创建）
  - `src/runtime/loops/_types.py` — `StepResult`, `StepStatus`, `Plan`, `PlanStep`
  - `src/runtime/loops/_react.py` — `ReActLoop`（边思考边行动）
  - `src/runtime/loops/_plan_execute.py` — `PlanExecuteLoop`（先规划再执行 + Replan）
  - `src/runtime/loops/_workflow.py` — `WorkflowLoop`, `WorkflowDefinition`, `FixedNode`, `AgentNode`, `ConditionNode`
  - `src/runtime/hooks/_approval_hook.py` — `HumanApprovalInterceptor` + 审批策略族
  - `src/runtime/hooks/_critique_hook.py` — `SelfCritiqueHook`, `DualModelCritiqueHook`
  - `src/runtime/hooks/_replan_hook.py` — `ReplanHook`（可插拔 Replan）
  - `src/runtime/hooks/__init__.py` — 导出新 Hook 类型
  - `src/runtime/_steps/_step_runner.py` — 新增 `run_step()`, `run_llm_only()` 方法
  - `src/runtime/_runtime.py` — 集成 `LoopStrategy`（`loop_strategy`/`loop_strategy_name` 参数），`set_loop_strategy()` 方法
  - `src/runtime/__init__.py` — 导出 Loop/Hook 新类型
  - `tests/test_loops.py` — 39 个单元测试（工厂/ReAct/PlanExecute/Workflow）
  - `tests/test_hooks_approval.py` — 26 个单元测试（审批策略/Interceptor/Critique/ReplanHook）
- **修改内容：** 将 Agent Runtime 的执行循环从 `_step_loop()` 提取为可插拔的 `LoopStrategy` 组件。三种策略覆盖所有工作方式，共享 StepRunner 基础设施。Hook 层补充了 HumanInTheLoop 审批、自我批评和可插拔 Replan 能力。向后兼容：旧 `loop_executor` 接口保留。
- **复盘结果：** 330 测试全部通过（265 原有 + 65 新增），ruff lint 零报错。
- **潜在风险：** 无。

#### 2. 实现 LLMExecutor 模块（Execute 原语）

- **时间：** 2026-07-23
- **发起人：** user
- **修改文件：**
  - `src/runtime/llm/__init__.py` — 包入口，导出全部 LLM 类型
  - `src/runtime/llm/_interfaces.py` — `LLMExecutor` / `StreamableLLMExecutor` ABC
  - `src/runtime/llm/_models.py` — `LLMResponse`, `ToolCall`, `LLMUsage`, `FinishReason`, `LLMMessage`
  - `src/runtime/llm/_config.py` — `LLMExecutorConfig`
  - `src/runtime/llm/_errors.py` — `LLMExecutionError`
  - `src/runtime/llm/_retry.py` — `RetryPolicy`
  - `src/runtime/llm/_providers/__init__.py`
  - `src/runtime/llm/_providers/_base.py` — `LLMProvider` 抽象 + `LLMProviderResponse`
  - `src/runtime/llm/_providers/_openai.py` — `OpenAIProvider`（OpenAI SDK 适配）
  - `src/runtime/llm/_executors/__init__.py`
  - `src/runtime/llm/_executors/_openai.py` — `OpenAILLMExecutor`（核心 + 流式）
  - `src/runtime/llm/_executors/_stream.py` — `AsyncStreamCollector`
  - `src/runtime/_runtime.py` — 适配 `_execute_llm_step` 支持 `LLMResponse`、`_get_next_step` 基于 `finish_reason` 判断
  - `src/runtime/_builder.py` — `build()` 自动创建 `OpenAILLMExecutor`
  - `src/runtime/_types.py` — 新增 `LLMExecutorFn` 注释
  - `src/runtime/__init__.py` — 导出 LLM 相关类型
  - `tests/test_llm_executor.py` — 51 个单元测试（数据模型、Provider、Executor、流式、重试、集成适配）
- **修改内容：** 实现 LLMExecutor 模块，定义 Execute 原语的 LLM 特化接口。LLMExecutor 负责 "messages → LLM API → LLMResponse" 的纯函数往返，不写 ctx.messages，结果通过 return 传回。
- **复盘结果：** 259 测试全部通过。lint 仅剩 `main.py` 预先存在的 `ANN201` 警告。向后兼容：旧接口 `ExecutorFn` 仍然可用。
- **潜在风险：** 无。

#### 1. 实现 Agent Runtime 核心骨架

- **时间：** 2026-07-23
- **发起人：** user
- **修改文件：**
  - `src/runtime/__init__.py` — 包入口导出
  - `src/runtime/_types.py` — 类型枚举、Protocol、数据类
  - `src/runtime/_runtime.py` — AgentRuntime 核心类（状态机 + step loop）
  - `src/runtime/_pipeline.py` — Pipeline[T] 通用管线框架
  - `src/runtime/context/__init__.py`
  - `src/runtime/context/_payload.py` — ContextPayload（上下文中间层 + 脏标记）
  - `src/runtime/context/_context.py` — RuntimeContext（不可变快照 + 受限写接口）
  - `src/runtime/context/_serializer.py` — MessageSerializer 接口 + DefaultSerializer
  - `src/runtime/hooks/__init__.py`
  - `src/runtime/hooks/_primitives.py` — 原语协议重导出
  - `src/runtime/hooks/_registry.py` — HookRegistry（分层编排引擎）
  - `src/runtime/config/__init__.py`
  - `src/runtime/config/_runtime_config.py` — RuntimeConfig 多源加载
  - `src/runtime/plugins/__init__.py`
  - `src/runtime/plugins/_plugin.py` — PluggableComponent + Plugin 协议
  - `tests/__init__.py`
  - `tests/test_types.py`
  - `tests/test_context_payload.py`
  - `tests/test_runtime_context.py`
  - `tests/test_serializer.py`
  - `tests/test_hook_registry.py`
  - `tests/test_pipeline.py`
  - `tests/test_plugin.py`
  - `tests/test_runtime_config.py`
  - `tests/test_runtime.py`
  - `tests/test_runtime_advanced.py`
  - `tests/test_coverage_edge.py`
- **修改内容：** 按照 agent-runtime-design.md 架构设计，实现 Runtime 核心骨架，包含 AgentRuntime、HookRegistry、Pipeline、ContextPayload、RuntimeContext、MessageSerializer、PluggableComponent/Plugin、RuntimeConfig 等模块。
- **复盘结果：** 171 个测试全部通过，覆盖率 96.30%，ruff lint/format 零报错。
- **潜在风险：** 部分高级功能（LLMExecutor 具体适配器、LoopStrategy、ContextManager 五阶段管线）尚未实现，需要后续子模块补充。
