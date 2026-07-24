"""
RuntimeBuilder——声明式构造器。

链式 API 替代膨胀的构造参数，支持从 RuntimeConfig 一键构建 AgentRuntime。
"""

from __future__ import annotations

from typing import Any

from src.runtime._runtime import AgentRuntime
from src.runtime._types import ExecutorFn, RouterFn
from src.runtime.config._runtime_config import RuntimeConfig
from src.runtime.hooks._registry import HookRegistry
from src.runtime.plugins._plugin import Plugin
from src.tools import MCPServerManager, SkillManager, ToolRegistry


class RuntimeBuilder:
    """
    声明式构造器——链式 API 替代膨胀的构造参数。

    使用方式:
        runtime = (RuntimeBuilder()
            .system_prompt("你是助手")
            .llm(model="gpt-4o", api_key="sk-...")
            .plugin(AuditPlugin())
            .build())
    """

    def __init__(self) -> None:
        """初始化构造器。"""
        self._system_prompt: str = ""
        self._hooks: HookRegistry | None = None
        self._llm_executor: ExecutorFn | None = None
        self._tool_executor: ExecutorFn | None = None
        self._loop_executor: ExecutorFn | None = None
        self._router: RouterFn | None = None
        self._serializer: Any = None
        self._services: dict[str, Any] = {}
        self._agent_id: str = ""
        self._plugins: list[Plugin] = []
        self._tool_registry: ToolRegistry | None = None
        self._mcp_manager: MCPServerManager | None = None
        self._skill_manager: SkillManager | None = None
        self._memory_service: Any | None = None

    def system_prompt(self, prompt: str) -> RuntimeBuilder:
        """
        设置系统提示词。

        Args:
            prompt: 系统提示词。

        Returns:
            self（链式调用）。
        """
        self._system_prompt = prompt
        return self

    def llm(
        self,
        model: str = "",
        api_key: str = "",
        executor: ExecutorFn | None = None,
        **kwargs: Any,
    ) -> RuntimeBuilder:
        """
        配置 LLM。

        Args:
            model: 模型名称。
            api_key: API 密钥。
            executor: 自定义 LLM 执行器（提供此参数时忽略 model/api_key）。
            kwargs: 额外 LLM 配置。

        Returns:
            self（链式调用）。
        """
        if executor is not None:
            self._llm_executor = executor
        else:
            self._services.setdefault("llm_config", {})
            self._services["llm_config"]["model"] = model
            if api_key:
                self._services["llm_config"]["api_key"] = api_key
            self._services["llm_config"].update(kwargs)
        return self

    def tool(self, executor: ExecutorFn) -> RuntimeBuilder:
        """
        注册工具执行器。

        Args:
            executor: 工具执行器。

        Returns:
            self（链式调用）。
        """
        self._tool_executor = executor
        return self

    def tool_registry(self, registry: ToolRegistry) -> RuntimeBuilder:
        """
        设置 ToolRegistry（同时提供 tool_executor 时，tool_registry 优先）。

        Args:
            registry: ToolRegistry 实例。

        Returns:
            self（链式调用）。
        """
        self._tool_registry = registry
        return self

    def mcp(self, manager: MCPServerManager) -> RuntimeBuilder:
        """
        设置 MCPServerManager，集成 MCP 工具。

        Args:
            manager: MCPServerManager 实例。

        Returns:
            self（链式调用）。
        """
        self._mcp_manager = manager
        return self

    def skills(self, manager: SkillManager) -> RuntimeBuilder:
        """
        设置 SkillManager，注入领域知识。

        Args:
            manager: SkillManager 实例。

        Returns:
            self（链式调用）。
        """
        self._skill_manager = manager
        return self

    def memory(self, service: Any | None = None) -> RuntimeBuilder:
        """
        注入记忆系统。

        传入已组装好的 MemoryService 实例，Runtime 将自动注册
        after_step Transform 将对话写入持久化记忆。

        Args:
            service: MemoryService 实例。由用户自行创建并注入，
                     支持任意 MemoryPersistence 后端（SQLite / Redis 等）。

        Returns:
            self（链式调用）。
        """
        self._memory_service = service
        return self

    def loop(self, strategy: str = "", **kwargs: Any) -> RuntimeBuilder:
        """
        配置 Step Loop 策略。

        Args:
            strategy: loop 策略名称（如 "react", "plan_and_execute"）。
            kwargs: loop 配置。

        Returns:
            self（链式调用）。
        """
        self._services.setdefault("loop_config", {})
        self._services["loop_config"]["strategy"] = strategy
        self._services["loop_config"].update(kwargs)
        return self

    def hooks(self, registry: HookRegistry) -> RuntimeBuilder:
        """
        设置自定义 HookRegistry。

        Args:
            registry: HookRegistry 实例。

        Returns:
            self（链式调用）。
        """
        self._hooks = registry
        return self

    def services(self, services: dict[str, Any]) -> RuntimeBuilder:
        """
        设置外部服务。

        Args:
            services: 服务字典。

        Returns:
            self（链式调用）。
        """
        self._services.update(services)
        return self

    def agent_id(self, agent_id: str) -> RuntimeBuilder:
        """
        设置 Agent ID。

        Args:
            agent_id: Agent 标识。

        Returns:
            self（链式调用）。
        """
        self._agent_id = agent_id
        return self

    def plugin(self, plugin: Plugin) -> RuntimeBuilder:
        """
        添加插件。

        Args:
            plugin: Plugin 实例。

        Returns:
            self（链式调用）。
        """
        self._plugins.append(plugin)
        return self

    def from_config(self, config: RuntimeConfig) -> RuntimeBuilder:
        """
        从 RuntimeConfig 加载配置。

        Args:
            config: RuntimeConfig 实例。

        Returns:
            self（链式调用）。
        """
        self._system_prompt = config.system_prompt

        if config.llm:
            self._services["llm_config"] = dict(config.llm)

        if config.loop:
            self._services["loop_config"] = dict(config.loop)

        if config.memory:
            self._services["memory_config"] = dict(config.memory)

        if config.services:
            self._services.update(config.services)

        return self

    def build(self) -> AgentRuntime:
        """
        构建 AgentRuntime 实例。

        如果设置了 llm 配置（通过 .llm() 或 from_config()）且
        未传入自定义 executor，自动创建 OpenAILLMExecutor。

        Returns:
            配置好的 AgentRuntime 实例。
        """
        # 自动创建 LLMExecutor（如果配置了 llm 且未自定义 executor，
        # 且有 api_key 或环境变量中有 OPENAI_API_KEY）
        if self._llm_executor is None and "llm_config" in self._services:
            from src.runtime.llm import LLMExecutorConfig, OpenAILLMExecutor

            config = LLMExecutorConfig.from_dict(self._services["llm_config"])
            # 仅在提供了 api_key 时自动创建，否则只保留配置供后续手动注入
            if config.api_key or self._has_openai_api_key():
                self._llm_executor = OpenAILLMExecutor(config)

        runtime = AgentRuntime(
            system_prompt=self._system_prompt,
            hooks=self._hooks,
            llm_executor=self._llm_executor,
            tool_executor=self._tool_executor,
            loop_executor=self._loop_executor,
            router=self._router,
            services=self._services or None,
            agent_id=self._agent_id,
            tools=self._tool_registry,
            mcp=self._mcp_manager,
            skills=self._skill_manager,
            memory_service=self._memory_service,
        )

        # 插件在 build() 时不自动注册（需要 async 上下文），
        # 用户需在异步上下文中调用 runtime.use(plugin)
        return runtime

    @staticmethod
    def _has_openai_api_key() -> bool:
        """检查环境变量中是否有 OpenAI API 密钥。

        Returns:
            True 如果 OPENAI_API_KEY 已设置。
        """
        import os

        return bool(os.environ.get("OPENAI_API_KEY", "")) or bool(
            os.environ.get("OPENAI_ADMIN_KEY", "")
        )
