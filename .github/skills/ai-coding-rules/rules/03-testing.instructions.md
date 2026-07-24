---
applyTo: '**/*'
---

# Testing Rules

## 测试分层

严格区分以下测试层级，各自有不同的目标和约束：

| 层级 | 目标 | 外部依赖 | 执行条件 |
|------|------|---------|---------|
| **单元测试** | 验证代码逻辑正确性 | Mock 所有外部依赖 | 无需真实环境 |
| **集成测试** | 验证模块间交互 | 可 mock 部分依赖，但**关键外部服务必须真实连接** | 需要对应服务可用 |
| **环境验证测试（Smoke Test）** | 验证外部服务真实可用 | **禁止 Mock**，必须直连真实服务 | 必须依赖对应服务运行中 |
| **E2E 测试（端到端）** | 验证全链路业务流程 | **所有服务均为真实连接**，与生产环境一致 | 需要完整环境（所有外部服务运行中） |

## 通用测试原则（跨语言适用）

- **三维覆盖**：每个测试对象必须覆盖 Happy Path（正常路径）、Boundary Case（边界条件）、Exception Handling（异常处理）
- **Arrange-Act-Assert**：每个测试用例按"准备→执行→断言"三段式组织
- **单一关注点**：一个测试只验证一个行为，不合并多个不相关的断言
- **测试即文档**：测试命名应清晰表达行为和预期，新人能通过测试名理解功能
- **单元测试**：Mock 外部依赖而非真实调用，关注逻辑正确性
- **集成测试**：可 mock 部分依赖，但**关键外部服务必须真实连接**

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

## 真实环境连接强制要求（核心规则）

> **⚠️ 任何涉及数据库、消息队列、缓存、外部 API、对象存储等真实环境连接的服务，必须同时满足以下条件：**

1. **必须有专用的连接验证测试**：为每个外部服务（PostgreSQL、Neo4j、Redis、MinIO、Elasticsearch 等）编写独立的 Smoke Test，**禁止 Mock**，必须直连真实服务并执行至少一条简单查询/操作
2. **禁止用 Mock 测试替代真实验证**：集成测试中对外部服务的 mock 仅用于测试业务逻辑，不能替代对服务可达性/可用性的验证
3. **测试报告必须区分 Mock 与真实**：在输出测试结果时，必须明确标注：
   - 哪些测试使用了 Mock
   - 哪些测试使用了真实连接
   - 哪些外部服务尚未验证（如果有）
4. **Mock 测试通过 ≠ 系统可用**：单元测试/集成测试全部通过后，**必须额外执行真实环境 Smoke Test**，确认外部服务连接正常，才能报告"测试通过"
5. **新增外部服务依赖时同步添加 Smoke Test**：引入新的外部服务（数据库、缓存、队列、API 等），必须同步编写对应的连接验证测试文件
6. **E2E 测试必须覆盖核心业务流程**：每个项目至少有一条 E2E 测试覆盖"用户登录→核心功能操作→结果验证"的完整链路，所有服务均为真实连接，**禁止 Mock**
7. **E2E 测试通过是最终准入条件**：单元测试 + Smoke Test 全部通过后，还必须运行 E2E 测试确认全链路可用。**E2E 测试失败视为发布阻塞**

## 验证报告（强制输出）

每次完成测试后，**必须**输出一份结构化的验证报告，格式如下：

````markdown
## 测试验证报告

### 1. 单元测试（Mock）
- [x] 通过 / [ ] 失败
- Mock 的外部服务：PostgreSQL、Neo4j、Redis（列表）
- 覆盖用例：N 个

### 2. 集成测试
- [x] 通过 / [ ] 失败
- 真实连接的服务：PostgreSQL（是/否）、Neo4j（是/否）...
- Mock 的服务：......

### 3. 真实环境 Smoke Test
- [x] 通过 / [ ] 失败 / [ ] 跳过（原因：......）
- PostgreSQL 连接：✅ 正常 / ❌ 失败 / ⏭️ 跳过
- Neo4j 连接：✅ 正常 / ❌ 失败 / ⏭️ 跳过
- Redis 连接：✅ 正常 / ❌ 失败 / ⏭️ 跳过
- 其他服务：...

### 4. E2E 测试（端到端）
- [x] 通过 / [ ] 失败 / [ ] 跳过（原因：......）
- 覆盖链路：注册→登录→创建工作空间→...（列出关键步骤）
- 所有服务均为真实连接：是 / 否（说明原因）

### 5. 最终结论
- [x] **测试通过** — 所有 Mock 测试 + 真实环境 Smoke Test 均通过
- [ ] **测试不通过** — 以下服务未通过验证：...
- [ ] **部分验证** — 以下服务因环境不可用跳过：...（需人工确认）
````

> 注意：
> - 禁止伪造验证报告，必须基于实际运行结果填写
> - Smoke Test / E2E 跳过的必须注明明确原因（如"当前环境未部署 Neo4j"）
> - 最终结论为"测试通过"的前提是：**所有外部服务的 Smoke Test 均为 ✅ 正常，且 E2E 测试通过**（E2E 跳过时需在结论中说明并人工确认）
