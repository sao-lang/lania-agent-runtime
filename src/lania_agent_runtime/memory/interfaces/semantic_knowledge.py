"""Layer 4: 语义知识存储接口."""

from __future__ import annotations

from abc import ABC, abstractmethod

from lania_agent_runtime.models import SemanticEdge, SemanticNode


class SemanticStore(ABC):
    """语义知识存储接口 (Layer 4).

    特性:
    - 图结构 (节点 + 边)
    - 节点支持语义检索
    - 边支持关系遍历和路径查询
    """

    # ── 节点操作 ──

    @abstractmethod
    async def create_semantic_node(
        self, name: str, node_type: str = "concept", description: str = ""
    ) -> str:
        """创建节点. 如果 name 已存在则返回已有 ID (幂等)."""

    @abstractmethod
    async def read_node(self, node_id: str) -> SemanticNode | None:
        """按 ID 读取节点."""

    @abstractmethod
    async def find_node_by_name(self, name: str) -> SemanticNode | None:
        """按名称精确查找节点."""

    @abstractmethod
    async def search_semantic(
        self, query: str, *, type_filter: str | None = None, limit: int = 10
    ) -> list[SemanticNode]:
        """按名称/描述模糊搜索节点."""

    # ── 边操作 ──

    @abstractmethod
    async def create_semantic_edge(
        self,
        source_node: str,
        target_node: str,
        relation: str,
        *,
        confidence: float = 1.0,
    ) -> str:
        """创建边. 相同(source, target, relation)视为重复, 返回已有 ID."""

    @abstractmethod
    async def get_semantic_edges(
        self, node_id: str, *, direction: str = "both", limit: int = 20
    ) -> list[SemanticEdge]:
        """获取连接到某节点的边."""

    @abstractmethod
    async def get_neighbors(
        self,
        node_id: str,
        *,
        relation: str | None = None,
        max_depth: int = 1,
        limit: int = 20,
    ) -> list[tuple[SemanticNode, str]]:
        """获取邻居节点. max_depth=1 查直接邻居, >1 递归查询. 返回 [(node, relation), ...]."""

    @abstractmethod
    async def find_path(
        self,
        source_id: str,
        target_id: str,
        *,
        max_depth: int = 5,
    ) -> list[list[tuple[str, str]]]:
        """查找两节点之间的路径. 返回多条路径, 每条是 [(node_id, relation), ...]."""

    # ── 批量操作 ──

    @abstractmethod
    async def merge_knowledge(
        self,
        extractions: list[tuple[str, str, str]],
        *,
        source: str = "extracted_from_dialogue",
    ) -> None:
        """批量注入知识三元组 (source_name, relation, target_name). 自动创建不存在的节点."""

    @abstractmethod
    async def increment_mention(self, node_id: str) -> None:
        """增加节点提及计数."""

    @abstractmethod
    async def get_low_mention_nodes(
        self, threshold: int = 3, *, limit: int = 50
    ) -> list[SemanticNode]:
        """获取提及次数低于阈值的节点(冷数据)."""

    @abstractmethod
    async def delete_node(self, node_id: str) -> None:
        """删除节点及其所有边."""
