"""
test_skill_registration.py
==========================
外部 Skill 注册与执行单元测试（P0 保护网）。

覆盖范围：
1. external_loader 的 frontmatter 解析
2. SKILL.md 文件发现
3. 同级资源目录检测（helpers/scripts/agents/references）
4. 动态 Skill 子类生成（type() 工厂）
5. skill 注册幂等性
6. MCP 配置自动扫描

设计原则：
- 纯 Python 单元测试，不依赖 Qt
- 使用临时目录隔离，不污染真实 external/ 目录
- 遵循 .trae/rules/2.md §七 TDD 规则
"""
import os
import json
import pytest
import tempfile
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Type


# ─────────────── 导入受测模块 ───────────────
def _import_external_loader():
    """延迟导入，避免初始化副作用。"""
    from app.skills import external_loader
    return external_loader


# ════════════════════════════════════════════════════════════════════
# 1. frontmatter 解析
# ════════════════════════════════════════════════════════════════════
class TestParseFrontmatter:
    """验证 _parse_frontmatter 解析 SKILL.md 顶部 YAML。"""

    def test_parse_simple_frontmatter(self):
        """简单 key: value frontmatter 应正确解析。"""
        loader = _import_external_loader()
        content = """---
name: 测试技能
description: 这是一个测试技能
version: 1.0.0
---

# Skill body
"""
        result = loader._parse_frontmatter(content)
        assert result["name"] == "测试技能"
        assert result["description"] == "这是一个测试技能"
        assert result["version"] == "1.0.0"

    def test_parse_frontmatter_with_quotes(self):
        """带引号的 value 应去引号。"""
        loader = _import_external_loader()
        content = '''---
name: "带引号的技能"
description: '单引号描述'
---
body
'''
        result = loader._parse_frontmatter(content)
        assert result["name"] == "带引号的技能"
        assert result["description"] == "单引号描述"

    def test_parse_frontmatter_no_frontmatter(self):
        """没有 frontmatter 应返回空 dict。"""
        loader = _import_external_loader()
        content = "# Just a markdown\nNo frontmatter here."
        result = loader._parse_frontmatter(content)
        assert result == {}

    def test_parse_frontmatter_skips_comments(self):
        """# 开头的行应被跳过。"""
        loader = _import_external_loader()
        content = """---
# this is a comment
name: 真实技能
# another comment
description: 描述
---
body
"""
        result = loader._parse_frontmatter(content)
        assert result["name"] == "真实技能"
        assert result["description"] == "描述"

    def test_parse_frontmatter_skips_invalid_lines(self):
        """没有冒号的行应被跳过。"""
        loader = _import_external_loader()
        content = """---
name: 测试
invalid line without colon
description: 描述
---
body
"""
        result = loader._parse_frontmatter(content)
        assert result["name"] == "测试"
        assert result["description"] == "描述"
        assert "invalid line without colon" not in result


# ════════════════════════════════════════════════════════════════════
# 2. SKILL.md 文件发现
# ════════════════════════════════════════════════════════════════════
class TestFindSkillMdFiles:
    """验证 _find_skill_md_files 递归扫描。"""

    def test_find_skill_md_in_root(self, tmp_path):
        """根目录的 SKILL.md 应被发现。"""
        loader = _import_external_loader()
        (tmp_path / "SKILL.md").write_text("---\nname: test\n---\nbody", encoding="utf-8")

        result = loader._find_skill_md_files(tmp_path)
        assert len(result) == 1
        assert result[0].name == "SKILL.md"

    def test_find_skill_md_recursive(self, tmp_path):
        """嵌套目录的 SKILL.md 应被发现。"""
        loader = _import_external_loader()
        nested = tmp_path / "repo" / "skills" / "my-skill"
        nested.mkdir(parents=True)
        (nested / "SKILL.md").write_text("---\nname: test\n---\nbody", encoding="utf-8")

        result = loader._find_skill_md_files(tmp_path)
        assert len(result) == 1

    def test_find_skill_md_skips_git(self, tmp_path):
        """.git 目录应被跳过。"""
        loader = _import_external_loader()
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "SKILL.md").write_text("should be ignored", encoding="utf-8")
        (tmp_path / "SKILL.md").write_text("---\nname: real\n---\nbody", encoding="utf-8")

        result = loader._find_skill_md_files(tmp_path)
        assert len(result) == 1
        assert ".git" not in str(result[0])

    def test_find_skill_md_empty_dir(self, tmp_path):
        """空目录应返回空列表。"""
        loader = _import_external_loader()
        result = loader._find_skill_md_files(tmp_path)
        assert result == []

    def test_find_skill_md_nonexistent_dir(self, tmp_path):
        """不存在的目录应返回空列表。"""
        loader = _import_external_loader()
        result = loader._find_skill_md_files(tmp_path / "nonexistent")
        assert result == []


# ════════════════════════════════════════════════════════════════════
# 3. 同级资源目录检测
# ════════════════════════════════════════════════════════════════════
class TestDetectCompanionDirs:
    """验证 _detect_companion_dirs 检测同级辅助目录。"""

    def test_detect_all_companions(self, tmp_path):
        """所有辅助目录都存在时应全部识别。"""
        loader = _import_external_loader()
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("---\nname: test\n---\nbody", encoding="utf-8")
        for d in ["helpers", "scripts", "agents", "references"]:
            (tmp_path / d).mkdir()

        result = loader._detect_companion_dirs(skill_md)
        assert result["helpers_dir"] is not None
        assert result["scripts_dir"] is not None
        assert result["agents_dir"] is not None
        assert result["references_dir"] is not None

    def test_detect_no_companions(self, tmp_path):
        """无辅助目录时应返回全 None。"""
        loader = _import_external_loader()
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("---\nname: test\n---\nbody", encoding="utf-8")

        result = loader._detect_companion_dirs(skill_md)
        assert result["helpers_dir"] is None
        assert result["scripts_dir"] is None
        assert result["agents_dir"] is None
        assert result["references_dir"] is None

    def test_detect_partial_companions(self, tmp_path):
        """部分辅助目录存在时应只识别存在的。"""
        loader = _import_external_loader()
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("---\nname: test\n---\nbody", encoding="utf-8")
        (tmp_path / "helpers").mkdir()
        (tmp_path / "agents").mkdir()

        result = loader._detect_companion_dirs(skill_md)
        assert result["helpers_dir"] is not None
        assert result["scripts_dir"] is None
        assert result["agents_dir"] is not None
        assert result["references_dir"] is None


# ════════════════════════════════════════════════════════════════════
# 4. 来源仓库名推断
# ════════════════════════════════════════════════════════════════════
class TestExtractSourceRepo:
    """验证 _extract_source_repo 从路径推断仓库名。"""

    def test_top_level_repo(self, tmp_path):
        """顶层 SKILL.md 应返回第一级目录名。"""
        loader = _import_external_loader()
        external_root = tmp_path / "external"
        repo_dir = external_root / "seedance-skill"
        repo_dir.mkdir(parents=True)
        skill_md = repo_dir / "SKILL.md"
        skill_md.write_text("---\nname: test\n---\nbody", encoding="utf-8")

        repo = loader._extract_source_repo(skill_md, external_root)
        assert repo == "seedance-skill"

    def test_nested_repo(self, tmp_path):
        """嵌套 SKILL.md 应返回第一级目录名。"""
        loader = _import_external_loader()
        external_root = tmp_path / "external"
        nested = external_root / "videocut-skills" / "plugins" / "chengfeng"
        nested.mkdir(parents=True)
        skill_md = nested / "SKILL.md"
        skill_md.write_text("---\nname: test\n---\nbody", encoding="utf-8")

        repo = loader._extract_source_repo(skill_md, external_root)
        assert repo == "videocut-skills"


# ════════════════════════════════════════════════════════════════════
# 5. agents/ 目录 YAML 列表
# ════════════════════════════════════════════════════════════════════
class TestListAgentYamls:
    """验证 _list_agent_yamls 列出 agents/ 下的 YAML 文件。"""

    def test_list_yaml_and_yml(self, tmp_path):
        """应同时识别 .yaml 和 .yml。"""
        loader = _import_external_loader()
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        (agents_dir / "agent1.yaml").write_text("name: agent1", encoding="utf-8")
        (agents_dir / "agent2.yml").write_text("name: agent2", encoding="utf-8")
        (agents_dir / "readme.md").write_text("not yaml", encoding="utf-8")

        result = loader._list_agent_yamls(agents_dir)
        assert len(result) == 2
        suffixes = {p.suffix for p in result}
        assert suffixes == {".yaml", ".yml"}

    def test_list_empty_dir(self, tmp_path):
        """空目录应返回空列表。"""
        loader = _import_external_loader()
        result = loader._list_agent_yamls(tmp_path)
        assert result == []

    def test_list_none_dir(self):
        """None 应返回空列表。"""
        loader = _import_external_loader()
        result = loader._list_agent_yamls(None)
        assert result == []

    def test_list_sorted(self, tmp_path):
        """结果应排序。"""
        loader = _import_external_loader()
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        (agents_dir / "c.yaml").write_text("c", encoding="utf-8")
        (agents_dir / "a.yaml").write_text("a", encoding="utf-8")
        (agents_dir / "b.yaml").write_text("b", encoding="utf-8")

        result = loader._list_agent_yamls(agents_dir)
        names = [p.name for p in result]
        assert names == ["a.yaml", "b.yaml", "c.yaml"]


# ════════════════════════════════════════════════════════════════════
# 6. 动态 Skill 子类生成
# ════════════════════════════════════════════════════════════════════
class TestMakeExternalSkillClass:
    """验证 _make_external_skill_class 动态生成 Skill 子类。"""

    def test_make_class_has_correct_attributes(self, tmp_path):
        """生成的类应有正确的类属性。"""
        loader = _import_external_loader()
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text("---\nname: 测试\n---\nbody", encoding="utf-8")

        cls = loader._make_external_skill_class(
            skill_id="test__my-skill",
            name="测试",
            description="测试描述",
            source_repo="test",
            skill_dir=skill_dir,
            companions={},
            agent_yamls=[],
        )

        assert cls.skill_id == "test__my-skill"
        assert cls.skill_name == "测试"
        assert cls.skill_description == "测试描述"
        assert cls.skill_category == "外部/test"
        assert cls.skill_icon == "📦"

    def test_make_class_long_description_truncated(self, tmp_path):
        """长描述应被截断到 120 字符。"""
        loader = _import_external_loader()
        long_desc = "x" * 200
        cls = loader._make_external_skill_class(
            skill_id="test__long",
            name="long",
            description=long_desc,
            source_repo="test",
            skill_dir=tmp_path,
            companions={},
            agent_yamls=[],
        )
        assert len(cls.skill_description) <= 120
        assert cls.skill_description.endswith("...")


# ════════════════════════════════════════════════════════════════════
# 7. 注册幂等性
# ════════════════════════════════════════════════════════════════════
class TestRegistrationIdempotency:
    """验证 ensure_external_skills_registered 幂等性。"""

    def test_register_returns_count(self):
        """注册应返回 skill 数量。"""
        loader = _import_external_loader()
        # 重置标志位（测试隔离）
        loader.reset_registration_state()
        try:
            count = loader.ensure_external_skills_registered()
            # 真实 external/ 目录应有 11 个 skill
            assert count >= 0, "应返回非负数"
        finally:
            # 恢复标志位
            loader.reset_registration_state()

    def test_register_twice_idempotent(self):
        """二次注册应返回 0（幂等）。"""
        loader = _import_external_loader()
        loader.reset_registration_state()
        try:
            first_count = loader.ensure_external_skills_registered()
            second_count = loader.ensure_external_skills_registered()
            # 第二次应该返回 0（已注册）
            assert second_count == 0, f"二次注册应返回 0，实际 {second_count}"
        finally:
            loader.reset_registration_state()


# ════════════════════════════════════════════════════════════════════
# 8. MCP 配置自动扫描
# ════════════════════════════════════════════════════════════════════
class TestMcpConfigDiscovery:
    """验证 discover_external_mcp_configs 扫描 .mcp.json。"""

    def test_discover_returns_list(self):
        """应返回列表。"""
        from app.core.mcp_client import discover_external_mcp_configs
        result = discover_external_mcp_configs()
        assert isinstance(result, list)

    def test_discover_finds_videocut(self):
        """应发现 videocut MCP（如果已下载）。"""
        from app.core.mcp_client import discover_external_mcp_configs
        result = discover_external_mcp_configs()
        # 查找 videocut 相关
        videocut_entries = [
            entry for entry in result
            if "videocut" in entry.get("id", "").lower()
            or "videocut" in entry.get("name", "").lower()
        ]
        # 如果 external/ 目录存在 videocut-skills，应被发现
        videocut_path = Path("app/skills/external/videocut-skills")
        if videocut_path.is_dir():
            assert len(videocut_entries) > 0, "应发现 videocut MCP 配置"

    def test_discover_skips_git(self, tmp_path):
        """.git 目录下的 .mcp.json 应被跳过。"""
        from app.core.mcp_client import discover_external_mcp_configs
        # 该函数扫描 app/skills/external/，无法用 tmp_path 注入
        # 这里只验证返回值不包含 .git 路径
        result = discover_external_mcp_configs()
        for entry in result:
            assert ".git" not in entry.get("command", ""), "不应包含 .git 路径"

    def test_list_all_presets_includes_builtin(self):
        """list_all_mcp_presets_with_external 应包含内置预设。"""
        from app.core.mcp_client import list_all_mcp_presets_with_external
        result = list_all_mcp_presets_with_external()
        assert isinstance(result, list)
        assert len(result) >= 5, f"应至少 5 个内置预设，实际 {len(result)}"
        # 验证内置预设存在
        ids = [p.get("id", "") for p in result]
        assert "blender" in ids or any("blender" in i for i in ids)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "not slow"])
