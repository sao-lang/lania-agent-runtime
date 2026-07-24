---
applyTo: '**/*.rs'
---

# Rust Rules

> **AI Summary**: Rust 开发规范，强调类型安全（enum + match、Result 而非 panic）、/// rustdoc 文档注释、cargo test 测试、cargo clippy 检查。

- 优先使用 `enum` + `match` 处理状态/错误分支
- 使用 `Result<T, E>` 而非 `panic!` / `unwrap()`
- 泛型约束用 `where` 子句提升可读性
- 遵循 Rustfmt 和 Clippy 规范
- 常用 trait 用 `#[derive(Debug, Clone, PartialEq)]` 而非手写
- 模块按文件组织，每个文件一个核心类型，`mod.rs` 只做重导出

## 风格规范（Rust API Guidelines + Rust Style Guide）

### 命名规范

| 类型 | 风格 | 示例 |
|------|------|------|
| 变量/函数/方法 | `snake_case` | `user_name`, `get_user()` |
| 类型/结构体/trait/enum | `PascalCase` | `UserService`, `Display` |
| 常量/静态变量 | `UPPER_SNAKE_CASE` | `MAX_RETRY_COUNT` |
| 文件/目录 | `snake_case` | `auth_service.rs` |
| 模块名 | `snake_case` | `mod auth_service` |
| 枚举变体 | `PascalCase` | `Status::Active` |
| 泛型参数 | 单大写字母 | `T`, `E`, `K`, `V` |
| 生命周期 | 单引号 + 短名 | `'a`, `'_` |
| 构造器/转换器 | `from_`, `to_`, `as_`, `into_` | `from_str()`, `into_inner()` |
| getter | 去掉 `get_` 前缀 | `.name()` 而非 `.get_name()` |
| 错误类型 | 后缀 `Error` | `ParseError`, `AuthError` |
| trait 标记 | 后缀 `able` / `ing` | `Cloneable`, `Serializing` |

### 格式规范

- **缩进**：4 空格，禁止 Tab
- **行长度**：≤ 100 字符（rustfmt 默认）
- **花括号**：左花括号与表达式同行（same-line），右花括号单独一行
- **空行**：函数/item 之间 1 空行，`impl` 块内方法按逻辑分组
- **import 组织**：标准库 → 外部 crate → 本地模块，每组空行分隔
- **import 合并**：`use std::collections::{HashMap, HashSet}`

### 类型系统

- **Result 优先**：返回 `Result<T, E>` 而非 `Option<T>`（除非逻辑上确实"可能没有"）
- **自定义错误**：实现 `std::error::Error` + `Display`，用 `thiserror` crate 简化
- **newtype 模式**：用单字段元组结构体包装原始类型，利用类型系统防止混淆
- **Builder 模式**：超过 3 个参数的构造器用 Builder 模式
- **trait 约束**：用 `where` 子句提升可读性，尤其泛型参数多时
- **derive**：常用 trait 用 `#[derive(Debug, Clone, PartialEq)]`，避免手写
- **Copy vs Clone**：仅当类型大小 ≤ 指针宽度时才实现 `Copy`

### 模块与文件组织

- **模块结构**：每个模块一个目录，`mod.rs` 只做重导出，逻辑在子文件中
- **可见性**：最小化 `pub`——crate 内部用 `pub(crate)`，对外 API 才用 `pub`
- **re-export**：通过 `pub use` 暴露公共 API 路径，隐藏内部模块层次
- **cfg 条件**：平台特定代码用 `#[cfg(target_os = "...")]`，不要写死平台分支

### 错误处理模式

| 模式 | 推荐度 | 说明 |
|------|--------|------|
| `Result<T, E>` | ⭐ 首选 | 可恢复错误的标准方式 |
| `Option<T>` | ⭐ 常用 | 空值/不存在的情况 |
| `panic!` / `unwrap()` | ❌ 避免 | 仅示例/测试/prototype 可用 |
| `expect("msg")` | ⚠️ 慎用 | 仅当 panic 确实不可能发生 |
| `.unwrap_or_default()` | ✅ 推荐 | 提供合理默认值 |
| `anyhow::Result` | ✅ 应用层 | 二进制/应用代码使用 |
| `thiserror::Error` | ✅ 库层 | 库代码定义错误类型 |

### 代码风格

- **模式匹配**：用 `match` 穷尽处理枚举，用 `if let` 处理单分支
- **迭代器链**：优先 `iter()` → `.filter()` → `.map()` → `.collect()` 链，而非 for 循环
- **? 操作符**：优先 `?` 传播错误，而非手动 `match`
- **懒初始化**：用 `LazyLock` / `OnceLock`（取代 `lazy_static!` / `once_cell`）
- **字符串**：用 `&str` 作参数，`String` 作所有权值
- **借用规则**：优先 `&T` 引用，需要修改用 `&mut T`，避免 `Rc<RefCell<T>>`

## 注释规范

### 注释示例

```rust
/// 用户认证服务，提供登录、登出和 Token 刷新功能。
///
/// # Remarks
/// 所有方法均返回 `StandardResponse<T>` 统一格式，
/// 使用 `AuthTokenInterceptor` 自动附加 Authorization header。
///
/// # Examples
/// ```
/// use auth::AuthService;
///
/// let auth = AuthService::new(http_client);
/// let res = auth.login("a@b.com", "xxx", false).await?;
/// ```
pub struct AuthService {
    /// HTTP 客户端，用于发送网络请求。
    client: HttpClient,
    /// 基础 URL，默认从环境变量 `API_BASE_URL` 读取。
    base_url: String,
}

impl AuthService {
    /// 用户登录。
    ///
    /// # Arguments
    /// * `email` - 登录邮箱
    /// * `password` - 登录密码
    /// * `remember_me` - 是否记住登录状态
    ///
    /// # Returns
    /// `Result<StandardResponse<TokenPair>, AuthError>`
    ///
    /// # Errors
    /// 当凭据无效或账户被锁定返回 `AuthError::InvalidCredentials`
    ///
    /// # Safety
    /// 此方法内部使用了 unsafe 代码进行 Token 解析，
    /// 调用方需确保传入的 Token 格式正确。
    pub async fn login(
        &self,
        email: &str,
        password: &str,
        remember_me: bool,
    ) -> Result<StandardResponse<TokenPair>, AuthError> {
        // SAFETY: Token 在此处已被 AuthService 内部校验过格式，
        // 传入 parse_unchecked 的 Token 必定是合法 Base64 编码。
        let token = unsafe { parse_token_unchecked(&raw_token) };
        // ... 业务逻辑
    }
}
```

## Testing

- 使用 `#[cfg(test)]` 模块 + `#[test]` 属性编写单元测试
- 集成测试放于 `tests/` 目录
- 覆盖正常路径、边界条件和错误处理
- 使用 `assert_eq!` / `assert!` 断言，必要时用 `?` 操作符传播错误
- 使用 `cargo test` 执行所有测试
- 使用 `cargo test -- --nocapture` 查看测试中的 println! 输出
- **真实环境验证**：涉及外部服务（数据库、API、缓存等）时，必须有专用的连接验证测试（禁止 Mock），确认服务可达后才能报告"测试通过"

## Lint

- 运行 `cargo fmt` 格式化代码
- 运行 `cargo clippy` 静态分析（等价于增强版 lint）
- 运行 `cargo check` 快速检查编译错误（比 `cargo build` 更快）
- 确保 `cargo clippy` 无 warning
