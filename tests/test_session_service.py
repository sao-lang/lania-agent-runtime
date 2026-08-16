"""
SessionService 单元测试。

覆盖：生命周期（create/get/finalize/delete）、TTL 过期、消息增量提交、
历史裁剪、单条截断、用户会话列表。
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from src.memory._backends._sqlite import SQLitePersistence
from src.session._config import SessionConfig
from src.session._service import SessionService


@pytest.fixture
async def service() -> SessionService:
    """创建基于 SQLite 内存后端的 SessionService。"""
    persistence = SQLitePersistence(":memory:")
    svc = SessionService(persistence)
    yield svc
    await svc.close()


class TestSessionService:
    """SessionService 核心功能测试。"""

    async def test_create(self, service: SessionService) -> None:
        record = await service.create("sess_1", agent_id="a1", user_id="u1", title="hello")
        assert record.session_id == "sess_1"
        assert record.agent_id == "a1"
        assert record.user_id == "u1"
        assert record.status == "active"
        assert record.created_at is not None

    async def test_create_idempotent(self, service: SessionService) -> None:
        await service.create("sess_1", title="first")
        record = await service.create("sess_1", title="second")
        assert record.title == "first"

    async def test_get_uses_cache(self, service: SessionService) -> None:
        await service.create("sess_1")
        record = await service.get("sess_1")
        assert record is not None
        assert service._cache["sess_1"] is record

    async def test_get_missing(self, service: SessionService) -> None:
        assert await service.get("nope") is None

    async def test_ttl_expired(self) -> None:
        svc = SessionService(
            SQLitePersistence(":memory:"),
            config=SessionConfig(ttl_seconds=1),
        )
        try:
            await svc.create("sess_1")
            record = await svc.get("sess_1")
            assert record is not None
            record.updated_at = datetime.now() - timedelta(seconds=10)
            assert await svc.get("sess_1") is None
        finally:
            await svc.close()

    async def test_ttl_expired_on_store_load(self) -> None:
        """未命中缓存时，存储中的过期记录被删除并返回 None。"""
        backend = SQLitePersistence(":memory:")
        svc1 = SessionService(backend, config=SessionConfig(ttl_seconds=1))
        # 注意：不能 close()——:memory: 库在连接关闭后清空，需两个服务共享同一连接
        await svc1.create("sess_1")
        record = await svc1.get("sess_1")
        assert record is not None
        record.updated_at = datetime.now() - timedelta(seconds=10)
        await svc1._store.save_record(record)

        svc2 = SessionService(backend, config=SessionConfig(ttl_seconds=1))
        try:
            assert await svc2.get("sess_1") is None
            assert await backend.get("ss:sess_1") is None  # 已删除
        finally:
            await svc2.close()
            await svc1.close()

    async def test_list_user_sessions_skips_invalid_index(self, service: SessionService) -> None:
        await service.create("s1", user_id="u1")
        await service._store._store.put("ssi:u1", b"1")  # 非法索引键
        summaries = await service.list_user_sessions("u1")
        assert [s.session_id for s in summaries] == ["s1"]

    async def test_append_messages_rebuilds_when_count_ahead(self, service: SessionService) -> None:
        """message_count 落后于传入消息时整体重建。"""
        await service.create("sess_1")
        await service.append_messages(
            "sess_1",
            [{"role": "user", "content": "old"}],
        )
        record = await service.get("sess_1")
        assert record is not None
        record.message_count = 5  # 模拟外部裁剪导致计数超前
        await service._store.save_record(record)

        updated = await service.append_messages(
            "sess_1",
            [{"role": "user", "content": "new"}],
        )
        assert updated is not None
        assert [m["content"] for m in updated.messages] == ["new"]

    async def test_append_messages_no_truncation_when_disabled(self) -> None:
        svc = SessionService(
            SQLitePersistence(":memory:"),
            config=SessionConfig(max_message_chars=0),
        )
        try:
            await svc.create("sess_1")
            record = await svc.append_messages(
                "sess_1",
                [{"role": "user", "content": "a" * 100}],
            )
            assert record is not None
            assert record.messages[0]["content"] == "a" * 100
        finally:
            await svc.close()

    async def test_append_messages_non_string_content(self, service: SessionService) -> None:
        await service.create("sess_1")
        record = await service.append_messages(
            "sess_1",
            [{"role": "user", "content": 12345}],
        )
        assert record is not None
        assert record.messages[0]["content"] == 12345

    async def test_delete_when_not_cached(self) -> None:
        backend = SQLitePersistence(":memory:")
        svc1 = SessionService(backend)
        await svc1.create("sess_1", user_id="u1")

        svc2 = SessionService(backend)
        try:
            await svc2.delete("sess_1")
            assert await svc2.get("sess_1") is None
        finally:
            await svc2.close()
            await svc1.close()

    async def test_list_user_sessions(self, service: SessionService) -> None:
        await service.create("s1", user_id="u1", title="a")
        await service.create("s2", user_id="u1", title="b")
        await service.create("s3", user_id="u2", title="c")
        summaries = await service.list_user_sessions("u1")
        assert {s.session_id for s in summaries} == {"s1", "s2"}

    async def test_list_user_sessions_status_filter(self, service: SessionService) -> None:
        await service.create("s1", user_id="u1")
        await service.finalize("s1", status="ended")
        await service.create("s2", user_id="u1")
        summaries = await service.list_user_sessions("u1", status="active")
        assert [s.session_id for s in summaries] == ["s2"]

    async def test_list_user_sessions_limit_and_order(self, service: SessionService) -> None:
        for i in range(5):
            await service.create(f"s{i}", user_id="u1")
            record = service._cache[f"s{i}"]
            record.updated_at = datetime(2026, 1, 1) + timedelta(hours=i)
            await service._store.save_record(record)
        summaries = await service.list_user_sessions("u1", limit=2)
        assert [s.session_id for s in summaries] == ["s4", "s3"]

    async def test_append_messages_idempotent(self, service: SessionService) -> None:
        await service.create("sess_1")
        messages = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "yo"},
        ]
        first = await service.append_messages("sess_1", messages)
        second = await service.append_messages("sess_1", messages)
        assert first is not None and second is not None
        assert first.message_count == 2
        assert second.message_count == 2
        assert len(second.messages) == 2

    async def test_append_messages_filters_system(self, service: SessionService) -> None:
        """system prompt 属运行时配置，不入会话历史。"""
        await service.create("sess_1")
        record = await service.append_messages(
            "sess_1",
            [
                {"role": "system", "content": "你是助手"},
                {"role": "user", "content": "hi"},
            ],
        )
        assert record is not None
        assert [m["role"] for m in record.messages] == ["user"]

    async def test_append_messages_self_heals_legacy_system(self, service: SessionService) -> None:
        """旧格式记录（v2 前首条为 system）在提交时自动剥离自愈。"""
        await service.create("sess_1")
        record = await service.get("sess_1")
        assert record is not None
        record.messages = [
            {"role": "system", "content": "旧提示词"},
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "a1"},
        ]
        record.message_count = 3
        await service._store.save_record(record)
        service._cache.clear()  # 强制从存储读取，模拟旧记录

        updated = await service.append_messages(
            "sess_1",
            [
                {"role": "system", "content": "旧提示词"},
                {"role": "user", "content": "u1"},
                {"role": "assistant", "content": "a1"},
                {"role": "user", "content": "u2"},
            ],
        )
        assert updated is not None
        assert [m["content"] for m in updated.messages] == ["u1", "a1", "u2"]
        assert updated.message_count == 3

    async def test_append_messages_incremental(self, service: SessionService) -> None:
        await service.create("sess_1")
        await service.append_messages(
            "sess_1",
            [{"role": "user", "content": "hi"}],
            step_index=1,
        )
        record = await service.append_messages(
            "sess_1",
            [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "yo"},
            ],
            step_index=2,
        )
        assert record is not None
        assert record.message_count == 2
        assert record.turn_count == 1
        assert record.step_index == 2

    async def test_append_messages_cap_history(self) -> None:
        svc = SessionService(
            SQLitePersistence(":memory:"),
            config=SessionConfig(max_history_messages=3),
        )
        try:
            await svc.create("sess_1")
            messages = [{"role": "user", "content": f"m{i}"} for i in range(5)]
            record = await svc.append_messages("sess_1", messages)
            assert record is not None
            assert len(record.messages) == 3
            assert record.message_count == 3
            assert record.messages[-1]["content"] == "m4"
        finally:
            await svc.close()

    async def test_append_messages_truncate_content(self) -> None:
        svc = SessionService(
            SQLitePersistence(":memory:"),
            config=SessionConfig(max_message_chars=5),
        )
        try:
            await svc.create("sess_1")
            record = await svc.append_messages(
                "sess_1",
                [{"role": "user", "content": "abcdefgh"}],
            )
            assert record is not None
            assert record.messages[0]["content"] == "abcde"
        finally:
            await svc.close()

    async def test_append_messages_missing_session(self, service: SessionService) -> None:
        assert await service.append_messages("nope", [{"role": "user", "content": "x"}]) is None

    async def test_update_status(self, service: SessionService) -> None:
        await service.create("sess_1")
        record = await service.update_status("sess_1", "error", last_error="boom")
        assert record is not None
        assert record.status == "error"
        assert record.last_error == "boom"

    async def test_update_status_missing(self, service: SessionService) -> None:
        assert await service.update_status("nope", "error") is None

    async def test_finalize(self, service: SessionService) -> None:
        await service.create("sess_1")
        record = await service.finalize(
            "sess_1",
            status="ended",
            token_used=42,
            step_count=3,
        )
        assert record is not None
        assert record.status == "ended"
        assert record.token_used == 42
        assert record.step_count == 3
        assert record.ended_at is not None

    async def test_finalize_missing(self, service: SessionService) -> None:
        assert await service.finalize("nope") is None

    async def test_delete_removes_index(self, service: SessionService) -> None:
        await service.create("sess_1", user_id="u1")
        await service.delete("sess_1")
        assert await service.get("sess_1") is None
        assert await service.list_user_sessions("u1") == []

    async def test_close(self, service: SessionService) -> None:
        await service.close()
        assert service._cache == {}
