# 测试基础设施设计方案（v0.1）

> ⚠️ **本文档是 `agent-runtime-design.md` 的子文档**。阅读前请确保已理解主文档中的
> **Hook / Loop / 组件体系**。
>
> 关联文档：
> - [`api-surface-extension-sdk-design.md`](api-surface-extension-sdk-design.md) — 契约校验（assert_implements）
> - [`governance-component-design.md`](governance-component-design.md) — 组件验收标准（覆盖率 ≥96%）
> - [`examples-templates-design.md`](examples-templates-design.md) — E2E 参考工程

## 0. 背景与目标

当前测试已覆盖 96%，但全部是**手写 fixture**：每个测试文件各自构造
Mock LLM / 内存后端 / RuntimeContext，重复且易漂移。框架缺少：

- 统一测试夹具库（MockLLM / MockTool / 内存后端 / TestRuntimeBuilder）；
- 契约测试工具（协议实现是否完整满足，而非依赖鸭子类型偶然通过）；
- E2E 模板（会话 → 工具 → 护栏 → 审计全链路）；
- 基准测试（延迟 / 内存 / token 预算）。

本文档定义**测试基础设施设计方案**，把测试从"每个文件自造"升级为"框架级资产"。

## 1. 现状盘点

| 项 | 状态 |
|----|------|
| 覆盖率门槛（fail_under=96，branch） | ✅ 已配置并达标 |
| pytest-asyncio / pytest-cov | ✅ 已配置 |
| Mock LLM / Mock Tool | ⚠️ 各测试文件手写，重复 |
| 内存后端（SQLite :memory:） | ✅ 已有，可复用 |
| 契约测试工具 | ❌ 缺失 |
| E2E 模板 | ❌ 缺失 |
| 基准测试 | ❌ 缺失 |

## 2. 设计原则

### R1 测试夹具是公共资产

`tests/helpers/`（或 `src/testing/`）提供统一夹具，业务测试只关心场景，不关心基建。

### R2 三层测试

| 层 | 内容 | 依赖 |
|----|------|------|
| 单元 | 组件 / 协议 / Hook 行为 | 全部 Mock |
| 集成 | 组件间协作（Session → Memory → Context → 护栏） | 内存后端 |
| E2E | 全链路（网关 → runtime → 工具 → 护栏 → 审计） | 真实配置（Mock LLM 或桩） |

### R3 契约测试

对每个 `runtime_checkable` 协议，用 `assert_implements`（api-surface 设计）生成
契约用例：方法存在 + 签名兼容 + 边界行为。

### R4 基准可重复

基准测试固定：模型（Mock）、后端（内存）、seed，输出可对比基线。

## 3. 目录结构

```text
tests/helpers/
  __init__.py
  mocks.py               # MockLLM / MockTool / MockRateLimiter / MockAuditSink
  backends.py            # 内存后端工厂（SQLite :memory: / FakePersistence）
  builder.py             # TestRuntimeBuilder（一键构造带默认 Mock 的 runtime）
  contexts.py            # make_ctx / make_event 工厂
tests/contracts/
  test_protocol_contracts.py   # 各协议契约用例
tests/e2e/
  test_full_chain.py           # 会话 → 工具 → 护栏 → 审计全链路模板
tests/benchmarks/
  bench_react_loop.py          # 基准（pytest-benchmark 或自建计时）
```

## 4. 夹具规格

```python
# mocks.py
class MockLLM:
    """可编程 LLM：按调用次数返回预设 LLMResponse / 抛错 / 统计调用。"""

    def __init__(self, responses: list[LLMResponse] | None = None): ...
    async def execute(self, ctx) -> LLMResponse: ...

class MockTool:
    def __init__(self, result: Any = "ok"): ...
    async def __call__(self, ctx) -> Any: ...

# builder.py
class TestRuntimeBuilder:
    """构造带默认 Mock 的 runtime，测试只覆盖想覆盖的差异。"""

    def build(self, *, llm=None, tool=None, hooks=None, loop="react") -> AgentRuntime: ...
```

## 5. 实施顺序

| 步 | 内容 | 验收 |
|----|------|------|
| 1 | `tests/helpers/mocks.py` + `contexts.py` | 现有测试可迁移抽查 |
| 2 | `tests/helpers/builder.py`（TestRuntimeBuilder） | 新测试使用率 ≥50% |
| 3 | `tests/contracts/`（assert_implements 生成契约用例） | 协议实现全部通过 |
| 4 | `tests/e2e/test_full_chain.py` 模板 | 全链路可运行 |
| 5 | `tests/benchmarks/` | 基准可重复、有基线 |

每步完成即：全量测试通过、覆盖率 ≥96%、ruff 零报错、文档同步。

## 6. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 夹具过度抽象掩盖真实行为 | 夹具默认"最简真实"，复杂场景用参数覆盖 |
| 契约测试形同虚设 | 断言签名 + 边界 + 返回值类型 |
| 基准受环境波动 | 固定环境 / 多次取中位数 / 相对基线告警 |

## 7. 待确认决策

| 编号 | 决策 | 推荐 |
|------|------|------|
| D1 | 夹具位置 | `tests/helpers/`（推荐，不进入发布包）vs `src/testing/` |
| D2 | 基准工具 | pytest-benchmark（推荐，dev 依赖）vs 自建计时 |
| D3 | E2E LLM | 统一 MockLLM（推荐）vs 可选真实 Provider（标记 skip） |

## 附录 A：文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `tests/helpers/*` | 新增 | 夹具库 |
| `tests/contracts/*` | 新增 | 契约测试 |
| `tests/e2e/test_full_chain.py` | 新增 | E2E 模板 |
| `tests/benchmarks/*` | 新增 | 基准 |
| `pyproject.toml` | 修改（D2=A 时） | pytest-benchmark dev 依赖 |

## 附录 B：修订记录

| 版本 | 日期 | 说明 |
|------|------|------|
| v0.1 | 2026-08-17 | 初稿 |