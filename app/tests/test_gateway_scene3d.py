# -*- coding: utf-8 -*-
"""app/tests/test_gateway_scene3d.py — T5 可选网关全景生成客户端（2026-11-20）。

契约（上游 /v1/scene3d/* 字段报告未给 ⇒ 薄客户端 OpenAI 兼容 multipart，
响应 data[0].b64_json [INFERRED]，异常形状诚实失败）：
  · 渠道未启用 ⇒ ok:false + guidance（默认关，绝不静默假图）；
  · prompt / image 至少一项；image 须为有效 data URL；
  · 成功 ⇒ image_data_url + 显著署名 "MiniMax H3"（社区许可合规义务）；
  · 超时/网络异常/异常响应形状 ⇒ 诚实失败。
本测试不触网：_load_channels 与 urllib.request.urlopen 全部打桩。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from app.core.ai import gateway_scene3d as gs

_IMG = "data:image/png;base64,aGVsbG8="
_CHANNEL = {
    "id": gs.GATEWAY_CHANNEL_ID,
    "name": "拾光·无界网关",
    "baseUrl": "http://127.0.0.1:8190/v1",
    "apiKey": "test-key",
    "models": [{"name": "MiniMax-H3", "capability": "image"}],
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
    monkeypatch.setattr(gs, "_load_channels", lambda: list(channels))


def _patch_urlopen(monkeypatch, payload, capture):
    def _fake(req, timeout=None):
        capture.append(req)
        return _Resp(payload)
    monkeypatch.setattr(urllib.request, "urlopen", _fake)


# ─────────────────────── 参数校验 ───────────────────────

def test_missing_prompt_and_image_rejected():
    res = gs.generate_panorama(prompt="", image="")
    assert res["ok"] is False


def test_invalid_image_data_url_rejected(monkeypatch):
    _patch_channels(monkeypatch, [_CHANNEL])
    res = gs.generate_panorama(prompt="全景", image="not-a-data-url")
    assert res["ok"] is False


# ─────────────────────── 未启用 ⇒ 诚实 guidance ───────────────────────

def test_not_enabled_returns_guidance(monkeypatch):
    _patch_channels(monkeypatch, [])
    res = gs.generate_panorama(prompt="一间木屋的等距柱状全景")
    assert res["ok"] is False
    assert "未启用" in res["message"]
    assert res.get("guidance")
    assert "无界网关" in res["guidance"]


def test_channel_without_key_returns_guidance(monkeypatch):
    _patch_channels(monkeypatch, [dict(_CHANNEL, apiKey="")])
    res = gs.generate_panorama(prompt="全景")
    assert res["ok"] is False
    assert res.get("guidance")


# ─────────────────────── 成功路径（mock multipart）───────────────────────

def test_text_prompt_success(monkeypatch):
    _patch_channels(monkeypatch, [_CHANNEL])
    cap = []
    _patch_urlopen(monkeypatch, {"data": [{"b64_json": "aGVsbG8="}]}, cap)
    res = gs.generate_panorama(prompt="一间木屋的等距柱状全景")
    assert res["ok"] is True
    assert res["image_data_url"].startswith("data:image/png;base64,")
    assert res["attribution"] == "MiniMax H3"   # 社区许可：UI 显著署名
    assert len(cap) == 1
    req = cap[0]
    assert req.full_url.endswith("/scene3d/panorama")
    body = req.data
    assert b'name="prompt"' in body
    assert b'name="n"\r\n\r\n1\r\n' in body
    assert b'name="image"' not in body   # 纯文本生全景，无源图


def test_image_conditioned_success(monkeypatch):
    _patch_channels(monkeypatch, [_CHANNEL])
    cap = []
    _patch_urlopen(monkeypatch, {"data": [{"b64_json": "aGVsbG8="}]}, cap)
    res = gs.generate_panorama(prompt="扩展为全景", image=_IMG)
    assert res["ok"] is True
    body = cap[0].data
    assert b'name="image"' in body


# ─────────────────────── 超时/异常形状 ⇒ 诚实失败 ───────────────────────

def test_timeout_honest_failure(monkeypatch):
    _patch_channels(monkeypatch, [_CHANNEL])

    def _boom(req, timeout=None):
        raise urllib.error.URLError("timed out")
    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    res = gs.generate_panorama(prompt="全景")
    assert res["ok"] is False
    assert res.get("message")


def test_empty_data_honest_failure(monkeypatch):
    _patch_channels(monkeypatch, [_CHANNEL])
    _patch_urlopen(monkeypatch, {"data": []}, [])
    res = gs.generate_panorama(prompt="全景")
    assert res["ok"] is False
    assert res.get("message")


def test_unexpected_shape_honest_failure(monkeypatch):
    _patch_channels(monkeypatch, [_CHANNEL])
    _patch_urlopen(monkeypatch, {"foo": "bar"}, [])
    res = gs.generate_panorama(prompt="全景")
    assert res["ok"] is False
