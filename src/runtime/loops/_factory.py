"""
LoopStrategy 工厂模块——LoopStrategyFactory。

负责根据策略名称创建对应的 LoopStrategy 实例。
支持运行时注册新策略（扩展点）——注册项可以是策略类或工厂函数，
内置三种策略（react / plan_and_execute / workflow）在首次 create 时懒注册。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.runtime.loops._base import LoopStrategy

# 策略工厂类型：策略类（type[LoopStrategy]）或任意接收 **kwargs 返回策略实例的工厂函数
LoopFactory = Callable[..., "LoopStrategy"]

# 模块级注册表（替代类级可变状态，避免所有 Runtime 实例共享同一字典
# 带来的并发安全隐患）
_registry: dict[str, LoopFactory] = {}

# 内置策略名称 → 具体类（延迟加载，避免模块导入期循环依赖）
_BUILTIN_FACTORIES: dict[str, LoopFactory] | None = None


def _ensure_builtins() -> None:
    """懒注册内置策略（幂等）。

    仅在名称缺失时补注册，不覆盖用户已注册的同名工厂。
    具体类在首次调用时延迟导入，避免模块级循环依赖。
    """
    global _BUILTIN_FACTORIES
    builtins = _BUILTIN_FACTORIES
    if builtins is None:
        from src.runtime.loops._plan_execute import PlanExecuteLoop
        from src.runtime.loops._react import ReActLoop
        from src.runtime.loops._workflow import WorkflowLoop

        builtins = {
            "react": ReActLoop,
            "plan_and_execute": PlanExecuteLoop,
            "workflow": WorkflowLoop,
        }
        _BUILTIN_FACTORIES = builtins
    for name, factory in builtins.items():
        if name not in _registry:
            _registry[name] = factory


class LoopStrategyFactory:
    """
    LoopStrategy 工厂。

    通过名称注册和创建策略实例。
    各策略所需的构造参数不同，通过 **kwargs 传入。

    使用方式：
        LoopStrategyFactory.register("react", ReActLoop)
        # 或用工厂函数注册自定义策略，工厂可声明自己的构造参数
        LoopStrategyFactory.register("my_loop", lambda **kw: MyLoop(**kw))
        strategy = LoopStrategyFactory.create("my_loop", hooks=hooks, step_runner=runner, foo=1)
    """

    # 指向模块级 _registry——所有实例/测试共享同一注册表
    _registry: dict[str, LoopFactory] = _registry

    @classmethod
    def register(
        cls,
        name: str,
        factory: type[LoopStrategy] | Callable[..., LoopStrategy],
    ) -> None:
        """注册一个策略工厂（策略类或工厂函数）到工厂。

        Args:
            name: 策略名称。
            factory: 策略类（type[LoopStrategy]）或接收 **kwargs 返回策略实例的工厂函数。

        Raises:
            ValueError: 如果策略名称已注册。
        """
        if name in cls._registry:
            raise ValueError(f"策略 '{name}' 已注册")
        cls._registry[name] = factory

    @classmethod
    def create(cls, name: str, **kwargs: Any) -> LoopStrategy:
        """通过工厂创建策略实例。

        Args:
            name: 策略名称（内置或已注册的自定义名称）。
            **kwargs: 传递给策略构造函数的参数。

        Returns:
            LoopStrategy 实例。

        Raises:
            ValueError: 如果策略名称未注册。
        """
        _ensure_builtins()
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
