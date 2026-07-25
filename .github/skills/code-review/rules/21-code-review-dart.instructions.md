---
applyTo: never
---

# Code Review — Dart 专项审查规则

> 审查 Dart/Flutter 代码时加载此文件，配合 `code-review` skill 的通用 7 维度审查流程使用。

## 类型与变量

| 审查项 | 说明 |
|--------|------|
| **final/const 优先** | 变量是否优先用 `final` / `const` 而非 `var` |
| **dynamic 禁止** | 是否有不必要的 `dynamic`，能否用 `Object?` + 类型检查替代 |
| **sealed class** | 有限状态分支是否用 `sealed class` + `when`/`switch` 穷尽匹配 |
| **record 类型** | 临时组合值是否可以用 Record `(value, error)` 替代小 class |
| **const 构造** | class 如不可变，是否添加了 `const` 构造函数 |
| **类型推断** | 是否合理利用类型推断，避免冗余的类型标注 |

## 空安全

| 审查项 | 说明 |
|--------|------|
| **null 处理** | 是否用 `??` 提供默认值，用 `?.` 安全访问 |
| **! 使用** | `!` 非空断言是否仅在绝对确定时使用，有无更安全的替代方案 |
| **late 使用** | `late` 变量是否在初始化前被访问的风险 |
| **required 命名参数** | 必填命名参数是否标记了 `required` |

## 异步与并发

| 审查项 | 说明 |
|--------|------|
| **await 完整性** | Future 调用是否都有 `await`，有无被遗漏的异步操作 |
| **错误处理** | async 函数是否有 try/catch 捕获异常 |
| **Future 链** | 是否用 `.then()`/`.catchError()` 链式处理，还是应该用 async/await |
| **Stream 管理** | Stream 订阅是否正确取消（`StreamSubscription.cancel()`） |
| **并发执行** | 独立异步任务是否用 `Future.wait` / `FutureGroup` 并行执行 |
| **Isolate 使用** | CPU 密集型任务是否用 `Isolate.run` 避免阻塞 UI 线程 |

## Flutter 专项

| 审查项 | 说明 |
|--------|------|
| **Widget 拆分** | Widget 是否过大，是否应拆分为小组件 |
| **const Widget** | 无变化的 Widget 是否标记为 `const` |
| **Build 方法纯函数** | `build` 方法中是否避免副作用和耗时操作 |
| **key 使用** | 列表项/可复用 Widget 是否加了合理的 `Key` |
| **setState 范围** | `setState` 是否包裹了最小必要范围 |
| **InheritedWidget** | 全局状态是否通过 `InheritedWidget` / Provider / Riverpod 传递 |
| **didChangeDependencies** | 依赖变化后的重计算是否放对了生命周期 |
| **dispose 清理** | Controller/StreamSubscription/Timer 是否在 `dispose` 中清理 |

## 命名与风格

| 审查项 | 说明 |
|--------|------|
| **常量命名** | 常量是否使用 `lowerCamelCase`（Dart 惯例，非 UPPER_SNAKE_CASE） |
| **私有成员** | 私有变量/方法是否加前导下划线 `_` |
| **文件命名** | 文件是否使用 `snake_case.dart` |
| **库命名** | 库名是否使用 `snake_case` |
| **导入顺序** | import 是否按 `dart:` → 第三方 → 项目内部 分组 |

## 集合与字符串

| 审查项 | 说明 |
|--------|------|
| **集合字面量** | 是否用 `[]` `{}` 而非 `List()` `Map()` 构造 |
| **集合操作** | 是否用 `.map()`/`.where()`/`.expand()`/`.toList()` 链式处理 |
| **级联操作** | 同一对象多次操作是否用 `..` 级联替代重复变量名 |
| **字符串插值** | 是否用 `$variable` / `${expression}` 而非 `+` 拼接 |
| **字符串构建** | 大量字符串拼接是否用 `StringBuffer` |

## 函数与参数

| 审查项 | 说明 |
|--------|------|
| **命名参数** | 布尔型参数是否用命名参数而非位置参数 |
| **箭头函数** | 单表达式函数是否用 `=>` 而非 block body |
| **可选参数** | 可选参数是否放在最后，位置可选参数用 `[]` 包裹 |
| **默认值** | 参数是否有合理的默认值 |

## 测试

| 审查项 | 说明 |
|--------|------|
| **测试框架** | 是否使用 `flutter_test` 编写测试 |
| **Widget 测试** | UI 组件是否有 Widget 测试覆盖渲染和交互 |
| **group 组织** | 相关测试用例是否用 `group()` 组织 |
| **Mock 使用** | 外部依赖是否用 `mockito` Mock |
| **Golden 测试** | UI 变化是否用 Golden 测试捕获视觉回归 |

## Lint 与工具链

| 审查项 | 说明 |
|--------|------|
| **dart format** | 是否通过了 `dart format .` 格式化检查 |
| **dart analyze** | 是否通过了 `dart analyze` 静态分析（无 warning / info） |
| **flutter analyze** | Flutter 项目是否通过了 `flutter analyze` |
| **dart test** | 是否所有测试通过（`dart test` / `flutter test`） |
