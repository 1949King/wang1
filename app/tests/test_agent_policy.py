# -*- coding: utf-8 -*-
"""Policy Engine：Plan / B / C 矩阵与重试边界。"""
from app.core.agent_policy import (
    DECISION_ALLOW,
    DECISION_DENY,
    DECISION_REQUIRE_APPROVAL,
    EFFECT_CANVAS_WRITE,
    EFFECT_READ,
    MODE_AUTONOMOUS,
    MODE_COLLABORATIVE,
    MODE_PLAN,
    can_auto_retry,
    decide,
    memory_content_allowed,
    normalize_mode,
    sanitize_for_log,
    tools_visible_to_model,
)
from app.core.agent_context import compress_messages


def test_normalize_legacy_execute_is_collaborative():
    assert normalize_mode("execute") == MODE_COLLABORATIVE
    assert normalize_mode("B") == MODE_COLLABORATIVE
    assert normalize_mode("plan") == MODE_PLAN
    assert normalize_mode("C") == MODE_AUTONOMOUS


def test_plan_denies_canvas_write():
    d = decide(tool_id="addNode", mode=MODE_PLAN)
    assert d.action == DECISION_DENY
    assert d.effect == EFFECT_CANVAS_WRITE


def test_plan_user_confirm_allows_write():
    d = decide(tool_id="addNode", mode=MODE_PLAN, approved=True)
    assert d.action == DECISION_ALLOW


def test_plan_allows_query():
    d = decide(tool_id="queryNodes", mode=MODE_PLAN)
    assert d.action == DECISION_ALLOW
    assert d.effect == EFFECT_READ


def test_collaborative_write_needs_approval():
    d = decide(tool_id="deleteNode", mode=MODE_COLLABORATIVE)
    assert d.action == DECISION_REQUIRE_APPROVAL
    d2 = decide(tool_id="deleteNode", mode=MODE_COLLABORATIVE, approved=True)
    assert d2.action == DECISION_ALLOW


def test_autonomous_allows_media_but_no_retry():
    d = decide(tool_id="runGenerate", mode=MODE_AUTONOMOUS)
    assert d.action == DECISION_ALLOW
    assert d.paid is True
    assert can_auto_retry(effect=d.effect, paid=d.paid, attempt=0) is False


def test_read_retry_cap():
    assert can_auto_retry(effect=EFFECT_READ, paid=False, attempt=0) is True
    assert can_auto_retry(effect=EFFECT_READ, paid=False, attempt=2) is True
    assert can_auto_retry(effect=EFFECT_READ, paid=False, attempt=3) is False
    assert can_auto_retry(effect=EFFECT_READ, paid=True, attempt=0) is False


def test_unregistered_tool_treated_as_write():
    d = decide(tool_id="invented_delete_all", mode=MODE_PLAN)
    assert d.action == DECISION_DENY


def test_plan_hides_write_tools():
    vis = tools_visible_to_model(MODE_PLAN)
    assert "queryNodes" in vis
    assert "addNode" not in vis
    assert "editor.get_timeline_context" in vis
    assert "editor.split_clip" not in vis


def test_sanitize_redacts_secrets_and_paths():
    out = sanitize_for_log({"api_key": "sk-secret", "note": "ok", "path": r"C:\Users\x\a.mp4"})
    assert out["api_key"] == "[redacted]"
    assert out["note"] == "ok"
    assert out["path"] == "[path]"


def test_memory_rejects_keys():
    ok, _ = memory_content_allowed({"pref": "竖屏"})
    assert ok
    bad, reason = memory_content_allowed({"api_key": "sk-1"})
    assert not bad
    assert "密钥" in reason


def test_compress_keeps_system_and_tail():
    msgs = [{"role": "system", "content": "sys"}]
    for i in range(20):
        msgs.append({"role": "user", "content": ("目标约束决定 " + str(i)) * 80})
        msgs.append({"role": "assistant", "content": ("节点 n1 失败原因 " + str(i)) * 80})
    out = compress_messages(msgs, max_chars=2000, keep_tail=4)
    assert out[0]["role"] == "system"
    assert any("压缩上下文" in str(m.get("content")) for m in out)
    assert len(str(out)) < len(str(msgs))
