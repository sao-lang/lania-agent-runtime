---
applyTo: never
---

# Database Rules — 数据库与 ORM 规范

> **AI Summary**: 数据库开发规范。覆盖 SQLite（项目主要存储）、ORM 使用（SQLAlchemy 等）、连接管理、迁移策略、查询优化、索引设计、事务管理、N+1 预防。

## 核心理念

> **"查询越少，速度越快。"** — 减少数据库交互次数是性能第一原则。
> **"索引是双刃剑。"** — 加索引加速查询，但减慢写入。

## 连接管理

| 检查项 | 说明 |
|--------|------|
| **连接池** | 是否使用连接池（`sqlite://?check_same_thread=False&pool_size=5`）而非每次新建连接 |
| **连接释放** | 连接是否在使用后正确归还池中（context manager） |
| **并发安全** | SQLite 在写并发时是否使用了 `WAL` 模式（`PRAGMA journal_mode=WAL`） |
| **超时设置** | 连接超时是否合理（`timeout` 参数），避免无限等待锁释放 |
| **连接泄漏** | 异常路径中连接是否被正确释放 |

### SQLite 优化

```sql
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA cache_size=-8000;
PRAGMA busy_timeout=5000;
PRAGMA foreign_keys=ON;
```

## ORM 使用规范

### 模型定义

| 检查项 | 说明 |
|--------|------|
| **类型安全** | ORM 模型字段类型是否精确 |
| **索引声明** | 频繁查询的字段是否声明了索引（`index=True`） |
| **唯一约束** | 业务上应唯一的字段是否有唯一约束 |
| **关系定义** | 外键关系是否正确定义了 `lazy` 加载策略 |
| **默认值** | 字段是否有合理的默认值 |
| **nullable** | 可空字段是否明确了 `nullable=True` |

### 查询优化

| 检查项 | 说明 |
|--------|------|
| **select 字段** | 限制返回字段，避免 SELECT * |
| **预加载关系** | 关联数据是否用 `joinedload` / `selectinload` / `prefetch_related` 预加载 |
| **延迟加载陷阱** | 循环中访问未加载的关系（N+1）是否已被识别 |
| **批量操作** | 循环内逐条 insert/update 是否可改为 `bulk_insert` / `bulk_update` |
| **count 优化** | 大表 count 是否使用近似值或缓存 |
| **分页查询** | 大数据量是否使用分页（LIMIT/OFFSET 或 cursor-based） |

### N+1 查询预防

```python
# ❌ N+1: 循环中访问未加载的关联
for user in users:
    print(user.orders)  # 每次触发 SQL

# ✅ 预加载
users = session.query(User).options(selectinload(User.orders)).all()
```

| ORM | N+1 预防 |
|-----|---------|
| SQLAlchemy | `joinedload()` / `selectinload()` |
| Django ORM | `select_related()` / `prefetch_related()` |
| Prisma | `include` / `select` 嵌套 |
| TypeORM | `relations` |
| GORM | `Preload("Orders")` |

### 事务管理

| 检查项 | 说明 |
|--------|------|
| **事务边界** | 事务是否包裹了最小必要操作（不在事务中做耗时 I/O） |
| **自动提交** | 是否依赖 ORM 的自动提交而非显式 `commit()` |
| **回滚处理** | 异常时事务是否回滚（`session.rollback()`） |
| **隔离级别** | 事务隔离级别是否适合当前场景 |
| **长事务** | 事务持有时间不应跨越 HTTP 请求或用户交互 |

## SQL 查询规范

| 检查项 | 说明 |
|--------|------|
| **参数化查询** | 使用参数化查询（`?` / `%s`），禁止字符串拼接 SQL |
| **SELECT \*** | 只选取需要的字段 |
| **LIMIT 子句** | 查询有 `LIMIT` 限制返回行数 |
| **WHERE 条件** | WHERE 条件利用了索引（避免在索引列上使用函数） |
| **EXISTS 优化** | `IN (SELECT ...)` 大数据集时改为 `EXISTS` |
| **EXPLAIN 验证** | 慢查询用 `EXPLAIN ANALYZE` 分析执行计划 |

## 索引设计

| 检查项 | 说明 |
|--------|------|
| **查询驱动** | 索引基于实际查询模式设计 |
| **复合索引顺序** | 等值条件列在前，范围条件列在后：`INDEX(a, c, b)` 匹配 `WHERE a=1 AND b>10 AND c='x'` |
| **索引覆盖** | 高频查询是否可以被覆盖索引满足 |
| **冗余索引** | 是否有重复/冗余索引（`(a,b)` 和 `(a)`） |
| **未使用索引** | 是否有建立了但从未使用的索引 |
| **索引维护** | SQLite 定期 `REINDEX` / `ANALYZE` |

## 迁移管理

| 检查项 | 说明 |
|--------|------|
| **版本管理** | 所有 schema 变更通过迁移脚本执行，禁止手动 DDL |
| **可逆性** | 每个迁移有 `upgrade` 和 `downgrade` 路径 |
| **原子性** | 迁移在单个事务中执行 |
| **迁移工具** | Python: Alembic, Go: golang-migrate, Rust: diesel |

## 数据库审查清单

```
□ 连接池：使用了连接池，无连接泄漏
□ WAL 模式：SQLite 开启了 WAL 模式
□ N+1 查询：ORM 查询已预加载关联数据
□ 批量操作：循环内无逐条 insert/update
□ 索引策略：关键查询字段有索引，无冗余索引
□ 参数化查询：所有 SQL 使用参数化，无拼接
□ 分页：大数据量查询有 LIMIT/OFFSET
□ SELECT *：只选取必要字段
□ 事务管理：事务范围最小化，异常时有回滚
□ 迁移管理：schema 变更通过迁移脚本
□ EXPLAIN：慢查询有 EXPLAIN 分析
```
