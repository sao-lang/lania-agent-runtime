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

## 注释规范

- 公开 API 使用 `///` 文档注释（可生成 rustdoc）
- 结构体字段必须加 `///` 文档注释
- 复杂函数需在函数上方写文档注释说明用途、参数和返回值
- 使用 `// SAFETY:` 标注 unsafe 代码块的 safety 前提
- 修改代码不得删除已有注释，逻辑变化时追加说明

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
