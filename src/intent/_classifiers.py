"""
意图分类器实现——RuleClassifier / LLMClassifier / HybridClassifier。

三种分类器均遵循 IntentClassifier 协议：
  - RuleClassifier：关键词规则匹配，零依赖、O(n) 延迟、适合简单场景
  - LLMClassifier：LLM 分类，灵活处理复杂语义、适合生产环境
  - HybridClassifier：混合策略（规则兜底 + LLM 补充），兼顾低延迟和高准确率
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Awaitable, Callable

if TYPE_CHECKING:
    from src.runtime.context._context import RuntimeContext


class RuleClassifier:
    """
    关键词规则匹配分类器。

    零依赖、O(n) 延迟，适合简单场景。
    根据预设的关键词规则匹配用户输入，返回对应的意图名称。
    未匹配任何规则时返回默认意图。

    可直接作为 Callable 使用（__call__ 委托给 classify），
    满足 add_intent_route 的 Callable[[RuntimeContext], Awaitable[str]] 类型要求。

    Usage:
        classifier = RuleClassifier(
            rules={
                "qa": ["什么", "为什么", "如何", "怎么"],
                "coding": ["代码", "实现", "bug", "函数", "类"],
            },
            default="chat",
        )
        intent = await classifier.classify(ctx)
        # 或直接 await classifier(ctx)
    """

    def __init__(
        self,
        rules: dict[str, list[str]],
        default: str = "chat",
    ) -> None:
        """
        初始化规则分类器。

        Args:
            rules: 意图名称到关键词列表的映射。关键词会被转为小写进行匹配。
            default: 未匹配任何规则时返回的默认意图。
        """
        self._rules: dict[str, list[str]] = {k: [kw.lower() for kw in v] for k, v in rules.items()}
        self._default = default

    async def __call__(self, ctx: RuntimeContext) -> str:
        """委托给 classify，使得分类器实例可直接作为 Callable 使用。"""
        return await self.classify(ctx)

    async def classify(self, ctx: RuntimeContext) -> str:
        """
        对用户输入进行关键词规则匹配。

        Args:
            ctx: RuntimeContext 实例。

        Returns:
            匹配的意图名称，未匹配时返回 default。
        """
        query = self._get_query(ctx)
        query_lower = query.lower()
        for intent, keywords in self._rules.items():
            if any(kw in query_lower for kw in keywords):
                return intent
        return self._default

    @staticmethod
    def _get_query(ctx: RuntimeContext) -> str:
        """
        从 RuntimeContext 中提取用户最新消息。

        Args:
            ctx: RuntimeContext 实例。

        Returns:
            用户最新消息的文本内容，如果没有则返回空字符串。
        """
        for msg in reversed(ctx.messages):
            if isinstance(msg, dict) and msg.get("role") == "user":
                content = msg.get("content", "")
                return str(content) if content else ""
        return ""


class LLMClassifier:
    """
    LLM 分类器。

    使用 LLM 对用户输入进行意图分类，灵活处理复杂语义，适合生产环境。
    通过 prompt 指导 LLM 从预定义分类中选择最匹配的意图。

    可直接作为 Callable 使用（__call__ 委托给 classify）。

    Usage:
        classifier = LLMClassifier(
            llm=lambda prompt: llm_executor(prompt),
            categories=["qa", "coding", "summary", "chat"],
            default="chat",
        )
        intent = await classifier.classify(ctx)
    """

    def __init__(
        self,
        llm: Callable[[str], Awaitable[str]],
        categories: list[str],
        default: str = "chat",
    ) -> None:
        """
        初始化 LLM 分类器。

        Args:
            llm: LLM 调用函数，接收 prompt 字符串返回分类结果字符串。
            categories: 可选的意图分类列表。
            default: LLM 返回不在 categories 中时使用的默认意图。
        """
        self._llm = llm
        self._categories = categories
        self._default = default

    async def __call__(self, ctx: RuntimeContext) -> str:
        """委托给 classify，使得分类器实例可直接作为 Callable 使用。"""
        return await self.classify(ctx)

    async def classify(self, ctx: RuntimeContext) -> str:
        """
        使用 LLM 对用户输入进行意图分类。

        Args:
            ctx: RuntimeContext 实例。

        Returns:
            LLM 分类结果，若不在 categories 中则返回 default。
        """
        query = self._get_query(ctx)
        prompt = (
            "从以下分类中选择最匹配用户意图的一项：\n"
            + "\n".join(f"- {c}" for c in self._categories)
            + f"\n\n用户输入：{query}\n"
            + "只返回分类名称，不要任何额外内容。"
        )
        result = (await self._llm(prompt)).strip().lower()
        return result if result in self._categories else self._default

    @staticmethod
    def _get_query(ctx: RuntimeContext) -> str:
        """
        从 RuntimeContext 中提取用户最新消息。

        Args:
            ctx: RuntimeContext 实例。

        Returns:
            用户最新消息的文本内容，如果没有则返回空字符串。
        """
        for msg in reversed(ctx.messages):
            if isinstance(msg, dict) and msg.get("role") == "user":
                content = msg.get("content", "")
                return str(content) if content else ""
        return ""


class HybridClassifier:
    """
    混合分类器——规则兜底 + LLM 补充（推荐方案）。

    规则分类置信度足够高时直接返回，否则走 LLM。
    兼顾低延迟（简单 query 秒回）和高准确率（复杂 query 走 LLM）。

    匹配强度判断：命中的关键词数量 >= threshold 时走规则，
    否则走 LLM 进行更精确的分类。

    可直接作为 Callable 使用（__call__ 委托给 classify）。

    Usage:
        classifier = HybridClassifier(
            rules={"coding": ["代码", "实现", "bug"]},
            llm=llm_func,
            categories=["qa", "coding", "summary", "chat"],
            threshold=2,
        )
        intent = await classifier.classify(ctx)
    """

    def __init__(
        self,
        rules: dict[str, list[str]],
        llm: Callable[[str], Awaitable[str]],
        categories: list[str],
        threshold: int = 3,
        default: str = "chat",
    ) -> None:
        """
        初始化混合分类器。

        Args:
            rules: 意图名称到关键词列表的映射。
            llm: LLM 调用函数，接收 prompt 返回分类结果。
            categories: LLM 可选的意图分类列表。
            threshold: 规则匹配的阈值，至少匹配 threshold 个关键词才走规则。
            default: 默认意图。
        """
        self._rule = RuleClassifier(rules, default)
        self._llm = LLMClassifier(llm, categories, default)
        self._threshold = threshold
        self._rules = rules

    async def __call__(self, ctx: RuntimeContext) -> str:
        """委托给 classify，使得分类器实例可直接作为 Callable 使用。"""
        return await self.classify(ctx)

    async def classify(self, ctx: RuntimeContext) -> str:
        """
        对用户输入进行混合策略分类。

        先尝试规则匹配，若匹配强度 >= threshold 则直接返回；
        否则走 LLM 分类。

        Args:
            ctx: RuntimeContext 实例。

        Returns:
            意图名称字符串。
        """
        # 先走规则分类
        intent = await self._rule.classify(ctx)

        # 检查匹配强度
        query = RuleClassifier._get_query(ctx).lower()
        matched = sum(1 for kw in self._rules.get(intent, []) if kw in query)

        if matched >= self._threshold:
            return intent

        # 匹配不足，走 LLM
        return await self._llm.classify(ctx)
