"""文件系统存储后端: 将 StorageBackend 原语映射为纯文本文件操作.

目录结构 (人类可读, 可 git 管理):

    <root>/
    ├── kv/                  # KV 存储
    │   └── <key>.json       # {"value":"...", "expires_at":"..."}
    ├── list/                # 列表存储 (JSONL 追加写)
    │   └── <key>.jsonl      # 每行一条 JSON 记录
    ├── set/                 # 集合索引
    │   └── <key>.json       # ["member1", "member2", ...]
    ├── graph/
    │   ├── nodes/
    │   │   └── <id>.json    # 节点数据
    │   └── edges.jsonl      # 全部边, 每行一条 JSON
    └── lock/
        └── <id>.lock        # 锁标记文件 (含过期时间)

用法:
    store = GenericMemoryStore(FileSystemBackend("./memory-store"))
    await store.initialize()
"""

from __future__ import annotations

import base64
import json
import os
import threading
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any

from lania_agent_runtime.memory.backends.base import StorageBackend


def _encode_key(key: str) -> str:
    """将任意 key 编码为安全的文件名.

    使用 URL-safe base64 确保:
    - 无特殊字符 (冒号/斜杠/空格等)
    - 无长度问题 (base64 仅 A-Za-z0-9-_)
    - 无碰撞 (编码是双射)
    """
    return base64.urlsafe_b64encode(key.encode("utf-8")).decode("ascii").rstrip("=")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _parse_time(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _is_expired(expires_at: str | None) -> bool:
    if not expires_at:
        return False
    exp = _parse_time(expires_at)
    return exp is not None and exp <= datetime.now(timezone.utc)


class _FileLock:
    """文件锁: 基于临时文件 + O_CREAT|O_EXCL 实现跨进程互斥."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._held = False

    def try_lock(self, ttl: int = 30) -> bool:
        """尝试获取锁."""
        try:
            fd = os.open(self._path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w") as f:
                expires = (
                    datetime.now(timezone.utc).timestamp() + ttl
                )
                f.write(f"{expires}\n")
            self._held = True
            return True
        except FileExistsError:
            # 检查是否过期
            try:
                with open(self._path, "r") as f:
                    expires_str = f.readline().strip()
                    if expires_str:
                        exp = float(expires_str)
                        if datetime.now(timezone.utc).timestamp() > exp:
                            # 过期, 尝试删除并重新创建
                            os.unlink(self._path)
                            return self.try_lock(ttl)
            except (OSError, ValueError):
                pass
            return False
        except OSError:
            return False

    def unlock(self) -> None:
        if self._held:
            try:
                os.unlink(self._path)
            except OSError:
                pass
            self._held = False


class FileSystemBackend(StorageBackend):
    """文件系统存储后端.

    将所有数据存储为纯文本文件, 目录结构清晰, 人类可读, 可 git 管理.

    Args:
        root: 存储根目录. 默认为 "./memory_store".
    """

    def __init__(self, root: str = "./memory_store") -> None:
        self._root = os.path.abspath(root)
        self._lock = threading.Lock()

    # ── 属性 ──

    @property
    def root(self) -> str:
        return self._root

    # ── 生命周期 ──

    async def initialize(self) -> None:
        os.makedirs(os.path.join(self._root, "kv"), exist_ok=True)
        os.makedirs(os.path.join(self._root, "list"), exist_ok=True)
        os.makedirs(os.path.join(self._root, "set"), exist_ok=True)
        os.makedirs(os.path.join(self._root, "graph", "nodes"), exist_ok=True)
        os.makedirs(os.path.join(self._root, "lock"), exist_ok=True)
        # 确保 edges.jsonl 存在
        edges_path = os.path.join(self._root, "graph", "edges.jsonl")
        if not os.path.exists(edges_path):
            with open(edges_path, "w", encoding="utf-8"):
                pass

    async def close(self) -> None:
        pass  # 无需显式释放资源

    # ── 内部工具 ──

    def _kv_path(self, key: str) -> str:
        return os.path.join(self._root, "kv", f"{_encode_key(key)}.json")

    def _list_path(self, key: str) -> str:
        return os.path.join(self._root, "list", f"{_encode_key(key)}.jsonl")

    def _set_path(self, key: str) -> str:
        return os.path.join(self._root, "set", f"{_encode_key(key)}.json")

    def _node_path(self, node_id: str) -> str:
        return os.path.join(self._root, "graph", "nodes", f"{_encode_key(node_id)}.json")

    def _edges_path(self) -> str:
        return os.path.join(self._root, "graph", "edges.jsonl")

    def _lock_path(self, lock_id: str) -> str:
        return os.path.join(self._root, "lock", f"{_encode_key(lock_id)}.lock")

    def _read_json(self, path: str) -> Any | None:
        """读取 JSON 文件, 不存在返回 None."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def _write_json(self, path: str, data: Any) -> None:
        """原子写入 JSON 文件 (先写临时文件再重命名)."""
        tmp = path + ".tmp." + uuid.uuid4().hex[:8]
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, default=str)
        os.replace(tmp, path)

    def _read_jsonl(self, path: str) -> list[dict[str, Any]]:
        """读取 JSONL 文件全部行."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                return [
                    json.loads(line)
                    for line in f
                    if line.strip()
                ]
        except FileNotFoundError:
            return []

    def _append_jsonl(self, path: str, data: dict[str, Any]) -> None:
        """追加一行到 JSONL 文件."""
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False, default=str) + "\n")

    # ════════════════════════════════════════════════════════════
    # KV 操作
    # ════════════════════════════════════════════════════════════

    async def kv_set(self, key: str, value: str, ttl: int | None = None) -> None:
        expires_at = None
        if ttl is not None:
            expires_at = (
                datetime.now(timezone.utc).timestamp() + ttl
            )
            expires_at = datetime.fromtimestamp(
                expires_at, tz=timezone.utc
            ).isoformat()
        self._write_json(self._kv_path(key), {
            "value": value,
            "expires_at": expires_at,
        })

    async def kv_get(self, key: str) -> str | None:
        data = self._read_json(self._kv_path(key))
        if data is None:
            return None
        if _is_expired(data.get("expires_at")):
            await self.kv_delete(key)
            return None
        return data.get("value")

    async def kv_delete(self, key: str) -> None:
        try:
            os.unlink(self._kv_path(key))
        except FileNotFoundError:
            pass

    async def kv_exists(self, key: str) -> bool:
        data = self._read_json(self._kv_path(key))
        if data is None:
            return False
        if _is_expired(data.get("expires_at")):
            await self.kv_delete(key)
            return False
        return True

    # ════════════════════════════════════════════════════════════
    # 列表操作
    # ════════════════════════════════════════════════════════════

    async def list_push(self, key: str, value: str) -> None:
        self._append_jsonl(self._list_path(key), {
            "value": value,
            "timestamp": _now(),
        })

    async def list_range(
        self, key: str, start: int, stop: int
    ) -> list[str]:
        items = self._read_jsonl(self._list_path(key))
        if stop == -1:
            return [item["value"] for item in items[start:]]
        return [item["value"] for item in items[start:stop + 1]]

    async def list_len(self, key: str) -> int:
        try:
            return sum(1 for _ in open(self._list_path(key), "r", encoding="utf-8") if _.strip())
        except FileNotFoundError:
            return 0

    async def list_remove(self, key: str, value: str, count: int = 0) -> None:
        path = self._list_path(key)
        with self._lock:
            items = self._read_jsonl(path)
            removed = 0
            kept = []
            for item in items:
                if item["value"] == value and (count == 0 or removed < count):
                    removed += 1
                else:
                    kept.append(item)
            # 重写文件
            tmp = path + ".tmp." + uuid.uuid4().hex[:8]
            with open(tmp, "w", encoding="utf-8") as f:
                for item in kept:
                    f.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")
            os.replace(tmp, path)

    # ════════════════════════════════════════════════════════════
    # 集合操作
    # ════════════════════════════════════════════════════════════

    async def set_add(self, key: str, *values: str) -> None:
        path = self._set_path(key)
        with self._lock:
            members = set(self._read_json(path) or [])
            members.update(values)
            self._write_json(path, sorted(members))

    async def set_members(self, key: str) -> set[str]:
        members = self._read_json(self._set_path(key))
        return set(members) if members else set()

    async def set_intersect(self, keys: list[str]) -> set[str]:
        if not keys:
            return set()
        result = await self.set_members(keys[0])
        for k in keys[1:]:
            result &= await self.set_members(k)
        return result

    # ════════════════════════════════════════════════════════════
    # 图: 节点操作
    # ════════════════════════════════════════════════════════════

    async def graph_node_create(
        self,
        node_id: str,
        name: str,
        type: str = "concept",
        description: str = "",
    ) -> bool:
        # 先检查 name 是否已存在
        existing = await self.graph_node_find_by_name(name)
        if existing is not None:
            return False

        now = _now()
        node = {
            "id": node_id,
            "name": name,
            "type": type,
            "description": description,
            "mention_count": 0,
            "first_seen_at": now,
            "last_seen_at": now,
            "created_at": now,
        }
        path = self._node_path(node_id)
        if os.path.exists(path):
            return False  # 已存在
        self._write_json(path, node)
        return True

    async def graph_node_get(self, node_id: str) -> dict[str, Any] | None:
        return self._read_json(self._node_path(node_id))

    async def graph_node_find_by_name(self, name: str) -> dict[str, Any] | None:
        nodes_dir = os.path.join(self._root, "graph", "nodes")
        try:
            for fname in os.listdir(nodes_dir):
                if not fname.endswith(".json"):
                    continue
                node = self._read_json(os.path.join(nodes_dir, fname))
                if node and node.get("name") == name:
                    return node
        except FileNotFoundError:
            pass
        return None

    async def graph_node_search(
        self,
        query: str,
        type_filter: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        query_lower = query.lower()
        result: list[dict[str, Any]] = []
        nodes_dir = os.path.join(self._root, "graph", "nodes")
        try:
            for fname in os.listdir(nodes_dir):
                if not fname.endswith(".json"):
                    continue
                node = self._read_json(os.path.join(nodes_dir, fname))
                if node is None:
                    continue
                if type_filter and node.get("type") != type_filter:
                    continue
                name = (node.get("name") or "").lower()
                desc = (node.get("description") or "").lower()
                if query_lower in name or query_lower in desc:
                    result.append(node)
                    if len(result) >= limit:
                        break
        except FileNotFoundError:
            pass
        return result

    async def graph_node_increment_mention(self, node_id: str) -> None:
        path = self._node_path(node_id)
        with self._lock:
            node = self._read_json(path)
            if node is None:
                return
            node["mention_count"] = node.get("mention_count", 0) + 1
            node["last_seen_at"] = _now()
            self._write_json(path, node)

    async def graph_node_get_low_mention(
        self, threshold: int = 3, limit: int = 50
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        nodes_dir = os.path.join(self._root, "graph", "nodes")
        try:
            nodes: list[dict[str, Any]] = []
            for fname in os.listdir(nodes_dir):
                if not fname.endswith(".json"):
                    continue
                node = self._read_json(os.path.join(nodes_dir, fname))
                if node and node.get("mention_count", 0) < threshold:
                    nodes.append(node)
            # 按 last_seen_at 升序排序 (最久未见的在前)
            nodes.sort(key=lambda n: n.get("last_seen_at", ""))
            result = nodes[:limit]
        except FileNotFoundError:
            pass
        return result

    async def graph_node_delete(self, node_id: str) -> None:
        # 删除节点文件
        try:
            os.unlink(self._node_path(node_id))
        except FileNotFoundError:
            pass

        # 删除相关边
        edges_path = self._edges_path()
        with self._lock:
            edges = self._read_jsonl(edges_path)
            kept = [
                e for e in edges
                if e.get("source_node") != node_id and e.get("target_node") != node_id
            ]
            if len(kept) < len(edges):
                tmp = edges_path + ".tmp." + uuid.uuid4().hex[:8]
                with open(tmp, "w", encoding="utf-8") as f:
                    for e in kept:
                        f.write(json.dumps(e, ensure_ascii=False, default=str) + "\n")
                os.replace(tmp, edges_path)

    # ════════════════════════════════════════════════════════════
    # 图: 边操作
    # ════════════════════════════════════════════════════════════

    async def graph_edge_create(
        self,
        source_node: str,
        target_node: str,
        relation: str,
        confidence: float = 1.0,
    ) -> bool:
        edges_path = self._edges_path()
        with self._lock:
            # 检查是否重复
            edges = self._read_jsonl(edges_path)
            for e in edges:
                if (e.get("source_node") == source_node
                        and e.get("target_node") == target_node
                        and e.get("relation") == relation):
                    return False

            edge = {
                "id": uuid.uuid4().hex,
                "source_node": source_node,
                "target_node": target_node,
                "relation": relation,
                "confidence": confidence,
                "created_at": _now(),
            }
            self._append_jsonl(edges_path, edge)
            return True

    async def graph_edge_list(
        self,
        node_id: str,
        direction: str = "both",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        edges = self._read_jsonl(self._edges_path())
        result: list[dict[str, Any]] = []
        for e in edges:
            if direction == "out" and e.get("source_node") == node_id:
                result.append(e)
            elif direction == "in" and e.get("target_node") == node_id:
                result.append(e)
            elif direction == "both" and (
                e.get("source_node") == node_id or e.get("target_node") == node_id
            ):
                result.append(e)
            if len(result) >= limit:
                break
        return result

    async def graph_neighbors(
        self,
        node_id: str,
        relation: str | None = None,
        max_depth: int = 1,
        limit: int = 20,
    ) -> list[tuple[dict[str, Any], str]]:
        edges = self._read_jsonl(self._edges_path())

        # 构建邻接表
        adj: dict[str, list[tuple[str, str]]] = {}
        for e in edges:
            src = e.get("source_node", "")
            tgt = e.get("target_node", "")
            rel = e.get("relation", "")
            if relation and rel != relation:
                continue
            adj.setdefault(src, []).append((tgt, rel))
            adj.setdefault(tgt, []).append((src, rel))

        if max_depth == 1:
            # 直接邻居
            neighbor_ids: set[str] = set()
            neighbors: list[tuple[dict[str, Any], str]] = []
            for nid, rel in adj.get(node_id, []):
                if nid not in neighbor_ids:
                    neighbor_ids.add(nid)
                    n = await self.graph_node_get(nid)
                    if n:
                        neighbors.append((n, rel))
                    if len(neighbors) >= limit:
                        break
            return neighbors

        # BFS 多跳查询
        visited: set[str] = {node_id}
        q: deque[tuple[str, str, int]] = deque(
            (nid, rel, 1) for nid, rel in adj.get(node_id, [])
        )
        result: list[tuple[dict[str, Any], str]] = []
        while q and len(result) < limit:
            cur_id, cur_rel, depth = q.popleft()
            if cur_id in visited:
                continue
            visited.add(cur_id)
            n = await self.graph_node_get(cur_id)
            if n:
                result.append((n, cur_rel))
            if depth < max_depth:
                for nid, rel in adj.get(cur_id, []):
                    if nid not in visited:
                        q.append((nid, rel, depth + 1))
        return result[:limit]

    async def graph_find_path(
        self,
        source_id: str,
        target_id: str,
        max_depth: int = 5,
    ) -> list[list[tuple[str, str]]]:
        edges = self._read_jsonl(self._edges_path())

        # 构建邻接表
        adj: dict[str, list[tuple[str, str]]] = {}
        for e in edges:
            src = e.get("source_node", "")
            tgt = e.get("target_node", "")
            rel = e.get("relation", "")
            adj.setdefault(src, []).append((tgt, rel))
            adj.setdefault(tgt, []).append((src, rel))

        # DFS 找路径
        results: list[list[tuple[str, str]]] = []
        visited: set[str] = {source_id}

        def dfs(current: str, path: list[tuple[str, str]]) -> None:
            if len(results) >= 10:
                return
            if current == target_id and path:
                results.append(list(path))
                return
            if len(path) >= max_depth:
                return
            for nid, rel in adj.get(current, []):
                if nid not in visited:
                    visited.add(nid)
                    path.append((nid, rel))
                    dfs(nid, path)
                    path.pop()
                    visited.discard(nid)

        dfs(source_id, [])
        # 按路径长度排序
        results.sort(key=len)
        return results

    # ════════════════════════════════════════════════════════════
    # 锁操作
    # ════════════════════════════════════════════════════════════

    async def acquire_lock(self, lock_id: str, ttl: int = 30) -> bool:
        lock = _FileLock(self._lock_path(lock_id))
        return lock.try_lock(ttl=ttl)
