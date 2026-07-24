---
applyTo: never
---

# Security Rules — 轻量安全编码规范

> 当任务涉及用户输入、认证、密钥管理、数据库查询、文件操作等安全敏感场景时加载。

## 密钥管理

- ❌ 禁止硬编码 API Key / Token / 密码
- ❌ 禁止将 `.env` 提交到 Git（加入 `.gitignore`，提供 `.env.example`）
- ❌ 禁止将密钥写入日志
- ✅ 从环境变量读取，启动时校验

## 常见漏洞速查

### SQL 注入
- ✅ 参数化查询，禁止拼接 SQL
- ORM（Prisma/SQLAlchemy 等）默认安全，避免 raw query

### XSS
- ✅ 用 `textContent` 而非 `innerHTML`
- React/Vue 默认转义，慎用 `dangerouslySetInnerHTML` / `v-html`

### 命令注入
- ✅ 用 `subprocess.run([...], shell=False)` 而非 `os.system()`
- 永远不要用字符串拼接构建命令

### 路径遍历
- ✅ 限制路径范围，使用 `os.path.normpath` + `startswith` 验证

## 认证最低要求

- 密码用 bcrypt/argon2 哈希，不自己实现
- JWT 设置合理过期时间，用 HTTP-only Secure SameSite Cookie
- 登录接口必须有速率限制

## 依赖安全

- 定期运行 `npm audit` / `cargo audit` / `pip audit`
- 关注 Dependabot 提醒
- 维护 lockfile
