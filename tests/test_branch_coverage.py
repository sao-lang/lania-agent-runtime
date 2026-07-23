"""
精准分支覆盖——覆盖剩余的 partial branches。
"""

from __future__ import annotations

import pytest

from src.runtime._runtime import AgentRuntime
from src.runtime._types import AllowAction, HookPoint, PrimitiveType
from src.runtime.config._runtime_config import RuntimeConfig


class TestRuntimeBranches:
    """Runtime 剩余分支。"""

    async def test_after_llm_intercept_modified_str(self) -> None:
        """after_llm AllowAction.modified 为字符串时替换 content。"""
        runtime = AgentRuntime(system_prompt="助手")

        @runtime.on(HookPoint.AFTER_LLM, primitive=PrimitiveType.INTERCEPT)
        async def modify_str(data, ctx):
            return AllowAction(modified="modified str")

        async def mock_llm(ctx):
            return {"role": "assistant", "content": "original"}

        runtime.set_llm_executor(mock_llm)
        await runtime.run("test")
        # 最后一条 assistant 消息的 content 应被修改
        last_msg = runtime._messages[-1]
        assert "modified str" in str(last_msg.get("content", ""))

    async def test_run_with_custom_loop_executor(self) -> None:
        """自定义 loop_executor 路径。"""
        runtime = AgentRuntime(system_prompt="助手")

        async def custom_loop(ctx):
            return {"content": "loop result"}

        runtime.set_loop_executor(custom_loop)
        result = await runtime.run("hi")
        assert result.content == "loop result"

    async def test_before_serialize_not_dirty(self) -> None:
        """非 dirty 时不触发 before_serialize。"""
        runtime = AgentRuntime(system_prompt="助手")
        called: list[str] = []

        @runtime.on(HookPoint.BEFORE_SERIALIZE, primitive=PrimitiveType.TRANSFORM)
        async def on_serialize(data, ctx):
            called.append("called")
            return data

        async def mock_llm(ctx):
            return {"role": "assistant", "content": "ok"}

        runtime.set_llm_executor(mock_llm)
        # 标记为 clean
        runtime._context_payload.mark_clean()
        await runtime.run("test")
        # 不应触发 before_serialize
        assert "called" not in called

    async def test_after_llm_intercept_modified_dict_replaces(self) -> None:
        """after_llm AllowAction.modified dict 替换整个消息。"""
        runtime = AgentRuntime(system_prompt="助手")

        @runtime.on(HookPoint.AFTER_LLM, primitive=PrimitiveType.INTERCEPT)
        async def modify_full(data, ctx):
            return AllowAction(modified={"role": "assistant", "content": "full replace"})

        async def mock_llm(ctx):
            return {"role": "assistant", "content": "original"}

        runtime.set_llm_executor(mock_llm)
        await runtime.run("test")
        last_msg = runtime._messages[-1]
        assert last_msg["content"] == "full replace"


class TestConfigBranches:
    """RuntimeConfig 分支覆盖。"""

    def test_from_env_with_known_sections(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """单下划线已知 section 路径。"""
        monkeypatch.setenv("AGENT_LLM_MODEL", "gpt-4o")
        monkeypatch.setenv("AGENT_TIMEOUT_STEP_TIMEOUT_MS", "30000")

        config = RuntimeConfig.from_env(prefix="AGENT_")
        assert config.llm.get("model") == "gpt-4o"
        assert config.timeout.get("step_timeout_ms") == 30000
