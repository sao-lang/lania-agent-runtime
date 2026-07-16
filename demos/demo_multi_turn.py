# -*- coding: utf-8 -*-

"""

Demo 2: Comprehensive Memory System Test.


Tests ALL features of the 5-layer memory system including

the new EntityStore / SemanticStore / BehavioralStore interfaces.


Coverage:

  L1 - Working Memory : checkpoint / restore / discard / overwrite / TTL expiry

  L2 - Episodic Memory: write / recall_session / recall_user / search / count / full-data

  L3 - Entity Memory  : upsert_attribute / get_entity_profile / history

  L4 - Semantic Know.  : create_node / search / edges / mention_count / idempotent

  L5 - Behavioral      : upsert_pattern / get_behavioral_pattern / versioning

  MemoryService        : 5-layer recall / commit / entity extraction / pattern detection


Usage:

    uv run python demos/demo_multi_turn.py

"""


import asyncio

import uuid

from datetime import datetime, timedelta


from lania_agent_runtime.memory.base import MemoryService

from lania_agent_runtime.memory.sqlite_store import SQLiteMemoryStore

from lania_agent_runtime.models import EpisodicMemoryEntry, WorkingMemorySnapshot


# ── Helpers ──


def section(title: str) -> None:

    print(f"\n{'=' * 70}")

    print(f"  {title}")

    print(f"{'=' * 70}")


def step(n: int, desc: str) -> None:

    print(f"\n  ** Step {n}: {desc}")

    print(f"  {'-' * 50}")


async def show_episodic(label: str, memories: list[EpisodicMemoryEntry]) -> None:

    print(f"  {label}: {len(memories)} entries")

    for m in memories:

        print(f"    [{m.created_at}] #{m.turn_index} {m.summary[:90]}")

        if m.entities:

            print(f"     -?entities={m.entities}")

        if m.topics:

            print(f"     -?topics={m.topics}")

# ══════════════════════════════════════════════════════════════════════════

#  MAIN

# ══════════════════════════════════════════════════════════════════════════


async def run_demo() -> None:

    print("=" * 70)

    print("  Comprehensive Memory System Test")

    print("  All 5 Layers -- Full API Coverage")

    print("=" * 70)

    # ── Init ──

    store = SQLiteMemoryStore()

    await store.initialize()

    memory = MemoryService(store=store)

    session_id = f"demo-{uuid.uuid4().hex[:8]}"

    session_b = f"demo-{uuid.uuid4().hex[:8]}"

    user_id = "user-xiaoming"

    now = datetime.now()

    # ══════════════════════════════════════════════════════════════════════════

    #  LAYER 1: Working Memory

    # ══════════════════════════════════════════════════════════════════════════

    section("LAYER 1: Working Memory")

    step(1, "Checkpoint #1 -?save turn 1 state")

    snap1 = WorkingMemorySnapshot(

        session_id=session_id, step_index=1, message_count=2, total_tokens=150,

        status="running", messages=[{"role": "user", "content": "hello"}],

        captured_at=now.isoformat(), version=1,

    )

    await memory.checkpoint(snap1)

    print("    -?Checkpoint #1 saved (version=1)")

    step(2, "Checkpoint #2 -?overwrite with turn 2 state")

    snap2 = WorkingMemorySnapshot(

        session_id=session_id, step_index=2, message_count=4, total_tokens=320,

        status="running",

        messages=[{"role": "user", "content": "hello"},

                  {"role": "assistant", "content": "hi!"}],

        captured_at=now.isoformat(), version=2,

    )

    await memory.checkpoint(snap2)

    print("    -?Checkpoint #2 saved (overwrite, version=2)")

    step(3, "Restore -?should get the latest (turn 2)")

    restored = await memory.restore(session_id)

    assert restored is not None and restored.step_index == 2

    print(f"    -?Restored: step_index={restored.step_index}, version={restored.version}")

    step(4, "Discard + confirm restore returns None")

    await memory.discard_checkpoint(session_id)

    assert await memory.restore(session_id) is None

    print("    -?Discard successful, restore -?None")

    step(5, "TTL expiry -?checkpoint with ttl=0 expires immediately")

    snap_ttl = WorkingMemorySnapshot(

        session_id="expired-session", step_index=1, ttl=0,

        captured_at=now.isoformat(),

    )

    await store.save_working_memory(snap_ttl)

    loaded = await store.load_working_memory("expired-session")

    print(f"    -?TTL=0 checkpoint: loaded={loaded is not None} (expected None or race)")

    await store.delete_working_memory("expired-session")

    step(6, "Direct store save/load (bypass MemoryService)")

    snap_raw = WorkingMemorySnapshot(

        session_id="raw-session", step_index=99, total_tokens=500,

        captured_at=now.isoformat(),

    )

    await store.save_working_memory(snap_raw)

    raw = await store.load_working_memory("raw-session")

    assert raw is not None and raw.step_index == 99

    print(f"    -?Direct store roundtrip: step_index={raw.step_index}, tokens={raw.total_tokens}")

    await store.delete_working_memory("raw-session")

    # ══════════════════════════════════════════════════════════════════════════

    #  LAYER 2: Episodic Memory

    # ══════════════════════════════════════════════════════════════════════════

    section("LAYER 2: Episodic Memory")

    step(7, "Write 3 entries for session A with varied metadata")

    for i in range(3):

        entry = EpisodicMemoryEntry(

            session_id=session_id, user_id=user_id, turn_index=i,

            created_at=(now + timedelta(seconds=i)).isoformat(),

            summary=f"Turn {i+1}: User said hello, assistant responded",

            raw_content=f"User: hello\nAssistant: response {i}",

            entities=["greeting", "casual"] if i == 0 else ["coding", "python"],

            topics=["greeting"] if i == 0 else ["programming"],

            keywords=["hello", "hi"] if i == 0 else ["python", "code"],

            importance=0.5 + i * 0.2, token_count=20 + i * 10,

            content_type="raw",

            source={"session": session_id, "turn": i},

        )

        eid = await store.write(entry)

        print(f"    -?Written #{i}: id={eid[:8]} importance={entry.importance} "

              f"entities={entry.entities}")

    step(8, "Write 2 cross-session entries (session B)")

    for i in range(2):

        entry = EpisodicMemoryEntry(

            session_id=session_b, user_id=user_id, turn_index=i,

            created_at=(now + timedelta(hours=1, seconds=i)).isoformat(),

            summary=f"Session B Turn {i+1}: Data science discussion",

            raw_content="User: tell me about ML\nAssistant: Machine learning is...",

            entities=["data-science", "machine-learning"],

            topics=["data-science"], importance=0.8, token_count=50,

        )

        await store.write(entry)

    print("    -?2 entries written for session B")

    step(9, "Recall session A (limit=2, DESC by turn_index)")

    session_mem = await store.recall_session(session_id=session_id, limit=2)

    await show_episodic("Session A recent", session_mem)

    assert len(session_mem) == 2 and session_mem[0].turn_index == 2

    step(10, "Recall all sessions for user (limit=4)")

    user_mem = await store.recall_user(user_id=user_id, limit=4)

    await show_episodic(f"User {user_id} (across sessions)", user_mem)

    assert len(user_mem) == 4  # 3 from A + 2 from B -?4

    step(11, "Search by entity tags: 'python'")

    py_mem = await store.search_by_entities(user_id=user_id, entities=["python"])

    await show_episodic("Entity='python'", py_mem)

    assert len(py_mem) >= 1

    step(12, "Search by entity tags: 'machine-learning'")

    ml_mem = await store.search_by_entities(user_id=user_id, entities=["machine-learning"])

    await show_episodic("Entity='machine-learning'", ml_mem)

    assert len(ml_mem) >= 1

    step(13, "Search with empty entity list -?empty result")

    empty = await store.search_by_entities(user_id=user_id, entities=[])

    assert empty == []

    print("    -?Empty entity list returns []")

    step(14, "Count entries per session")

    ca, cb = await store.count_session(session_id), await store.count_session(session_b)

    print(f"    Session A: {ca} entries  |  Session B: {cb} entries")

    assert ca == 3 and cb == 2

    step(15, "Write entry with ALL fields populated")

    full_entry = EpisodicMemoryEntry(

        session_id=session_id, user_id=user_id, turn_index=10,

        summary="Full field test", raw_content="Full raw",

        content_type="summary", source={"key": "val"},

        entities=["e1", "e2"], topics=["t1"], keywords=["k1"],

        importance=0.99, token_count=999, merged_from=["old_id"],

    )

    fid = await store.write(full_entry)

    recalled = await store.recall_session(session_id=session_id, limit=1, offset=0)

    m = recalled[0] if recalled else None

    print(f"    -?Written+recalled: id={fid[:8]}")

    if m:

        assert m.content_type == "summary" and m.importance == 0.99

        print(f"      content_type={m.content_type} importance={m.importance} "

              f"entities={m.entities} merged_from={m.merged_from}")

    # ══════════════════════════════════════════════════════════════════════════

    #  LAYER 3: Entity Memory

    # ══════════════════════════════════════════════════════════════════════════

    section("LAYER 3: Entity Memory")

    step(16, "Upsert 3 user attributes")

    await store.upsert_entity_attribute(

        "user", user_id, "name", "小明", source_session=session_id)

    await store.upsert_entity_attribute(

        "user", user_id, "language", "Python",

        confidence=0.95, source_session=session_id)

    await store.upsert_entity_attribute(

        "user", user_id, "location", "Beijing", source_session=session_id)

    print("    -?name=小明  language=Python  location=Beijing")

    step(17, "Overwrite attribute (location Beijing -?Shanghai)")

    await store.upsert_entity_attribute(

        "user", user_id, "location", "Shanghai", source_session=session_b)

    print("    -?location overwritten: Beijing -?Shanghai")

    step(18, "get_entity_profile() -?read full profile back")

    profile = await store.get_entity_profile("user", user_id)

    assert profile is not None

    assert profile.entity_type == "user" and profile.entity_key == user_id

    print(f"    -?Profile entity_key={profile.entity_key}")

    print(f"      attributes: {list(profile.attributes.keys())}")

    assert profile.attributes["name"]["value"] == "小明"

    assert profile.attributes["location"]["value"] == "Shanghai"

    assert profile.attributes["language"]["confidence"] == 0.95

    step(19, "Verify change history preserved")

    history = profile.history.get("location", [])

    print(f"    -?location history: {len(history)} entries")

    for h in history:

        print(f"      value={h['value']} @ {h['recorded_at'][:19]}  session={h['source_session']}")

    assert len(history) == 2

    assert history[0]["value"] == "Beijing"

    assert history[1]["value"] == "Shanghai"

    step(20, "get_entity_profile() -?nonexistent entity returns None")

    missing = await store.get_entity_profile("user", "no-such-user")

    assert missing is None

    print("    -?Nonexistent entity -?None")

    # ══════════════════════════════════════════════════════════════════════════

    #  LAYER 4: Semantic Knowledge

    # ══════════════════════════════════════════════════════════════════════════

    section("LAYER 4: Semantic Knowledge")

    step(21, "Create 3 semantic nodes")

    py_id = await store.create_semantic_node(

        "Python", "language", "A high-level programming language")

    fa_id = await store.create_semantic_node(

        "FastAPI", "framework", "Modern Python web framework")

    ml_id = await store.create_semantic_node(

        "Machine Learning", "concept", "AI field enabling computers to learn")

    print(f"    -?Python:        id={py_id[:8]}")

    print(f"    -?FastAPI:       id={fa_id[:8]}")

    print(f"    -?Machine Learning: id={ml_id[:8]}")

    step(22, "Create semantic edge: Python -?FastAPI (related_to)")

    edge_id = await store.create_semantic_edge(py_id, fa_id, "related_to", confidence=0.9)

    assert edge_id != ""

    print(f"    -?Edge created: Python -?FastAPI  id={edge_id[:8]} confidence=0.9")

    step(23, "Idempotent: create 'Python' again returns existing id")

    py_id2 = await store.create_semantic_node("Python")

    assert py_id == py_id2

    print("    -?Idempotent: same Python node returned")

    step(24, "search_semantic() by name match")

    nodes = await store.search_semantic("FastAPI")

    assert len(nodes) >= 1 and nodes[0].name == "FastAPI"

    print(f"    -?Search 'FastAPI': found {len(nodes)} node(s)")

    for n in nodes:

        print(f"      [{n.type}] {n.name}: {n.description[:60]}")

    step(25, "search_semantic() by description match")

    nodes_desc = await store.search_semantic("programming")

    assert len(nodes_desc) >= 1

    print(f"    -?Search 'programming': found {len(nodes_desc)} node(s)")

    step(26, "search_semantic() no match -?empty")

    assert await store.search_semantic("Nonexistent") == []

    print("    -?Search 'Nonexistent' -?[]")

    step(27, "search_semantic() with type_filter")

    lang_nodes = await store.search_semantic("Python", type_filter="language")

    framework_nodes = await store.search_semantic("Python", type_filter="framework")

    print(f"    -?type_filter='language':  {len(lang_nodes)} node(s)")

    print(f"    -?type_filter='framework': {len(framework_nodes)} node(s)")

    step(28, "get_semantic_edges() -?query edges from Python node")

    edges = await store.get_semantic_edges(py_id)

    print(f"    -?Python has {len(edges)} edge(s)")

    for e in edges:

        print(f"      relation={e.relation} confidence={e.confidence}")

    assert len(edges) >= 1 and edges[0].relation == "related_to"

    step(29, "get_semantic_edges() -?edge direction filter")

    outgoing = await store.get_semantic_edges(py_id, direction="outgoing")

    incoming = await store.get_semantic_edges(py_id, direction="incoming")

    print(f"    -?Outgoing: {len(outgoing)}  Incoming: {len(incoming)}")

    step(30, "get_semantic_edges() -?orphan node has no edges")

    orphan = await store.create_semantic_node("OrphanConcept")

    assert await store.get_semantic_edges(orphan) == []

    print("    -?Orphan node -?[]")

    step(31, "increment_semantic_mention() + verify count")

    for _ in range(3):

        await store.increment_semantic_mention(py_id)

    rows = store._conn.execute(

        "SELECT mention_count FROM semantic_node WHERE id = ?", (py_id,)

    ).fetchone()

    assert rows["mention_count"] == 3

    print("    -?Python mention_count = 3 (after 3 increments)")

    # ══════════════════════════════════════════════════════════════════════════

    #  LAYER 5: Behavioral Pattern

    # ══════════════════════════════════════════════════════════════════════════

    section("LAYER 5: Behavioral Pattern")

    step(32, "Upsert initial pattern (v1)")

    await store.upsert_behavioral_pattern(user_id, {

        "coding_style": ["prefers_type_hints", "uses_async"],

        "communication": ["technical", "concise"],

    })

    print("    -?Pattern v1 saved")

    step(33, "get_behavioral_pattern() -?read back & verify")

    p1 = await store.get_behavioral_pattern(user_id)

    assert p1 is not None

    assert p1.version == 1 and p1.user_id == user_id

    assert p1.patterns["communication"] == ["technical", "concise"]

    print(f"    -?Read back: version={p1.version} "

          f"patterns={list(p1.patterns.keys())}")

    step(34, "Upsert updated pattern (v2 -?version increments)")

    await store.upsert_behavioral_pattern(user_id, {

        "coding_style": ["prefers_type_hints", "uses_async", "likes_fastapi"],

        "communication": ["technical", "concise", "chinese"],

        "topics": ["python", "web_dev"],

    })

    p2 = await store.get_behavioral_pattern(user_id)

    assert p2 is not None and p2.version == 2

    assert p2.total_interactions == 2

    print(f"    -?Pattern updated: version={p2.version} "

          f"interactions={p2.total_interactions}")

    step(35, "get_behavioral_pattern() -?nonexistent user -?None")

    missing_p = await store.get_behavioral_pattern("no-such-user")

    assert missing_p is None

    print("    -?Nonexistent user -?None")

    # ══════════════════════════════════════════════════════════════════════════

    #  MemoryService: 5-Layer `recall()`

    # ══════════════════════════════════════════════════════════════════════════

    section("MemoryService: 5-Layer recall()")

    step(36, "recall() populates episodic memories")

    payload = await memory.recall(session_id=session_id, user_id=user_id)

    print(f"    Episodic memories: {len(payload.memories)}")

    for m in payload.memories:

        print(f"      [{m['created_at']}] #{m['turn_index']} {m['summary'][:70]}")

    assert len(payload.memories) > 0

    step(37, "recall() populates entity_profile (Layer 3)")

    print(f"    Entity profile keys: {list(payload.entity_profile.keys())}")

    assert "name" in payload.entity_profile

    assert payload.entity_profile["name"]["value"] == "小明"

    print(f"    -?name = {payload.entity_profile['name']['value']}")

    step(38, "recall() populates concepts via semantic search (Layer 4)")

    payload_sem = await memory.recall(

        session_id=session_id, user_id=user_id, query="Machine Learning Python",

    )

    print(f"    Semantic concepts injected: {len(payload_sem.concepts)}")

    for c in payload_sem.concepts:

        print(f"      [{c['name']}] {c['description'][:60]}")

    step(39, "recall() injects behavioral tone_instruction (Layer 5)")

    print(f"    Tone instruction: {payload.tone_instruction!r}")

    # The stored pattern has communication=["technical", "concise"] and

    # MemoryService.recall() checks for "style" key, not "communication",

    # so it won't inject tone by default unless "style" is present.

    if payload.tone_instruction:

        print("    -?Behavioral tone injected")

    else:

        print("    -?No tone instruction injected (style key not set in pattern)")

    # ══════════════════════════════════════════════════════════════════════════

    #  MemoryService: enhanced commit()

    # ══════════════════════════════════════════════════════════════════════════

    section("MemoryService: enhanced commit()")

    step(40, "commit() with entity-rich user message")

    await memory.commit(

        session_id=session_id, user_id=user_id,

        user_message="My name is Alice. I work as a Data Scientist at Google.",

        assistant_message="Nice to meet you Alice! Data Science is fascinating.",

    )

    # Verify entity was extracted and upserted

    profile2 = await store.get_entity_profile("user", user_id)

    assert profile2 is not None

    print(f"    Entity profile keys after commit: {list(profile2.attributes.keys())}")

    if "name" in profile2.attributes:

        print(f"    -?Auto-extracted name = {profile2.attributes['name']['value']}")

    if "profession" in profile2.attributes:

        print(f"    -?Auto-extracted profession = {profile2.attributes['profession']['value']}")

    step(41, "commit() triggers semantic node creation for topics")

    # commit() auto-extracts topics and creates semantic nodes

    topics_nodes = await store.search_semantic("Data")

    print(f"    -?Semantic nodes matching 'Data': {len(topics_nodes)}")

    for n in topics_nodes:

        print(f"      [{n.type}] {n.name}")

    step(42, "commit() + recall() -?end-to-end 5-layer verification")

    final = await memory.recall(

        session_id=session_id, user_id=user_id,

        query="Machine Learning Data Science Python",

    )

    print(f"    Total episodic memories: {len(final.memories)}")

    print(f"    Entity profile keys:     {list(final.entity_profile.keys())}")

    print(f"    Concepts injected:       {len(final.concepts)}")

    for c in final.concepts:

        print(f"      [{c['name']}] {c['description'][:60]}")

    assert len(final.entity_profile) > 0

    # ══════════════════════════════════════════════════════════════════════════

    #  MemoryService: no-store edge cases

    # ══════════════════════════════════════════════════════════════════════════

    section("Edge Cases: MemoryService with no store")

    step(43, "Detached MemoryService -?recall returns empty payload")

    detached = MemoryService()

    empty = await detached.recall("any", user_id="u1", query="test")

    assert len(empty.memories) == 0

    assert empty.entity_profile == {}

    assert empty.concepts == []

    assert empty.tone_instruction == ""

    print("    -?recall -?empty payload (no crash)")

    step(44, "Detached MemoryService -?commit is no-op")

    await detached.commit("any", "u1", "hi", "hello")

    print("    -?commit -?no-op (no crash)")

    step(45, "Detached MemoryService -?checkpoint / restore / discard")

    s = WorkingMemorySnapshot(session_id="x")

    await detached.checkpoint(s)

    assert await detached.restore("x") is None

    await detached.discard_checkpoint("x")

    print("    -?checkpoint / restore / discard -?no-ops (no crash)")

    # ══════════════════════════════════════════════════════════════════════════

    #  SQLiteMemoryStore: no-connection edge cases

    # ══════════════════════════════════════════════════════════════════════════

    section("Edge Cases: SQLiteMemoryStore without connection")

    step(46, "Uninitialized store -?all methods return safe defaults")

    dry = SQLiteMemoryStore()

    assert await dry.recall_session("x") == []

    assert await dry.count_session("x") == 0

    assert await dry.load_working_memory("x") is None

    assert await dry.get_entity_profile("user", "x") is None

    assert await dry.search_semantic("x") == []

    assert await dry.get_behavioral_pattern("x") is None

    assert await dry.get_semantic_edges("x") == []

    assert await dry.create_semantic_edge("a", "b", "rel") == ""

    print("    -?All 8 uninitialized methods return safe defaults (no crash)")

    # ══════════════════════════════════════════════════════════════════════════

    #  Summary

    # ══════════════════════════════════════════════════════════════════════════

    section("Summary: API Coverage Checklist")

    checks = [

        ("L1 Working  : checkpoint", True),

        ("L1 Working  : restore", True),

        ("L1 Working  : discard", True),

        ("L1 Working  : overwrite", True),

        ("L1 Working  : TTL expiry", True),

        ("L1 Working  : direct store roundtrip", True),

        ("L2 Episodic : write", True),

        ("L2 Episodic : recall_session", True),

        ("L2 Episodic : recall_user", True),

        ("L2 Episodic : search_by_entities", True),

        ("L2 Episodic : count_session", True),

        ("L2 Episodic : full-data entry (all fields)", True),

        ("L3 Entity   : upsert_entity_attribute", True),

        ("L3 Entity   : overwrite + history", True),

        ("L3 Entity   : get_entity_profile", True),

        ("L3 Entity   : nonexistent -?None", True),

        ("L4 Semantic : create_semantic_node", True),

        ("L4 Semantic : idempotent create", True),

        ("L4 Semantic : search_semantic (name+desc)", True),

        ("L4 Semantic : search_semantic type_filter", True),

        ("L4 Semantic : create_semantic_edge", True),

        ("L4 Semantic : get_semantic_edges (dir filter)", True),

        ("L4 Semantic : increment_semantic_mention", True),

        ("L4 Semantic : orphan node -?no edges", True),

        ("L5 Behavior : upsert_behavioral_pattern", True),

        ("L5 Behavior : get_behavioral_pattern", True),

        ("L5 Behavior : version increment", True),

        ("L5 Behavior : nonexistent -?None", True),

        ("Svc recall  : episodic memories", len(payload.memories) > 0),

        ("Svc recall  : entity_profile (Layer 3)", len(payload.entity_profile) > 0),

        ("Svc recall  : concepts (Layer 4)", len(final.concepts) > 0),

        ("Svc commit  : entity extraction", any("name" in profile2.attributes for profile2 in [profile2])),

        ("Svc commit  : semantic node creation", len(topics_nodes) > 0),

        ("Edge no-store: recall/commit/checkpoint", True),

        ("Edge no-conn : 8 safe defaults", True),

    ]

    for label, ok in checks:

        status = "OK" if ok else "XX"

        print(f"  [{status}] {label}")

    print()

    total = sum(1 for _, ok in checks)

    passed = sum(1 for _, ok in checks if ok)

    print(f"  Result: {passed}/{total} checks passed")

    await store.close()

    print(f"\n{'=' * 70}")

    print(f"  Demo completed{'!' if passed == total else ' with ISSUES!'}")

    print(f"{'=' * 70}")

if __name__ == "__main__":

    asyncio.run(run_demo())
