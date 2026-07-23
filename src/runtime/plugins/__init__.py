"""
插件模块——PluggableComponent 与 Plugin 协议。

任何需要挂载到 AgentRuntime 的模块都实现 PluggableComponent 接口。
Plugin 继承 PluggableComponent，提供简化的 hook 声明方式。
"""

from src.runtime.plugins._plugin import PluggableComponent, Plugin

__all__ = [
    "PluggableComponent",
    "Plugin",
]
