"""
ToolRegistry——本地工具注册中心。

管理 ToolSpec 的注册、描述查询和按名称分派执行。
支持覆盖注册策略，同名工具后注册覆盖先注册。
"""

from __future__ import annotations

from typing import Any

from src.tools._spec import ToolSpec


class ToolRegistry:
    """
    本地工具注册中心。

    管理 ToolSpec 的注册、描述查询和按名称分派执行。
    同名工具后注册覆盖先注册，方便测试 mock。

    Usage:
        >>> registry = ToolRegistry()
        >>> registry.register(ToolSpec(name="calc", handler=my_handler, ...))
        >>> specs = registry.describe()
        >>> result = await registry.execute("calc", a=1, b=2)
    """

    def __init__(self) -> None:
        """初始化空的注册中心。"""
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        """
        注册一个工具。

        同名工具后注册覆盖先注册（覆盖注册策略）。

        Args:
            spec: ToolSpec 实例。

        Raises:
            TypeError: 如果 spec 不是 ToolSpec 实例。
        """
        if not isinstance(spec, ToolSpec):
            raise TypeError(f"期望 ToolSpec 实例，收到 {type(spec).__name__}")
        self._tools[spec.name] = spec

    def unregister(self, name: str) -> None:
        """
        注销指定名称的工具。

        Args:
            name: 工具名称。

        Raises:
            KeyError: 如果工具不存在。
        """
        if name not in self._tools:
            raise KeyError(f"工具 '{name}' 未注册")
        del self._tools[name]

    def get(self, name: str) -> ToolSpec | None:
        """
        按名称获取工具。

        Args:
            name: 工具名称。

        Returns:
            ToolSpec 实例，未找到时返回 None。
        """
        return self._tools.get(name)

    def describe(self) -> list[ToolSpec]:
        """
        返回所有已注册工具的列表。

        Returns:
            ToolSpec 列表。
        """
        return list(self._tools.values())

    def list_specs(self) -> list[ToolSpec]:
        """
        返回所有已注册工具的列表（describe 的别名，与设计文档一致）。

        Returns:
            ToolSpec 列表。
        """
        return self.describe()

    async def execute(self, name: str, **kwargs: Any) -> Any:
        """
        按名称执行工具。

        执行前校验：
          - 工具必须已注册
          - 所有 required 参数必须提供
          - 不允许多余参数

        Args:
            name: 工具名称。
            kwargs: 工具参数。

        Returns:
            工具执行结果。

        Raises:
            KeyError: 如果工具未注册。
            ValueError: 如果缺少必要参数或有多余参数。
        """
        spec = self._tools.get(name)
        if spec is None:
            raise KeyError(f"工具 '{name}' 未注册")

        # 校验必要参数
        for req in spec.required:
            if req not in kwargs:
                raise ValueError(f"工具 '{name}' 缺少必要参数: {req}")

        # 校验多余参数
        extra = [k for k in kwargs if k not in spec.parameters]
        if extra:
            raise ValueError(f"工具 '{name}' 收到未知参数: {extra}")

        return await spec.handler(**kwargs)

    def __len__(self) -> int:
        """返回已注册工具数量。"""
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        """检查工具是否已注册。"""
        return name in self._tools
