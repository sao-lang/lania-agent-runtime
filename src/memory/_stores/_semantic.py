"""
SemanticKnowledgeStore——语义知识存储适配器。

基于 MemoryPersistence 实现。
节点键名前缀 sn:{node_id}，边键名前缀 se:{source_id}:{target_id}:{relation}。
特性：
- 图结构（节点 + 边）
- 边支持关系遍历
- 节点名唯一（幂等创建）
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from src.memory._persistence import MemoryPersistence
from src.memory._types import SemanticEdge, SemanticNode


class SemanticKnowledgeStore:
    """
    语义知识存储适配器。

    将 SemanticNode / SemanticEdge 的读写转化为 MemoryPersistence 的键值操作。
    """

    def __init__(self, persistence: MemoryPersistence) -> None:
        """
        初始化 SemanticKnowledgeStore。

        Args:
            persistence: MemoryPersistence 实例。
        """
        self._store = persistence

    def _node_key(self, node_id: str) -> str:
        return f"sn:{node_id}"

    def _edge_key(self, source_id: str, target_id: str, relation: str) -> str:
        return f"se:{source_id}:{target_id}:{relation}"

    def _serialize_node(self, node: SemanticNode) -> bytes:
        data: dict[str, Any] = {
            "id": node.id,
            "name": node.name,
            "type": node.type,
            "description": node.description,
            "aliases": node.aliases,
            "embedding": node.embedding,
            "embedding_dim": node.embedding_dim,
            "mention_count": node.mention_count,
            "first_seen_at": node.first_seen_at.isoformat() if node.first_seen_at else None,
            "last_seen_at": node.last_seen_at.isoformat() if node.last_seen_at else None,
            "source": node.source,
            "created_at": node.created_at.isoformat() if node.created_at else None,
        }
        return json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")

    def _deserialize_node(self, data: bytes) -> SemanticNode | None:
        try:
            raw = json.loads(data.decode("utf-8"))
            return SemanticNode(
                id=raw.get("id", ""),
                name=raw.get("name", ""),
                type=raw.get("type", "concept"),
                description=raw.get("description", ""),
                aliases=raw.get("aliases", []),
                embedding=raw.get("embedding"),
                embedding_dim=raw.get("embedding_dim"),
                mention_count=raw.get("mention_count", 0),
                first_seen_at=(
                    datetime.fromisoformat(raw["first_seen_at"])
                    if raw.get("first_seen_at") else None
                ),
                last_seen_at=(
                    datetime.fromisoformat(raw["last_seen_at"])
                    if raw.get("last_seen_at") else None
                ),
                source=raw.get("source", "extracted_from_dialogue"),
                created_at=(
                    datetime.fromisoformat(raw["created_at"])
                    if raw.get("created_at") else None
                ),
            )
        except (json.JSONDecodeError, KeyError, TypeError):
            return None

    def _serialize_edge(self, edge: SemanticEdge) -> bytes:
        data: dict[str, Any] = {
            "id": edge.id,
            "source_node": edge.source_node,
            "target_node": edge.target_node,
            "relation": edge.relation,
            "confidence": edge.confidence,
            "source": edge.source,
            "created_at": edge.created_at.isoformat() if edge.created_at else None,
            "last_confirmed_at": (
                edge.last_confirmed_at.isoformat() if edge.last_confirmed_at else None
            ),
        }
        return json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")

    def _deserialize_edge(self, data: bytes) -> SemanticEdge | None:
        try:
            raw = json.loads(data.decode("utf-8"))
            return SemanticEdge(
                id=raw.get("id", ""),
                source_node=raw.get("source_node", ""),
                target_node=raw.get("target_node", ""),
                relation=raw.get("relation", ""),
                confidence=raw.get("confidence", 1.0),
                source=raw.get("source", "extracted"),
                created_at=(
                    datetime.fromisoformat(raw["created_at"])
                    if raw.get("created_at") else None
                ),
                last_confirmed_at=(
                    datetime.fromisoformat(raw["last_confirmed_at"])
                    if raw.get("last_confirmed_at") else None
                ),
            )
        except (json.JSONDecodeError, KeyError, TypeError):
            return None

    async def create_node(self, node: SemanticNode) -> str:
        """
        创建节点。如果 name 已存在则返回已有 ID（幂等）。

        Args:
            node: 语义节点。

        Returns:
            节点 ID。
        """
        existing = await self.find_node_by_name(node.name)
        if existing is not None:
            return existing.id
        data = self._serialize_node(node)
        await self._store.put(self._node_key(node.id), data)
        return node.id

    async def read_node(self, node_id: str) -> SemanticNode | None:
        """按 ID 读取节点。"""
        data = await self._store.get(self._node_key(node_id))
        if data is None:
            return None
        return self._deserialize_node(data)

    async def find_node_by_name(self, name: str) -> SemanticNode | None:
        """按名称精确查找。"""
        keys = await self._store.list_keys("sn:")
        for key in keys:
            data = await self._store.get(key)
            if data is not None:
                node = self._deserialize_node(data)
                if node and node.name == name:
                    return node
        return None

    async def search_nodes(
        self,
        query: str,
        *,
        top_k: int = 5,
        threshold: float = 0.6,
    ) -> list[SemanticNode]:
        """
        检索节点（基于名称和描述的简单文本匹配）。

        Args:
            query: 查询文本。
            top_k: 最大返回条数。
            threshold: 匹配阈值（当前未使用，保留接口兼容）。

        Returns:
            匹配的节点列表。
        """
        query_lower = query.lower()
        keys = await self._store.list_keys("sn:")
        matched: list[tuple[SemanticNode, float]] = []

        for key in keys:
            data = await self._store.get(key)
            if data is not None:
                node = self._deserialize_node(data)
                if node:
                    score = 0.0
                    if query_lower in node.name.lower():
                        score += 1.0
                    if query_lower in node.description.lower():
                        score += 0.5
                    for alias in node.aliases:
                        if query_lower in alias.lower():
                            score += 0.8
                    if score > 0:
                        matched.append((node, score))

        matched.sort(key=lambda x: x[1], reverse=True)
        return [node for node, _ in matched[:top_k]]

    async def update_embedding(self, node_id: str, embedding: list[float]) -> None:
        """更新节点向量。"""
        node = await self.read_node(node_id)
        if node is not None:
            node.embedding = embedding
            node.embedding_dim = len(embedding)
            data = self._serialize_node(node)
            await self._store.put(self._node_key(node.id), data)

    async def increment_mention(self, node_id: str) -> None:
        """增加提及计数。"""
        node = await self.read_node(node_id)
        if node is not None:
            node.mention_count += 1
            node.last_seen_at = datetime.utcnow()
            data = self._serialize_node(node)
            await self._store.put(self._node_key(node.id), data)

    async def create_edge(
        self,
        source_id: str,
        target_id: str,
        relation: str,
        *,
        confidence: float = 1.0,
    ) -> str:
        """
        创建边。相同 (source, target, relation) 视为重复，返回已有 ID。

        Args:
            source_id: 源节点 ID。
            target_id: 目标节点 ID。
            relation: 关系类型。
            confidence: 置信度。

        Returns:
            边 ID。
        """
        key = self._edge_key(source_id, target_id, relation)
        existing_data = await self._store.get(key)
        if existing_data is not None:
            existing = self._deserialize_edge(existing_data)
            if existing is not None:
                return existing.id

        edge = SemanticEdge(
            source_node=source_id,
            target_node=target_id,
            relation=relation,
            confidence=confidence,
            created_at=datetime.utcnow(),
        )
        data = self._serialize_edge(edge)
        await self._store.put(key, data)
        return edge.id

    async def get_neighbors(
        self,
        node_id: str,
        *,
        relation: str | None = None,
        max_depth: int = 1,
    ) -> list[tuple[SemanticNode, str]]:
        """
        获取邻居节点。

        Args:
            node_id: 节点 ID。
            relation: 筛选关系类型。
            max_depth: 遍历深度（>1 时递归查找）。

        Returns:
            [(node, relation), ...] 列表。
        """
        keys = await self._store.list_keys("se:")
        neighbors: list[tuple[SemanticNode, str]] = []
        visited: set[str] = {node_id}

        def _should_include(edge: SemanticEdge) -> bool:
            if relation and edge.relation != relation:
                return False
            return True

        async def _collect(target_id: str, depth: int) -> None:
            if depth > max_depth:
                return
            for key in keys:
                data = await self._store.get(key)
                if data is not None:
                    edge = self._deserialize_edge(data)
                    if edge and _should_include(edge):
                        neighbor_id = None
                        if edge.source_node == target_id:
                            neighbor_id = edge.target_node
                        elif edge.target_node == target_id:
                            neighbor_id = edge.source_node

                        if neighbor_id and neighbor_id not in visited:
                            visited.add(neighbor_id)
                            neighbor_node = await self.read_node(neighbor_id)
                            if neighbor_node:
                                neighbors.append((neighbor_node, edge.relation))
                                await _collect(neighbor_id, depth + 1)

        await _collect(node_id, 1)
        return neighbors

    async def find_path(
        self,
        source_id: str,
        target_id: str,
        *,
        max_depth: int = 5,
    ) -> list[list[tuple[str, str]]]:
        """
        查找两节点之间的路径（BFS）。

        Returns:
            多条路径，每条路径是 [(node_id, relation), ...]。
        """
        if source_id == target_id:
            return [[(source_id, "")]]

        keys = await self._store.list_keys("se:")
        edges: list[SemanticEdge] = []
        for key in keys:
            data = await self._store.get(key)
            if data is not None:
                edge = self._deserialize_edge(data)
                if edge:
                    edges.append(edge)

        # 构建邻接表
        adj: dict[str, list[tuple[str, str, str]]] = {}
        for e in edges:
            adj.setdefault(e.source_node, []).append((e.target_node, e.relation, e.id))
            adj.setdefault(e.target_node, []).append((e.source_node, e.relation, e.id))

        # BFS
        from collections import deque

        paths: list[list[tuple[str, str]]] = []
        queue: deque[tuple[str, list[tuple[str, str]], set[str]]] = deque()
        queue.append((source_id, [(source_id, "")], {source_id}))

        while queue and len(paths) < 3:
            current, path, visited = queue.popleft()
            if len(path) - 1 >= max_depth:
                continue

            for neighbor, rel, _ in adj.get(current, []):
                if neighbor == target_id:
                    new_path = path + [(neighbor, rel)]
                    paths.append(new_path)
                    continue
                if neighbor not in visited and len(path) < max_depth:
                    new_visited = visited | {neighbor}
                    queue.append((neighbor, path + [(neighbor, rel)], new_visited))

        return paths

    async def merge_knowledge(
        self,
        extractions: list[tuple[str, str, str]],
    ) -> None:
        """
        批量注入提取的知识。

        Args:
            extractions: [(source_name, relation, target_name), ...]。
                       自动创建不存在的节点。
        """
        for source_name, relation, target_name in extractions:
            source_node = await self.find_node_by_name(source_name)
            if source_node is None:
                source_node = SemanticNode(name=source_name)
                source_node.id = await self.create_node(source_node)

            target_node = await self.find_node_by_name(target_name)
            if target_node is None:
                target_node = SemanticNode(name=target_name)
                target_node.id = await self.create_node(target_node)

            await self.create_edge(
                source_node.id,
                target_node.id,
                relation,
                confidence=0.7,
            )

    async def get_low_mention_nodes(
        self,
        threshold: int = 3,
    ) -> list[SemanticNode]:
        """获取提及次数低于阈值的节点。"""
        keys = await self._store.list_keys("sn:")
        low_mention: list[SemanticNode] = []
        for key in keys:
            data = await self._store.get(key)
            if data is not None:
                node = self._deserialize_node(data)
                if node and node.mention_count < threshold:
                    low_mention.append(node)
        return low_mention

    async def delete_node(self, node_id: str) -> None:
        """删除节点及其相关边。"""
        # 删除相关边
        keys = await self._store.list_keys("se:")
        for key in keys:
            data = await self._store.get(key)
            if data is not None:
                edge = self._deserialize_edge(data)
                if edge and (edge.source_node == node_id or edge.target_node == node_id):
                    await self._store.delete(key)
        # 删除节点
        await self._store.delete(self._node_key(node_id))
