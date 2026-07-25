---
applyTo: never
---

# Code Review — Go 专项审查规则

> 审查 Go 代码时加载此文件，配合 `code-review` skill 的通用 7 维度审查流程使用。

## 错误处理

| 审查项 | 说明 |
|--------|------|
| **err 检查** | 每个返回 `error` 的调用是否都检查了 `err != nil` |
| **错误传播** | 错误是否用 `fmt.Errorf("context: %w", err)` 包裹上下文 |
| **sentinel error** | 哨兵错误是否用 `errors.Is` 检查错误链 |
| **错误转型** | 自定义错误类型是否用 `errors.As` 转型 |
| **错误忽略** | 是否有被显式忽略的错误（`_ = foo()`），是否有合理的理由 |
| **panic 限制** | `panic` / `recover` 是否仅用于不可恢复的错误 |
| **defer 清理** | 资源获取后是否立即 `defer` 释放（`Close`、`Unlock` 等） |

## 并发与 goroutine

| 审查项 | 说明 |
|--------|------|
| **goroutine 生命周期** | 每个 `go` 启动的 goroutine 是否有明确的退出条件 |
| **WaitGroup 使用** | `sync.WaitGroup` 的 `Add` 是否在 goroutine 外调用 |
| **channel 所有权** | 创建 channel 的 goroutine 是否负责关闭它 |
| **关闭已关 channel** | 是否有向已关闭的 channel 写数据的风险 |
| **context 传播** | 阻塞/网络/并发操作的函数是否接受 `ctx context.Context` 作为第一参数 |
| **select 超时** | channel 操作是否有 `select` + `time.After` 超时保护 |
| **竞态检测** | 共享状态是否有 `sync.Mutex` / `sync.RWMutex` 保护 |
| **errgroup** | 并发任务统一错误管理是否用 `errgroup` |
| **零值 channel** | `nil` channel 在 select 中是否被合理利用（禁用分支） |

## 接口与类型

| 审查项 | 说明 |
|--------|------|
| **小接口** | 接口定义是否保持 1-2 个方法，命名以 `er` 结尾 |
| **接受接口，返回结构** | 函数参数用接口，返回值用具体类型 |
| **any 替代** | 是否用 `any`（Go 1.18+）替代 `interface{}` |
| **零值有用** | 是否合理利用 Go 的零值初始化特性 |
| **泛型使用** | 泛型是否在明显有益时使用，避免过度抽象 |
| **类型嵌入** | 是否用结构体组合（嵌入）而非继承式设计 |

## 并发安全模式

| 审查项 | 说明 |
|--------|------|
| **Mutex 与 RWMutex** | 读多写少场景是否用 `sync.RWMutex` |
| **atomic 操作** | 简单计数器/标志位是否用 `sync/atomic` 而非 Mutex |
| **sync.Map** | 是否真的需要 `sync.Map`（高并发读+写、key 动态变化） |
| **Once** | 一次性初始化是否用 `sync.Once` |
| **Pool** | 热路径对象复用是否考虑 `sync.Pool` |
| **race detector** | 开发期间是否用 `-race` 运行了测试 |

## 包与文件组织

| 审查项 | 说明 |
|--------|------|
| **包名一致** | 包名是否与目录名一致（`package auth` 在 `auth/`） |
| **单一职责** | 一个包是否只做一件事，避免 `package util` / `package common` |
| **init() 管控** | 是否使用了不该用的 `init()`（优先显式初始化函数） |
| **测试文件** | 测试文件是否命名为 `*_test.go` |
| **命名导出** | 公开标识符是否有文档注释（以符号名开头） |

## 代码风格

| 审查项 | 说明 |
|--------|------|
| **简短声明** | 局部变量是否用 `:=` 声明 |
| **命名返回值** | 复杂函数是否用命名返回值提高可读性 |
| **表驱动测试** | 多组用例是否用 table-driven tests |
| **defer 位置** | defer 是否紧跟在资源获取之后 |
| **getter 风格** | 是否遵循 Go 惯例（`user.Name()` 而非 `user.GetName()`） |
| **iota 枚举** | 枚举值是否用 `iota` + 类型别名 |
| **import 分组** | import 是否按 标准库 → 第三方 → 本地 分组 |

## 性能

| 审查项 | 说明 |
|--------|------|
| **预分配 slice** | slice 大小已知时是否用 `make([]T, 0, n)` 预分配 |
| **字符串拼接** | 大量字符串拼接是否用 `strings.Builder` |
| **逃逸分析** | 热路径中是否有不必要的堆分配 |
| **I/O 缓冲** | 文件/网络读写是否使用了 buffered I/O |

## Lint 与工具链

| 审查项 | 说明 |
|--------|------|
| **go vet** | 是否通过了 `go vet ./...` 静态分析 |
| **golangci-lint** | 是否通过了 `golangci-lint run` |
| **go test** | 是否所有测试通过（`go test ./...`） |
| **-race 测试** | 并发代码是否通过了 `go test -race ./...` |
