"""
Session → Runtime → Memory → Session 全链路端到端测试。

覆盖：Builder 接线、session_id 注入、逐轮提交原文、session_end 归档、
续聊恢复历史、Memory 不再保存原文。
"""

from __future__ import annotations

from src.memory._backends._sqlite import SQLitePersistence
from src.memory._service import MemoryService
from src.runtime import AgentRuntime
from src.session._service import SessionService


async def mock_llm(ctx) -> dict:
    """返回固定回复的 mock LLM。"""
    return {"role": "assistant", "content": "好的，我知道了"}


class TestSessionEndToEnd:
    """Session 全链路测试。"""

    async def test_full_chain(self) -> None:
        backend = SQLitePersistence(":memory:")
        session = SessionService(backend)
        memory = MemoryService(persistence=backend)
        try:
            runtime = (
                AgentRuntime.builder()
                .system_prompt("你是助手")
                .session_id("sess_e2e")
                .session(session)
                .memory(memory)
                .build()
            )
            runtime.set_llm_executor(mock_llm)
            result = await runtime.run("我叫小明，帮我记录一下")
            assert result.content == "好的，我知道了"

            record = await session.get("sess_e2e")
            assert record is not None
            assert record.status == "ended"
            # v2.1：会话历史不含 system（system prompt 属运行时配置）
            assert record.message_count == 2
            assert [m["role"] for m in record.messages] == ["user", "assistant"]
            assert record.step_index == 1

            # Memory 不再保存原文，只保存摘要
            entries = await memory._episodic.recall_session("sess_e2e")
            assert len(entries) == 1
            assert entries[0].raw_content is None
            assert "我叫小明" in entries[0].summary
        finally:
            await session.close()
            await memory.close()

    async def test_resume_restores_history(self) -> None:
        backend = SQLitePersistence(":memory:")
        session = SessionService(backend)
        memory = MemoryService(persistence=backend)
        try:

            async def llm(ctx) -> dict:
                return {"role": "assistant", "content": "ok"}

            runtime1 = (
                AgentRuntime.builder()
                .system_prompt("p")
                .session_id("sess_r")
                .session(session)
                .memory(memory)
                .build()
            )
            runtime1.set_llm_executor(llm)
            await runtime1.run("第一轮")

            runtime2 = (
                AgentRuntime.builder()
                .system_prompt("p")
                .session_id("sess_r")
                .session(session)
                .memory(memory)
                .build()
            )
            runtime2.set_llm_executor(llm)
            await runtime2.run("第二轮")

            record = await session.get("sess_r")
            assert record is not None
            assert record.message_count == 4
            contents = [m["content"] for m in record.messages]
            assert contents == ["第一轮", "ok", "第二轮", "ok"]
        finally:
            await session.close()
            await memory.close()

    async def test_resume_with_changed_system_prompt(self) -> None:
        """换提示词续聊时，执行器应收到新 system_prompt。"""
        backend = SQLitePersistence(":memory:")
        session = SessionService(backend)
        memory = MemoryService(persistence=backend)
        seen: list[list[dict]] = []
        try:

            async def llm(ctx) -> dict:
                return {"role": "assistant", "content": "ok"}

            runtime1 = (
                AgentRuntime.builder()
                .system_prompt("旧提示词")
                .session_id("sess_p")
                .session(session)
                .memory(memory)
                .build()
            )
            runtime1.set_llm_executor(llm)
            await runtime1.run("第一轮")

            async def capturing_llm(ctx) -> dict:
                seen.append(list(ctx.messages))
                return {"role": "assistant", "content": "ok"}

            runtime2 = (
                AgentRuntime.builder()
                .system_prompt("新提示词")
                .session_id("sess_p")
                .session(session)
                .memory(memory)
                .build()
            )
            runtime2.set_llm_executor(capturing_llm)
            await runtime2.run("第二轮")

            assert seen
            sent = seen[-1]
            assert sent[0]["role"] == "system"
            assert sent[0]["content"] == "新提示词"
            assert [m["content"] for m in sent] == ["新提示词", "第一轮", "ok", "第二轮"]
        finally:
            await session.close()
            await memory.close()

    async def test_executor_receives_system_without_memory(self) -> None:
        """无 memory 场景：执行器应收到 system + user（L1 修复）。"""
        seen: list[list[dict]] = []

        async def capturing_llm(ctx) -> dict:
            seen.append(list(ctx.messages))
            return {"role": "assistant", "content": "ok"}

        runtime = AgentRuntime(system_prompt="你是助手")
        runtime.set_llm_executor(capturing_llm)
        await runtime.run("你好")
        assert seen
        assert seen[0][0]["role"] == "system"
        assert seen[0][0]["content"] == "你是助手"
        assert seen[0][1]["role"] == "user"
        assert seen[0][1]["content"] == "你好"

    async def test_resume_without_memory_uses_new_prompt(self) -> None:
        """无 memory 续聊：恢复纯对话历史后执行器收到新 system + 完整历史。"""
        backend = SQLitePersistence(":memory:")
        session = SessionService(backend)
        seen: list[list[dict]] = []
        try:

            async def llm(ctx) -> dict:
                return {"role": "assistant", "content": "ok"}

            runtime1 = (
                AgentRuntime.builder()
                .system_prompt("旧")
                .session_id("sess_nm")
                .session(session)
                .build()
            )
            runtime1.set_llm_executor(llm)
            await runtime1.run("第一轮")

            async def capturing_llm(ctx) -> dict:
                seen.append(list(ctx.messages))
                return {"role": "assistant", "content": "ok"}

            runtime2 = (
                AgentRuntime.builder()
                .system_prompt("新")
                .session_id("sess_nm")
                .session(session)
                .build()
            )
            runtime2.set_llm_executor(capturing_llm)
            await runtime2.run("第二轮")

            assert seen
            sent = seen[-1]
            assert sent[0]["content"] == "新"
            assert [m["content"] for m in sent] == ["新", "第一轮", "ok", "第二轮"]
        finally:
            await session.close()

    async def test_builder_registers_session_hooks(self) -> None:
        backend = SQLitePersistence(":memory:")
        session = SessionService(backend)
        try:
            runtime = (
                AgentRuntime.builder()
                .system_prompt("p")
                .session_id("sess_h")
                .session(session)
                .build()
            )
            names = {h.name for h in runtime._hooks.list()}
            assert {"_session_start", "_session_commit", "_session_end"} <= names
            assert runtime.session_id == "sess_h"
        finally:
            await session.close()
