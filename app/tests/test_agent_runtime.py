# -*- coding: utf-8 -*-
from app.core.agent_runtime import parse_canvas_tools
from app.core.agent_task_store import AgentTaskStore, legal_transitions


def test_parse_appended_canvas_tools():
    text, tools = parse_canvas_tools(
        '先加一个近景镜头。\n{"canvas_tools":[{"action":"addNode","params":{"kind":"shot","title":"近景"}}]}'
    )
    assert "近景" in text
    assert tools == [{"action": "addNode", "params": {"kind": "shot", "title": "近景"}}]


def test_parse_ignores_plain_chat():
    text, tools = parse_canvas_tools("这只是建议，不要改画布。")
    assert tools == []
    assert "建议" in text


def test_parse_reply_field():
    text, tools = parse_canvas_tools(
        '{"reply":"好的","canvas_tools":[{"action":"queryNodes","params":{"kind":"shot"}}]}'
    )
    assert text == "好的"
    assert tools[0]["action"] == "queryNodes"


def test_invalid_transition_raises():
    store = AgentTaskStore()
    t = store.create(session_id="test", goal="x", mode="collaborative", source="test")
    assert t["status"] == "planning"
    store.transition(t["id"], "running")
    store.transition(t["id"], "completed")
    try:
        store.transition(t["id"], "running")
        assert False, "should reject"
    except ValueError as e:
        assert "AGENT_INVALID_TRANSITION" in str(e)


def test_legal_table_has_paused_resume():
    assert "running" in legal_transitions["paused"]
    assert "stopped" in legal_transitions["running"]
