---
applyTo: never
---

# Code Review — Python 专项审查规则

> 审查 Python 代码时加载此文件，配合 `code-review` skill 的通用 7 维度审查流程使用。

## 类型注解与类型安全

| 审查项 | 说明 |
|--------|------|
| **函数签名标注** | 所有函数参数和返回值是否标注了类型 |
| **Optional 写法** | 是否用 `str | None` 而非 `Optional[str]`（Python 3.10+） |
| **集合类型标注** | 是否标注了元素类型：`list[int]` 而非裸 `list` |
| **TypeVar 泛型** | 泛型函数是否用 `TypeVar` 而非 `Any` |
| **type 别名** | 复杂类型是否用 `type` 语句定义别名（Python 3.12+） |
| **Pydantic 类型校验** | Pydantic model 字段类型是否准确，是否用了 `Field()` 做约束 |
| **TypedDict 使用** | dict 结构是否可以用 `TypedDict` 替代裸 dict |

## 错误处理

| 审查项 | 说明 |
|--------|------|
| **具体异常捕获** | 是否捕获了具体异常类型，禁止裸 `except:` |
| **异常链** | `raise ... from e` 是否保留了原始异常上下文 |
| **静默捕获** | 是否用 `contextlib.suppress` 替代空的 `except: pass` |
| **自定义异常** | 自定义异常是否继承 `Exception`（非 `BaseException`） |
| **异常信息** | 异常是否包含足够的上下文：`raise AuthError(f"User {uid} not found")` |
| **日志记录** | except 块中是否记录了异常堆栈（`logger.exception()` 或 `exc_info=True`） |
| **finally 清理** | 资源释放是否放在 finally 或 context manager 中 |

## 异步与并发

| 审查项 | 说明 |
|--------|------|
| **await 完整性** | 协程调用是否都有 `await`，没有被遗忘的协程 |
| **同步阻塞混入** | async 函数中是否混入了 `time.sleep()`、`requests.get()` 等同步调用 |
| **Task 管理** | `asyncio.create_task` 创建的 Task 是否有引用持有，防止被 GC |
| **Task 取消** | 任务取消时是否清理了资源（文件/DB 连接） |
| **超时控制** | 所有网络/IO 调用是否有超时（`asyncio.wait_for` 或 `timeout` context） |
| **gather 错误** | `asyncio.gather` 是否设置了 `return_exceptions=True` |
| **锁/同步** | 共享可变状态是否有 `asyncio.Lock` 保护 |
| **并发安全** | 是否有潜在的竞态条件（先检查后写入等） |

## 数据模型与序列化

| 审查项 | 说明 |
|--------|------|
| **Pydantic 优先** | 数据模型是否用 Pydantic `BaseModel` / `dataclass` 而非裸 dict |
| **model_validate** | 反序列化是否用 `model_validate()` 而非手写解析逻辑 |
| **序列化控制** | 是否合理使用了 `model_dump()` 的 `exclude`/`include`/`by_alias` |
| **配置管理** | 配置是否用 Pydantic `BaseSettings` 管理，而非硬编码 |
| **枚举使用** | 有限取值字段是否用 `Enum` / `IntEnum` 而非裸字符串 |

## API 与 I/O

| 审查项 | 说明 |
|--------|------|
| **上下文管理器** | 文件/锁/连接/HTTP session 是否用 `with` / `async with` 管理 |
| **路径操作** | 是否用 `pathlib.Path` 而非 `os.path` |
| **文件编码** | 文本文件读写是否指定了 `encoding=` |
| **HTTP 客户端** | 是否用 `httpx`/`aiohttp` 而非不推荐的 `requests`（async 项目） |

## 代码风格与习惯

| 审查项 | 说明 |
|--------|------|
| **f-string** | 字符串拼接优先 f-string 而非 `+` / `%` / `.format()` |
| **判空习惯** | 是否用 `if not items:` 而非 `if len(items) == 0:` |
| **直接迭代** | 优先 `for item in collection:` 而非 `for i in range(len(...))` |
| **字典安全取值** | 是否用 `dict.get(key, default)` 而非 try/except KeyError |
| **列表解析** | 简单映射/过滤是否用 list comprehension 而非 for+append |
| **三元表达式** | 简单条件赋值是否用 `x if cond else y` 替代 if/else |
| **导入顺序** | import 是否按 标准库 → 第三方 → 本地 分组排列 |
| **print 残留** | 是否有调试遗留的 `print()`（生产代码应使用 logging） |

## 测试

| 审查项 | 说明 |
|--------|------|
| **pytest 规范** | 测试是否使用 pytest，函数名是否以 `test_` 开头 |
| **fixture 使用** | 测试依赖是否用 fixture 管理，而非在测试函数内重复创建 |
| **参数化** | 多组输入输出是否用 `@pytest.mark.parametrize` 而非复制粘贴 |
| **Mock 使用** | 外部依赖是否被 Mock，是否验证了 Mock 的调用 |
| **边界覆盖** | 测试是否覆盖了空值、异常、边界条件 |
| **异步测试** | 异步函数测试是否用 `pytest-asyncio` 的 `@pytest.mark.asyncio` |

## Lint 与工具链

| 审查项 | 说明 |
|--------|------|
| **ruff 检查** | 是否通过了 `ruff check .`（无 error 和 warning） |
| **ruff 格式化** | 是否通过了 `ruff format .`（格式一致） |
| **mypy 类型检查** | 是否通过了 `mypy .`（无类型错误） |
| **Pylance 报错** | VS Code Pylance 是否有红色波浪线报错 |
