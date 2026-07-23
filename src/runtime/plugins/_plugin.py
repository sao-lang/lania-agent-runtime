"""
可插拔组件与插件协议。

PluggableComponent 是所有可插拔组件的统一协议。
Plugin 继承 PluggableComponent，提供简化的 hook 声明方式。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Callable

from src.runtime._types import HookPoint, PrimitiveType

if TYPE_CHECKING:
    from src.runtime._runtime import AgentRuntime


class PluggableComponent(ABC):
    """
    所有可插拔组件的统一协议。

    任何需要挂载到 AgentRuntime 的模块都实现此接口。
    runtime.use(component) 内部自动调用 on_attach()。

    子类需定义 name 属性，并可按需覆写 on_attach / on_detach。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """组件唯一标识。"""

    async def on_attach(self, runtime: "AgentRuntime") -> None:
        """
        挂载到 Runtime 时调用。

        组件在此注册自己的 hooks、executors、services。
        默认无操作——组件按需覆写。

        Args:
            runtime: AgentRuntime 实例。
        """
        pass

    async def on_detach(self) -> None:
        """
        从 Runtime 卸载时调用。

        组件在此清理资源（关闭连接、取消任务）。
        默认无操作——组件按需覆写。
        """
        pass


class Plugin(PluggableComponent):
    """
    插件——自动声明需要注册的 hooks。

    用户只需实现 _declare_hooks()，runtime.use() 自动注册。

    示例:
        class AuditPlugin(Plugin):
            name = "audit"

            def _declare_hooks(self):
                return [
                    (HookPoint.AFTER_LLM, PrimitiveType.OBSERVER,
                     self._on_llm),
                    (HookPoint.AFTER_TOOL, PrimitiveType.OBSERVER,
                     self._on_tool),
                ]

            async def _on_llm(self, event, ctx): ...
            async def _on_tool(self, event, ctx): ...
    """

    def _declare_hooks(
        self,
    ) -> list[tuple[HookPoint, PrimitiveType, Callable]]:
        """
        声明需要注册的 hooks。

        子类应覆写此方法返回 (HookPoint, PrimitiveType, handler) 元组列表。

        Returns:
            (HookPoint, PrimitiveType, Callable) 元组列表。
        """
        return []

    async def on_attach(self, runtime: "AgentRuntime") -> None:
        """
        默认实现：遍历 _declare_hooks() 的返回值，
        对每个 (point, primitive, handler) 调用 runtime.register()。

        插件可覆写此方法实现更复杂的注册逻辑。

        Args:
            runtime: AgentRuntime 实例。
        """
        for point, primitive, handler in self._declare_hooks():
            runtime.register(
                point,
                handler,
                primitive=primitive,
                name=f"{self.name}.{handler.__name__}",
            )
