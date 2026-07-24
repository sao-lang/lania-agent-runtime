---
name: commit-rules
description: 'Use when: committing code, writing commit messages, pushing changes, or managing Git history. Triggers: "git commit", "提交", "push", "commit", "提交信息". Provides Conventional Commits规范, 提交粒度原则, 推送策略.'
user-invocable: true
---

# Commit Rules — Git 提交规范

> **AI Summary**: Git 提交与推送规范。Conventional Commits 格式、原子提交原则、推送策略。

## 核心规范

### 提交信息格式

```
<type>(<scope>): <subject>

<body>

<footer>
```

| 部分 | 必填 | 说明 |
|------|------|------|
| `type` | ✅ | 提交类型（见下方） |
| `scope` | ❌ | 影响范围（模块/组件名） |
| `subject` | ✅ | 简短描述（≤ 72 字符，首字母小写，无句号） |
| `body` | ❌ | 详细描述（动机：为什么改，而非改了什么） |
| `footer` | ❌ | BREAKING CHANGE、关联 Issue 等 |

### 提交类型

| type | 用途 |
|------|------|
| `feat` | 新功能 |
| `fix` | Bug 修复 |
| `refactor` | 重构（不改变外部行为） |
| `perf` | 性能优化 |
| `test` | 测试相关 |
| `docs` | 文档变更 |
| `style` | 代码格式（不影响功能） |
| `chore` | 构建/工具/依赖变更 |
| `ci` | CI 配置变更 |
| `revert` | 回退提交 |

### 示例

```
feat(auth): 增加 Token 刷新接口

登录凭证过期后自动调用刷新接口获取新 Token，
避免用户频繁重新登录。

Closes #123
```

```
fix(api): 修复分页查询总数不准确

排序字段为空时 COUNT 查询结果与数据行数不匹配，
在排序前单独执行 COUNT 查询。

BREAKING CHANGE: 分页响应格式从 {total, items} 改为 {total, data}
```

## 提交原则

### 原子提交

- 每次提交只做一件事：一个功能、一个修复、一个重构
- 如果改了 3 个不相关的文件，拆成 3 次提交
- 允许在提交信息中用 `|` 分隔多个关联变更

### 信息撰写

- **Subject**：用动词开头（增加/修复/重构/优化），英文用祈使句
- **Body**：写动机（why）而非内容（what）——代码本身已经说明了 what
- **Breaking Change**：在 footer 标注 `BREAKING CHANGE:` 并说明影响

## 推送策略

### 推送前

```powershell
# 先拉取远程变更，避免冲突
git pull --rebase
```

### 推送命令

| 场景 | 命令 |
|------|------|
| 全量推送 | `git add . && git commit -m "<msg>" && git push` |
| 精细推送 | `git add <files> && git commit -m "<msg>" && git push` |
| 修改上次提交 | `git commit --amend` |
| 推送新分支 | `git push -u origin <branch>` |

### 推送后

提交完成后列出本次修改的文件总结：

```
📦 修改文件:
  src/auth/service.ts    (新增 42 行)
  src/auth/types.ts      (修改 8 行)
  tests/auth.test.ts     (新增 15 行)
```

## Git 历史管理

- **不要 rebase 已推送的公共分支**（main/master/release）
- **本地分支**：用 `rebase` 保持线性历史
- **合并**：优先 `--no-ff` 保留分支信息
- **回退**：已推送用 `git revert`，未推送用 `git reset`
