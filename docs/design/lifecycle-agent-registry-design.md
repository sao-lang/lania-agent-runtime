# 生命周期与资源管理设计方案（v0.1）

> ⚠️ **本文档是 `agent-runtime-design.md` 的子文档**。阅读前请确保已理解主文档中的
> **Runtime 状态机**（§3）、**Builder 构造**与 **Session 断点恢复**。
>
> 关联文档：
> - [`session-component-design.md`](session-component-design.md) — 会话生命周期与断点恢复
> - [`memory-system-design.md`](memory-system-design.md) — wm 工作记忆快照（checkpoint 存储侧）
> - [`gateway-design.md`](gateway-design.md) — 会话映射（本设计的薄客户端）
> - [`governance-component-design.md`](governance-component-design.md) — 护栏状态清理（SESSION_END）

## 0. 背景与目标

当前框架能"建 runtime"，但缺少框架级的：
- **AgentRegistry**：`agent_id → 构造配置` 的注册与查询（设计文档提过，代码没有）；
- **统一生命周期**：创建 / 复用 / 销毁 / 优雅关闭没有统一语义；
- **崩溃恢复数据源**：`wm` 工作记忆快照只有存储侧（`checkpoint()`），
  **没有生产端**——Session Phase 2 的 resume 机制实际没有数据来源。

本文档定义**生命周期与资源管理设计方案**，让 runtime 实例可被框架统一管理、
可复用、可恢复、可优雅关闭，并给网关 / 护栏 / 多 Agent 提供公共底座。

## 1. 现状盘点

| 项 | 状态 |
|----|------|
| Builder 构造（`.build()`） | ✅ 已实现 |
| `runtime.use(plugin)` 异步挂载 | ✅ 已实现 |
| `destroy()` / `cancel()` / 状态枚举 | ✅ 已实现 |
| Session 断点恢复（SESSION_RESUME hooks） | ✅ 已实现（Phase 2） |
| wm 快照存储（`MemoryService.checkpoint/restore`） | ✅ 已实现 |
| wm 快照**生产端**（谁在 pause/error/checkpoint 时写快照） | ❌ 缺失 |
| AgentRegistry（agent_id → 配置） | ❌ 缺失 |
| runtime 复用 / 引用计数 / 优雅关闭链 | ❌ 缺失 |

## 2. 设计原则

### R1 Agent 即配置

`AgentSpec` 是 agent 的唯一事实来源：agent_id、构造配置（Builder 参数）、
默认会话策略（是否持久化 / TTL）、默认护栏 / 观测配置。
Runtime 实例**不保存** AgentSpec，只保存 agent_id 与运行状态。

### R2 生命周期统一由 RuntimeLifecycle 管理

```python
class RuntimeLifecycle:
    """统一管理 runtime 的获取 / 归还 / 销毁。"""

    async def acquire(self, agent_id: str, session_id: str = "") -> AgentRuntime: ...
    async def release(self, runtime: AgentRuntime) -> None: ...
    async def shutdown(self) -> None: ...
```

网关、测试、宿主统一走 `acquire/release`，不再各自 new。

### R3 恢复数据源必须补齐

在 pause / error / checkpoint 三个触发点**生产** wm 快照
（`CheckpointHook`，见 §5），否则断点恢复机制是空转的。

### R4 优雅关闭链

`shutdown()` 顺序：停止接收新请求 → 等待活跃任务（超时取消）→
逐 runtime `destroy()` → 关闭后端（Session / Memory / 观测 / 护栏 flush）。

## 3. 目录结构

```text
src/lifecycle/
  __init__.py            # 惰性导出
  _config.py             # LifecycleConfig / AgentSpec
  _registry.py           # AgentRegistry（注册 / 查询 / 校验）
  _factory.py            # AgentFactory（AgentSpec → Builder → runtime）
  _lifecycle.py          # RuntimeLifecycle（acquire / release / shutdown）
  _hooks.py              # CheckpointHook（pause / error / checkpoint 三点生产 wm）
```

## 4. AgentRegistry

```python
@dataclass
class AgentSpec:
    agent_id: str
    description: str = ""
    builder: Callable[[], RuntimeBuilder] | None = None   # 编程式构造
    config: RuntimeConfig | None = None                  # 配置式构造
    session_policy: SessionPolicy | None = None          # 会话持久化策略
    default_governance: GovernanceConfig | None = None

class AgentRegistry:
    def register(self, spec: AgentSpec) -> None: ...
    def get(self, agent_id: str) -> AgentSpec: ...       # 不存在抛 AgentNotFoundError
    def list(self) -> list[AgentSpec]: ...
```

- 启动时由宿主注册（YAML 或代码），网关 `RuntimeFactory` 经注册表解析 agent_id；
- 重复注册 / 未知 agent_id 有明确错误（`AgentNotFoundError`）。

## 5. CheckpointHook（补齐恢复数据源）

| 触发点 | 行为 |
|--------|------|
| pause（审批暂停） | 写 wm 快照（plan / budget / pause_state / step_index） |
| error（非致命错误） | 写 wm 快照（error_state / 进度） |
| checkpoint（显式） | 宿主或护栏触发，写 wm 快照 |

- 挂载：SESSION 相关点 + ON_ERROR（Observer）+ 显式服务入口；
- 数据来源：`ctx`（budget / plan / step_index）+ `runtime.services`（pause_state）；
- 恢复：现有 `SessionResumeHook` / `MemoryResumeHook` 已就绪，无需改动；
- 与护栏 error 治理联动：护栏记录错误分类，CheckpointHook 负责落快照。

## 6. RuntimeLifecycle 语义

```python
async def acquire(agent_id, session_id=""):
    # 1. registry.get(agent_id) → AgentSpec
    # 2. 活跃池命中（agent_id + session_id）→ 返回复用
    # 3. 未命中 → factory.build(spec, session_id)（含 SessionService 恢复）
    # 4. 计数 +1，标记 busy

async def release(runtime):
    # 计数 -1；空闲超过 idle_timeout → destroy() + 移出池

async def shutdown():
    # 停止接收 → 等待活跃任务（超时取消）→ 逐实例 destroy() → 后端关闭
```

- 复用条件：`status in (IDLE, PAUSED)`（paused 等待审批时保留）；
- 容量上限：`max_active_runtimes`，超限抛 `RuntimeCapacityError`；
- 与网关 SessionStore 的关系：网关映射是 Lifecycle 的薄客户端，
  会话元数据归 SessionService，实例归 Lifecycle。

## 7. 实施顺序

| 步 | 内容 | 验收 |
|----|------|------|
| 1 | AgentSpec / AgentRegistry + AgentNotFoundError | 注册 / 查询 / 错误单测 |
| 2 | AgentFactory（Spec → Builder → runtime） | 编程式与配置式构造单测 |
| 3 | RuntimeLifecycle（acquire / release / 池 / 容量 / shutdown） | 复用 / 回收 / 优雅关闭测试 |
| 4 | CheckpointHook（三点生产 wm） | pause / error / checkpoint 快照单测 |
| 5 | 网关 RuntimeFactory 改造为基于 Registry + Lifecycle | 集成测试 |

每步完成即：全量测试通过、覆盖率 ≥96%、ruff 零报错、文档同步。

## 8. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 复用中的 runtime 状态脏（上轮未清理） | release 前校验状态；脏实例直接销毁重建 |
| paused 实例长期占用容量 | approval_wait_timeout 超时自动取消（可配置） |
| 快照写放大 | checkpoint 间隔 / 仅在状态跃迁时写 |
| 优雅关闭卡死 | shutdown 每阶段超时强制推进 |

## 9. 待确认决策

| 编号 | 决策 | 推荐 |
|------|------|------|
| D1 | 包位置 | `src/lifecycle/`（推荐） |
| D2 | CheckpointHook 归属 | lifecycle 内实现、经协议与 memory 对接（推荐）vs 放 memory |
| D3 | 复用池 | 按 session 维度复用（推荐）vs 按 agent 维度 |

## 附录 A：文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/lifecycle/*` | 新增 | 注册表 / 工厂 / 生命周期 / 快照生产 |
| `src/runtime/_runtime.py` | 修改（可选） | 状态查询辅助 |
| `tests/test_lifecycle_*.py` | 新增 | 单元 + 集成 |

## 附录 B：修订记录

| 版本 | 日期 | 说明 |
|------|------|------|
| v0.1 | 2026-08-17 | 初稿 |