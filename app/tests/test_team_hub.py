# -*- coding: utf-8 -*-
"""团队协作中枢（2026-10-31）：版本冲突 / 编辑锁 / 交接 / HTTP 端到端。

不碰 GPU、不起 Qt —— 纯存储 + 本地 HTTP，秒级可跑。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from app.core.team_hub import ConflictError, Hub, LockedError, TeamError
from app.core.team_server import TeamServer


@pytest.fixture()
def hub(tmp_path):
    return Hub(str(tmp_path / "team"))


def _bundle(marker="v1"):
    return {"id": "proj_1", "nodes": [{"id": "n1", "type": "shot", "data": {"marker": marker}}], "edges": []}


# ── 纯逻辑 ──────────────────────────────────────────────
def test_member_register_and_auth(hub):
    m = hub.register_member("张三")
    assert m["member_id"].startswith("m_")
    assert hub.auth(m["token"])["name"] == "张三"
    assert hub.auth("wrong") is None
    # 库里不该有明文令牌
    with open(hub.db_path, "rb") as f:
        raw = f.read()
    assert m["token"].encode() not in raw


def test_create_and_get_bundle_roundtrip(hub):
    m = hub.register_member("张三")
    created = hub.create_project("短剧A", m["member_id"], _bundle("v1"))
    got = hub.get_bundle(created["project_id"])
    assert got["rev"] == 1
    assert got["bundle"]["nodes"][0]["data"]["marker"] == "v1"


def test_push_conflict_is_explicit_not_silent(hub):
    """base_rev 落后 ⇒ 必须 Conflict（画布绝不自动 merge）。"""
    a = hub.register_member("张三")
    b = hub.register_member("李四")
    pid = hub.create_project("短剧A", a["member_id"], _bundle("v1"))["project_id"]
    hub.push(pid, a["member_id"], _bundle("v2"), base_rev=1)      # rev → 2
    with pytest.raises(ConflictError) as ei:
        hub.push(pid, b["member_id"], _bundle("v3"), base_rev=1)
    assert ei.value.current_rev == 2
    assert "张三" in ei.value.author      # 提示里带"谁改的"


def test_claim_lock_and_expiry(hub):
    a = hub.register_member("张三")
    b = hub.register_member("李四")
    pid = hub.create_project("短剧A", a["member_id"], _bundle())["project_id"]
    hub.claim(pid, a["member_id"], ttl=60)
    with pytest.raises(LockedError):
        hub.claim(pid, b["member_id"], ttl=60)
    # 自己续租不算冲突
    hub.claim(pid, a["member_id"], ttl=60)
    hub.release(pid, a["member_id"])
    hub.claim(pid, b["member_id"], ttl=60)     # 释放后别人能拿


def test_claim_expired_can_be_taken(hub, monkeypatch):
    a = hub.register_member("张三")
    b = hub.register_member("李四")
    pid = hub.create_project("短剧A", a["member_id"], _bundle())["project_id"]
    hub.claim(pid, a["member_id"], ttl=30)
    # 时间前进 1 小时：过期锁不该继续挡人
    import app.core.team_hub as TH
    real_now = TH._now
    monkeypatch.setattr(TH, "_now", lambda: real_now() + 3600)
    hub.claim(pid, b["member_id"], ttl=30)


def test_handoff_releases_lock_and_fills_inbox(hub):
    a = hub.register_member("张三")
    b = hub.register_member("李四")
    pid = hub.create_project("短剧A", a["member_id"], _bundle())["project_id"]
    hub.claim(pid, a["member_id"], ttl=600)
    hid = hub.handoff(pid, a["member_id"], b["member_id"], "这版的第 3 卡我调好了")["handoff_id"]
    assert hub.inbox(b["member_id"])[0]["project_name"] == "短剧A"
    # 交接即释放锁：接手方能立刻认领
    hub.claim(pid, b["member_id"], ttl=60)
    hub.ack_handoff(hid, b["member_id"])
    assert hub.inbox(b["member_id"]) == []
    with pytest.raises(TeamError):
        hub.ack_handoff(hid, a["member_id"])   # 不能确认别人的交接


def test_bundle_too_large_rejected(hub, monkeypatch):
    import app.core.team_hub as TH
    monkeypatch.setattr(TH, "MAX_BUNDLE_BYTES", 64)
    m = hub.register_member("张三")
    with pytest.raises(TeamError) as ei:
        hub.create_project("大工程", m["member_id"], {"nodes": ["x" * 200]})
    assert ei.value.code == "too_large"


# ── HTTP 端到端 ─────────────────────────────────────────
def _req(base, path, payload=None, token="", method=None):
    url = base + path
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method or ("POST" if data else "GET"))
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def test_http_end_to_end(tmp_path):
    srv = TeamServer(str(tmp_path / "team"), host="127.0.0.1", port=0, name="测试团队")
    info = srv.start()
    base = "http://127.0.0.1:%d" % info["port"]
    try:
        code, ping = _req(base, "/team/ping")
        assert code == 200 and ping["service"] == "shiguang-team-hub"

        code, a = _req(base, "/team/join", {"name": "张三"})
        assert code == 200 and a["token"]
        code, b = _req(base, "/team/join", {"name": "李四"})
        assert code == 200

        # 未带令牌 ⇒ 401
        code, _ = _req(base, "/team/projects")
        assert code == 401

        code, created = _req(base, "/team/projects", {"name": "短剧A", "bundle": _bundle("v1")}, a["token"])
        assert code == 200
        pid = created["project_id"]

        code, pulled = _req(base, "/team/projects/" + pid, token=b["token"])
        assert code == 200 and pulled["bundle"]["nodes"][0]["data"]["marker"] == "v1"

        code, pushed = _req(base, "/team/projects/%s/push" % pid,
                            {"bundle": _bundle("v2"), "base_rev": 1}, a["token"])
        assert code == 200 and pushed["rev"] == 2

        # 李四拿着旧 rev 推 ⇒ 409 + 谁改的
        code, conf = _req(base, "/team/projects/%s/push" % pid,
                          {"bundle": _bundle("v3"), "base_rev": 1}, b["token"])
        assert code == 409 and conf["code"] == "conflict" and conf["author"] == "张三"

        # 张三认领，李四被 423 挡
        code, _ = _req(base, "/team/projects/%s/claim" % pid, {"ttl": 60}, a["token"])
        assert code == 200
        code, locked = _req(base, "/team/projects/%s/claim" % pid, {"ttl": 60}, b["token"])
        assert code == 423 and locked["holder"] == "张三"

        # 交接给李四 → 李四 inbox 有单 → 能立刻认领
        code, _ = _req(base, "/team/projects/%s/handoff" % pid,
                       {"to": b["member_id"], "message": "第三卡改好了"}, a["token"])
        assert code == 200
        code, inbox = _req(base, "/team/inbox", token=b["token"])
        assert code == 200 and inbox["items"][0]["message"] == "第三卡改好了"
        code, _ = _req(base, "/team/projects/%s/claim" % pid, {"ttl": 60}, b["token"])
        assert code == 200
    finally:
        srv.stop()
