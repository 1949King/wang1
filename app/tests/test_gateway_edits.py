# -*- coding: utf-8 -*-
"""app/tests/test_gateway_edits.py — T3 可选网关局部编辑客户端（2026-11-20）。

契约（上游无界工作台 server.js /images/edits，默认关）：
  · mode ∈ {inpaint, remove, outpaint}；
  · inpaint/remove 必须 image + mask 双文件；outpaint 单图 + megapixels；
  · singleShot 强制 n=1；响应 data[0].b64_json；
  · 渠道未启用 ⇒ ok:false + guidance（绝不静默假图）；
  · 超时/网络异常 ⇒ 诚实失败。
本测试不触网：_load_channels 与 urllib.request.urlopen 全部打桩。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from app.core.ai import gateway_edits as ge

_IMG = "data:image/png;base64,aGVsbG8="
_MASK = "data:image/png;base64,d29ybGQ="
_CHANNEL = {
    "id": ge.GATEWAY_CHANNEL_ID,
    "name": "拾光·无界网关",
    "baseUrl": "http://127.0.0.1:8190/v1",
    "apiKey": "test-key",
    "models": [{"name": "gpt-image-2", "capability": "image"}],
}


class _Resp:
    """桩 HTTP 响应（上下文管理器 + read）。"""

    def __init__(self, payload):
        self._b = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _patch_channels(monkeypatch, channels):
    monkeypatch.setattr(ge, "_load_channels", lambda: list(channels))


def _patch_urlopen(monkeypatch, payload, capture):
    def _fake(req, timeout=None):
        capture.append(req)
        return _Resp(payload)
    monkeypatch.setattr(urllib.request, "urlopen", _fake)


# ─────────────────────── 参数校验 ───────────────────────

def test_invalid_mode_rejected():
    res = ge.gateway_edit(mode="foo", image=_IMG)
    assert res["ok"] is False
    assert "mode" in res["message"]


def test_missing_image_rejected():
    res = ge.gateway_edit(mode="inpaint", image="", mask=_MASK)
    assert res["ok"] is False


def test_inpaint_requires_mask(monkeypatch):
    _patch_channels(monkeypatch, [_CHANNEL])
    res = ge.gateway_edit(mode="inpaint", image=_IMG, mask="")
    assert res["ok"] is False
    assert "蒙版" in res["message"]


def test_remove_requires_mask(monkeypatch):
    _patch_channels(monkeypatch, [_CHANNEL])
    res = ge.gateway_edit(mode="remove", image=_IMG, mask="")
    assert res["ok"] is False
    assert "蒙版" in res["message"]


# ─────────────────────── 未启用 ⇒ 诚实 guidance ───────────────────────

def test_not_enabled_returns_guidance(monkeypatch):
    _patch_channels(monkeypatch, [])
    res = ge.gateway_edit(mode="outpaint", image=_IMG)
    assert res["ok"] is False
    assert "未启用" in res["message"]
    assert res.get("guidance")
    assert "无界网关" in res["guidance"]


def test_channel_without_key_returns_guidance(monkeypatch):
    ch = dict(_CHANNEL, apiKey="")
    _patch_channels(monkeypatch, [ch])
    res = ge.gateway_edit(mode="outpaint", image=_IMG)
    assert res["ok"] is False
    assert res.get("guidance")


# ─────────────────────── 成功路径（mock multipart）───────────────────────

def test_outpaint_success_single_image_megapixels(monkeypatch):
    _patch_channels(monkeypatch, [_CHANNEL])
    cap = []
    _patch_urlopen(monkeypatch, {"data": [{"b64_json": "aGVsbG8="}]}, cap)
    res = ge.gateway_edit(mode="outpaint", image=_IMG, megapixels=2.0)
    assert res["ok"] is True
    assert res["image_data_url"].startswith("data:image/png;base64,")
    assert len(cap) == 1
    req = cap[0]
    assert req.full_url.endswith("/images/edits")
    body = req.data
    assert b"megapixels" in body
    assert b'name="mask"' not in body          # outpaint 单图，无蒙版
    assert b'name="n"\r\n\r\n1\r\n' in body    # singleShot 强制 n=1


def test_inpaint_success_double_file(monkeypatch):
    _patch_channels(monkeypatch, [_CHANNEL])
    cap = []
    _patch_urlopen(monkeypatch, {"data": [{"b64_json": "aGVsbG8="}]}, cap)
    res = ge.gateway_edit(mode="inpaint", image=_IMG, mask=_MASK, prompt="重绘")
    assert res["ok"] is True
    body = cap[0].data
    assert b'name="image"' in body
    assert b'name="mask"' in body
    assert b'name="mode"' in body
    assert b"inpaint" in body


# ─────────────────────── 超时/异常 ⇒ 诚实失败 ───────────────────────

def test_timeout_honest_failure(monkeypatch):
    _patch_channels(monkeypatch, [_CHANNEL])

    def _boom(req, timeout=None):
        raise urllib.error.URLError("timed out")
    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    res = ge.gateway_edit(mode="outpaint", image=_IMG)
    assert res["ok"] is False
    assert res.get("message")
