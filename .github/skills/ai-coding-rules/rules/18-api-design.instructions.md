---
applyTo: never
---

# API Design Rules — API 设计规范

> **AI Summary**: 全面的 API 设计规范。覆盖 RESTful 设计、URL 结构、HTTP 方法/状态码、请求/响应格式、分页筛选、错误格式、版本化、认证鉴权、限流、文档、MCP 接口、WebSocket、向后兼容性。

## 设计原则

| 原则 | 说明 |
|------|------|
| **面向资源** | API 围绕资源（Resource）而非操作（Action）设计 |
| **约定大于配置** | 一致的命名、状态码、错误格式减少学习成本 |
| **演进式设计** | API 从简单的端点开始，按需扩展，避免过度设计 |
| **显式优于隐式** | 每个参数、状态码、错误都有明确含义 |
| **向后兼容** | 从不破坏现有客户端，兼容优先于完美 |
| **文档驱动** | API 文档在实现之前或同步编写 |

## RESTful 资源设计

**URL 结构：**
- 复数名词：`/users` 而非 `/user`
- kebab-case：`/order-items` 而非 `/orderItems`
- 小写：`/api/v1/users` 而非 `/API/V1/Users`
- 嵌套不超过 2 层：`/users/{id}/orders`
- 参数用查询字符串：`/users?status=active&page=1`

**HTTP 方法：**

| 方法 | 用途 | 幂等 | 请求体 |
|------|------|------|--------|
| GET | 获取资源 | ✅ | ❌ |
| POST | 创建资源 / 提交操作 | ❌ | 创建数据 |
| PUT | 全量替换 | ✅ | 完整资源 |
| PATCH | 部分更新 | ❌ | 增量数据 |
| DELETE | 删除资源 | ✅ | ❌ |

**状态码选择：**
- `200` 成功有返回体 / `201` 创建成功 / `204` 成功无返回体
- `400` 参数校验失败 / `401` 未认证 / `403` 无权限 / `404` 资源不存在
- `409` 冲突 / `422` 业务校验失败 / `429` 触发限流
- `500` 未捕获异常（不暴露细节）

## 请求与响应格式

**统一响应结构：**
```json
{"code":200,"message":"ok","data":{},"meta":{"request_id":"req_xxx","timestamp":"..."}}
```

**错误响应结构：**
```json
{"code":422,"message":"参数校验失败","error":{"type":"VALIDATION_ERROR","details":[{"field":"email","message":"邮箱格式不正确","code":"INVALID_FORMAT"}]}}
```

**分页参数：** `GET /users?page=1&page_size=20&sort=created_at&order=desc`

**分页响应：**
```json
{"code":200,"data":[],"meta":{"page":1,"page_size":20,"total":156,"has_next":true}}
```

大数据量（>10000 条）优先 cursor-based 或 keyset pagination。

## API 版本化

| 策略 | 说明 |
|------|------|
| URL 路径 | `/api/v1/users` — 推荐，简单直观 |
| 请求头 | `Accept: application/vnd.api+json;version=1` |
| 查询参数 | `/api/users?version=1` |

**向后兼容规则：**
- ✅ 允许：新增可选字段、新增端点、扩展枚举值、放宽输入约束
- ❌ 不允许：删除/重命名字段、修改已有端点 URL、减少枚举值、收紧输入约束

## 认证与鉴权

| 模式 | 说明 | 适用场景 |
|------|------|---------|
| API Key | `X-API-Key: xxx` | 服务间通信 |
| Bearer Token (JWT) | `Authorization: Bearer xxx` | 用户认证 |
| OAuth 2.0 | 授权码流程 | 第三方登录 |
| HMAC 签名 | 请求体 + 密钥签名 | 高安全性要求 |

**安全要求：** 所有 API 端点默认需要认证；Token 有过期时间；敏感操作需二次确认。

## 限流

**响应头：**
```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 57
Retry-After: 30
```

限流返回 `429 Too Many Requests`。

## MCP 接口规范

| 规范 | 说明 |
|------|------|
| Tool 命名 | `snake_case`，动词开头：`get_weather` |
| 参数定义 | JSON Schema，区分必填与非必填 |
| 返回值 | 结构化 `{content: [...], isError: bool}` 格式 |
| 错误处理 | `isError: true` + 可读错误信息 |
| 超时 | 每个工具默认 30s 超时 |

## WebSocket

统一 JSON 格式 `{type, payload, id, timestamp}`，心跳 ping/pong 检测连接健康，指数退避重连。

## API 审查清单

```
□ 资源命名：复数、小写、kebab-case
□ HTTP 方法：GET 幂等只读、PUT 幂等全覆盖
□ 状态码：用了最合适的，不使用 200 通吃
□ 错误格式：统一结构，有 type/code/details
□ 分页：大数据集有分页，考虑 cursor-based
□ 版本化：有版本策略，破坏性变更走新版本
□ 向后兼容：未删除/重命名字段
□ 认证：默认需要认证
□ 限流：有配额限制
□ 文档：OpenAPI 同步更新
```
