# -*- coding: utf-8 -*-
"""Policy Engine：Plan / B / C 矩阵与重试边界。"""
from unittest.mock import Mock

from app.core.capability_dispatcher import (
    CapabilityCategory,
    CapabilityDispatcher,
    CapabilityRequest,
    CapabilityResult,
)
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
    d2 = decide(tool_id="queryTimeline", mode=MODE_PLAN)
    assert d2.action == DECISION_ALLOW
    d3 = decide(tool_id="editor.suggest_canvas_roundtrip", mode=MODE_PLAN)
    assert d3.action == DECISION_ALLOW


def test_send_to_canvas_needs_confirm_in_collaborative():
    d = decide(tool_id="editor.send_selected_to_canvas", mode=MODE_COLLABORATIVE)
    assert d.action == DECISION_REQUIRE_APPROVAL


def test_collaborative_batch_generate_needs_approval():
    d = decide(tool_id="batchGenerate", mode=MODE_COLLABORATIVE)
    assert d.action == DECISION_REQUIRE_APPROVAL
    d2 = decide(tool_id="batchGenerate", mode=MODE_COLLABORATIVE, approved=True)
    assert d2.action == DECISION_ALLOW
    d3 = decide(tool_id="canvas_breakdown", mode=MODE_PLAN)
    assert d3.action == DECISION_DENY


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


def test_dispatcher_policy_exception_fails_closed(monkeypatch):
    """策略判断自身异常时必须拒绝执行，不能让写能力绕过审批链。"""
    dispatcher = object.__new__(CapabilityDispatcher)
    dispatcher._initialized = False
    CapabilityDispatcher.__init__(dispatcher)
    dispatcher._builtin_registered = True
    dispatcher._memory = Mock()
    dispatcher._safe_emit = Mock()
    handler = Mock(return_value=CapabilityResult(request_id="policy-error", success=True))
    dispatcher.register("editor.split_clip", CapabilityCategory.EDITOR, handler)

    def _raise_policy_error(**_kwargs):
        raise RuntimeError("policy unavailable")

    monkeypatch.setattr("app.core.agent_policy.decide", _raise_policy_error)
    monkeypatch.setattr("app.core.agent_brain.agent_brain.activate", Mock())
    result = dispatcher.invoke(CapabilityRequest(
        request_id="policy-error",
        capability_id="editor.split_clip",
        caller="agent_loop",
        agent_mode=MODE_COLLABORATIVE,
    ))

    assert result.success is False
    assert "策略校验失败" in result.error
    handler.assert_not_called()
