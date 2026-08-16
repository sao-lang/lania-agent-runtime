"""
SessionStore 单元测试。

覆盖：记录读写、用户索引、key 解析、损坏数据容错、摘要转换。
"""

from __future__ import annotations

from datetime import datetime

import pytest

from src.memory._backends._sqlite import SQLitePersistence
from src.session._models import SessionRecord
from src.session._store import SessionStore


@pytest.fixture
async def store() -> SessionStore:
    """创建基于 SQLite 内存后端的 SessionStore。"""
    persistence = SQLitePersistence(":memory:")
    s = SessionStore(persistence)
    yield s
    await persistence.close()


class TestSessionStore:
    """SessionStore 核心功能测试。"""

    async def test_save_and_load_record(self, store: SessionStore) -> None:
        record = SessionRecord(
            session_id="sess_1",
            agent_id="agent_1",
            user_id="u1",
            title="test",
        )
        record.messages = [{"role": "user", "content": "hi"}]
        await store.save_record(record)

        loaded = await store.load_record("sess_1")
        assert loaded is not None
        assert loaded.session_id == "sess_1"
        assert loaded.agent_id == "agent_1"
        assert loaded.user_id == "u1"
        assert loaded.messages == [{"role": "user", "content": "hi"}]

    async def test_load_missing_record(self, store: SessionStore) -> None:
        assert await store.load_record("missing") is None

    async def test_delete_record(self, store: SessionStore) -> None:
        await store.save_record(SessionRecord(session_id="sess_1"))
        await store.delete_record("sess_1")
        assert await store.load_record("sess_1") is None

    async def test_user_index_roundtrip(self, store: SessionStore) -> None:
        await store.save_user_index("u1", "sess_1")
        await store.save_user_index("u1", "sess_2")
        keys = await store.list_user_index_keys("u1")
        ids = sorted(SessionStore.parse_user_index_key(k) or "" for k in keys)
        assert ids == ["sess_1", "sess_2"]

        await store.delete_user_index("u1", "sess_1")
        remaining = await store.list_user_index_keys("u1")
        assert len(remaining) == 1

    async def test_parse_user_index_key_invalid(self, store: SessionStore) -> None:
        assert SessionStore.parse_user_index_key("wm:sess_1") is None
        assert SessionStore.parse_user_index_key("ssi") is None

    async def test_deserialize_corrupted_data(self, store: SessionStore) -> None:
        await store._store.put("ss:sess_x", b"not-json")
        assert await store.load_record("sess_x") is None

    async def test_deserialize_non_dict_data(self, store: SessionStore) -> None:
        await store._store.put("ss:sess_y", b"[1, 2, 3]")
        assert await store.load_record("sess_y") is None

    async def test_parse_datetime_invalid(self, store: SessionStore) -> None:
        await store._store.put("ss:sess_z", b'{"session_id": "sess_z", "created_at": "not-a-date"}')
        loaded = await store.load_record("sess_z")
        assert loaded is not None
        assert loaded.created_at is None

    async def test_datetime_roundtrip(self, store: SessionStore) -> None:
        record = SessionRecord(
            session_id="sess_1",
            created_at=datetime(2026, 1, 1, 10, 0, 0),
            updated_at=datetime(2026, 1, 2, 10, 0, 0),
        )
        await store.save_record(record)
        loaded = await store.load_record("sess_1")
        assert loaded is not None
        assert loaded.created_at == datetime(2026, 1, 1, 10, 0, 0)
        assert loaded.updated_at == datetime(2026, 1, 2, 10, 0, 0)

    async def test_to_summary_excludes_messages(self, store: SessionStore) -> None:
        record = SessionRecord(
            session_id="s1",
            title="t",
            status="ended",
            user_id="u",
            turn_count=3,
            created_at=datetime(2026, 1, 1),
            updated_at=datetime(2026, 1, 2),
        )
        summary = SessionStore.to_summary(record)
        assert summary.session_id == "s1"
        assert summary.title == "t"
        assert summary.status == "ended"
        assert summary.user_id == "u"
        assert summary.turn_count == 3
        assert not hasattr(summary, "messages")
