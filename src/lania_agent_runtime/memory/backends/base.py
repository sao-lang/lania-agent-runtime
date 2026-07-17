"""存储后端抽象基类: 用户只需实现 ~12 个原语方法, 5 层记忆逻辑由 GenericMemoryStore 自动完成."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class StorageBackend(ABC):
    """存储后端原语接口.

    用户实现自定义存储 (Redis / MongoDB / Postgres 等) 只需实现这 ~12 个方法.
    框架自动处理 5 层记忆的所有业务逻辑 (append-only、UPSERT、图遍历、TTL 管理等).

    Usage:
        class RedisBackend(StorageBackend):
            ...
    """

    # ── 生命周期 ──

    @abstractmethod
    async def initialize(self) -> None:
        """初始化连接/连接池."""

    @abstractmethod
    async def close(self) -> None:
        """关闭连接/释放资源."""

    # ── KV 存储 (用于 Working / Entity / Pattern) ──

    @abstractmethod
    async def kv_set(self, key: str, value: str, ttl: int | None = None) -> None:
        """写入 KV, 已存在则覆盖. ttl 为过期秒数."""

    @abstractmethod
    async def kv_get(self, key: str) -> str | None:
        """读取 KV, 过期或不存在返回 None."""

    @abstractmethod
    async def kv_delete(self, key: str) -> None:
        """删除 KV."""

    @abstractmethod
    async def kv_exists(self, key: str) -> bool:
        """检查 KV 是否存在且未过期."""

    # ── 有序列表 (用于 Episodic append-only) ──

    @abstractmethod
    async def list_push(self, key: str, value: str) -> None:
        """追加到列表尾部 (append)."""

    @abstractmethod
    async def list_range(
        self, key: str, start: int, stop: int
    ) -> list[str]:
        """读取列表片段, 按插入顺序 0=最早, -1=最新. 类似 Redis LRANGE."""

    @abstractmethod
    async def list_len(self, key: str) -> int:
        """列表长度."""

    @abstractmethod
    async def list_remove(self, key: str, value: str, count: int = 0) -> None:
        """删除列表中匹配的值. count=0 删除全部."""

    # ── 集合索引 (用于 Episodic 实体/话题搜索) ──

    @abstractmethod
    async def set_add(self, key: str, *values: str) -> None:
        """向集合添加元素."""

    @abstractmethod
    async def set_members(self, key: str) -> set[str]:
        """获取集合全部元素."""

    @abstractmethod
    async def set_intersect(self, keys: list[str]) -> set[str]:
        """多个集合的交集."""

    # ── 图存储 (用于 Semantic) ──

    @abstractmethod
    async def graph_node_create(
        self,
        node_id: str,
        name: str,
        type: str = "concept",
        description: str = "",
    ) -> bool:
        """创建节点, 返回 True=新建, False=已存在."""

    @abstractmethod
    async def graph_node_get(self, node_id: str) -> dict[str, Any] | None:
        """按 ID 读取节点."""

    @abstractmethod
    async def graph_node_find_by_name(self, name: str) -> dict[str, Any] | None:
        """按名称精确查找节点."""

    @abstractmethod
    async def graph_node_search(
        self,
        query: str,
        type_filter: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """模糊搜索节点名称/描述."""

    @abstractmethod
    async def graph_node_increment_mention(self, node_id: str) -> None:
        """增加节点提及计数."""

    @abstractmethod
    async def graph_node_get_low_mention(
        self, threshold: int = 3, limit: int = 50
    ) -> list[dict[str, Any]]:
        """获取提及次数低于阈值的节点 (冷数据标记)."""

    @abstractmethod
    async def graph_node_delete(self, node_id: str) -> None:
        """删除节点及其所有边."""

    @abstractmethod
    async def graph_edge_create(
        self,
        source_node: str,
        target_node: str,
        relation: str,
        confidence: float = 1.0,
    ) -> bool:
        """创建边, 相同 (source, target, relation) 视为重复返回 False."""

    @abstractmethod
    async def graph_edge_list(
        self,
        node_id: str,
        direction: str = "both",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """列出连接到某节点的边."""

    @abstractmethod
    async def graph_neighbors(
        self,
        node_id: str,
        relation: str | None = None,
        max_depth: int = 1,
        limit: int = 20,
    ) -> list[tuple[dict[str, Any], str]]:
        """获取邻居节点, 返回 [(node, relation), ...]."""

    @abstractmethod
    async def graph_find_path(
        self,
        source_id: str,
        target_id: str,
        max_depth: int = 5,
    ) -> list[list[tuple[str, str]]]:
        """查找两节点间路径, 返回多条路径."""

    # ── 分布式锁 (用于 Pattern 收敛防冲突) ──

    @abstractmethod
    async def acquire_lock(self, lock_id: str, ttl: int = 30) -> bool:
        """获取锁, 返回 True 表示成功. 已有锁则返回 False."""
