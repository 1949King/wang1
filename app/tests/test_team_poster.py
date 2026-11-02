# -*- coding: utf-8 -*-
"""视频封面抽帧端点（`/host/team/poster` · 2026-11-02）

为什么这个端点必须存在（而不是让前端截首帧）：画布跑在 Qt WebEngine 上，
实测 `canPlayType('video/mp4; codecs="avc1.42E01E"')` 是**空串**、`<video>` 报
`error.code=4`（webm 正常）。pip 装的 WebEngine 不带 H.264，而本产品渲染的成片
正是 h264 ⇒ 浏览器里既放不出画面，`canvas.drawImage(video)` 也拿不到像素。

这里守四件事：
① **只认 `/inbox_file/` 与 `/editor_file/`**（绝对路径一律 400）—— 否则就成了
   「让 ffmpeg 读任意本机文件再回一张图」的探测工具；
② 文件不在 ⇒ `not_found`；抽不出来 ⇒ `frame_failed`，都**如实回**不假装成功；
③ 抽帧超时压在画布桥 30 秒上限之内；
④ 成功时回 `data:image/jpeg;base64,…`，前端可直接当 `<img src>`。

不 import `canvas_server`（太重）：`_cs()` 与 `canvas_bridge` 都在测试里替换掉。
"""
from __future__ import annotations

import json
import sys
import types

import pytest

from app.core.canvas_routes_team import CanvasTeamRoutesMixin


class _Handler:
    def __init__(self) -> None:
        self.code = None
        self.payload = None

    def _json(self, code, payload) -> None:
        self.code, self.payload = code, payload


class _FakeCs:
    @staticmethod
    def _check_host_token(handler) -> bool:
        return True


def _safe_filename(name: str) -> str:
    base = str(name or "asset.bin").replace("..", "_")
    keep = "".join(c for c in base if c.isalnum() or c in "._- ()[]")
    return keep or "asset.bin"


@pytest.fixture()
def dirs(tmp_path, monkeypatch):
    """替掉 canvas_bridge：给一个凑合的 inbox / outbox 目录与 `_safe_filename`。"""
    inbox = tmp_path / "inbox"
    outbox = tmp_path / "outbox"
    inbox.mkdir()
    outbox.mkdir()
    fake = types.ModuleType("app.core.canvas_bridge")
    fake.canvas_inbox_dir = lambda: str(inbox)       # type: ignore[attr-defined]
    fake.canvas_outbox_dir = lambda: str(outbox)     # type: ignore[attr-defined]
    fake._safe_filename = _safe_filename             # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.core.canvas_bridge", fake)
    monkeypatch.setattr("app.core.canvas_routes_team._cs", lambda: _FakeCs)
    return inbox, outbox


@pytest.fixture()
def frames(monkeypatch):
    """替掉真正的 ffmpeg 抽帧，记录调用参数（测试不依赖本机装没装 ffmpeg）。"""
    calls = []

    def fake(path, t, width=256, timeout=60.0):
        calls.append({"path": path, "t": t, "width": width, "timeout": timeout})
        return b"\xff\xd8fakejpeg"

    monkeypatch.setattr("app.core.canvas_shot_vision._grab_frame", fake)
    return calls


def _poster(payload):
    h = _Handler()
    CanvasTeamRoutesMixin._p_host_team_poster(
        h, None, json.dumps(payload).encode("utf-8"), "application/json"
    )
    return h.code, h.payload


# ── 闸门 ────────────────────────────────────────────────
@pytest.mark.parametrize("bad", [
    r"C:\Windows\System32\drivers\etc\hosts",
    "/etc/passwd",
    "D:/拾光剪影/inbox/x.mp4",
    "/inbox_file/../../secret.mp4",
    "/inbox_file/..\\..\\secret.mp4",
    "http://evil.example.com/inbox_file/x.mp4",
    "/other_dir/x.mp4",
    "",
])
def test_poster_rejects_non_canvas_paths(dirs, bad):
    """绝对路径 / 目录穿透 / 外站 URL 一律 400，绝不落到 ffmpeg。"""
    code, payload = _poster({"path": bad})
    assert code == 400 and payload["ok"] is False and payload["code"] == "bad_path"


def test_poster_rejects_bad_json(dirs):
    h = _Handler()
    CanvasTeamRoutesMixin._p_host_team_poster(h, None, b"{not json", "application/json")
    assert h.code == 400 and h.payload["ok"] is False


# ── 正常 / 失败 ─────────────────────────────────────────
def test_poster_returns_data_url(dirs, frames):
    inbox, _ = dirs
    video = inbox / "成片.mp4"
    video.write_bytes(b"\x00" * 1024)

    code, payload = _poster({"path": "/inbox_file/成片.mp4"})
    assert code == 200 and payload["ok"] is True
    assert payload["data_url"].startswith("data:image/jpeg;base64,")
    assert payload["bytes"] > 0
    # 真的抽了那个文件，且超时压在 30 秒请求上限以内
    assert frames and frames[0]["path"] == str(video)
    assert frames[0]["timeout"] <= 25 and frames[0]["width"] == 320


def test_poster_accepts_editor_file_and_localhost_prefix(dirs, frames):
    _, outbox = dirs
    (outbox / "片段.mp4").write_bytes(b"\x00" * 8)
    code, payload = _poster({"path": "http://127.0.0.1:18765/editor_file/片段.mp4"})
    assert code == 200 and payload["ok"] is True


def test_poster_reports_missing_file(dirs, frames):
    code, payload = _poster({"path": "/inbox_file/没有这个.mp4"})
    assert code == 200 and payload["ok"] is False and payload["code"] == "not_found"
    assert frames == [], "文件都不在，不该去调 ffmpeg"


def test_poster_reports_frame_failure(dirs, monkeypatch):
    """抽不出来（没 ffmpeg / 编码怪）如实回 frame_failed，绝不回空白图。"""
    inbox, _ = dirs
    (inbox / "坏.mp4").write_bytes(b"\x00" * 8)
    monkeypatch.setattr("app.core.canvas_shot_vision._grab_frame",
                        lambda *a, **k: None)
    code, payload = _poster({"path": "/inbox_file/坏.mp4"})
    assert code == 200 and payload["ok"] is False and payload["code"] == "frame_failed"
    assert "没装 ffmpeg" in payload["message"]


def test_poster_clamps_at_and_width(dirs, frames):
    """越界参数夹到合理区间：at 落到 0，width 落到上限 640 —— 不让 base64 撑爆响应。"""
    inbox, _ = dirs
    (inbox / "x.mp4").write_bytes(b"\x00" * 8)
    _poster({"path": "/inbox_file/x.mp4", "at": -99, "width": 99999})
    assert frames[0]["t"] == 0.0 and frames[0]["width"] == 640
