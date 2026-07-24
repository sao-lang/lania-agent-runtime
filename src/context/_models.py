"""
上下文专用模型定义。

包含选取决策（SelectionDecision）、裸数据容器（RawContext）、
概念摘要（ConceptSummary）等上下文管线专用的数据结构。

与 src.memory._types 无依赖关系：
- RawContext 的字段类型均使用 Python 内置类型（list / dict / str）
- 实际运行时 episodic_memories 中存放的是 EpisodicMemoryEntry 实例
- 但类型标注层面不引用任何 Memory 侧类型，保持包间零耦合
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class SelectionDecision:
    """
    选取决策结果——Selector 阶段的输出。

    记录滑动窗口裁切后保留哪些原始消息、哪些记忆需要去重，
    供后续 Compressor / Loader 阶段使用。
    """

    preserve_message_count: int = 0
    """保留的原始消息轮次数。"""

    cropped_ranges: list[tuple[int, int]] = field(default_factory=list)
    """被裁的 [start_turn, end_turn] turn_index 范围列表。"""

    keep_from_index: int = 0
    """ctx.messages 中保留的起始索引。"""

    dedup_memory_ids: set[str] = field(default_factory=set)
    """与保留消息重叠、需要去重的记忆 ID 集合。"""

    dedup_turn_indices: set[int] = field(default_factory=set)
    """与保留消息重叠的 turn_index 集合。"""


@dataclass
class RawContext:
    """
    Memory 返回的裸数据容器——Loader 阶段的输出。

    与 ContextPayload 的区别：不含裁剪/序列化逻辑，
    由 ContextManager 的 Compressor 阶段决定取舍。
    """

    episodic_memories: list = field(default_factory=list)
    """情景记忆条目列表（EpisodicMemoryEntry 实例列表）。"""

    entity_profile: dict[str, Any] = field(default_factory=dict)
    """实体画像字典（键为属性名，值为 EntityAttributeValue 或原始值）。"""

    concepts: list[dict[str, str]] = field(default_factory=list)
    """语义概念摘要列表（每项含 name / description）。"""

    tone_instruction: str = ""
    """从行为模式提取的语气指令文本。"""


@dataclass
class ConceptSummary:
    """
    概念摘要——语义知识检索结果中的单个概念条目。

    Attributes:
        name: 概念名称。
        description: 概念定义描述。
        relevance_score: 与查询的相关性评分。
    """

    name: str = ""
    description: str = ""
    relevance_score: float = 0.0


@dataclass
class EntityProfileValue:
    """
    实体属性值——实体画像中的单个属性条目。

    Attributes:
        value: 属性值。
        confidence: 置信度，0.0 ~ 1.0。
        recorded_at: 记录时间。
        source_session: 来源会话 ID。
    """

    value: Any = None
    confidence: float = 1.0
    recorded_at: datetime | None = None
    source_session: str = ""


@dataclass
class CompressResult:
    """
    压缩结果——Compressor 阶段的输出。

    记录实际采用的层级和被裁剪的字段信息，
    供日志/监控/调试使用。
    """

    level: int = 4
    """实际采用的层级（1 ~ 4）。"""

    dropped_memories: int = 0
    """因 token 预算被丢弃的记忆条数。"""

    dropped_concepts: int = 0
    """被裁剪的概念数。"""

    profile_trimmed: bool = False
    """实体画像是否被压缩。"""

    total_estimated_tokens: int = 0
    """压缩后的估计 token 总数。"""
