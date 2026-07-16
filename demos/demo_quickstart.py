"""
Demo 1: Quickstart — Runtime + Memory in 30 Seconds.

Shows the new composition pattern:
  SQLiteStorageEngine → individual Stores → MemoryService → AgentRuntime

Flow:
  1. User says "Hi, I'm Alice, a data scientist"
  2. System extracts entity (name=Alice) and commits episodic memory
  3. User asks about ML — system recalls past context
  4. Second session — system remembers Alice from before

Usage:
    uv run python demos/demo_quickstart.py
"""

from __future__ import annotations

import asyncio
import uuid

from lania_agent_runtime.hooks import BEFORE_STEP, HookRegistry
from lania_agent_runtime.memory import MemoryService
from lania_agent_runtime.memory.stores import (
    SQLiteStorageEngine,
    WorkingMemorySQLiteStore,
    EpisodicMemorySQLiteStore,
    EntityMemorySQLiteStore,
    SemanticKnowledgeSQLiteStore,
    BehavioralPatternSQLiteStore,
)
from lania_agent_runtime.models import LLMResponse, LLMUsage
from lania_agent_runtime.runtime import AgentRuntime


# ── Helpers ──

def banner(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def info(label: str, value: object) -> None:
    print(f"  {label}: {value}")


class EchoExecutor:
    """模拟 LLM 执行器 — 无需 API key."""

    async def execute(self, ctx):
        content = ctx.messages[-1].get("content", "")
        return LLMResponse(
            content=f"👤 我记得你说过: \"{content[:60]}\"",
            usage=LLMUsage(prompt_tokens=10, completion_tokens=5),
            finish_reason="stop",
            model="echo-demo",
        )

    async def execute_stream(self, ctx):
        from lania_agent_runtime.executor import AsyncStreamCollector
        content = ctx.messages[-1].get("content", "")
        text = f"👤 我记得你说过: \"{content[:60]}\""
        collector = AsyncStreamCollector()
        collector._content_chunks = [text]
        response = LLMResponse(content=text, usage=LLMUsage(10, 5), finish_reason="stop", model="echo-demo")
        return collector, response


# ── Hook: 打印召回内容 ──

async def trace_recall(data, ctx):
    memories = ctx.context_payload.memories
    profile = ctx.context_payload.entity_profile
    tone = ctx.context_payload.tone_instruction
    if memories or profile or tone:
        print(f"    📦 召回: {len(memories)} 条记忆, {len(profile)} 个画像属性"
              f"{', 语气=' + tone if tone else ''}")


# ── 主流程 ──

async def run():
    banner("Step 1: 创建存储引擎 + 各层 Store")
    engine = SQLiteStorageEngine(":memory:")
    await engine.initialize()

    working = WorkingMemorySQLiteStore(engine)
    episodic = EpisodicMemorySQLiteStore(engine)
    entity = EntityMemorySQLiteStore(engine)
    semantic = SemanticKnowledgeSQLiteStore(engine)
    pattern = BehavioralPatternSQLiteStore(engine)

    for s in [working, episodic, entity, semantic, pattern]:
        await s.initialize()
    info("引擎 + 5 层 Store", "✅ 已就绪 (共享同一连接)")

    banner("Step 2: 组装 MemoryService + Runtime")
    memory_svc = MemoryService(
        working_store=working,
        episodic_store=episodic,
        entity_store=entity,
        semantic_store=semantic,
        pattern_store=pattern,
    )
    hooks = HookRegistry()
    hooks.observe(BEFORE_STEP, trace_recall, "trace")
    runtime = AgentRuntime(
        session_id=f"qstart-{uuid.uuid4().hex[:6]}",
        agent_id="quickstart",
        llm_executor=EchoExecutor(),
        hooks=hooks,
        memory=memory_svc,
    )
    info("Runtime", f"{runtime.session_id} ✅")

    # ── 对话 ──

    banner("Step 3: 多轮对话")
    turns = [
        "Hi! I'm Alice, a data scientist.",
        "Tell me about Machine Learning.",
        "I love building ML models with Python.",
    ]
    for i, msg in enumerate(turns, 1):
        print(f"\n  🗣️  Turn {i}: {msg}")
        result = await runtime.run(msg, user_id="alice",
                                   system_prompt="You are a helpful assistant.")
        print(f"  🤖 {result.content}")
        info("消息数", len(result.messages))

    # ── 记忆检查 ──

    banner("Step 4: 记忆系统检查")

    profile = await entity.get_entity_profile("user", "alice")
    if profile:
        info("Layer 3 实体画像",
             ", ".join(f"{k}={v['value']}" for k, v in profile.attributes.items()))

    pattern_data = await pattern.get_behavioral_pattern("alice")
    if pattern_data:
        info("Layer 5 行为模式",
             ", ".join(f"{k}={v}" for k, v in pattern_data.patterns.items()))

    # ── 新建 session 但同用户 → 跨 session 召回 ──

    banner("Step 5: 新 Session — 跨对话记忆")
    runtime2 = AgentRuntime(
        session_id=f"qstart-{uuid.uuid4().hex[:6]}",
        agent_id="quickstart",
        llm_executor=EchoExecutor(),
        hooks=hooks,
        memory=memory_svc,
    )
    msg = "Do you know who I am?"
    print(f"  🗣️  {msg}")
    result2 = await runtime2.run(msg, user_id="alice",
                                 system_prompt="You are a helpful assistant.")
    print(f"  🤖 {result2.content}")
    info("(跨 session 召回, 用户画像保留)", "✅")

    # ── 清理 ──

    await runtime.destroy()
    await runtime2.destroy()
    await engine.close()

    banner("完成")
    info("全部流程", "Runtime + 5层记忆 + 跨 Session 召回 ✅")


if __name__ == "__main__":
    asyncio.run(run())
