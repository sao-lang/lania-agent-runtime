---
applyTo: never
---

# Code Review — TypeScript 专项审查规则

> 审查 TypeScript/TSX 代码时加载此文件，配合 `code-review` skill 的通用 7 维度审查流程使用。

## 类型系统

| 审查项 | 说明 |
|--------|------|
| **strict mode** | `tsconfig.json` 是否开启了 `strict: true` |
| **any 禁止** | 是否有不必要的 `any`，能否用 `unknown` + 类型守卫替代 |
| **类型断言** | 是否过度使用 `as` 断言，是否有更好的类型守卫或类型收窄方式 |
| **interface vs type** | 优先 `interface`（可合并声明）；联合/交叉类型用 `type` |
| **泛型命名** | 泛型参数是否语义化（`TData`/`TResponse`），避免单字母 |
| **readonly** | 不变属性是否加 `readonly`，数组用 `readonly T[]` / `ReadonlyArray<T>` |
| **枚举** | 是否可以用联合类型 `type Status = 'active' | 'inactive'` 替代运行时 enum |
| **const 断言** | 常量值是否用 `as const` 确保类型精确推断 |
| **satisfies** | 是否可以用 `satisfies` 替代类型断言 |

## 空值与可选链

| 审查项 | 说明 |
|--------|------|
| **可选链** | 深层属性访问是否用 `?.` 替代 `&&` 链 |
| **空值合并** | 默认值是否用 `??` 而非 `||`（避免 falsy 陷阱） |
| **null 检查** | 函数参数/返回值是否有未处理的 `null`/`undefined` |
| **非空断言** | `!` 非空断言是否合理使用，有无更安全的守卫替代方案 |

## 异步与 Promise

| 审查项 | 说明 |
|--------|------|
| **await 完整性** | Promise 调用是否都有 `await`，有无被遗忘的异步调用 |
| **Promise 返回值** | async 函数是否检查/await 了返回的 Promise |
| **错误处理** | async/await 是否有 try/catch，Promise 是否有 `.catch()` |
| **并发控制** | 并行请求是否用 `Promise.all`/`Promise.allSettled` 而非逐个 await |
| **race 条件** | `Promise.race` 超时场景是否有清理逻辑 |

## 模块与导入

| 审查项 | 说明 |
|--------|------|
| **import type** | 类型引用是否用 `import type { ... }` 而非普通 `import` |
| **命名导出** | 是否优先 named export，减少 `export default` |
| **循环依赖** | 模块之间是否存在循环引用 |
| **barrel 文件** | `index.ts` 是否合理控制导出范围，避免导入不需要的内容 |
| **路径别名** | 是否用 `@/` 等路径别名而非深层相对路径 `../../../` |

## React/JSX 专项

| 审查项 | 说明 |
|--------|------|
| **props 类型** | 组件 props 是否定义了类型（interface） |
| **key 属性** | 列表渲染是否都加了合理的 `key`（非 index） |
| **依赖数组** | `useEffect`/`useMemo`/`useCallback` 的依赖数组是否完整 |
| **状态更新** | `setState` 是否用了函数式更新形式（依赖旧状态时） |
| **副作用清理** | `useEffect` 返回值是否清理了订阅/定时器/事件监听 |
| **条件渲染** | 是否用 `{condition && <Component />}` 而非三元表达式 |
| **自定义 Hook** | 复用逻辑是否提取为自定义 Hook |

## 代码风格

| 审查项 | 说明 |
|--------|------|
| **解构赋值** | 对象属性是否用解构提取，而非重复 `obj.prop` |
| **模板字符串** | 字符串拼接是否用 `${}` 模板字符串 |
| **箭头函数** | 是否优先箭头函数（顶层/export 函数可用 `function`） |
| **可选参数** | 函数可选参数是否用 `?` 而非手动检查 undefined |
| **默认参数** | 函数参数是否有合理的默认值 |
| **console 残留** | 是否有调试遗留的 `console.log`/`console.debug` |

## 测试

| 审查项 | 说明 |
|--------|------|
| **测试框架** | 是否使用 vitest / jest |
| **渲染测试** | React 组件是否使用 `@testing-library/react` 测试渲染 |
| **事件测试** | 用户交互（点击/输入）是否被测试 |
| **Mock 外部** | API 调用/第三方是否被 Mock |
| **快照测试** | 快照测试是否合理，有无过大或频繁变动的快照 |

## Lint 与工具链

| 审查项 | 说明 |
|--------|------|
| **ESLint** | 是否通过了 ESLint 检查（`pnpm lint`） |
| **TypeScript 检查** | 是否通过了 `tsc --noEmit` 类型检查（`pnpm typecheck`） |
| **Prettier** | 是否通过了 Prettier 格式化（`pnpm format`） |
