"""
MemoryPersistence 单元测试。

覆盖 SQLitePersistence 的全部 4 个方法（get/put/delete/list_keys）
以及 TTL 过期、覆盖写、异常路径等场景。
"""

from __future__ import annotations

import json
import os
import tempfile
import time

import pytest

from src.memory._backends._sqlite import SQLitePersistence
from src.memory._persistence import MemoryPersistence


@pytest.fixture
def db_path() -> str:
    """创建临时数据库文件路径。"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    yield path
    if os.path.exists(path):
        os.unlink(path)


@pytest.fixture
async def store(db_path: str) -> SQLitePersistence:
    """创建 SQLitePersistence 实例。"""
    store = SQLitePersistence(db_path)
    yield store
    await store.close()


@pytest.fixture
async def store_with_ttl(db_path: str) -> SQLitePersistence:
    """创建带 TTL 的 SQLitePersistence 实例。"""
    store = SQLitePersistence(db_path, default_ttl_seconds=1)
    yield store
    await store.close()


class TestSQLitePersistence:
    """SQLitePersistence 单元测试。"""

    async def test_get_put(self, store: SQLitePersistence) -> None:
        """测试基本的 put 和 get 操作。"""
        await store.put("key1", b"value1")
        result = await store.get("key1")
        assert result == b"value1"

    async def test_get_non_existent(self, store: SQLitePersistence) -> None:
        """测试获取不存在的键返回 None。"""
        result = await store.get("non_existent")
        assert result is None

    async def test_overwrite(self, store: SQLitePersistence) -> None:
        """测试覆盖写。"""
        await store.put("key1", b"value1")
        await store.put("key1", b"value2")
        result = await store.get("key1")
        assert result == b"value2"

    async def test_delete(self, store: SQLitePersistence) -> None:
        """测试删除键。"""
        await store.put("key1", b"value1")
        await store.delete("key1")
        result = await store.get("key1")
        assert result is None

    async def test_delete_non_existent(self, store: SQLitePersistence) -> None:
        """测试删除不存在的键不抛出异常。"""
        # 应该静默成功
        await store.delete("non_existent")

    async def test_list_keys(self, store: SQLitePersistence) -> None:
        """测试按前缀列出键。"""
        await store.put("ep:sess1:0:a", b"data1")
        await store.put("ep:sess1:1:b", b"data2")
        await store.put("ep:sess2:0:c", b"data3")
        await store.put("wm:sess1", b"data4")

        # 匹配 ep:sess1: 前缀
        keys = await store.list_keys("ep:sess1:")
        assert sorted(keys) == ["ep:sess1:0:a", "ep:sess1:1:b"]

        # 匹配 ep: 前缀
        keys = await store.list_keys("ep:")
        assert sorted(keys) == ["ep:sess1:0:a", "ep:sess1:1:b", "ep:sess2:0:c"]

        # 匹配 wm: 前缀
        keys = await store.list_keys("wm:")
        assert keys == ["wm:sess1"]

    async def test_list_keys_empty_prefix(self, store: SQLitePersistence) -> None:
        """测试空前缀返回所有键。"""
        await store.put("a", b"1")
        await store.put("b", b"2")
        keys = await store.list_keys("")
        assert sorted(keys) == ["a", "b"]

    async def test_list_keys_no_match(self, store: SQLitePersistence) -> None:
        """测试无匹配前缀返回空列表。"""
        keys = await store.list_keys("nonexistent:")
        assert keys == []

    async def test_list_keys_empty_store(self, store: SQLitePersistence) -> None:
        """测试空存储返回空列表。"""
        keys = await store.list_keys("")
        assert keys == []

    async def test_binary_data(self, store: SQLitePersistence) -> None:
        """测试二进制数据（非 UTF-8）。"""
        binary = bytes(range(256))
        await store.put("binary", binary)
        result = await store.get("binary")
        assert result == binary

    async def test_large_data(self, store: SQLitePersistence) -> None:
        """测试大数据写入。"""
        large = b"x" * 100_000
        await store.put("large", large)
        result = await store.get("large")
        assert result == large
        assert len(result) == 100_000

    async def test_json_roundtrip(self, store: SQLitePersistence) -> None:
        """测试 JSON 序列化数据的读写（模拟 MemoryService 使用模式）。"""
        data = {"user_id": "u1", "turn_index": 5, "summary": "用户询问订单状态"}
        json_bytes = json.dumps(data, ensure_ascii=False).encode("utf-8")
        await store.put("ep:sess1:0:abc", json_bytes)

        raw = await store.get("ep:sess1:0:abc")
        assert raw is not None
        decoded = json.loads(raw.decode("utf-8"))
        assert decoded["user_id"] == "u1"
        assert decoded["turn_index"] == 5
        assert decoded["summary"] == "用户询问订单状态"

    async def test_multiple_keys_ordering(self, store: SQLitePersistence) -> None:
        """测试 list_keys 按 key 排序。"""
        for i in range(10):
            await store.put(f"ep:sess1:{i}:entry", f"data{i}".encode())
        keys = await store.list_keys("ep:sess1:")
        assert len(keys) == 10
        # 验证排序
        for i, key in enumerate(keys):
            assert key == f"ep:sess1:{i}:entry"

    async def test_close_and_reopen(self, db_path: str) -> None:
        """测试关闭后重新打开仍能读取数据。"""
        store = SQLitePersistence(db_path)
        try:
            await store.put("persist", b"data")
        finally:
            await store.close()

        store2 = SQLitePersistence(db_path)
        try:
            result = await store2.get("persist")
            assert result == b"data"
        finally:
            await store2.close()


class TestSQLitePersistenceWithTTL:
    """SQLitePersistence TTL 过期测试。"""

    async def test_ttl_not_expired(self, store_with_ttl: SQLitePersistence) -> None:
        """测试 TTL 未过期时数据可读取。"""
        await store_with_ttl.put("temp", b"data")
        result = await store_with_ttl.get("temp")
        assert result == b"data"

    async def test_ttl_expired(self, store_with_ttl: SQLitePersistence) -> None:
        """测试 TTL 过期后数据不可读取。"""
        await store_with_ttl.put("temp", b"data")
        # 等待 TTL 过期
        time.sleep(1.1)
        result = await store_with_ttl.get("temp")
        assert result is None

    async def test_ttl_list_keys_excludes_expired(
        self, store_with_ttl: SQLitePersistence
    ) -> None:
        """测试 list_keys 排除已过期的键。"""
        await store_with_ttl.put("ep:sess1:0:a", b"data1")
        await store_with_ttl.put("ep:sess1:1:b", b"data2")
        # 等待 TTL 过期
        time.sleep(1.1)
        keys = await store_with_ttl.list_keys("ep:")
        assert keys == []

    async def test_ttl_mixed_expiry(
        self, db_path: str
    ) -> None:
        """测试混合 TTL：无 TTL 的键保持，有 TTL 的键过期。"""
        store_no_ttl = SQLitePersistence(db_path)
        store_with_ttl = SQLitePersistence(db_path, default_ttl_seconds=1)

        try:
            await store_no_ttl.put("permanent", b"forever")
            await store_with_ttl.put("ep:sess1:0:a", b"temporary")

            time.sleep(1.1)

            # 无 TTL 的键仍然存在
            result = await store_no_ttl.get("permanent")
            assert result == b"forever"

            # 有 TTL 的键已过期
            result = await store_no_ttl.get("ep:sess1:0:a")
            assert result is None
        finally:
            await store_no_ttl.close()
            await store_with_ttl.close()


class TestMemoryPersistenceABC:
    """MemoryPersistence 抽象基类测试。"""

    def test_cannot_instantiate_abc(self) -> None:
        """测试抽象基类不能直接实例化。"""
        with pytest.raises(TypeError):
            MemoryPersistence()  # type: ignore[abstract]

    def test_sqlite_is_concrete(self) -> None:
        """测试 SQLitePersistence 可以实例化。"""
        store = SQLitePersistence(":memory:")
        assert isinstance(store, MemoryPersistence)
