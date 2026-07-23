"""
OpenAI LLMExecutor 实现——OpenAILLMExecutor。

OpenAI / OpenAI-compatible API 的 LLMExecutor 实现。
支持：
  - GPT-4o / GPT-4 / GPT-3.5 / DeepSeek / Qwen 等兼容 API
  - Function calling / tool_calls
  - 流式与非流式
  - 指数退避重试
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from openai import APIError, APITimeoutError, RateLimitError

from src.runtime.llm._config import LLMExecutorConfig
from src.runtime.llm._errors import LLMExecutionError
from src.runtime.llm._executors._stream import AsyncStreamCollector
from src.runtime.llm._interfaces import StreamableLLMExecutor
from src.runtime.llm._models import FinishReason, LLMResponse, LLMUsage, ToolCall
from src.runtime.llm._providers._openai import OpenAIProvider

if TYPE_CHECKING:
    from src.runtime.context._context import RuntimeContext


class OpenAILLMExecutor(StreamableLLMExecutor):
    """OpenAI / OpenAI-compatible API 的 LLMExecutor 实现。

    通过组合模式持有 OpenAIProvider，而非继承。
    支持流式与非流式，自动处理重试和错误包装。

    使用方式：
        config = LLMExecutorConfig(model="gpt-4o", api_key="sk-...")
        executor = OpenAILLMExecutor(config)
        response = await executor.execute(ctx)

    流式方式：
        collector, response = await executor.execute_stream(ctx)
        print(collector.full_content)
    """

    # 可重试的 OpenAI 异常类型
    RETRYABLE_ERRORS: tuple[type[Exception], ...] = (
        APITimeoutError,
        RateLimitError,
        APIError,
    )

    def __init__(
        self,
        config: LLMExecutorConfig,
        provider: OpenAIProvider | None = None,
    ) -> None:
        """初始化 OpenAILLMExecutor。

        Args:
            config: LLMExecutor 配置。
            provider: OpenAIProvider 实例（不提供则自动创建）。
        """
        self._config = config
        self._provider = provider or OpenAIProvider(
            api_key=config.api_key,
            api_base=config.api_base,
            timeout=config.timeout,
            max_retries=0,  # 由 LLMExecutor 控制重试
            extra_headers=config.extra_headers or None,
            default_model=config.model,
        )

    # ============ LLMExecutor 接口 ============

    async def execute(self, ctx: RuntimeContext) -> LLMResponse:
        """执行 LLM 调用（非流式）。

        流程：
          1. 从 ctx 提取 messages 并序列化
          2. 合并参数（ctx 覆盖默认配置）
          3. 获取 tools schema
          4. 调用 Provider（含指数退避重试）
          5. 转换响应为 LLMResponse

        Args:
            ctx: RuntimeContext 实例。

        Returns:
            LLMResponse 实例。

        Raises:
            LLMExecutionError: 重试耗尽后抛出。
        """
        messages = self._extract_messages(ctx)
        params = self._merge_params(ctx)
        tools_schema = self._get_tools_schema(ctx)

        last_error: Exception | None = None

        for attempt in range(self._config.max_retries + 1):
            try:
                raw = await self._provider.chat(
                    messages=messages,
                    model=params.model,
                    temperature=params.temperature,
                    max_tokens=params.max_tokens,
                    tools=tools_schema,
                    stream=False,
                )
                # 非流式下返回 LLMProviderResponse
                return self._to_response(raw, params.model)  # type: ignore[arg-type]

            except self.RETRYABLE_ERRORS as e:
                last_error = e
                if attempt < self._config.max_retries:
                    backoff = min(
                        self._config.retry_backoff_base * (2**attempt),
                        self._config.retry_backoff_max,
                    )
                    import asyncio

                    await asyncio.sleep(backoff)
                    continue

                raise LLMExecutionError(
                    last_error=last_error,
                    consecutive_errors=ctx.step_index,
                    model=params.model,
                )

    # ============ StreamableLLMExecutor 接口 ============

    async def execute_stream(
        self,
        ctx: RuntimeContext,
    ) -> tuple[AsyncStreamCollector, LLMResponse]:
        """流式执行 LLM 调用。

        流程：
          1. 从 ctx 提取 messages 并序列化
          2. 合并参数
          3. 获取 tools schema
          4. 调用 Provider（流式模式）
          5. 逐 chunk 收集到 AsyncStreamCollector
          6. 组装最终 LLMResponse

        Args:
            ctx: RuntimeContext 实例。

        Returns:
            - collector: 流收集器（含逐 chunk 的累积数据）。
            - final_response: 完整组装后的 LLMResponse。
        """
        messages = self._extract_messages(ctx)
        params = self._merge_params(ctx)
        tools_schema = self._get_tools_schema(ctx)

        stream = await self._provider.chat(
            messages=messages,
            model=params.model,
            temperature=params.temperature,
            max_tokens=params.max_tokens,
            tools=tools_schema,
            stream=True,
        )

        collector = AsyncStreamCollector()
        # stream 是 AsyncIterator[dict]
        async for chunk in stream:  # type: ignore[union-attr]
            collector.collect(chunk)

        assembled = collector.assemble()
        final_response = self._to_response(assembled, params.model)

        return collector, final_response

    # ============ 内部方法 ============

    def _extract_messages(self, ctx: RuntimeContext) -> list[dict]:
        """从 ctx.messages 提取 LLM API 格式的消息。

        将 RuntimeContext 中的不可变消息元组转换为
        OpenAI API 可消费的 dict 列表。

        Args:
            ctx: RuntimeContext 实例。

        Returns:
            符合 LLM API 格式的消息列表。
        """
        return [self._serialize_message(msg) for msg in ctx.messages]

    def _serialize_message(self, msg: dict[str, Any]) -> dict[str, Any]:
        """单条消息序列化为 OpenAI API 格式。

        Args:
            msg: Runtime 侧的消息字典。

        Returns:
            OpenAI API 格式的消息字典。
        """
        d: dict[str, Any] = {"role": msg.get("role", "user")}

        content = msg.get("content")
        if content is not None and content != "":
            d["content"] = content
        elif msg.get("role") == "tool":
            # tool 消息必须有 content
            d["content"] = str(content) if content is not None else ""

        tool_calls = msg.get("tool_calls")
        if tool_calls:
            d["tool_calls"] = [
                {
                    "id": tc.get("id", tc.get("tool_call_id", "")),
                    "type": "function",
                    "function": {
                        "name": tc.get("name", tc.get("function", {}).get("name", "")),
                        "arguments": self._encode_arguments(tc),
                    },
                }
                for tc in tool_calls
            ]

        tool_call_id = msg.get("tool_call_id")
        if tool_call_id:
            d["tool_call_id"] = tool_call_id
            if "content" not in d:
                d["content"] = msg.get("content", "")

        return d

    def _encode_arguments(self, tc: dict[str, Any]) -> str:
        """将 tool_call 的 arguments 序列化为 JSON 字符串。

        支持两种格式：
          - 已序列化字符串：直接使用
          - dict 格式：json.dumps

        Args:
            tc: tool_call 字典。

        Returns:
            JSON 字符串。
        """
        function = tc.get("function", tc)
        if isinstance(function, dict):
            args = function.get("arguments", "{}")
            if isinstance(args, dict):
                return json.dumps(args)
            return str(args)
        return "{}"

    def _merge_params(self, ctx: RuntimeContext) -> LLMExecutorConfig:
        """合并参数——ctx 配置覆盖默认配置。

        当前实现返回 self._config 的副本。
        RuntimeContext 不包含 llm_config 字段，
        LLM 配置通过 LLMExecutorConfig 在构造时注入。
        如需按 step 调整参数，请在 before_llm Transform 中
        通过 ctx.services 传递。

        Args:
            ctx: RuntimeContext 实例。

        Returns:
            LLMExecutorConfig 实例。
        """
        # 从 services 中读取运行时覆盖参数
        overrides = ctx.services.get("llm_config_overrides", {})
        if not overrides:
            return self._config

        # 返回新配置（保留原始 api_key/api_base）
        return LLMExecutorConfig(
            model=overrides.get("model", self._config.model),
            temperature=overrides.get("temperature", self._config.temperature),
            max_tokens=overrides.get("max_tokens", self._config.max_tokens),
            timeout=overrides.get("timeout", self._config.timeout),
            max_retries=overrides.get("max_retries", self._config.max_retries),
            retry_backoff_base=overrides.get("retry_backoff_base", self._config.retry_backoff_base),
            retry_backoff_max=overrides.get("retry_backoff_max", self._config.retry_backoff_max),
            api_key=self._config.api_key,
            api_base=self._config.api_base,
            stream=overrides.get("stream", self._config.stream),
        )

    def _get_tools_schema(self, ctx: RuntimeContext) -> list[dict] | None:
        """从 Runtime 获取已注册工具的 JSON Schema。

        工具 schema 由 ToolDispatcher 注入到 ctx.services["tool_dispatcher"]，
        或通过 ctx.services["tools_schema"] 直接传递。

        Args:
            ctx: RuntimeContext 实例。

        Returns:
            工具的 JSON Schema 列表，None 表示不传 tools。
        """
        # 优先从 services 直接获取 schema
        tools_schema = ctx.services.get("tools_schema")
        if tools_schema is not None:
            return tools_schema

        # 其次通过 tool_dispatcher 获取
        dispatcher = ctx.services.get("tool_dispatcher")
        if dispatcher is not None:
            # 兼容两种接口：all_tools() 或 get_tools_schema()
            if hasattr(dispatcher, "all_tools"):
                return dispatcher.all_tools()
            if hasattr(dispatcher, "get_tools_schema"):
                return dispatcher.get_tools_schema()

        return None

    def _to_response(
        self,
        raw: Any,
        model: str,
    ) -> LLMResponse:
        """OpenAI 原始响应 → 统一 LLMResponse。

        Args:
            raw: OpenAI 原始响应（ChatCompletion 对象或 assemble() 后的 dict）。
            model: 模型名称（备选）。

        Returns:
            LLMResponse 实例。
        """
        # 处理 dict 格式（由 stream collector assemble 产生）
        if isinstance(raw, dict):
            return self._dict_to_response(raw, model)

        # 处理 SDK 对象格式
        choice = raw.choices[0]
        raw_tool_calls = getattr(choice.message, "tool_calls", None) or []

        tool_calls_list: list[ToolCall] = []
        for tc in raw_tool_calls:
            tool_calls_list.append(
                ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=json.loads(tc.function.arguments),
                    raw_arguments=tc.function.arguments,
                )
            )

        finish_raw = getattr(choice, "finish_reason", None) or "error"
        finish_reason = self._parse_finish_reason(str(finish_raw))

        usage_raw = getattr(raw, "usage", None)
        usage = LLMUsage()
        if usage_raw:
            usage = LLMUsage(
                prompt_tokens=getattr(usage_raw, "prompt_tokens", 0),
                completion_tokens=getattr(usage_raw, "completion_tokens", 0),
            )

        return LLMResponse(
            content=choice.message.content or "",
            tool_calls=tool_calls_list,
            usage=usage,
            finish_reason=finish_reason,
            model=getattr(raw, "model", None) or model,
        )

    def _dict_to_response(self, raw: dict[str, Any], model: str) -> LLMResponse:
        """从字典格式的响应构造 LLMResponse。

        主要用于流式 collector.assemble() 后的数据。

        Args:
            raw: 响应字典。
            model: 模型名称（备选）。

        Returns:
            LLMResponse 实例。
        """
        choices = raw.get("choices", [])
        if not choices:
            return LLMResponse(model=model)

        choice = choices[0]
        message = choice.get("message", {})

        content = message.get("content") or ""

        raw_tool_calls = message.get("tool_calls") or []
        tool_calls_list: list[ToolCall] = []
        for tc in raw_tool_calls:
            func = tc.get("function", {})
            args_str = func.get("arguments", "{}")
            try:
                arguments = json.loads(args_str) if isinstance(args_str, str) else args_str
            except json.JSONDecodeError:
                arguments = {"_raw": args_str}
            tool_calls_list.append(
                ToolCall(
                    id=tc.get("id", ""),
                    name=func.get("name", ""),
                    arguments=arguments,
                    raw_arguments=args_str if isinstance(args_str, str) else json.dumps(args_str),
                )
            )

        finish_raw = choice.get("finish_reason", "stop") or "stop"
        finish_reason = self._parse_finish_reason(str(finish_raw))

        usage_raw = raw.get("usage") or {}
        usage = LLMUsage(
            prompt_tokens=usage_raw.get("prompt_tokens", 0),
            completion_tokens=usage_raw.get("completion_tokens", 0),
        )

        return LLMResponse(
            content=content,
            tool_calls=tool_calls_list,
            usage=usage,
            finish_reason=finish_reason,
            model=raw.get("model", "") or model,
        )

    def _parse_finish_reason(self, reason: str) -> FinishReason:
        """将字符串结束原因解析为 FinishReason 枚举。

        Args:
            reason: 字符串格式的结束原因。

        Returns:
            FinishReason 枚举值。
        """
        reason_lower = reason.lower().strip()
        for fr in FinishReason:
            if fr.value == reason_lower:
                return fr
        # 兼容 OpenAI 的 "function_call" → "tool_calls"
        if reason_lower in ("function_call",):
            return FinishReason.TOOL_CALLS
        return FinishReason.ERROR
