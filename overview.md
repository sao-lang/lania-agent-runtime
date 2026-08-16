### 2026-08-16

#### 8. Loop 策略框架化改造：默认注册移出 Runtime + 工厂/Builder 开放扩展

- **时间：** 2026-08-16 23:10:00
- **发起人：** user
- **修改文件：**
  - `src/runtime/loops/_factory.py` — 注册表支持工厂函数（策略类或 Callable）；内置三策略懒注册（create 兜底、幂等、不覆盖用户同名注册）
  - `src/runtime/_runtime.py` — 删除 `_register_default_strategies()` 调用；新增 `loop_strategy_cls` / `loop_kwargs`，装配顺序 实例 > 类 > 名称
  - `src/runtime/_helper_mixin.py` — 删除 `_register_default_strategies()` 方法与无用 import
  - `src/runtime/_builder.py` — `.loop()` 接受 `str | type[LoopStrategy] | LoopStrategy`，kwargs 透传策略构造；`from_config` 真正应用 `config.loop`
  - `src/runtime/config/_runtime_config.py` — loop 字段文档口径修正（max_steps → max_iterations）
  - `src/runtime/loops/__init__.py` — 模块 docstring 更新为"内置 3 种 + 开放注册"
  - `tests/test_loop_factory.py` — 新增 11 个用例
  - `README.md`、`docs/design/loop-strategy-design.md`、`overview.md`、`grill-self-review.md`
- **修改内容：** 针对"Loop 策略不止三种"的框架化诉求：默认装配从 AgentRuntime 核心移入 loops 子系统（工厂 create 懒注册），Runtime 只依赖 LoopStrategy 抽象与工厂接口；工厂注册放宽为工厂函数；Builder kwargs 真正生效（顺带修复 README F3 `.loop(WorkflowLoop, workflow_definition=wf)` 文档承诺但不可用的问题）；`from_config` 的 loop 配置从"仅存 services"变为真正应用。
- **复盘结果：** 886 测试通过（875 → 886），覆盖率 96.27%（≥96），ruff check/format 零报错（仅预存 test_workflow_intent.py N817）；`_factory.py` 100% 覆盖。
- **潜在风险：** ① `from_config` 的 `config.loop` 此前被静默忽略，现真正生效——含 strategy 但缺必需构造参数（如 workflow 缺 workflow_definition）会在 build 时报错而非忽略；② 保留参数名 hooks/step_runner/controller/router 不可通过 kwargs 覆盖（重复传参会 TypeError）；③ `LoopStrategyFactory.available()` 仅列出已注册名称，内置名称在首次 create 前不列出。

#### 9. 文档：护栏方案落实为 v0.2

- **时间：** 2026-08-16 23:30:00
- **发起人：** user
- **修改文件：**
  - `docs/design/governance-component-design.md` — v0.1 → v0.2 落实版
- **修改内容：** 补齐职责边界与状态分层（R7）、零耦合依赖矩阵与验证清单（§3）、原语链执行语义代码依据（§5.2）、各子组件完整规格（Config 字段/协议/行为/状态/异常/测试，§6）、一次 run() 协作时序（§7）、与接入层网关的分工契约（§8，审计单一出口/审批 resume/限流分工）、配置 YAML 示例（§9）、风险与缓解表（§13）、决策 D1-D4 选项与推荐理由（§14）、文件清单与修订记录。
- **复盘结果：** N/A（纯设计文档，未编码）
- **潜在风险：** 决策 D1-D4 待用户确认后开始实现；工作区存在另一条工作线的未提交改动（LoopStrategy 工厂/Builder 类注册），本次提交未涉及。
#### 8. 文档：护栏（治理）组件封装方案

- **时间：** 2026-08-16 23:10:00
- **发起人：** user
- **修改文件：**
  - `docs/design/governance-component-design.md` — 新增护栏组件封装方案（全治理 + 可插拔）
- **修改内容：** 定义护栏组件域 `src/governance/` 的封装方案：对照 session/memory/context 组件范式，按能力（approval / budget / audit / ratelimit / critique / redact / permission）逐个封装；明确设计原则（Runtime 纯壳、零耦合、协议化后端、优先级契约、状态约束、兼容优先）、公共底座（优先级段位表 / 审计事件 / 异步任务组 / GovernanceConfig）、Builder 接线与配置驱动、兼容迁移策略、实施顺序与验收标准。
- **复盘结果：** N/A（纯设计文档，未实现）
- **潜在风险：** 待确认决策 D1-D4（启动入口 / Critique 重试机制 / 后台任务组位置 / 预算 cost 维度）确认后才能开始实现。
#### 7. 文档：编排高级模式标记为暂缓/按需

- **时间：** 2026-08-16 22:45:00
- **发起人：** user
- **修改文件：**
  - `docs/design/orchestration-components-design.md` — §四 实现优先级状态标注（三循环策略 ✅，Critique / AgentTool / CritiqueInterceptor ⏸️）
  - `docs/design/loop-strategy-design.md` — Multi-Agent 实现状态标注
  - `docs/design/session-component-design.md` — Session Phase 3 标记暂缓
- **修改内容：** 纯文档变更：确认三种循环策略（ReAct / PlanExecute / Workflow）已全部实现、构成编排核心；"编排高级模式"中未实现项（Critique 真实现 / AgentTool / CritiqueInterceptor / PlannerTool / CoT）统一标记为按需暂缓、不进入排期。
- **复盘结果：** N/A（纯文档）。期间发现并修复一次 PowerShell 脚本误伤（编排文档 P→h 全局替换），已从 HEAD 恢复并重做编辑。
- **潜在风险：** 无
#### 6. WorkflowLoop max_iterations 安全网

- **时间：** 2026-08-16 22:20:00
- **发起人：** user
- **修改文件：**
  - `src/runtime/loops/_workflow.py` — `WorkflowLoop.__init__` 新增 `max_iterations`（0 = 不限制），run/run_stream 循环内计数截停
  - `docs/design/loop-strategy-design.md` — 安全网说明
  - `tests/test_coverage_loops.py` — 新增 4 个用例
  - `overview.md`、`grill-self-review.md`
- **修改内容：** 为经 ConditionNode 但分支永不走出口的环提供最终安全网：`max_iterations` 限制单次 run 的最大节点执行次数，超限后停止并记录 warning；默认 0 不限制，向后兼容。
- **复盘结果：** 全量 875 测试通过，覆盖率保持 96%，ruff 零报错。
- **潜在风险：** 截停是静默停止（与 ReAct/PlanExecute 的 max_iterations 行为一致），宿主如需感知需自行判断工作流是否到达终点。
#### 5. Workflow 无条件环检测修复

- **时间：** 2026-08-16 22:10:00
- **发起人：** user
- **修改文件：**
  - `src/runtime/loops/_workflow.py` — 新增 `assert_no_unconditional_cycles()`，run/run_stream 启动时调用；移除失效的 in_path 循环检测
  - `docs/design/loop-strategy-design.md` — 环检测语义说明
  - `tests/test_coverage_loops.py` — 新增 4 个用例（自环/固定环报错、run_stream 错误事件、条件环保留）
  - `overview.md`、`grill-self-review.md`
- **修改内容：** 修复 Workflow 自环（a→a）与固定节点环（a→b→a）会无限循环的问题：原 in_path 检测在顺序遍历中永远不触发，现改为启动前静态检测"无条件环"（仅由 Fixed/Agent 边构成）并抛 WorkflowError；经 ConditionNode 的环保留（分支负责运行时退出），符合"支持循环图结构"的设计语义。
- **复盘结果：** 全量 871 测试通过，覆盖率保持 96%，ruff 零报错。
- **潜在风险：** 经 ConditionNode 且分支永不走出口的环仍会无限循环（无 max_iterations 兜底），属于宿主编排职责，文档已注明。
#### 4. Memory 向量/图检索增强（L4）

- **时间：** 2026-08-16 21:50:00
- **发起人：** user
- **修改文件：**
  - `src/memory/_embedding.py` — 新增 EmbeddingProvider 协议 + HashEmbeddingProvider（纯 Python 特征哈希）
  - `src/memory/_stores/_semantic.py` — search_nodes 向量检索 / ensure_embeddings / search_related
  - `src/memory/_service.py` — embedding_provider 注入 + recall_graph
  - `src/memory/__init__.py` — 导出嵌入类型
  - `docs/design/memory-system-design.md`、`README.md`
  - `tests/test_memory_embedding.py` — 新增 14 个用例
- **修改内容：** 补齐 L4 语义层的向量/图检索能力：`search_nodes` 配置 EmbeddingProvider 后按 embedding 余弦相似度排序（未嵌入节点回退关键词，threshold 仅约束向量路径）；`ensure_embeddings` 批量生成缺失向量；`search_related` / `recall_graph` 做语义命中 + 图扩展检索。
- **复盘结果：** 全量 867 测试通过，覆盖率保持 96%。
- **潜在风险：** HashEmbeddingProvider 是特征哈希近似，生产级语义检索建议替换为模型 embedding；向量路径的 threshold 语义与关键词路径不同（仅约束向量分）。

#### 3. 覆盖率提升至 96% 并修复测试暴露的三个缺陷

- **时间：** 2026-08-16 21:20:00
- **发起人：** user
- **修改文件：**
  - `tests/test_coverage_{loops,llm,memory,context,runtime,memory_management}.py` — 新增 6 个补测文件（约 180 用例）
  - `src/memory/_service.py` — 修复 `_BackgroundTaskGroup.shutdown` 孤儿任务（嵌套任务未被等待）
  - `src/context/__init__.py` — 修复惰性导出映射（ContextManager/BudgetController 指向不存在模块）
  - `src/runtime/_runtime.py` — 修复 run_stream 无法消费 ReAct/Workflow 扩展事件字段
  - `tests/test_memory_persistence.py` — 加固偶发失败的 TTL 测试
- **修改内容：** 覆盖率 86% → 96%（fail_under=96 达标），853 测试通过；补测过程中发现并修复三个真实缺陷。
- **复盘结果：** ruff 零报错（仅预存 N817）。
- **潜在风险：** run_stream 事件字段过滤会丢弃 loop 扩展字段（如 step/node_id），消费方需改用 metadata。

#### 2. Session 组件 Phase 2：断点恢复 + 消息分块 + 分页

- **时间：** 2026-08-16 21:05:00
- **发起人：** user
- **修改文件：**
  - `src/session/_hooks/_resume.py`、`src/memory/_hooks/_resume.py`、`src/memory/_protocols.py` — 新增
  - `src/runtime/context/_context.py`、`src/runtime/_helper_mixin.py` — set_budget / set_pause_state writer
  - `src/session/_store.py` / `_service.py` / `_models.py` / `_config.py` — ssh: 分块与分页
  - `src/runtime/_builder.py` — 并列注册 Resume Hooks
  - `tests/test_session_phase2.py` — 新增 18 个用例
- **修改内容：** SessionResumeHook 恢复历史与游标、MemoryResumeHook 恢复 plan/budget/pause_state；历史消息支持 `ssh:` 分块存储与裁剪；`list_user_sessions` 增加 offset 分页。
- **复盘结果：** 全量 683 测试通过。
- **潜在风险：** chunk_size 默认 100，超阈值记录从内联切换为分块布局（重读自动重组）；`ssh:` 分块为新增 key 前缀，旧数据无需迁移。

#### 1. 文档口径更新（第 5 项）

- **时间：** 2026-08-16 21:55:00
- **发起人：** user
- **修改文件：**
  - `README.md` — 治理组件口径（Hook 已内置、插件封装规划中）、Memory 向量/图检索说明
  - `docs/design/agent-runtime-design.md` — Phase 2/3 实现状态标注
  - `docs/design/session-component-design.md` — Phase 2 勾选
  - `docs/design/memory-system-design.md` — 向量/图检索实现状态
  - `grill-self-review.md` — 第十四轮自省
- **修改内容：** 纯文档变更，对齐实现与文档口径；第 6 项（编排高级模式）按用户要求暂不规划。
- **复盘结果：** N/A（纯文档）
- **潜在风险：** 无
### 2026-08-15

#### 4. Memory 按层 storage 注入（v2.2）

- **时间：** 2026-08-15 15:14:58
- **发起人：** user
- **修改文件：**
  - `src/memory/_service.py` — `MemoryService.__init__` 增加 `working/episodic/entity/semantic/pattern_persistence` 可选参数，未指定层回退默认 `persistence`；`close()` 对去重后的全部后端逐一关闭
  - `docs/design/memory-system-design.md` — §3.1/§3.2 按层注入说明；§4.5 重写为 persistence 级注入示例；附录补充约定
  - `README.md` — Memory 段落补充按层注入示例
  - `tests/test_memory_storage_injection.py` — 新增 7 个用例（路由/回退/共享/close 去重/默认后端创建）
- **修改内容：** 让 5 层记忆可各自绑定独立的 `MemoryPersistence` 后端（SQLite/Redis/PG/Neo4j 等），层与层之间 storage 彻底解耦；未注入的层自动回退到默认后端，向后兼容 `MemoryService(persistence=...)`。
- **复盘结果：** 665 个测试全部通过；新增用例覆盖按层路由、回退、close 去重；ruff 检查通过（仅 `test_workflow_intent.py` 预存 N817 一条）。
- **潜在风险：** `close()` 现在会关闭所有去重后的后端——共享同一实例只关一次；若某个自定义后端没有 `close()` 方法会静默跳过。真正的向量/图检索仍取决于各层后端与 Store 语义查询能力，本次只完成 storage 注入层。

#### 3. v2.1 修订：system prompt 归属运行时配置 + 执行器消息传递修复

- **时间：** 2026-08-15 15:20:00
- **发起人：** user
- **修改文件：**
  - `src/runtime/_steps/_step_runner.py` — 序列化/组装后重建 ctx 再调执行器（run_step + run_llm_only）；dirty 路径“首条是 system 才替换，否则前置新 system”
  - `src/session/_service.py` — `append_messages()` 过滤 system 消息；旧记录首条 system 自动剥离自愈
  - `src/session/_models.py` / `_hooks/_commit.py` — 文档口径“对话消息历史（不含 system）”
  - `docs/design/session-component-design.md` — 新增 §16“system prompt 归属与执行器消息传递（v2.1 修订）”
  - `README.md` — Session 段落口径同步
  - `tests/` — e2e 断言更新；新增换提示词续聊生效、执行器入参、旧记录自愈用例
- **修改内容：** 修复“同一 session_id 续聊更换 system_prompt 不生效”与“执行器收到步前快照导致 system/最新消息丢失”两个问题：执行器经重建 ctx 收到序列化/组装后的完整消息；system prompt 唯一归属运行时配置，Session 历史只存 user/assistant/tool，恢复后由 ContextAssemblerHook 用运行时提示词组装。
- **复盘结果：** 全量测试通过；dirty 路径语义保持（system 来自 payload、历史来自 controller.messages）；旧记录无需迁移、首次提交自愈。
- **潜在风险：** 执行器入参变化属契约修正，第三方自定义执行器若依赖步前快照需适配；升级后首次续聊旧会话仍可能沿用旧 system 一次。

#### 2. 实现 Session 组件 v2（唯一事实源 + 零耦合）+ Memory/Context 改造

- **时间：** 2026-08-15 14:38:41
- **发起人：** user
- **修改文件：**
  - `src/session/` — 新增 Session 组件（models / persistence / store / service / config / protocols / hooks）
  - `src/runtime/_runtime.py` — `session_id` 注入；SESSION_START/END 先 Transform 后 Observer；session_end 事件带 last_error；run_stream 补 session_end
  - `src/runtime/_helper_mixin.py` — `set_messages` / `set_step_index` writer 与实现；resume/destroy 先 Transform 后 Observer
  - `src/runtime/context/_context.py` — RuntimeContext 新增 `set_messages` / `set_step_index`
  - `src/runtime/_builder.py` — 新增 `.session()` / `.session_id()` 并注册 Session hooks
  - `src/runtime/loops/_react.py` / `_plan_execute.py` / `_workflow.py` / `_helper_mixin.py` — AFTER_STEP 前重建 ctx（修复看不到本轮 assistant 回复的问题）
  - `src/context/context_hooks/_assembler_hook.py` — 组装路径兜底 Runtime `system_prompt`（修复 system 提示词丢失）
  - `src/memory/_types.py` / `_hooks/_commit.py` / `_service.py` — 停止写原文；字段标记 `@deprecated v2`；token_count 改按 summary
  - `docs/design/`（memory-system-design / context-management-redesign / agent-runtime-design / session-component-design）、`README.md` — 统一"原文唯一归 Session"口径与 SESSION 挂载点顺序
  - `pyproject.toml` — wheel packages 增加 `src/session`
  - `tests/` — 新增 test_session_store/service/hooks/e2e；更新 test_builder / test_memory_service / test_context_manager
- **修改内容：** 按 session-component-design.md v2 实现 Phase 1：Session 组件（会话生命周期、TTL、逐轮提交完整历史、user 索引）、Runtime 侧 session_id 注入与 `set_messages`/`set_step_index` writer、SESSION 挂载点先 Transform 后 Observer、Builder `.session()`/`.session_id()` 接线；Memory 停止写入消息原文（`raw_content=None`、hook 不再拼 raw），Context 保持纯编排；顺带修复 AFTER_STEP 快照陈旧与 system_prompt 丢失两个既有问题。
- **复盘结果：** 653 个测试全部通过；新增 Session 代码覆盖率 91%–100%；全量覆盖率 85.74%（基线 HEAD 为 84.27%——96% 门槛在改动前已不达标，主要缺口在 PlanExecuteLoop/WorkflowLoop/OpenAI Provider/Memory stores 等既有模块）；ruff 检查通过（仅 `test_workflow_intent.py` 预存 N817 一条）。
- **潜在风险：** 会话历史现在包含 system 消息（StepRunner 序列化后写回 controller.messages）；恢复历史后组装出的 system 内容沿用历史首条，仅当内容为空时以运行时 `system_prompt` 兜底——同一 session_id 更换 system_prompt 时需清空历史或显式覆盖（已知限制，见 grill-self-review.md）。`WorkingMemorySnapshot.messages` / `EpisodicMemoryEntry.raw_content` 保留字段但不再写入，读取旧数据不受影响。

#### 1. Session 组件设计文档 v2：唯一事实源 + 零耦合边界

- **时间：** 2026-08-15 04:38:19
- **发起人：** user
- **修改文件：**
  - `docs/design/session-component-design.md` — 重写为 v2（删除 v1，替换为"唯一事实源 + 零耦合"方案）
- **修改内容：** 根据"Session / Memory / Context 三组件是否有功能重叠"的讨论结论更新设计文档：(1) 明确 Session 是完整原始消息历史的唯一事实源，Memory L1/L2 不再存储消息原文（`WorkingMemorySnapshot.messages`、`EpisodicMemoryEntry.raw_content` 标记 `@deprecated v2`），Context 保持纯编排不持有数据；(2) 新增零耦合约束：组件间运行期零导入（`src/session` 不 import `src/memory`/`src/context`，对 `src.runtime` 仅 TYPE_CHECKING），唯一接线点在 `RuntimeBuilder`，共享 persistence 实例按 key 前缀隔离、不构成耦合；(3) 修正 v1 审查问题：`ctx.services` 浅拷贝不可写（改为 SessionService 内存缓存）、session_id 无注入入口（AgentRuntime + Builder 增加 `session_id`）、续聊 turn_index 重置（持久化并恢复 `step_index`，新增 `set_step_index` writer）、TTL 不生效（SessionService 内置过期）、新增 SessionCommitHook 逐轮提交原文以支撑崩溃恢复。
- **复盘结果：** 纯文档变更，无代码改动；方案已按项目惯例（协议解耦、Hook 插拔、Runtime 纯壳）对齐。
- **潜在风险：** 设计仍处 Phase 1 规划阶段，尚未实现；Memory 侧字段废弃为破坏性变更，实现时需同步更新 memory-system-design.md 与相关测试。

### 2026-07-27

#### 2. Code Review 驱动修复：闭包变量风险 + lint 清理

- **时间：** 2026-07-27
- **发起人：** user (code-review)
- **修改文件：**
  - `src/runtime/loops/_workflow.py` — `add_intent_route()` 闭包变量 → `WorkflowDefinition._intent_results` dict；新增 `reset_intent_results()`；`WorkflowLoop.run()`/`run_stream()` 入口自动重置
  - `src/runtime/_builder.py` — 删除多余的 `Union` import
  - `tests/test_workflow_intent.py` — `-> any` → `-> Any`；ruff 清理 9 个未使用的 import
- **修改内容：** Code Review 发现 3 个问题并修复：(1) `add_intent_route()` 的闭包变量 `_intent_result` 在同一个 `WorkflowDefinition` 实例被多次 `run()` 时不会重置，改为存储在 `self._intent_results` dict 中，`WorkflowLoop.run()`/`run_stream()` 入口处自动调用 `reset_intent_results()` 清除旧状态。(2) 删除 `_builder.py` 中未使用的 `Union` import。(3) `test_workflow_intent.py` 修复 `any` → `Any`。
- **复盘结果：** 132 项相关测试通过，ruff 零报错（仅 1 个预存 N817 风格问题）。
- **潜在风险：** 无

#### 1. 实现 WorkflowLoop 意图路由方案

- **时间：** 2026-07-27
- **发起人：** user
- **修改文件：**
  - `src/intent/__init__.py` — 新增，导出三种分类器
  - `src/intent/_protocols.py` — 新增，`IntentClassifier` Protocol 定义
  - `src/intent/_classifiers.py` — 新增，`RuleClassifier` / `LLMClassifier` / `HybridClassifier` 实现
  - `src/runtime/loops/_workflow.py` — 新增 `WorkflowDefinition.add_intent_route()` 方法；扩展 `to_dict()`/`from_dict()` 支持意图路由元信息
  - `src/runtime/loops/__init__.py` — 导出 `IntentClassifier`、`RuleClassifier`、`LLMClassifier`、`HybridClassifier`
  - `tests/test_workflow_intent.py` — 新增，23 个测试用例（单元 + E2E + 序列化）
- **修改内容：** 根据 `intent-routing-design.md` 实现意图路由功能。(1) `add_intent_route()` 作为 `WorkflowDefinition` 的声明式语法糖，内部展开为 `FixedNode`（分类）+ `ConditionNode`（路由）组合，零侵入 WorkflowLoop 执行引擎。(2) 三种内置分类器：RuleClassifier（关键词匹配）、LLMClassifier（LLM 分类）、HybridClassifier（规则兜底 + LLM 补充）。(3) 使用闭包变量（而非 `ctx.services`）在分类/路由节点间共享结果，避免 `build_context()` 重建导致的状态丢失。(4) 序列化支持：`to_dict()`/`from_dict()` 包含意图路由元信息。
- **复盘结果：** 597 测试通过（23 个新增），ruff 零报错。
- **潜在风险：** 无

### 2026-07-26

#### 2. Simplify skill 驱动代码简化

- **时间：** 2026-07-26
- **发起人：** user
- **修改文件：**
  - `src/runtime/_runtime.py` — 删除 `_default_loop()`（~37行）、`run()`/`run_stream()`不可达兜底分支（~60行）；提升 `import RuntimeController` 到模块级；`logger.info` → `logger.debug`
  - `src/runtime/loops/_workflow.py` — 删除 `ConditionNode.execute` 中冗余的局部 `import inspect`
  - `tests/test_coverage_edge.py` — 同步删除 `test_default_loop_extract_assistant_response`
  - `src/memory/_pipeline/` — 删除空目录
- **修改内容：** 由 `simplify` skill 驱动的 7 维度代码简化。净减 ~115 行，消除 1 个空目录。
- **复盘结果：** 575 测试通过，ruff 零报错。
- **潜在风险：** 无（仅删除不可达死代码和局部重复导入）

- **时间：** 2026-07-25 10:00
- **发起人：** user
- **修改文件：**
  - `.github/skills/code-review/SKILL.md` — 新建 code-review skill
  - `.github/skills/simplify/SKILL.md` — 新建 simplify skill
  - `.github/copilot-instructions.md` — 注册两个新 skill 的加载要求
- **修改内容：** 新增 code-review（系统化代码审查，7 维度：正确性/安全/性能/可读性/可维护性/项目约定/文档测试）和 simplify（代码简化，7 维度：死代码删除/重复消除/扁平化/逻辑简化/数据结构简化/流程简化/API 简化）两个 skill，并更新 copilot-instructions.md 注册其加载条件。
- **复盘结果：** N/A（纯新增 skill 文件，不涉及代码修改）
- **潜在风险：** 无

#### 2. 优化 code-review 和 simplify skill

- **时间：** 2026-07-25 10:30
- **发起人：** user
- **修改文件：**
  - `.github/skills/code-review/SKILL.md` — 添加反模式速查表 + 语言专项审查重点（Python/TS/异步）
  - `.github/skills/simplify/SKILL.md` — 优化速查表（去除冗余，补充 walrus/context manager/match-case/dataclass 模式）
  - `.github/copilot-instructions.md` — 修复调试任务过时引用（"见下文第 3 条"→ 精确路径）
- **修改内容：** code-review 新增 15 种常见代码反模式速查表 + Python/TypeScript/异步并发三组语言专项审查重点；simplify 优化速查表替换冗余项、补充 walrus 运算符/上下文管理器/match-case/dataclass 化简等 Python 常用简化模式；修复 copilot-instructions.md 中 debug-tools 引用指向已不存在的"第 3 条"。
- **复盘结果：** 无代码修改，无回归风险
- **潜在风险：** 无

### 2026-07-24

#### 10. 第十轮自省：修复 except 块缺失 exc_info

- **时间：** 2026-07-24 19:00
- **发起人：** user
- **修改文件：**
  - `src/memory/_service.py` — `_safe_background_task` 加 `exc_info=True`
  - `src/memory/_hooks/_commit.py` — 写入失败日志加 `exc_info=True`
  - `src/tools/_dispatcher.py` — tool 失败日志加 `exc_info=True`
  - `src/tools/_mcp/_client.py` — 子进程关闭异常日志加 `exc_info=True`
  - `src/tools/_mcp/_manager.py` — MCP 连接失败日志加 `exc_info=True`
  - `src/tools/_skill/_manager.py` — skill.toml 加载失败日志加 `exc_info=True`
- **修改内容：** 6 处 `except` 块补全 `exc_info=True`，确保异常堆栈不被丢失。
- **复盘结果：** 575 测试通过，ruff 零报错。

#### 9. 第九轮自省：修复 __import__ hack

- **时间：** 2026-07-24 18:30
- **发起人：** user
- **修改文件：**
  - `src/runtime/loops/_plan_execute.py` — 导入 `FinishReason` 替代 `__import__` hack（2 处）
  - `src/runtime/loops/_workflow.py` — 同上
  - `src/tools/_mcp/_client.py` — 导入 `os` 替代 `__import__("os")` hack
- **修改内容：** 消除最后 3 处 `__import__` hack，替换为直接 import。`type: ignore` 从 10 降至 7 处。
- **复盘结果：** 575 测试通过，ruff 零报错。

#### 8. 第八轮自省：深度修复 plan 路由 + 输入校验 + 防御加固

- **时间：** 2026-07-24 18:00
- **发起人：** user
- **修改文件：**
  - `src/runtime/_runtime.py` — after_llm 前重建 ctx；plan 自定义 step_id 映射 llm；`_default_loop` 加 `_cancelled` 检查
  - `src/runtime/loops/_react.py` — run_stream 步后 hook 前重建 ctx
  - `src/runtime/loops/_plan_execute.py` — run_stream 加 `injected_context.clear()`；`_parse_plan` 合并解析逻辑
  - `src/runtime/loops/_workflow.py` — run/run_stream 加循环依赖检测（`in_path`）
  - `src/tools/_dispatcher.py` — `json.loads` 加 65536 字符上限
  - `src/tools/_spec.py` — `__post_init__` 加 name 格式校验（`^[a-zA-Z0-9_-]+$`）
  - `src/tools/_registry.py` — `execute()` 加 required 参数 + 多余参数检测
  - `src/context/_manager.py` — recall_raw query 截断至 2048 字符
  - `src/memory/_hooks/_commit.py` — raw 字段截断至 16384 字符
  - `src/runtime/_builder.py` — `from_config` 注释说明 hooks/plugins 需手动注册
- **修改内容：** 全面防御加固 + 功能修复。
- **复盘结果：** 575 测试通过，ruff 零报错。`__import__` hack 3 处待修复。

#### 7. 全组件解耦：Runtime 纯壳化 + 协议化 + Context/Memory API 分离

- **时间：** 2026-07-24
- **发起人：** user
- **修改文件：**
  - `src/context/_protocols.py` — 新增：MemoryRecallProtocol / MemoryCommitProtocol（模块间解耦接口）
  - `src/context/_manager.py` — ContextManager 依赖 MemoryRecallProtocol 而非具体 MemoryService
  - `src/context/__init__.py` — 导出新增协议
  - `src/memory/_hooks/_commit.py` — MemoryCommitHook 依赖 MemoryCommitProtocol 而非具体 MemoryService
  - `src/runtime/_runtime.py` — 瘦身 __init__，移除 memory_service / tools / mcp / skills / context_config 参数
  - `src/runtime/_builder.py` — 承载所有接线逻辑（ToolDispatcher 创建、Hook 注册等）；分离 .memory() / .context() API
  - `docs/design/agent-runtime-design.md` — 新增 §"模块间解耦协议"章节；更新 Builder 示例
  - `docs/design/context-management-redesign.md` — 更新 ContextManager 签名使用 MemoryRecallProtocol
  - `docs/design/memory-system-design.md` — 新增 §7.1 协议解耦说明；更新 Builder 示例
  - `docs/design/tool-mcp-skill-design.md` — 重写 §7 Runtime 集成，移除 AgentRuntime 参数
  - `docs/design/llm-executor-design.md` — 更新 §6.6 内置 Transform 说明
  - `README.md` — 更新手动接线示例；分离 memory/context API
- **修改内容：** 全组件解耦改造。(1) 协议化：在 `src.context` 包中定义 `MemoryRecallProtocol` 和 `MemoryCommitProtocol`，`ContextManager` / `MemoryCommitHook` 依赖协议而非具体类，`src.context` 与 `src.memory` 双向零导入。(2) Runtime 纯壳化：`AgentRuntime.__init__` 删除 `memory_service` / `tools` / `mcp` / `skills` / `context_config` 参数，所有接线逻辑移到 `RuntimeBuilder.build()`。(3) API 分离：`.memory(service)` 只管记忆数据层，`.context(config)` 只管上下文编排层，各司其职。
- **复盘结果：** 全部测试通过，ruff lint 零报错。
- **潜在风险：** 无。向后兼容：Builder 快捷方式保持不变，手动接线用户需参照新文档调整 `AgentRuntime` 构造参数。

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
- **修改内容：** 实现 MCP 和 Skill 原语。MCP 支持 stdio/sse 传输、initialize/list_tools/call_tool 完整协议。Skill 支持 SKILL.md 扫描、关键词匹配、auto_inject 无条件注入、before_llm hook 自动注入。集成到 ToolDispatcher（MCP 前缀路由）和 AgentRuntime（mcp/skills 参数 + Builder 链式 API，注：mcp/skills 参数在后续 #7 重构中已移除，现由 Builder 接管）。编写了 6 个真实集成测试。
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
- **修改内容：** 按照设计文档 tool-mcp-skill-design.md 实现 Tool 原语。ToolSpec 定义工具数据结构，ToolRegistry 管理注册/描述/执行（覆盖注册策略），ToolDispatcher 统一调度（当前仅 Tool 路由，MCP 前缀路由为占位）。通过 tools 参数集成到 AgentRuntime（注：该参数在后续 #7 重构中已移除，现由 Builder 接管）。RuntimeBuilder 新增 tool_registry() 方法。MCP 和 Skill 原语预留目录结构，待后续迭代实现。
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

