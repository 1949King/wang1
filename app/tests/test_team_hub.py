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


# ── 附件归属与封面（2026-11-02 · 第三刀）──────────────────
def test_asset_owner_and_poster_roundtrip(hub):
    """封面也是一张附件，但**不进列表**；归属 `镜 03` 随附件存下来。"""
    m = hub.register_member("张三")
    pid = hub.create_project("工程", m["member_id"], {"nodes": []})["project_id"]

    poster = hub.save_asset(pid, m["member_id"], "成片.mp4.jpg", b"jpegbytes",
                           "image", "image/jpeg", owner="镜 03")
    vid = hub.save_asset(pid, m["member_id"], "成片.mp4", b"v" * 4096,
                         "video", "video/mp4", owner="镜 03", poster=poster["sha256"])

    rows = hub.list_assets(pid)
    assert [r["sha256"] for r in rows] == [vid["sha256"]], "封面不该单独列成一行"
    assert rows[0]["owner"] == "镜 03"
    assert rows[0]["poster"] == poster["sha256"]
    # 不列 ≠ 删掉：同事的缩略图还得按 sha 取到这张 JPEG
    assert hub.asset_path_of(pid, poster["sha256"])[1]["name"] == "成片.mp4.jpg"


def test_asset_empty_owner_does_not_wipe_existing(hub):
    """同一份素材被多个节点引用：后一次没带归属，不能把前一次记的抹掉。"""
    m = hub.register_member("张三")
    pid = hub.create_project("工程", m["member_id"], {"nodes": []})["project_id"]

    poster = hub.save_asset(pid, m["member_id"], "p.jpg", b"jpeg", "image", owner="镜 03")
    hub.save_asset(pid, m["member_id"], "成片.mp4", b"v" * 64, "video",
                   owner="镜 03", poster=poster["sha256"])
    hub.save_asset(pid, m["member_id"], "成片.mp4", b"v" * 64, "video")   # 什么都没带

    row = hub.list_assets(pid)[0]
    assert row["owner"] == "镜 03" and row["poster"] == poster["sha256"]


def test_asset_columns_migrated_on_old_db(tmp_path):
    """老库（asset 表没有 owner/poster 列）打开时自动补列，且不丢已有附件。"""
    import sqlite3

    root = str(tmp_path / "team")
    os.makedirs(root, exist_ok=True)
    conn = sqlite3.connect(os.path.join(root, "team.db"))
    conn.executescript(
        "CREATE TABLE asset (project_id TEXT NOT NULL, sha256 TEXT NOT NULL,"
        " name TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL DEFAULT 'file',"
        " mime TEXT NOT NULL DEFAULT '', bytes INTEGER NOT NULL,"
        " author_id TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL,"
        " PRIMARY KEY (project_id, sha256));"
    )
    conn.execute("INSERT INTO asset VALUES ('p_old','s_old','老附件.png','image','image/png',10,'',0)")
    conn.commit()
    conn.close()

    hub2 = Hub(root)          # 打开即迁移
    with sqlite3.connect(os.path.join(root, "team.db")) as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(asset)").fetchall()}
    assert {"owner", "poster"} <= cols
    assert len(hub2.list_assets("p_old")) == 1, "补列不能把老数据弄丢"


# ── 版本差异（2026-11-02）────────────────────────────────
def _bundle_for_diff(title="片子"):
    return {
        "dramaTitle": title,
        "nodes": [
            {"id": "n1", "type": "shot", "data": {"title": "镜 01", "prompt": "a"}},
            {"id": "n2", "type": "shot", "data": {"title": "镜 02", "prompt": "b"}},
            {"id": "n3", "type": "script", "data": {"title": "剧本"}},
        ],
        "edges": [{"id": "e1", "source": "n1", "target": "n2"}],
        "timeline": {"clips": [{"id": "c1", "path": "/a.mp4"}, {"id": "c2", "path": "/b.mp4"}]},
    }


def test_diff_bundle_counts_nodes_edges_timeline():
    from app.core.team_hub import diff_bundle

    old = _bundle_for_diff("旧名")
    new = {
        "dramaTitle": "新名",
        "nodes": [
            {"id": "n1", "type": "shot", "data": {"title": "镜 01", "prompt": "a"}},      # 没动
            {"id": "n2", "type": "shot", "data": {"title": "镜 02", "prompt": "b2"}},     # 改了
            {"id": "n4", "type": "video", "data": {"title": "镜 04"}},                    # 新增
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "n2"},
            {"id": "e2", "source": "n2", "target": "n4"},
        ],
        "timeline": {"clips": [{"id": "c1", "path": "/a.mp4"}, {"id": "c3", "path": "/c.mp4"}]},
    }
    d = diff_bundle(old, new)
    assert d["nodes"]["added"] == 1
    assert d["nodes"]["removed"] == 1
    assert d["nodes"]["changed"] == 1
    assert d["nodes"]["added_titles"] == ["镜 04"]
    assert d["nodes"]["removed_titles"] == ["剧本"]
    assert d["nodes"]["changed_titles"] == ["镜 02"]
    assert d["edges"] == {"added": 1, "removed": 0}
    assert d["timeline"] == {"before": 2, "after": 2, "added": 1, "removed": 1, "changed": 0}
    assert d["title"]["changed"] is True and d["title"]["before"] == "旧名"


def test_diff_ignores_ui_noise():
    """拖动 / 选中 / 测量值变化**不算**改内容 —— 否则一拉就是满屏假差异。"""
    from app.core.team_hub import diff_bundle

    old = {"nodes": [{"id": "n1", "position": {"x": 1, "y": 2}, "selected": False,
                      "measured": {"width": 240}, "data": {"title": "A", "prompt": "p"}}]}
    new = {"nodes": [{"id": "n1", "position": {"x": 99.5, "y": 8.25}, "selected": True,
                      "measured": {"width": 241}, "data": {"title": "A", "prompt": "p"}}]}
    assert diff_bundle(old, new)["nodes"]["changed"] == 0
    # 内容真变了才算
    new["nodes"][0]["data"]["prompt"] = "p2"
    assert diff_bundle(old, new)["nodes"]["changed"] == 1


def test_diff_empty_and_garbage_input():
    from app.core.team_hub import diff_bundle

    d = diff_bundle(_bundle_for_diff(), _bundle_for_diff())
    assert d["nodes"] == {"added": 0, "removed": 0, "changed": 0,
                          "added_titles": [], "removed_titles": [], "changed_titles": []}
    # 任意垃圾输入不炸（服务端可能读到半截写坏的文件）
    for bad in (None, {}, {"nodes": "not a list"}, {"nodes": [1, 2, None]}):
        assert diff_bundle(bad, bad)["nodes"]["added"] == 0


def test_hub_diff_between_revs(hub):
    m = hub.register_member("张三")
    pid = hub.create_project("片子", m["member_id"], _bundle_for_diff("v1"))["project_id"]
    new = _bundle_for_diff("v2")
    new["nodes"][1]["data"]["prompt"] = "改过了"
    hub.push(pid, m["member_id"], new, base_rev=1)

    d = hub.diff(pid, 1, 2)
    assert d["from_rev"] == 1 and d["to_rev"] == 2 and d["revisions"] == 1
    assert d["same"] is False and d["nodes"]["changed"] == 1

    # 同版本 ⇒ same，不做无意义比较
    same = hub.diff(pid, 2, 2)
    assert same["same"] is True and same["revisions"] == 0

    # 都不指定 ⇒ 自动取最近两版
    auto = hub.diff(pid, 0, 0)
    assert auto["from_rev"] == 1 and auto["to_rev"] == 2

    # 只给 from ⇒ to 取最新
    only_from = hub.diff(pid, 1, 0)
    assert only_from["to_rev"] == 2

    # 版本不存在 ⇒ 如实报
    with pytest.raises(TeamError) as ei:
        hub.diff(pid, 1, 99)
    assert ei.value.code == "not_found"


def test_diff_endpoint_rejects_bad_query(tmp_path):
    """from/to 写坏了按「不指定」处理，不是 500 —— 别让人去猜服务端怎么了。"""
    srv = TeamServer(str(tmp_path / "team"), host="127.0.0.1", port=0)
    info = srv.start()
    base = "http://127.0.0.1:%d" % info["port"]
    try:
        _, a = _req(base, "/team/join", {"name": "张三"})
        _, created = _req(base, "/team/projects", {"name": "片", "bundle": _bundle_for_diff("v1")}, a["token"])
        pid = created["project_id"]
        hub = srv.hub
        hub.push(pid, a["member_id"], _bundle_for_diff("v2"), base_rev=1)

        code, d = _req(base, "/team/projects/%s/diff?from=1&to=2" % pid, token=a["token"])
        assert code == 200 and d["title"]["changed"] is True and d["revisions"] == 1

        code, bad = _req(base, "/team/projects/" + pid + "/diff?from=abc&to=xxx", token=a["token"])
        assert code == 200 and bad["from_rev"] == 1 and bad["to_rev"] == 2

        # 没令牌 ⇒ 401（差异里含节点标题，不能裸奔）
        code, _ = _req(base, "/team/projects/%s/diff" % pid)
        assert code == 401
    finally:
        srv.stop()


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


def test_asset_http_owner_and_poster(tmp_path):
    """HTTP 层：`?owner=`（含中文，URL 编码）与 `?poster=` 落库；封面不进列表。

    单独守一遍是因为这一层最容易漏：`parse_qs` 解出来的中文要 `unquote`、
    poster 要正则校验、列表要过滤 —— 任何一步写错，前端拿到的就是空归属，
    而界面上只表现为「没显示来自哪个镜」，静默得没人会发现。
    """
    srv = TeamServer(str(tmp_path / "team"), host="127.0.0.1", port=0)
    info = srv.start()
    base = "http://127.0.0.1:%d" % info["port"]
    try:
        _, a = _req(base, "/team/join", {"name": "导演A"})
        token = a["token"]
        _, created = _req(base, "/team/projects", {"name": "成片", "bundle": {"nodes": []}}, token)
        pid = created["project_id"]
        owner = urllib.parse.quote("镜 03")

        _, poster, _h = _raw_req(
            base, "/team/projects/%s/assets?name=p.jpg&kind=image&owner=%s" % (pid, owner),
            b"jpegbytes", token, headers={"Content-Type": "image/jpeg"},
        )
        assert poster["ok"] is True and poster["owner"] == "镜 03"

        _, vid, _h = _raw_req(
            base,
            "/team/projects/%s/assets?name=%s&kind=video&owner=%s&poster=%s"
            % (pid, urllib.parse.quote("成片.mp4"), owner, poster["sha256"]),
            b"v" * 4096, token, headers={"Content-Type": "video/mp4"},
        )
        assert vid["ok"] is True and vid["poster"] == poster["sha256"]

        _, listed = _req(base, "/team/projects/%s/assets" % pid, None, token)
        names = [x["name"] for x in listed["assets"]]
        assert names == ["成片.mp4"], "封面不该出现在列表里"
        assert listed["assets"][0]["owner"] == "镜 03"

        # 非法 poster（不是 64 位 sha）当没给，不能写进库
        _, bad, _h = _raw_req(
            base,
            "/team/projects/%s/assets?name=%s&kind=video&poster=not-a-sha"
            % (pid, urllib.parse.quote("另一个.mp4")),
            b"w" * 128, token, headers={"Content-Type": "video/mp4"},
        )
        assert bad["ok"] is True and bad["poster"] == ""
    finally:
        srv.stop()


# ── 配对码（2026-11-02）────────────────────────────────
#
# 这套东西替掉「手填 IP」。它自己的安全边界必须锁死：
# 一次性（用过即废）、120 秒寿命、复用未过期的码（同一台机器连点两次不该出两个号）。
def test_pairing_reused_while_alive(hub):
    host = hub.register_member("主机")
    first = hub.create_pairing(host["member_id"])
    again = hub.create_pairing(host["member_id"])
    assert first["reused"] is False and again["reused"] is True
    assert first["code"] == again["code"]
    assert len(first["code"]) == 6 and first["code"].isdigit()
    # 换个成员要换号：码是「谁发的」，不能借用别人的
    other = hub.register_member("另一位")
    assert hub.create_pairing(other["member_id"])["code"] != first["code"]


def test_pairing_claim_is_one_shot(hub):
    host = hub.register_member("主机")
    code = hub.create_pairing(host["member_id"])["code"]
    assert hub.pairing_alive(code) is True

    got = hub.pairing_claim(code, "m_guest")
    assert got["code"] == code and got["created_by"] == host["member_id"]
    # 兑换即作废：同一张码不许换第二个成员
    assert hub.pairing_alive(code) is False
    with pytest.raises(TeamError) as ei:
        hub.pairing_claim(code, "m_other")
    assert ei.value.code == "code_used"


def test_pairing_expired_and_unknown(hub, monkeypatch):
    host = hub.register_member("主机")
    code = hub.create_pairing(host["member_id"])["code"]

    with pytest.raises(TeamError) as bad:
        hub.pairing_claim("000000")
    assert bad.value.code == "bad_code"

    # 把时钟推过 TTL（create_pairing 内部会把 ttl 下限夹到 30 秒，所以只能拨表）
    from app.core import team_hub as H

    later = H._now() + H.PAIR_TTL + 1
    monkeypatch.setattr(H, "_now", lambda: later)
    assert hub.pairing_alive(code) is False
    with pytest.raises(TeamError) as gone:
        hub.pairing_claim(code)
    assert gone.value.code == "code_expired"


def test_pair_http_needs_no_token_but_only_once(tmp_path):
    """`/team/pair` 是**唯一**不需要令牌的团队端点 —— 它就是拿码换令牌的那一条。"""
    srv = TeamServer(str(tmp_path / "team"), host="127.0.0.1", port=0)
    info = srv.start()
    base = "http://127.0.0.1:%d" % info["port"]
    try:
        _, host = _req(base, "/team/join", {"name": "主机"})
        code, p = _req(base, "/team/pairing", {}, host["token"])
        assert code == 200 and len(p["code"]) == 6
        assert p["address"].startswith("http://") and "/pair?code=" in p["pair_url"]
        assert p["qr"].startswith("data:image/png;base64,")
        assert p["expires_at"] > 0

        # 手机落地页：能看到地址和码，且明确说码还有效
        page = urllib.request.urlopen(base + "/pair?code=" + p["code"], timeout=10).read().decode()
        assert "配对码有效" in page and p["code"] in page

        # 刷新面板不该换号：还没过期就原样复用（否则刚念出去的码会白费）
        code, back = _req(base, "/team/pairing", token=host["token"])
        assert code == 200 and back["code"] == p["code"] and back["reused"] is True

        # 无令牌兑换成功，拿到的是一个能用的令牌
        code, joined = _req(base, "/team/pair", {"code": p["code"], "name": "同事B"})
        assert code == 200 and joined["paired"] is True
        assert srv.hub.auth(joined["token"])["name"] == "同事B"

        # 第二个人拿同一张码再来 ⇒ 拒（一次性）
        code, dup = _req(base, "/team/pair", {"code": p["code"], "name": "同事C"})
        assert code >= 400 and dup["code"] == "code_used"

        # 手机落地页此时要如实说失效了（地址照旧有用）
        page2 = urllib.request.urlopen(base + "/pair?code=" + p["code"], timeout=10).read().decode()
        assert "已失效" in page2

        # 码作废之后再要：必须给新号，不能把用过的号再发出去
        code, fresh = _req(base, "/team/pairing", token=host["token"])
        assert code == 200 and fresh["code"] and fresh["code"] != p["code"] and fresh["reused"] is False
    finally:
        srv.stop()
