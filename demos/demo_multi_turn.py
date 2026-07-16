"""
Demo 2: Multi-turn — Runtime + 5-Layer Memory Deep Dive.

Shows the complete memory system architecture:
  - Composition pattern: StorageEngine + individual Stores
  - All 5 memory layers in action (working -> episodic -> entity -> semantic -> pattern)
  - Cross-session recall with user identity
  - Backend flexibility: swap WorkingMemoryFileStore for Layer 1

Usage:
    uv run python demos/demo_multi_turn.py
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
    WorkingMemoryFileStore,
)
from lania_agent_runtime.models import LLMResponse, LLMUsage
from lania_agent_runtime.runtime import AgentRuntime

# ── Utilities ──


def section(title: str) -> None:
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}")


def info(label: str, value: object = "", indent: int = 0) -> None:
    pad = "  " * indent
    if value:
        print(f"{pad}  * {label}: {value}")
    else:
        print(f"{pad}  * {label}")


class MockExecutor:
    """Mock LLM executor — no API key needed."""

    def __init__(self) -> None:
        self.turn = 0

    async def execute(self, ctx):
        self.turn += 1
        content = ctx.messages[-1].get("content", "")
        return LLMResponse(
            content=f"[Mock] Echo: {content[:60]}",
            usage=LLMUsage(prompt_tokens=15, completion_tokens=8),
            finish_reason="stop",
            model="mock-demo",
        )

    async def execute_stream(self, ctx):
        from lania_agent_runtime.executor import AsyncStreamCollector

        content = ctx.messages[-1].get("content", "")
        text = f"[Mock] Echo: {content[:60]}"
        collector = AsyncStreamCollector()
        collector._content_chunks = [text]
        response = LLMResponse(
            content=text, usage=LLMUsage(15, 8), finish_reason="stop", model="mock-demo"
        )
        return collector, response


async def trace_before_step(data, ctx):
    """Hook: log recall volume before each LLM call."""
    memories = ctx.context_payload.memories
    profile = ctx.context_payload.entity_profile
    tone = ctx.context_payload.tone_instruction
    parts = []
    if memories:
        parts.append(f"{len(memories)} episodic memories")
    if profile:
        parts.append(f"{len(profile)} entity attributes")
    if tone:
        parts.append(f"tone=「{tone}」")
    if parts:
        print(f"    [before_step] -> LLM carries: {', '.join(parts)}")


# ── Main ──


async def run():
    section("Part 1: Architecture — Engine + Composable Stores")

    # 1. Create shared engine
    info("Creating SQLiteStorageEngine (shared connection)", ":memory:")
    engine = SQLiteStorageEngine(":memory:")
    await engine.initialize()

    # 2. Create 5 stores sharing the same engine
    info("Creating 5 layer Stores (sharing one engine instance)")
    working = WorkingMemorySQLiteStore(engine)
    episodic = EpisodicMemorySQLiteStore(engine)
    entity = EntityMemorySQLiteStore(engine)
    semantic = SemanticKnowledgeSQLiteStore(engine)
    pattern = BehavioralPatternSQLiteStore(engine)

    for s in [working, episodic, entity, semantic, pattern]:
        await s.initialize()
    info("All stores", "table creation OK")

    # 3. Optional: swap Layer 1 to file-based
    info("Optional: replace Layer 1 with WorkingMemoryFileStore (file system)")
    file_working = WorkingMemoryFileStore(".runtime/demo_working")
    await file_working.initialize()
    info("File store ready", "(Layer 1 is pluggable)")

    arch = """Architecture:
    SQLiteStorageEngine (shared connection)
      +-- WorkingMemorySQLiteStore    (Layer 1: overwrite + TTL)
      +-- EpisodicMemorySQLiteStore   (Layer 2: append-only)
      +-- EntityMemorySQLiteStore     (Layer 3: UPSERT)
      +-- SemanticKnowledgeSQLiteStore (Layer 4: graph)
      +-- BehavioralPatternSQLiteStore (Layer 5: full overwrite)
    """
    print(f"\n{arch}")

    # 4. Assemble facade
    memory_svc = MemoryService(
        working_store=working,
        episodic_store=episodic,
        entity_store=entity,
        semantic_store=semantic,
        pattern_store=pattern,
    )

    hooks = HookRegistry()
    hooks.observe(BEFORE_STEP, trace_before_step, "trace_recall")

    session_id = f"demo-{uuid.uuid4().hex[:8]}"
    runtime = AgentRuntime(
        session_id=session_id,
        agent_id="demo-agent",
        llm_executor=MockExecutor(),
        hooks=hooks,
        memory=memory_svc,
    )
    info("Runtime created", session_id)

    # ════════════════════════════════════════════════════════════════
    section("Part 2: Multi-turn Dialogue — Auto Memory Commit")
    # ════════════════════════════════════════════════════════════════

    turns = [
        "Hi! My name is Alice and I'm a Data Scientist.",
        "Tell me about Machine Learning algorithms.",
        "I love using Python and FastAPI for my projects.",
        "Can you explain Deep Learning vs traditional ML?",
        "What's the best way to deploy models to production?",
    ]

    for i, msg in enumerate(turns, 1):
        print(f"\n  Turn {i}:")
        print(f"    User:       {msg}")
        result = await runtime.run(
            msg, user_id="alice", system_prompt="You are a helpful assistant."
        )
        print(f"    Assistant:  {result.content[:70]}")
        info("Messages accumulated", f"{len(result.messages)}", indent=1)

    # ════════════════════════════════════════════════════════════════
    section("Part 3: Inspect Each Memory Layer")
    # ════════════════════════════════════════════════════════════════

    # Layer 1: Working Memory
    info("Layer 1 - Working Memory")
    wm = await working.load_working_memory(session_id)
    if wm:
        info(
            f"step={wm.step_index}, tokens={wm.total_tokens}, status={wm.status}",
            indent=1,
        )
    else:
        info("(not expired)", indent=1)

    # Layer 2: Episodic Memory
    info("Layer 2 - Episodic Memory")
    entries = await episodic.recall_session(session_id)
    info(f"Total {len(entries)} entries", indent=1)
    for m in entries:
        detail = f"[#{m.turn_index}] {m.summary[:50]}"
        if m.topics:
            detail += f"  topics={m.topics}"
        info(detail, indent=2)

    # Layer 3: Entity Profile
    info("Layer 3 - Entity Profile")
    profile = await entity.get_entity_profile("user", "alice")
    if profile:
        for attr, data in profile.attributes.items():
            info(f"{attr} = {data['value']} (conf={data['confidence']})", indent=1)
    else:
        info("(none)", indent=1)

    # Layer 4: Semantic Knowledge — use full terms to match nodes
    info("Layer 4 - Semantic Knowledge")
    for term in ["Machine Learning", "Python", "Deep Learning"]:
        nodes = await semantic.search_semantic(term, limit=3)
        for n in nodes:
            info(f"[{n.type}] {n.name} (mentioned {n.mention_count}x)", indent=1)

    # Layer 5: Behavioral Pattern
    info("Layer 5 - Behavioral Pattern")
    pat = await pattern.get_behavioral_pattern("alice")
    if pat:
        for k, v in pat.patterns.items():
            info(f"{k} = {v}", indent=1)
    else:
        info("(not yet converged)", indent=1)

    # ════════════════════════════════════════════════════════════════
    section("Part 4: Cross-Session Recall — Memory Persists")
    # ════════════════════════════════════════════════════════════════

    info("New session (same user: alice)")
    runtime2 = AgentRuntime(
        session_id=f"demo-{uuid.uuid4().hex[:8]}",
        agent_id="demo-agent",
        llm_executor=MockExecutor(),
        hooks=hooks,
        memory=memory_svc,
    )
    result = await runtime2.run(
        "What do you remember about me?",
        user_id="alice",
        system_prompt="You are a helpful assistant.",
    )
    info("Assistant", result.content[:80], indent=1)

    # ════════════════════════════════════════════════════════════════
    section("Part 5: ContextPayload -> System Message")
    # ════════════════════════════════════════════════════════════════

    payload = await memory_svc.recall(
        session_id=session_id,
        user_id="alice",
        query="Machine Learning Python deployment",
    )
    sys_msg = payload.serialize_to_system_message()
    info(f"Serialized to system message ({len(sys_msg)} chars)")
    for line in sys_msg.split("\n")[:10]:
        info(line.strip() if line.strip() else "(blank)", indent=1)
    if sys_msg.count("\n") > 10:
        info(f"... {sys_msg.count(chr(10)) + 1} lines total", indent=1)

    # ════════════════════════════════════════════════════════════════
    section("Cleanup")
    # ════════════════════════════════════════════════════════════════

    await runtime.destroy()
    await runtime2.destroy()
    await engine.close()
    await file_working.close()
    info("Runtime destroyed, connection closed")

    # ════════════════════════════════════════════════════════════════
    section("Summary")
    # ════════════════════════════════════════════════════════════════

    print(f"  Session:       {session_id}")
    print(f"  Turns:         {len(turns)}")
    print(f"  Episodic:      {len(entries)} entries")
    print(f"  Entity attrs:  {len(profile.attributes) if profile else 0}")
    print("  Architecture:  Interface + Composition (no inheritance)")
    print("  Cross-session: OK")


if __name__ == "__main__":
    asyncio.run(run())
