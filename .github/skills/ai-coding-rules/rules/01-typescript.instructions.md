---
applyTo: '**/*.{ts,tsx}'
---

# TypeScript Rules

> **AI Summary**: TypeScript 开发规范，强调类型安全（interface > type、unknown > any）、JSDoc 文档注释、vitest 测试、ESLint + tsc 检查。

- 类型声明优先用 interface，组件 props 用 interface 继承
- 泛型参数用语义化命名（TData、TResponse），避免单字母
- 优先 `unknown` 而非 `any`，减少类型断言 `as`
- 函数返回类型显式标注，不依赖类型推断
- 类型引用用 `import type` 而非 `import`，避免运行时残留
- 优先命名导出（named export），减少 `export default`

## 风格规范（TypeScript 官方 + Google TS 风格 + 项目约定）

### 命名规范

| 类型 | 风格 | 示例 |
|------|------|------|
| 变量/函数/方法 | `camelCase` | `userName`, `getUser()` |
| 类/接口/类型 | `PascalCase` | `UserService`, `UserProps` |
| 常量（模块级） | `UPPER_SNAKE_CASE` | `MAX_RETRY_COUNT` |
| 文件/目录 | `kebab-case` | `auth-service.ts` |
| React 组件文件 | `PascalCase` | `UserProfile.tsx` |
| 枚举成员 | `PascalCase` | `UserRole.Admin` |
| 私有成员 | `#` 或 `_` 前缀 | `#cache` / `_private` |
| 泛型参数 | 语义化短名 | `TData`, `TResponse`, `TError` |

### 格式规范

- **缩进**：2 空格，禁止 Tab
- **引号**：单引号 `'`（Prettier 默认），JSX 属性用双引号
- **分号**：每行末尾必须加分号
- **行长度**：≤ 100 字符（Prettier 默认）
- **尾逗号**：多行结构末尾加逗号（Prettier 默认）
- **空行**：import 组之间、顶级声明之间空行分隔

### 类型系统

- **interface vs type**：优先 `interface`（可合并声明），联合类型/交叉类型用 `type`
- **strict mode**：确保 `tsconfig.json` 开启 `strict: true`
- **unknown over any**：类型不确定时用 `unknown`，禁止使用 `any`
- **减少类型断言**：避免滥用 `as`，优先用类型守卫 `is` 或类型收窄
- **import type**：类型引用用 `import type { ... }`，避免运行时残留
- **readonly**：不变属性加 `readonly`，数组用 `readonly T[]` 或 `ReadonlyArray<T>`
- **枚举**：优先 `const enum` 或联合类型（`type Status = 'active' | 'inactive'`），减少运行时开销
- **函数重载**：优先联合类型参数或泛型，必要时才用重载签名

### 文件组织

- **单文件单导出**：每个文件只导出一个主要实体（类/组件/函数）
- **命名导出**：优先 named export，减少 `export default`
- **目录结构**：按功能/模块组织，`index.ts` 做统一导出
- **测试文件**：`*.test.ts` 或 `*.spec.ts`，与源码同目录

### 代码风格

- **解构赋值**：优先对象解构取属性
- **可选链**：`obj?.prop` 替代 `obj && obj.prop`
- **空值合并**：`??` 替代 `||` 做默认值（避免 falsy 陷阱）
- **箭头函数**：优先箭头函数表达式，避免 `function` 关键字（顶层/export 除外）
- **async/await**：优先 async/await 替代原生 Promise 链式调用
- **模板字符串**：字符串拼接用 `${}` 模板字符串

## 注释规范

### 注释示例

```typescript
/**
 * 用户认证服务，提供登录、登出和 Token 刷新功能。
 *
 * @remarks
 * 所有方法均返回 StandardResponse<T> 统一格式，
 * 使用 AuthTokenInterceptor 自动附加 Authorization header。
 *
 * @example
 * ```ts
 * const auth = new AuthService(httpClient);
 * const res = await auth.login({ email: 'a@b.com', password: 'xxx' });
 * ```
 */
export class AuthService {
  /**
   * 用户登录。
   *
   * @param credentials - 登录凭据（邮箱 + 密码）
   * @param rememberMe - 是否记住登录状态（可选，默认 false）
   * @returns 包含 accessToken 和 refreshToken 的响应
   * @throws {AuthError} 当凭据无效或账户被锁定时
   *
   * @deprecated 自 v2.1 起改用 {@link loginWithOAuth}，此方法仅向后兼容
   */
  async login(
    credentials: LoginCredentials,
    rememberMe?: boolean,
  ): Promise<StandardResponse<TokenPair>> { /* ... */ }
}
```

## Testing

- 使用 vitest + @testing-library/react 编写测试
- 覆盖 Happy Path、Boundary Case、Exception Handling 三个维度
- 测试文件命名 `*.test.ts` 或 `*.test.tsx`
- 单元测试：Mock 外部依赖而非真实调用
- **真实环境验证**：涉及外部服务（数据库、API、缓存等）时，必须有专用的连接验证测试（禁止 Mock），确认服务可达后才能报告"测试通过"

## Lint

- 运行 `pnpm lint` 检查代码质量（等价于 `eslint @lania-pro-components/components --ext .ts,.tsx`）
- 运行 `pnpm typecheck` 确保类型无错误（等价于 `tsc --noEmit`，从项目根目录执行）
- 运行 `pnpm format` 格式化代码（等价于 `prettier --write`）

> 所有检查均从项目根目录执行，不要进入子目录运行。
