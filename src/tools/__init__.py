"""
工具原语包——Tool / MCP / Skill 三种能力原语。

- Tool：本地函数工具（ToolSpec + ToolRegistry + ToolDispatcher）
- MCP：外部协议工具（MCPServerConfig + MCPClient + MCPToolAdapter + MCPServerManager）
- Skill：知识注入单元（SkillManager + SkillEntry + SkillConfig）
"""

from src.tools._dispatcher import ToolDispatcher
from src.tools._mcp import MCPClient, MCPServerConfig, MCPServerManager, MCPToolAdapter
from src.tools._registry import ToolRegistry
from src.tools._skill import SkillConfig, SkillEntry, SkillManager
from src.tools._spec import ToolSpec

__all__ = [
    # Tool
    "ToolDispatcher",
    "ToolRegistry",
    "ToolSpec",
    # MCP
    "MCPServerConfig",
    "MCPClient",
    "MCPToolAdapter",
    "MCPServerManager",
    # Skill
    "SkillManager",
    "SkillConfig",
    "SkillEntry",
]
