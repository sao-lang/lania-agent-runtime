"""
MemoryService 按层 storage 注入测试。

覆盖：按层后端路由、未指定层回退默认后端、默认共用单后端、
close() 对所有去重后端逐一关闭、共享实例只关一次。
"""

from __future__ import annotations

from src.memory._service import MemoryService
from src.memory._types import EpisodicMemoryEntry, WorkingMemorySnapshot


class DictPersistence:
    """测试用内存 KV 后端——实现 MemoryPersistence 4 方法。"""

    def __init__(self) -> None:
        self._data: dict[str, bytes] = {}
        self.close_calls = 0

    async def get(self, key: str) -> bytes | None:
        """读取键值。"""
        return self._data.get(key)

    async def put(self, key: str, value: bytes) -> None:
        """写入键值。"""
        self._data[key] = value

    async def delete(self, key: str) -> None:
        """删除键。"""
        self._data.pop(key, None)

    async def list_keys(self, prefix: str) -> list[str]:
        """按前缀列出键。"""
        return [k for k in self._data if k.startswith(prefix)]

    async def close(self) -> None:
        """记录关闭次数。"""
        self.close_calls += 1


class TestMemoryStorageInjection:
    """MemoryService 按层 storage 注入测试。"""

    async def test_default_creates_sqlite_backend(self, monkeypatch) -> None:
        """不传 persistence 时自动创建默认 SQLite 后端。"""
        created: dict[str, str] = {}

        def fake_factory(path: str) -> DictPersistence:
            created["path"] = path
            return DictPersistence()

        monkeypatch.setattr("src.memory._backends._sqlite.SQLitePersistence", fake_factory)
        memory = MemoryService()
        assert created["path"] == "./memory.db"
        await memory.close()

    async def test_per_layer_backend_routing(self) -> None:
        """写入只落到对应层自己的后端。"""
        default = DictPersistence()
        episodic = DictPersistence()
        memory = MemoryService(persistence=default, episodic_persistence=episodic)
        try:
            entry = EpisodicMemoryEntry(session_id="s1", turn_index=0, summary="x")
            await memory._episodic.write(entry)
            await memory._entity.upsert_attribute(
                "user",
                "u1",
                "name",
                "Alice",
                source_session="s1",
            )

            # 情景记忆 → episodic 后端，默认后端无 ep:
            assert await episodic.list_keys("ep:")
            assert not await default.list_keys("ep:")
            # 实体记忆 → 默认后端，episodic 后端无 en:
            assert await default.list_keys("en:")
            assert not await episodic.list_keys("en:")
        finally:
            await memory.close()

    async def test_fallback_to_default_backend(self) -> None:
        """未指定层的记忆回退到默认后端。"""
        default = DictPersistence()
        semantic = DictPersistence()
        memory = MemoryService(persistence=default, semantic_persistence=semantic)
        try:
            entry = EpisodicMemoryEntry(session_id="s1", turn_index=0, summary="x")
            await memory._episodic.write(entry)
            await memory._semantic.merge_knowledge([("Python", "is_a", "编程语言")])

            assert await default.list_keys("ep:")
            assert await semantic.list_keys("sn:")
            assert not await default.list_keys("sn:")
        finally:
            await memory.close()

    async def test_default_shared_backend(self) -> None:
        """不注入任何层后端时，全部层共用默认后端。"""
        backend = DictPersistence()
        memory = MemoryService(persistence=backend)
        try:
            snap = WorkingMemorySnapshot(session_id="s1")
            await memory.checkpoint(snap)
            entry = EpisodicMemoryEntry(session_id="s1", turn_index=0, summary="x")
            await memory._episodic.write(entry)

            assert await backend.list_keys("wm:")
            assert await backend.list_keys("ep:")
        finally:
            await memory.close()

    async def test_close_closes_each_distinct_backend(self) -> None:
        """close() 对每个去重后的后端各关闭一次。"""
        default = DictPersistence()
        episodic = DictPersistence()
        memory = MemoryService(persistence=default, episodic_persistence=episodic)
        await memory.close()
        assert default.close_calls == 1
        assert episodic.close_calls == 1

    async def test_close_dedupes_shared_backend(self) -> None:
        """同一实例被多层共享时只关闭一次。"""
        backend = DictPersistence()
        memory = MemoryService(
            persistence=backend,
            episodic_persistence=backend,
            pattern_persistence=backend,
        )
        assert len(memory._backends) == 1
        await memory.close()
        assert backend.close_calls == 1

    async def test_backends_list_contains_distinct(self) -> None:
        """_backends 只包含去重后的后端实例。"""
        default = DictPersistence()
        episodic = DictPersistence()
        memory = MemoryService(persistence=default, episodic_persistence=episodic)
        assert len(memory._backends) == 2
        await memory.close()
