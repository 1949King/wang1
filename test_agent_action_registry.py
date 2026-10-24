"""agent_action_registry：白名单与提示词同源、SkillEngine.list_all 可用。"""
from __future__ import annotations


def test_allowed_actions_cover_ripple_and_answer():
    from app.core.agent_action_registry import (
        get_allowed_actions,
        get_dangerous_actions,
        get_safe_actions,
        ACTION_TO_CAPABILITY,
        build_agent_actions_prompt_line,
    )

    allowed = get_allowed_actions()
    assert "answer" in allowed
    assert "ripple_delete_range" in allowed
    assert "suggest_cleanup" in allowed
    assert "add_clip" not in allowed
    assert get_dangerous_actions() <= allowed
    assert get_safe_actions() <= allowed
    assert ACTION_TO_CAPABILITY["split_clip"] == "editor.split_clip"
    assert ACTION_TO_CAPABILITY["ripple_delete_range"] == "editor.ripple_delete_range"
    line = build_agent_actions_prompt_line()
    assert "ripple_delete_range" in line
    assert "remove_clip" in line


def test_ai_agent_panel_whitelist_matches_registry():
    from app.core.agent_action_registry import get_allowed_actions
    from app.modules.lego.ai_agent_panel import _AGENT_ALLOWED_ACTIONS

    assert _AGENT_ALLOWED_ACTIONS == get_allowed_actions()


def test_skill_engine_has_list_all():
    from app.modules.lego.skill_engine import skill_engine

    assert hasattr(skill_engine, "list_all")
    skills = skill_engine.list_all()
    assert isinstance(skills, list)


def test_opentake_gap_table_has_blocked_add_clips():
    from app.core.agent_action_registry import list_opentake_gaps, build_clipskills_layers_block

    gaps = {r["opentake"]: r["status"] for r in list_opentake_gaps()}
    assert gaps.get("add_clips") == "blocked"
    assert gaps.get("split_clip") == "ok"
    assert "L0" in build_clipskills_layers_block()


def test_memory_project_context_roundtrip(tmp_path, monkeypatch):
    import app.core.memory_store as ms

    monkeypatch.setattr(ms, "_STORAGE_PATH", str(tmp_path / "agent_memory.jsonl"))
    ms.MemoryStore._instance = None
    store = ms.MemoryStore.get_instance()
    store.set_project_context(drama_title="逆袭", episode="3", platform="douyin", notes="竖屏")
    ctx = store.get_project_context()
    assert ctx["drama_title"] == "逆袭"
    assert ctx["episode"] == "3"
    blob = store.get_agent_context()
    assert "逆袭" in blob and "多集" in blob


def test_ensure_active_provider_sensible_callable():
    from app.modules.lego.model_config import ensure_active_provider_sensible, load_active_provider

    pid = ensure_active_provider_sensible()
    assert isinstance(pid, str)
    assert isinstance(load_active_provider(), str)
