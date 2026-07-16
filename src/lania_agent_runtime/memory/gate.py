"""记忆提升门控: 判断本轮对话是否值得写入持久化记忆."""

from __future__ import annotations

import re

from lania_agent_runtime.models import GateDecision


class MemoryCommitGate:
    """记忆写入门控.

    评估本轮对话的信息价值, 决定:
    - 是否写入情景记忆
    - 是否提取实体
    - 是否更新行为模式
    - 重要性分数
    """

    # 值得记录为 critical_event 的信息类型
    CRITICAL_PATTERNS = [
        r"(?:我叫|我是|我的名字|我姓|I am|I'm|my name is|I am a)",
        r"(?:我[在做了用]|我[的]?[职业工作项目]|I work as|I use|I build)",
        r"(?:我喜欢|我不喜欢|我偏好|我倾向于|I like|I love|I prefer|I enjoy)",
        r"(?:我[在正]?在(?:做|开发|使用|学习)|I am (?:building|using|learning|working on))",
        r"(?:I need help with|I want to|I'm trying to|I'd like to)",
    ]

    # 不值得记录的模式 (寒暄 / 确认 / 无信息量)
    # 注意: 加 $ 确保只匹配纯寒暄, 不误杀 "Hello with memory" 等有实质内容的消息
    SKIP_PATTERNS = [
        r"^(?:你好|hi|hello|在吗|谢谢|好的|嗯|ok|yes|no|thanks|thank you)[\s.!?]*$",
        r"^(?:是的|对的|没错|明白|了解了|收到|got it|understood|sure)[\s.!?]*$",
        r"^(?:不对|不是|错了|重来|never mind|nevermind)[\s.!?]*$",
        r"^\s*$",
        r"^(?:test|测试|试试|try|ping)[\s.!?]*$",
    ]

    # 高信息密度的关键词
    HIGH_IMPORTANCE_KEYWORDS = [
        "error", "bug", "crash", "fail", "broken", "wrong",
        "重要", "紧急", "错误", "问题", "不能用",
    ]

    async def evaluate(
        self,
        user_message: str | None,
        assistant_message: str | None,
    ) -> GateDecision:
        """评估本轮对话的信息价值.

        Args:
            user_message: 用户消息
            assistant_message: 助手回复

        Returns:
            GateDecision: 包含重要性分数和是否记录等决策
        """
        importance = 0.3  # 默认低
        reason = "general_conversation"
        should_record = True
        should_extract = False
        should_update_pattern = True

        if not user_message:
            return GateDecision(
                importance=0.0, should_record=False,
                should_extract_entities=False, should_update_pattern=False,
                reason="no_user_input",
            )

        # 跳过无信息量内容
        for pattern in self.SKIP_PATTERNS:
            if re.match(pattern, user_message.strip(), re.IGNORECASE):
                return GateDecision(
                    importance=0.0, should_record=False,
                    should_extract_entities=False, should_update_pattern=False,
                    reason=f"skipped_skip_pattern: {pattern}",
                )

        # 检测关键信息
        for pattern in self.CRITICAL_PATTERNS:
            if re.search(pattern, user_message, re.IGNORECASE):
                importance = 0.9
                reason = "critical_info"
                should_extract = True
                break

        # 检测高重要性关键词
        for kw in self.HIGH_IMPORTANCE_KEYWORDS:
            if kw.lower() in (user_message + (assistant_message or "")).lower():
                importance = max(importance, 0.8)
                reason = "high_importance_keyword"
                break

        # LLM 回复长度 (长回复通常含重要信息)
        if assistant_message and len(assistant_message) > 200:
            importance = max(importance, 0.5)
            if reason == "general_conversation":
                reason = "long_response"

        # 用户消息长度
        if len(user_message) > 100:
            importance = max(importance, 0.4)
            should_extract = True

        should_record = importance >= 0.3

        return GateDecision(
            importance=importance,
            should_record=should_record,
            should_extract_entities=should_extract or should_record,
            should_update_pattern=should_update_pattern,
            reason=reason,
        )
