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

## 风格规范（Effective Dart + 官方约定）

### 命名规范

| 类型 | 风格 | 示例 |
|------|------|------|
| 变量/常量/参数 | `lowerCamelCase` | `userName`, `maxCount` |
| 类/枚举/类型 | `PascalCase` | `UserService`, `HttpStatus` |
| 库/文件/目录 | `snake_case` | `auth_service.dart` |
| 私有成员 | 前导下划线 `_` | `_cache`, `_loadData()` |
| 枚举值 | `lowerCamelCase` | `HttpStatus.ok` |
| 常量（顶级/类级） | `lowerCamelCase` | `const defaultTimeout = 30` |
| 类型参数（泛型） | 单字大写 | `T`, `K`, `V`, `S` |

> **注意**：Dart 与多数语言不同——常量也使用 `lowerCamelCase`，而非 `UPPER_SNAKE_CASE`。这是 Effective Dart 的明确推荐。

### 格式规范

- **缩进**：2 空格，禁止 Tab
- **行长度**：≤ 80 字符（官方推荐），项目可放宽至 100
- **引号**：优先单引号 `'`，嵌套引号时用双引号 `"`
- **花括号**：左花括号与表达式同行，右花括号单独一行
- **空行**：方法之间 1 空行，类之间 2 空行
- **链式调用**：`.` 另起一行并缩进 2 空格
- **级联操作**：`..` 另起一行

### 类型系统

- **final/const 优先**：变量能用 `final` 就不用 `var`，编译期常量用 `const`
- **避免 dynamic**：类型不确定时优先 `Object?` 配合类型检查，而非 `dynamic`
- **sealed class**：有限状态分支用 `sealed class` + `when`/`switch` 穷尽匹配
- **record 类型**（Dart 3+）：临时组合值用 Record `(value, error)` 而非创建小 class
- **命名参数**：布尔型参数必须用命名参数（`enableCache: true`），禁止位置参数
- **required**：必填命名参数标记 `required`
- **类型安全**：`as` 转型前先 `is` 检查，优先模式匹配

### 文件组织

- **单文件单类**：每个文件一个核心类，文件名为 `snake_case`
- **export**：`export` 放于 `library` 声明之后，第三方 import 之前
- **import 顺序**：`dart:` → 第三方包 → 项目内部包，每组空行分隔
- **part/part of**：**尽量避免**，优先用独立文件 + import

### 代码风格

- **集合字面量**：优先 `[]` `{}` 而非 `List()` `Map()`
- **箭头函数**：单表达式函数用 `=>`，多语句用 block body
- **字符串插值**：用 `$variable` 或 `${expression}`，避免 `+` 拼接
- **空安全**：用 `??` 提供默认值，用 `?.` 安全访问，用 `!` 仅当绝对确定
- **级联操作**：多用 `..` 链式操作替代重复变量名
- **async 函数**：`await` 表达式作为参数时加括号：`foo((await bar()))`

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
