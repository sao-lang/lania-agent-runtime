"""
记忆系统数据类定义。

包含五层记忆的全部数据类：
- Layer 1: WorkingMemorySnapshot（工作记忆快照）
- Layer 2: EpisodicMemoryEntry（情景记忆条目）
- Layer 3: EntityMemoryEntry（实体记忆）
- Layer 4: SemanticNode / SemanticEdge（语义知识）
- Layer 5: BehavioralPattern（行为模式）

以及 StepContext、GateDecision、RecallResult 等辅助数据结构。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

# =============================================
# 辅助类型
# =============================================


@dataclass
class ToolCallRecord:
    """工具调用记录，嵌入在 MemorySource 中使用。

    Attributes:
        tool_name: 工具名称。
        args: 工具调用参数字典。
        result: 工具调用结果字符串。
    """

    tool_name: str
    args: dict[str, Any]
    result: str


@dataclass
class MemorySource:
    """情景记忆的来源信息。

    Attributes:
        user_message: 用户消息原文。
        assistant_message: 助理消息原文。
        tool_calls: 本轮涉及的工具调用列表。
    """

    user_message: str | None = None
    assistant_message: str | None = None
    tool_calls: list[ToolCallRecord] | None = None


@dataclass
class EntityAttributeValue:
    """实体属性的单个值结构。

    每个属性包含值、置信度、记录时间和来源会话。

    Attributes:
        value: 属性值（动态类型：str / int / bool 等）。
        confidence: 置信度，0.0 ~ 1.0。
        recorded_at: 记录时间。
        source_session: 来源会话 ID。
    """

    value: Any
    confidence: float = 1.0
    recorded_at: datetime | None = None
    source_session: str = ""


# =============================================
# Layer 1: Working Memory（工作记忆）
# =============================================


@dataclass
class PauseState:
    """暂停状态快照。

    Attributes:
        is_paused: 是否暂停。
        pending_approvals: 待审批请求列表。
        resume_token: 恢复令牌。
    """

    is_paused: bool = False
    pending_approvals: list[dict[str, Any]] = field(default_factory=list)
    resume_token: str | None = None


@dataclass
class ErrorStateSnapshot:
    """错误状态快照。

    Attributes:
        consecutive_errors: 连续错误次数。
        max_retries: 最大重试次数。
        last_error: 最近一次错误信息。
    """

    consecutive_errors: int = 0
    max_retries: int = 3
    last_error: dict[str, str] | None = None


@dataclass
class BudgetSnapshot:
    """预算快照。

    Attributes:
        token_used: 已使用 token 数。
        token_limit: token 上限。
        step_count: 已执行步数。
        step_limit: 步数上限。
        cost_in_cents: 已花费（美分）。
    """

    token_used: int = 0
    token_limit: int = 0
    step_count: int = 0
    step_limit: int = 0
    cost_in_cents: int = 0


@dataclass
class WorkingMemorySnapshot:
    """工作记忆快照——Runtime 执行状态的完整序列化快照。

    仅当 Runtime 进入 paused 状态、发生非致命错误或主动 checkpoint 时持久化。
    一个 session 只保留最新快照（覆盖写），TTL 默认 3600 秒。

    Attributes:
        session_id: 会话 ID。
        step_index: 快照时刻的步数。
        messages: 完整的 messages 数组。
        message_count: 消息数量。
        total_tokens: 已知总 token 数（避免重算）。
        context_payload: ContextPayload 快照（dict 格式）。
        status: Runtime 状态。
        plan: 执行计划。
        budget: 预算快照。
        pause_state: 暂停状态。
        error_state: 错误状态。
        hook_states: Hook 链状态。
        captured_at: 快照时间。
        version: 快照格式版本号。
        ttl: 过期秒数。
    """

    session_id: str = ""
    step_index: int = 0
    messages: list = field(default_factory=list)
    message_count: int = 0
    total_tokens: int = 0
    context_payload: dict[str, Any] = field(default_factory=dict)
    status: str = "running"
    plan: dict[str, Any] | None = None
    budget: BudgetSnapshot = field(default_factory=BudgetSnapshot)
    pause_state: PauseState = field(default_factory=PauseState)
    error_state: ErrorStateSnapshot = field(default_factory=ErrorStateSnapshot)
    hook_states: dict[str, Any] = field(default_factory=dict)
    captured_at: datetime | None = None
    version: int = 1
    ttl: int = 3600


# =============================================
# Layer 2: Episodic Memory（情景记忆）
# =============================================


@dataclass
class EpisodicMemoryEntry:
    """情景记忆条目——时序化的对话轮次。

    每轮用户+AI对话被压缩为一条或多条记录，append-only 写入。
    支持按 session / user / entities / topics 检索。

    Attributes:
        id: 全局唯一 ID（UUID）。
        session_id: 所属会话 ID。
        user_id: 所属用户 ID。
        turn_index: 第几轮对话（0-based）。
        created_at: 写入时间。
        summary: 压缩后的内容摘要。
        raw_content: 原始对话全文。
        content_type: 内容类型。
        source: 来源信息（用户消息 / 助理消息 / 工具调用）。
        entities: 提及的实体名列表。
        topics: 话题标签列表。
        keywords: 关键词列表。
        importance: 信息密度评分，0.0 ~ 1.0。
        token_count: 原始 token 数。
        merged_to: 如果被合并，指向目标摘要 ID。
        merged_from: 如果本条是合并结果，包含源 ID 列表。
    """

    id: str = ""
    session_id: str = ""
    user_id: str = ""
    turn_index: int = 0
    created_at: datetime | None = None
    summary: str = ""
    raw_content: str | None = None
    content_type: str = "raw"
    source: MemorySource | None = None
    entities: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    importance: float = 0.3
    token_count: int = 0
    merged_to: str | None = None
    merged_from: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """初始化后自动生成 ID（如果未提供）。"""
        if not self.id:
            self.id = uuid4().hex


# =============================================
# Layer 3: Entity Memory（实体记忆）
# =============================================


@dataclass
class EntityMemoryEntry:
    """实体记忆——以实体为中心的结构化属性存储。

    每个实体（用户、项目、组织等）一行，属性是动态扩展的结构。
    使用 UPSERT 语义，保留属性变更历史。

    Attributes:
        entity_type: 实体类型（"user" / "project" / "organization"）。
        entity_key: 实体标识（如 "user-9527"）。
        attributes: 当前属性字典。键为属性名，值为 EntityAttributeValue。
        history: 属性变更历史。键为属性名，值为 EntityAttributeValue 列表。
        created_at: 创建时间。
        last_updated_at: 最后更新时间。
        last_source_session: 最后来源会话 ID。
        ttl: 过期时间，None 表示永久。
    """

    entity_type: str = ""
    entity_key: str = ""
    attributes: dict[str, EntityAttributeValue] = field(default_factory=dict)
    history: dict[str, list[EntityAttributeValue]] = field(default_factory=dict)
    created_at: datetime | None = None
    last_updated_at: datetime | None = None
    last_source_session: str = ""
    ttl: datetime | None = None


# =============================================
# Layer 4: Semantic Knowledge（语义知识）
# =============================================


@dataclass
class SemanticNode:
    """语义知识节点——概念定义。

    Attributes:
        id: 节点唯一 ID（UUID）。
        name: 概念名称（如 "WorkingMemory"）。
        type: 节点类型。
        description: 概念定义描述。
        aliases: 别名列表。
        embedding: 向量（用于语义检索）。
        embedding_dim: 向量维度。
        mention_count: 在对话中被提及次数。
        first_seen_at: 首次出现时间。
        last_seen_at: 最后出现时间。
        source: 来源类型。
        created_at: 创建时间。
    """

    id: str = ""
    name: str = ""
    type: str = "concept"
    description: str = ""
    aliases: list[str] = field(default_factory=list)
    embedding: list[float] | None = None
    embedding_dim: int | None = None
    mention_count: int = 0
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    source: str = "extracted_from_dialogue"
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        """初始化后自动生成 ID（如果未提供）。"""
        if not self.id:
            self.id = uuid4().hex


@dataclass
class SemanticEdge:
    """语义知识边——概念之间的关系。

    Attributes:
        id: 边唯一 ID（UUID）。
        source_node: 源节点 ID。
        target_node: 目标节点 ID。
        relation: 关系类型。
        confidence: 置信度，0.0 ~ 1.0。
        source: 来源类型。
        created_at: 创建时间。
        last_confirmed_at: 最后确认时间。
    """

    id: str = ""
    source_node: str = ""
    target_node: str = ""
    relation: str = ""
    confidence: float = 1.0
    source: str = "extracted"
    created_at: datetime | None = None
    last_confirmed_at: datetime | None = None

    def __post_init__(self) -> None:
        """初始化后自动生成 ID（如果未提供）。"""
        if not self.id:
            self.id = uuid4().hex


# =============================================
# Layer 5: Behavioral Pattern（行为模式）
# =============================================


@dataclass
class BehavioralPattern:
    """行为模式——统计收敛后的用户特征。

    每个用户一行，全量覆盖写。通过聚合采样而非单次写入来更新。

    Attributes:
        user_id: 用户唯一 ID。
        patterns: 模式数据字典（communication_style / depth_preference 等）。
        total_interactions: 参与统计的总交互数。
        version: 收敛版本号。
        last_converged_at: 最近一次收敛时间。
        last_interaction_at: 最近一次交互时间。
        created_at: 创建时间。
    """

    user_id: str = ""
    patterns: dict[str, Any] = field(default_factory=dict)
    total_interactions: int = 0
    version: int = 1
    last_converged_at: datetime | None = None
    last_interaction_at: datetime | None = None
    created_at: datetime | None = None


# =============================================
# 管线辅助类型
# =============================================


@dataclass
class StepContext:
    """Step 上下文——传给 commit 管线的输入结构。

    Attributes:
        user_message: 本轮用户消息。
        assistant_message: 本轮助理消息。
        tool_results: 本轮工具调用结果列表。
        turn_index: 第几轮对话。
        session_id: 会话 ID。
        user_id: 用户 ID。
        importance: 来自 Gate 的信息价值评分。
        entities_detected: 检测到的实体列表。
        topics_detected: 检测到的话题列表。
        summary: 压缩后的摘要文本。
        raw: 原始对话文本。
    """

    user_message: str | None = None
    assistant_message: str | None = None
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    turn_index: int = 0
    session_id: str = ""
    user_id: str | None = None
    importance: float = 0.3
    entities_detected: list[str] = field(default_factory=list)
    topics_detected: list[str] = field(default_factory=list)
    summary: str = ""
    raw: str = ""


@dataclass
class GateDecision:
    """门控决策结果——判断本轮对话是否值得写入持久化记忆。

    Attributes:
        importance: 信息价值评分，0.0 ~ 1.0。
        should_record: 是否应写入持久化记忆。
        reason: 决策原因。
    """

    importance: float = 0.0
    should_record: bool = False
    reason: str = ""


@dataclass
class RecallResult:
    """MemoryService.recall_raw() 的裸数据返回结构。

    与 ContextPayload 的区别：不含裁剪/序列化逻辑，返回完整数据，
    由 ContextManager 决定取舍。

    Attributes:
        episodic_memories: 情景记忆条目列表。
        entity_profile: 实体画像字典。
        concepts: 概念摘要列表。
        tone_instruction: 语气指令文本。
    """

    episodic_memories: list[EpisodicMemoryEntry] = field(default_factory=list)
    entity_profile: dict[str, EntityAttributeValue] = field(default_factory=dict)
    concepts: list[dict[str, str]] = field(default_factory=list)
    tone_instruction: str = ""
