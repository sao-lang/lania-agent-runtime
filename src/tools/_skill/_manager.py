"""
SkillManager——Skill 管理器。

在 before_llm 阶段扫描、匹配并注入领域知识到 ContextPayload。
Skill 是 Transform 原语，不是 Execute 原语——它不产生 tool_call，只修改上下文。
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

from src.tools._skill._models import SkillConfig, SkillEntry

if TYPE_CHECKING:
    from src.runtime.context._context import RuntimeContext
    from src.runtime.context._payload import ContextPayload

logger = logging.getLogger(__name__)


class SkillManager:
    """
    Skill 管理器——扫描、匹配、注入领域知识。

    Skill 是 Transform 原语，在 before_llm 阶段将 SKILL.md 内容
    注入到 ContextPayload.injected_context 中，让 LLM 看到领域知识。

    Usage:
        manager = SkillManager()
        manager.scan(["skills/pr-analysis", "skills/sql-helper"])
        hook = manager.get_before_llm_hook()
        # 将 hook 注册为 before_llm Transform
    """

    def __init__(self) -> None:
        """初始化空的 Skill 管理器。"""
        self._skills: list[SkillEntry] = []

    # ============ 扫描与加载 ============

    def scan(self, skill_dirs: list[str]) -> None:
        """
        扫描目录，加载 SKILL.md 和可选的 skill.toml。

        遍历每个目录的一级子目录，查找 SKILL.md 文件（核心内容），
        以及可选的 skill.toml（元信息）。

        Args:
            skill_dirs: 要扫描的父目录路径列表，每个目录下的子目录
                被视为一个 Skill。
        """
        for base_dir in skill_dirs:
            resolved = os.path.abspath(base_dir)
            if not os.path.isdir(resolved):
                logger.warning("Skill 父目录不存在: %s", resolved)
                continue

            # 遍历一级子目录
            for entry_name in os.listdir(resolved):
                skill_dir = os.path.join(resolved, entry_name)
                if not os.path.isdir(skill_dir):
                    continue

                skill_name = entry_name
                skill_md_path = os.path.join(skill_dir, "SKILL.md")

                if not os.path.isfile(skill_md_path):
                    continue

                # 读取 SKILL.md
                with open(skill_md_path, encoding="utf-8") as f:
                    content = f.read()

                # 读取 skill.toml（可选）
                config = self._load_config(skill_dir, skill_name)

                entry = SkillEntry(
                    name=config.name or skill_name,
                    path=skill_dir,
                    content=content,
                    config=config,
                )
                self._skills.append(entry)
                logger.info("Skill 已加载: %s (%s)", entry.name, skill_dir)

    def add_skill(self, entry: SkillEntry) -> None:
        """
        直接添加一个 SkillEntry（编程方式，不通过文件扫描）。

        Args:
            entry: SkillEntry 实例。
        """
        self._skills.append(entry)

    def remove_skill(self, name: str) -> None:
        """
        移除指定名称的 Skill。

        Args:
            name: Skill 名称。
        """
        self._skills = [s for s in self._skills if s.name != name]

    def get_all_skills(self) -> list[SkillEntry]:
        """
        获取所有已加载的 Skill。

        Returns:
            SkillEntry 列表。
        """
        return list(self._skills)

    # ============ Transform Hook ============

    def get_before_llm_hook(self) -> Any:
        """
        返回一个 before_llm Transform hook。

        该 hook 匹配用户 query 与 Skill 的关键词，
        将匹配的 SKILL.md 内容注入到 ContextPayload.injected_context。

        Returns:
            异步函数，签名符合 Transformer[ContextPayload]。
        """

        async def hook(data: "ContextPayload", ctx: "RuntimeContext") -> "ContextPayload":
            """before_llm Transform：匹配并注入 Skill 知识。"""
            if not self._skills:
                return data

            user_msg = self._get_last_user_message(ctx)
            if not user_msg:
                # auto_inject 的 skill 仍然注入
                for skill in self._skills:
                    if skill.config.auto_inject:
                        data.injected_context.append(
                            f"## {skill.name} ({skill.config.description})\n{skill.content}"
                        )
                        data.mark_dirty()
                return data

            for skill in self._skills:
                score = skill.match_score(user_msg)
                if score >= skill.config.priority:
                    # 注入知识到 context_payload
                    header = f"## {skill.name}"
                    if skill.config.description:
                        header += f" ({skill.config.description})"
                    data.injected_context.append(f"{header}\n{skill.content}")
                    data.mark_dirty()
                    logger.debug(
                        "Skill '%s' 已匹配 (score=%d >= priority=%d)",
                        skill.name, score, skill.config.priority,
                    )

            return data

        return hook

    def list_skills(self) -> list[dict]:
        """
        列出所有 Skill 的简要信息。

        Returns:
            Skill 信息字典列表。
        """
        return [
            {
                "name": s.name,
                "description": s.config.description,
                "keywords": s.config.keywords,
                "auto_inject": s.config.auto_inject,
                "content_length": len(s.content),
            }
            for s in self._skills
        ]

    # ============ 内部方法 ============

    @staticmethod
    def _load_config(skill_dir: str, default_name: str) -> SkillConfig:
        """
        从 skill.toml 加载配置（如存在）。

        Args:
            skill_dir: Skill 目录路径。
            default_name: 默认 Skill 名称（当未配置时）。

        Returns:
            SkillConfig 实例。
        """
        toml_path = os.path.join(skill_dir, "skill.toml")
        if not os.path.isfile(toml_path):
            return SkillConfig(name=default_name)

        try:
            import tomli

            with open(toml_path, "rb") as f:
                data = tomli.load(f)

            skill_data = data.get("skill", {})
            return SkillConfig(
                name=skill_data.get("name", default_name),
                description=skill_data.get("description", ""),
                keywords=skill_data.get("keywords", []),
                priority=skill_data.get("priority", 5),
                auto_inject=skill_data.get("auto_inject", False),
            )
        except Exception as e:
            logger.warning(
                "加载 skill.toml 失败 (%s): %s", toml_path, e,
                exc_info=True,
            )
            return SkillConfig(name=default_name)

    @staticmethod
    def _get_last_user_message(ctx: "RuntimeContext") -> str:
        """
        从 RuntimeContext 中提取最后一条用户消息。

        Args:
            ctx: RuntimeContext 实例。

        Returns:
            用户消息文本，无消息时返回空字符串。
        """
        for msg in reversed(ctx.messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                return str(content) if content else ""
        return ""
