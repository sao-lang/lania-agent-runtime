# Tool / MCP / Skill 三种原语集成方案

> ⚠️ **本文档是 `agent-runtime-design.md` 的子文档**。阅读前请确保已理解主文档中的 **Execute 原语**（§2）、**Tool Execute**（§7）和 **Tool guardrails**（§8 #23）。
>
> 关联文档：[`llm-executor-design.md`](llm-executor-design.md) — LLMExecutor 消费 Tool schema
> 主文档：[`agent-runtime-design.md`](agent-runtime-design.md) — §12 `PluggableComponent`（Tool/MCP/Skill 统一通过 `runtime.use()` 集成）

> 基于 agent-runtime-design.md 的五级原语体系，定义 Tool / MCP / Skill 三种能力原语的抽象、接口、数据流和集成方案。

---

## 编码规范

本文档涉及的所有代码实现必须遵循以下质量要求：

### 注释
- `ToolSpec`、`MCPServerConfig`、`MCPToolAdapter`、`SkillManager` 等核心类必须包含完整的**中文 docstring**
- MCP 协议适配逻辑、三种原语的路由规则必须添加行内中文注释

### 测试
- 完整的**单元测试**（ToolRegistry 注册/描述/执行、MCP 连接/断开/工具发现、Skill 扫描/匹配/注入）和**端到端测试**（ToolDispatcher 完整路由链路）
- 测试通过率：**100%**，覆盖率：**≥96%**（含分支覆盖）
- 对 MCP 连接失败、工具执行异常等错误路径编写专项测试

### Lint
- **flake8** 零报错 + **Pylance** strict 模式零报错 + `ruff` 格式检查通过

### 类型标注
- 禁止使用 `Any`；`ToolSpec.handler` 的类型应使用 `Callable[..., Awaitable[Any]]` 而非裸 `Any`
- `ToolDispatcher.dispatch()` 的输入输出类型必须精确标注

---

## 目录

1. [设计目标](#1-设计目标)
2. [三种原语定义](#2-三种原语定义)
3. [Tool 原语](#3-tool-原语)
4. [MCP 原语](#4-mcp-原语)
5. [Skill 原语](#5-skill-原语)
6. [统一调度器](#6-统一调度器)
7. [Runtime 集成方案](#7-runtime-集成方案)
8. [完整数据流](#8-完整数据流)
9. [使用示例](#9-使用示例)
10. [文件清单](#10-文件清单)

---

## 1. 设计目标

### 1.1 核心原则

| 原则 | 含义 |
|------|------|
| **原语平等** | Tool / MCP / Skill 是平级概念，各司其职，互不嵌套 |
| **职责分离** | Tool = 执行，MCP = 传输，Skill = 知识 |
| **LLM 透明** | LLM 只看到 flat tool list，不感知底层是哪种原语 |
| **生命周期独立** | 每种原语管理自己的初始化/清理，互不影响 |
| **渐进接入** | 可以只用 Tool，也可以逐步加 MCP 和 Skill |

### 1.2 三种原语在 Runtime 架构中的定位

```
Runtime 五级原语体系           Tool / MCP / Skill 映射
───────────────────────       ─────────────────────────
Execute (替换执行)              │─ ToolExecutor (本地函数执行)
                               │─ MCPBridge   (外部协议执行)
                               │
Transform (修改数据)            │─ SkillManager (知识注入 context_payload)
                               │
Observer / Intercept / Router  │  （不涉及）
```

---

## 2. 三种原语定义

| 维度 | **Tool** | **MCP** | **Skill** |
|------|----------|---------|-----------|
| **本质** | 本地函数 | 外部协议 | 知识包 |
| **Runtime 原语类型** | Execute | Execute | Transform |
| **挂载点** | `tool_executor` | `tool_executor` | `before_llm` |
| **输入** | `**kwargs` 参数字典 | `tool_name + args` | 用户 query 上下文 |
| **输出** | 任意 Python 对象 | MCP CallToolResult | 注入 `context_payload.injected_context` |
| **生命周期** | 无（随注册存在） | Server 级：connect → init → run → shutdown | 无（加载即存在） |
| **状态** | 无状态 | Server 可能有状态 | 无状态 |
| **LLM 感知** | `name` + `description` + `parameters` | `mcp_{server}_{tool_name}` | SKILL.md 内容 → system prompt |
| **典型场景** | calculator, weather, search | filesystem, database, docker | pr-review, sql-helper, meeting-summary |

### 2.1 分层关系

```
AgentRuntime
  │
  ├─ ToolRegistry ─────── Execute 原语 ──── 本地函数
  │     └─ calculator, get_weather, ...
  │
  ├─ MCPServerManager ─── Execute 原语 ──── 外部协议
  │     └─ mcp_fs_read_file, mcp_fs_list_dir, ...
  │
  └─ SkillManager ─────── Transform 原语 ── 知识注入
        └─ skills/pr-analysis/SKILL.md
        └─ skills/sql-helper/SKILL.md
```

---

## 3. Tool 原语

### 3.1 定位

**Execute 原语**。最简的函数调用抽象：name + schema + handler。

### 3.2 ToolSpec 定义

```python
@dataclass
class ToolSpec:
    """Tool 原语：本地函数工具。纯函数，无状态，进程内执行。"""
    name: str
    description: str
    parameters: dict[str, Any]          # JSON Schema
    handler: Callable[..., Awaitable[Any]]
    required: list[str] = field(default_factory=list)
    timeout: float = 30.0

    def to_openai_schema(self) -> dict:
        """转换为 OpenAI tools 参数格式。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.parameters,
                    "required": self.required,
                },
            },
        }
```

### 3.3 ToolRegistry

```python
class ToolRegistry:
    """本地工具注册中心。管理 ToolSpec 的注册、描述、分派。"""

    def register(self, spec: ToolSpec) -> None: ...
    def describe(self) -> list[dict]: ...
    async def execute(self, name: str, **kwargs: Any) -> Any: ...
```

设计要点：
- **覆盖注册**：同名工具后注册覆盖先注册，方便测试 mock
- **同步兼容**：`handler` 可以是普通 `Callable`，Registry 自动 `await`
- **无状态**：不维护调用计数、缓存等

---

## 4. MCP 原语

### 4.1 定位

**Execute 原语**。通过 Model Context Protocol 连接外部进程暴露的工具集。

MCP 不是一个工具，而是一组工具的服务发现和执行协议。

### 4.2 三层架构

```
MCPServerManager
  │
  ├─ MCPServerConfig     # 连接信息（stdio / sse）
  │
  ├─ MCPClient           # 协议客户端（传输、初始化、请求）
  │     ├─ StdioTransport   # 子进程 stdin/stdout
  │     └─ SSETransport     # HTTP SSE
  │
  └─ MCPToolAdapter[]    # 将 MCP tool → ToolSpec 的适配器
        ├─ mcp_fs_read_file
        ├─ mcp_fs_list_dir
        └─ mcp_fs_write_file
```

### 4.3 MCPServerConfig

```python
@dataclass
class MCPServerConfig:
    """MCP Server 连接配置。"""
    name: str                              # server 标识（也用于 tool 名前缀）
    transport: str                         # "stdio" | "sse"
    command: str = ""                      # stdio: 启动命令
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str = ""                          # sse: 端点 URL
    auto_connect: bool = True              # Runtime 启动时自动连接
```

### 4.4 MCPToolAdapter（核心适配逻辑）

```python
class MCPToolAdapter:
    """
    将 MCP Server 的一个 tool 适配为 ToolSpec。

    name 格式: mcp_{server_name}_{tool_name}
    保证全局唯一，方便 LLM 区分工具来源。
    """

    @property
    def tool_spec(self) -> ToolSpec:
        return ToolSpec(
            name=f"mcp_{self._server_name}_{self._tool_name}",
            description=f"[MCP:{self._server_name}] {self._mcp_description}",
            parameters=self._mcp_input_schema,
            handler=self._execute,
            timeout=self._timeout,
        )

    async def _execute(self, **kwargs: Any) -> Any:
        """通过 MCP client 远程调用。"""
        result = await self._client.call_tool(self._tool_name, kwargs)
        return self._parse_result(result)
```

### 4.5 MCPServerManager（生命周期管理）

```python
class MCPServerManager:
    """
    MCP Server 生命周期管理器。

    职责:
      - connect(): 启动子进程/连接 SSE → 初始化 → 发现工具 → 返回 ToolSpec[]
      - disconnect() / disconnect_all(): 清理
      - health_check: 可选心跳
    """

    async def connect(self, config: MCPServerConfig) -> list[ToolSpec]:
        """连接 MCP Server，返回其暴露的所有工具（已适配为 ToolSpec）。"""
        ...

    async def disconnect(self, name: str) -> None: ...
    async def disconnect_all(self) -> None: ...

    def get_all_tools(self) -> list[ToolSpec]:
        """获取所有已连接 Server 的工具。"""
        ...
```

设计要点：
- **前缀路由**：所有 MCP 工具名前缀 `mcp_`，`ToolDispatcher` 据此路由
- **连接失败不崩溃**：connect 失败只记日志，不影响 Runtime 启动
- **按需重连**：可选（默认不自动重连，返回错误）

---

## 5. Skill 原语

### 5.1 定位

**Transform 原语**。不是执行单元，是 **LLM 知识注入单元**。

Skill 的本质是 `<skill-dir>/SKILL.md` 文件 + 可选的 `skill.toml` 元信息。它不注册 tool，不产生 tool_calls，而是在 `before_llm` 阶段将领域知识注入 `context_payload`。

### 5.2 Skill 目录结构

```
skills/
  pr-analysis/                     ← Skill 目录
    SKILL.md                       # 领域知识（核心）
    skill.toml                     # 元信息：名称、触发关键词、优先级
    prompts/
      review.j2                    # 内部 prompt 模板（可选）
  sql-helper/
    SKILL.md
    skill.toml
```

### 5.3 SKILL.md 示例

```markdown
# PR Analysis Skill

You are an expert code reviewer. When analyzing a pull request:

1. Review changed files one by one
2. Check for: logic errors, security issues, performance problems
3. Suggest concrete improvements with code examples
4. Use `mcp_github_get_pr_files` and `mcp_github_post_comment` tools

Always output in this format:
## Summary
## Files Reviewed
## Issues Found
## Suggestions
```

### 5.4 skill.toml

```toml
[skill]
name = "pr-analysis"
description = "Expert PR code review with file-level analysis"
keywords = ["pr", "pull request", "review", "code review"]
priority = 5              # 匹配分数 > 5 时注入
auto_inject = false       # 是否无条件注入（忽略匹配）
```

### 5.5 SkillManager

```python
class SkillManager:
    """
    Skill 管理器。在 before_llm 阶段注入领域知识。

    职责:
      - scan(skill_dirs): 扫描目录加载 SKILL.md
      - before_llm Transform hook: 根据上下文匹配 skill，注入 knowledge
    """

    def __init__(self) -> None:
        self._skills: list[SkillEntry] = []

    def scan(self, skill_dirs: list[str]) -> None:
        """扫描目录，加载 SKILL.md + skill.toml。"""
        ...

    def get_before_llm_hook(self) -> Transformer:
        """返回一个 Transform hook：匹配 → 注入 context_payload。"""
        async def hook(data: dict, ctx: RuntimeContext) -> dict:
            user_msg = self._get_last_user_message(ctx)
            for skill in self._skills:
                score = self._match(skill, user_msg, ctx)
                if score >= skill.priority:
                    content = self._load_skill_md(skill.path)
                    ctx.context_payload.injected_context.append(
                        f"## {skill.name}\n{content}"
                    )
            return data
        return hook
```

### 5.6 匹配策略

| 策略 | 分数规则 | 适用场景 |
|------|---------|---------|
| 关键词匹配 | 命中 1 个关键词得 5 分，累加。`score ≥ priority` 时注入 | 简单规则 |
| 语义匹配 | embedding 余弦相似度 × 10。`score ≥ priority` 时注入 | 精确匹配 |
| auto_inject | `score = 999`，始终注入（如 system-level skill） | 全局知识 |
| LLM 路由 | LLM 自行判断，`score = priority`（由 LLM 调用触发） | 灵活但昂贵 |

设计要点：
- **Transform 不是 Execute**：Skill 不改执行路径，只改 LLM 看到的上下文
- **不注册 tool**：Skill 通过 SKILL.md 引导 LLM 去调已有的 Tool/MCP
- **轻量**：Skill 就是一个 Markdown 文件 + 可选的 toml 元信息

---

## 6. 统一调度器

### 6.1 ToolDispatcher

```python
class ToolDispatcher:
    """
    三种原语的统一调度入口。

    LLM 调用 tool 时，按 name 前缀路由到不同后端。
    """

    def __init__(
        self,
        tool_registry: ToolRegistry,
        mcp_manager: MCPServerManager,
    ) -> None: ...

    def all_tools(self) -> list[dict]:
        """
        合并 Tool + MCP 的全部工具描述。

        注意：此方法返回 ToolSpec 列表而非 OpenAI 格式。
        LLMExecutor 负责在 _get_tools_schema() 中将其转换为 provider 所需格式
        （OpenAI tools 格式 / Anthropic tool 格式等）。
        参见 llm-executor-design.md §4.1 _get_tools_schema()。
        """
        return [*self._tools.list_specs(), *self._mcp.get_all_tools()]

    async def dispatch(self, tool_call: dict, ctx: RuntimeContext) -> dict:
        """
        统一分派。
        路由规则:
          - "mcp_{server}_{tool}" → MCPServerManager
          - 其他                   → ToolRegistry

        异常处理：工具执行异常**不在此捕获**，而是向上传播给 Runtime，
        触发 on_error hook 链（Error Intercept 可做 retry/skip/degrade 决策）。
        参见 agent-runtime-design.md §7 on_error 流程。
        """
        name = tool_call.get("name", "")
        args = tool_call.get("arguments", {})

        if name.startswith("mcp_"):
            result = await self._dispatch_mcp(name, args)
        else:
            result = await self._tools.execute(name, **args)
        return {"result": result}
```

### 6.2 Skill 不经过 Dispatcher

Skill 是 Transform 原语，注册在 `before_llm` hook，不走 `dispatch()`。

```
输入流：
  user query
    │
    ▼
  before_llm Transform hooks
    ├─ SkillManager.match_and_inject()   ← Skill 进入 context
    │
    ▼
  LLM （看到注入的 SKILL.md 知识）
    │
    ▼
  LLMResponse.tool_calls = [...]         ← Tool / MCP
    │
    ▼
  ToolDispatcher.dispatch()
    ├─ name.startswith("mcp_") → MCP
    └─ else                     → Tool
```

---

## 7. Runtime 集成方案

### 7.1 AgentRuntime 构造接口

```python
class AgentRuntime:
    def __init__(
        self,
        # ... 现有参数 ...
        tools: ToolRegistry | None = None,
        mcp: MCPServerManager | None = None,
        skills: SkillManager | None = None,
    ) -> None:
        ...
```

### 7.2 __init__ 内部自动注入

```python
class AgentRuntime:
    def __init__(self, ..., tools=None, mcp=None, skills=None):
        ...

        # 1. 创建统一调度器
        self._dispatcher = ToolDispatcher(
            tool_registry=tools or ToolRegistry(),
            mcp_manager=mcp or MCPServerManager(),
        )

        # 2. 注入 tool_executor Execute 原语
        self._hooks.set_tool_executor(self._dispatcher.dispatch)

        # 3. 注入 before_llm Transform hook（自动刷新 tools_schema）
        self._hooks.transform(BEFORE_LLM, self._inject_tools_schema, "tools_schema")

        # 4. 注入 Skill 知识
        if skills:
            self._hooks.transform(BEFORE_LLM, skills.get_before_llm_hook(), "skill_inject")

        # 5. 自动连接 MCP
        self._pending_mcp: list[MCPServerConfig] = []
```

### 7.3 自动 schema 刷新

```python
async def _inject_tools_schema(self, data: dict, ctx: RuntimeContext) -> dict:
    """每次 before_llm 时刷新 tools_schema。"""
    ctx.set_tools_schema(self._dispatcher.all_tools())
    return data
```

---

## 8. 完整数据流

```
用户: "审查这个 PR，计算改动行数"
  │
  ▼
before_step hooks
  │
  ▼
before_llm:
  1. SkillManager.match("pr-analysis") → 命中，注入 SKILL.md
  2. _inject_tools_schema → 合并 Tool + MCP schema
  3. context_payload.serialize → 生成 system message
  │
  ▼
LLMExecutor.execute(ctx)
  ├─ system: [SKILL.md 知识 + 工具列表]
  ├─ user: "审查这个 PR..."
  │
  ▼
LLMResponse:
  content: "我来分析这个 PR..."
  tool_calls: [
    {name: "mcp_github_get_pr_files", args: {pr: "42"}},
    {name: "calculator", args: {expression: "23 + 15"}},
  ]
  │
  ▼
ToolDispatcher.dispatch():
  ├─ "mcp_github_get_pr_files" → MCPServerManager → MCPClient → 远程执行
  ├─ "calculator" → ToolRegistry → calc_handler(**args)
  │
  ▼
  after_tool hooks → 追加 tool 结果
  │
  ▼
  第二轮 LLM（如有更多 tool_calls）或 返回最终回复
```

---

## 9. 使用示例

### 9.1 最简模式：只用 Tool

```python
registry = ToolRegistry()
registry.register(ToolSpec(name="calc", handler=calc_handler, ...))

runtime = AgentRuntime(tools=registry)
```

### 9.2 标准模式：Tool + MCP

```python
registry = ToolRegistry()
registry.register(ToolSpec(name="get_weather", handler=weather_handler, ...))

mcp = MCPServerManager()
await mcp.connect(MCPServerConfig(
    name="fs",
    transport="stdio",
    command="npx",
    args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
))

runtime = AgentRuntime(tools=registry, mcp=mcp)
```

### 9.3 完整模式：Tool + MCP + Skill

```python
registry = ToolRegistry()
registry.register(ToolSpec(name="calculator", handler=calc_handler, ...))

mcp = MCPServerManager()
await mcp.connect(MCPServerConfig(name="fs", ...))

skills = SkillManager()
skills.scan(["skills/pr-analysis", "skills/sql-helper"])

runtime = AgentRuntime(tools=registry, mcp=mcp, skills=skills)
```

---

## 10. 文件清单

```
src/
├── tools/                          # 统一工具目录（Tool + MCP + Skill）
│   ├── __init__.py                 # 导出 ToolRegistry, MCPServerManager, SkillManager
│   ├── _registry.py                # ToolRegistry
│   ├── _dispatcher.py              # ToolDispatcher（统一调度）
│   ├── _spec.py                    # ToolSpec
│   ├── _mcp/
│   │   ├── __init__.py
│   │   ├── _config.py              # MCPServerConfig
│   │   ├── _client.py              # MCPClient (stdio/sse 传输)
│   │   ├── _adapter.py             # MCPToolAdapter
│   │   └── _manager.py             # MCPServerManager
│   └── _skill/
│       ├── __init__.py
│       ├── _manager.py             # SkillManager (扫描 + 注入)
│       └── _models.py              # SkillEntry, SkillConfig
│
└── todo: 改为通过 runtime.use() 集成，不再直接修改 runtime.py
```

各文件依赖关系：

```
ToolDispatcher
  ├─ ToolRegistry     (tool/registry.py)
  │   └─ ToolSpec     (tool/base.py)
  └─ MCPServerManager (mcp/manager.py)
       ├─ MCPClient   (mcp/client.py)
       └─ MCPToolAdapter (mcp/adapter.py)
           └─ ToolSpec

SkillManager 独立，只依赖 RuntimeContext
  └─ 挂载到 before_llm Transform
```

---

## 附录

### A. 为什么不把 Skill 放到 Dispatcher 里？

Skill 的本质是 **知识注入（Transform）**，不是 **执行（Execute）**。如果放到 Dispatcher 里：

1. LLM 需要为 skill 产生 tool_call → 但 skill 不需要执行函数
2. Skill 的 SKILL.md 已经在 system prompt 里了，再调一次 tool_call 是冗余
3. Skill 需要在 LLM 决策之前就影响上下文，而不是 LLM 决策之后才被调用

### B. MCP 连接失败的处理策略

| 策略 | 行为 | 适用场景 |
|------|------|---------|
| fail-fast | Runtime 启动失败 | 核心服务，不可降级 |
| graceful | 记录日志，跳过该 server | 可选服务 |
| lazy-connect | 首次有 tool_call 匹配时才尝试连接 | 按需连接 |

默认采用 **graceful** 策略。

### C. Skill 匹配性能

Skill 匹配发生在每次 `before_llm`。大量 skill（>20 个）时建议：
1. 使用 embedding 预计算 + 向量检索代替关键词轮询
2. 对每个 skill 设置 `priority` 阈值，低分跳过
3. 启用 `auto_inject` 的 skill 直接注入，不参与匹配
