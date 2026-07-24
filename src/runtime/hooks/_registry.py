"""
Hook 注册中心——HookRegistry 分层编排引擎。

同一 hook point 上按以下顺序执行：
  1. Transformer（按 priority 升序）
  2. Interceptor（按 priority 升序，遇到 block/pause 短路）
  3. Observer（按 priority 升序，全部执行不阻塞）
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Callable

from src.runtime._types import (
    AllowAction,
    BlockAction,
    Event,
    HandlerInfo,
    HookPoint,
    InterceptResult,
    PauseAction,
    PrimitiveType,
)


@dataclass
class HandlerRecord:
    """内部 handler 记录——比 HandlerInfo 多存储已解析的 primitive 分类。"""

    handler_id: str
    point: HookPoint
    primitive: PrimitiveType
    handler: Callable
    priority: int = 0
    name: str = ""
    enabled: bool = True


class HookRegistry:
    """
    Hook 注册中心——分层编排引擎。

    同一 hook point 上按以下顺序执行：
      1. Transformer（按 priority 升序）
      2. Interceptor（按 priority 升序，遇到 block/pause 短路）
      3. Observer（按 priority 升序，全部执行不阻塞）
    """

    def __init__(self) -> None:
        """初始化空的 HookRegistry。"""
        self._handlers: dict[str, HandlerRecord] = {}
        self._point_handlers: dict[HookPoint, list[HandlerRecord]] = {
            point: [] for point in HookPoint
        }

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
        注册一个 handler。

        Args:
            point: 挂载点。
            handler: handler 可调用对象。
            primitive: 原语类型，必须显式指定。
            name: 可选的可读名称，用于调试/热加载。
            priority: 可选优先级，值越小越先执行。

        Returns:
            handler_id，可用于后续 remove/replace 操作。
        """
        handler_id = f"{point.value}.{name or handler.__name__}.{uuid.uuid4().hex[:8]}"

        record = HandlerRecord(
            handler_id=handler_id,
            point=point,
            primitive=primitive,
            handler=handler,
            priority=priority,
            name=name or handler.__name__,
        )

        self._handlers[handler_id] = record
        self._point_handlers[point].append(record)
        self._point_handlers[point].sort(key=lambda r: r.priority)

        return handler_id

    def remove(self, handler_id: str) -> None:
        """
        移除已注册的 handler。

        Args:
            handler_id: 要移除的 handler 的 ID。

        Raises:
            KeyError: 如果 handler_id 不存在。
        """
        record = self._handlers.pop(handler_id)
        point_list = self._point_handlers[record.point]
        for i, r in enumerate(point_list):
            if r.handler_id == handler_id:
                point_list.pop(i)
                break

    def copy(self) -> HookRegistry:
        """
        深拷贝当前 HookRegistry。

        创建全新的 HookRegistry 实例，所有 handler 引用保持不变。
        用于 Multi-Agent 场景：父 Agent 的 hooks 拷贝后与子 Agent hooks 合并。

        Returns:
            HookRegistry 新实例。
        """
        new_registry = HookRegistry()
        for record in self._handlers.values():
            new_registry.register(
                record.point,
                record.handler,
                primitive=record.primitive,
                name=record.name,
                priority=record.priority,
            )
        return new_registry

    def list(self, point: HookPoint | None = None) -> list[HandlerInfo]:
        """
        列出所有（或指定 point 的）已注册 handler。

        Args:
            point: 可选，指定挂载点进行过滤。

        Returns:
            HandlerInfo 列表。
        """
        if point is not None:
            return [
                HandlerInfo(
                    handler_id=r.handler_id,
                    point=r.point,
                    primitive=r.primitive,
                    handler=r.handler,
                    priority=r.priority,
                    name=r.name,
                    enabled=r.enabled,
                )
                for r in self._point_handlers[point]
            ]

        result: list[HandlerInfo] = []
        for records in self._point_handlers.values():
            for r in records:
                result.append(
                    HandlerInfo(
                        handler_id=r.handler_id,
                        point=r.point,
                        primitive=r.primitive,
                        handler=r.handler,
                        priority=r.priority,
                        name=r.name,
                        enabled=r.enabled,
                    )
                )
        return result

    def enable(self, handler_id: str, enabled: bool = True) -> None:
        """
        启用或禁用指定 handler。

        Args:
            handler_id: handler 的 ID。
            enabled: True 启用，False 禁用。

        Raises:
            KeyError: 如果 handler_id 不存在。
        """
        record = self._handlers[handler_id]
        record.enabled = enabled

        # 同步更新 point_handlers 中的引用
        for r in self._point_handlers[record.point]:
            if r.handler_id == handler_id:
                r.enabled = enabled
                break

    def disable(self, handler_id: str) -> None:
        """禁用指定 handler 的快捷方式。"""
        self.enable(handler_id, enabled=False)

    def replace(self, handler_id: str, new_handler: Callable) -> None:
        """
        替换已注册的 handler（保持 point / primitive / priority 不变）。

        Args:
            handler_id: 要替换的 handler 的 ID。
            new_handler: 新的 handler 可调用对象。

        Raises:
            KeyError: 如果 handler_id 不存在。
        """
        record = self._handlers[handler_id]
        record.handler = new_handler

        # 同步更新 point_handlers 中的引用
        for r in self._point_handlers[record.point]:
            if r.handler_id == handler_id:
                r.handler = new_handler
                break

    async def run_transformers(self, point: HookPoint, data: Any, ctx: Any) -> Any:
        """
        执行指定 point 上所有 Transform，返回最终 data。

        Args:
            point: 挂载点。
            data: 输入数据。
            ctx: RuntimeContext 实例。

        Returns:
            经过所有 Transform 处理后的数据。
        """
        for record in self._point_handlers[point]:
            if record.primitive == PrimitiveType.TRANSFORM and record.enabled:
                data = await record.handler(data, ctx)
        return data

    async def run_interceptors(self, point: HookPoint, data: Any, ctx: Any) -> InterceptResult:
        """
        执行指定 point 上所有 Intercept，返回第一个 block/pause 或最终 allow。

        Args:
            point: 挂载点。
            data: 输入数据。
            ctx: RuntimeContext 实例。

        Returns:
            第一个 BlockAction 或 PauseAction，或所有 Intercept 放行后的 AllowAction。
        """
        for record in self._point_handlers[point]:
            if record.primitive == PrimitiveType.INTERCEPT and record.enabled:
                result = await record.handler(data, ctx)
                if isinstance(result, (BlockAction, PauseAction)):
                    return result
                if isinstance(result, AllowAction) and (result.modified is not None):
                    data = result.modified
        # 返回带最后修改数据的 AllowAction
        return AllowAction(modified=data)

    async def run_observers(self, point: HookPoint, event: Event, ctx: Any) -> None:
        """
        并发执行指定 point 上所有 Observer。

        Args:
            point: 挂载点。
            event: 事件数据。
            ctx: RuntimeContext 实例。
        """
        import asyncio

        tasks = []
        for record in self._point_handlers[point]:
            if record.primitive == PrimitiveType.OBSERVER and record.enabled:
                tasks.append(record.handler(event, ctx))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
