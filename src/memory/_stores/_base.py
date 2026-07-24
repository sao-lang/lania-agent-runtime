"""
Store 基类——BaseStore。

提供通用的 JSON 序列化/反序列化基础设施，消除 5 个 Store 中重复的
json.dumps / json.loads / try-except 模板代码。

每个 Store 继承 BaseStore，实现 _to_dict(obj) 和 _from_dict(raw)，
由基类统一处理序列化管道的公共部分。
"""

from __future__ import annotations

import json
from typing import Any, Callable, Generic, TypeVar

from src.memory._persistence import MemoryPersistence

T = TypeVar("T")


class BaseStore(Generic[T]):
    """
    Store 基类。

    提供标准化的 JSON 序列化/反序列化公共方法。
    子类只需实现 _to_dict / _from_dict 完成模型 ↔ dict 转换。

    Usage:
        class MyStore(BaseStore):
            def _to_dict(self, obj: MyModel) -> dict:
                return {"field": obj.field, ...}

            def _from_dict(self, raw: dict) -> MyModel:
                return MyModel(field=raw["field"], ...)
    """

    def __init__(self, persistence: MemoryPersistence) -> None:
        """
        初始化 BaseStore。

        Args:
            persistence: MemoryPersistence 实例。
        """
        self._store = persistence

    # ── 公共序列化辅助方法 ──

    def _serialize_json(self, obj: Any, to_dict: Callable[[Any], dict]) -> bytes:
        """
        将对象序列化为 JSON bytes。

        使用 ensure_ascii=False 保留 Unicode，default=str 兜底不可序列化类型。

        Args:
            obj: 要序列化的对象。
            to_dict: 将对象转换为 dict 的回调函数。

        Returns:
            UTF-8 编码的 JSON bytes。
        """
        data = to_dict(obj)
        return json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")

    def _deserialize_json(
        self,
        data: bytes,
        from_dict: Callable[[dict], T],
    ) -> T | None:
        """
        将 JSON bytes 反序列化为对象。

        统一处理 JSONDecodeError / KeyError / TypeError。

        Args:
            data: UTF-8 编码的 JSON bytes。
            from_dict: 从 dict 重建对象的回调函数。

        Returns:
            反序列化后的对象，解析失败则返回 None。
        """
        try:
            raw = json.loads(data.decode("utf-8"))
            return from_dict(raw)
        except (json.JSONDecodeError, KeyError, TypeError):
            return None
