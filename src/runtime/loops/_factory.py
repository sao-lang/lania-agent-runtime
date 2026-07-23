"""
LoopStrategy 工厂模块——LoopStrategyFactory。

负责根据策略名称创建对应的 LoopStrategy 实例。
支持运行时注册新策略（扩展点）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.runtime.loops._base import LoopStrategy


class LoopStrategyFactory:
    """
    LoopStrategy 工厂。

    通过名称注册和创建策略实例。
    各策略所需的构造参数不同，通过 **kwargs 传入。

    使用方式：
        LoopStrategyFactory.register("react", ReActLoop)
        strategy = LoopStrategyFactory.create("react", hooks=hooks, step_runner=runner)
    """

    _registry: dict[str, type[LoopStrategy]] = {}

    @classmethod
    def register(cls, name: str, strategy_cls: type[LoopStrategy]) -> None:
        """
        注册一个策略类到工厂。

        Args:
            name: 策略名称（如 "react", "plan_and_execute", "workflow"）。
            strategy_cls: 策略类（必须是 LoopStrategy 子类）。

        Raises:
            ValueError: 如果名称已注册。
        """
        if name in cls._registry:
            raise ValueError(f"策略 '{name}' 已注册")
        cls._registry[name] = strategy_cls

    @classmethod
    def create(cls, name: str, **kwargs: Any) -> LoopStrategy:
        """
        通过工厂创建策略实例。

        Args:
            name: 策略名称。
            **kwargs: 传递给策略构造函数的参数。
                - react: hooks, step_runner, router=None
                - plan_and_execute: hooks, step_runner, router=None,
                  planner_prompt="", max_replans=3
                - workflow: hooks, step_runner, workflow_definition

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
        """
        获取所有已注册的策略名称列表。

        Returns:
            策略名称列表。
        """
        return list(cls._registry.keys())

    @classmethod
    def unregister(cls, name: str) -> None:
        """
        注销一个策略。

        Args:
            name: 要注销的策略名称。

        Raises:
            ValueError: 如果策略名称未注册。
        """
        if name not in cls._registry:
            raise ValueError(f"未知的策略: '{name}'")
        del cls._registry[name]

    @classmethod
    def clear(cls) -> None:
        """清空所有注册的策略。"""
        cls._registry.clear()
