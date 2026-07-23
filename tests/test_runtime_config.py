"""
测试 RuntimeConfig：多源加载。
"""

from __future__ import annotations

import os
import tempfile

import pytest

from src.runtime.config._runtime_config import RuntimeConfig


class TestRuntimeConfig:
    """测试 RuntimeConfig。"""

    def test_default_values(self) -> None:
        config = RuntimeConfig()
        assert config.system_prompt == ""
        assert config.llm == {}
        assert config.loop == {}
        assert config.memory == {}
        assert config.services == {}
        assert config.plugins == {}
        assert config.hooks == {}
        assert config.timeout == {"step_timeout_ms": 60_000, "total_timeout_ms": 600_000}
        assert config.budget == {"token_limit": 100_000, "step_limit": 50, "max_cost_cents": 1000}

    def test_from_dict(self) -> None:
        data = {
            "system_prompt": "你是助手",
            "llm": {"model": "gpt-4o", "api_key": "sk-test"},
            "loop": {"strategy": "react", "max_steps": 20},
            "memory": {"backend": "sqlite", "path": "./memory.db"},
            "services": {"weather_api_key": "test"},
            "plugins": {"audit": {"include": ["llm_calls"]}},
            "timeout": {"step_timeout_ms": 30_000},
            "budget": {"token_limit": 50_000},
        }
        config = RuntimeConfig.from_dict(data)
        assert config.system_prompt == "你是助手"
        assert config.llm["model"] == "gpt-4o"
        assert config.loop["strategy"] == "react"
        assert config.memory["backend"] == "sqlite"
        assert config.services["weather_api_key"] == "test"
        assert config.plugins["audit"]["include"] == ["llm_calls"]
        assert config.timeout["step_timeout_ms"] == 30_000
        assert config.budget["token_limit"] == 50_000

    def test_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AGENT_SYSTEM_PROMPT", "你是一个助手")
        monkeypatch.setenv("AGENT_LLM__MODEL", "gpt-4o")
        monkeypatch.setenv("AGENT_LLM__API_KEY", "sk-test")
        monkeypatch.setenv("AGENT_LOOP__STRATEGY", "react")
        monkeypatch.setenv("AGENT_BUDGET__TOKEN_LIMIT", "50000")

        config = RuntimeConfig.from_env(prefix="AGENT_")
        assert config.system_prompt == "你是一个助手"
        assert config.llm["model"] == "gpt-4o"
        assert config.llm["api_key"] == "sk-test"
        assert config.loop["strategy"] == "react"
        assert config.budget["token_limit"] == 50_000

    def test_from_env_single_underscore_section(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """兼容旧版单下划线 section 命名。"""
        monkeypatch.setenv("AGENT_LLM_MODEL", "gpt-4o")
        monkeypatch.setenv("AGENT_BUDGET_TOKEN_LIMIT", "30000")

        config = RuntimeConfig.from_env(prefix="AGENT_")
        assert config.llm["model"] == "gpt-4o"
        assert config.budget["token_limit"] == 30_000

    def test_from_env_no_prefix(self) -> None:
        """不匹配前缀的 env 不应影响配置。"""
        config = RuntimeConfig.from_env(prefix="NONEXISTENT_")
        assert config.system_prompt == ""

    def test_to_dict(self) -> None:
        config = RuntimeConfig(
            system_prompt="助手",
            llm={"model": "gpt-4o"},
            loop={"strategy": "plan_and_execute"},
        )
        d = config.to_dict()
        assert d["system_prompt"] == "助手"
        assert d["llm"]["model"] == "gpt-4o"
        assert d["loop"]["strategy"] == "plan_and_execute"
        # 默认值
        assert "timeout" in d
        assert "budget" in d

    def test_from_yaml_file_not_found(self) -> None:
        with pytest.raises(FileNotFoundError):
            RuntimeConfig.from_yaml("nonexistent.yaml")

    def test_from_yaml_success(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            f.write("system_prompt: 你是助手\nllm:\n  model: gpt-4o\n")
            yaml_path = f.name

        try:
            config = RuntimeConfig.from_yaml(yaml_path)
            assert config.system_prompt == "你是助手"
            assert config.llm["model"] == "gpt-4o"
        finally:
            os.unlink(yaml_path)

    def test_from_toml_file_not_found(self) -> None:
        with pytest.raises(FileNotFoundError):
            RuntimeConfig.from_toml("nonexistent.toml")

    def test_from_toml_success(self) -> None:
        try:
            import tomllib  # noqa: F401
        except ImportError:
            try:
                import tomli  # noqa: F401
            except ImportError:
                pytest.skip("需要 tomllib 或 tomli 模块")

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".toml", delete=False, encoding="utf-8"
        ) as f:
            f.write('system_prompt = "你是助手"\n[llm]\nmodel = "gpt-4o"\n')
            toml_path = f.name

        try:
            config = RuntimeConfig.from_toml(toml_path)
            assert config.system_prompt == "你是助手"
            assert config.llm["model"] == "gpt-4o"
        finally:
            os.unlink(toml_path)


class TestEnvValueParser:
    """测试环境变量值解析。"""

    def test_parse_boolean_true(self) -> None:
        from src.runtime.config._runtime_config import _parse_env_value

        assert _parse_env_value("true") is True
        assert _parse_env_value("True") is True
        assert _parse_env_value("yes") is True
        assert _parse_env_value("1") is True

    def test_parse_boolean_false(self) -> None:
        from src.runtime.config._runtime_config import _parse_env_value

        assert _parse_env_value("false") is False
        assert _parse_env_value("False") is False
        assert _parse_env_value("no") is False
        assert _parse_env_value("0") is False

    def test_parse_int(self) -> None:
        from src.runtime.config._runtime_config import _parse_env_value

        assert _parse_env_value("42") == 42
        assert _parse_env_value("0") is False  # 0 被解析为布尔值 False

    def test_parse_float(self) -> None:
        from src.runtime.config._runtime_config import _parse_env_value

        assert _parse_env_value("3.14") == 3.14

    def test_parse_string(self) -> None:
        from src.runtime.config._runtime_config import _parse_env_value

        assert _parse_env_value("hello world") == "hello world"
        assert _parse_env_value("sk-test-key") == "sk-test-key"
