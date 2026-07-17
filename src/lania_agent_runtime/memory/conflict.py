"""冲突解决器: 实体属性更新时判断是否覆盖."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from lania_agent_runtime.memory.interfaces import EntityStore


class ConflictResolver:
    """冲突解决器.

    用于实体属性更新时判断是否覆盖旧值.
    策略:
    - 置信度加权: 新 confidence > 旧 × OVERRIDE_RATIO 才覆盖
    - 过期覆盖: 旧值超过一定天数且新置信度可接受则覆盖
    - 来源优先级: 用户显式表述 > 推断
    """

    # 新信息需要达到旧信息 confidence 的此比例才覆盖
    OVERRIDE_RATIO = 1.2

    # 用户主动、明确表述的默认置信度
    EXPLICIT_CONFIDENCE = 0.9
    # 从对话推断的默认置信度
    INFERRED_CONFIDENCE = 0.5

    # 旧值超过此天数且新置信度 > 阈值则覆盖
    STALE_DAYS = 30
    STALE_CONFIDENCE_THRESHOLD = 0.3

    def __init__(self, store: EntityStore) -> None:
        self._store = store

    async def resolve(
        self,
        entity_type: str,
        entity_key: str,
        attr_name: str,
        new_value: Any,
        *,
        new_confidence: float = 0.7,
        source_session: str = "",
    ) -> tuple[bool, str]:
        """解决冲突.

        Args:
            entity_type: 实体类型
            entity_key: 实体标识
            attr_name: 属性名
            new_value: 新值
            new_confidence: 新置信度(0.0~1.0)
            source_session: 来源 session ID

        Returns:
            (是否覆盖, 原因)
        """
        entity = await self._store.get_entity_profile(entity_type, entity_key)
        if entity is None or attr_name not in entity.attributes:
            return True, "新属性, 直接写入"

        old = entity.attributes[attr_name]

        if not isinstance(old, dict) or "confidence" not in old:
            return True, "旧值无置信度信息, 直接覆盖"

        old_confidence = old.get("confidence", 0.5)

        # 策略1: 置信度加权
        if new_confidence >= old_confidence * self.OVERRIDE_RATIO:
            return True, (
                f"新置信度 {new_confidence:.1f} > "
                f"旧 {old_confidence:.1f} × {self.OVERRIDE_RATIO:.1f}"
            )

        # 策略2: 过期覆盖
        old_recorded = old.get("recorded_at")
        if old_recorded:
            try:
                days_since_old = (
                    datetime.now() - datetime.fromisoformat(str(old_recorded))
                ).days
            except (ValueError, TypeError):
                days_since_old = 0

            if days_since_old > self.STALE_DAYS and new_confidence > self.STALE_CONFIDENCE_THRESHOLD:
                return True, (
                    f"旧值已过 {days_since_old} 天, "
                    f"新置信度 {new_confidence:.1f} 可接受"
                )

        # 策略3: 值不同但置信度接近时, 合并到历史(不覆盖)
        old_value = old.get("value")
        if str(old_value) != str(new_value):
            # 不覆盖, 但保留到历史(upsert 本身会追加 history)
            return False, (
                f"新置信度 {new_confidence:.1f} 不足以覆盖 "
                f"旧 {old_confidence:.1f}, 保留两个值"
            )

        # 值相同: 更新置信度(取较高者)
        if new_confidence > old_confidence:
            return True, f"值相同但置信度提升 {old_confidence:.1f} → {new_confidence:.1f}"

        return False, "值相同且置信度未提升, 跳过"

    @staticmethod
    def classify_confidence(source: str) -> float:
        """根据来源判断置信度.

        Args:
            source: 来源说明, 如 "explicit", "inferred", "system"

        Returns:
            置信度值
        """
        source_lower = source.lower()
        if source_lower in ("explicit", "user_said"):
            return 0.9
        if source_lower in ("inferred", "extracted"):
            return 0.5
        if source_lower in ("system", "default"):
            return 0.3
        return 0.5
