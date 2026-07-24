"""
测试 Skill 原语：SkillConfig、SkillEntry、SkillManager。
"""

from __future__ import annotations

import os
import tempfile

import pytest

from src.runtime.context._context import RuntimeContext
from src.runtime.context._payload import ContextPayload
from src.tools._skill import SkillConfig, SkillEntry, SkillManager


# ============ Test SkillConfig ============


class TestSkillConfig:
    """测试 SkillConfig 数据类。"""

    def test_default_values(self) -> None:
        config = SkillConfig()
        assert config.name == ""
        assert config.description == ""
        assert config.keywords == []
        assert config.priority == 5
        assert config.auto_inject is False

    def test_custom_values(self) -> None:
        config = SkillConfig(
            name="pr-analysis",
            description="Expert PR review",
            keywords=["pr", "pull request", "review"],
            priority=5,
            auto_inject=False,
        )
        assert config.name == "pr-analysis"
        assert len(config.keywords) == 3
        assert config.priority == 5


# ============ Test SkillEntry ============


class TestSkillEntry:
    """测试 SkillEntry 运行时表示。"""

    def test_create(self) -> None:
        entry = SkillEntry(
            name="test-skill",
            path="/tmp/skills/test-skill",
            content="# Test Skill\n\nYou are a test assistant.",
            config=SkillConfig(
                name="test-skill",
                keywords=["test", "debug"],
                priority=5,
            ),
        )
        assert entry.name == "test-skill"
        assert "# Test Skill" in entry.content

    def test_match_score_keyword_hit(self) -> None:
        entry = SkillEntry(
            name="pr-analysis",
            path="/tmp/skills/pr-analysis",
            content="# PR Analysis",
            config=SkillConfig(
                keywords=["pr", "pull request", "review"],
                priority=5,
            ),
        )
        # "review" 命中 1 个关键词 = 5 分
        score = entry.match_score("Please review the code")
        assert score == 5

    def test_match_score_multiple_keywords(self) -> None:
        entry = SkillEntry(
            name="pr-analysis",
            path="/tmp/skills/pr-analysis",
            content="# PR Analysis",
            config=SkillConfig(
                keywords=["pr", "pull request", "review"],
                priority=5,
            ),
        )
        # "review" 和 "pr" 都命中 = 10 分
        score = entry.match_score("Please review this PR carefully")
        assert score == 10

    def test_match_score_no_match(self) -> None:
        entry = SkillEntry(
            name="pr-analysis",
            path="/tmp/skills/pr-analysis",
            content="# PR Analysis",
            config=SkillConfig(
                keywords=["pr", "pull request", "review"],
                priority=5,
            ),
        )
        score = entry.match_score("Hello, how are you?")
        assert score == 0

    def test_match_score_case_insensitive(self) -> None:
        entry = SkillEntry(
            name="sql-helper",
            path="/tmp/skills/sql-helper",
            content="# SQL Helper",
            config=SkillConfig(
                keywords=["sql", "database", "query"],
                priority=5,
            ),
        )
        score = entry.match_score("Write a SQL query")
        assert score == 10  # "sql" + "query"

    def test_auto_inject_always_high_score(self) -> None:
        entry = SkillEntry(
            name="system-skill",
            path="/tmp/skills/system",
            content="# System Skill",
            config=SkillConfig(
                auto_inject=True,
            ),
        )
        score = entry.match_score("anything")
        assert score == 999

    def test_empty_keywords(self) -> None:
        entry = SkillEntry(
            name="empty-skill",
            path="/tmp/skills/empty",
            content="# Empty",
            config=SkillConfig(),
        )
        score = entry.match_score("anything")
        assert score == 0


# ============ Test SkillManager ============


class TestSkillManager:
    """测试 SkillManager 扫描、匹配、注入。"""

    @pytest.mark.asyncio
    async def test_initial_state(self) -> None:
        manager = SkillManager()
        assert manager.get_all_skills() == []
        assert manager.list_skills() == []

    @pytest.mark.asyncio
    async def test_add_skill(self) -> None:
        manager = SkillManager()
        entry = SkillEntry(
            name="test-skill",
            path="/tmp/test",
            content="# Test",
            config=SkillConfig(keywords=["test"]),
        )
        manager.add_skill(entry)
        assert len(manager.get_all_skills()) == 1
        assert manager.get_all_skills()[0].name == "test-skill"

    @pytest.mark.asyncio
    async def test_remove_skill(self) -> None:
        manager = SkillManager()
        manager.add_skill(SkillEntry(name="a", path="/tmp/a", content="a"))
        manager.add_skill(SkillEntry(name="b", path="/tmp/b", content="b"))
        manager.remove_skill("a")
        assert len(manager.get_all_skills()) == 1
        assert manager.get_all_skills()[0].name == "b"

    @pytest.mark.asyncio
    async def test_remove_nonexistent(self) -> None:
        manager = SkillManager()
        manager.add_skill(SkillEntry(name="a", path="/tmp/a", content="a"))
        manager.remove_skill("nonexistent")
        assert len(manager.get_all_skills()) == 1

    @pytest.mark.asyncio
    async def test_list_skills(self) -> None:
        manager = SkillManager()
        manager.add_skill(SkillEntry(
            name="pr",
            path="/tmp/pr",
            content="x" * 100,
            config=SkillConfig(description="PR review", keywords=["pr"]),
        ))
        info = manager.list_skills()
        assert len(info) == 1
        assert info[0]["name"] == "pr"
        assert info[0]["description"] == "PR review"
        assert info[0]["keywords"] == ["pr"]
        assert info[0]["content_length"] == 100

    @pytest.mark.asyncio
    async def test_scan_nonexistent_dir(self) -> None:
        manager = SkillManager()
        manager.scan(["/nonexistent/path/skills"])
        assert manager.get_all_skills() == []

    @pytest.mark.asyncio
    async def test_scan_directory_with_skill_md(self) -> None:
        """扫描包含 SKILL.md 的子目录。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "test-skill")
            os.makedirs(skill_dir)
            skill_md = os.path.join(skill_dir, "SKILL.md")
            with open(skill_md, "w", encoding="utf-8") as f:
                f.write("# Test Skill\n\nTest content")

            manager = SkillManager()
            manager.scan([tmpdir])
            assert len(manager.get_all_skills()) == 1
            assert manager.get_all_skills()[0].name == "test-skill"
            assert "Test Skill" in manager.get_all_skills()[0].content

    @pytest.mark.asyncio
    async def test_scan_directory_without_skill_md(self) -> None:
        """没有 SKILL.md 的目录应跳过。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "no-skill")
            os.makedirs(skill_dir)
            # 不创建 SKILL.md

            manager = SkillManager()
            manager.scan([tmpdir])
            assert manager.get_all_skills() == []

    # ============ Test Transform Hook ============

    @pytest.mark.asyncio
    async def test_hook_no_skills(self) -> None:
        manager = SkillManager()
        hook = manager.get_before_llm_hook()
        payload = ContextPayload(system_prompt="test")
        ctx = RuntimeContext()
        result = await hook(payload, ctx)
        assert result.injected_context == []

    @pytest.mark.asyncio
    async def test_hook_match_injects_knowledge(self) -> None:
        manager = SkillManager()
        manager.add_skill(SkillEntry(
            name="pr-analysis",
            path="/tmp/pr",
            content="# PR Analysis\n\nReview code carefully.",
            config=SkillConfig(
                name="pr-analysis",
                keywords=["pr", "review", "pull request"],
                priority=5,
            ),
        ))

        hook = manager.get_before_llm_hook()
        payload = ContextPayload(system_prompt="test")
        ctx = RuntimeContext(
            messages=(
                {"role": "user", "content": "Please review this PR"},
            ),
        )
        result = await hook(payload, ctx)
        assert len(result.injected_context) == 1
        assert "PR Analysis" in result.injected_context[0]
        assert "Review code" in result.injected_context[0]
        assert result.is_dirty is True

    @pytest.mark.asyncio
    async def test_hook_no_match_does_not_inject(self) -> None:
        manager = SkillManager()
        manager.add_skill(SkillEntry(
            name="pr-analysis",
            path="/tmp/pr",
            content="# PR Analysis",
            config=SkillConfig(
                keywords=["pr", "review"],
                priority=5,
            ),
        ))

        hook = manager.get_before_llm_hook()
        payload = ContextPayload(system_prompt="test")
        ctx = RuntimeContext(
            messages=(
                {"role": "user", "content": "What is the weather today?"},
            ),
        )
        result = await hook(payload, ctx)
        assert result.injected_context == []

    @pytest.mark.asyncio
    async def test_hook_auto_inject(self) -> None:
        """auto_inject=True 的 Skill 应始终注入。"""
        manager = SkillManager()
        manager.add_skill(SkillEntry(
            name="system-skill",
            path="/tmp/system",
            content="# System Knowledge",
            config=SkillConfig(
                auto_inject=True,
            ),
        ))

        hook = manager.get_before_llm_hook()
        payload = ContextPayload(system_prompt="test")
        ctx = RuntimeContext(
            messages=(
                {"role": "user", "content": "anything"},
            ),
        )
        result = await hook(payload, ctx)
        assert len(result.injected_context) == 1
        assert "System Knowledge" in result.injected_context[0]

    @pytest.mark.asyncio
    async def test_hook_auto_inject_no_user_msg(self) -> None:
        """没有 user message 时，auto_inject 仍然注入。"""
        manager = SkillManager()
        manager.add_skill(SkillEntry(
            name="auto-skill",
            path="/tmp/auto",
            content="# Auto",
            config=SkillConfig(auto_inject=True),
        ))

        hook = manager.get_before_llm_hook()
        payload = ContextPayload(system_prompt="test")
        ctx = RuntimeContext(messages=())  # 没有消息
        result = await hook(payload, ctx)
        assert len(result.injected_context) == 1

    @pytest.mark.asyncio
    async def test_hook_multiple_skills(self) -> None:
        """多个 Skill 同时匹配时，全部注入。"""
        manager = SkillManager()
        manager.add_skill(SkillEntry(
            name="pr",
            path="/tmp/pr",
            content="# PR",
            config=SkillConfig(keywords=["pr", "review"], priority=5),
        ))
        manager.add_skill(SkillEntry(
            name="sql",
            path="/tmp/sql",
            content="# SQL",
            config=SkillConfig(keywords=["sql", "query"], priority=5),
        ))

        hook = manager.get_before_llm_hook()
        payload = ContextPayload(system_prompt="test")
        ctx = RuntimeContext(
            messages=(
                {"role": "user", "content": "Review this PR and write a SQL query"},
            ),
        )
        result = await hook(payload, ctx)
        assert len(result.injected_context) == 2

    @pytest.mark.asyncio
    async def test_hook_with_description_in_header(self) -> None:
        """description 应出现在注入内容的 header 中。"""
        manager = SkillManager()
        manager.add_skill(SkillEntry(
            name="pr",
            path="/tmp/pr",
            content="# PR Knowledge",
            config=SkillConfig(
                description="Expert PR review",
                keywords=["pr"],
                priority=5,
            ),
        ))

        hook = manager.get_before_llm_hook()
        payload = ContextPayload(system_prompt="test")
        ctx = RuntimeContext(
            messages=({"role": "user", "content": "review this pr"},),
        )
        result = await hook(payload, ctx)
        assert len(result.injected_context) == 1
        assert "(Expert PR review)" in result.injected_context[0]

    @pytest.mark.asyncio
    async def test_scan_with_skill_toml(self) -> None:
        """扫描包含 SKILL.md 和 skill.toml 的目录。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "my-skill")
            os.makedirs(skill_dir)
            with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
                f.write("# Custom Skill\n\nContent")
            with open(os.path.join(skill_dir, "skill.toml"), "w", encoding="utf-8") as f:
                f.write("[skill]\n")
                f.write('name = "custom-name"\n')
                f.write('description = "Custom desc"\n')
                f.write('keywords = ["custom", "skill"]\n')
                f.write("priority = 8\n")
                f.write("auto_inject = true\n")

            manager = SkillManager()
            manager.scan([tmpdir])
            assert len(manager.get_all_skills()) == 1
            entry = manager.get_all_skills()[0]
            assert entry.name == "custom-name"
            assert entry.config.description == "Custom desc"
            assert entry.config.keywords == ["custom", "skill"]
            assert entry.config.priority == 8
            assert entry.config.auto_inject is True

    @pytest.mark.asyncio
    async def test_scan_with_malformed_toml(self) -> None:
        """格式错误的 skill.toml 不应导致 scan 崩溃。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "broken-skill")
            os.makedirs(skill_dir)
            with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
                f.write("# Broken Skill\n\nContent")
            with open(os.path.join(skill_dir, "skill.toml"), "w", encoding="utf-8") as f:
                f.write("这不是有效 TOML [[[语法错误")

            manager = SkillManager()
            manager.scan([tmpdir])
            assert len(manager.get_all_skills()) == 1
            # 使用默认名称（目录名）
            assert manager.get_all_skills()[0].name == "broken-skill"

    @pytest.mark.asyncio
    async def test_scan_skips_non_directory_files(self) -> None:
        """扫描时文件而非目录应跳过。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 在扫描目录下创建一个文件（不是目录）
            file_path = os.path.join(tmpdir, "not-a-dir.txt")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("this is a file, not a directory")

            # 同时创建一个有效的 skill 子目录
            skill_dir = os.path.join(tmpdir, "valid-skill")
            os.makedirs(skill_dir)
            with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
                f.write("# Valid Skill")

            manager = SkillManager()
            manager.scan([tmpdir])
            # 只有 valid-skill 被加载
            assert len(manager.get_all_skills()) == 1
            assert manager.get_all_skills()[0].name == "valid-skill"

    @pytest.mark.asyncio
    async def test_get_last_user_message_empty_content(self) -> None:
        """user 消息 content 为空时仍能处理。"""
        manager = SkillManager()
        manager.add_skill(SkillEntry(
            name="auto-skill",
            path="/tmp/auto",
            content="# Auto",
            config=SkillConfig(auto_inject=True),
        ))
        hook = manager.get_before_llm_hook()
        payload = ContextPayload(system_prompt="test")
        ctx = RuntimeContext(
            messages=({"role": "user", "content": ""},),
        )
        result = await hook(payload, ctx)
        assert len(result.injected_context) == 1

    @pytest.mark.asyncio
    async def test_hook_priority_threshold(self) -> None:
        """score < priority 时不注入。"""
        manager = SkillManager()
        manager.add_skill(SkillEntry(
            name="high-bar",
            path="/tmp/high",
            content="# High Bar",
            config=SkillConfig(keywords=["rare"], priority=10),
        ))

        hook = manager.get_before_llm_hook()
        payload = ContextPayload(system_prompt="test")
        ctx = RuntimeContext(
            messages=(
                {"role": "user", "content": "rare keyword present"},
            ),
        )
        result = await hook(payload, ctx)
        # score=5, priority=10 → 不注入
        assert len(result.injected_context) == 0
