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


# ── 本机主人自动引导（2026-11-04）──────────────────────────
#
# 背景：面板出配对码要 Bearer，而令牌只存哈希取不回来 ⇒ 老流程逼用户
# 「手填自己地址 → 加入自己」才能发码，第一步就卡在 401 上。
def test_ensure_owner_bootstraps_then_rotates_token(hub):
    first = hub.ensure_owner("本机主人")
    assert first["created"] is True and first["promoted"] is False
    assert first["role"] == "owner"
    assert hub.auth(first["token"])["role"] == "owner"

    again = hub.ensure_owner("本机主人")
    assert again["created"] is False and again["promoted"] is False
    assert again["member_id"] == first["member_id"]      # 身份不变（项目归属挂在它上面）
    assert again["token"] != first["token"]
    # 换了令牌旧的就必须失效，否则等于留了一张永久后门
    assert hub.auth(first["token"]) is None
    assert hub.auth(again["token"])["id"] == first["member_id"]


def test_ensure_owner_promotes_earliest_member_instead_of_adding_one(hub):
    """老库升级：服务器那台通常就是第一个加入的人 ⇒ 提升他，别凭空多出一个「本机主人」。"""
    old = hub.register_member("王志")
    info = hub.ensure_owner("本机主人")
    assert info["promoted"] is True and info["created"] is False
    assert info["member_id"] == old["member_id"]
    assert info["name"] == "王志"        # 名字跟着成员走，不被默认名盖掉
    assert len(hub.members()) == 1       # 不能变成两个人
    assert hub.member_by_role("owner")["id"] == old["member_id"]


def test_ensure_owner_keeps_existing_owner_over_earlier_editor(hub):
    owner = hub.ensure_owner("主人")
    hub.register_member("后来的编辑")
    again = hub.ensure_owner("主人")
    assert again["member_id"] == owner["member_id"]
    assert len(hub.members()) == 2


def test_owner_cred_reuses_disk_token_and_never_mints_on_read(tmp_path):
    """盘上那张还有效就复用：换令牌 = 把主人别处的会话踢下线。

    同时守住一条：只读路径（status 每 2 秒轮询）**绝不能**顺手签发/写盘。
    """
    from app.core import canvas_routes_team as ct

    class _Srv:
        def __init__(self, hub):
            self.hub = hub

    hub = Hub(str(tmp_path / "team"))
    srv = _Srv(hub)
    first = ct._owner_cred(srv, create=True)
    assert first and first["reused"] is False
    assert os.path.isfile(os.path.join(hub.root, ct.OWNER_FILE))

    again = ct._owner_cred(srv, create=True)
    assert again["token"] == first["token"] and again["reused"] is True

    # 干净库 + create=False ⇒ 返回 None，且不许落下任何文件
    bare_root = str(tmp_path / "bare")
    assert ct._owner_cred(_Srv(Hub(bare_root))) is None
    assert not os.path.exists(os.path.join(bare_root, ct.OWNER_FILE))


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
        # 2026-11-04 起：无码 join 只能是 viewer（第一个成员自举成 owner）。
        # 李四要能改，得走主人发的码 —— 这里刻意走真实路径，而不是把测试改成
        # 「反正能推就行」，否则冲突检测测的就不是真实权限下的行为了。
        assert a["role"] == "owner"
        _, pairing = _req(base, "/team/pairing", {}, a["token"])
        code, b = _req(base, "/team/pair", {"name": "李四", "code": pairing["code"]})
        assert code == 200 and b["role"] == "editor"

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
        assert p["max_uses"] == 1 and p["remaining"] == 1 and p["alive"] is True
        assert p["address"].startswith("http://") and "/pair?code=" in p["pair_url"]
        # 2026-11-04 移除二维码：配对只留「6 位码」和「邀请链接」两条路。
        # 这里守的是**别再有人把图塞回载荷** —— 那会让面板多一个模板和一层 cv2。
        assert "qr" not in p
        assert p["expires_at"] > 0 and 0 < p["ttl"] <= 120
        assert isinstance(p["host_name"], str)

        # 手机落地页：地址 + 码 + 名额都看得见
        page = urllib.request.urlopen(base + "/pair?code=" + p["code"], timeout=10).read().decode()
        assert p["code"] in page and "还能请 1 人" in page

        # 🔴 GET 只读：面板每 2 秒轮询一次，反复查既不能换号也不能新建
        for _ in range(3):
            code, back = _req(base, "/team/pairing", token=host["token"])
            assert code == 200 and back["code"] == p["code"]

        # 无令牌兑换成功，并回报「还剩几个名额」
        code, joined = _req(base, "/team/pair", {"code": p["code"], "name": "同事B"})
        assert code == 200 and joined["paired"] is True and joined["remaining"] == 0
        assert srv.hub.auth(joined["token"])["name"] == "同事B"

        # 第二个人拿同一张码再来 ⇒ 拒（名额用完）
        code, dup = _req(base, "/team/pair", {"code": p["code"], "name": "同事C"})
        assert code >= 400 and dup["code"] == "code_used"

        # 手机落地页此时要如实说「请满了」（不是笼统一句"已失效"）
        page2 = urllib.request.urlopen(base + "/pair?code=" + p["code"], timeout=10).read().decode()
        assert "已经请满" in page2

        # 名额用完后 GET 仍能看到「刚那张已请满」（不伪造活码，也不假装从没有过）
        code, none_left = _req(base, "/team/pairing", token=host["token"])
        assert code == 200 and none_left["code"] == p["code"]
        assert none_left["alive"] is False and none_left["exhausted"] is True
        # 再要才给新号
        code, fresh = _req(base, "/team/pairing", {}, host["token"])
        assert code == 200 and fresh["code"] and fresh["code"] != p["code"]
    finally:
        srv.stop()


def test_pair_http_multi_use_selects_quota(tmp_path):
    """一次请 3 个人：面板选「3 人」→ 三张名额，第三个人进来后码自动死。"""
    srv = TeamServer(str(tmp_path / "team"), host="127.0.0.1", port=0)
    info = srv.start()
    base = "http://127.0.0.1:%d" % info["port"]
    try:
        _, host = _req(base, "/team/join", {"name": "主机"})
        code, p = _req(base, "/team/pairing", {"max_uses": 3}, host["token"])
        assert code == 200 and p["max_uses"] == 3 and p["remaining"] == 3

        remain = []
        for i in range(3):
            code, joined = _req(base, "/team/pair", {"code": p["code"], "name": "同事%d" % i})
            assert code == 200
            remain.append(joined["remaining"])
        assert remain == [2, 1, 0]

        code, dup = _req(base, "/team/pair", {"code": p["code"], "name": "第四个"})
        assert code >= 400 and dup["code"] == "code_used"

        # 面板侧的只读查询此时应该回「刚那张已请满」，而不是一张活码
        code, back = _req(base, "/team/pairing", token=host["token"])
        assert code == 200 and back["code"] == p["code"] and back["alive"] is False

        # 作废一条新码
        code, p2 = _req(base, "/team/pairing", {}, host["token"])
        code, rv = _req(base, "/team/pairing/revoke", {"code": p2["code"]}, host["token"])
        assert code == 200 and rv["revoked"] is True
        code, gone = _req(base, "/team/pair", {"code": p2["code"], "name": "迟到的人"})
        assert code >= 400 and gone["code"] == "code_revoked"
    finally:
        srv.stop()


def test_pairing_multi_use_quota(hub):
    host = hub.register_member("主机")
    p = hub.create_pairing(host["member_id"], max_uses=3)
    assert p["max_uses"] == 3 and p["remaining"] == 3 and p["uses"] == 0
    for i in range(3):
        got = hub.pairing_claim(p["code"], "m_%d" % i)
        assert got["uses"] == i + 1 and got["remaining"] == 2 - i
    assert hub.pairing_alive(p["code"]) is False
    with pytest.raises(TeamError) as ei:
        hub.pairing_claim(p["code"], "m_x")
    assert ei.value.code == "code_used"


def test_pairing_revoke_is_owner_only_and_reports_reason(hub):
    a = hub.register_member("A")
    b = hub.register_member("B")
    code = hub.create_pairing(a["member_id"])["code"]

    with pytest.raises(TeamError) as ei:
        hub.pairing_revoke(code, b["member_id"])
    assert ei.value.code == "bad_owner"

    assert hub.pairing_revoke(code, a["member_id"])["revoked"] is True
    assert hub.pairing_alive(code) is False
    # 被主人废掉 ≠ 用完了 —— 报错要说清是哪种，人才知道该找谁
    with pytest.raises(TeamError) as ei2:
        hub.pairing_claim(code)
    assert ei2.value.code == "code_revoked"
    # 幂等：再废一次不抛，只是不再声称"这次废掉了"
    again = hub.pairing_revoke(code, a["member_id"])
    assert again["revoked"] is False and again["alive"] is False


def test_pairing_widen_replaces_old_code(hub):
    """名额只能往上加：要 3 人时必须废掉 1 人的旧码，否则会出现两张并存的活码。"""
    host = hub.register_member("主机")
    one = hub.create_pairing(host["member_id"], max_uses=1)
    assert hub.create_pairing(host["member_id"], max_uses=1)["reused"] is True
    assert hub.create_pairing(host["member_id"], max_uses=1)["replaced"] is False

    wide = hub.create_pairing(host["member_id"], max_uses=3)
    assert wide["code"] != one["code"] and wide["max_uses"] == 3
    assert wide["replaced"] is True and wide["reused"] is False
    assert hub.pairing_alive(one["code"]) is False
    with pytest.raises(TeamError) as ei:
        hub.pairing_claim(one["code"])
    assert ei.value.code == "code_revoked"


def test_latest_pairing_is_readonly(hub):
    host = hub.register_member("主机")
    assert hub.latest_pairing(host["member_id"]) is None
    p = hub.create_pairing(host["member_id"])
    for _ in range(3):
        assert hub.latest_pairing(host["member_id"])["code"] == p["code"]
    hub.pairing_claim(p["code"], "m_1")
    assert hub.latest_pairing(host["member_id"]) is None
    # 「最近一张」还在，且如实标成用满 —— 面板靠它解释「刚那张怎么了」
    dead = hub.last_pairing(host["member_id"])
    assert dead["code"] == p["code"] and dead["exhausted"] is True and dead["alive"] is False
    # 别人的码不算「我手上的」
    other = hub.register_member("另一位")
    assert hub.latest_pairing(other["member_id"]) is None
    assert hub.last_pairing(other["member_id"]) is None


def test_pairing_columns_migrated_on_old_db(tmp_path):
    """老库补列：已用过的码不能显示成「还能加 1 人」（等于把废码说成活的）。"""
    import sqlite3

    db = tmp_path / "team" / "team.db"
    db.parent.mkdir(parents=True)
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE pairing (code TEXT PRIMARY KEY, created_by TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL, expires_at REAL NOT NULL,
            used_at REAL NOT NULL DEFAULT 0, used_by TEXT NOT NULL DEFAULT '');
        INSERT INTO pairing VALUES ('111111','m_a',1e9,1e9+120,1e9,'m_b');
        INSERT INTO pairing VALUES ('222222','m_a',1e9,1e9+120,0,'');
        """
    )
    conn.commit()
    conn.close()

    hub = Hub(str(tmp_path / "team"))
    used = hub.pairing_info("111111")
    assert used["uses"] == 1 and used["exhausted"] is True and used["alive"] is False
    fresh = hub.pairing_info("222222")
    assert fresh["uses"] == 0 and fresh["max_uses"] == 1 and fresh["remaining"] == 1


# ── 回滚：历史只增不删（2026-11-04 · 画布 0.3.48）──────────────────────

def test_rollback_republishes_old_content_as_new_rev(hub):
    """回滚 ＝ 又提交一版旧内容，不是把指针退回去（同事后来的工作不能被抹掉）。"""
    a = hub.register_member("张三")
    pid = hub.create_project("短剧A", a["member_id"], _bundle("v1"))["project_id"]
    hub.push(pid, a["member_id"], _bundle("v2"), base_rev=1)      # rev → 2
    res = hub.rollback(pid, a["member_id"], to_rev=1, base_rev=2)

    assert res["rev"] == 3 and res["rolled_back_to"] == 1
    got = hub.get_bundle(pid)
    assert got["rev"] == 3
    assert got["bundle"]["nodes"][0]["data"]["marker"] == "v1"     # 内容是旧的
    # 🔴 rev 2 必须仍在：回滚不是删除，事后还要能回到「回滚前」
    assert [v["rev"] for v in hub.versions(pid)] == [3, 2, 1]
    assert hub.get_bundle(pid, 2)["bundle"]["nodes"][0]["data"]["marker"] == "v2"


def test_rollback_note_says_where_it_came_from(hub):
    a = hub.register_member("张三")
    pid = hub.create_project("短剧A", a["member_id"], _bundle("v1"))["project_id"]
    hub.push(pid, a["member_id"], _bundle("v2"), base_rev=1)
    hub.rollback(pid, a["member_id"], to_rev=1, base_rev=2)
    latest = hub.versions(pid)[0]
    assert latest["rev"] == 3
    assert "回滚到 rev 1" in latest["message"]
    assert "张三" in latest["message"]        # 谁那一版，事后才查得到


def test_rollback_rejects_latest_old_and_unknown_rev(hub):
    a = hub.register_member("张三")
    pid = hub.create_project("短剧A", a["member_id"], _bundle("v1"))["project_id"]
    with pytest.raises(TeamError) as e_latest:
        hub.rollback(pid, a["member_id"], to_rev=1)          # 它已经是最新
    assert e_latest.value.code == "noop"
    with pytest.raises(TeamError) as e_future:
        hub.rollback(pid, a["member_id"], to_rev=9)
    assert e_future.value.code == "not_found"
    with pytest.raises(TeamError) as e_zero:
        hub.rollback(pid, a["member_id"], to_rev=0)
    assert e_zero.value.code == "not_found"


def test_rollback_conflicts_when_someone_pushed_meanwhile(hub):
    """看着旧界面回滚，会把同事刚提交的那一版顺手盖掉 ⇒ 必须 Conflict。"""
    a = hub.register_member("张三")
    b = hub.register_member("李四")
    pid = hub.create_project("短剧A", a["member_id"], _bundle("v1"))["project_id"]
    hub.push(pid, b["member_id"], _bundle("v2"), base_rev=1)      # rev → 2
    with pytest.raises(ConflictError) as ei:
        hub.rollback(pid, a["member_id"], to_rev=1, base_rev=1)   # 他以为还在 rev 1
    assert ei.value.current_rev == 2
    assert "李四" in ei.value.author


# ── 在线状态：last_seen（2026-11-04 · 画布 0.3.50）────────────────────

def test_new_member_is_immediately_seen(hub):
    """刚加入的人当然算「刚活跃」——否则面板会把新同事显示成「没上线过」。"""
    m = hub.register_member("张三")
    row = next(x for x in hub.members() if x["id"] == m["member_id"])
    assert row["last_seen"] > 0


def test_auth_refreshes_last_seen_but_is_throttled(hub, monkeypatch):
    """每次请求都写库没必要；但超过节流窗口必须刷新，否则「在线」永远不动。"""
    import app.core.team_hub as th

    m = hub.register_member("张三")
    base = hub.members()[0]["last_seen"]

    monkeypatch.setattr(th, "_now", lambda: base + 5)          # 窗口内
    hub.auth(m["token"])
    assert hub.members()[0]["last_seen"] == base               # 不该写

    monkeypatch.setattr(th, "_now", lambda: base + 60)         # 超窗口
    hub.auth(m["token"])
    assert hub.members()[0]["last_seen"] == base + 60


def test_auth_with_bad_token_does_not_touch_anything(hub):
    hub.register_member("张三")
    before = hub.members()[0]["last_seen"]
    assert hub.auth("not-a-token") is None
    assert hub.members()[0]["last_seen"] == before


def test_member_last_seen_column_migrated_on_old_db(tmp_path):
    """老库补列取 0 而不是「现在」：升级瞬间全员显示「在线」是编的。"""
    import sqlite3

    db = tmp_path / "team" / "team.db"
    db.parent.mkdir(parents=True)
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE member (id TEXT PRIMARY KEY, name TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'editor', token_hash TEXT NOT NULL,
            created_at REAL NOT NULL);
        INSERT INTO member VALUES ('m_1','张三','editor','x',1e9);
        """
    )
    conn.commit()
    conn.close()

    hub = Hub(str(tmp_path / "team"))
    row = hub.members()[0]
    assert row["last_seen"] == 0


# ── 角色鉴权（2026-11-04 · 画布 0.3.52）────────────────────
#
# 为什么这组必须有：以前 `role` 只是登记信息，**任何成员令牌都能做任何事**。
# 而设计评审最常见的动作是把工程发给甲方看 —— 那样等于把删除权一起给出去了。
# 这里锁四件事：
#   ① 认不出角色时按 viewer 算（少给权限，不给多）；
#   ② 无码 join 只能拿到 viewer，且请求体里自封 `role: owner` 无效；
#   ③ 主人能升任何人，但改不了自己的角色，别人也改不了他；
#   ④ 老库升级后码的角色是 editor（不能把原来能改的人降成只读）。


def test_role_rank_and_allow_are_monotonic():
    from app.core.team_hub import allow_role, role_rank

    assert role_rank("owner") > role_rank("editor") > role_rank("viewer")
    assert allow_role("owner", "owner") and allow_role("owner", "editor")
    assert allow_role("editor", "editor") and not allow_role("editor", "owner")
    assert allow_role("viewer", "viewer") and not allow_role("viewer", "editor")


def test_unknown_role_is_treated_as_viewer():
    """写错角色名 ⇒ 当 viewer。**故意的不对称**：多给权限用户永远发现不了。"""
    from app.core.team_hub import allow_role, role_rank

    for bad in ("", None, "admin", "机器人", "  "):
        assert role_rank(bad) == 1
        assert not allow_role(bad, "editor")
    # 大小写与首尾空格不算「不认识」—— 老库里可能写的是 `Editor `
    assert allow_role("Editor ", "editor")
    assert allow_role("EDITOR", "editor")


def test_join_without_code_is_viewer_and_cannot_write(tmp_path):
    srv = TeamServer(str(tmp_path / "team"), host="127.0.0.1", port=0)
    info = srv.start()
    base = "http://127.0.0.1:%d" % info["port"]
    try:
        _, owner = _req(base, "/team/join", {"name": "主人"})
        code, guest = _req(base, "/team/join", {"name": "路人"})
        assert code == 200 and guest["role"] == "viewer"

        # 能读
        assert _req(base, "/team/projects", token=guest["token"])[0] == 200
        assert _req(base, "/team/members", token=guest["token"])[0] == 200
        # 不能写：建项目 / 上传附件都挡
        code, err = _req(base, "/team/projects", {"name": "x", "bundle": _bundle()},
                         guest["token"])
        assert code == 403 and err["code"] == "forbidden"
        assert "编辑者" in err["message"] or "编辑权限" in err["message"]
    finally:
        srv.stop()


def test_join_ignores_role_in_request_body(tmp_path):
    """自封 owner 无效 —— 这是 2026-11-04 之前的真洞，不是理论风险。"""
    srv = TeamServer(str(tmp_path / "team"), host="127.0.0.1", port=0)
    info = srv.start()
    base = "http://127.0.0.1:%d" % info["port"]
    try:
        _req(base, "/team/join", {"name": "主人"})
        code, evil = _req(base, "/team/join", {"name": "攻击者", "role": "owner"})
        assert code == 200 and evil["role"] == "viewer"
        # 再试一次带 editor，也一样
        code, evil2 = _req(base, "/team/join", {"name": "攻击者2", "role": "editor"})
        assert evil2["role"] == "viewer"
    finally:
        srv.stop()


def test_pairing_can_invite_viewer(tmp_path):
    srv = TeamServer(str(tmp_path / "team"), host="127.0.0.1", port=0)
    info = srv.start()
    base = "http://127.0.0.1:%d" % info["port"]
    try:
        _, owner = _req(base, "/team/join", {"name": "主人"})
        _, p = _req(base, "/team/pairing", {"role": "viewer"}, owner["token"])
        assert p["role"] == "viewer"
        code, guest = _req(base, "/team/pair", {"name": "甲方", "code": p["code"]})
        assert code == 200 and guest["role"] == "viewer"
        # 拿到 viewer 码的人，自己加 role 也升不上去（角色只来自码）
        _, p2 = _req(base, "/team/pairing", {"role": "viewer"}, owner["token"])
        code, sneak = _req(base, "/team/pair",
                           {"name": "滑头", "code": p2["code"], "role": "editor"})
        assert code == 200 and sneak["role"] == "viewer"
    finally:
        srv.stop()


def test_pairing_reuse_requires_same_role(tmp_path):
    """同一串数字不能对甲是可改、对乙是只读 ⇒ 换角色必须换码。"""
    hub = Hub(str(tmp_path / "team"))
    m = hub.register_member("主人", "owner")
    first = hub.create_pairing(m["member_id"], max_uses=3, role="editor")
    same = hub.create_pairing(m["member_id"], max_uses=3, role="editor")
    assert same["code"] == first["code"] and same["reused"] is True

    other = hub.create_pairing(m["member_id"], max_uses=3, role="viewer")
    assert other["code"] != first["code"] and other["replaced"] is True
    # 旧码被作废，不能留两张活码
    assert hub.pairing_alive(first["code"]) is False
    assert hub.pairing_alive(other["code"]) is True


def test_owner_can_promote_member_and_then_can_write(tmp_path):
    srv = TeamServer(str(tmp_path / "team"), host="127.0.0.1", port=0)
    info = srv.start()
    base = "http://127.0.0.1:%d" % info["port"]
    try:
        _, owner = _req(base, "/team/join", {"name": "主人"})
        _, guest = _req(base, "/team/join", {"name": "同事"})
        assert _req(base, "/team/projects", {"name": "x", "bundle": _bundle()},
                    guest["token"])[0] == 403

        code, res = _req(base, "/team/members/%s/role" % guest["member_id"],
                         {"role": "editor"}, owner["token"])
        assert code == 200 and res["member"]["role"] == "editor"
        # 升完之后立刻能建项目（权限是查库的，不是缓存在令牌里）
        code, made = _req(base, "/team/projects", {"name": "x", "bundle": _bundle()},
                          guest["token"])
        assert code == 200 and made["project_id"]
    finally:
        srv.stop()


def test_non_owner_cannot_change_role_and_owner_role_is_immutable(tmp_path):
    srv = TeamServer(str(tmp_path / "team"), host="127.0.0.1", port=0)
    info = srv.start()
    base = "http://127.0.0.1:%d" % info["port"]
    try:
        _, owner = _req(base, "/team/join", {"name": "主人"})
        _, p = _req(base, "/team/pairing", {}, owner["token"])
        _, editor = _req(base, "/team/pair", {"name": "同事", "code": p["code"]})

        # 编辑者想改别人角色 ⇒ 403
        code, err = _req(base, "/team/members/%s/role" % owner["member_id"],
                         {"role": "viewer"}, editor["token"])
        assert code == 403 and err["code"] == "forbidden"

        # 主人改自己 ⇒ 403（团队始终只有一个主人）
        code, err = _req(base, "/team/members/%s/role" % owner["member_id"],
                         {"role": "editor"}, owner["token"])
        assert code == 403 and "让渡" in err["message"]
    finally:
        srv.stop()


def test_set_member_role_rejects_unknown_member(hub):
    m = hub.register_member("主人", "owner")
    with pytest.raises(TeamError) as gone:
        hub.set_member_role(m["member_id"], "m_不存在", "editor")
    assert gone.value.code == "not_found"


def test_old_db_pairing_gets_editor_role(tmp_path):
    """老库升级后码的角色必须是 editor：那些人本来是能改的，
    升级瞬间变只读会让人莫名其妙改不动东西。"""
    import sqlite3

    db = tmp_path / "team" / "team.db"
    db.parent.mkdir(parents=True)
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE member (id TEXT PRIMARY KEY, name TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'editor', token_hash TEXT NOT NULL,
            created_at REAL NOT NULL, last_seen REAL NOT NULL DEFAULT 0);
        CREATE TABLE pairing (code TEXT PRIMARY KEY, created_by TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL, expires_at REAL NOT NULL,
            used_at REAL NOT NULL DEFAULT 0, used_by TEXT NOT NULL DEFAULT '',
            max_uses INTEGER NOT NULL DEFAULT 1, uses INTEGER NOT NULL DEFAULT 0);
        INSERT INTO member VALUES ('m_1','张三','owner','x',1e9,0);
        INSERT INTO pairing VALUES ('229140','m_1',1e9,9e18,0,'',1,0);
        """
    )
    conn.commit()
    conn.close()

    hub = Hub(str(tmp_path / "team"))
    info = hub.pairing_info("229140")
    assert info is not None and info["role"] == "editor"


# ── 批注（2026-11-04 · 设计评审）────────────────────────────
#
# 这一组的重点是**角色分工**：viewer 能提意见但不能替人标「已解决」。
# 如果哪天有人把提批注也加上编辑权门槛，客户就再也说不了话了 —— 那正是
# 这条功能存在的理由（甲方只看不改，但必须能说话）。


def test_comment_lifecycle(hub):
    m = hub.register_member("张三", "owner")
    p = hub.create_project("第一集", m["member_id"], _bundle())

    c = hub.add_comment(p["project_id"], m["member_id"], "镜 03 字幕压住人脸了",
                        node_id="n1", rev=2)
    assert c["node_id"] == "n1" and c["rev"] == 2
    assert c["author"] == "张三" and c["resolved"] is False

    listed = hub.list_comments(p["project_id"])
    assert len(listed) == 1 and listed[0]["body"].startswith("镜 03")

    done = hub.set_comment_resolved(p["project_id"], c["id"], m["member_id"], True)
    assert done["resolved"] is True and done["resolver"] == "张三"

    reopened = hub.set_comment_resolved(p["project_id"], c["id"], m["member_id"], False)
    assert reopened["resolved"] is False
    # 重开必须把「谁解决的」清掉，否则记录指向一个其实没解决的人
    assert reopened["resolved_by"] == "" and reopened["resolver"] == ""


def test_comment_rejects_empty_body_and_missing_project(hub):
    m = hub.register_member("张三", "owner")
    p = hub.create_project("第一集", m["member_id"], _bundle())

    with pytest.raises(TeamError) as empty:
        hub.add_comment(p["project_id"], m["member_id"], "   ")
    assert empty.value.code == "empty_body"

    with pytest.raises(TeamError) as too_long:
        hub.add_comment(p["project_id"], m["member_id"], "字" * 2001)
    assert too_long.value.code == "too_long"

    with pytest.raises(TeamError) as gone:
        hub.add_comment("proj_不存在", m["member_id"], "随便说点什么")
    assert gone.value.code == "not_found"


def test_comment_does_not_touch_rev(hub):
    """提批注**不产生新版本** —— 否则每提一条意见都多一个 rev，
    「谁改了什么」会被意见淹掉，而且评审者并不想动别人的画布。"""
    m = hub.register_member("张三", "owner")
    p = hub.create_project("第一集", m["member_id"], _bundle())
    before = hub._project_row(p["project_id"])["rev"]
    hub.add_comment(p["project_id"], m["member_id"], "整体色调偏冷", node_id="")
    after = hub._project_row(p["project_id"])["rev"]
    assert before == after == 1


def test_viewer_can_comment_but_cannot_resolve(tmp_path):
    srv = TeamServer(str(tmp_path / "team"), host="127.0.0.1", port=0)
    info = srv.start()
    base = "http://127.0.0.1:%d" % info["port"]
    try:
        _, owner = _req(base, "/team/join", {"name": "主人"})
        # 甲方：无码 join ⇒ viewer
        _, client = _req(base, "/team/join", {"name": "甲方"})
        assert client["role"] == "viewer"

        _, made = _req(base, "/team/projects",
                       {"name": "第一集", "bundle": _bundle()}, owner["token"])
        pid = made["project_id"]

        # viewer 能提 —— 这是关键
        code, res = _req(base, "/team/projects/%s/comments" % pid,
                         {"body": "这一版封面太暗", "node_id": "n1", "rev": 1},
                         client["token"])
        assert code == 200 and res["comment"]["author"] == "甲方"
        cid = res["comment"]["id"]

        # 但解决不了（那是干活的人的流程）
        code, err = _req(base, "/team/projects/%s/comments/%s" % (pid, cid),
                         {"resolved": True}, client["token"])
        assert code == 403 and err["code"] == "forbidden"

        # 编辑者能解决；读列表两种角色都能
        code, done = _req(base, "/team/projects/%s/comments/%s" % (pid, cid),
                          {"resolved": True}, owner["token"])
        assert code == 200 and done["comment"]["resolved"] is True
        code, listed = _req(base, "/team/projects/%s/comments" % pid, token=client["token"])
        assert code == 200 and len(listed["comments"]) == 1
        assert listed["comments"][0]["resolver"] == "主人"
    finally:
        srv.stop()


def test_stats_counts_open_comments(tmp_path):
    hub = Hub(str(tmp_path / "team"))
    m = hub.register_member("张三", "owner")
    p = hub.create_project("第一集", m["member_id"], _bundle())
    c = hub.add_comment(p["project_id"], m["member_id"], "第一处")
    hub.add_comment(p["project_id"], m["member_id"], "第二处")
    assert hub.stats()["open_comments"] == 2
    hub.set_comment_resolved(p["project_id"], c["id"], m["member_id"], True)
    assert hub.stats()["open_comments"] == 1
