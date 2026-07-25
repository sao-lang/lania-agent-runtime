---
applyTo: never
---

# Code Review — Rust 专项审查规则

> 审查 Rust 代码时加载此文件，配合 `code-review` skill 的通用 7 维度审查流程使用。

## 错误处理

| 审查项 | 说明 |
|--------|------|
| **unwrap/panic 禁止** | 库代码中是否存在不应出现的 `unwrap()` / `expect()` / `panic!` |
| **Result 传播** | 是否用 `?` 操作符传播错误，而非手动 `match`/`unwrap` |
| **错误类型** | 库代码是否用 `thiserror` 定义错误类型；应用代码是否用 `anyhow` |
| **错误上下文** | 错误是否包含足够上下文（`context`/`with_context`） |
| **Option 处理** | 是否用 `unwrap_or`/`unwrap_or_else`/`ok_or` 处理 Option，而非直接 unwrap |
| **自定义 Error** | 错误类型是否实现了 `std::error::Error` + `Display` |

## 类型系统与借用

| 审查项 | 说明 |
|--------|------|
| **不必要的 clone** | 是否有不必要的 `.clone()`，能否用引用 `&T` 替代 |
| **借用规则** | 是否合理使用 `&T` / `&mut T`，有无不必要的所有权转移 |
| **生命周期** | 引用是否标注了正确的生命周期，有无不必要的生命周期参数 |
| **newtype 模式** | 原始类型包装是否用 newtype 模式利用类型安全 |
| **Copy vs Clone** | 仅当类型大小 ≤ 指针宽度时才实现 `Copy` |
| **trait 约束** | 复杂泛型约束是否用 `where` 子句提升可读性 |
| **derive** | 常用 trait 是否通过 `#[derive(Debug, Clone, PartialEq)]` 派生 |

## 模式匹配

| 审查项 | 说明 |
|--------|------|
| **穷尽匹配** | 有限状态/枚举是否用 `match` 穷尽处理（而非 if-else 链） |
| **if let 简洁** | 单分支匹配是否用 `if let` 而非完整 `match` |
| **守卫条件** | match arm 中是否合理使用了 `if` 守卫 |
| **解构** | 元组/结构体是否用解构匹配，而非逐字段访问 |

## unsafe 代码

| 审查项 | 说明 |
|--------|------|
| **Safety 注释** | 每个 `unsafe` 块是否有 `// SAFETY:` 注释说明前置条件 |
| **unsafe 最小化** | `unsafe` 范围是否最小（尽量在函数/块级别而非大型函数） |
| **不变量维护** | unsafe 代码是否维护了它假设的不变量 |
| **FFI 安全** | 外部函数调用是否检查了空指针、错误码和资源释放 |

## 并发与异步

| 审查项 | 说明 |
|--------|------|
| **Send/Sync** | 跨线程类型是否自动或手动实现了 `Send`/`Sync` |
| **锁范围** | `Mutex`/`RwLock` 的锁定范围是否最小化 |
| **async 函数** | async 函数中是否混入了阻塞调用（`std::thread::sleep` 等） |
| **Tokio 规范** | 是否使用 `tokio::spawn` 创建并发任务，Task 退出条件是否明确 |
| **channel 关闭** | channel 的发送端/接收端是否在合适的时机 drop |

## 迭代器与集合

| 审查项 | 说明 |
|--------|------|
| **迭代器链** | 循环是否可以用 `.iter()` → `.filter()` → `.map()` → `.collect()` 链替代 |
| **懒求值** | 迭代器操作是否是 lazy 的，是否在末尾正确 `.collect()` 或 `.for_each()` |
| **集合初始化** | 是否用 `with_capacity` 预分配容量避免多次 reallocation |
| **entry API** | HashMap/BTreeMap 操作是否用 `entry()` API 替代手动 `contains_key` + `insert` |

## 模块与可见性

| 审查项 | 说明 |
|--------|------|
| **pub 最小化** | 对外 API 是否最小化 `pub`，crate 内部用 `pub(crate)` |
| **模块结构** | 每个模块一个目录，`mod.rs` 是否只做重导出 |
| **re-export** | 是否通过 `pub use` 提供简洁的公共 API 路径 |
| **cfg 条件** | 平台特定代码是否用 `#[cfg(target_os = "...")]` 而非写死分支 |

## 测试

| 审查项 | 说明 |
|--------|------|
| **单元测试** | 核心逻辑是否有 `#[cfg(test)]` 模块下的 `#[test]` 函数 |
| **集成测试** | 库的公开 API 是否有 `tests/` 目录下的集成测试 |
| **错误路径** | 测试是否覆盖了错误路径和边界条件 |
| **文档测试** | 文档注释中的代码示例是否可作为测试运行 |

## Lint 与工具链

| 审查项 | 说明 |
|--------|------|
| **cargo fmt** | 是否通过了 `cargo fmt` 格式化检查 |
| **cargo clippy** | 是否通过了 `cargo clippy` lint 检查（无 warning） |
| **cargo test** | 是否所有测试通过（`cargo test`） |
| **dead code** | 是否有 `#[allow(dead_code)]` 掩盖的未使用代码 |
