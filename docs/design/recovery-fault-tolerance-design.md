# 恢复与容错设计方案（v0.1）

> ⚠️ **本文档是 `agent-runtime-design.md` 的子文档**。阅读前请确保已理解主文档中的
> **Runtime 状态机**、**ON_ERROR 挂载点**与 **Session 断点恢复**。
>
> 关联文档：
> - [`session-component-design.md`](session-component-design.md) — 会话恢复（ss:）与游标
> - [`memory-system-design.md`](memory-system-design.md) — wm 工作记忆快照
> - [`lifecycle-agent-registry-design.md`](lifecycle-agent-registry-design.md) — CheckpointHook（快照生产端）
> - [`governance-component-design.md`](governance-component-design.md) — error 治理

## 0. 背景与目标

当前容错能力分散且不完整：
- LLM 层有重试（`_retry.py` / OpenAILLMExecutor 指数退避）；
- Session 有恢复机制（ss: 历史 + wm 快照 + resume hooks），但 **wm 快照没有生产端**；
- 工具调用、审计落库、网关请求**没有统一幂等/重试语义**；
- 取消与流式中断的传播没有定义。

本文档定义**恢复与容错设计方案**：快照生产、幂等、重试矩阵、取消传播、降级策略，
让"进程崩溃 / 网络抖动 / 工具失败 / 用户中断"都有明确行为。

## 1. 现状盘点

| 项 | 状态 |
|----|------|
| LLM 重试（指数退避 + 上限） | ✅ 已实现 |
| Session 恢复（ss: 历史 / 游标 / resume hooks） | ✅ 已实现 |
| wm 快照存储 | ✅ 已实现 |
| wm 快照生产端（pause / error / checkpoint 触发） | ❌ 缺失（由 lifecycle CheckpointHook 补齐） |
| 工具调用重试 / 幂等 | ❌ 缺失 |
| 审计落库幂等 | ❌ 缺失 |
| 取消 / 流式中断传播 | ⚠️ 有 `cancel()`，但流式 generator 中断语义未定义 |

## 2. 设计原则

### R1 分层容错，各层各管一段

| 层 | 负责 | 机制 |
|----|------|------|
| 网关（请求） | 客户端重试的幂等 | idempotency key |
| Runtime（执行） | 状态一致性 | 快照 + 恢复 |
| LLM | 瞬时故障重试 | 已有 retry |
| 工具 | 可配置重试 | 新增 ToolRetryPolicy |
| 落库（审计/记忆） | 不因写入失败影响主流程 | 异步 + 重试/丢弃策略 |

### R2 快照是恢复的唯一基准

恢复点 = Session 最后提交的轮次 + wm 快照的执行状态；
**未提交的失败轮次不恢复**（由用户重发），与 Session v2 语义一致。

### R3 幂等优先于重试

- 网关请求：`Idempotency-Key` 头，网关缓存响应，重复请求返回缓存；
- 工具调用：`tool_call_id` 作为幂等键（已有消息级去重基础）；
- 审计落库：事件 `(request_id, point, step_index)` 幂等键，sink 去重。

### R4 取消语义

- `runtime.cancel()`：置取消标志，循环检查点中断；
- 流式：客户端断开 → 网关取消生成器 → runtime 进入 cancelled 状态 → 快照丢弃（不写 wm）；
- 后台任务：`_background.shutdown(wait=False)` 强制取消并排空。

## 3. 方案

### 3.1 快照生产（承接 lifecycle CheckpointHook）

| 触发 | 动作 |
|------|------|
| pause | 写 wm（plan / budget / pause_state / step_index） |
| error（可恢复） | 写 wm（error_state / 进度） |
| checkpoint（显式） | 写 wm |
| cancel / 正常结束 | 丢弃 wm |

### 3.2 重试矩阵

| 目标 | 触发条件 | 重试策略 | 上限 |
|------|---------|---------|------|
| LLM | 可重试异常（APITimeout / RateLimit / APIError） | 指数退避 | `max_retries` |
| 工具 | 可配置异常白名单 + 幂等键 | 固定间隔 | `ToolRetryPolicy.max_attempts` |
| 审计落库 | sink 瞬时失败 | 队列内重试 | `max_attempts` 后丢弃 + 告警 |
| 网关请求 | 客户端幂等键 | 客户端决定 | — |

### 3.3 降级策略

- 预算超限：`block_on_exceed=False` 时降级为"仅记录并放行一次"（governance 已设计）；
- LLM 不可用：错误分类 → 降级文案（error governance）；
- 记忆不可用：MemoryCommitHook 已静默降级（warning 不阻塞）。

## 4. 实施顺序

| 步 | 内容 | 验收 |
|----|------|------|
| 1 | CheckpointHook（承接 lifecycle） | pause / error / checkpoint 快照单测 |
| 2 | ToolRetryPolicy + 工具执行重试 | 白名单 / 上限 / 幂等单测 |
| 3 | 审计落库重试与去重 | 幂等键 / 重试 / 丢弃单测 |
| 4 | 网关 idempotency key | 重复请求返回缓存测试 |
| 5 | 取消传播（流式断开 / cancel） | 状态一致性测试 |

每步完成即：全量测试通过、覆盖率 ≥96%、ruff 零报错、文档同步。

## 5. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 快照写放大 | 状态跃迁时才写；可配置 checkpoint 间隔 |
| 重试放大故障 | 全局限流（护栏 ratelimit）+ 上限收敛 |
| 幂等键膨胀 | 网关缓存 TTL + LRU |
| 取消与后台任务竞态 | 取消后统一丢弃快照，后台任务排空后再销毁 |

## 6. 待确认决策

| 编号 | 决策 | 推荐 |
|------|------|------|
| D1 | ToolRetryPolicy 归属 | 护栏组件域（tools 治理）vs tools 包内（推荐 tools 包内，工具执行语义） |
| D2 | 网关幂等缓存实现 | 内存 LRU（推荐）vs Redis（可选后端） |
| D3 | 取消后快照 | 一律丢弃（推荐）vs 保留可恢复 |

## 附录 A：文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/lifecycle/_hooks.py` | 新增 | CheckpointHook |
| `src/tools/_retry.py` | 新增 | ToolRetryPolicy |
| `src/governance/audit/*` | 修改 | 落库重试与去重 |
| `src/gateway/_app.py` | 修改 | idempotency key |
| `tests/test_fault_tolerance_*.py` | 新增 | 各层容错测试 |

## 附录 B：修订记录

| 版本 | 日期 | 说明 |
|------|------|------|
| v0.1 | 2026-08-17 | 初稿 |