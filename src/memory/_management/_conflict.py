"""
ConflictResolver——冲突解决器。

用于实体属性更新时判断是否覆盖旧值。
基于置信度加权和时间衰减策略。
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.memory._stores import EntityMemoryStore


class ConflictResolver:
    """
    冲突解决器。

    用于实体属性更新时判断是否覆盖。
    策略：置信度加权 + 时间衰减。
    - 新置信度达到旧的 1.2 倍时覆盖
    - 旧值超过 30 天且新置信度 > 0.3 时覆盖
    """

    OVERRIDE_RATIO = 1.2
    """新信息需要达到旧信息 confidence 的此比例才覆盖。"""

    EXPLICIT_CONFIDENCE = 0.9
    """用户主动、明确表述的默认置信度。"""

    INFERRED_CONFIDENCE = 0.5
    """从对话推断的默认置信度。"""

    STALE_DAYS = 30
    """超过此天数的旧值允许被较低置信度覆盖。"""

    STALE_MIN_CONFIDENCE = 0.3
    """覆盖旧值时新值的最低置信度要求。"""

    def __init__(self, entity_store: EntityMemoryStore) -> None:
        """
        初始化冲突解决器。

        Args:
            entity_store: 实体记忆存储适配器。
        """
        self._entity = entity_store

    async def resolve(
        self,
        entity_type: str,
        entity_key: str,
        attr_name: str,
        new_value: object,
        new_confidence: float,
    ) -> tuple[bool, str]:
        """
        解决冲突。

        Args:
            entity_type: 实体类型。
            entity_key: 实体标识。
            attr_name: 属性名。
            new_value: 新属性值。
            new_confidence: 新置信度。

        Returns:
            (是否覆盖, 原因) 元组。
        """
        entity = await self._entity.read(entity_type, entity_key)
        if entity is None or attr_name not in entity.attributes:
            return True, "新属性，直接写入"

        old = entity.attributes[attr_name]

        # 策略 1: 置信度加权
        if new_confidence >= old.confidence * self.OVERRIDE_RATIO:
            return True, (
                f"新置信度 {new_confidence} > "
                f"旧 {old.confidence} × {self.OVERRIDE_RATIO}"
            )

        # 策略 2: 时间衰减
        now = datetime.now(timezone.utc)
        if old.recorded_at is not None:
            # 确保 recorded_at 有时区信息以便比较
            old_recorded = old.recorded_at
            if old_recorded.tzinfo is None:
                old_recorded = old_recorded.replace(tzinfo=timezone.utc)

            days_since_old = (now - old_recorded).days
            if days_since_old > self.STALE_DAYS and new_confidence > self.STALE_MIN_CONFIDENCE:
                return True, f"旧值已过 {days_since_old} 天，新值置信度可接受"

        return False, (
            f"新置信度 {new_confidence} "
            f"不足以覆盖旧 {old.confidence}"
        )
