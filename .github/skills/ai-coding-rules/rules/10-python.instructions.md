---
applyTo: '**/*.py'
---

# Python Rules

> **AI Summary**: Python 开发规范，强调类型注解、Pydantic/dataclass 定义数据、PEP 257 docstring、pytest 测试、ruff + mypy 检查。

- 类型注解：函数参数和返回值必须标注类型
- 使用 `Pydantic` / `dataclass` 定义数据结构，避免裸 dict
- 异常处理：捕获具体异常类型，禁止 `except: pass`
- 使用 `pathlib` 而非 `os.path`
- 遵循 PEP 8 规范
- 使用uv、ruff等工具
- 日志用 `import logging` 模块，禁止 `print()`
- 异步用 `async def` + `asyncio`，而非 `threading`

## 风格规范（PEP 8 + 项目约定）

### 命名规范

| 类型 | 风格 | 示例 |
|------|------|------|
| 变量/函数/方法 | `snake_case` | `user_name`, `get_user()` |
| 类/异常 | `PascalCase` | `UserService`, `AuthError` |
| 常量 | `UPPER_SNAKE_CASE` | `MAX_RETRY_COUNT` |
| 模块/包 | `snake_case` | `auth_service.py` |
| 私有成员 | 前导下划线 `_` | `_internal_cache` |
| 名称混淆 | 双下划线 `__` | `__private_method` |
| 类型变量 | `PascalCase` 短名 | `T`, `ResponseT` |

### 格式规范

- **行长度**：≤ 120 字符（项目 ruff 配置）
- **缩进**：4 空格，禁止 Tab
- **引号**：双引号 `"`（ruff 配置 `quote-style = "double"`）
- **空行**：顶级定义之间 2 空行，方法之间 1 空行
- **import 顺序**：标准库 → 第三方 → 本地模块（ruff I 规则自动排序）
- **行尾逗号**：多行结构（列表/dict/函数参数）每行末尾加逗号

### 类型注解（PEP 484）

- 所有函数参数和返回值必须标注类型
- 使用 `|` 替代 `Optional`：`str | None` 而非 `Optional[str]`
- 集合类型标注元素类型：`list[int]` 而非 `list`
- 使用 `TypeVar` 标注泛型，避免 `Any`
- 复杂的类型别名用 `type` 语句（Python 3.12+）：`type JSON = dict[str, Any]`

### 异常处理

- 捕获具体异常类型，禁止裸 `except:`
- 使用 `contextlib.suppress` 替代静默捕获的场景
- 自定义异常继承自 `Exception` 而非 `BaseException`
- 异常信息包含上下文：`raise AuthError(f"User {uid} not found")`

### 字面量与构造

- **字符串拼接**：用 f-string 而非 `+` 或 `%`
- **路径操作**：用 `pathlib.Path` 而非 `os.path`
- **文件读写**：用 `with open(...) as f:` 而非手动 close
- **判空**：`if not items:` 而非 `if len(items) == 0:`
- **循环**：优先 `for item in collection:` 而非 `for i in range(len(...))`
- **字典取值**：`dict.get(key, default)` 而非 try/except KeyError

## 注释规范

- 遵循 PEP 257 文档注释规范
- 公开模块、类、函数使用 `"""docstring"""` 写文档注释
- docstring 格式：首行简述，空行后详述参数/返回值/异常
- 复杂逻辑添加行内注释，解释"为什么做"而非"做了什么"
- 修改代码不得删除已有注释，逻辑变化时追加说明

### 注释示例

```python
from pydantic import BaseModel
from typing import Optional
import aiohttp


class StandardResponse(BaseModel):
    """统一 API 响应格式。

    所有服务层方法均返回此类型，确保调用方获得一致的响应结构。

    Attributes:
        code: 业务状态码，200 表示成功。
        data: 响应数据，泛型类型由调用方指定。
        message: 人类可读的消息，失败时包含错误描述。
    """
    code: int = 200
    data: dict | None = None
    message: str = "ok"


class AuthService:
    """用户认证服务，提供登录、登出和 Token 刷新功能。

    所有方法均返回 StandardResponse 统一格式，
    使用 AuthTokenInterceptor 自动附加 Authorization header。

    Usage:
        auth = AuthService(http_client)
        res = await auth.login("a@b.com", "xxx", remember_me=False)
    """

    async def login(
        self,
        email: str,
        password: str,
        remember_me: bool = False,
    ) -> StandardResponse:
        """用户登录。

        Args:
            email: 登录邮箱。
            password: 登录密码。
            remember_me: 是否记住登录状态，默认 False。

        Returns:
            包含 accessToken 和 refreshToken 的响应。

        Raises:
            AuthError: 当凭据无效或账户被锁定。
            ConnectionError: 当无法连接到认证服务器。

        Deprecated:
            v2.1 起改用 login_with_oauth，此方法仅向后兼容。
        """
        ...
```

## Testing

- 使用 `pytest` 编写测试，函数名以 `test_` 开头
- 测试文件命名 `test_*.py`，放于 `tests/` 目录
- 使用 fixture 管理测试依赖和 Mock
- 覆盖正常路径、边界条件和异常分支
- 使用 `parametrize` 减少重复测试代码
- 运行 `pytest` 或 `pytest tests/` 执行测试
- 运行 `pytest --cov` 检查测试覆盖率
- **真实环境验证**：涉及外部服务（PostgreSQL、Neo4j、Redis、MinIO、外部 API 等）时，必须有专用的连接验证测试（禁止 Mock），直连真实服务并执行至少一条简单操作，确认服务可达后才能报告"测试通过"

## Lint

- 运行 `ruff check .` 检查代码质量（替代 flake8，速度更快）
- 运行 `ruff format .` 格式化代码（替代 black，与 ruff 无缝集成）
- 运行 `mypy .` 检查类型注解
- 确保 `ruff check` 无 error 和 warning，确保代码无flake和pylance报错
