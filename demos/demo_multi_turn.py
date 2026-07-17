"""
Demo 2: 多轮对话 — Runtime + 五层记忆深度演示.

展示完整记忆系统架构:
  - 选择一个后端 (GenericMemoryStore + SQLiteBackend)
  - 五层记忆全部运作 (工作 -> 情景 -> 实体 -> 语义 -> 行为)
  - 跨 session 召回, 基于用户身份

用法:
    python demos/demo_multi_turn.py
"""

from __future__ import annotations

import asyncio
import uuid

from lania_agent_runtime.hooks import BEFORE_STEP, HookRegistry
from lania_agent_runtime.memory import GenericMemoryStore, MemoryService
from lania_agent_runtime.memory.backends import SQLiteBackend
from lania_agent_runtime.models import LLMResponse, LLMUsage
from lania_agent_runtime.runtime import AgentRuntime

# ── 辅助函数 ──


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
    """模拟 LLM 执行器 — 无需 API key."""

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
    """Hook: 每次 LLM 调用前打印召回量."""
    memories = ctx.context_payload.memories
    profile = ctx.context_payload.entity_profile
    tone = ctx.context_payload.tone_instruction
    parts = []
    if memories:
        parts.append(f"{len(memories)} 条情景记忆")
    if profile:
        parts.append(f"{len(profile)} 个实体属性")
    if tone:
        parts.append(f"语气=「{tone}」")
    if parts:
        print(f"    [before_step] -> LLM 携带: {', '.join(parts)}")


# ── 主流程 ──


async def run():
    section("第 1 部分: 架构 — GenericMemoryStore + SQLiteBackend")

    # 1. 创建存储 — 只需选择一个后端
    store = GenericMemoryStore(SQLiteBackend(":memory:"))
    await store.initialize()
    info("存储后端", "GenericMemoryStore(SQLiteBackend) (:memory:)")

    info("原语映射")
    for line in [
        "kv_set/get/delete/exists    → Layer 1 (覆盖写 + TTL)",
        "list_push/range/len/remove  → Layer 2 (追加写入)",
        "kv + set                    → Layer 3 (UPSERT)",
        "graph_node/edge/neighbors   → Layer 4 (图)",
        "kv + lock                   → Layer 5 (全量覆盖)",
    ]:
        info(line, indent=1)

    # 2. 组装门面
    memory_svc = MemoryService(store=store)

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
    info("Runtime 已创建", session_id)

    # ════════════════════════════════════════════════════════════════
    section("第 2 部分: 多轮对话 — 自动记忆提交")
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
        info("消息累积", f"{len(result.messages)} 条", indent=1)

    # ════════════════════════════════════════════════════════════════
    section("第 3 部分: 检查各层记忆")
    # ════════════════════════════════════════════════════════════════

    # Layer 1: 工作记忆
    info("Layer 1 - 工作记忆")
    wm = await store.load_working_memory(session_id)
    if wm:
        info(
            f"step={wm.step_index}, tokens={wm.total_tokens}, status={wm.status}",
            indent=1,
        )
    else:
        info("(未过期)", indent=1)

    # Layer 2: 情景记忆
    info("Layer 2 - 情景记忆")
    entries = await store.recall_session(session_id)
    info(f"共 {len(entries)} 条记录", indent=1)
    for m in entries:
        detail = f"[#{m.turn_index}] {m.summary[:50]}"
        if m.topics:
            detail += f"  topics={m.topics}"
        info(detail, indent=2)

    # Layer 3: 实体画像
    info("Layer 3 - 实体画像")
    profile = await store.get_entity_profile("user", "alice")
    if profile:
        for attr, data in profile.attributes.items():
            info(f"{attr} = {data['value']} (置信度={data['confidence']})", indent=1)
    else:
        info("(无)", indent=1)

    # Layer 4: 语义知识
    info("Layer 4 - 语义知识")
    for term in ["Machine Learning", "Python", "Deep Learning"]:
        nodes = await store.search_semantic(term, limit=3)
        for n in nodes:
            info(f"[{n.type}] {n.name} (提及 {n.mention_count} 次)", indent=1)

    # Layer 5: 行为模式
    info("Layer 5 - 行为模式")
    pat = await store.get_behavioral_pattern("alice")
    if pat:
        for k, v in pat.patterns.items():
            info(f"{k} = {v}", indent=1)
    else:
        info("(尚未收敛)", indent=1)

    # ════════════════════════════════════════════════════════════════
    section("第 4 部分: 跨 Session 召回 — 记忆持久化")
    # ════════════════════════════════════════════════════════════════

    info("新 session (同一用户: alice)")
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
    section("第 5 部分: ContextPayload -> System Message")
    # ════════════════════════════════════════════════════════════════

    payload = await memory_svc.recall(
        session_id=session_id,
        user_id="alice",
        query="Machine Learning Python deployment",
    )
    sys_msg = payload.serialize_to_system_message()
    info(f"序列化为 system message ({len(sys_msg)} 字符)")
    for line in sys_msg.split("\n")[:10]:
        info(line.strip() if line.strip() else "(空白)", indent=1)
    if sys_msg.count("\n") > 10:
        info(f"... 共 {sys_msg.count(chr(10)) + 1} 行", indent=1)

    # ════════════════════════════════════════════════════════════════
    section("清理")
    # ════════════════════════════════════════════════════════════════

    await runtime.destroy()
    await runtime2.destroy()
    await store.close()
    info("Runtime 已销毁, 连接已关闭")

    # ════════════════════════════════════════════════════════════════
    section("总结")
    # ════════════════════════════════════════════════════════════════

    print(f"  Session:       {session_id}")
    print(f"  对话轮次:       {len(turns)}")
    print(f"  情景记忆:       {len(entries)} 条")
    print(f"  实体属性:       {len(profile.attributes) if profile else 0}")
    print("  架构模式:       Interface + Composition (无继承)")
    print("  跨 Session:     OK")


if __name__ == "__main__":
    asyncio.run(run())
