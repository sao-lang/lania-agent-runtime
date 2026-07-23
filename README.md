# Lania Agent Runtime

一个**以治理为核心**的 Agent 运行时框架。核心设计理念：

- **Runtime 管执行闭环** —— 状态机 + Step Loop，最小必要状态
- **Hook 管治理逻辑** —— 12 个挂载点 × 5 种原语类型，无状态纯函数
- **状态分层持有** —— Runtime 持有执行状态，外部服务持有持久化状态，互不越界

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
# 推荐：使用 uv
uv pip install lania-agent-runtime

# 或使用 pip
pip install lania-agent-runtime
```

### 模式 A：开箱即用（~15 行）

```python
import asyncio
from src.runtime import AgentRuntime
from src.runtime.llm import OpenAILLMExecutor, LLMExecutorConfig

async def main():
    executor = OpenAILLMExecutor(LLMExecutorConfig(
        model="gpt-4o",
        api_key="sk-...",
    ))

    agent = AgentRuntime(
        system_prompt="你是电商客服助手，回答简洁友好。",
        llm_executor=executor,
    )

    result = await agent.run("帮我查一下订单 OD20240723001 的状态")
    print(result.content)

asyncio.run(main())
```

> 💡 也可以通过 `RuntimeBuilder` 链式构造：
>
> ```python
> from src.runtime import AgentRuntime
>
> agent = (
>     AgentRuntime.builder()
>     .system_prompt("你是电商客服助手，回答简洁友好。")
>     .llm(model="gpt-4o", api_key="sk-...")
>     .build()
> )
> # 注：builder 自动创建 OpenAILLMExecutor（需环境变量中有 api_key）
> result = await agent.run("查订单")
> ```

---

## 🚀 使用模式

### 模式 B：加工具（~30 行）

```python
import asyncio
from src.runtime import AgentRuntime
from src.runtime.llm import OpenAILLMExecutor, LLMExecutorConfig
from src.tools import ToolRegistry, ToolSpec

async def query_order(order_id: str) -> dict:
    return {"status": "已发货", "express": "顺丰 SF123456"}

async def get_user_info(user_id: str) -> dict:
    return {"name": "张三", "level": "VIP"}

# 注册工具
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
    executor = OpenAILLMExecutor(LLMExecutorConfig(model="gpt-4o", api_key="sk-..."))
    agent = AgentRuntime(
        system_prompt="你是电商客服助手。",
        llm_executor=executor,
        tools=registry,  # ← 传入 ToolRegistry，自动注册工具调度
    )
    result = await agent.run("帮我查一下订单 OD20240723001 的状态")
    print(result.content)

asyncio.run(main())
```

> 💡 传入 `tools` 参数后，Runtime 会自动创建 `ToolDispatcher` 并设为 `tool_executor`，
> 同时注册 `before_llm` Transform 自动刷新 tools_schema。

### 模式 C：加治理（~50 行）

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

### 模式 D：完全自定义（100+ 行）

```python
from src.runtime import AgentRuntime
from src.runtime.loops import PlanExecuteLoop
from src.runtime.llm import OpenAILLMExecutor, LLMExecutorConfig, LLMResponse, LLMUsage, FinishReason
from src.runtime.hooks import HookRegistry, PrimitiveType, HookPoint

# 自定义 LLM 执行器
class MyCustomExecutor(OpenAILLMExecutor):
    async def execute(self, ctx):
        response = await super().execute(ctx)
        # 后处理
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

registry = HookRegistry()
registry.register(
    HookPoint.BEFORE_LLM, my_threat_scanner,
    primitive=PrimitiveType.INTERCEPT,
)

runtime = AgentRuntime(
    hooks=registry,
    llm_executor=MyCustomExecutor(LLMExecutorConfig(model="gpt-4o", api_key="sk-...")),
    router=my_router,
)
# 注：LoopStrategy 通过 loop_strategy_name 参数或 LoopStrategyFactory 设置
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

详细设计文档见 [`docs/design/agent-runtime-design.md`](docs/design/agent-runtime-design.md)。

---

## 🧩 扩展生态（规划中）

| 扩展 | 说明 |
|------|------|
| Memory | 5 层记忆系统（工作记忆/情景/实体/语义/行为模式） |
| Guardrails | 治理组件（预算控制、人工审批、限流） |
| Anthropic Provider | Anthropic Claude Provider 适配器 |
| MCP | Model Context Protocol 工具协议 |
| Skill | Skill 预置能力加载 |

> 以上扩展处于规划阶段，核心骨架已预留扩展点（`PluggableComponent` / `Plugin` 协议）。

---

## 🛠 开发

```bash
# 使用 uv 创建虚拟环境并安装
uv venv
uv pip install -e ".[dev]"

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
