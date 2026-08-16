# 网关（接入层）设计方案（v0.1）

> ⚠️ **本文档是 `agent-runtime-design.md` 的子文档**。阅读前请确保已理解主文档中的
> **Runtime 纯壳**（§1）、**执行闭环 API**（`run / run_stream / resume / cancel`）
> 与 **Builder 唯一接线点**。
>
> 关联文档：
> - [`governance-component-design.md`](governance-component-design.md) — 护栏组件与网关的分工契约（§8）
> - [`session-component-design.md`](session-component-design.md) — 会话持久化 / 续聊恢复
> - [`loop-strategy-design.md`](loop-strategy-design.md) — 流式执行（run_stream）事件来源

## 0. 背景与目标

`AgentRuntime` 是纯壳：只暴露 Python 接口，不感知任何传输层。
外部工程（Web / 移动端 / 后台服务）要接入 Agent，需要一个**接入层适配器**：
把 `run / run_stream / resume / cancel` 等能力暴露为 HTTP / SSE 服务。

本文档定义**网关（接入层）的设计方案**：

- **目标 1（工程化落地）**：提供 REST + SSE 两种接入形态，外部工程零门槛调用；
- **目标 2（边界清晰）**：网关是 **runtime 之外的应用层适配器**，不修改 runtime 核心；
- **目标 3（可替换）**：`AgentGateway` 协议 + FastAPI 默认实现，传输框架可换；
- **目标 4（与护栏协同）**：承接 governance 设计的分工契约——网关管请求边界，
  护栏管会话内治理，审计单一出口。

**非目标**：
- 分布式路由 / 负载均衡 / 服务注册（宿主基础设施职责）；
- 在 `AgentRuntime` 内实现任何 HTTP / SSE 能力；
- 网关层双写审计（审计单一出口在护栏，见 §7）。

## 1. 现状盘点

| 项 | 状态 |
|----|------|
| Runtime 公共 API（run / run_stream / resume / cancel / get_session_state） | ✅ 已实现 |
| RunResult / StreamEvent / SessionSnapshot 返回类型 | ✅ 已实现 |
| Builder 构造（builder().session_id() 续聊） | ✅ 已实现 |
| SessionService 会话持久化 / 恢复 | ✅ 已实现 |
| 审批 pause / resume（HumanApprovalInterceptor → PauseAction） | ✅ 已实现 |
| 护栏协议（AuditSink / RateLimiter 等） | 🚧 设计中（governance v0.2） |
| HTTP / SSE 依赖（fastapi / uvicorn / httpx-sse） | ✅ 已声明（dev 组） |
| 网关代码 | ❌ 无（main.py 仅为 hello world） |

## 2. 设计原则

### R1 边界：网关是 runtime 之外的适配器

`src/gateway` 依赖 `src.runtime` 与 `src.governance` 的**公共 API / 协议**，
`src/runtime` 不得反向依赖网关。网关只调用：

- `AgentRuntime.run(user_input) -> RunResult`
- `AgentRuntime.run_stream(user_input) -> AsyncIterator[StreamEvent]`
- `AgentRuntime.resume(approval_id)` / `cancel()` / `destroy()` / `get_session_state()`
- `RuntimeBuilder`（经 RuntimeFactory 封装）

### R2 可替换实现

```python
class AgentGateway(Protocol):
    """网关协议——任何传输框架实现均可替换。"""

    def create_app(self) -> Any: ...   # 返回可挂载的 ASGI 应用
```

FastAPI 是默认实现；替换为其他框架只需实现同一协议。

### R3 复用护栏，不重复治理

- 请求级治理（鉴权 / IP 限流）在网关做；
- 会话内治理（预算 / 审批 / 质量 / 脱敏）在护栏做；
- 审计**单一出口在护栏**：网关只把 `client_ip / route / user` 写入
  `runtime.services`（只读注入），由 AuditPlugin 采集合并；
- 限流协议复用 governance 的 `RateLimiter`（网关可注入同一个实现）。

### R4 会话生命周期由网关持有

网关维护 `session_id ↔ runtime` 的活跃映射（LRU + TTL），
续聊请求复用活跃 runtime；空闲回收调用 `destroy()`。

### R5 流式一致

SSE 帧直接映射 `StreamEvent`（`text / tool_start / tool_end / error / done`），
事件类型与字段保持稳定，客户端按事件类型消费。

### R6 错误码统一

网关层错误映射为稳定状态码 + 错误体（见 §6），不透传内部异常细节。

## 3. 目录结构

```text
src/gateway/
  __init__.py            # 惰性导出：GatewayConfig / AgentGateway / create_app
  _config.py             # GatewayConfig
  _protocols.py          # AgentGateway / AuthProvider / RuntimeFactory
  _runtime_factory.py    # 按配置构造 runtime（Builder 封装，支持 agent_id 路由）
  _session_store.py      # session_id ↔ runtime 映射 + LRU/TTL 回收
  _schemas.py            # ChatRequest / ChatResponse / ApprovalRequest / SSE 帧模型
  _errors.py             # 网关错误类型与状态码映射
  _sse.py                # StreamEvent → SSE 帧编码
  _deps.py               # 依赖注入（AuthProvider / RateLimiter / 元数据注入）
  _app.py                # FastAPI 默认实现（REST + SSE + 审批 + 健康检查端点）
```

## 4. API 设计

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/v1/chat` | 非流式对话 |
| POST | `/v1/chat/stream` | SSE 流式对话 |
| POST | `/v1/approvals/{approval_id}/approve` | 审批通过 → `runtime.resume(approval_id)` |
| GET | `/v1/sessions/{session_id}` | 会话快照（`get_session_state` + SessionService 摘要） |
| GET | `/v1/health` | 健康检查 |

### 4.1 请求体（ChatRequest）

```json
{
  "agent_id": "customer_service",
  "session_id": "sess_xxx",
  "user_input": "查订单",
  "metadata": {}
}
```

`session_id` 缺省时网关创建新会话；续聊时传回上次响应中的 `session_id`。

### 4.2 响应体（ChatResponse，非流式）

```json
{
  "session_id": "sess_xxx",
  "content": "已为您查询订单…",
  "messages": [],
  "tool_calls": [],
  "token_used": 123,
  "finish_reason": "stop",
  "status": "ended"
}
```

### 4.3 SSE 流（/v1/chat/stream）

逐条映射 `StreamEvent`：

```text
event: text
data: {"content": "你好"}

event: tool_start
data: {"name": "query_order"}

event: tool_end
data: {"name": "query_order"}

event: error
data: {"error": "..."}

event: done
data: {"result": {"session_id": "...", "content": "...", "status": "ended"}}
```

## 5. 请求生命周期

```text
HTTP 请求
  │
  ├─ 1. AuthProvider 鉴权                失败 → 401
  ├─ 2. 请求级限流（网关层）              超限 → 429
  ├─ 3. 请求体校验                        非法 → 400
  ├─ 4. RuntimeFactory 获取 runtime
  │      ├─ 命中活跃映射 → 复用
  │      └─ 未命中 → 按 agent_id 配置 Builder 构造
  │           ├─ 续聊：.session_id(现有) + SessionService 恢复
  │           └─ 新会话：生成 session_id
  ├─ 5. 注入请求元数据（只读）
  │      runtime.services["client_ip"|"route"|"user"] = ...
  ├─ 6. run / run_stream
  ├─ 7. 非流式 → ChatResponse；流式 → SSE 帧
  └─ 8. 会话映射更新 + 审计（护栏 AuditSink 异步落库）
```

## 6. 错误码与异常映射

| 场景 | 状态码 | 错误体 |
|------|--------|--------|
| 未认证 / 令牌无效 | 401 | `{"code": "unauthorized"}` |
| 请求级限流超限 | 429 | `{"code": "rate_limited", "retry_after": 60}` |
| 请求体非法 | 400 | `{"code": "invalid_request", "detail": ...}` |
| agent_id 未配置 | 404 | `{"code": "agent_not_found"}` |
| 会话不存在 / 已过期 | 404 | `{"code": "session_not_found"}` |
| 审批 ID 不存在或非暂停态 | 409 | `{"code": "approval_not_pending"}` |
| 运行时内部错误 | 500 | `{"code": "runtime_error", "detail": "..."}` |

> 错误体不透传堆栈；内部异常经日志记录（可对接护栏审计/错误治理）。

## 7. 与护栏的分工契约（承接 governance §8）

| 层 | 管什么 | 例子 |
|----|--------|------|
| 网关（请求边界） | 鉴权、IP / 请求级限流、错误码、SSE 协议、会话映射 | 谁在调、调多快、以什么格式回 |
| 护栏（会话内治理） | 预算 / 审批 / 质量 / 脱敏 / 工具权限 / 审计采集 | 这次会话能不能超支、工具要不要人批 |

- **审计单一出口**：网关只注入 `client_ip / route / user` 到 `runtime.services`，
  由 AuditPlugin 采集合并进 `GovernanceEvent.data`，网关不落库；
- **审批恢复**：`POST /v1/approvals/{id}/approve` → `runtime.resume(approval_id)`；
- **限流分工**：网关管请求级（IP / API Key），护栏管会话内 LLM 调用频率，
  可共用 governance 的 `RateLimiter` 协议。

## 8. 可替换点

| 协议 | 职责 | 默认实现 |
|------|------|---------|
| `AuthProvider` | 请求鉴权 | HeaderTokenProvider（示例）/ 可注入 JWT |
| `RuntimeFactory` | 按 agent_id / session_id 构造或复用 runtime | BuilderRuntimeFactory（读 GatewayConfig.agents） |
| `AgentGateway` | ASGI 应用形态 | FastAPI 实现 |
| `RateLimiter` | 请求级限流 | 复用 governance 协议（可注入） |
| `AuditSink` | 审计落库 | 由护栏提供，网关不实现 |

## 9. 配置

```python
@dataclass
class GatewayConfig:
    """网关配置。"""

    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = 8000
    auth: AuthProvider | None = None          # 默认 HeaderToken（读环境变量）
    session_idle_timeout_seconds: int = 1800  # 空闲回收
    max_active_sessions: int = 1000           # LRU 上限
    runtime: RuntimeConfig | None = None      # 默认 runtime 构造配置
    agents: dict[str, RuntimeConfig] = field(default_factory=dict)  # agent_id → 构造配置
```

YAML 示例（`gateway` 段挂在应用配置下，或独立 `gateway.toml`）：

```yaml
gateway:
  host: 0.0.0.0
  port: 8000
  session_idle_timeout_seconds: 1800
  max_active_sessions: 1000
  agents:
    customer_service:
      system_prompt: 你是电商客服助手
      loop: {strategy: plan_and_execute}
      governance:
        stack: full
        budget: {token_limit: 100000, step_limit: 50}
```

## 10. 实施顺序

| 步 | 内容 | 依赖 | 验收 |
|----|------|------|------|
| 1 | 公共底座：`_config.py` / `_protocols.py` / `_schemas.py` / `_errors.py` | 无 | 模型与错误码单测 |
| 2 | `_runtime_factory.py` + `_session_store.py` | 1 | 构造/复用/续聊/TTL 回收单测（无 HTTP） |
| 3 | `_sse.py`（StreamEvent → SSE 帧） | 1 | 全事件类型编码单测 |
| 4 | `_app.py` FastAPI：REST + SSE 端点 | 2、3 | TestClient 集成测试 |
| 5 | 鉴权 / 限流 / 元数据注入（对接 governance 协议） | 1 | 401 / 429 / 审计字段单测 |
| 6 | 审批端点（approve → resume） | 4 | 暂停 → 审批 → 恢复 E2E |
| 7 | 健康检查 / 会话快照端点 + 文档 | 4 | 冒烟通过 |

每步完成即：全量测试通过、覆盖率 ≥96%、ruff 零报错、overview + 自审记录 + 文档同步。

## 11. 验收标准

- `POST /v1/chat` 与 `/v1/chat/stream` 全链路可用（含会话续聊）；
- 审批暂停 → 网关 approve 端点 → `resume` 继续执行；
- 鉴权 401、限流 429、错误码统一；
- 审计事件包含 `client_ip / route / user`（由护栏 sink 落库，网关不双写）；
- 活跃会话映射 LRU + TTL 回收生效；
- 全量测试 / 覆盖率 / ruff 达标。

## 12. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 流式连接中断 / 客户端断开 | SSE 生成器 finally 中释放 runtime（destroy 或放回池）；取消传播测试 |
| 活跃会话映射内存膨胀 | LRU 上限 + TTL 回收 + 会话快照持久化后可重建 |
| 审批暂停的 runtime 长期挂起 | paused 状态排除在空闲回收外，另设 `approval_wait_timeout`（可选） |
| 与护栏协议版本耦合 | 网关只依赖 governance 公共协议；协议未定前先以"注入元数据"最小契约落地 |
| 重复治理（网关 + 护栏双限流/双审计） | 按 §7 分工契约；审计单一出口、限流协议共用 |

## 13. 待确认决策

| 编号 | 决策 | 选项 |
|------|------|------|
| D1 | 网关包位置 | **A：`src/gateway/`（推荐，与 governance 同级）**；B：独立包 |
| D2 | 默认认证实现 | **A：HeaderToken（推荐，零依赖）**；B：JWT（需引入依赖） |
| D3 | 审批拒绝语义 | **A：网关只提供 approve（resume）（推荐，runtime 无 reject 通道）**；B：为 reject 扩展 runtime API（改动核心，暂缓） |
| D4 | 依赖归类 | **A：fastapi/uvicorn/httpx-sse 移入主依赖（网关成为正式组件，推荐）**；B：保持 dev（网关可选安装） |

## 附录 A：文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/gateway/__init__.py` | 新增 | 惰性导出 |
| `src/gateway/_config.py` | 新增 | GatewayConfig |
| `src/gateway/_protocols.py` | 新增 | AgentGateway / AuthProvider / RuntimeFactory |
| `src/gateway/_runtime_factory.py` | 新增 | Builder 封装 |
| `src/gateway/_session_store.py` | 新增 | 活跃会话映射 |
| `src/gateway/_schemas.py` | 新增 | 请求/响应/SSE 模型 |
| `src/gateway/_errors.py` | 新增 | 错误码映射 |
| `src/gateway/_sse.py` | 新增 | StreamEvent → SSE 帧 |
| `src/gateway/_deps.py` | 新增 | 依赖注入 |
| `src/gateway/_app.py` | 新增 | FastAPI 默认实现 |
| `tests/test_gateway_*.py` | 新增 | 单元 + 集成 + E2E |
| `pyproject.toml` | 修改（D4=A 时） | 依赖归类调整 |

## 附录 B：修订记录

| 版本 | 日期 | 说明 |
|------|------|------|
| v0.1 | 2026-08-16 | 初稿：边界与原则、API 设计、请求生命周期、会话映射、与护栏分工、配置、实施顺序、决策 |