# -*- coding: utf-8 -*-
"""团队附件落地（`/host/team/materialize` · 2026-11-02）

同事拉下来的时间线片段指向团队服务器，而剪辑器只认本地文件路径 —— 不落地就
永远只能「看」不能「接着剪」。这里守三件事：

① **SSRF 闸门**：只放行 `…/team/projects/{id}/assets/{sha}`。放开的话本机就成了
   「任意内网 URL 的下载代理」；
② 下载字节与源文件完全一致，文件名带 sha 前缀（不覆盖用户素材库里同名文件）；
③ 第二次命中本地缓存直接返回，不重复下载。

不 import `canvas_server`（太重）：`_cs()` 与 `canvas_bridge` 都在测试里替换掉。
"""
from __future__ import annotations

import json
import sys
import types
import urllib.parse

import pytest

from app.core.canvas_routes_team import CanvasTeamRoutesMixin
from app.core.team_server import TeamServer


class _Handler:
    """只实现 materialize 用到的 `_json`。"""

    def __init__(self) -> None:
        self.code = None
        self.payload = None

    def _json(self, code, payload) -> None:  # noqa: ANN001 - 与桥一致
        self.code, self.payload = code, payload


class _FakeCs:
    """替掉 `canvas_server._check_host_token`（这里要测的是业务，不是鉴权）。"""

    @staticmethod
    def _check_host_token(handler) -> bool:  # noqa: ANN001
        return True


@pytest.fixture()
def inbox(tmp_path, monkeypatch):
    d = tmp_path / "inbox"
    d.mkdir()
    fake = types.ModuleType("app.core.canvas_bridge")
    fake.canvas_inbox_dir = lambda: str(d)          # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.core.canvas_bridge", fake)
    monkeypatch.setattr("app.core.canvas_routes_team._cs", lambda: _FakeCs)
    return d


def _materialize(payload):
    h = _Handler()
    CanvasTeamRoutesMixin._p_host_team_materialize(
        h, None, json.dumps(payload).encode("utf-8"), "application/json"
    )
    return h.code, h.payload


@pytest.fixture()
def served(tmp_path):
    """起一个真团队服务并上传一份附件，返回 (base, pid, sha, 原始字节, token)。

    **token 必须一起返回**：附件字节流端点要求鉴权，而 `<video src>` / 剪辑器
    都发不出 `Authorization` 头 ⇒ 生产路径靠 URL 里的 `?token=`（`teamAssetUrl()`
    就是这么拼的）。测试不带令牌就会 401，那不是 bug。
    """
    srv = TeamServer(str(tmp_path / "team"), host="127.0.0.1", port=0)
    info = srv.start()
    base = "http://127.0.0.1:%d" % info["port"]
    try:
        import urllib.request

        req = urllib.request.Request(
            base + "/team/join", data=json.dumps({"name": "导演A"}).encode(), method="POST"
        )
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=10) as resp:
            token = json.loads(resp.read().decode())["token"]

        req = urllib.request.Request(
            base + "/team/projects",
            data=json.dumps({"name": "成片", "bundle": {"nodes": []}}).encode(),
            method="POST",
        )
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", "Bearer " + token)
        with urllib.request.urlopen(req, timeout=10) as resp:
            pid = json.loads(resp.read().decode())["project_id"]

        payload = bytes(range(256)) * 4096          # 1MB 伪成片
        req = urllib.request.Request(
            base + "/team/projects/%s/assets?name=%s&kind=video"
            % (pid, urllib.parse.quote("成片终版.mp4")),
            data=payload,
            method="POST",
        )
        req.add_header("Content-Type", "video/mp4")
        req.add_header("Authorization", "Bearer " + token)
        with urllib.request.urlopen(req, timeout=20) as resp:
            sha = json.loads(resp.read().decode())["sha256"]
        yield base, pid, sha, payload, token
    finally:
        srv.stop()


def _asset_url(base, pid, sha, token):
    """与 `teamAssetUrl()` 同形：路�� + `?token=`。"""
    return "%s/team/projects/%s/assets/%s?token=%s" % (base, pid, sha, urllib.parse.quote(token))


# ── SSRF 闸门 ────────────────────────────────────────────
@pytest.mark.parametrize("bad", [
    "http://192.168.1.4:18770/anything/else",
    "http://192.168.1.4:18770/team/projects/p_1/assets/../../etc/passwd",
    "http://192.168.1.4:18770/team/projects/p_1/assets/shortsha",
    "file:///C:/Windows/win.ini",
    "ftp://192.168.1.4/x.mp4",
    "",
    "  ",
])
def test_materialize_rejects_non_team_url(inbox, bad):
    code, payload = _materialize({"url": bad, "name": "x.mp4"})
    assert code == 400
    assert payload["code"] == "bad_url"
    # 目录里不该出现任何文件（连半截都不该有）
    assert list(inbox.iterdir()) == []


def test_materialize_rejects_bad_json(inbox):
    h = _Handler()
    CanvasTeamRoutesMixin._p_host_team_materialize(h, None, b"{oops", "application/json")
    assert h.code == 400 and h.payload["message"] == "invalid json"


# ── 正常下载 ─────────────────────────────────────────────
def test_materialize_downloads_bytes_with_sha_prefix(inbox, served):
    base, pid, sha, payload, token = served
    url = _asset_url(base, pid, sha, token)
    code, res = _materialize({"url": url, "name": "成片终版.mp4"})

    assert code == 200 and res["ok"] is True
    assert res["bytes"] == len(payload)
    assert res.get("cached") is None
    # 文件名带 sha 前缀：素材库里到处是「成片.mp4」，不能覆盖用户的同名文件
    assert res["path"].endswith("team_%s_成片终版.mp4" % sha[:8])
    with open(res["path"], "rb") as f:
        assert f.read() == payload
    # 临时文件不残留
    assert not any(p.suffix == ".part" for p in inbox.iterdir())


def test_materialize_second_call_hits_cache(inbox, served):
    base, pid, sha, payload, token = served
    url = _asset_url(base, pid, sha, token)
    _materialize({"url": url, "name": "成片终版.mp4"})
    code, again = _materialize({"url": url, "name": "成片终版.mp4"})
    assert code == 200 and again["cached"] is True and again["bytes"] == len(payload)


def test_materialize_sanitizes_filename(inbox, served):
    base, pid, sha, _, token = served
    url = _asset_url(base, pid, sha, token)
    code, res = _materialize({"url": url, "name": 'a/b\\c:d*e?.mp4'})
    assert code == 200 and res["ok"] is True
    name = res["path"].replace("\\", "/").split("/")[-1]
    # 路径分隔符与 Windows 非法字符全部被替换，不会逃出 inbox
    assert "/" not in name and "\\" not in name and ":" not in name
    assert res["path"].startswith(str(inbox))


# ── 失败如实报 ───────────────────────────────────────────
def test_materialize_missing_asset_reports_failure(inbox, served):
    base, pid, _, _, token = served
    url = _asset_url(base, pid, "f" * 64, token)
    code, res = _materialize({"url": url, "name": "不存在.mp4"})
    assert code == 200 and res["ok"] is False
    assert res["code"] == "download_failed"
    # 失败不留半截文件
    assert [p.name for p in inbox.iterdir()] == []
