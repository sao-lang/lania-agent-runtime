---
applyTo: '**/*.test.{ts,tsx}'
---

# Testing Rules

## 通用测试原则（跨语言适用）

- **三维覆盖**：每个测试对象必须覆盖 Happy Path（正常路径）、Boundary Case（边界条件）、Exception Handling（异常处理）
- **Arrange-Act-Assert**：每个测试用例按"准备→执行→断言"三段式组织
- **单一关注点**：一个测试只验证一个行为，不合并多个不相关的断言
- **测试即文档**：测试命名应清晰表达行为和预期，新人能通过测试名理解功能
- **Mock 外部依赖**：数据库、网络、文件系统等外部服务必须 Mock，不写集成测试级别的用例

## 各语言测试实践

### TypeScript (vitest)
- 框架：`vitest` + `@testing-library/react` / `supertest`（API）
- 文件命名：`*.test.ts` / `*.test.tsx`
- 组织：`describe` 分组 → `it` 用例
- Mock：`vi.mock()` / `vi.spyOn()`
- 命名风格：`describe('Component')` / `it('should ... when ...')`

### Python (pytest)
- 框架：`pytest` + `pytest-asyncio`（异步）+ `pytest-cov`（覆盖率）
- 文件命名：`test_*.py`
- 组织：`class TestXxx` 或顶层函数
- Mock：`unittest.mock` / `pytest-mock`
- 参数化：`@pytest.mark.parametrize` 减少重复
- Fixture：`@pytest.fixture` 管理依赖和共享状态
- 命名风格：函数名 `test_xxx_yyy`，清晰表达场景

### Go (testing)
- 框架：标准库 `testing` + `testify/assert`（可选的断言增强）
- 文件命名：`*_test.go`，与被测文件同包
- 组织：`TestXxx(t *testing.T)` + `t.Run("sub", ...)` 子测试
- Mock：接口 + 手写 mock struct，或 `testify/mock`
- 推荐模式：**Table-driven tests** — 用匿名结构体切片列出所有输入/预期
- 命名风格：`TestFuncName_Scenario`

### Rust (cargo test)
- 框架：内置 `#[test]` + `#[cfg(test)]` 模块
- 文件命名：单元测试在文件末尾 `mod tests` 模块内；集成测试在 `tests/` 目录
- 组织：`mod tests { ... }` + `#[test] fn ...`
- Mock：trait + 手写 mock 实现，或 `mockall` crate
- 断言：`assert_eq!` / `assert!` / `matches!` / `?` 传播错误
- 属性：`#[should_panic(expected = "...")]` 验证 panic
- 命名风格：`fn test_xxx()` 或 `fn xxx_works()`

### Dart (flutter_test)
- 框架：`flutter_test` + `mockito` / `mocktail`
- 文件命名：`*_test.dart`，放于 `test/` 目录
- 组织：`group('desc')` → `test('should ...')` / `widgetTest(...)`
- Mock：`@GenerateMocks` 或 `Mocktail` 的 `Mock` 类
- Widget 测试：`pumpWidget()` / `find.text()` / `expect()` 验证渲染
- 命名风格：`group('ClassName')` → `test('should ... when ...')`

## 覆盖率要求
- 核心逻辑模块：**≥90%** 行覆盖 + **≥80%** 分支覆盖
- 工具/辅助模块：**≥70%** 行覆盖
- 新增代码必须配套新增测试，不允许"先实现后补测试"
- CI 阶段覆盖率低于阈值视为失败
