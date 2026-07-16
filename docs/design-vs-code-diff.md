# 设计文档 vs 代码实现差异清单

> 以三份设计文档为唯一标准，标记所有与设计文档不符的代码差异。
> 来源文档：`agent-runtime-design.md` / `llm-executor-design.md` / `memory-system-design.md`

---

## 一、Memory 系统

| # | 设计文档要求 | 代码现状 | 来源 | 优先级 |
|---|------------|---------|------|--------|
| M1 | `MemoryService(working_store, episodic_store, entity_store, semantic_store, pattern_store)` — 5个独立 Store | ✅ `MemoryService(working_store, episodic_store, entity_store, semantic_store, pattern_store)` — 5独立Store, 兼向后兼容 `store=` | memory-system-design.md §3.1 + §4.5 | 🔴 → ✅ |
| M2 | 文件结构：`interfaces/` `stores/` `pipeline/` `hooks/` `management/` 子目录 | ✅ `interfaces/` `stores/` `pipeline/` `hooks/` `service.py` 已分离 | memory-system-design.md 附录 | 🔴 → ✅ |
| M3 | Memory 应通过 Hook 集成：`runtime.on_before_step(MemoryRecallHook(...))` | ✅ `__init__` 中自动注册 `MemoryRecallHook` + `MemoryCommitHook` 到 BEFORE_STEP/AFTER_STEP; `SessionCleanupHook` 在 `destroy()` 时触发 | memory-system-design.md §7.2 | 🔴 → ✅ |
| M4 | `WorkingMemoryStore` 推荐文件系统实现 `WorkingMemoryFileStore`，每个 session 一个 JSON 文件 | ✅ `WorkingMemoryFileStore` 已实现, 同时保留 `WorkingMemorySQLiteStore` 向后兼容 | memory-system-design.md §4.4 | 🟡 → ✅ |
| M5 | `WorkingMemorySnapshot` 需包含 `context_payload`, `budget`, `pause_state`, `error_state`, `plan`, `hook_states` | ✅ 已扩展: `ContextPayloadSnapshot`, `BudgetSnapshot`, `PauseStateSnapshot`, `ErrorStateSnapshot`, `PlanStep`, `hook_states` | memory-system-design.md §2.1 | 🟡 → ✅ |
| M6 | 应有 `pipeline/commit.py` `pipeline/recall.py` `pipeline/token_manager.py` 独立管线 | ✅ `pipeline/commit.py` `pipeline/recall.py` `pipeline/token_manager.py` 均存在 | memory-system-design.md §5 | 🟡 → ✅ |
| M7 | 应有 `hooks/recall_hook.py` `hooks/commit_hook.py` `hooks/cleanup_hook.py` | ✅ `hooks/recall_hook.py` `hooks/commit_hook.py` `hooks/cleanup_hook.py` 均存在 | memory-system-design.md §7.2 附录 | 🟡 → ✅ |

## 二、LLMExecutor

| # | 设计文档要求 | 代码现状 | 来源 | 优先级 |
|---|------------|---------|------|--------|
| L1 | `LLMExecutorConfig` 应有 `api_key` `api_base` `stream` 字段 | ✅ `api_key`, `api_base`, `stream` 已添加; `stream` 控制默认流式行为 | llm-executor-design.md §2.3 | 🔴 → ✅ |
| L2 | `LLMExecutor.__init__(config, provider)` — 内部构造 `AsyncOpenAI` 客户端 | ✅ `LLMExecutor(config=, *, client=, provider=)` — config 为首参, 无 client/provider 时内部构造; 向后兼容 client= | llm-executor-design.md §4.1 | 🟡 → ✅ |
| L3 | 应有 `LLMProvider` 抽象接口 + `LLMProviderResponse` 用于隔离 SDK | ✅ `LLMProvider(ABC)` + `LLMProviderResponse` + `OpenAIProvider` 已在 provider.py 实现 | llm-executor-design.md §3.3 | 🟡 → ✅ |
| L4 | `execute_stream()` 应统一返回 `(AsyncStreamCollector, LLMResponse)` | ✅ `execute_stream()` 统一返回 `(AsyncStreamCollector, LLMResponse)`; `execute_stream_collected` 保留为别名 | llm-executor-design.md §2.2 | 🟢 → ✅ |

## 三、Runtime / Hook

| # | 设计文档要求 | 代码现状 | 来源 | 优先级 |
|---|------------|---------|------|--------|
| R1 | `HookRegistry` 应有语义化注册方法 `on_session_start()` `on_before_step()` 等 | ✅ `observe()` / `transform()` / `intercept()` 语义化方法已实现; 无需 `on_` 前缀 | agent-runtime-design.md §六 | 🟡 → ✅ |
| R2 | 缺少 `resume()` — Runtime 需支持 step 级别的暂停/恢复协议 | ✅ `resume()` + `resume_stream()` 已添加, 清空 pause_state 后继续 step loop | agent-runtime-design.md §九-3 | 🔴 → ✅ |
| R3 | `RuntimeContext` 缺少 `llm_config` 字段 | ✅ `llm_config` property + `set_llm_config()` 已添加; `_merge_params()` 优先读取 | llm-executor-design.md §5.2 | 🟢 → ✅ |
| R4 | `before_llm` 顺序: Transform(上下文组装/RAG/裁剪) → Intercept(安全扫描) | ✅ `_step_loop` / `_step_loop_stream` 中修正为 `Transform → Intercept`; 先组装再安检 | agent-runtime-design.md §七 | 🔴 → ✅ |
| R5 | `after_tool` 顺序: Transform(Budget) → Intercept(Groundedness) | ✅ 修正为 `Transform → Intercept`; Budget 先扣减再事实检查 | agent-runtime-design.md §七 | 🔴 → ✅ |
| R6 | `on_error` 应为 Intercept(可决策 retry/skip/degrade) + Router, 而非 Observer | ✅ `ON_ERROR` 注册点支持 Intercept + Observer; Error Intercept 决策后 Router 决定下一步 | agent-runtime-design.md §八-#15 | 🔴 → ✅ |
| R7 | Router 应在 before_step 后/LLM 前调用以决定步骤类型 | ✅ `_step_loop` / `_step_loop_stream` 在 before_step Transform 后加入 Router 调用 | agent-runtime-design.md §七 | 🟡 → ✅ |
| R8 | `session_end` 顺序: Observer → Transform | ✅ `destroy()` 中修正为先 Observer 后 Transform | agent-runtime-design.md §七 | 🟢 → ✅ |
| R9 | `serialize()` 应由 Runtime 在 LLM Execute 前显式调用, 非 Executor 内部隐式执行 | ✅ `_step_loop` / `_step_loop_stream` 中 LLM 前调用 `ctx.serialize_for_llm()`; executor 读取预序列化结果 | agent-runtime-design.md §5.3 | 🟡 → ✅ |
| R10 | `budget.step_count` 应在 after_step 中 `increment_step()` 递增, 而非 `deduct_budget()` | ✅ `deduct_budget` 移除 `step_count += 1`; `increment_step()` 同时递增 `_step_index` 和 `_budget.step_count` | agent-runtime-design.md §七 | 🟢 → ✅ |

## 四、包导出

| # | 设计文档要求 | 代码现状 | 优先级 |
|---|------------|---------|--------|
| E1 | `__init__.py` 应导出 `AgentRuntime`, `HookRegistry`, `RuntimeContext`, memory 全套 | ✅ 已导出: `AgentRuntime`, `RuntimeContext`, `HookRegistry`, `MemoryService` + 全部 LLM 类 | 🟡 → ✅ |

---

## 优先级说明

- **🔴 高**：架构性偏差，必须修复
- **🟡 中**：功能或 API 易用性偏差，建议修复
- **🟢 低**：接口规范统一，可选修复
