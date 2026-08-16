"""
Session hooks 单元测试。

覆盖：SessionStartHook（创建/恢复/开关/容错）、SessionCommitHook（提交/开关/容错）、
SessionEndHook（归档/容错）。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.memory._backends._sqlite import SQLitePersistence
from src.session._config import SessionConfig
from src.session._hooks import SessionCommitHook, SessionEndHook, SessionStartHook
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
    return ctx


class TestSessionStartHook:
    """SessionStartHook 测试。"""

    async def test_creates_session(self, service: SessionService) -> None:
        hook = SessionStartHook(service)
        ctx = make_ctx(services={"user_id": "u1"})
        data = {"type": "session_start", "input": "你好世界"}
        result = await hook(data, ctx)
        assert result is data
        record = await service.get("sess_1")
        assert record is not None
        assert record.user_id == "u1"
        assert record.title == "你好世界"
        ctx.set_messages.assert_not_called()

    async def test_restores_history_and_step(self, service: SessionService) -> None:
        await service.create("sess_1")
        await service.append_messages(
            "sess_1",
            [{"role": "user", "content": "hi"}],
            step_index=3,
        )
        hook = SessionStartHook(service)
        ctx = make_ctx()
        await hook({}, ctx)
        ctx.set_messages.assert_called_once_with([{"role": "user", "content": "hi"}])
        ctx.set_step_index.assert_called_once_with(3)

    async def test_auto_title_disabled(self, service: SessionService) -> None:
        hook = SessionStartHook(service, config=SessionConfig(auto_title=False))
        ctx = make_ctx()
        await hook({"type": "session_start", "input": "xxx"}, ctx)
        record = await service.get("sess_1")
        assert record is not None
        assert record.title == ""

    async def test_disabled_skips(self, service: SessionService) -> None:
        hook = SessionStartHook(service, config=SessionConfig(enabled=False))
        ctx = make_ctx()
        await hook({}, ctx)
        assert await service.get("sess_1") is None

    async def test_error_is_silent(self) -> None:
        svc = AsyncMock()
        svc.get = AsyncMock(side_effect=RuntimeError("boom"))
        hook = SessionStartHook(svc)
        data = {"type": "session_start"}
        result = await hook(data, make_ctx())
        assert result is data


class TestSessionCommitHook:
    """SessionCommitHook 测试。"""

    async def test_appends_messages(self, service: SessionService) -> None:
        await service.create("sess_1")
        hook = SessionCommitHook(service)
        ctx = make_ctx(messages=[{"role": "user", "content": "hi"}], step_index=1)
        await hook({}, ctx)
        record = await service.get("sess_1")
        assert record is not None
        assert record.message_count == 1
        assert record.step_index == 1

    async def test_persist_disabled_skips(self, service: SessionService) -> None:
        await service.create("sess_1")
        hook = SessionCommitHook(service, config=SessionConfig(persist_messages=False))
        ctx = make_ctx(messages=[{"role": "user", "content": "hi"}])
        await hook({}, ctx)
        record = await service.get("sess_1")
        assert record is not None
        assert record.message_count == 0

    async def test_error_is_silent(self) -> None:
        svc = AsyncMock()
        svc.append_messages = AsyncMock(side_effect=RuntimeError("boom"))
        hook = SessionCommitHook(svc)
        data = {"type": "after_step"}
        result = await hook(data, make_ctx())
        assert result is data


class TestSessionEndHook:
    """SessionEndHook 测试。"""

    async def test_finalize(self, service: SessionService) -> None:
        await service.create("sess_1")
        hook = SessionEndHook(service)
        ctx = make_ctx(step_index=5)
        ctx.budget.token_used = 99
        data = {"type": "session_end", "status": "ended", "last_error": None}
        await hook(data, ctx)
        record = await service.get("sess_1")
        assert record is not None
        assert record.status == "ended"
        assert record.token_used == 99
        assert record.step_count == 5

    async def test_error_is_silent(self) -> None:
        svc = AsyncMock()
        svc.finalize = AsyncMock(side_effect=RuntimeError("boom"))
        hook = SessionEndHook(svc)
        data = {"type": "session_end", "status": "ended"}
        result = await hook(data, make_ctx())
        assert result is data
