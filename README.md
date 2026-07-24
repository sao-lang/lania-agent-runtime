# Lania Agent Runtime

一个**以治理为核心**的 Agent 运行时框架。核心设计理念：

- **Runtime 是纯壳** —— 不感知任何具体组件，所有功能通过 Hook 插拔
- **Hook 管治理逻辑** —— 12 个挂载点 × 5 种原语类型，无状态纯函数
- **状态分层持有** —— Runtime 持有执行状态，外部服务持有持久化状态，互不越界

> 所有扩展（LLM、工具、记忆、上下文管理）都是**用户侧注册**的 Hook。
> `RuntimeBuilder` 提供快捷方式自动完成接线，但 `AgentRuntime` 本身
> 不依赖任何外部组件包。

适用于需要精细管控 LLM 调用、工具执行、审计追踪、人工审批的企业级 Agent 应用。

---

## 🧰 技术栈

| 工具 | 用途 |
|------|------|
| **Python ≥3.10** | 运行语言 |
| **Pydantic** | 运行时核心：所有数据模型（RuntimeContext / ContextPayload / LLMResponse 等）基于 `@dataclass` + `Protocol` 定义，工具参数校验使用 Pydantic 模型 |
| **uv** | 项目管理：依赖安装、虚拟环境、`uv.lock` 锁定、`pyproject.toml` 构建（hatchling 后端） |
| **ruff** | 代码检查与格式化：替代 flake8 + isort + black，`pyproject.toml` 中配置了完整的规则集（E/F/I/W/N/ANN） |
| **pytest** | 测试框架：`asyncio_mode=auto`，覆盖率目标 ≥96% |
| 不限 | LLM Provider 可替换（当前内置 OpenAI 适配器，可通过 `LLMProvider` 接口接入任意 Provider） |

---

## 🌟 快速开始

### 安装

```bash
# 推荐：使用 uv（安装所有依赖，含 dev 组）
uv sync --group dev

# 或使用 pip
pip install -e "."
```

### 模式 A：纯手动，完全解耦（~20 行）

Runtime 是纯壳，所有功能通过 Hook 插拔：

```python
import asyncio
from src.runtime import AgentRuntime
from src.runtime._types import HookPoint, PrimitiveType
from src.runtime.llm import OpenAILLMExecutor, LLMExecutorConfig

async def main():
    # 1. 创建 Runtime（纯壳）
    agent = AgentRuntime(system_prompt="你是电商客服助手，回答简洁友好。")

    # 2. 用户组装 LLM
    executor = OpenAILLMExecutor(LLMExecutorConfig(model="gpt-4o", api_key="sk-..."))

    # 3. 用户自己接线——替换 step_runner 的 llm_executor
    agent.set_llm_executor(executor)

    # 4. 用户注册治理 Hook
    @agent.on(HookPoint.AFTER_LLM)
    async def log_usage(event, ctx):
        print(f"token 用量: {event.get('response', {}).usage.total_tokens}")

    result = await agent.run("帮我查一下订单")
    print(result.content)

asyncio.run(main())
```

### 模式 B：Builder 快捷（~10 行）

`RuntimeBuilder` 在 `build()` 内部自动完成接线：

```python
from src.runtime import AgentRuntime

agent = (
    AgentRuntime.builder()
    .system_prompt("你是电商客服助手，回答简洁友好。")
    .llm(model="gpt-4o", api_key="sk-...")
    .build()
)
# ↑ build() 内部自动创建 OpenAILLMExecutor 并 set_llm_executor
result = await agent.run("查订单")
```

---

## 🚀 使用模式

### 模式 C：加工具（Builder 快捷）

```python
import asyncio
from src.runtime import AgentRuntime
from src.tools import ToolRegistry, ToolSpec

async def query_order(order_id: str) -> dict:
    return {"status": "已发货", "express": "顺丰 SF123456"}

async def get_user_info(user_id: str) -> dict:
    return {"name": "张三", "level": "VIP"}

registry = ToolRegistry()
registry.register(ToolSpec(
    name="query_order", description="查询订单状态",
    parameters={"order_id": {"type": "string"}},
    handler=query_order, required=["order_id"],
))
registry.register(ToolSpec(
    name="get_user_info", description="获取用户信息",
    parameters={"user_id": {"type": "string"}},
    handler=get_user_info, required=["user_id"],
))

async def main():
    agent = (
        AgentRuntime.builder()
        .system_prompt("你是电商客服助手。")
        .llm(model="gpt-4o", api_key="sk-...")
        .tool_registry(registry)  # ← Builder 帮你接线
        .build()
    )
    result = await agent.run("帮我查一下订单 OD20240723001 的状态")
    print(result.content)

asyncio.run(main())
```

> 💡 `build()` 内部自动创建 `ToolDispatcher` 并注册 `before_llm` Transform 刷新 tools_schema。

### 模式 D：加治理（~50 行）

```python
import asyncio
from src.runtime import AgentRuntime
from src.runtime._types import HookPoint, PrimitiveType, BlockAction, AllowAction
from src.runtime.llm import OpenAILLMExecutor, LLMExecutorConfig

async def main():
    executor = OpenAILLMExecutor(LLMExecutorConfig(model="gpt-4o", api_key="sk-..."))
    agent = AgentRuntime(
        system_prompt="你是金融客服助手。",
        llm_executor=executor,
    )

    # 自定义观察者（@runtime.on 装饰器）
    @agent.on(HookPoint.AFTER_LLM)
    async def log_response(event, ctx):
        print(f"LLM 回复: {event.get('response','')[:100]}...")

    # 自定义拦截器
    @agent.on(HookPoint.BEFORE_TOOL, primitive=PrimitiveType.INTERCEPT)
    async def check_sensitive_params(data, ctx):
        if "bank_account" in str(data):
            return BlockAction(reason="禁止传递敏感参数")
        return AllowAction()

    # 或者用非装饰器方式
    # agent.observe(HookPoint.AFTER_LLM, log_response, name="log_response")
    # agent.intercept(HookPoint.BEFORE_TOOL, check_sensitive_params, name="check_params")

    # 插件注册（需要 async 上下文）
    # await agent.use(SomePlugin())

    result = await agent.run("把1000元转到银行卡8888")
    print(result.content)

asyncio.run(main())
```

> ⚠️ `HumanApprovalPlugin`、`BudgetPlugin`、`AuditPlugin` 等治理插件尚在规划中。
> 当前可用的治理组件：`HumanApprovalInterceptor`、`SelfCritiqueHook`、`DualModelCritiqueHook`、`ReplanHook`。

### 模式 E：完全自定义（100+ 行）

```python
from src.runtime import AgentRuntime
from src.runtime.loops import PlanExecuteLoop
from src.runtime.llm import OpenAILLMExecutor, LLMExecutorConfig, LLMResponse, LLMUsage, FinishReason
from src.runtime.hooks import HookRegistry, PrimitiveType, HookPoint

# 自定义 LLM 执行器
class MyCustomExecutor(OpenAILLMExecutor):
    async def execute(self, ctx):
        response = await super().execute(ctx)
        response.content = self._post_process(response.content)
        return response

    def _post_process(self, content: str) -> str:
        return content.replace("\n\n", "\n")

# 自定义 Router
async def my_router(ctx):
    if ctx.budget.token_used > 50_000:
        return "summarize_step"
    return "llm"

# 自定义 Hook
async def my_threat_scanner(data, ctx):
    from src.runtime._types import AllowAction
    return AllowAction()

# 纯手动注册——Runtime 不感知任何组件
runtime = AgentRuntime(system_prompt="你是助手。")
runtime.set_llm_executor(MyCustomExecutor(LLMExecutorConfig(model="gpt-4o", api_key="sk-...")))
runtime.set_router(my_router)
runtime.intercept(HookPoint.BEFORE_LLM, my_threat_scanner, name="threat_scanner")
```

---

## 🧩 核心概念

| 概念 | 说明 |
|------|------|
| **Hook Point** | Runtime 执行流程中的 12 个挂载点（session_start → session_end → on_stream_chunk） |
| **Primitive** | 5 种原语类型：Observe / Transform / Intercept / Router / Execute |
| **ContextPayload** | 上下文中间层，Hook 操作此对象，Runtime 序列化为 LLM messages |
| **RuntimeContext** | Hook 看到的只读快照 + 受限写接口 |
| **HookRegistry** | 分层编排引擎：Transform 串行 → Intercept 短路 → Observer 并行 |
| **插拔设计** | Runtime 是纯壳，不感知 LLM/工具/记忆等具体组件。`RuntimeBuilder` 提供快捷接线，用户也可手动注册任意 Hook |

详细设计文档见 [`docs/design/agent-runtime-design.md`](docs/design/agent-runtime-design.md)。

---

## 🧩 扩展生态

所有扩展通过 Hook 机制插拔，Runtime 不感知具体组件。

### Memory（记忆系统）

```python
from src.runtime import AgentRuntime
from src.runtime._types import HookPoint
from src.memory import MemoryService
from src.memory._backends._sqlite import SQLitePersistence
from src.memory._hooks import MemoryCommitHook
from src.context import ContextConfig
from src.context._manager import ContextManager
from src.context.context_hooks import ContextAssemblerHook

# 方式 A：手动接线（完全解耦）
persistence = SQLitePersistence("./memory.db")
memory = MemoryService(persistence=persistence)
ctx_mgr = ContextManager(memory=memory)          # ContextManager 依赖 MemoryRecallProtocol

runtime = AgentRuntime(system_prompt="你是助手")
runtime.set_llm_executor(my_executor)
runtime.transform(HookPoint.BEFORE_LLM, ContextAssemblerHook(ctx_mgr))
runtime.transform(HookPoint.AFTER_STEP, MemoryCommitHook(memory))  # 依赖 MemoryCommitProtocol

# 方式 B：Builder 快捷——memory 和 context 是分开的 API
runtime = (AgentRuntime.builder()
    .system_prompt("你是助手")
    .llm(executor=my_executor)
    .memory(MemoryService(persistence=SQLitePersistence("./memory.db")))  # 数据层
    .context(config=ContextConfig(compression_level=4))                   # 编排层（可选）
    .build())
```

记忆系统包含 5 层：工作记忆（崩溃恢复）、情景记忆（对话历史）、实体记忆（用户画像）、语义知识（概念图谱）、行为模式（风格偏好）。

详情见 [`docs/design/memory-system-design.md`](docs/design/memory-system-design.md) 和 [`docs/design/context-management-redesign.md`](docs/design/context-management-redesign.md)。

### Guardrails（治理组件，规划中）

| 组件 | 说明 |
|------|------|
| 预算控制 | Token/步数/费用上限 |
| 人工审批 | 敏感操作前暂停等待确认 |
| 限流 | 单位时间调用次数限制 |

### Anthropic Provider

Anthropic Claude Provider 适配器（可通过 `LLMProvider` 接口接入）。

### MCP

Model Context Protocol 工具协议，已在 `src/tools/_mcp/` 中实现基础骨架。

### Skill

Skill 预置能力加载，已在 `src/tools/_skill/` 中实现。

> 以上扩展均通过 Hook 注册到 Runtime，`AgentRuntime` 本身不依赖任何扩展包。

---

## 🛠 开发

```bash
# 使用 uv 创建虚拟环境并安装（含 dev 依赖）
uv venv
uv sync --group dev

# 运行测试（覆盖率 ≥96%）
pytest --cov=src --cov-branch --cov-fail-under=96

# 代码检查（ruff + flake8 规则，零报错）
ruff check src/ --strict

# 类型检查（Pylance strict 模式，零报错）
# 在 VS Code 中启用 "python.analysis.typeCheckingMode": "strict"

# 构建
uv build
```

---

## 📄 许可证

MIT
