# 打包与发布设计方案（v0.1）

> ⚠️ **本文档是 `agent-runtime-design.md` 的子文档**。阅读前请确保已理解
> `pyproject.toml`（hatchling / uv）与组件边界。
>
> 关联文档：
> - [`api-surface-extension-sdk-design.md`](api-surface-extension-sdk-design.md) — 版本化（semver）与废弃流程
> - [`governance-component-design.md`](governance-component-design.md) / [`gateway-design.md`](gateway-design.md) — 新组件打包范围
> - [`observability-design.md`](observability-design.md) / [`lifecycle-agent-registry-design.md`](lifecycle-agent-registry-design.md) — 同上

## 0. 背景与目标

当前 `0.1.0`、hatchling 构建、wheel 只包含 `src/runtime` 与 `src/session`，
其余组件（memory / context / tools / intent 等）**不在 wheel 内**——
`pip install` 后的包不可用。

本文档定义**打包与发布设计方案**：wheel 内容完整、可选 extras、
版本矩阵、发布流程与 CHANGELOG，让框架可被外部工程正式安装使用。

## 1. 现状盘点

| 项 | 状态 |
|----|------|
| 版本号 | ⚠️ 0.1.0（无 semver 流程） |
| 构建后端（hatchling）+ uv | ✅ 已配置 |
| wheel 内容 | ❌ 仅 runtime / session，不完整 |
| 可选 extras（gateway / governance / observability） | ❌ 缺失 |
| Python 版本矩阵 | ⚠️ 仅声明 ≥3.10 |
| 发布流程 / CHANGELOG / tag | ❌ 缺失 |

## 2. 设计原则

### R1 wheel 自包含

`pip install lania-agent-runtime` 后，`import src.runtime` 及全部组件可用。
wheel 包含：runtime / session / memory / context / tools / intent / llm / loops /
pipeline / plugins / hooks（以及随版本加入的 governance / gateway / observability / lifecycle）。

### R2 可选依赖用 extras

| extra | 内容 |
|-------|------|
| 默认 | 核心运行（openai / pydantic / pyyaml / tomli） |
| `gateway` | fastapi / uvicorn / httpx-sse |
| `governance` | 无额外依赖（纯实现） |
| `observability` | prometheus-client（如 D3 选 Prometheus） |
| `dev` | pytest / ruff / pytest-cov / pytest-asyncio / pytest-benchmark |

### R3 包名与导入路径

- 保持 `src.*` 顶层包结构（`src.runtime` 等），避免大重构；
- 发布名：`lania-agent-runtime`（与 pyproject 一致）；
- 若未来需要 `lania_agent_runtime` 顶层别名，走兼容层而非移动源码。

### R4 版本与发布流程

- semver（见 api-surface 设计）：`0.x` 阶段实验组件可小版本调整；
- 发布流程：
  1. `uv lock` 更新 + `uv build`（sdist + wheel）；
  2. `uv publish`（PyPI，需凭证）；
  3. `git tag vX.Y.Z` + 推送；
  4. CHANGELOG 更新（Keep a Changelog 风格）；
- CI：`uv build` + 安装产物冒烟（`pip install dist/*.whl` 后 import + 跑 smoke）。

## 3. 实施顺序

| 步 | 内容 | 验收 |
|----|------|------|
| 1 | 修正 wheel packages（纳入全部现有组件） | `pip install` 后 import 冒烟通过 |
| 2 | extras 拆分（gateway / governance / observability / dev） | 各 extra 安装可用 |
| 3 | Python 版本矩阵（3.10–3.13）CI | 矩阵全绿 |
| 4 | 发布流程脚本（build / tag / changelog） | 本地演练通过 |
| 5 | 首个 0.2.0 发布（含新组件） | PyPI 安装冒烟 |

每步完成即：全量测试通过、覆盖率 ≥96%、ruff 零报错、文档同步。

## 4. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 顶层 `src.*` 命名与生态冲突 | 保持现状，必要时加兼容别名 |
| extras 依赖版本漂移 | lock 文件按 extra 分组维护 |
| 发布后才发现缺文件 | CI 安装产物冒烟（import + smoke） |
| 破坏性变更未走 semver | api-surface 评审门禁 + CHANGELOG |

## 5. 待确认决策

| 编号 | 决策 | 推荐 |
|------|------|------|
| D1 | 首个正式发布版本 | 0.2.0（纳入新组件后，推荐） |
| D2 | 发布渠道 | PyPI 官方（推荐）vs 私有源 |
| D3 | 观测 extra 依赖 | 保持零额外依赖（推荐）vs prometheus-client |

## 附录 A：文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `pyproject.toml` | 修改 | wheel packages / extras / 版本 |
| `CHANGELOG.md` | 新增 | 变更记录 |
| `scripts/release.ps1`（或 .sh） | 新增 | 构建 / tag / 发布脚本 |
| `.github/workflows/release.yml` | 新增（可选） | CI 发布流水线 |

## 附录 B：修订记录

| 版本 | 日期 | 说明 |
|------|------|------|
| v0.1 | 2026-08-17 | 初稿 |