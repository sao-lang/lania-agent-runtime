"""
Skill 原语包——基于 SKILL.md 的领域知识注入能力。

Skill 是 Transform 原语，在 before_llm 阶段将领域知识注入 ContextPayload。
"""

from src.tools._skill._manager import SkillManager
from src.tools._skill._models import SkillConfig, SkillEntry

__all__ = [
    "SkillManager",
    "SkillConfig",
    "SkillEntry",
]

