# Observer 与原始类型重构方案

> ⚠️ **本文档已被 [`agent-runtime-design.md`](agent-runtime-design.md) §6 取代。**
>
> 本文的核心思想（Observer 从控制层分离、Transform 串行 + Observer 并行）已并入主文档：
> - **Observer 隔离执行** → 主文档 §6.3 `run_observers()` 并发 + 错误隔离
> - **Transform 串行管线** → 主文档 §6.3 `run_transformers()` 串行执行
> - **PrimitiveType 保留 5 种原语**（含 OBSERVER）→ 主文档 §6.1
> - **Router/Executor 归属 AgentRuntime** → 主文档 §6.3
>
> **本文档保留仅作设计思路追溯，不应用于指导编码。**
> 编码实现请以主文档 [`agent-runtime-design.md`](agent-runtime-design.md) §6 为准。
> 本文档不涉及独立编码，编码规范以主文档 §「编码规范」为准。

## 源码目录结构

本文档对应主文档 [`agent-runtime-design.md`](agent-runtime-design.md) 的 `src/hooks/` 目录：

```
src/hooks/
├── __init__.py                   # 导出 HookRegistry、Observer、Transformer、Interceptor
├── _registry.py                  # HookRegistry（分层编排：控制层 + 观察层）
└── _primitives.py                # PrimitiveType、Observer/Transformer/Interceptor 类型定义
```

> 本文档已废弃，编码实现以主文档 §6 为准。

## 一、问题分析

### 1.1 当前设计的矛盾

当前 `PrimitiveType` 将五种原语放在同一层级：

```python
class PrimitiveType(str, Enum):
    OBSERVE = "observe"      # 只读观察
    TRANSFORM = "transform"  # 可改数据
    INTERCEPT = "intercept"  # 可阻断
    ROUTER = "router"        # 改走向
    EXECUTE = "execute"      # 替换执行
```

但 Observer 和其他四种有**本质区别**：

| 维度 | Observer | Transform / Intercept / Router / Execute |
|------|----------|----------------------------------------|
| **对数据流的影响** | 无（只读） | 有（可改/可阻断/可转向/可替换） |
| **执行顺序要求** | 可并行 | 必须串行（后一个依赖前一个结果） |
| **错误影响** | 不应影响主流程 | 错误必须影响流程 |
| **权限** | 不应有 ctx 写权限 | 需要 ctx 写权限 |

### 1.2 当前代码中的具体体现

在 `HookRegistry` 中，Observer 和 Transform 混在同一个列表里，靠 `hook["type"]` 区分：

```python
async def run_observers(self, point, event, ctx):
    for hook in self._hooks.get(point, []):
        if hook["type"] == "observe":       # 硬编码字符串判断
            await hook["handler"](event, ctx)

async def run_transformers(self, point, data, ctx):
    result = data
    for hook in self._hooks.get(point, []):
        if hook["type"] == "transform":     # 同样硬编码
            result = await hook["handler"](result, ctx)
    return result
```

**问题**：
- 每次遍历都全部扫描一遍，靠 if 过滤类型——O(n) 复杂度，n 中包含不相关的 handler
- Observer 失败会阻塞 Transform 链（因为在同一循环中）
- 无法给 Observer 单独做错误隔离（"观察器失败不应影响主流程"）

---

## 二、重构方案：分两层

### 2.1 分层结构

```
HookRegistry
  │
  ├── 控制层（Control Plane）
  │     TRANSFORM / INTERCEPT / ROUTER / EXECUTE
  │     按序串行执行，错误影响流程
  │
  └── 观察层（Observation Plane）
        BEFORE / AFTER 事件通知
        异步并行触发，错误不影响流程
```

### 2.2 新枚举定义

```python
class PrimitiveType(str, Enum):
    """控制原语：影响数据流走向。"""
    TRANSFORM = "transform"    # 可修改数据
    INTERCEPT = "intercept"    # 可阻断/暂停
    ROUTER = "router"          # 可改变走向
    EXECUTE = "execute"        # 可替换执行

class ObservationPoint(str, Enum):
    """观察点：只读事件通知，不影响数据流。"""
    BEFORE_STEP = "before_step"
    AFTER_STEP = "after_step"
    BEFORE_LLM = "before_llm"
    AFTER_LLM = "after_llm"
    BEFORE_TOOL = "before_tool"
    AFTER_TOOL = "after_tool"
    BEFORE_SESSION_START = "before_session_start"
    AFTER_SESSION_START = "after_session_start"
    BEFORE_SESSION_END = "before_session_end"
    AFTER_SESSION_END = "after_session_end"
    ON_STREAM_CHUNK = "on_stream_chunk"
    ON_ERROR = "on_error"
```

### 2.3 HookRegistry 新设计

```python
class HookRegistry:
    def __init__(self):
        # 控制层：按 hook point 分类
        self._transforms: dict[str, list[Transformer]] = defaultdict(list)
        self._intercepts: dict[str, list[Interceptor]] = defaultdict(list)
        # Router 和 Executor 是单例
        self._router: RouterFn | None = None
        self._llm_executor: ExecutorFn | None = None
        self._tool_executor: ExecutorFn | None = None
        self._loop_executor: ExecutorFn | None = None

        # 观察层：按观察点分类（独立存储）
        self._observers: dict[str, list[Observer]] = defaultdict(list)

    # ── 控制层注册 ──

    def transform(self, point: str, handler: Transformer, name: str = "") -> None:
        self._transforms[point].append((name, handler))

    def intercept(self, point: str, handler: Interceptor, name: str = "") -> None:
        self._intercepts[point].append((name, handler))

    def set_router(self, router: RouterFn) -> None:
        self._router = router

    def set_llm_executor(self, executor: ExecutorFn) -> None:
        self._llm_executor = executor

    def set_tool_executor(self, executor: ExecutorFn) -> None:
        self._tool_executor = executor

    def set_loop_executor(self, executor: ExecutorFn) -> None:
        self._loop_executor = executor

    # ── 观察层注册 ──

    def on(self, point: str, observer: Observer, name: str = "") -> None:
        """注册一个观察器。"""
        self._observers[point].append((name, observer))

    # 便捷方法
    def on_step_start(self, observer: Observer) -> None:
        self.on("before_step", observer)

    def on_step_end(self, observer: Observer) -> None:
        self.on("after_step", observer)

    def on_llm_response(self, observer: Observer) -> None:
        self.on("after_llm", observer)

    def on_error(self, observer: Observer) -> None:
        self.on("on_error", observer)

    # ── 控制层执行 ──

    async def run_transforms(self, point: str, data: Any, ctx) -> Any:
        """串行执行 Transform 链。"""
        result = data
        for _, handler in self._transforms.get(point, []):
            result = await handler(result, ctx)
        return result

    async def run_intercepts(self, point: str, data: Any, ctx) -> InterceptResult:
        """串行执行 Intercept 链，返回第一个 block/pause 或 allow。"""
        for _, handler in self._intercepts.get(point, []):
            result = await handler(data, ctx)
            if result.action != "allow":
                return result
        return InterceptResult(action="allow")

    async def run_router(self, ctx) -> str:
        if self._router is None:
            return "end"
        return await self._router(ctx)

    # ── 观察层执行 ──

    async def emit(self, point: str, event: dict, ctx) -> None:
        """触发观察事件（异步并行，错误隔离）。"""
        if point not in self._observers:
            return

        tasks = []
        for _, handler in self._observers[point]:
            tasks.append(self._safe_observe(handler, event, ctx))

        # 并行执行，不等待全部完成（fire-and-forget 策略）
        await asyncio.gather(*tasks, return_exceptions=True)

    async def emit_wait(self, point: str, event: dict, ctx) -> None:
        """触发观察事件并等待全部完成（用于 session_end 等必须等待的场景）。"""
        if point not in self._observers:
            return

        results = await asyncio.gather(
            *[handler(event, ctx) for _, handler in self._observers[point]],
            return_exceptions=True,
        )
        # 记录异常但不抛出
        for (name, _), result in zip(self._observers[point], results):
            if isinstance(result, Exception):
                logger.warning(f"Observer '{name}' failed: {result}")

    async def _safe_observe(self, handler, event, ctx) -> None:
        """安全的观察器执行（异常不会传播）。"""
        try:
            await handler(event, ctx)
        except Exception as e:
            logger.warning(f"Observer failed (isolated): {e}")
```

### 2.4 旧接口兼容

保持旧接口以维持向后兼容，内部映射到新接口：

```python
class HookRegistry:
    # ── 旧接口兼容（内部重定向） ──

    def observe(self, point: str, handler: Observer, name: str = "") -> None:
        """旧接口：内部转发到 on()。"""
        self.on(point, handler, name)

    def register(self, point: str, hook_type: str, handler, name: str = "") -> None:
        """旧接口：根据 hook_type 转发到对应新接口。"""
        if hook_type == "observe":
            self.on(point, handler, name)
        elif hook_type == "transform":
            self.transform(point, handler, name)
        elif hook_type == "intercept":
            self.intercept(point, handler, name)
        else:
            raise ValueError(f"Unknown hook type: {hook_type}")

    def run_observers(self, point: str, event: dict, ctx) -> None:
        """旧接口：转发到 emit_wait()。"""
        return self.emit_wait(point, event, ctx)

    def run_transformers(self, point: str, data: Any, ctx) -> Any:
        """旧接口：转发到 run_transforms()。"""
        return self.run_transforms(point, data, ctx)

    def run_interceptors(self, point: str, data: Any, ctx) -> InterceptResult:
        """旧接口：转发到 run_intercepts()。"""
        return self.run_intercepts(point, data, ctx)
```

---

## 三、关键改动点

### 3.1 按"新注册方式"和"新执行方式"列出全部更改

| # | 位置 | 改动 | 影响 |
|---|------|------|------|
| 1 | `hooks.py:PrimitiveType` | 移除 OBSERVE，仅保留 4 种控制原语 | 枚举值减少 |
| 2 | `hooks.py:HookRegistry._hooks` | 从 `dict[str, list[dict]]` 改为 `_transforms` / `_intercepts` / `_observers` 三个独立字典 | 数据结构变更 |
| 3 | `hooks.py:HookRegistry.register()` | 标记为 deprecated，内部转发到新方法 | 旧代码继续可用 |
| 4 | `hooks.py:HookRegistry.on()` | 新增方法，注册观察器 | 新增 |
| 5 | `hooks.py:HookRegistry.emit()` | 新增方法，异步并行触发观察器 | 新增 |
| 6 | `hooks.py:HookRegistry.emit_wait()` | 新增方法，等待型触发（session_end 用） | 新增 |
| 7 | `hooks.py:HookRegistry.get_hooks_at()` | 需要兼容返回格式 | 小改 |
| 8 | `runtime.py:_step_loop()` | 将 `run_observers()` 改为 `emit()` | 非阻塞化 |
| 9 | `runtime.py:destroy()` | `run_observers(SESSION_END)` 改为 `emit_wait(SESSION_END)` | 保持等待 |
| 10 | 所有现有 `hooks.observe()` 调用处 | 无需改动（兼容层处理） | 无 |

### 3.2 需要同步修改的文件

```
src/hooks/_registry.py                # 核心改动
src/_runtime.py                       # run_observers → emit/emit_wait
src/__init__.py                       # 导出调整（如需要）
tests/test_hooks.py                   # 测试适配
tests/test_runtime.py                 # 测试适配
tests/test_executor.py                # 可能依赖观察器行为
```

---

## 四、带来的变化

### 4.1 观察器跑飞不影响主流程

```python
# 重构前：观察器抛异常 → Transform 链中断
async def run_transformers(self, point, data, ctx):
    for hook in self._hooks.get(point, []):
        if hook["type"] == "observe":     # 抛异常！
            result = await hook["handler"](data, ctx)  # 后续 Transform 不会执行
        ...

# 重构后：观察器异常被隔离
async def run_transforms(self, point, data, ctx):
    for _, handler in self._transforms.get(point, []):
        result = await handler(result, ctx)  # 这里只有 Transform，没有 Observer
    return result

# 观察器独立触发
await self.emit("before_step", event, ctx)
# ↑ 即使观察器抛异常，主流程不受影响
```

### 4.2 观察器可以并行

```python
# 重构前：串行
for hook in self._hooks.get(point, []):
    if hook["type"] == "observe":
        await hook["handler"](event, ctx)

# 重构后：并行
tasks = [handler(event, ctx) for _, handler in self._observers[point]]
await asyncio.gather(*tasks, return_exceptions=True)
```

### 4.3 Transformer 不再需要 if 过滤

```python
# 重构前：O(n) 遍历全部，if 过滤类型
for hook in hooks:
    if hook["type"] == "transform":
        ...

# 重构后：O(m) 直接取 Transform 列表，m <= n
for _, handler in self._transforms[point]:
    ...
```

---

## 五、风险与迁移策略

### 5.1 风险

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| 现有代码使用旧接口 | 高 | 行为不变（兼容层） | 保留 `register()` / `observe()` / `run_observers()` 兼容方法 |
| 观察器并行导致日志错乱 | 中 | 可接受 | 日志系统自带时间戳，无需额外处理 |
| session_end 观察器需要串行 | 低 | 影响 Evaluation | `emit_wait()` 提供等待语义 |

### 5.2 迁移步骤

```
Step 1: 修改 hooks.py 内部数据结构（_hooks → _transforms / _intercepts / _observers）
Step 2: 添加 on() / emit() / emit_wait() 新方法
Step 3: 添加旧接口兼容层（observe → on, register → 分发）
Step 4: 修改 runtime.py 中 run_observers() 调用为 emit()/emit_wait()
Step 5: 修改 tests 适配新结构
Step 6: 运行全部测试验证
```
