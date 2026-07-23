# Lania Agent Runtime

一个**以治理为核心**的 Agent 运行时框架。核心设计理念：

- **Runtime 管执行闭环** —— 状态机 + Step Loop，最小必要状态
- **Hook 管治理逻辑** —— 9 个挂载点 × 5 种原语类型，无状态纯函数
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

### 模式 A：开箱即用（~10 行）

```python
from lania_agent_runtime import AgentRuntime

agent = AgentRuntime(
    system_prompt="你是电商客服助手，回答简洁友好。",
    llm_config={"model": "gpt-4o", "api_key": "sk-..."},
)

response = agent.run("帮我查一下订单 OD20240723001 的状态")
print(response)
```

---

## 🚀 使用模式

### 模式 B：加工具（~30 行）

```python
from lania_agent_runtime import AgentRuntime

agent = AgentRuntime(
    system_prompt="你是电商客服助手。",
    llm_config={"model": "gpt-4o"},
)

@agent.tool(name="query_order", description="查询订单状态")
async def query_order(order_id: str) -> dict:
    # 实际业务逻辑
    return {"status": "已发货", "express": "顺丰 SF123456"}

@agent.tool(name="get_user_info", description="获取用户信息")
async def get_user_info(user_id: str) -> dict:
    return {"name": "张三", "level": "VIP"}

response = await agent.run_async("帮我查一下订单 OD20240723001 的状态")
print(response)
```

### 模式 C：加治理（~50 行）

```python
from lania_agent_runtime import AgentRuntime
from lania_agent_runtime.extensions import HumanApprovalPlugin, BudgetPlugin, AuditPlugin

agent = AgentRuntime(
    system_prompt="你是金融客服助手。",
    llm_config={"model": "gpt-4o"},
)

# 插件式治理
agent.use(HumanApprovalPlugin(
    require_for_tools=["transfer_money", "modify_order"],
    approval_mode="console",   # 也支持 "api"、"webhook"
))

agent.use(BudgetPlugin(
    max_steps=20,
    max_tokens=100_000,
    on_exceed="pause",         # 超限时可 "pause" / "warn" / "stop"
))

agent.use(AuditPlugin(
    storage="sqlite:///audit.db",
    include=["llm_calls", "tool_calls", "errors"],
))

# 自定义观察者
@agent.observe(point="after_llm")
async def log_response(response, ctx):
    logger.info(f"LLM 回复: {response.content[:100]}...")

# 自定义拦截器
@agent.intercept(point="before_tool")
async def check_sensitive_params(tool_call, ctx):
    if "bank_account" in str(tool_call.arguments):
        return BlockAction(reason="禁止传递敏感参数")
    return AllowAction()

response = agent.run("把1000元转到银行卡8888")
# → 触发 HumanApproval pause → 等待审批 → 继续
```

### 模式 D：完全自定义（100+ 行）

```python
from lania_agent_runtime import AgentRuntime
from lania_agent_runtime.loop import PlanExecuteLoop
from lania_agent_runtime.llm import OpenAIExecutor
from lania_agent_runtime.hooks import HookRegistry, PrimitiveType, HookPoint

# 自定义 LLM 执行器
class MyCustomExecutor(OpenAIExecutor):
    async def execute(self, ctx):
        response = await super().execute(ctx)
        response.content = self._post_process(response.content)
        return response

# 自定义 Router
async def my_router(ctx):
    if ctx.budget.token_used > 50_000:
        return "summarize_step"
    return ctx.plan.next_step()

# 自定义 Hook
registry = HookRegistry()
registry.register(
    HookPoint.BEFORE_LLM, my_threat_scanner,
    primitive=PrimitiveType.INTERCEPT,
)

runtime = AgentRuntime(
    hooks=registry,
    loop=PlanExecuteLoop(),
    llm_executor=MyCustomExecutor(model="gpt-4o"),
    router=my_router,
)
```

---

## 🧩 核心概念

| 概念 | 说明 |
|------|------|
| **Hook Point** | Runtime 执行流程中的 10 个挂载点（session_start → session_end） |
| **Primitive** | 5 种原语类型：Observe / Transform / Intercept / Router / Execute |
| **ContextPayload** | 上下文中间层，Hook 操作此对象，Runtime 序列化为 LLM messages |
| **RuntimeContext** | Hook 看到的只读快照 + 受限写接口 |
| **HookRegistry** | 分层编排引擎：Transform 串行 → Intercept 短路 → Observer 并行 |

详细设计文档见 [`docs/design/agent-runtime-design.md`](docs/design/agent-runtime-design.md)。

---

## 📦 扩展生态

| 扩展包 | 说明 |
|--------|------|
| `lania-agent-runtime[memory]` | 5 层记忆系统（工作记忆/情景/实体/语义/行为模式） |
| `lania-agent-runtime[guardrails]` | 治理组件（预算控制、人工审批、限流） |
| `lania-agent-runtime[anthropic]` | Anthropic Claude Provider 适配器 |
| `lania-agent-runtime[all]` | 全量安装 |

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
