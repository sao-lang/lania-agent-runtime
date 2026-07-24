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

## 注释规范

- 公开 API 使用 JSDoc 格式（`/** */`）写文档注释
- 组件 props 使用 `@param` 标注每个属性的用途
- 复杂逻辑添加行内注释，解释"为什么做"而非"做了什么"
- 使用 `@deprecated` 标注已废弃 API，并注明替代方案
- 修改代码不得删除已有注释，逻辑变化时追加说明

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
