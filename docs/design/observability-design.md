# 可观测性设计方案（v0.1）

> ⚠️ **本文档是 `agent-runtime-design.md` 的子文档**。阅读前请确保已理解主文档中的
> **Hook 治理体系**（Observer / Transform / Intercept）与 **Runtime 纯壳**。
>
> 关联文档：
> - [`governance-component-design.md`](governance-component-design.md) — 审计事件与护栏协议（审计 vs 观测分工）
> - [`gateway-design.md`](gateway-design.md) — 请求元数据注入（client_ip / route / user）
> - [`session-component-design.md`](session-component-design.md) — 会话维度观测

## 0. 背景与目标

当前框架只有散落的 `logging.getLogger(__name__)`，没有统一的：
- **结构化日志**（无统一字段 / 无 `request_id` 贯穿）；
- **指标**（LLM 调用数 / 延迟 / token、工具调用、护栏命中、会话数均不可观测）；
- **追踪**（一次请求从网关 → runtime → LLM → 工具 → 护栏的调用链无法还原）。

本文档定义**可观测性设计方案**，目标是让"框架行为可量化、可排查、可告警"，
同时与护栏的**审计**明确分工，避免双写。

## 1. 现状盘点

| 项 | 状态 |
|----|------|
| 日志 | ⚠️ 散落 logger，无统一格式与 request_id |
| 指标 | ❌ 无 |
| 追踪 | ❌ 无 |
| 审计事件 | 🚧 设计中（governance `GovernanceEvent`） |
| 采集点（12 挂载点 Observer） | ✅ 已实现，天然是观测采集点 |

## 2. 设计原则

### R1 观测与审计分工

| 维度 | 目的 | 输出 | 归属 |
|------|------|------|------|
| 日志 | 排障 | 文本行（结构化） | ObservabilityPlugin |
| 指标 | 告警 / 容量 | 数值序列 | ObservabilityPlugin |
| 追踪 | 调用链还原 | span 树 | ObservabilityPlugin |
| 审计 | 合规 / 追责 | 事件落库 | 护栏 AuditPlugin |

审计与观测**同源采集、不同出口**：同一个 Hook Observer 可同时产出指标增量与审计事件，
但落库与导出互不依赖。

### R2 采集不阻塞主流程

所有采集走异步缓冲 + 后台任务（复用 `src/runtime/_background.py` 公共任务组），
采集失败只告警不抛错。

### R3 一次请求一个 request_id

`request_id` 由网关生成并注入 `runtime.services["request_id"]`（只读），
贯穿日志 / 指标标签 / 追踪 span / 审计事件，是关联四者的主键。

### R4 协议化出口

指标 / 追踪后端可替换：

```python
class MetricsSink(Protocol):
    def inc(self, name: str, value: float = 1.0, labels: dict[str, str] | None = None) -> None: ...
    def observe(self, name: str, value: float, labels: dict[str, str] | None = None) -> None: ...

class TraceExporter(Protocol):
    async def export(self, spans: list["TraceSpan"]) -> None: ...
```

内置内存实现（`InMemoryMetrics` + `LoggingTraceExporter`），
生产可替换为 Prometheus / OpenTelemetry。

## 3. 目录结构

```text
src/observability/
  __init__.py            # 惰性导出
  _config.py             # ObservabilityConfig
  _protocols.py          # MetricsSink / TraceExporter / LogFormatter
  _metrics.py            # InMemoryMetrics（计数 / 直方图）
  _tracing.py            # TraceSpan / Tracer / LoggingTraceExporter
  _logging.py            # 结构化日志绑定（request_id 注入）
  _hooks.py              # ObservabilityHook（各挂载点 Observer）
  _plugin.py             # ObservabilityPlugin（Plugin 封装）
```

## 4. 指标清单（内置，可扩展）

| 指标 | 类型 | 标签 |
|------|------|------|
| `llm_calls_total` | Counter | agent_id / model / status |
| `llm_tokens_total` | Counter | agent_id / model / type(prompt\|completion) |
| `llm_latency_seconds` | Histogram | agent_id / model |
| `tool_calls_total` | Counter | agent_id / tool / status |
| `guardrail_hits_total` | Counter | agent_id / guardrail |
| `sessions_total` / `sessions_active` | Counter / Gauge | agent_id |
| `runtime_errors_total` | Counter | agent_id / error_type |

采集点：BEFORE_LLM / AFTER_LLM（token、延迟）、BEFORE_TOOL / AFTER_TOOL、
护栏各 Intercept 命中处（护栏事件回调）、SESSION_START / SESSION_END、ON_ERROR。

## 5. 追踪（调用链）

```text
request_id: req_xxx
  └─ span: gateway.chat（HTTP）
      └─ span: runtime.run
          ├─ span: guardrail.ratelimit / guardrail.budget
          ├─ span: llm.call（含 token / latency）
          ├─ span: tool.call
          └─ span: guardrail.critique
```

- span 生命周期：网关在请求入口创建根 span，runtime / 护栏经 `ctx.services["tracer"]`
  创建子 span（只读注入，不修改 runtime 核心）；
- 输出：`LoggingTraceExporter` 默认；可替换为 OpenTelemetry。

## 6. 结构化日志

统一字段（JSON Lines）：

```json
{"ts": "...", "level": "info", "logger": "src.runtime.loops._react",
 "request_id": "req_xxx", "session_id": "sess_x", "agent_id": "a1",
 "event": "llm_called", "model": "gpt-4o", "tokens": 123}
```

约束：
- 密钥 / 原始参数**永不落日志**（见 security-design.md）；
- 现有 `logger.warning(...)` 逐步迁移到统一格式化器，迁移期间保持兼容。

## 7. 实施顺序

| 步 | 内容 | 验收 |
|----|------|------|
| 1 | 公共底座：`_config` / `_protocols` / `_metrics`（InMemory） | 计数 / 直方图单测 |
| 2 | `_logging`：request_id 绑定 + JSON 格式化 | 日志字段单测 |
| 3 | `_tracing`：TraceSpan / Tracer / 默认导出 | span 树单测 |
| 4 | `_hooks` + `_plugin`：指标采集与追踪埋点 | 全链路集成测试 |
| 5 | 与护栏审计联动（同源采集） | 审计事件与指标一致性测试 |

每步完成即：全量测试通过、覆盖率 ≥96%、ruff 零报错、文档同步。

## 8. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 采集开销影响主流程 | 异步缓冲 + 采样率可配（`sample_rate`） |
| 指标爆炸（标签基数） | 标签白名单 + 基数上限校验 |
| 日志/追踪泄漏敏感信息 | 字段白名单 + 密钥拦截（security 联动） |
| 与审计重复实现 | §2 R1 同源采集、不同出口，职责固化 |

## 9. 待确认决策

| 编号 | 决策 | 推荐 |
|------|------|------|
| D1 | 包位置 | `src/observability/`（与 governance / gateway 同级） |
| D2 | 追踪协议 | 自研轻量 TraceSpan（推荐，零依赖）vs 直接 OpenTelemetry |
| D3 | 指标导出 | 内存 + 轮询拉取（推荐）vs Prometheus 直连 |

## 附录 A：文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/observability/*` | 新增 | 底座 / 指标 / 追踪 / 日志 / 插件 |
| `src/runtime/_background.py` | 新增（若 D3=A） | 公共异步任务组 |
| `tests/test_observability_*.py` | 新增 | 单元 + 集成 |

## 附录 B：修订记录

| 版本 | 日期 | 说明 |
|------|------|------|
| v0.1 | 2026-08-17 | 初稿 |