"""
MemoryCommitGate——记忆写入门控。

判断本轮对话是否值得写入持久化记忆。
基于正则模式匹配和消息长度评估信息密度。
"""

from __future__ import annotations

import re

from src.memory._types import GateDecision


class MemoryCommitGate:
    """
    记忆写入门控——判断本轮对话是否值得写入持久化记忆。

    基于规则判断：
    - 跳过寒暄/确认/无信息量内容
    - 检测关键信息（自我介绍、偏好、项目等）
    - 长回复自动提升重要性
    """

    # 值得记录为 critical_event 的信息类型
    CRITICAL_PATTERNS: list[str] = [
        r"(?:我叫|我是|我的名字|我姓)",
        r"(?:我[在做了用]|我[的]?[职业工作项目])",
        r"(?:我喜欢|我不喜欢|我偏好|我倾向于)",
        r"(?:我[在正]?在(?:做|开发|使用|学习))",
    ]

    # 不值得记录的模式
    SKIP_PATTERNS: list[str] = [
        r"^(?:你好|hi|hello|在吗|谢谢|好的|嗯|ok)",
        r"^(?:是的|对的|没错|明白|了解了|收到)",
        r"^(?:不对|不是|错了|重来)",
        r"^\s*$",
    ]

    def __init__(self) -> None:
        """初始化门控。"""
        self._critical_patterns = [
            re.compile(p) for p in self.CRITICAL_PATTERNS
        ]
        self._skip_patterns = [
            re.compile(p) for p in self.SKIP_PATTERNS
        ]

    async def evaluate(
        self,
        user_message: str | None,
        assistant_message: str | None,
    ) -> GateDecision:
        """
        评估本轮对话的信息价值。

        Args:
            user_message: 用户消息文本。
            assistant_message: 助理消息文本。

        Returns:
            门控决策结果。
        """
        importance = 0.3
        reason = "general_conversation"

        if not user_message:
            return GateDecision(
                importance=0.0, should_record=False, reason="no_user_input",
            )

        stripped = user_message.strip()

        # 跳过无信息量内容
        for pattern in self._skip_patterns:
            if pattern.match(stripped):
                return GateDecision(
                    importance=0.0,
                    should_record=False,
                    reason="skip_pattern_matched",
                )

        # 检测关键信息
        for pattern in self._critical_patterns:
            if pattern.search(stripped):
                importance = 0.9
                reason = "critical_info"
                break

        # LLM 回复长度（长回复通常含重要信息）
        if assistant_message and len(assistant_message) > 200:
            importance = max(importance, 0.5)
            if reason == "general_conversation":
                reason = "long_response"

        should_record = importance >= 0.3

        return GateDecision(
            importance=importance,
            should_record=should_record,
            reason=reason,
        )
