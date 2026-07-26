"""
意图路由模块——可插拔的 IntentClassifier 协议与实现。

提供三种分类器实现：
  - RuleClassifier：关键词规则匹配，零依赖、O(n) 延迟
  - LLMClassifier：LLM 分类，灵活处理复杂语义
  - HybridClassifier：混合策略（规则兜底 + LLM 补充）

使用方式：
    from src.intent import RuleClassifier, LLMClassifier, HybridClassifier

    classifier = RuleClassifier(
        rules={"qa": ["什么", "为什么"], "coding": ["代码", "bug"]},
        default="chat",
    )
    intent = await classifier.classify(ctx)
"""

from src.intent._classifiers import HybridClassifier, LLMClassifier, RuleClassifier
from src.intent._protocols import IntentClassifier

__all__ = [
    "IntentClassifier",
    "RuleClassifier",
    "LLMClassifier",
    "HybridClassifier",
]
