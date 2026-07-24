"""
Skill 数据模型——SkillEntry 和 SkillConfig。

定义 Skill 的元信息结构和加载后的运行时表示。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SkillConfig:
    """
    skill.toml 的 Python 表示——Skill 元信息。

    Attributes:
        name: Skill 名称，需与目录名一致。
        description: Skill 描述。
        keywords: 触发关键词列表，用于关键词匹配策略。
        priority: 匹配阈值，匹配分数 ≥ priority 时注入知识。
        auto_inject: 是否无条件注入（忽略匹配逻辑）。
    """

    name: str = ""
    """Skill 名称。"""

    description: str = ""
    """Skill 描述。"""

    keywords: list[str] = field(default_factory=list)
    """触发关键词列表。"""

    priority: int = 5
    """匹配阈值。"""

    auto_inject: bool = False
    """是否无条件注入。"""


@dataclass
class SkillEntry:
    """
    Skill 的运行时表示——包含加载后的 SKILL.md 内容和元信息。

    Attributes:
        name: Skill 名称。
        path: Skill 目录的绝对路径。
        content: SKILL.md 的全部文本内容。
        config: SkillConfig 配置（来自 skill.toml 或默认值）。
    """

    name: str
    """Skill 名称。"""

    path: str
    """Skill 目录的绝对路径。"""

    content: str
    """SKILL.md 的全部文本内容。"""

    config: SkillConfig = field(default_factory=SkillConfig)
    """Skill 配置。"""

    def match_score(self, text: str) -> int:
        """
        计算给定文本与此 Skill 的匹配分数。

        使用关键词匹配策略：命中 1 个关键词得 5 分，累加。
        如果 auto_inject 为 True，始终返回 999。

        Args:
            text: 要匹配的文本（通常是用户最近的 query）。

        Returns:
            匹配分数。
        """
        if self.config.auto_inject:
            return 999

        score = 0
        lower_text = text.lower()
        for kw in self.config.keywords:
            if kw.lower() in lower_text:
                score += 5
        return score
