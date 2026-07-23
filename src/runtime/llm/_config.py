"""
LLMExecutor 配置模块——LLMExecutorConfig 定义。

构造参数，不进 Runtime 内存，仅构造时使用。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LLMExecutorConfig:
    """LLMExecutor 构造参数。

    安全约束：api_key 和 api_base 不进 Runtime，仅构造时使用。

    Attributes:
        model: 模型名称（默认 "gpt-4o"）。
        temperature: 采样温度（默认 0.7）。
        max_tokens: 最大输出 token 数（默认 4096）。
        timeout: API 调用超时秒数（默认 60.0）。
        max_retries: 最大重试次数（默认 3）。
        retry_backoff_base: 指数退避基数秒数（默认 1.0）。
        retry_backoff_max: 最大退避秒数（默认 30.0）。
        api_key: API 密钥（仅构造时使用）。
        api_base: OpenAI-compatible base URL（仅构造时使用）。
        stream: 是否默认启用流式（默认 False）。
        extra_headers: 额外的 HTTP 请求头。
        extra_body: 额外的请求体参数。
    """

    model: str = "gpt-4o"
    """模型名称。"""

    temperature: float = 0.7
    """采样温度。"""

    max_tokens: int = 4096
    """最大输出 token 数。"""

    timeout: float = 60.0
    """API 调用超时秒数。"""

    max_retries: int = 3
    """最大重试次数。"""

    retry_backoff_base: float = 1.0
    """指数退避基数秒数。"""

    retry_backoff_max: float = 30.0
    """最大退避秒数。"""

    api_key: str = ""
    """API 密钥（仅构造时使用，不进 Runtime）。"""

    api_base: str = ""
    """OpenAI-compatible base URL（仅构造时使用）。"""

    stream: bool = False
    """是否默认启用流式。"""

    extra_headers: dict[str, str] = field(default_factory=dict)
    """额外的 HTTP 请求头。"""

    extra_body: dict[str, object] = field(default_factory=dict)
    """额外的请求体参数。"""

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "LLMExecutorConfig":
        """从字典创建配置。

        允许从 RuntimeConfig.llm 等字典源构造。

        Args:
            data: 配置字典。

        Returns:
            LLMExecutorConfig 实例。
        """
        return cls(
            model=str(data.get("model", "gpt-4o")),
            temperature=float(data.get("temperature", 0.7)),
            max_tokens=int(data.get("max_tokens", 4096)),
            timeout=float(data.get("timeout", 60.0)),
            max_retries=int(data.get("max_retries", 3)),
            retry_backoff_base=float(data.get("retry_backoff_base", 1.0)),
            retry_backoff_max=float(data.get("retry_backoff_max", 30.0)),
            api_key=str(data.get("api_key", "")),
            api_base=str(data.get("api_base", "")),
            stream=bool(data.get("stream", False)),
            extra_headers=dict(data.get("extra_headers", {})),
            extra_body=dict(data.get("extra_body", {})),
        )
