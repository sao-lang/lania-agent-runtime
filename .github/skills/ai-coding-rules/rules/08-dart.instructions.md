---
applyTo: '**/*.dart'
---

# Dart Rules

> **AI Summary**: Dart 开发规范，强调类型安全（final/const 优先、sealed class）、/// 文档注释、flutter_test 测试、dart analyze 检查。

- 类型声明优先使用 `class` 和 `typedef`，避免 `dynamic`
- 使用 `final` / `const` 替代 `var`，不可变优先
- 遵循 Effective Dart 风格指南
- 使用 `sealed class` + `when` 处理状态/结果分支（而非手动 if-else）
- class 如可不可变，加 `const` 构造函数
- 异常用 `try/catch` 捕获具体类型，禁止 `catch (e)` 不处理

## 注释规范

- 公开 API 使用 `///` 文档注释，而非 `//` 或 `/** */`
- 类、方法、顶级常量必须写文档注释
- 复杂逻辑需添加行内注释解释意图，不解释"是什么"
- 修改代码不得删除已有注释，逻辑变化时追加说明

### 注释示例

```dart
/// 用户认证服务，提供登录、登出和 Token 刷新功能。
///
/// 所有方法均返回 [StandardResponse<T>] 统一格式，
/// 使用 [AuthTokenInterceptor] 自动附加 Authorization header。
///
/// {@tool snippet}
/// ```dart
/// final auth = AuthService(httpClient);
/// final res = await auth.login(email: 'a@b.com', password: 'xxx');
/// ```
/// {@end-tool}
class AuthService {
  /// 用户登录。
  ///
  /// [credentials] 登录凭据（邮箱 + 密码）
  /// [rememberMe] 是否记住登录状态（可选，默认 false）
  ///
  /// Returns [StandardResponse<TokenPair>] 包含 accessToken 和 refreshToken
  ///
  /// Throws [AuthError] 当凭据无效或账户被锁定
  ///
  /// @Deprecated 自 v2.1 起改用 [loginWithOAuth]，此方法仅向后兼容
  @Deprecated('Use [loginWithOAuth] instead')
  Future<StandardResponse<TokenPair>> login(
    LoginCredentials credentials, {
    bool rememberMe = false,
  }) async { /* ... */ }
}
```

## Testing

- 使用 `flutter_test` + `mockito` 编写测试
- 测试文件放于 `test/` 目录，命名 `*_test.dart`
- Widget 测试覆盖 UI 渲染和交互行为
- 使用 `group()` 组织相关测试用例
- 覆盖正常路径、边界条件和异常处理
- 运行 `flutter test` 执行所有测试
- **真实环境验证**：涉及外部服务（API、数据库、Firebase 等）时，必须有专用的连接验证测试（禁止 Mock），确认服务可达后才能报告"测试通过"

## Lint

- 运行 `dart format .` 格式化代码
- 运行 `dart analyze` 静态分析
- 运行 `flutter analyze`（Flutter 项目专用，包含更多规则）
- 确保无 warning 和 info 级别的问题
