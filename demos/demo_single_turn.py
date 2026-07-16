"""
Demo 1: Single-turn dialogue with DeepSeek.

Usage:
    uv run python demos/demo_single_turn.py
"""

import asyncio

from openai import AsyncOpenAI

from lania_agent_runtime.executor import LLMExecutor, LLMExecutorConfig
from lania_agent_runtime.runtime import AgentRuntime


async def main() -> None:
    print("=" * 60)
    print("Demo 1: Single-turn Dialogue with DeepSeek")
    print("=" * 60)

    config = LLMExecutorConfig(
        model="deepseek-chat",
        temperature=0.7,
        max_tokens=4096,
    )

    client = AsyncOpenAI(
        api_key="sk-9c2fb6996ebf4387ba299d8048dd4070",
        base_url="https://api.deepseek.com",
    )
    executor = LLMExecutor(client=client, config=config)
    runtime = AgentRuntime(
        session_id="demo-single",
        agent_id="demo-agent",
        llm_executor=executor,
        config=config,
    )

    user_input = "你好！请用中文介绍一下你自己。"
    print(f"\nUser: {user_input}")

    result = await runtime.run(
        user_input,
        system_prompt="You are a helpful assistant. Always respond in Chinese.",
    )

    print(f"\nAssistant: {result.content}")
    print("\n--- Stats ---")
    print(f"Session: {result.session_id}")
    print(f"Tokens used: {result.usage.total_tokens}")
    print(f"Finish reason: {result.finish_reason}")

    await runtime.destroy()
    print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
