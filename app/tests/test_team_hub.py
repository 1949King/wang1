# -*- coding: utf-8 -*-
"""团队协作中枢（2026-10-31）：版本冲突 / 编辑锁 / 交接 / HTTP 端到端。

不碰 GPU、不起 Qt —— 纯存储 + 本地 HTTP，秒级可跑。
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
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


# ── 附件（视频 / 图片 / 音频 · 2026-11-02）──────────────
def test_asset_save_dedup_and_delete(hub):
    """同内容只落一份盘；删登记时**全表无引用**才真删字节。"""
    m = hub.register_member("张三")
    pid = hub.create_project("成片工程", m["member_id"], {"nodes": []})["project_id"]

    a = hub.save_asset(pid, m["member_id"], "成片.mp4", b"x" * 2048, "video", "video/mp4")
    b = hub.save_asset(pid, m["member_id"], "成片副本.mp4", b"x" * 2048, "video", "video/mp4")
    assert a["sha256"] == b["sha256"]              # 内容哈希去重
    assert len(os.listdir(hub.blobs_dir)) == 1     # 盘上只有一个文件
    assert hub.stats()["assets"] == 1              # 同 (project, sha) 只一行

    path, row = hub.asset_path_of(pid, a["sha256"])
    assert os.path.getsize(path) == 2048 and row["mime"] == "video/mp4"

    # 另一个项目也挂同一份 ⇒ 删掉其中一个不能把字节删了
    pid2 = hub.create_project("另一个", m["member_id"], {"nodes": []})["project_id"]
    hub.save_asset(pid2, m["member_id"], "成片.mp4", b"x" * 2048, "video", "video/mp4")
    assert hub.delete_asset(pid, a["sha256"])["removed"] is False
    assert len(os.listdir(hub.blobs_dir)) == 1
    assert hub.delete_asset(pid2, a["sha256"])["removed"] is True
    assert os.listdir(hub.blobs_dir) == []


def test_asset_rejects_empty_oversize_and_traversal(hub, monkeypatch):
    m = hub.register_member("张三")
    pid = hub.create_project("工程", m["member_id"], {"nodes": []})["project_id"]

    with pytest.raises(TeamError) as ei:
        hub.save_asset(pid, m["member_id"], "空.mp4", b"", "video")
    assert ei.value.code == "bad_asset"   # 0 字节不登记，免得同事点开是白屏

    import app.core.team_hub as TH
    monkeypatch.setattr(TH, "MAX_ASSET_BYTES", 16)
    with pytest.raises(TeamError) as ei:
        hub.save_asset(pid, m["member_id"], "大.mp4", b"x" * 100, "video")
    assert ei.value.code == "too_large"
    monkeypatch.undo()

    # 目录穿透：名字里的 ../ 不进路径，且后缀只认白名单
    bad = hub.save_asset(pid, m["member_id"], "../../../evil.sh", b"bad", "file")
    path, _ = hub.asset_path_of(pid, bad["sha256"])
    assert os.path.dirname(path) == hub.blobs_dir
    assert path.endswith(".bin")           # .sh 不在白名单 ⇒ 落 .bin

    with pytest.raises(TeamError) as ei:
        hub.asset_path_of(pid, "f" * 64)
    assert ei.value.code == "not_found"


def test_asset_missing_blob_reports_not_found(hub):
    """登记还在、字节被手删 ⇒ 如实报 404，绝不回空内容。"""
    m = hub.register_member("张三")
    pid = hub.create_project("工程", m["member_id"], {"nodes": []})["project_id"]
    a = hub.save_asset(pid, m["member_id"], "a.png", b"img", "image", "image/png")
    path, _ = hub.asset_path_of(pid, a["sha256"])
    os.remove(path)
    with pytest.raises(TeamError) as ei:
        hub.asset_path_of(pid, a["sha256"])
    assert ei.value.code == "not_found" and "丢失" in ei.value.message


def _raw_req(base, path, data=b"", token="", method="POST", headers=None):
    """原始请求：成功时能解析成 JSON 就回 dict，否则回 bytes（下载附件用）。"""
    req = urllib.request.Request(base + path, data=(data or None), method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            try:
                return resp.status, json.loads(raw.decode()), dict(resp.headers)
            except Exception:
                return resp.status, raw, dict(resp.headers)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw.decode()), dict(e.headers)
        except Exception:
            return e.code, raw, dict(e.headers)


def test_asset_http_roundtrip(tmp_path):
    """上传 → 列表 → 取字节（含 `?token=` 与 Range）→ 删除。"""
    srv = TeamServer(str(tmp_path / "team"), host="127.0.0.1", port=0)
    info = srv.start()
    base = "http://127.0.0.1:%d" % info["port"]
    try:
        _, a = _req(base, "/team/join", {"name": "导演A"})
        token = a["token"]
        _, created = _req(base, "/team/projects", {"name": "成片", "bundle": {"nodes": []}}, token)
        pid = created["project_id"]

        payload = bytes(range(256)) * 8192        # 2MB 伪成片
        code, up, _ = _raw_req(base, "/team/projects/%s/assets?name=%s&kind=video"
                               % (pid, urllib.parse.quote("成片终版.mp4")), payload,
                               token, headers={"Content-Type": "video/mp4"})
        assert code == 200 and up["bytes"] == len(payload) and up["kind"] == "video"
        sha = up["sha256"]

        code, lst, _ = _raw_req(base, "/team/projects/%s/assets" % pid, method="GET", token=token)
        assert code == 200 and lst["assets"][0]["name"] == "成片终版.mp4"

        # `<video src>` 带不了请求头 ⇒ 必须支持 ?token=
        code, body, hdrs = _raw_req(base, "/team/projects/%s/assets/%s?token=%s"
                                    % (pid, sha, urllib.parse.quote(token)),
                                    method="GET", headers={})
        assert code == 200 and body == payload and hdrs["Content-Type"] == "video/mp4"

        # Range：不 206 的话浏览器拖不动进度条
        code, head, hdrs = _raw_req(base, "/team/projects/%s/assets/%s?token=%s"
                                   % (pid, sha, urllib.parse.quote(token)),
                                   method="GET", headers={"Range": "bytes=0-99"})
        assert code == 206 and head == payload[:100]
        assert hdrs["Content-Range"] == "bytes 0-99/%d" % len(payload)

        # 空体 ⇒ 400 而不是悄悄存一个 0 字节附件
        code, err, _ = _raw_req(base, "/team/projects/%s/assets?name=x.mp4" % pid, b"",
                                token, headers={"Content-Type": "video/mp4"})
        assert code == 400 and err["code"] == "bad_asset"

        # 没令牌 ⇒ 401
        code, _, _ = _raw_req(base, "/team/projects/%s/assets" % pid, method="GET")
        assert code == 401

        code, dele, _ = _raw_req(base, "/team/projects/%s/assets/%s" % (pid, sha),
                                 method="DELETE", token=token)
        assert code == 200 and dele["removed"] is True
        assert os.listdir(srv.hub.blobs_dir) == []
    finally:
        srv.stop()
