"""
全局配置模块——RuntimeConfig。

支持多源加载：字典、环境变量、YAML/TOML 文件。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class RuntimeConfig:
    """
    Runtime 全局配置——多源加载。

    支持从 dict、环境变量和文件（YAML/TOML）加载配置。

    Attributes:
        system_prompt: 系统提示词模板。
        llm: LLM 配置（model, api_key, base_url, max_tokens 等）。
        loop: Step loop 配置（strategy, max_steps, max_replans 等）。
        memory: 记忆系统配置（backend, path 等）。
        services: 外部服务配置字典。
        plugins: 要加载的插件列表（plugin_name: config_dict）。
        hooks: 自定义 hook 配置。
        timeout: 超时配置（step_timeout_ms, total_timeout_ms）。
        budget: 预算配置（token_limit, step_limit, max_cost_cents）。
    """

    system_prompt: str = ""
    """系统提示词模板。"""

    llm: dict[str, Any] = field(default_factory=dict)
    """LLM 配置（model, api_key, base_url, max_tokens 等）。"""

    loop: dict[str, Any] = field(default_factory=dict)
    """Step loop 配置（strategy, max_steps, max_replans 等）。"""

    memory: dict[str, Any] = field(default_factory=dict)
    """记忆系统配置（backend, path 等）。"""

    services: dict[str, Any] = field(default_factory=dict)
    """外部服务配置字典。"""

    plugins: dict[str, dict[str, Any]] = field(default_factory=dict)
    """要加载的插件列表（plugin_name: config_dict）。"""

    hooks: dict[str, Any] = field(default_factory=dict)
    """自定义 hook 配置。"""

    timeout: dict[str, int] = field(
        default_factory=lambda: {
            "step_timeout_ms": 60_000,
            "total_timeout_ms": 600_000,
        }
    )
    """超时配置（step_timeout_ms, total_timeout_ms）。"""

    budget: dict[str, int] = field(
        default_factory=lambda: {
            "token_limit": 100_000,
            "step_limit": 50,
            "max_cost_cents": 1000,
        }
    )
    """预算配置（token_limit, step_limit, max_cost_cents）。"""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RuntimeConfig":
        """
        从字典加载配置。

        Args:
            data: 配置字典。

        Returns:
            RuntimeConfig 实例。
        """
        return cls(
            system_prompt=data.get("system_prompt", ""),
            llm=data.get("llm", {}),
            loop=data.get("loop", {}),
            memory=data.get("memory", {}),
            services=data.get("services", {}),
            plugins=data.get("plugins", {}),
            hooks=data.get("hooks", {}),
            timeout=data.get(
                "timeout",
                {
                    "step_timeout_ms": 60_000,
                    "total_timeout_ms": 600_000,
                },
            ),
            budget=data.get(
                "budget",
                {
                    "token_limit": 100_000,
                    "step_limit": 50,
                    "max_cost_cents": 1000,
                },
            ),
        )

    @classmethod
    def from_env(cls, prefix: str = "AGENT_") -> "RuntimeConfig":
        """
        从环境变量加载配置。

        环境变量命名约定：
          AGENT_SYSTEM_PROMPT=...           → 顶级字段
          AGENT_LLM__MODEL=gpt-4o           → 双层：section__key
          AGENT_LLM__API_KEY=sk-...         → 双层
          AGENT_LOOP__STRATEGY=react         → 双层
          AGENT_BUDGET__TOKEN_LIMIT=50000   → 双层

        Args:
            prefix: 环境变量前缀，默认 "AGENT_"。

        Returns:
            RuntimeConfig 实例。
        """
        import os

        # 已知的 section 名称（用于兼容旧版单下划线命名）
        known_sections = {
            "llm",
            "loop",
            "memory",
            "services",
            "plugins",
            "hooks",
            "timeout",
            "budget",
        }

        data: dict[str, Any] = {}
        for key, value in os.environ.items():
            if not key.startswith(prefix):
                continue
            rest = key[len(prefix) :].lower()

            # 优先尝试双下划线分隔 section__key
            if "__" in rest:
                section, sub_key = rest.split("__", 1)
                if section not in data:
                    data[section] = {}
                if isinstance(data[section], dict):
                    data[section][sub_key] = _parse_env_value(value)
            else:
                # 单下划线：判断是否为已知 section
                parts = rest.split("_", 1)
                if len(parts) == 2 and parts[0] in known_sections:
                    section, sub_key = parts
                    if section not in data:
                        data[section] = {}
                    if isinstance(data[section], dict):
                        data[section][sub_key] = _parse_env_value(value)
                else:
                    # 顶级字段
                    data[rest] = _parse_env_value(value)

        return cls.from_dict(data)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "RuntimeConfig":
        """
        从 YAML 文件加载配置。

        Args:
            path: YAML 文件路径。

        Returns:
            RuntimeConfig 实例。

        Raises:
            FileNotFoundError: 如果文件不存在。
            ImportError: 如果未安装 PyYAML。
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"配置文件不存在: {path}")

        try:
            import yaml
        except ImportError:
            raise ImportError("加载 YAML 配置需要安装 PyYAML: pip install pyyaml")

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        return cls.from_dict(data or {})

    @classmethod
    def from_toml(cls, path: str | Path) -> "RuntimeConfig":
        """
        从 TOML 文件加载配置。

        Args:
            path: TOML 文件路径。

        Returns:
            RuntimeConfig 实例。

        Raises:
            FileNotFoundError: 如果文件不存在。
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"配置文件不存在: {path}")

        try:
            import tomllib  # type: ignore[import-untyped]
        except ImportError:
            # Python 3.10 降级使用 tomli
            try:
                import tomli as tomllib  # type: ignore[no-redef]
            except ImportError:
                raise ImportError("加载 TOML 配置需要安装 tomli: pip install tomli")

        with open(path, "rb") as f:
            data = tomllib.load(f)

        return cls.from_dict(data)

    def to_dict(self) -> dict[str, Any]:
        """
        将配置导出为字典。

        Returns:
            配置字典。
        """
        return {
            "system_prompt": self.system_prompt,
            "llm": self.llm,
            "loop": self.loop,
            "memory": self.memory,
            "services": self.services,
            "plugins": self.plugins,
            "hooks": self.hooks,
            "timeout": self.timeout,
            "budget": self.budget,
        }


def _parse_env_value(value: str) -> Any:
    """解析环境变量值（尝试转换为数字或布尔值）。"""
    # 布尔值
    if value.lower() in ("true", "yes", "1"):
        return True
    if value.lower() in ("false", "no", "0"):
        return False
    # 整数
    try:
        return int(value)
    except ValueError:
        pass
    # 浮点数
    try:
        return float(value)
    except ValueError:
        pass
    # 字符串
    return value
