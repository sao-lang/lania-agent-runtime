"""
Session Phase 2 测试。

覆盖：SessionResumeHook / MemoryResumeHook（断点恢复）、
历史消息分块（ssh: 前缀）与裁剪、list_user_sessions 分页/状态过滤、
Builder 并列注册 Resume Hooks。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.memory._backends._sqlite import SQLitePersistence
from src.memory._hooks import MemoryResumeHook
from src.memory._service import MemoryService
from src.memory._types import BudgetSnapshot, PauseState, WorkingMemorySnapshot
from src.runtime._builder import RuntimeBuilder
from src.runtime._types import HookPoint
from src.session._config import SessionConfig
from src.session._hooks import SessionResumeHook
from src.session._service import SessionService


@pytest.fixture
async def service() -> SessionService:
    """创建基于 SQLite 内存后端的 SessionService。"""
    persistence = SQLitePersistence(":memory:")
    svc = SessionService(persistence)
    yield svc
    await svc.close()


def make_ctx(
    session_id: str = "sess_1",
    messages: tuple = (),
    step_index: int = 0,
    services: dict | None = None,
) -> MagicMock:
    """构造 mock RuntimeContext。"""
    ctx = MagicMock()
    ctx.session_id = session_id
    ctx.agent_id = "agent_1"
    ctx.messages = tuple(messages)
    ctx.step_index = step_index
    ctx.services = services or {}
    ctx.budget.token_used = 10
    ctx.set_messages = MagicMock()
    ctx.set_step_index = MagicMock()
    ctx.set_plan = MagicMock()
    ctx.set_budget = MagicMock()
    ctx.set_pause_state = MagicMock()
    return ctx


def build_messages(n: int) -> list[dict]:
    """构造 n 条 user 消息。"""
    return [{"role": "user", "content": f"msg-{i}"} for i in range(n)]


class TestSessionResumeHook:
    """SessionResumeHook 测试。"""

    async def test_restores_history_and_step_index(self, service: SessionService) -> None:
        await service.create("sess_1")
        await service.append_messages(
            "sess_1",
            [{"role": "user", "content": "hi"}],
            step_index=3,
        )
        hook = SessionResumeHook(service)
        ctx = make_ctx()
        result = await hook({}, ctx)
        assert result == {}
        ctx.set_messages.assert_called_once_with([{"role": "user", "content": "hi"}])
        ctx.set_step_index.assert_called_once_with(3)

    async def test_skips_when_no_record(self, service: SessionService) -> None:
        hook = SessionResumeHook(service)
        ctx = make_ctx()
        await hook({}, ctx)
        ctx.set_messages.assert_not_called()
        ctx.set_step_index.assert_not_called()

    async def test_skips_when_persist_disabled(self, service: SessionService) -> None:
        await service.create("sess_1")
        await service.append_messages("sess_1", [{"role": "user", "content": "hi"}])
        hook = SessionResumeHook(service, config=SessionConfig(persist_messages=False))
        ctx = make_ctx()
        await hook({}, ctx)
        ctx.set_messages.assert_not_called()
        ctx.set_step_index.assert_not_called()

    async def test_disabled_skips(self, service: SessionService) -> None:
        await service.create("sess_1")
        hook = SessionResumeHook(service, config=SessionConfig(enabled=False))
        ctx = make_ctx()
        await hook({}, ctx)
        ctx.set_messages.assert_not_called()

    async def test_error_is_silent(self) -> None:
        svc = AsyncMock()
        svc.get = AsyncMock(side_effect=RuntimeError("boom"))
        hook = SessionResumeHook(svc)
        data = {"type": "session_resume"}
        result = await hook(data, make_ctx())
        assert result is data


class TestMemoryResumeHook:
    """MemoryResumeHook 测试。"""

    @pytest.fixture
    async def memory(self) -> MemoryService:
        m = MemoryService(SQLitePersistence(":memory:"))
        yield m
        await m.close()

    async def test_restores_plan_budget_pause(self, memory: MemoryService) -> None:
        snapshot = WorkingMemorySnapshot(
            session_id="sess_1",
            plan={"steps": ["a", "b"]},
            budget=BudgetSnapshot(token_used=12, token_limit=100, step_count=3, step_limit=10),
            pause_state=PauseState(
                is_paused=True,
                pending_approvals=[{"id": "ap1", "context": {}}],
                resume_token="tok",
            ),
        )
        await memory.checkpoint(snapshot)
        hook = MemoryResumeHook(memory)
        ctx = make_ctx()
        await hook({}, ctx)
        ctx.set_plan.assert_called_once_with({"steps": ["a", "b"]})
        ctx.set_budget.assert_called_once()
        restored_budget = ctx.set_budget.call_args.args[0]
        assert restored_budget.token_used == 12
        assert restored_budget.step_limit == 10
        ctx.set_pause_state.assert_called_once_with(
            {
                "is_paused": True,
                "pending_approvals": [{"id": "ap1", "context": {}}],
                "resume_token": "tok",
            }
        )

    async def test_no_snapshot_noop(self, memory: MemoryService) -> None:
        hook = MemoryResumeHook(memory)
        ctx = make_ctx()
        await hook({}, ctx)
        ctx.set_plan.assert_not_called()
        ctx.set_budget.assert_not_called()
        ctx.set_pause_state.assert_not_called()

    async def test_plan_none_keeps_plan(self, memory: MemoryService) -> None:
        snapshot = WorkingMemorySnapshot(
            session_id="sess_1",
            plan=None,
            budget=BudgetSnapshot(token_used=5),
        )
        await memory.checkpoint(snapshot)
        hook = MemoryResumeHook(memory)
        ctx = make_ctx()
        await hook({}, ctx)
        ctx.set_plan.assert_not_called()
        ctx.set_budget.assert_called_once()

    async def test_error_is_silent(self) -> None:
        memory = AsyncMock()
        memory.restore = AsyncMock(side_effect=RuntimeError("boom"))
        hook = MemoryResumeHook(memory)
        data = {"type": "session_resume"}
        result = await hook(data, make_ctx())
        assert result is data


class TestMessageChunking:
    """历史消息分块（ssh: 前缀）测试。"""

    async def test_chunks_stored_when_over_threshold(self) -> None:
        persistence = SQLitePersistence(":memory:")
        svc = SessionService(persistence, config=SessionConfig(chunk_size=10))
        try:
            await svc.create("sess_1")
            await svc.append_messages("sess_1", build_messages(25))
            keys = await persistence.list_keys("ssh:sess_1:")
            assert len(keys) == 3  # 25 条 → 10/10/5 三个分块
            record = await svc.get("sess_1")
            assert record is not None
            assert record.chunk_count == 3
            assert len(record.messages) == 25
        finally:
            await svc.close()

    async def test_inline_when_below_threshold(self) -> None:
        persistence = SQLitePersistence(":memory:")
        svc = SessionService(persistence, config=SessionConfig(chunk_size=10))
        try:
            await svc.create("sess_1")
            await svc.append_messages("sess_1", build_messages(8))
            raw = await persistence.get("ss:sess_1")
            assert raw is not None
            assert b"msg-0" in raw  # 消息内联存储在 ss:
            keys = await persistence.list_keys("ssh:sess_1:")
            assert keys == []
        finally:
            await svc.close()

    async def test_reload_reassembles_chunks(self) -> None:
        persistence = SQLitePersistence(":memory:")
        svc1 = SessionService(persistence, config=SessionConfig(chunk_size=10))
        await svc1.create("sess_1")
        await svc1.append_messages("sess_1", build_messages(22))
        svc2 = SessionService(persistence, config=SessionConfig(chunk_size=10))
        try:
            record = await svc2.get("sess_1")
            assert record is not None
            assert [m["content"] for m in record.messages] == [f"msg-{i}" for i in range(22)]
        finally:
            await svc2.close()
            await svc1.close()

    async def test_trimming_applies_with_chunking(self) -> None:
        persistence = SQLitePersistence(":memory:")
        svc = SessionService(
            persistence,
            config=SessionConfig(chunk_size=10, max_history_messages=15),
        )
        try:
            await svc.create("sess_1")
            await svc.append_messages("sess_1", build_messages(30))
            record = await svc.get("sess_1")
            assert record is not None
            assert len(record.messages) == 15  # 裁剪到上限
            assert record.message_count == 15
            keys = await persistence.list_keys("ssh:sess_1:")
            assert len(keys) == 2  # 15 条 → 10/5
        finally:
            await svc.close()

    async def test_layout_switch_cleans_chunks(self) -> None:
        persistence = SQLitePersistence(":memory:")
        svc1 = SessionService(persistence, config=SessionConfig(chunk_size=10))
        await svc1.create("sess_1")
        await svc1.append_messages("sess_1", build_messages(20))
        try:
            keys = await persistence.list_keys("ssh:sess_1:")
            assert len(keys) == 2
            # 新服务关闭分块 → 保存后回到内联布局并清理分块
            svc2 = SessionService(persistence, config=SessionConfig(chunk_size=0))
            await svc2.update_status("sess_1", "paused")
            keys = await persistence.list_keys("ssh:sess_1:")
            assert keys == []
            raw = await persistence.get("ss:sess_1")
            assert raw is not None and b"msg-0" in raw
            record = await svc2.get("sess_1")
            assert record is not None and record.chunk_count == 0
            assert len(record.messages) == 20
            await svc2.close()
        finally:
            await svc1.close()

    async def test_delete_removes_chunks(self) -> None:
        persistence = SQLitePersistence(":memory:")
        svc = SessionService(persistence, config=SessionConfig(chunk_size=10))
        try:
            await svc.create("sess_1")
            await svc.append_messages("sess_1", build_messages(20))
            await svc.delete("sess_1")
            keys = await persistence.list_keys("ssh:sess_1:")
            assert keys == []
            assert await persistence.get("ss:sess_1") is None
        finally:
            await svc.close()


class TestListUserSessionsPagination:
    """list_user_sessions 分页 / 状态过滤测试。"""

    async def test_offset_pagination(self, service: SessionService) -> None:
        for i in range(5):
            await service.create(f"sess_{i}", user_id="u1")
        page1 = await service.list_user_sessions("u1", limit=2, offset=0)
        page2 = await service.list_user_sessions("u1", limit=2, offset=2)
        page3 = await service.list_user_sessions("u1", limit=2, offset=4)
        all_ids = (
            [s.session_id for s in page1]
            + [s.session_id for s in page2]
            + [s.session_id for s in page3]
        )
        assert len(page1) == 2
        assert len(page2) == 2
        assert len(page3) == 1
        assert len(set(all_ids)) == 5

    async def test_status_filter_with_pagination(self, service: SessionService) -> None:
        await service.create("s1", user_id="u1")
        await service.create("s2", user_id="u1")
        await service.update_status("s2", "ended")
        await service.create("s3", user_id="u1")
        await service.update_status("s3", "ended")
        ended = await service.list_user_sessions("u1", status="ended")
        assert [s.session_id for s in ended] == ["s3", "s2"]  # updated_at 倒序
        active = await service.list_user_sessions("u1", status="active")
        assert [s.session_id for s in active] == ["s1"]


class TestBuilderResumeWiring:
    """Builder 并列注册 Session/Memory Resume Hook 测试。"""

    async def test_registers_resume_hooks(self) -> None:
        persistence = SQLitePersistence(":memory:")
        session_svc = SessionService(persistence)
        memory_svc = MemoryService(persistence)
        try:
            runtime = RuntimeBuilder().session(session_svc).memory(memory_svc).build()
            names = {h.name for h in runtime._hooks.list(HookPoint.SESSION_RESUME)}
            assert "_session_resume" in names
            assert "_memory_resume" in names
        finally:
            await session_svc.close()
            await memory_svc.close()
            await persistence.close()
