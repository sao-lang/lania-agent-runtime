"""
LoopStrategy 工厂模块——LoopStrategyFactory。

负责根据策略名称创建对应的 LoopStrategy 实例。
支持运行时注册新策略（扩展点）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.runtime.loops._base import LoopStrategy

# 模块级注册表（替代类级可变状态，避免所有 Runtime 实例共享同一字典
# 带来的并发安全隐患）
_registry: dict[str, type[LoopStrategy]] = {}


class LoopStrategyFactory:
    """
    LoopStrategy 工厂。

    通过名称注册和创建策略实例。
    各策略所需的构造参数不同，通过 **kwargs 传入。

    使用方式：
        LoopStrategyFactory.register("react", ReActLoop)
        strategy = LoopStrategyFactory.create("react", hooks=hooks, step_runner=runner)
    """

    # 指向模块级 _registry——所有实例/测试共享同一注册表
    _registry: dict[str, type[LoopStrategy]] = _registry

    @classmethod
    def register(cls, name: str, strategy_cls: type[LoopStrategy]) -> None:
        """注册一个策略类到工厂。"""
        if name in cls._registry:
            raise ValueError(f"策略 '{name}' 已注册")
        cls._registry[name] = strategy_cls

    @classmethod
    def create(cls, name: str, **kwargs: Any) -> LoopStrategy:
        """通过工厂创建策略实例。

        Args:
            name: 策略名称。
            **kwargs: 传递给策略构造函数的参数。

        Returns:
            LoopStrategy 实例。

        Raises:
            ValueError: 如果策略名称未注册。
        """
        if name not in cls._registry:
            raise ValueError(f"未知的策略: '{name}'，可用策略: {', '.join(cls.available())}")
        return cls._registry[name](**kwargs)

    @classmethod
    def available(cls) -> list[str]:
        """获取所有已注册的策略名称列表。"""
        return list(cls._registry.keys())

    @classmethod
    def unregister(cls, name: str) -> None:
        """注销一个策略。"""
        if name not in cls._registry:
            raise ValueError(f"未知的策略: '{name}'")
        del cls._registry[name]

    @classmethod
    def clear(cls) -> None:
        """清空所有注册的策略。"""
        cls._registry.clear()
