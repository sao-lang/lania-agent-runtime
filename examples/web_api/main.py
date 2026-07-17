"""
FastAPI web application for Lania Agent Runtime.

Provides three API groups:
  POST /chat/single       - Single-turn dialogue
  POST /chat/multi        - Multi-turn dialogue (session-based)
  POST /chat/stream       - Streaming output (SSE)

Usage:
    cd examples/web_api
    uv run uvicorn main:app --reload
"""

from __future__ import annotations

import json
import uuid
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from openai import AsyncOpenAI
from pydantic import BaseModel

from lania_agent_runtime.executor import LLMExecutor
from lania_agent_runtime.models import LLMExecutorConfig
from lania_agent_runtime.memory import GenericMemoryStore, MemoryService
from lania_agent_runtime.memory.backends import SQLiteBackend
from lania_agent_runtime.runtime import AgentRuntime

# ── Request/Response Models ──


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    user_id: str | None = None
    system_prompt: str | None = None


class ChatResponse(BaseModel):
    content: str
    session_id: str
    finish_reason: str


class SessionState(BaseModel):
    session_id: str
    message_count: int
    step_count: int
    total_tokens: int
    status: str


# ── FastAPI App ──

app = FastAPI(
    title="Lania Agent Runtime API",
    description="Agent runtime with single-turn, multi-turn, and streaming APIs",
    version="0.1.0",
)

# In-memory session store
_sessions: dict[str, AgentRuntime] = {}
_default_config: LLMExecutorConfig | None = None
_default_client: AsyncOpenAI | None = None
_default_memory: MemoryService | None = None


def _get_config() -> LLMExecutorConfig:
    global _default_config
    if _default_config is None:
        _default_config = LLMExecutorConfig(
            model="deepseek-chat",
            temperature=0.7,
            max_tokens=4096,
        )
    return _default_config


def _get_client() -> AsyncOpenAI:
    global _default_client
    if _default_client is None:
        _default_client = AsyncOpenAI(
            api_key="sk-9c2fb6996ebf4387ba299d8048dd4070",
            base_url="https://api.deepseek.com",
        )
    return _default_client


def _get_memory() -> MemoryService:
    global _default_memory
    if _default_memory is None:
        store = GenericMemoryStore(SQLiteBackend())
        import asyncio

        asyncio.get_event_loop().run_until_complete(store.initialize())
        _default_memory = MemoryService(store=store)
    return _default_memory


def _get_or_create_runtime(session_id: str | None = None) -> AgentRuntime:
    if session_id and session_id in _sessions:
        return _sessions[session_id]

    sid = session_id or f"session-{uuid.uuid4().hex[:8]}"
    config = _get_config()
    client = _get_client()
    memory = _get_memory()
    executor = LLMExecutor(client=client, config=config)

    runtime = AgentRuntime(
        session_id=sid,
        agent_id="lania-agent",
        llm_executor=executor,
        memory=memory,
        config=config,
    )
    _sessions[sid] = runtime
    return runtime


# ── API: Single-turn ──


@app.post("/chat/single", response_model=ChatResponse)
async def chat_single(req: ChatRequest) -> ChatResponse:
    """Single-turn dialogue: one-shot session, no history retained."""
    print(f"\n[chat/single] >>> {req.message}")
    runtime = _get_or_create_runtime()
    try:
        result = await runtime.run(
            req.message,
            system_prompt=req.system_prompt or "You are a helpful assistant.",
        )
        await runtime.destroy()
        _sessions.pop(runtime.session_id, None)
        print(f"[chat/single] <<< {result.content}")
        return ChatResponse(
            content=result.content,
            session_id=result.session_id,
            finish_reason=result.finish_reason,
        )
    except Exception as e:
        print(f"[chat/single] ERROR: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── API: Multi-turn ──


@app.post("/chat/multi", response_model=ChatResponse)
async def chat_multi(req: ChatRequest) -> ChatResponse:
    """Multi-turn dialogue: maintains session context."""
    if not req.session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    print(f"\n[chat/multi] [{req.session_id}] >>> {req.message}")
    runtime = _get_or_create_runtime(req.session_id)
    try:
        result = await runtime.run(req.message, system_prompt=req.system_prompt)
        print(f"[chat/multi] [{req.session_id}] <<< {result.content}")
        return ChatResponse(
            content=result.content,
            session_id=result.session_id,
            finish_reason=result.finish_reason,
        )
    except Exception as e:
        print(f"[chat/multi] ERROR: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── API: Multi-turn with Memory ──


@app.post("/chat/multi/memory", response_model=ChatResponse)
async def chat_multi_memory(req: ChatRequest) -> ChatResponse:
    """Multi-turn dialogue with memory recall."""
    if not req.session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    print(f"\n[chat/multi/memory] [{req.session_id}] >>> {req.message}")
    runtime = _get_or_create_runtime(req.session_id)
    try:
        memories = await runtime.memory.recall(
            session_id=req.session_id, user_id=req.user_id, query=req.message
        )
        if memories.memories:
            runtime.context.context_payload.memories = memories.memories

        result = await runtime.run(
            req.message, user_id=req.user_id, system_prompt=req.system_prompt
        )
        print(f"[chat/multi/memory] [{req.session_id}] <<< {result.content}")
        return ChatResponse(
            content=result.content,
            session_id=result.session_id,
            finish_reason=result.finish_reason,
        )
    except Exception as e:
        print(f"[chat/multi/memory] ERROR: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── API: Streaming ──


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest) -> StreamingResponse:
    """Streaming dialogue via SSE."""
    sid = req.session_id or f"stream-{uuid.uuid4().hex[:8]}"
    print(f"\n[chat/stream] [{sid}] >>> {req.message}")
    runtime = _get_or_create_runtime(sid)

    async def _stream() -> AsyncIterator[str]:
        full_content = ""
        try:
            async for event in runtime.run_stream(
                req.message,
                system_prompt=req.system_prompt or "You are a helpful assistant.",
            ):
                if event.type == "text":
                    full_content += event.content
                    yield f"data: {json.dumps({'type': 'text', 'content': event.content})}\n\n"
                elif event.type == "error":
                    yield f"data: {json.dumps({'type': 'error', 'content': event.content})}\n\n"
                elif event.type == "done":
                    print(f"[chat/stream] [{sid}] <<< {full_content}")
                    yield f"data: {json.dumps({'type': 'done', 'session_id': runtime.session_id})}\n\n"
        except Exception as e:
            print(f"[chat/stream] ERROR: {e}")
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")


# ── Session Management ──


@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str) -> dict:
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    await _sessions[session_id].destroy()
    del _sessions[session_id]
    return {"status": "deleted", "session_id": session_id}


@app.get("/sessions", response_model=list[SessionState])
async def list_sessions() -> list[SessionState]:
    states: list[SessionState] = []
    for sid, runtime in _sessions.items():
        s = runtime.get_session_state()
        states.append(
            SessionState(
                session_id=sid,
                message_count=s.message_count,
                step_count=s.step_count,
                total_tokens=s.total_tokens,
                status=s.status.value,
            )
        )
    return states


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "active_sessions": len(_sessions)}
