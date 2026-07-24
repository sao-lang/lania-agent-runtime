### 2026-07-24

#### 6. 集成上下文与记忆系统（Context + Memory 原语）

- **时间：** 2026-07-24
- **发起人：** user
- **修改文件：**
  - `src/context/__init__.py` — 上下文模块入口
  - `src/context/_budget.py` — TokenManager / BudgetController（令牌预算控制）
  - `src/context/_compressor.py` — Compressor（上下文压缩，三级压缩策略）
  - `src/context/_config.py` — ContextConfig（上下文配置）
  - `src/context/_manager.py` — ContextManager（五阶段上下文编排）
  - `src/context/_models.py` — 上下文数据模型（SelectionDecision / RawContext 等）
  - `src/context/_selector.py` — Selector（上下文选择器）
  - `src/context/context_hooks/_assembler_hook.py` — ContextAssemblerHook（before_llm Transform 组装上下文）
  - `src/memory/__init__.py` — 记忆模块入口
  - `src/memory/_types.py` — 记忆核心类型（StepContext / GateDecision / RecallResult 等 15+ 类型）
  - `src/memory/_persistence.py` — MemoryPersistence 抽象基类
  - `src/memory/_service.py` — MemoryService（记忆服务编排）
  - `src/memory/_backends/_sqlite.py` — SQLitePersistence（记忆持久化 SQLite 实现）
  - `src/memory/_hooks/_commit.py` — MemoryCommitHook（after_step Transform 写入持久化记忆）
  - `src/memory/_management/_compressor.py` — CompressionManager（记忆压缩管理）
  - `src/memory/_management/_conflict.py` — ConflictResolver（记忆冲突解决）
  - `src/memory/_management/_eviction.py` — EvictionManager（记忆淘汰策略）
  - `src/memory/_management/_gate.py` — MemoryCommitGate（记忆提交门控）
  - `src/memory/_stores/_entity.py` — EntityMemoryStore（实体记忆）
  - `src/memory/_stores/_episodic.py` — EpisodicMemoryStore（情景记忆）
  - `src/memory/_stores/_pattern.py` — BehavioralPatternStore（行为模式）
  - `src/memory/_stores/_semantic.py` — SemanticKnowledgeStore（语义知识）
  - `src/memory/_stores/_working.py` — WorkingMemoryStore（工作记忆）
  - `src/runtime/_builder.py` — 重构 memory() 方法，接受 MemoryService 实例注入
  - `src/runtime/_runtime.py` — 集成 ContextManager / ContextAssemblerHook / MemoryCommitHook；_execute_step 支持组装消息
  - `tests/test_context_budget.py` — 上下文预算测试
  - `tests/test_context_compressor.py` — 上下文压缩测试
  - `tests/test_context_manager.py` — 上下文管理测试
  - `tests/test_context_selector.py` — 上下文选择器测试
  - `tests/test_memory_management.py` — 记忆管理测试
  - `tests/test_memory_persistence.py` — 记忆持久化测试
  - `tests/test_memory_service.py` — 记忆服务测试
  - `tests/test_memory_stores.py` — 记忆存储测试
  - `tests/test_builder.py` — 更新 memory 测试用例
  - `.github/skills/commit-rules/` — Git 提交规范技能
  - `.github/skills/debug-principles/` — 调试原则技能
  - `.github/skills/doc-rules/` — 文档规则技能
  - `.github/skills/grill-me/` — Socratic 拷问技能
  - `.github/skills/refactor-rules/` — 重构规则技能
- **修改内容：** 实现 Context 和 Memory 原语。Context 模块提供 Token 预算控制（BudgetController）、三级上下文压缩（Compressor）、智能上下文选择（Selector）和五阶段上下文编排（ContextManager），通过 ContextAssemblerHook 在 before_llm 阶段自动组装上下文。Memory 模块提供 5 种记忆存储（实体/情景/行为模式/语义知识/工作记忆）、SQLite 持久化后端、记忆管理流水线（压缩/冲突解决/淘汰/提交门控），通过 MemoryCommitHook 在 after_step 阶段自动写入持久化记忆。重构 RuntimeBuilder.memory() 为接受 MemoryService 实例注入。新增 5 个独立技能文件。重写了 Runtime._execute_step 以支持 ContextAssemblerHook 组装的 messages。
- **复盘结果：** 全部测试通过，ruff lint 零报错。
- **潜在风险：** 无。向后兼容：旧接口保留，memory_service/context_manager 为可选参数。

#### 5. 实现 MCP + Skill 原语（完整集成与集成测试）

- **时间：** 2026-07-24
- **发起人：** user
- **修改文件：**
  - `src/tools/_mcp/_config.py` — MCPServerConfig（stdio/sse 连接配置）
  - `src/tools/_mcp/_client.py` — MCPClient（JSON-RPC 协议客户端，stdio + SSE）
  - `src/tools/_mcp/_adapter.py` — MCPToolAdapter（MCP tool → ToolSpec 适配器）
  - `src/tools/_mcp/_manager.py` — MCPServerManager（Server 生命周期管理）
  - `src/tools/_mcp/__init__.py` — 导出 MCP 类
  - `src/tools/_skill/_models.py` — SkillConfig、SkillEntry 数据模型
  - `src/tools/_skill/_manager.py` — SkillManager（扫描/关键词匹配/注入 before_llm hook）
  - `src/tools/_skill/__init__.py` — 导出 Skill 类
  - `src/tools/__init__.py` — 导出全部 MCP/Skill 类
  - `src/tools/_dispatcher.py` — 集成 MCP 路由，all_tools() 合并 MCP 工具
  - `src/runtime/_runtime.py` — 新增 mcp/skills 参数，Skill hook 注册
  - `src/runtime/_builder.py` — 新增 .mcp()/.skills() 链式方法
  - `tests/mcp_mock_server.py` — MCP Mock Server（真实子进程，支持 stdio 协议）
  - `tests/test_tools_mcp_integration.py` — 6 个集成测试（真实子进程通信）
  - `tests/test_tools_mcp.py` — MCP 单元测试（含 mock）
  - `tests/test_tools_skill.py` — Skill 单元测试（含真实文件 I/O）
- **修改内容：** 实现 MCP 和 Skill 原语。MCP 支持 stdio/sse 传输、initialize/list_tools/call_tool 完整协议。Skill 支持 SKILL.md 扫描、关键词匹配、auto_inject 无条件注入、before_llm hook 自动注入。集成到 ToolDispatcher（MCP 前缀路由）和 AgentRuntime（mcp/skills 参数 + Builder 链式 API）。编写了 6 个真实集成测试，通过启动 Python 子进程模拟 MCP Server 验证完整的 stdio 协议交互。
- **复盘结果：** 448 测试全部通过（含 6 个真实子进程集成测试），ruff lint 零报错。MCP client 编码问题通过 utf-8-sig + latin-1 兜底策略解决。
- **潜在风险：** 无。向后兼容：mcp/skills 参数可选。

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
