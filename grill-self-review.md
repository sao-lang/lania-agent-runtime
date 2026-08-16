## 第十六轮自省（2026-08-16）：WorkflowLoop max_iterations 安全网

### 触发条件
✅ 第十五轮记录的已知边界（条件环无退出兜底）落地为功能

### 四大维度自省

**✅ 功能完整性**
- `WorkflowLoop(max_iterations=N)`：run/run_stream 循环内计数，达到上限后停止并 `logger.warning`；N=0（默认）不限制，向后兼容。

**✅ 功能间联通**
- 与 ReAct/PlanExecute 的 max_iterations 语义一致（静默截停）；自环静态检测仍先行生效，两者职责互补。

**✅ 模块间联通**
- 仅新增构造参数与循环计数，无新增跨模块依赖。

**✅ 可用性**
- 875 测试通过、覆盖率 96%、ruff 零报错。

### 最终状态
✅ 条件环即使永不退出也不会无限循环；默认行为不变。

---
## 第十五轮自省（2026-08-16）：Workflow 无条件环检测修复

### 触发条件
✅ 补测暴露的缺陷修复（a→a 自环会死循环）

### 四大维度自省

**✅ 功能完整性**
- 原 `in_path` 循环检测在顺序遍历中不可达（节点执行后立即 discard，迭代起点 in_path 恒为空），自环/固定环会无限循环；
- 改为启动前静态检测：`assert_no_unconditional_cycles()` 对缩减图（Fixed/Agent 第一条出边）做 DFS 环判定，run() 抛 WorkflowError，run_stream() 产出 error 事件后返回。

**✅ 功能间联通**
- 经 ConditionNode 的环（如 a→route→a）保留——分支可在运行时退出，验证 a 执行两次后走 exit 正常结束；
- 依赖检查语义不变（visited 前置校验），原 test_workflow_dependency_check 继续通过。

**✅ 模块间联通**
- 检测逻辑归属 WorkflowDefinition（纯数据类，可序列化），WorkflowLoop 仅调用；无新增跨模块依赖。

**✅ 可用性**
- 871 测试通过、覆盖率 96%、ruff 零报错。

### 发现的问题与处置
| # | 问题 | 严重度 | 处置 |
|---|------|--------|------|
| G5 | in_path 循环检测永不触发，a→a 自环死循环 | 严重 | 静态无条件环检测 + 移除 in_path 死代码 |
| G6 | 经 ConditionNode 且永不走出口的环无运行时兜底 | 轻微 | 记录为宿主编排职责（文档注明） |

### 最终状态
✅ 自环/固定环启动即报错；条件环保留；全量验证通过。

---
## 第十四轮自省（2026-08-16）：Session Phase 2 + 覆盖率 96% + Memory 检索增强

### 触发条件
✅ 改 ≥3 文件 / 架构决策 / 基础设施变更（RuntimeContext writer、存储布局、语义检索）

### 四大维度自省

**✅ 功能完整性**
- Session Phase 2 三项（Resume Hooks / ssh: 分块 / 分页过滤）全部实现并勾选设计文档；
- Memory L4 向量检索（EmbeddingProvider + 余弦排序 + 关键词回退）与图扩展检索（search_related / recall_graph）落地。

**✅ 功能间联通**
- 覆盖率 86% → 96%（fail_under=96 达标），全量 867 测试通过；
- 补测暴露并修复 3 个真实缺陷：后台任务孤儿（close 后仍写库）、context 惰性导出映射错误、run_stream 事件字段不兼容。

**✅ 模块间联通**
- 零耦合约束保持：session/memory/context 无新增运行期互相导入；MemoryResumeHook 仅依赖 MemoryResumeProtocol。

**✅ 可用性**
- ruff 零报错（仅预存 N817）；TTL 偶发失败测试已加固。

### 发现的问题与处置
| # | 问题 | 严重度 | 处置 |
|---|------|--------|------|
| G1 | `_BackgroundTaskGroup.shutdown` 等待期间新生成的任务被 clear() 孤儿化 | 严重 | 改为循环排空（含超时取消） |
| G2 | `src.context.__getattr__` 惰性映射指向 `_contextmanager` 等不存在模块 | 中等 | 改为显式模块映射表 |
| G3 | `runtime.run_stream` 对 ReAct/Workflow 扩展事件字段抛 TypeError | 严重 | 边界过滤字段后构造 StreamEvent |
| G4 | TTL 未过期测试在全量负载下偶发失败（1s TTL） | 轻微 | 未过期用例改用 10s TTL fixture |

### 最终状态
✅ 867 测试通过、覆盖率 96%、ruff 零报错（预存 N817 除外）；Session Phase 2 / Memory 向量图检索 / 文档口径全部落地。

---
# 自省回顾：Grill-Me 驱动的全面修复

> 2026-07-24，通过 10 轮自我拷问驱动，对 lania-agent-runtime 完成全量代码审查和修复。累计修复 **97 项**，575 测试全绿，ruff 零报错，`__import__` hack 清零。

---

## 第十一轮自省（2026-08-15）：Session 组件 v2 Phase 1 实现

### 触发条件
✅ 改 ≥3 文件 / 架构决策 / 基础设施变更（RuntimeContext 新增 writer、SESSION 挂载点顺序变更）

### 四大维度自省

**✅ 功能完整性**
- 对照 session-component-design.md §15 Phase 1 checklist 逐项核对：`src/session/` 全部模块、Runtime 变更、Builder 接线、Memory 字段废弃均完成；Phase 2/3 项（SessionResumeHook/MemoryResumeHook、ssh 分块、跨会话检索）明确留待后续。

**✅ 功能间联通**
- E2E 测试验证 `session_start 恢复 → after_step 提交 → session_end 归档 → 续聊恢复` 全链路；Memory 摘要与 Session 原文各自落位（`raw_content=None` 断言通过）。
- 自省发现并修复：AFTER_STEP 的 ctx 是步骤执行前快照（Session/Memory 看不到本轮 assistant 回复）——在 ReAct/PlanExecute/Workflow/`run_step()` 统一步后重建 ctx；ContextAssemblerHook 组装路径丢失 Runtime `system_prompt`——补空内容兜底。

**✅ 模块间联通**
- 零耦合验证清单通过：`src/session` 无 `import src.memory/src.context`（含 TYPE_CHECKING）；memory/context 无 `import src.session`；session 对 runtime 仅 TYPE_CHECKING；唯一接线点在 Builder。
- 653 个既有+新增测试全部通过，无回归。

**✅ 可用性**
- E2E + 冒烟验证通过；ruff format/check 通过（仅 `test_workflow_intent.py` 预存 N817 一条）。

### 发现的问题与处置
| # | 问题 | 严重度 | 处置 |
|---|------|--------|------|
| S1 | AFTER_STEP 快照陈旧，本轮 assistant 回复不可见 | 严重 | 已修复（三种 Loop + run_step 步后重建 ctx） |
| S2 | memory+context 启用时 system_prompt 在组装路径丢失 | 严重 | 已修复（ContextAssemblerHook 空内容兜底） |
| M1 | 同一 session_id 更换 system_prompt 时，恢复历史沿用旧 system 消息 | 中等 | **已修复（v2.1）**：StepRunner 重建 ctx 传执行器 + Session 存储过滤 system，见第十二轮 |
| M2 | 全量覆盖率 85.74%（门槛 96%） | 中等 | 基线 HEAD 为 84.27%——门槛在本次改动前已不达标（grill-self-review.md M16 已记录"coverage 83%→96% 需 3-5 小时"），主要缺口在 PlanExecuteLoop/WorkflowLoop/OpenAI Provider/Memory stores 等既有模块 |

### 最终状态
✅ 653 测试通过，Session 新增代码覆盖率 91%–100%，ruff 检查通过，设计文档与实现口径统一。

---

## 第十二轮自省（2026-08-15）：system prompt 归属与执行器消息传递修复

### 触发条件
✅ 架构决策 / 基础设施变更（执行器调用路径、Session 存储策略）

### 四大维度自省

**✅ 功能完整性**
- L1：`run_step()` / `run_llm_only()` 序列化/组装后重建 ctx 再调执行器；dirty 路径按“首条是否 system”分支，恢复的纯对话历史不丢首条 user。
- L2：`append_messages()` 过滤 system；旧记录首条 system 剥离自愈；`ContextAssemblerHook` 兜底让换提示词续聊立即生效。

**✅ 功能间联通**
- 诊断验证：修复前无 memory 场景执行器只收到 `[user]`；修复后应收到 `[system, user, ...]`。
- 新增长验证用例：换提示词续聊、执行器入参、旧记录自愈。

**✅ 模块间联通**
- 内置 after_llm 治理 hook（Critique/Approval/Replan）不读 `ctx.messages`，仅读 services/budget/step_index——不受 fresh_ctx 影响（已核对源码）。
- dirty 路径语义保持：system 来自 payload、历史来自 controller.messages，与旧逻辑一致。

**✅ 可用性**
- 全量测试 + ruff 通过；无 schema/API 变更，旧记录无需迁移。

### 已知边界
- 升级后**第一次**续聊旧会话仍可能沿用历史中的旧 system（该次提交后自愈）。
- 第三方自定义执行器若依赖“收到步前快照”需适配（属契约修正，与 `LLMExecutor` 接口文档对齐）。

---

## 第十三轮自省（2026-08-15）：Memory 按层 storage 注入

### 触发条件
✅ 基础设施变更 / 架构决策（MemoryService 构造与 close 语义）

### 四大维度自省

**✅ 功能完整性**
- 5 层各自可注入 `{layer}_persistence`，未指定回退默认 `persistence`；`close()` 对去重后的全部后端逐一关闭。

**✅ 功能间联通**
- Store 适配器无需改动（本就按层独立），`recall_raw`/`commit`/`checkpoint` 自动走各层后端；Builder 与 Session 共享后端场景不受影响。

**✅ 模块间联通**
- 向后兼容：`MemoryService(persistence=...)` 行为不变；全部既有测试通过。

**✅ 可用性**
- 665 测试全绿，新增 7 个用例覆盖路由/回退/共享/close 去重/默认创建。

### 发现的问题与边界
| # | 问题 | 处置 |
|---|------|------|
| M1 | `close()` 从“只关默认后端”变为“关全部去重后端”——共享实例只关一次（已用 id 去重） | 已实现并测试 |
| M2 | 自定义后端无 `close()` 时静默跳过 | 与 MemoryPersistence 契约一致（close 非必选） |
| M3 | 向量/图检索能力仍取决于各层后端实现，本次只完成 storage 注入层 | 记录为后续增强 |

---

## 第一轮自省（2026-07-24 10:00）

### 发现的问题
- 3 处崩溃级 bug（未定义变量、双重初始化、SyntaxError）
- 5 处逻辑错误（超时系统失效、缓存过期、消息匹配跨轮次）
- 4 处资源泄漏（SQLite 未关闭、后台任务无法关闭、stderr 管道阻塞）
- 4 处架构/并发问题（Factory 可变状态、后门访问、frozen 契约违反）
- 5 处功能缺失/性能（并行 tool_calls 被忽略、O(n) 查询、无类型校验）
- 10+ 处代码异味（`type: ignore`、`__import__` hack、重复模板）

### 修复措施（R1-R10）
| # | 文件 | 修改内容 |
|---|------|---------|
| R1 | `_react.py` | `runtime`→`ctl` 修复未定义变量崩溃 |
| R2-R3 | `_runtime.py` | 修复 `_cancelled` 双重初始化 |
| R4-R10 | 多个文件 | before_llm/after_tool 顺序修正、session_end 顺序修正、serialize_for_llm 集成 |

### 最终状态
✅ 282 测试通过，设计文档差异全部修复。

---

## 第二轮自省（2026-07-24 12:00）

### 发现的问题
- 第二轮深度审查发现运行时 bug、代码异味

### 修复措施（R11-R26）
| # | 文件 | 修改内容 |
|---|------|---------|
| R11 | `_react.py` | `run_stream` 中 `runtime`→`ctl` 二次修复 |
| R12 | `_service.py` | `_BackgroundTaskGroup` 追踪 fire-and-forget 任务 |
| R13-R14 | `_entity.py`, `_eviction.py` | `utcnow()`→`now(timezone.utc)` 时区修复 |
| R15 | `_dispatcher.py` | 支持并行多 `tool_call`（`asyncio.gather`） |
| R16 | `_commit.py` | 消息匹配修复（同一轮次） |
| R17-R26 | 多个文件 | 移除后门、enable/disable、cancel 中断、stderr 读取、测试修复 |

### 最终状态
✅ 575 测试通过，ruff 零报错。

---

## 第三轮自省（2026-07-24 14:00）

### 发现的问题
- 性能瓶颈、配置校验缺失

### 修复措施（R27-R29）
| # | 文件 | 修改内容 |
|---|------|---------|
| R27 | `_runtime_config.py` | `from_yaml` 加顶层类型校验 + `utf-8-sig` |
| R28 | `_episodic.py` | 用户索引键，跨 session 查询 O(n)→O(m) |
| R29 | `pyproject.toml` | 添加 `tomli` 依赖 |

### 最终状态
✅ 575 测试通过，跨 session 查询性能优化。

---

## 第四轮自省（2026-07-24 15:00）

### 发现的问题
- 5 个 Store 类重复序列化模板代码

### 修复措施（R30-R35）
| # | 文件 | 修改内容 |
|---|------|---------|
| R30 | `_stores/_base.py` | **新增** `BaseStore[T]` 泛型基类 |
| R31-R35 | 5 个 Store | 继承 `BaseStore`，消除 ~50 行模板代码 |

### 最终状态
✅ 575 测试通过，净减 ~50 行。

---

## 第五轮自省（2026-07-24 15:30）

### 发现的问题
- 死代码、过期数据缓存、类型安全

### 修复措施（R36-R47）
| # | 文件 | 修改内容 |
|---|------|---------|
| R36-R37 | `_runtime.py` | 删除 `_cancelled` 重复初始化；显式 `_loop` 类型 |
| R38 | `_serializer.py` | 删除 `_last_result` 缓存 |
| R39-R43 | `_stores/` | `BaseStore[T]` 泛型化，消除 4 处 `type: ignore` |
| R44 | `_runtime_config.py` | `from_env` 支持多级 `__` 嵌套 |
| R45 | `_react.py` | `__import__` hack→`FinishReason.STOP` 直接引用 |
| R46-R47 | `README.md`, `_semantic.py` | 文档修复、语法错误修复 |

### 最终状态
✅ `type: ignore` 从 15+ 降至 9 处，575 测试通过。

---

## 第六轮自省（2026-07-24 16:00）

### 发现的问题
- 深度审计发现隐藏的运行时 bug

### 修复措施（R48-R53）
| # | 文件 | 修改内容 |
|---|------|---------|
| R48-R49 | `_runtime.py` | 删除 `_cancel_event` 死代码；修复 `_cancelled` AttributeError |
| R50 | `loops/_factory.py` | `_registry` 模块级 dict，消除类级可变状态并发隐患 |
| R51 | `llm/_executors/_openai.py` | `consecutive_errors` 传值修复 |
| R52 | `memory/_service.py` | `_BackgroundTaskGroup.shutdown()` 加超时保护 |
| R53 | `pyproject.toml` | 补齐 dev 依赖 |

### 最终状态
✅ 575 测试通过，并发安全、资源泄漏修复。

---

## 第七轮自省（2026-07-24 17:00）

### 发现的问题
- 30 个 ruff 违规（E402×15, E501×5, F401×1, I001×6, E501-tests×4）
- `services["_assembled_messages"]` 后门模式
- `dedup_memory_ids` 恒空（核心功能损坏）
- `RuntimeContext` 回调类型不匹配
- 测试 3 个 RuntimeWarning、`_selector.py` 原地修改

### 修复措施（R54-R70）
| # | 文件 | 修改内容 |
|---|------|---------|
| R54-R55 | `_builder.py`, `_runtime.py` | E402: import 移至 logger 前 |
| R56 | `_runtime.py` | `_default_loop` 加 deprecation warning |
| R57 | `_control.py` | F401: 删除未使用的 `BudgetSnapshot` import |
| R58-R61 | 4 文件 | E501: 断行修复 |
| R62-R64 | 3 文件 | **后门修复**: `services["_assembled_messages"]`→`ContextPayload.assembled_messages` |
| R65 | `_compressor.py` | `dedup_memory_ids` 真正填充 |
| R66 | `_selector.py` | `turns.reverse()`→`list(reversed(turns))` |
| R67 | `context/_context.py` | `_update_context_payload_callback` 类型精确化 |
| R68-R70 | 测试文件 | I001 自动排序、E501 断行、RuntimeWarning 修复 |

### 最终状态
✅ ruff 30→0，575 测试通过，后门消除，记忆去重修复。

---

## 第八轮自省（2026-07-24 18:00）

### 发现的问题
- **严重（9）**: S1 死代码、S2 after_llm ctx 过时、S3 plan 路由断裂、S4 MCP 逐字节读、S5 kill 后挂起、S6 累积泄漏、S7 无输入校验、S8 流式漏 hook、S9 cancel 不生效
- **中等（18）**: M1-M18（路由不匹配、ctx 快照、解析脆弱、循环依赖、name/kwargs 校验、长度限制、coverage 等）

### 修复措施（R71-R88）

| 轮 | # | 文件 | 修改内容 |
|----|---|------|---------|
| 8a | R71 | `_steps/_step_runner.py` | 删除死代码 `run_llm_step`（72 行） |
| 8a | R72 | `_mcp/_client.py` | `read(1)`→`readuntil(b"\n")`，大响应 O(n)→O(1) |
| 8a | R73 | `_mcp/_client.py` | `kill()` 后 `wait()` 加 5s 超时保护 |
| 8a | R74 | `loops/_plan_execute.py` | `run_stream` 首轮 `injected_context.clear()` |
| 8a | R75 | `loops/_workflow.py` | `run_stream` 补 `_run_before_step_hooks` |
| 8a | R76 | 测试 2 文件 | 迁移 9 个测试从 `run_llm_step`→`run_llm_only`/`run_step` |
| 8b | R77 | `_runtime.py` | plan 自定义 step_id 默认映射为 llm 步骤 |
| 8b | R78 | `_dispatcher.py` | `json.loads` 加 65536 字符上限 |
| 8b | R79 | `loops/_plan_execute.py` | `_parse_plan` 合并冗余 JSON 提取逻辑 |
| 8b | R80 | `tools/_spec.py` | `__post_init__` 加 name 格式校验 |
| 8b | R81 | `tools/_registry.py` | `execute()` 加 required 参数 + 多余参数检测 |
| 8b | R82 | `context/_manager.py` | recall_raw query 截断至 2048 字符 |
| 8b | R83 | `memory/_hooks/_commit.py` | raw 字段截断至 16384 字符 |
| 8b | R84 | `runtime/_builder.py` | `from_config` 注释说明 hooks/plugins 需手动注册 |
| 8c | R85 | `_runtime.py` | after_llm 前重建 ctx，使 hooks 看到最新 messages |
| 8c | R86 | `_runtime.py` | `_default_loop` 加 `self._cancelled` 检查 |
| 8c | R87 | `loops/_react.py` | run_stream 步后 hook 前重建 ctx |
| 8c | R88 | `loops/_workflow.py` | run/run_stream 加循环依赖检测（`in_path`） |

### 最终状态
✅ **575 tests, ruff 零报错, type:ignore 9 处。**

---

## 第九轮自省（2026-07-24 18:30）

### 发现的问题
- 3 处 `__import__` hack 残留（`_plan_execute.py`, `_workflow.py`, `_mcp/_client.py`）

### 修复措施（R89-R91）
| # | 文件 | 修改内容 |
|---|------|---------|
| R89 | `loops/_plan_execute.py` | `__import__`→直接 `import FinishReason` |
| R90 | `loops/_workflow.py` | 同上 |
| R91 | `_mcp/_client.py` | `__import__("os")`→`import os` |

### 最终状态
✅ `__import__` hack 清零，`type: ignore` 降至 **7 处**，575 测试通过。

---

## 第十轮自省（2026-07-24 19:00）

### 发现的问题
- 4 处 `logger.error`/`logger.warning` 缺少 `exc_info=True`，异常时丢失堆栈

### 修复措施（R92-R95）
| # | 文件 | 修改内容 |
|---|------|---------|
| R92 | `memory/_service.py` | `_safe_background_task` 加 `exc_info=True` |
| R93 | `tools/_dispatcher.py` | tool 执行失败日志加 `exc_info=True` |
| R94 | `tools/_mcp/_manager.py` | MCP 连接失败日志加 `exc_info=True` |
| R95 | `memory/_hooks/_commit.py` | 记忆写入失败日志加 `exc_info=True` |
| R96 | `tools/_mcp/_client.py` | 子进程关闭异常日志加 `exc_info=True` |
| R97 | `tools/_skill/_manager.py` | skill.toml 加载失败日志加 `exc_info=True` |

### 最终状态
✅ 全部 `except` 块均有 `exc_info=True`，异常堆栈不再丢失。

---

## 修复总览

| 指标 | 数值 |
|------|------|
| **总修复项** | **97**（R1-R97） |
| **修改文件** | ~62 个 |
| **死代码删除** | ~72 行 |
| **`type: ignore`** | 15+ → **7** |
| **`__import__` hack** | 3 → **0** |
| **缺少 `exc_info` 的 except 块** | 6 → **0** |
| **ruff 违规** | 30 → **0** |
| **测试通过** | **575** ✅ |
| **总耗时** | ~9 小时 |

### 修复分布

| 领域 | 数量 | 代表修复 |
|------|------|---------|
| 崩溃/运行时 | 5 | 未定义变量、双重初始化、SyntaxError |
| 状态机 | 4 | 双调保护、cancel 中断、超时系统 |
| 资源管理 | 4 | SQLite 关闭、后台任务追踪、shutdown 超时 |
| 架构/安全 | 5 | 后门移除、Factory 并发、frozen 契约、输入校验×2 |
| 性能 | 3 | MCP readuntil、用户索引、并行 tool_calls |
| 功能缺失 | 5 | plan 路由、流式补 hook、循环检测、死代码删除 |
| 内存泄漏 | 2 | PlanExecute clear、raw 截断 |
| 代码质量 | 10+ | ruff 清零、BaseStore 泛型、`__import__` hack |
| 类型安全 | 6 | BaseStore[T]、回调类型、显式类型、测试 spec |
| 测试 | 10+ | Mock spec、close、controller、测试迁移 |

---

## 剩余未修复

### 长期搁置的架构债
| 项 | 说明 |
|----|------|
| `AgentRuntime` ~1160 行架构拆分 | 需设计评审，不宜在一次会话中完成 |
| 216 处 `Any` 逐步替换 | 违反设计文档规范，但单次修改风险高 |
| 7 处 `type: ignore` | 部分为 SDK/运行时兼容场景，不可消除 |
| M16: coverage 83% → 96% | 需补充 Loop 策略测试，约 3-5 小时 |
| `overview.md` 实为 changelog | 非阻塞，后续改名即可 |

### 已知但低优先级
| # | 问题 | 理由 |
|---|------|------|
| M1 | `_execute_tool_step` tool_call_request 恒 None | 字段设计为未来用，当前无逻辑依赖 |
| M3 | `_budget_after_llm_transform` 修改不影响 ctx | ctx.budget 是快照，transform 修改自身正确 |
| M7 | MCP `_sse_url` 异常时状态不一致 | 不影响功能性（`_connected=False` 保护） |
| M8 | MCP `call_tool` 中 `result.get()` 可能 None | 极端边缘情况 |
| M13 | `user_id` 为 None 只写情景记忆 | 设计如此，需文档说明 |
| M15 | `build()` 不校验 memory_service 协议 | 运行时 Duck Typing，Python 惯用方式 |
| M17-M18 | `type: ignore`/`Any` | 长期逐步清理 |
