"""Data models for Lania Agent Runtime."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, TypedDict

# ── Context Payload Sub-types ──


class MemoryEntrySummary(TypedDict):
    """Structured summary of an episodic memory entry."""

    id: str
    summary: str
    created_at: str
    turn_index: int


class RagDocumentSummary(TypedDict, total=False):
    """Summary of a RAG document reference."""

    title: str
    content: str
    url: str


class ConceptSummary(TypedDict, total=False):
    """Summary of a knowledge concept."""

    name: str
    description: str


class EntityProfileValue(TypedDict, total=False):
    """A single attribute value in an entity profile."""

    value: Any
    source: str


class RuntimeStatus(str, Enum):
    """Runtime status enum."""

    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"
    ENDED = "ended"
    HANDED_OFF = "handed_off"


# ── LLM Layer Models ──


@dataclass
class ToolCall:
    """LLM returned tool call request."""

    id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str


@dataclass
class LLMUsage:
    """Token usage statistics."""

    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class LLMResponse:
    """Unified return format for LLM calls."""

    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: LLMUsage = field(default_factory=LLMUsage)
    finish_reason: str = "stop"
    model: str = ""


@dataclass
class LLMMessage:
    """Single message in LLM format."""

    role: str  # "system" | "user" | "assistant" | "tool"
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None


# ── Runtime API Models ──


@dataclass
class RunResult:
    """Result of a run() call."""

    content: str
    session_id: str
    messages: list[dict]
    tool_calls: list[ToolCall]
    usage: LLMUsage
    finish_reason: str


@dataclass
class StreamEvent:
    """Stream event for streaming output."""

    type: str  # "text" | "tool_start" | "tool_end" | "error" | "done"
    content: str | None = None
    name: str | None = None
    error: str | None = None
    metadata: dict | None = None


@dataclass
class SessionSnapshot:
    """Session snapshot for debugging/monitoring."""

    session_id: str
    status: RuntimeStatus
    step_count: int
    message_count: int
    total_tokens: int
    duration_seconds: float
    last_error: str | None = None


# ── Memory System Models ──


@dataclass
class PriorityHints:
    """Token management priority hints."""

    preserve_last_n_history: int = 3
    max_tokens: int = 4096
    reserve_for_response: int = 1024


@dataclass
class ContextPayload:
    """Structured multi-source context for LLM calls."""

    system_prompt: str = ""
    memories: list[MemoryEntrySummary] = field(default_factory=list)
    rag_documents: list[RagDocumentSummary] = field(default_factory=list)
    injected_context: list[str] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)
    tone_instruction: str = ""
    concepts: list[ConceptSummary] = field(default_factory=list)
    entity_profile: dict[str, EntityProfileValue] = field(default_factory=dict)
    priority_hints: PriorityHints = field(default_factory=PriorityHints)

    def serialize_to_system_message(self) -> str:
        """Serialize context payload to a system message string."""
        parts = [self.system_prompt]

        if self.tone_instruction:
            parts.append(f"\n## Communication Style\n{self.tone_instruction}")

        if self.entity_profile:
            profile_str = "\n".join(
                f"- {k}: {v.get('value', v) if isinstance(v, dict) else v}"
                for k, v in self.entity_profile.items()
            )
            parts.append(f"\n## User Profile\n{profile_str}")

        if self.memories:
            mem_str = "\n".join(f"- [{m['created_at']}] {m['summary']}" for m in self.memories[-5:])
            parts.append(f"\n## Recent Memories\n{mem_str}")

        if self.concepts:
            concept_str = "\n".join(
                f"- {c.get('name', '')}: {c.get('description', '')}" for c in self.concepts
            )
            parts.append(f"\n## Relevant Concepts\n{concept_str}")

        if self.rag_documents:
            doc_str = "\n".join(
                f"- {d.get('title', d.get('content', ''))}" for d in self.rag_documents
            )
            parts.append(f"\n## Reference Documents\n{doc_str}")

        if self.injected_context:
            ctx_str = "\n".join(self.injected_context)
            parts.append(f"\n## Additional Context\n{ctx_str}")

        return "\n\n".join(p.strip() for p in parts if p.strip())


# ── Working Memory Models ──


@dataclass
class PlanStep:
    """A single step in an execution plan."""
    id: str = ""
    description: str = ""
    tool: str = ""
    args: dict[str, Any] = field(default_factory=dict)


@dataclass
class BudgetSnapshot:
    """Budget snapshot for working memory checkpoint."""
    token_used: int = 0
    token_limit: int = 100000
    step_count: int = 0
    step_limit: int = 100
    cost_in_cents: int = 0


@dataclass
class PauseStateSnapshot:
    """Pause state snapshot for working memory checkpoint."""
    is_paused: bool = False
    pending_approvals: list[dict] = field(default_factory=list)
    resume_token: str | None = None


@dataclass
class ErrorStateSnapshot:
    """Error state snapshot for working memory checkpoint."""
    consecutive_errors: int = 0
    max_retries: int = 3
    last_error: dict | None = None


@dataclass
class ContextPayloadSnapshot:
    """Serializable snapshot of context payload for working memory."""
    system_prompt: str = ""
    memories: list[dict] = field(default_factory=list)
    rag_documents: list[dict] = field(default_factory=list)
    injected_context: list[str] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)
    tone_instruction: str = ""
    concepts: list[dict] = field(default_factory=list)
    entity_profile: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkingMemorySnapshot:
    """Snapshot of working memory.

    设计文档: memory-system-design.md §2.1
    包含 Runtime 完整执行状态，用于崩溃恢复和暂停恢复。
    """

    session_id: str
    step_index: int = 0
    messages: list[dict] = field(default_factory=list)
    message_count: int = 0
    total_tokens: int = 0
    status: str = "running"

    # 新增: ContextPayload 快照 (M5)
    context_payload: ContextPayloadSnapshot = field(default_factory=ContextPayloadSnapshot)

    # 新增: Runtime 执行状态 (M5)
    plan: PlanStep | None = None
    budget: BudgetSnapshot = field(default_factory=BudgetSnapshot)
    pause_state: PauseStateSnapshot = field(default_factory=PauseStateSnapshot)
    error_state: ErrorStateSnapshot = field(default_factory=ErrorStateSnapshot)

    # 新增: Hook 链状态 (M5)
    hook_states: dict[str, Any] = field(default_factory=dict)

    # 元信息
    captured_at: str = field(default_factory=lambda: datetime.now().isoformat())
    version: int = 1
    ttl: int = 3600


@dataclass
class EpisodicMemoryEntry:
    """Episodic memory entry - a single turn in a conversation."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    user_id: str = ""
    turn_index: int = 0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    summary: str = ""
    raw_content: str | None = None
    content_type: str = "raw"
    source: dict | None = None
    entities: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    importance: float = 0.3
    token_count: int = 0
    merged_to: str | None = None
    merged_from: list[str] = field(default_factory=list)


@dataclass
class EntityMemoryEntry:
    """Entity memory entry - structured entity attributes."""

    entity_type: str = ""
    entity_key: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)
    history: dict[str, list] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_source_session: str = ""
    ttl: str | None = None


@dataclass
class SemanticNode:
    """Semantic knowledge node."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    type: str = "concept"
    description: str = ""
    aliases: list[str] = field(default_factory=list)
    mention_count: int = 0
    first_seen_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_seen_at: str = field(default_factory=lambda: datetime.now().isoformat())
    source: str = "extracted_from_dialogue"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class SemanticEdge:
    """Semantic knowledge edge."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source_node: str = ""
    target_node: str = ""
    relation: str = ""
    confidence: float = 1.0
    source: str = "extracted"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_confirmed_at: str | None = None


@dataclass
class BehavioralPattern:
    """Behavioral pattern for a user.

    设计文档: memory-system-design.md §3.5
    total_interactions / version / last_converged_at / last_interaction_at / created_at
    由存储层管理, 通过 upsert_behavioral_pattern 自增维护.
    """

    user_id: str = ""
    patterns: dict[str, Any] = field(default_factory=dict)
    total_interactions: int = 0
    version: int = 1
    last_converged_at: str = ""
    last_interaction_at: str = ""
    created_at: str = ""


# ── LLMExecutor 配置 (从 executor.py 移入，避免循环引用) ──


@dataclass
class LLMExecutorConfig:
    """Configuration for LLMExecutor.

    设计文档: llm-executor-design.md §2.3
    api_key / api_base 用于构造客户端(当不注入 client/provider 时).
    stream 控制默认是否启用流式.
    """

    model: str = "deepseek-chat"
    temperature: float = 0.7
    max_tokens: int = 4096
    timeout: float = 120.0
    max_retries: int = 3
    retry_backoff_base: float = 1.0
    retry_backoff_max: float = 30.0
    extra_headers: dict[str, str] = field(default_factory=dict)
    api_key: str = ""
    api_base: str = ""
    stream: bool = False
    total_interactions: int = 0
    version: int = 1
    last_converged_at: str = ""
    last_interaction_at: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


# ── Memory Gate / Compression / Eviction Models ──


@dataclass
class GateDecision:
    """记忆提升门控的决策结果."""

    importance: float = 0.0          # 0.0 ~ 1.0, 信息密度评分
    should_record: bool = False      # 是否写入持久化记忆
    should_extract_entities: bool = False  # 是否提取实体
    should_update_pattern: bool = False    # 是否更新行为模式
    reason: str = "no_input"         # 决策原因


@dataclass
class StepContext:
    """写入管线的上下文, 封装单轮对话的所有信息."""

    user_message: str | None = None
    assistant_message: str | None = None
    tool_results: list[dict] = field(default_factory=list)
    turn_index: int = 0
    session_id: str = ""
    user_id: str | None = None
    importance: float = 0.3
    entities_detected: list[str] = field(default_factory=list)
    topics_detected: list[str] = field(default_factory=list)
    raw_content: str = ""

    @property
    def summary(self) -> str:
        """自动摘要: 优先使用 assistant_message, 回退到 raw_content."""
        if self.assistant_message:
            return self.assistant_message[:200]
        return self.raw_content[:200]


@dataclass
class EntityExtraction:
    """实体提取结果: 一个实体 + 多个属性."""

    entity_type: str = ""
    entity_key: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.7
    source_session: str = ""


@dataclass
class MergeCandidate:
    """合并候选项: 一组待合并的记忆条目."""

    entry_ids: list[str] = field(default_factory=list)
    session_id: str = ""
    summaries: list[str] = field(default_factory=list)
    min_importance: float = 0.0
    max_importance: float = 0.0
    token_total: int = 0
