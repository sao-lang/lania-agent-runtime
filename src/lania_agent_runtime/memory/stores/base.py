"""存储引擎抽象基类: 定义连接生命周期接口.

所有具体存储引擎 (SQLite, PostgreSQL, MongoDB 等) 需实现此接口.
Store 实现通过组合方式持有 StorageEngine 实例, 而非继承.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class StorageEngine(ABC):
    """存储引擎抽象基类.

    负责连接管理生命周期 (初始化/关闭).
    Store 实现通过依赖注入持有引擎实例, 而非继承.
    """

    @abstractmethod
    async def initialize(self) -> None:
        """初始化连接/连接池."""

    @abstractmethod
    async def close(self) -> None:
        """关闭连接/释放资源."""
