# Memory System 技术方案文档

> ⚠️ **本文档是 `agent-runtime-design.md` 的子文档**。阅读前请确保已理解主文档中的 **ContextPayload**（§5）和 **Hook 治理组件**（§8 #17 Memory Bank）。
>
> 关联文档：[`context-management-redesign.md`](context-management-redesign.md) — ContextManager 读取记忆
> 主文档：[`agent-runtime-design.md`](agent-runtime-design.md)

> 基于 agent-runtime-design.md 的五层记忆架构，定义存储接口、引擎选型、数据流和管理策略。

---

## 目录

1. [架构总览](#1-架构总览)
2. [五层记忆定义](#2-五层记忆定义)
3. [存储接口设计](#3-存储接口设计)
4. [存储引擎实现](#4-存储引擎实现)
5. [数据流管线](#5-数据流管线)
6. [管理策略](#6-管理策略)
7. [集成到 Runtime](#7-集成到-runtime)

---

## 1. 架构总览

### 1.1 五层记忆分层

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 1: Working Memory (工作记忆)                         │
│  内容: 当前 LLM 调用看到的一切 + Runtime 执行状态             │
│  生命周期: 单次 LLM 调用 (持久化仅用于崩溃恢复 / 暂停恢复)    │
│  存储: 覆盖写, TTL 自动过期                                  │
├─────────────────────────────────────────────────────────────┤
│  Layer 2: Episodic Memory (情景记忆)                         │
│  内容: 原始对话记录 / 压缩后的摘要轮次                        │
│  生命周期: Session 级至跨 Session，按 TTL 或合并后淘汰        │
│  存储: append-only, 时间序 + 语义索引                        │
├─────────────────────────────────────────────────────────────┤
│  Layer 3: Entity Memory (实体记忆)                           │
│  内容: 从对话中提取的结构化实体属性 (用户画像 / 项目信息等)    │
│  生命周期: 跨 Session，长期保留                              │
│  存储: upsert, 保留变更历史                                  │
├─────────────────────────────────────────────────────────────┤
│  Layer 4: Semantic Knowledge (语义知识)                      │
│  内容: 概念定义、术语关系、知识图谱                           │
│  生命周期: 跨 Session，永久                                  │
│  存储: 图结构 (节点 + 边), 支持向量检索                      │
├─────────────────────────────────────────────────────────────┤
│  Layer 5: Behavioral Pattern (行为模式)                      │
│  内容: 从交互历史统计收敛的风格 / 偏好 / 活跃时间            │
│  生命周期: 跨 Session，长期，定期重新收敛                     │
│  存储: 按用户单行, 全量覆盖                                  │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 层间依赖关系

```
                   写入管线 (after_step 异步触发)
                   ┌────────────────────────────┐
                   │  用户回复 / Tool 结果       │
                   │            │               │
                   │            ▼               │
                   │  ┌──────────────────┐      │
                   │  │  Layer 2: 写入   │      │
                   │  │  原始 + 摘要     │      │
                   │  └───────┬──────────┘      │
                   │          │ 提取实体        │
                   │          ▼                 │
                   │  ┌──────────────────┐      │
                   │  │  Layer 3: UPSERT │      │
                   │  │  属性变更历史     │      │
                   │  └───────┬──────────┘      │
                   │          │ 提炼概念关系    │
                   │          ▼                 │
                   │  ┌──────────────────┐      │
                   │  │  Layer 4: MERGE  │      │
                   │  │  节点 + 边       │      │
                   │  └───────┬──────────┘      │
                   │          │ 累积采样触发    │
                   │          ▼                 │
                   │  ┌──────────────────┐      │
                   │  │  Layer 5: 收敛   │      │
                   │  │  模式重新计算    │      │
                   │  └──────────────────┘      │
                   └────────────────────────────┘

                   读取管线 (before_step 同步组合)
                   ┌────────────────────────────┐
                   │  当前用户消息               │
                   │            │               │
                   │            ▼               │
                   │  ┌──────────────────┐      │
                   │  │  Layer 5: 读风格  │──────┤──→ tone_instruction
                   │  └──────────────────┘      │
                   │            │               │
                   │            ▼               │
                   │  ┌──────────────────┐      │
                   │  │  Layer 4: 检索   │──────┤──→ relevant_concepts
                   │  │  语义相关概念    │      │
                   │  └──────────────────┘      │
                   │            │               │
                   │            ▼               │
                   │  ┌──────────────────┐      │
                   │  │  Layer 3: 读画像 │──────┤──→ entity_profile
                   │  │  实体全量属性    │      │
                   │  └──────────────────┘      │
                   │            │               │
                   │            ▼               │
                   │  ┌──────────────────┐      │
                   │  │  Layer 2: 读记忆 │──────┤──→ memories
                   │  │  最近 N 轮 + 相关│      │
                   │  └──────────────────┘      │
                   │            │               │
                   │            ▼               │
                   │  ┌──────────────────┐      │
                   │  │  TokenManager    │      │
                   │  │  按优先级裁剪    │      │
                   │  └───────┬──────────┘      │
                   │          ▼                 │
                   │  ┌──────────────────┐      │
                   │  │  contextPayload  │      │
                   │  │  → serialize()    │      │
                   │  │  → messages[]    │      │
                   │  └──────────────────┘      │
                   └────────────────────────────┘
```

---

## 2. 五层记忆定义

### 2.1 Layer 1: Working Memory (工作记忆)

工作记忆是 Runtime 当前执行状态的**完整序列化快照**，仅在以下之一发生时持久化：

- Runtime 进入 paused 状态（Human approval 等待）
- 发生非致命错误（容错恢复）
- 主动 checkpoint（长耗时操作前）

> 不是每次 step 后都写，写入频率极低。

#### 字段定义

```
WorkingMemorySnapshot {
    // ── 主键 ──
    session_id:     string              // 会话 ID
    step_index:     int                 // 快照时刻的步数

    // ── 完整消息缓存 ──
    messages:       Message[]           // 完整的 messages 数组
    message_count:  int                 // 消息数量
    total_tokens:   int                 // 已知总 token 数（避免重算）

    // ── ContextPayload 快照 ──
    context_payload: {
        system_prompt:      string
        memories:           MemoryEntry[]
        rag_documents:      RagDocument[]
        injected_context:   string[]
        history:            Message[]
        priority_hints:     PriorityHints
    }

    // ── Runtime 执行状态 ──
    status:         "running" | "paused" | "error"
    plan:           Plan | null
    budget: {
        token_used:     int
        token_limit:    int
        step_count:     int
        step_limit:     int
        cost_in_cents:  int
    }
    pause_state: {
        is_paused:            bool
        pending_approvals:    ApprovalRequest[]
        resume_token:         string | null
    }
    error_state: {
        consecutive_errors:   int
        max_retries:          int
        last_error:           { type: string, message: string } | null
    }

    // ── Hook 链状态（如果有第三方治理组件需要 checkpoint）──
    hook_states:    dict[string, any]   // { hook_name: checkpoint_data }

    // ── 元信息 ──
    captured_at:    datetime            // 快照时间
    version:        int                 // 快照格式版本号
    ttl:            int                 // 过期秒数
}
```

#### 约束

- 一个 session 只保留最新的一个快照（覆盖写）
- TTL 默认 3600 秒（1 小时），超时自动清理
- 快照内容不可变：一旦写入，不允许修改

---

### 2.2 Layer 2: Episodic Memory (情景记忆)

情景记忆是**时序化的对话轮次**。每轮用户+AI对话被压缩为一条或多条记录。

#### 字段定义

```
EpisodicMemoryEntry {
    // ── 主键 ──
    id:             string[UUID]        // 全局唯一
    session_id:     string              // 所属会话
    user_id:        string              // 所属用户

    // ── 时序 ──
    turn_index:     int                 // 第几轮对话 (0-based)
    created_at:     datetime            // 写入时间

    // ── 内容 ──
    summary:        string              // 压缩后的内容 (必填)
    raw_content:    string | null       // 原始对话全文 (可选)
    content_type:   "raw" | "summary" | "critical_event"

    // ── 来源 ──
    source: {
        user_message:       string | null
        assistant_message:  string | null
        tool_calls:         { tool_name: string, args: any, result: string }[]
    }

    // ── 标签 (辅助索引) ──
    entities:       string[]            // 提及的实体名
    topics:         string[]            // 话题标签
    keywords:       string[]            // 关键词
    importance:     float               // 0.0 ~ 1.0, 信息密度评分

    // ── Token 统计 ──
    token_count:    int                 // 原始 token 数

    // ── 层级关联 ──
    merged_to:      string[UUID] | null // 如果被合并, 指向目标摘要 ID
    merged_from:    string[UUID][]      // 如果本条是合并结果, 包含源 IDs
}
```

#### 索引需求

| 查询 | 索引 | 说明 |
|------|------|------|
| 最近 N 轮 | `(session_id, turn_index DESC)` | 取最近对话历史 |
| 跨 session 记忆 | `(user_id, created_at DESC)` | 检索用户所有历史 |
| 语义关联检索 | `(entities)` 或向量索引 | 查用户提过的某实体相关 |
| 未合并原始记录 | `(merged_to IS NULL)` | 待合并的候选 |
| 重要性排序 | `(user_id, importance DESC)` | 优先召回高价值记忆 |

---

### 2.3 Layer 3: Entity Memory (实体记忆)

实体记忆以**实体为中心**，每个实体（用户、项目、组织等）一行，属性是动态扩展的 JSON 结构。

#### 字段定义

```
EntityMemoryEntry {
    // ── 主键 ──
    entity_type:    string              // "user" | "project" | "organization"
    entity_key:     string              // 实体标识, 如 "user-9527"

    // ── 属性 (动态 schema) ──
    // 每个值包含 value + confidence + recorded_at
    attributes: {
        [attr_name: string]: {
            value:          any
            confidence:     float       // 0.0 ~ 1.0
            recorded_at:    datetime
            source_session: string      // 来源 session_id
        }
    }

    // ── 变更历史 ──
    // 每个属性历次变更的记录
    history: {
        [attr_name: string]: {
            value:          any
            confidence:     float
            recorded_at:    datetime
            source_session: string
        }[]
    }

    // ── 元信息 ──
    created_at:         datetime
    last_updated_at:    datetime
    last_source_session: string
    ttl:                datetime | null // 过期时间, null 表示永久
}
```

#### 存储约束

- 主键 `(entity_type, entity_key)` 唯一，用 UPSERT 语义
- `attributes` 的每个属性变更时，**同时追写** `history`
- `history` 数组按时间升序排列，保留最近 N 次（默认 20 次）
- 当 `history` 溢出时，丢弃最旧的记录

---

### 2.4 Layer 4: Semantic Knowledge (语义知识)

语义知识是**概念之间的关联图谱**，分为节点和边两张表。

#### 节点定义

```
SemanticNode {
    id:             string[UUID]        // 节点唯一 ID
    name:           string              // 概念名称, 如 "WorkingMemory"
    type:           "concept" | "term" | "framework" | "tool" | "person"

    description:    string              // 概念定义
    aliases:        string[]            // 别名列表

    embedding:      float[] | null      // 向量 (用于语义检索)
    embedding_dim:  int | null          // 向量维度

    // 统计
    mention_count:  int                 // 在对话中被提及次数
    first_seen_at:  datetime
    last_seen_at:   datetime

    // 来源
    source:         "extracted_from_dialogue" | "external_knowledge"

    created_at:     datetime
}
```

#### 边定义

```
SemanticEdge {
    id:             string[UUID]        // 边唯一 ID
    source_node:    string[UUID]        // 源节点 ID → SemanticNode.id
    target_node:    string[UUID]        // 目标节点 ID → SemanticNode.id
    relation:       string              // 关系类型

    // 关系类型枚举:
    //   "is_a"           — Python is_a 编程语言
    //   "part_of"        — AgentRuntime part_of AgentSystem
    //   "related_to"     — Memory related_to ContextPayload
    //   "used_by"        — FastAPI used_by 数据管道
    //   "prerequisite"   — Python prerequisite FastAPI
    //   "opposite_of"    — 同步 opposite_of 异步

    confidence:     float               // 0.0 ~ 1.0
    source:         "extracted" | "inferred" | "confirmed"

    created_at:     datetime
    last_confirmed_at: datetime | null  // 被后续对话确认的时间
}
```

#### 查询模式

```
-- 查某个节点的直接邻居
SELECT n.*, e.relation
FROM semantic_node n
JOIN semantic_edge e ON e.target_node = n.id OR e.source_node = n.id
WHERE e.source_node = ? OR e.target_node = ?
  AND n.id != ?;

-- 语义检索节点
SELECT n.*, cosine_similarity(n.embedding, ?) AS score
FROM semantic_node n
WHERE n.embedding IS NOT NULL
ORDER BY score DESC
LIMIT 5;

-- 查路径 (两概念之间的关系链)
-- 使用递归 CTE
WITH RECURSIVE path AS (
    SELECT source_node, target_node, relation, 1 AS depth
    FROM semantic_edge WHERE source_node = ?
    UNION ALL
    SELECT e.source_node, e.target_node, e.relation, p.depth + 1
    FROM semantic_edge e JOIN path p ON e.source_node = p.target_node
    WHERE p.depth < 5
)
SELECT * FROM path WHERE target_node = ?;
```

---

### 2.5 Layer 5: Behavioral Pattern (行为模式)

行为模式是**统计收敛后的用户特征**, 每个用户一行。

#### 字段定义

```
BehavioralPattern {
    // ── 主键 ──
    user_id:        string              // 用户唯一 ID

    // ── 模式数据 (动态 JSON) ──
    patterns: {
        // 沟通风格
        communication_style?: {
            value:              string      // "先原理后实现" | "直接给方案" etc.
            confidence:         float
            sample_count:       int
            evidence_sessions:  string[]    // 证据来源 session_id 列表
        }

        // 偏好深度
        depth_preference?: {
            value:              "shallow" | "moderate" | "deep"
            confidence:         float
            sample_count:       int
        }

        // 活跃时段
        active_hours?: {
            hourly_distribution:    int[]       // 24 小时, 每小时交互次数
            peak_start_hour:        int         // 峰值开始
            peak_end_hour:          int         // 峰值结束
            total_days_observed:    int
        }

        // 话题频率
        topic_frequency?: {
            [topic: string]: int    // 话题名 → 提及次数
        }

        // 通用模式 (动态扩展)
        [pattern_name: string]: {
            value:              any
            confidence:         float
            sample_count:       int
            last_updated:       datetime
        }
    }

    // ── 元信息 ──
    total_interactions:     int         // 参与统计的总交互数
    version:                int         // 收敛版本号
    last_converged_at:      datetime    // 最近一次收敛时间
    last_interaction_at:    datetime    // 最近一次交互时间
    created_at:             datetime
}
```

#### 更新语义

行为模式**不是单次写入**，而是**聚合收敛**：

```
on after_step:
  // 本轮对话采样
  sampling.record_style(user_id, detected_style)
  sampling.record_topics(user_id, detected_topics)
  sampling.record_hour(user_id, current_hour)

  // 当采样数达到阈值时触发收敛
  if sampling.count(user_id) >= CONVERGENCE_THRESHOLD (默认=10):
    pattern = behavioral_store.read(user_id)
    pattern.patterns.communication_style = sampling.converge_style(user_id)
    pattern.patterns.topic_frequency = sampling.converge_topics(user_id)
    pattern.version += 1
    pattern.last_converged_at = now()
    behavioral_store.write(user_id, pattern)
    sampling.reset(user_id)
```

收敛阈值之前的采样数据存在**内存缓冲**中，不写数据库。只有收敛结果才持久化。

> ⚠️ **风险**：如果 Runtime 在采样达到阈值前崩溃（如第 9/10 次交互时），
> 这 9 次采样的模式数据将全部丢失。对于行为模式这种低频收敛的特性可以接受，
> 但如果需要零丢失保证，应改为每次采样都持久化。

---

## 3. 存储接口设计

### 3.1 统一外观接口

对上层（Runtime、治理组件）暴露统一的 `MemoryService`：

```python
class MemoryService:
    """
    记忆系统统一外观。
    上层只感知这一个入口，不感知内部五层的存储差异。
    """

    def __init__(
        self,
        working_store: WorkingMemoryStore,
        episodic_store: EpisodicMemoryStore,
        entity_store: EntityMemoryStore,
        semantic_store: SemanticKnowledgeStore,
        pattern_store: BehavioralPatternStore,
    ):
        self._working = working_store
        self._episodic = episodic_store
        self._entity = entity_store
        self._semantic = semantic_store
        self._pattern = pattern_store

    # ── 读取管线 (before_step 调用) ──

    async def recall(
        self,
        session_id: str,
        user_id: str | None,
        query: str,
        *,
        max_tokens: int = 4096,
    ) -> ContextPayload:
        """
        五层组合读取, 返回已裁剪的 ContextPayload。
        """
        # 1. 读行为模式 → tone 指令
        tone = ""
        if user_id:
            pattern = await self._pattern.read(user_id)
            if pattern and "communication_style" in pattern.patterns:
                tone = self._format_tone(pattern)

        # 2. 读语义知识 → 相关概念
        concepts = await self._semantic.search(query, top_k=3)

        # 3. 读实体画像 → 用户/项目属性
        profile = {}
        if user_id:
            entity = await self._entity.read("user", user_id)
            if entity:
                profile = self._extract_attributes(entity)

        # 4. 读情景记忆 → 最近 N 轮 + 相关历史
        memories = await self._episodic.recall_session(
            session_id=session_id,
            limit=10,
        )
        if user_id:
            related = await self._episodic.search_by_entities(
                user_id=user_id,
                entities=list(profile.keys()),
                limit=5,
            )
            memories.extend(related)

        # 5. Token 裁剪
        payload = ContextPayload(
            tone_instruction=tone,
            concepts=concepts,
            entity_profile=profile,
            memories=memories,
            priority_hints=PriorityHints(
                max_tokens=max_tokens,
                preserve_last_n_history=3,
                reserve_for_response=1024,
            ),
        )
        return self._trim(payload)

    # ── 写入管线 (after_step 调用) ──

    async def commit(
        self,
        session_id: str,
        user_id: str | None,
        step_context: StepContext,
    ):
        """
        五层写入, 各层内部决定是否写、写什么。
        """
        # Layer 2: 始终写入情景记忆
        entry = await self._episodic.create_entry(session_id, user_id, step_context)
        entry_id = await self._episodic.write(entry)

        # Layer 3-5: 异步触发 (不阻塞回复)
        if user_id:
            asyncio.create_task(
                self._safe_background_task(
                    self._entity_extraction_pipeline(user_id, session_id, step_context),
                    f"entity_extraction({user_id}, {session_id})",
                )
            )

    async def _safe_background_task(self, coro, name: str) -> None:
        """安全的后台任务执行器——捕获异常并记录，不吞没错误。"""
        try:
            await coro
        except Exception as e:
            logger.error(f"Background task '{name}' failed: {type(e).__name__}: {e}")

    # ── 工作记忆快照 ──

    async def checkpoint(self, snapshot: WorkingMemorySnapshot):
        """保存工作记忆快照 (覆盖写)"""
        await self._working.save(snapshot)

    async def restore(self, session_id: str) -> WorkingMemorySnapshot | None:
        """恢复工作记忆快照"""
        return await self._working.load(session_id)

    async def discard_checkpoint(self, session_id: str):
        """丢弃工作记忆快照 (正常完成后清理)"""
        await self._working.delete(session_id)
```

### 3.2 各层 Store 接口

#### WorkingMemoryStore (工作记忆)

```python
class WorkingMemoryStore(ABC):
    """
    工作记忆存储接口。

    特性:
    - 覆盖写 (一个 session 只保留最新快照)
    - TTL 自动过期
    - 一次性的: 恢复后即刻删除
    """

    @abstractmethod
    async def save(self, snapshot: WorkingMemorySnapshot):
        """
        保存快照。覆盖 session_id 对应的现有快照。
        自动设置 TTL (默认 3600s)。
        """
        ...

    @abstractmethod
    async def load(self, session_id: str) -> WorkingMemorySnapshot | None:
        """加载快照。返回 None 表示已过期或不存在。"""

    @abstractmethod
    async def delete(self, session_id: str):
        """删除快照。恢复后或正常结束时调用。"""

    @abstractmethod
    async def exists(self, session_id: str) -> bool:
        """检查快照是否存在且未过期。"""
```

#### EpisodicMemoryStore (情景记忆)

```python
class EpisodicMemoryStore(ABC):
    """
    情景记忆存储接口。

    特性:
    - append-only (写入后不修改, 仅 merged_to 字段可更新)
    - 时间序索引 + 标签索引
    - 支持按实体/话题检索
    """

    @abstractmethod
    async def write(self, entry: EpisodicMemoryEntry) -> str:
        """写入一条情景记忆。返回 entry.id。"""
        ...

    @abstractmethod
    async def write_batch(self, entries: list[EpisodicMemoryEntry]) -> list[str]:
        """批量写入。"""

    @abstractmethod
    async def recall_session(
        self,
        session_id: str,
        *,
        limit: int = 20,
        offset: int = 0,
        min_importance: float = 0.0,
    ) -> list[EpisodicMemoryEntry]:
        """
        按 session 召回, 按 turn_index DESC 排序。
        min_importance: 只返回重要性 >= 此值的记录。
        """

    @abstractmethod
    async def recall_user(
        self,
        user_id: str,
        *,
        limit: int = 20,
        offset: int = 0,
        since: datetime | None = None,
    ) -> list[EpisodicMemoryEntry]:
        """
        按用户跨 session 召回, 按 created_at DESC 排序。
        since: 只返回此时间之后的记录。
        """

    @abstractmethod
    async def search_by_entities(
        self,
        user_id: str,
        entities: list[str],
        *,
        limit: int = 10,
    ) -> list[EpisodicMemoryEntry]:
        """召回包含指定实体标签的记忆。"""

    @abstractmethod
    async def search_by_topics(
        self,
        user_id: str,
        topics: list[str],
        *,
        limit: int = 10,
    ) -> list[EpisodicMemoryEntry]:
        """召回包含指定话题标签的记忆。"""

    @abstractmethod
    async def mark_merged(
        self,
        entry_id: str,
        merged_to_id: str,
    ) -> None:
        """
        标记一条记录已被合并到另一条。

        ⚠️ 此方法是 append-only 原则的唯一例外：
        仅允许修改 merged_to 和 merged_from 字段，
        不允许修改原始内容（summary / raw_content / entities 等）。
        """

    @abstractmethod
    async def count_session(self, session_id: str) -> int:
        """统计 session 的记录数 (用于 budget)。"""

    @abstractmethod
    async def delete_before(self, user_id: str, before: datetime):
        """
        批量删除指定时间之前的记录 (遗忘)。
        不会删除 merged_to IS NOT NULL 的记录 (保留合并结果)。
        """
```

#### EntityMemoryStore (实体记忆)

```python
class EntityMemoryStore(ABC):
    """
    实体记忆存储接口。

    特性:
    - UPSERT 语义 (写时基于 (type, key) 合并)
    - 保留属性变更历史
    - 读取时一次返回完整画像
    """

    @abstractmethod
    async def read(
        self,
        entity_type: str,
        entity_key: str,
    ) -> EntityMemoryEntry | None:
        """读取完整实体 (attributes + history)。"""

    @abstractmethod
    async def read_batch(
        self,
        keys: list[tuple[str, str]],
    ) -> list[EntityMemoryEntry | None]:
        """批量读取。"""

    @abstractmethod
    async def upsert_attribute(
        self,
        entity_type: str,
        entity_key: str,
        attr_name: str,
        value: any,
        *,
        confidence: float = 1.0,
        source_session: str = "",
    ) -> EntityMemoryEntry:
        """
        更新实体单个属性。
        - 如果实体不存在则创建
        - attributes[attr_name] 更新
        - history[attr_name] 追加
        """
        ...

    @abstractmethod
    async def upsert_attributes(
        self,
        entity_type: str,
        entity_key: str,
        attributes: dict[str, any],
        *,
        confidence: float = 1.0,
        source_session: str = "",
    ) -> EntityMemoryEntry:
        """批量更新多个属性。"""

    @abstractmethod
    async def delete_entity(
        self,
        entity_type: str,
        entity_key: str,
    ):
        """删除整个实体及其历史。"""

    @abstractmethod
    async def list_by_type(
        self,
        entity_type: str,
        *,
        limit: int = 100,
    ) -> list[EntityMemoryEntry]:
        """按类型列出所有实体。"""
```

#### SemanticKnowledgeStore (语义知识)

```python
class SemanticKnowledgeStore(ABC):
    """
    语义知识存储接口。

    特性:
    - 图结构 (节点 + 边)
    - 节点支持向量语义检索
    - 边支持关系遍历
    """

    # ── 节点操作 ──

    @abstractmethod
    async def create_node(self, node: SemanticNode) -> str:
        """创建节点。如果 name 已存在则返回已有 ID (幂等)。"""

    @abstractmethod
    async def read_node(self, node_id: str) -> SemanticNode | None:
        """按 ID 读节点。"""

    @abstractmethod
    async def find_node_by_name(self, name: str) -> SemanticNode | None:
        """按名称精确查找。"""

    @abstractmethod
    async def search_nodes(
        self,
        query: str,
        *,
        top_k: int = 5,
        threshold: float = 0.6,
    ) -> list[SemanticNode]:
        """
        语义检索节点。
        基于 embedding 余弦相似度。
        """

    @abstractmethod
    async def update_embedding(self, node_id: str, embedding: list[float]):
        """更新节点向量。"""

    @abstractmethod
    async def increment_mention(self, node_id: str):
        """增加提及计数。"""

    # ── 边操作 ──

    @abstractmethod
    async def create_edge(
        self,
        source_id: str,
        target_id: str,
        relation: str,
        *,
        confidence: float = 1.0,
    ) -> str:
        """创建边。相同 (source, target, relation) 视为重复, 返回已有 ID。"""

    @abstractmethod
    async def get_neighbors(
        self,
        node_id: str,
        *,
        relation: str | None = None,
        max_depth: int = 1,
    ) -> list[tuple[SemanticNode, str]]:
        """
        获取邻居节点。
        max_depth=1 查直接邻居, >1 查路径。
        返回 [(node, relation), ...]
        """

    @abstractmethod
    async def find_path(
        self,
        source_id: str,
        target_id: str,
        *,
        max_depth: int = 5,
    ) -> list[list[tuple[str, str]]]:
        """
        查找两节点之间的路径。
        返回多条路径, 每条路径是 [(node_id, relation), ...]。
        """

    # ── 批量操作 ──

    @abstractmethod
    async def merge_knowledge(
        self,
        extractions: list[tuple[str, str, str]],
    ):
        """
        批量注入提取的知识。
        extractions = [(source_name, relation, target_name), ...]
        自动创建不存在的节点。
        """
```

#### BehavioralPatternStore (行为模式)

```python
class BehavioralPatternStore(ABC):
    """
    行为模式存储接口。

    特性:
    - 每个用户一行
    - 全量覆盖写 (收敛后替换整个 patterns)
    - 低频读写
    """

    @abstractmethod
    async def read(self, user_id: str) -> BehavioralPattern | None:
        """读取用户的完整行为模式。"""

    @abstractmethod
    async def write(self, pattern: BehavioralPattern):
        """写入/覆盖用户行为模式。version 自增。"""

    @abstractmethod
    async def delete(self, user_id: str):
        """删除用户行为模式。"""

    @abstractmethod
    async def acquire_lock(self, user_id: str, ttl: int = 30) -> bool:
        """
        获取用户级锁 (防止并发收敛冲突)。
        返回 True 表示获取成功。
        """
```

---

## 4. 存储引擎实现

### 4.1 引擎选型矩阵

| 层 | 推荐的默认引擎 | 生产可替换引擎 | 选型理由 |
|---|--------------|--------------|---------|
| Layer 1 | 文件系统 (JSON) | Redis | 低频、单值、TTL |
| Layer 2 | SQLite | PostgreSQL + pgvector | 时序 + JSON 查询 + 向量 |
| Layer 3 | SQLite | Redis Hash / MongoDB | 高频 upsert, 宽表 |
| Layer 4 | SQLite (内存) + sqlite-vec | PostgreSQL + pgvector / Neo4j | 图遍历 + 向量检索 |
| Layer 5 | SQLite | Redis / 任意 KV | 单行低频, 无复杂查询 |

### 4.2 SQLite 统一实现 (默认引擎)

单文件 `memory.db`，5 张表覆盖所有层。

#### 建表 DDL

```sql
-- =============================================
-- Layer 1: Working Memory
-- =============================================
CREATE TABLE working_memory (
    session_id      TEXT PRIMARY KEY,
    snapshot        TEXT NOT NULL,         -- JSON 序列化
    captured_at     TEXT NOT NULL,         -- ISO 8601
    expires_at      TEXT NOT NULL,         -- ISO 8601 (写入时计算)
    version         INTEGER NOT NULL DEFAULT 1
);

-- 定时清理过期快照 (应用层或触发器)
CREATE INDEX idx_wm_expires ON working_memory(expires_at);


-- =============================================
-- Layer 2: Episodic Memory
-- =============================================
CREATE TABLE episodic_memory (
    id              TEXT PRIMARY KEY,       -- UUID
    session_id      TEXT NOT NULL,
    user_id         TEXT,
    turn_index      INTEGER NOT NULL,
    created_at      TEXT NOT NULL,          -- ISO 8601
    summary         TEXT NOT NULL,
    raw_content     TEXT,
    content_type    TEXT NOT NULL DEFAULT 'raw'
                    CHECK(content_type IN ('raw', 'summary', 'critical_event')),
    source          TEXT,                   -- JSON
    entities        TEXT,                   -- JSON array
    topics          TEXT,                   -- JSON array
    keywords        TEXT,                   -- JSON array
    importance      REAL NOT NULL DEFAULT 0.3,
    token_count     INTEGER NOT NULL DEFAULT 0,
    merged_to       TEXT REFERENCES episodic_memory(id),
    merged_from     TEXT                    -- JSON array
);

CREATE INDEX idx_ep_session_turn ON episodic_memory(session_id, turn_index DESC);
CREATE INDEX idx_ep_user_time ON episodic_memory(user_id, created_at DESC);
CREATE INDEX idx_ep_entities ON episodic_memory(entities);
CREATE INDEX idx_ep_topics ON episodic_memory(topics);
CREATE INDEX idx_ep_importance ON episodic_memory(user_id, importance DESC);
CREATE INDEX idx_ep_unmerged ON episodic_memory(merged_to) WHERE merged_to IS NULL;


-- =============================================
-- Layer 3: Entity Memory
-- =============================================
CREATE TABLE entity_memory (
    entity_type     TEXT NOT NULL,
    entity_key      TEXT NOT NULL,
    attributes      TEXT NOT NULL,          -- JSON: { attr: {value, confidence, recorded_at, source_session} }
    history         TEXT NOT NULL,          -- JSON: { attr: [{value, confidence, recorded_at, ...}] }
    created_at      TEXT NOT NULL,
    last_updated_at TEXT NOT NULL,
    last_source_session TEXT,
    ttl             TEXT,
    PRIMARY KEY (entity_type, entity_key)
);


-- =============================================
-- Layer 4: Semantic Knowledge
-- =============================================
CREATE TABLE semantic_node (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    type            TEXT NOT NULL DEFAULT 'concept',
    description     TEXT NOT NULL DEFAULT '',
    aliases         TEXT NOT NULL DEFAULT '[]',   -- JSON array
    mention_count   INTEGER NOT NULL DEFAULT 0,
    first_seen_at   TEXT NOT NULL,
    last_seen_at    TEXT NOT NULL,
    source          TEXT NOT NULL DEFAULT 'extracted_from_dialogue',
    created_at      TEXT NOT NULL
);

CREATE TABLE semantic_edge (
    id              TEXT PRIMARY KEY,
    source_node     TEXT NOT NULL REFERENCES semantic_node(id),
    target_node     TEXT NOT NULL REFERENCES semantic_node(id),
    relation        TEXT NOT NULL,
    confidence      REAL NOT NULL DEFAULT 1.0,
    source          TEXT NOT NULL DEFAULT 'extracted',
    created_at      TEXT NOT NULL,
    last_confirmed_at TEXT,
    UNIQUE(source_node, target_node, relation)
);

CREATE INDEX idx_edge_source ON semantic_edge(source_node);
CREATE INDEX idx_edge_target ON semantic_edge(target_node);
CREATE INDEX idx_edge_relation ON semantic_edge(relation);


-- =============================================
-- Layer 5: Behavioral Pattern
-- =============================================
CREATE TABLE behavioral_pattern (
    user_id             TEXT PRIMARY KEY,
    patterns            TEXT NOT NULL,       -- JSON
    total_interactions  INTEGER NOT NULL DEFAULT 0,
    version             INTEGER NOT NULL DEFAULT 1,
    last_converged_at   TEXT,
    last_interaction_at TEXT,
    created_at          TEXT NOT NULL
);
```

### 4.3 SQLiteStore 基类

所有 SQLite 实现的公共基类：

```python
class SQLiteStore:
    """
    SQLite 存储引擎基类。
    提供连接管理、事务、迁移能力。
    """

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._pool: list[sqlite3.Connection] = []

    async def connect(self):
        """初始化连接池 (默认 4 连接)"""
        ...

    async def execute(self, sql: str, params: dict | tuple = None) -> sqlite3.Cursor:
        """执行 SQL (自动获取连接)"""

    async def execute_many(self, sql: str, params_list: list[dict | tuple]):
        """批量执行"""

    async def fetch_one(self, sql: str, params: dict | tuple = None) -> dict | None:
        """查询单行, 返回 dict"""

    async def fetch_all(self, sql: str, params: dict | tuple = None) -> list[dict]:
        """查询多行, 返回 list[dict]"""

    async def transaction(self) -> AsyncContextManager:
        """事务上下文管理器"""

    async def migrate(self):
        """执行 DDL 迁移 (建表 / 加索引)"""

    async def close(self):
        """关闭所有连接"""
```

### 4.4 各层 Store 的 SQLite 实现 (概览)

每个实现类继承对应的接口 + `SQLiteStore`：

```
EpisodicMemorySQLiteStore(EpisodicMemoryStore, SQLiteStore)
EntityMemorySQLiteStore(EntityMemoryStore, SQLiteStore)
SemanticKnowledgeSQLiteStore(SemanticKnowledgeStore, SQLiteStore)
BehavioralPatternSQLiteStore(BehavioralPatternStore, SQLiteStore)
```

对于 `WorkingMemoryStore`，文件系统实现更简单：

```python
class WorkingMemoryFileStore(WorkingMemoryStore):
    """
    文件系统实现的工作记忆存储。
    每个 session 一个 JSON 文件。
    """

    def __init__(self, base_path: str):
        self._base_path = Path(base_path)  # e.g. "./.runtime/working_memory/"

    async def save(self, snapshot: WorkingMemorySnapshot):
        path = self._base_path / f"{snapshot.session_id}.json"
        path.write_text(json.dumps(snapshot.to_dict(), default=str))

    async def load(self, session_id: str) -> WorkingMemorySnapshot | None:
        path = self._base_path / f"{session_id}.json"
        if not path.exists():
            return None
        # 检查 TTL
        data = json.loads(path.read_text())
        if datetime.fromisoformat(data["expires_at"]) < datetime.utcnow():
            path.unlink()
            return None
        return WorkingMemorySnapshot.from_dict(data)
```

### 4.5 可插拔设计

替换引擎只需要实现对应接口：

```python
# 开发环境: 全部 SQLite
memory_service = MemoryService(
    working_store=WorkingMemoryFileStore("./data/wm"),
    episodic_store=EpisodicMemorySQLiteStore("./data/memory.db"),
    entity_store=EntityMemorySQLiteStore("./data/memory.db"),
    semantic_store=SemanticKnowledgeSQLiteStore("./data/memory.db"),
    pattern_store=BehavioralPatternSQLiteStore("./data/memory.db"),
)

# 生产环境: 混合引擎
memory_service = MemoryService(
    working_store=WorkingMemoryRedisStore(redis_client, ttl=3600),
    episodic_store=EpisodicMemoryPGStore(pg_pool),           # 向量检索
    entity_store=EntityMemoryRedisStore(redis_client),        # 高频 upsert
    semantic_store=SemanticKnowledgePGStore(pg_pool),         # 图 + 向量
    pattern_store=BehavioralPatternSQLiteStore("./data/memory.db"),
)
```

---

## 5. 数据流管线

### 5.1 写入管线 (commit)

```
StepContext {
    user_message:       string | None
    assistant_message:  string | None
    tool_results:       list[ToolResult]
    turn_index:         int
    session_id:         string
    user_id:            string | None
    importance:         float        // 来自 Gate 的判断
    entities_detected:  list[string] // 来自 EntityExtractor
    topics_detected:    list[string] // 来自 TopicClassifier
}
```

写入管线是一个**异步扇出**：

```python
async def commit(self, session_id, user_id, step_context):
    # ── 同步部分 (必须完成, 不影响响应速度) ──

    entry = EpisodicMemoryEntry(
        id=uuid4(),
        session_id=session_id,
        user_id=user_id,
        turn_index=step_context.turn_index,
        summary=step_context.summary,
        raw_content=step_context.raw,
        content_type="critical_event" if step_context.importance > 0.7 else "raw",
        entities=step_context.entities_detected,
        topics=step_context.topics_detected,
        importance=step_context.importance,
        token_count=estimate_tokens(step_context.raw),
    )
    await self._episodic.write(entry)

    # ── 异步部分 (不阻塞回复, 后台执行) ──

    if user_id:
        asyncio.create_task(
            self._safe_background_task(
                self._entity_pipeline(user_id, session_id, step_context),
                f"entity_pipeline({user_id}, {session_id})",
            )
        )
        asyncio.create_task(
            self._safe_background_task(
                self._pattern_sampling(user_id, step_context),
                f"pattern_sampling({user_id}, {session_id})",
            )
        )


async def _entity_pipeline(self, user_id, session_id, step_context):
    """实体提取管线"""
    extractions = await self._extract_entities(step_context)
    for (entity_type, entity_key, attributes) in extractions:
        for attr_name, attr_value in attributes.items():
            await self._entity.upsert_attribute(
                entity_type, entity_key, attr_name, attr_value,
                confidence=0.7,
                source_session=session_id,
            )

    # 检查是否需要更新语义知识
    if len(extractions) > 0:
        asyncio.create_task(
            self._safe_background_task(
                self._semantic_pipeline(user_id, extractions),
                f"semantic_pipeline({user_id})",
            )
        )


async def _semantic_pipeline(self, user_id, extractions):
    """语义知识提炼管线"""
    for (entity_type, entity_key, attributes) in extractions:
        for attr_name, attr_value in attributes.items():
            if isinstance(attr_value, str) and len(attr_value) > 3:
                await self._semantic.merge_knowledge([
                    (entity_key, "has_attribute", attr_name),
                    (attr_value, "is_value_of", attr_name),
                ])
```

### 5.2 读取管线 (recall)

```python
async def recall(self, session_id, user_id, query, *, max_tokens=4096):
    payload = ContextPayload()

    # Step 1: 行为模式 (最高优先级, 几乎不占 token)
    if user_id:
        pattern = await self._pattern.read(user_id)
        if pattern and "communication_style" in pattern.patterns:
            payload.tone_instruction = (
                f"用户偏好的沟通风格: "
                f"{pattern.patterns['communication_style']['value']}"
            )

    # Step 2: 语义知识 (按当前 query 检索)
    concept_texts = []
    if query:
        concepts = await self._semantic.search_nodes(query, top_k=3)
        for c in concepts:
            concept_texts.append(f"- {c.name}: {c.description}")
    if concept_texts:
        payload.concepts = concept_texts

    # Step 3: 实体画像
    if user_id:
        entity = await self._entity.read("user", user_id)
        if entity:
            profile_lines = []
            for attr_name, attr_data in entity.attributes.items():
                profile_lines.append(f"  {attr_name}: {attr_data['value']}")
            payload.entity_profile = "\n".join(profile_lines)

    # Step 4: 情景记忆
    memories = await self._episodic.recall_session(
        session_id, limit=10, min_importance=0.3
    )
    # 如果不足, 补充跨 session 高重要性记忆
    if len(memories) < 5 and user_id:
        extra = await self._episodic.recall_user(
            user_id, limit=5, min_importance=0.7
        )
        memories.extend(extra)
    payload.memories = memories

    # Step 5: Token 裁剪
    return self._apply_token_budget(payload, max_tokens)
```

### 5.3 裁剪算法

```python
def _apply_token_budget(self, payload: ContextPayload, max_tokens: int) -> ContextPayload:
    """
    按优先级裁剪, 优先级从高到低:
    1. tone_instruction (行为模式)  — 几乎不占 token, 不裁剪
    2. entity_profile (实体画像)    — 中等大小, 最后裁剪
    3. memories (情景记忆)           — 最大体积, 优先裁剪
    4. concepts (语义知识)           — 中等体积, 次于记忆裁剪
    5. history (历史对话)            — 最容易裁剪
    """
    reserve = payload.priority_hints.reserve_for_response
    budget = max_tokens - reserve

    # 估算各部分 token
    tone_tokens = estimate(payload.tone_instruction)
    profile_tokens = estimate(payload.entity_profile)
    concept_tokens = estimate("\n".join(payload.concepts))
    memory_tokens = sum(m.token_count for m in payload.memories)

    total = tone_tokens + profile_tokens + concept_tokens + memory_tokens

    if total <= budget:
        return payload

    # 1. 裁剪情景记忆 (从最旧/最低重要性的开始)
    over = total - budget
    if memory_tokens > 0:
        payload.memories.sort(key=lambda m: (m.importance, m.turn_index))
        while memory_tokens > 0 and over > 0 and payload.memories:
            removed = payload.memories.pop(0)
            memory_tokens -= removed.token_count
            over -= removed.token_count
            total -= removed.token_count

    # 2. 如果还是超, 裁剪概念
    if total > budget and len(payload.concepts) > 1:
        total -= len(payload.concepts) - 1
        payload.concepts = payload.concepts[:1]

    # 3. 如果还是超, 压缩画像为最精简格式
    if total > budget:
        # 只保留高置信度属性
        ...

    return payload
```

---

## 6. 管理策略

### 6.1 压缩策略

| 类型 | 触发时机 | 做法 |
|------|---------|------|
| 轮次摘要 | 每轮 after_step | LLM 将本轮对话压缩为 1-2 句话 |
| 批量合并 | 情景记忆满 50 条 | LLM 将多条记忆合并为摘要, 标记 merged_to |
| Token 裁剪 | 每次 before_step | 按优先级淘汰低价值记忆 |

摘要的触发控制：

```python
class CompressionManager:
    """
    压缩管理器。
    决定何时压缩、压缩到什么程度。
    """

    # 合并阈值
    MERGE_AFTER_TURNS = 50       # 50 轮后触发一次合并
    MERGE_WINDOW_SIZE = 20       # 每次合并最近 20 轮

    # 摘要触发
    SUMMARIZE_EVERY_TURN = True  # 是否每轮都生成摘要
    SUMMARIZE_MIN_TOKENS = 200   # 原始对话超过此值才需要摘要

    async def should_merge(self, session_id: str) -> bool:
        count = await self._episodic.count_session(session_id)
        return count > 0 and count % self.MERGE_AFTER_TURNS == 0

    async def merge_session(self, session_id: str):
        """将最旧的 N 条合并为一条摘要"""
        entries = await self._episodic.recall_session(
            session_id, limit=self.MERGE_WINDOW_SIZE, offset=0
        )
        if not entries:
            return

        # 调用 LLM 生成摘要
        merged_summary = await self._llm.summarize(entries)

        # 写入合并结果
        merged_entry = EpisodicMemoryEntry(
            summary=merged_summary,
            content_type="summary",
            merged_from=[e.id for e in entries],
            importance=max(e.importance for e in entries),
        )
        merged_id = await self._episodic.write(merged_entry)

        # 标记源记录
        for entry in entries:
            await self._episodic.mark_merged(entry.id, merged_id)
```

### 6.2 遗忘策略

```python
class EvictionManager:
    """
    遗忘管理器。
    定时清理低价值/过期的记忆。
    """

    # Layer 2 TTL
    EPISODIC_RAW_TTL = timedelta(days=7)       # 原始记录 7 天
    EPISODIC_MERGED_TTL = timedelta(days=30)   # 合并后摘要 30 天
    EPISODIC_CRITICAL_TTL = timedelta(days=90) # 关键事件 90 天

    # Layer 4 冷数据
    SEMANTIC_LOW_MENTION_THRESHOLD = 3         # 提及次数低于此值视为冷数据
    SEMANTIC_COLD_TTL = timedelta(days=60)     # 冷数据 60 天后清理

    async def evict_expired(self, user_id: str):
        """执行一次遗忘轮次"""
        now = datetime.utcnow()

        # Layer 2: 按 content_type 不同 TTL 清理
        for content_type, ttl in [
            ("raw", self.EPISODIC_RAW_TTL),
            ("summary", self.EPISODIC_MERGED_TTL),
            ("critical_event", self.EPISODIC_CRITICAL_TTL),
        ]:
            cutoff = now - ttl
            await self._episodic.delete_before(user_id, cutoff)

        # Layer 4: 低频节点归档
        nodes = await self._semantic.get_low_mention_nodes(
            threshold=self.SEMANTIC_LOW_MENTION_THRESHOLD
        )
        for node in nodes:
            if node.last_seen_at < (now - self.SEMANTIC_COLD_TTL):
                await self._semantic.delete_node(node.id)
```

### 6.3 冲突解决策略

实体记忆采用**版本化 + 置信度加权**策略：

```python
class ConflictResolver:
    """
    冲突解决器。
    用于实体属性更新时判断是否覆盖。
    """

    # 新信息需要达到旧信息 confidence 的此比例才覆盖
    OVERRIDE_RATIO = 1.2

    # 用户主动、明确表述的默认置信度
    EXPLICIT_CONFIDENCE = 0.9
    # 从对话推断的默认置信度
    INFERRED_CONFIDENCE = 0.5

    async def resolve(
        self,
        store: EntityMemoryStore,
        entity_type: str,
        entity_key: str,
        attr_name: str,
        new_value: any,
        new_confidence: float,
    ) -> tuple[bool, str]:
        """
        解决冲突。
        返回 (是否覆盖, 原因)。
        """
        entity = await store.read(entity_type, entity_key)
        if entity is None or attr_name not in entity.attributes:
            return True, "新属性, 直接写入"

        old = entity.attributes[attr_name]

        # 策略: 置信度加权
        if new_confidence >= old["confidence"] * self.OVERRIDE_RATIO:
            return True, f"新置信度 {new_confidence} > 旧 {old['confidence']} × {self.OVERRIDE_RATIO}"

        # 如果新置信度低但旧值很旧了, 也覆盖
        days_since_old = (datetime.utcnow() - old["recorded_at"]).days
        if days_since_old > 30 and new_confidence > 0.3:
            return True, "旧值已过 30 天, 新值置信度可接受"

        return False, f"新置信度 {new_confidence} 不足以覆盖旧 {old['confidence']}"
```

### 6.4 提升门控 (Memory Commit Gate)

```python
class MemoryCommitGate:
    """
    判断本轮对话是否值得写入持久化记忆。
    """

    # 值得记录为 critical_event 的信息类型
    CRITICAL_PATTERNS = [
        r"(?:我叫|我是|我的名字|我姓)",
        r"(?:我[在做了用]|我[的]?[职业工作项目])",
        r"(?:我喜欢|我不喜欢|我偏好|我倾向于)",
        r"(?:我[在正]?在(?:做|开发|使用|学习))",
    ]

    # 不值得记录的模式 (寒暄 / 确认 / 无信息量)
    SKIP_PATTERNS = [
        r"^(?:你好|hi|hello|在吗|谢谢|好的|嗯|ok)",
        r"^(?:是的|对的|没错|明白|了解了|收到)",
        r"^(?:不对|不是|错了|重来)",
        r"^\s*$",
    ]

    async def evaluate(
        self,
        user_message: str | None,
        assistant_message: str | None,
    ) -> GateDecision:
        """
        评估本轮对话的信息价值。
        """
        importance = 0.3  # 默认低
        reason = "general_conversation"

        if not user_message:
            return GateDecision(importance=0.0, should_record=False, reason="no_user_input")

        # 跳过无信息量内容
        for pattern in self.SKIP_PATTERNS:
            if re.match(pattern, user_message.strip()):
                return GateDecision(importance=0.0, should_record=False, reason="skipped_skip_pattern")

        # 检测关键信息
        for pattern in self.CRITICAL_PATTERNS:
            if re.search(pattern, user_message):
                importance = 0.9
                reason = "critical_info"
                break

        # LLM 回复长度 (长回复通常含重要信息)
        if assistant_message and len(assistant_message) > 200:
            importance = max(importance, 0.5)

        should_record = importance >= 0.3

        return GateDecision(
            importance=importance,
            should_record=should_record,
            reason=reason,
        )
```

---

## 7. 集成到 Runtime

### 7.1 MemoryService 注入

按照设计文档，`MemoryService` 通过 `RuntimeContext.services` 注入：

```python
class RuntimeContext:
    def __init__(self, ...):
        self.services = {
            "memory": MemoryService,   # ← 记忆服务
            "rag": RagService,
        }
```

### 7.2 Hook 注册示例

```python
# 构造阶段
memory_service = MemoryService(sqlite_store, ...)
gate = MemoryCommitGate()
compressor = CompressionManager(llm)
evictor = EvictionManager(episodic_store)

runtime = AgentRuntime(
    session_id=session_id,
    llm_config=llm_config,
    llm_executor=OpenAIExecutor(llm_config),
    services={"memory": memory_service},
)

# 注册治理组件
runtime.on_before_step(MemoryRecallHook(memory_service))
runtime.on_after_step(MemoryCommitHook(memory_service, gate, compressor))
runtime.on_after_step(PatternSamplingHook(memory_service))
runtime.on_session_end(SessionCleanupHook(memory_service, evictor))
runtime.on_error(ErrorRecoveryHook(memory_service))  # checkpoint
```

### 7.3 Hook 实现范例

```python
class MemoryRecallHook:
    """
    before_step Transform
    注入记忆到 contextPayload。
    """
    primitive = "transform"

    def __init__(self, memory_service: MemoryService):
        self._memory = memory_service

    async def __call__(self, ctx: RuntimeContext):
        query = ctx.messages[-1]["content"] if ctx.messages else ""
        payload = await self._memory.recall(
            session_id=ctx.session_id,
            user_id=ctx.user_id,
            query=query,
            max_tokens=ctx.llm_config.max_tokens,
        )
        ctx.context_payload = payload


class MemoryCommitHook:
    """
    after_step Transform
    写入记忆。
    """
    primitive = "transform"

    def __init__(self, memory_service, gate, compressor):
        self._memory = memory_service
        self._gate = gate
        self._compressor = compressor

    async def __call__(self, ctx: RuntimeContext):
        step = StepContext(
            user_message=ctx.last_user_message,
            assistant_message=ctx.last_assistant_message,
            tool_results=ctx.last_tool_results,
            turn_index=ctx.step_index,
            session_id=ctx.session_id,
            user_id=ctx.user_id,
        )

        # 门控判断
        decision = await self._gate.evaluate(
            step.user_message, step.assistant_message
        )
        step.importance = decision.importance

        if decision.should_record:
            await self._memory.commit(ctx.session_id, ctx.user_id, step)

        # 检查是否需要合并
        if await self._compressor.should_merge(ctx.session_id):
            await self._compressor.merge_session(ctx.session_id)
```

---

## 附录: 完整文件清单

```
docs/memory-system-design.md     ← 本文档
src/lania_agent_runtime/memory/
├── __init__.py                  # 导出 MemoryService
├── types.py                     # 所有数据类定义
├── service.py                   # MemoryService 外观
├── interfaces/
│   ├── __init__.py
│   ├── working_memory.py        # WorkingMemoryStore 接口
│   ├── episodic_memory.py       # EpisodicMemoryStore 接口
│   ├── entity_memory.py         # EntityMemoryStore 接口
│   ├── semantic_knowledge.py    # SemanticKnowledgeStore 接口
│   └── behavioral_pattern.py    # BehavioralPatternStore 接口
├── stores/
│   ├── __init__.py
│   ├── base_sqlite.py           # SQLiteStore 基类
│   ├── working_file.py          # WorkingMemoryFileStore
│   ├── episodic_sqlite.py       # EpisodicMemorySQLiteStore
│   ├── entity_sqlite.py         # EntityMemorySQLiteStore
│   ├── semantic_sqlite.py       # SemanticKnowledgeSQLiteStore
│   └── pattern_sqlite.py        # BehavioralPatternSQLiteStore
├── pipeline/
│   ├── __init__.py
│   ├── commit.py                # 写入管线
│   ├── recall.py                # 读取管线
│   └── token_manager.py         # Token 裁剪
├── management/
│   ├── __init__.py
│   ├── gate.py                  # MemoryCommitGate
│   ├── compressor.py            # CompressionManager
│   ├── eviction.py              # EvictionManager
│   └── conflict.py              # ConflictResolver
└── hooks/
    ├── __init__.py
    ├── recall_hook.py           # MemoryRecallHook
    ├── commit_hook.py           # MemoryCommitHook
    └── cleanup_hook.py          # SessionCleanupHook
```
