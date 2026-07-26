"""
意图分类器协议定义。

IntentClassifier 协议定义了所有意图分类器的接口规范。
任何实现了 classify 方法的对象都是 IntentClassifier。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from src.runtime.context._context import RuntimeContext


@runtime_checkable
class IntentClassifier(Protocol):
    """
    意图分类器协议。

    任何实现了 classify 方法的对象都是 IntentClassifier。
    输入用户消息上下文，输出意图名称字符串。
    未匹配时返回约定的默认意图（如 "chat"）。

    为什么是 (ctx) -> str 而不是 (query) -> str？
    因为有些分类器可能需要额外的上下文（对话历史、用户画像、
    当前 step 状态）来做判断。只传 query 会限制分类器的信息获取能力。
    """

    async def classify(self, ctx: RuntimeContext) -> str:
        """
        对用户输入进行意图分类。

        Args:
            ctx: RuntimeContext 实例，包含 messages/services 等上下文信息。

        Returns:
            意图名称字符串（如 "qa"、"coding"、"chat" 等）。
            未匹配时返回分类器预设的默认意图。
        """
        ...
