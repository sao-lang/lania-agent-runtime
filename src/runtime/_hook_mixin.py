"""
HookRegistratorMixin——AgentRuntime 的 Hook 注册方法集。

提取自 AgentRuntime，职责：观察/变换/拦截/注册/装饰器语法糖。
"""

from __future__ import annotations

from typing import Callable

from src.runtime._types import HookPoint, PrimitiveType


class HookRegistratorMixin:
    """Hook 注册方法集。"""

    # ============ 注册方法 ============

    def observe(
        self,
        point: HookPoint,
        handler: Callable,
        *,
        name: str = "",
        priority: int = 0,
    ) -> str:
        """
        注册 Observer hook。

        Args:
            point: 挂载点。
            handler: Observer handler。
            name: 可选名称。
            priority: 优先级（值越小越先执行）。

        Returns:
            handler_id。
        """
        return self._hooks.register(
            point,
            handler,
            primitive=PrimitiveType.OBSERVER,
            name=name,
            priority=priority,
        )

    def transform(
        self,
        point: HookPoint,
        handler: Callable,
        *,
        name: str = "",
        priority: int = 0,
    ) -> str:
        """
        注册 Transformer hook。

        Args:
            point: 挂载点。
            handler: Transformer handler。
            name: 可选名称。
            priority: 优先级（值越小越先执行）。

        Returns:
            handler_id。
        """
        return self._hooks.register(
            point,
            handler,
            primitive=PrimitiveType.TRANSFORM,
            name=name,
            priority=priority,
        )

    def intercept(
        self,
        point: HookPoint,
        handler: Callable,
        *,
        name: str = "",
        priority: int = 0,
    ) -> str:
        """
        注册 Interceptor hook。

        Args:
            point: 挂载点。
            handler: Interceptor handler。
            name: 可选名称。
            priority: 优先级（值越小越先执行）。

        Returns:
            handler_id。
        """
        return self._hooks.register(
            point,
            handler,
            primitive=PrimitiveType.INTERCEPT,
            name=name,
            priority=priority,
        )

    def register(
        self,
        point: HookPoint,
        handler: Callable,
        *,
        primitive: PrimitiveType,
        name: str = "",
        priority: int = 0,
    ) -> str:
        """
        通用注册方法——注册任意原语类型的 handler。

        Args:
            point: 挂载点。
            handler: handler 可调用对象。
            primitive: 原语类型。
            name: 可选名称。
            priority: 优先级（值越小越先执行）。

        Returns:
            handler_id。
        """
        return self._hooks.register(
            point, handler, primitive=primitive, name=name, priority=priority
        )

    # ============ 装饰器语法糖 ============

    def on(
        self,
        point: HookPoint,
        *,
        primitive: PrimitiveType = PrimitiveType.OBSERVER,
        priority: int = 0,
    ) -> Callable:
        """
        装饰器：@runtime.on(HookPoint.AFTER_LLM)

        Args:
            point: 挂载点。
            primitive: 原语类型，默认为 OBSERVER。
            priority: 优先级。
        """

        def decorator(func: Callable) -> Callable:
            self._hooks.register(point, func, primitive=primitive, priority=priority)
            return func

        return decorator
