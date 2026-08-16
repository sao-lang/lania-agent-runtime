# 示例与模板设计方案（v0.1）

> ⚠️ **本文档是 `agent-runtime-design.md` 的子文档**。阅读前请确保已理解主文档中的
> **Builder 接线**与各组件设计。
>
> 关联文档：
> - [`governance-component-design.md`](governance-component-design.md) — 护栏配置示例
> - [`gateway-design.md`](gateway-design.md) — 网关接入示例
> - [`testing-infrastructure-design.md`](testing-infrastructure-design.md) — E2E 模板
> - [`api-surface-extension-sdk-design.md`](api-surface-extension-sdk-design.md) — 扩展脚手架

## 0. 背景与目标

当前 README 有代码片段，但**没有可运行的参考工程**。外部开发者评估框架时
需要"跑起来就能看到效果"的样例。

本文档定义**示例与模板设计方案**：一组可运行、可测试、可扩展的参考工程，
覆盖从最小可用到治理完备的梯度。

## 1. 设计原则

### R1 梯度覆盖

```text
examples/
  hello-agent/          # 最小可用：Builder + 一个工具 + run()
  customer-service/     # 业务典型：PlanExecute + 工具 + 会话续聊
  governance-full/      # 治理完备：护栏 + 网关 + 观测（推荐组合）
  custom-extension/     # 扩展示范：自定义 Hook / Plugin / 协议后端
```

### R2 每个示例三件套

- `README.md`：启动步骤、架构说明、关键配置；
- 可运行入口（`main.py` 或 `app.py`）；
- 测试（`tests/`，跑通即验收）。

### R3 示例不重复实现框架

示例只使用公共 API 与配置，不 import 内部 `_` 模块
（同时验证公共 API 面设计是否够用）。

### R4 模板可复制

`custom-extension/` 与脚手架（api-surface 设计）配合：
复制目录 → 改名 → 填业务逻辑 → 跑通。

## 2. 示例规格

### 2.1 hello-agent

- Builder + `react` + 1 个工具 + `run("...")`；
- 展示：system_prompt、工具注册、结果解析。

### 2.2 customer-service

- `plan_and_execute` + 订单查询工具 + SessionService 续聊（同一 session_id 二次调用）；
- 展示：规划、工具、会话恢复。

### 2.3 governance-full

- 护栏（budget / approval / audit）+ 网关（REST + SSE）+ 观测（日志 / 指标）；
- 展示：`POST /v1/chat`、`/v1/chat/stream`、审批 approve、审计落库；
- 配置以 YAML 为主（`config.yaml`），验证配置驱动。

### 2.4 custom-extension

- 自定义 Hook（Observer）+ 自定义 Plugin + 自定义协议后端（如自定义 AuditSink）；
- 展示：扩展四类写法 + 契约校验 + 测试。

## 3. 目录结构

```text
examples/
  hello-agent/{main.py, README.md, tests/}
  customer-service/{main.py, config.yaml, README.md, tests/}
  governance-full/{app.py, config.yaml, README.md, tests/}
  custom-extension/{extension.py, README.md, tests/}
```

## 4. 验收标准

- 每个示例 `python main.py` / `uvicorn app:app` 可启动；
- 每个示例测试全绿（可纳入 CI）；
- 示例只使用公共 API（`_` 内部模块出现即视为失败）；
- governance-full 演示完整链路：对话 → 工具 → 审批暂停 → approve → 恢复 → 审计可见。

## 5. 实施顺序

| 步 | 内容 | 验收 |
|----|------|------|
| 1 | hello-agent | 最小链路跑通 |
| 2 | customer-service | 续聊跑通 |
| 3 | governance-full（依赖护栏 / 网关实现） | 全链路 + 审批 + 审计 |
| 4 | custom-extension | 四类扩展示范跑通 |

每步完成即：示例测试全绿、ruff 零报错、README 文档同步。

## 6. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 示例与框架演进脱节 | 示例纳入 CI（依赖版本锁定） |
| 示例掩盖内部模块 | R3 强制公共 API 检查 |
| governance-full 依赖未实现组件 | 排在护栏 / 网关实现之后，避免空转 |

## 7. 待确认决策

| 编号 | 决策 | 推荐 |
|------|------|------|
| D1 | 示例目录位置 | `examples/`（推荐，repo 内）vs 独立仓库 |
| D2 | 示例纳入 CI | 纳入（推荐）vs 手动维护 |
| D3 | governance-full 前置 | 等护栏 + 网关实现后再建（推荐） |

## 附录 A：文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `examples/*/{main.py, app.py, config.yaml, README.md, tests/}` | 新增 | 参考工程 |
| `pyproject.toml` | 修改（可选） | 示例测试纳入 pytest 路径 |

## 附录 B：修订记录

| 版本 | 日期 | 说明 |
|------|------|------|
| v0.1 | 2026-08-17 | 初稿 |