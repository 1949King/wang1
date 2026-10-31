# -*- coding: utf-8 -*-
"""Breeze TTS 2 客户端回归（2026-10-31 接入）。

锁四件事：
1. 未配置服务 ⇒ 完全跳过，绝不发请求（默认行为零变化）。
2. 声线枚举拼成的自然语言指令可预期（Breeze 靠 instruction 造音色）。
3. PCM 解码边界：空/奇数长度/满幅值都不得抛异常。
4. 服务返回非 200 或空音频 ⇒ None（诚实失败），由上层回退本地链，绝不造假音频。
"""

import pytest

from app.core.ai import breeze_tts_client as breeze


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """每条用例都在干净的环境变量下跑（避免开发机的 URL 泄漏进断言）。"""
    for key in (
        breeze.ENV_URL,
        breeze.ENV_CFG,
        breeze.ENV_TIMEOUT,
        "SHIGUANG_BREEZE_TTS_REF_AUDIO",
        "SHIGUANG_BREEZE_TTS_REF_TEXT",
    ):
        monkeypatch.delenv(key, raising=False)
    yield


# ── 1. 默认关闭 ───────────────────────────────────────────────

def test_disabled_by_default():
    assert breeze.breeze_tts_url() == ""
    assert breeze.breeze_tts_enabled() is False


def test_synthesize_returns_none_when_not_configured(monkeypatch):
    """未配置时连 requests 都不该 import 到发请求这一步。"""
    called = []
    import requests

    monkeypatch.setattr(requests, "post", lambda *a, **k: called.append(1))
    assert breeze.synthesize("你好") is None
    assert called == [], "未配置服务时不得发任何请求"


def test_url_is_normalized(monkeypatch):
    monkeypatch.setenv(breeze.ENV_URL, "http://127.0.0.1:7860///")
    assert breeze.breeze_tts_url() == "http://127.0.0.1:7860"
    assert breeze.breeze_tts_enabled() is True


# ── 2. 指令拼接 ───────────────────────────────────────────────

def test_instruction_video_design_full():
    got = breeze.build_instruction(
        gender="female", age="young", style="calm",
        description="温柔自信，声音清晰", emotion="neutral",
    )
    assert got == "一位年轻女声，语调平稳克制，情绪中性。温柔自信，声音清晰"


def test_instruction_ignores_unknown_enum():
    """枚举拼错不该让整条配音失败 —— 未知值直接忽略。"""
    got = breeze.build_instruction(gender="robot", age="adult", style="nope")
    assert got == "一位成年"


def test_instruction_empty_returns_empty_string():
    assert breeze.build_instruction() == ""


def test_instruction_description_only():
    assert breeze.build_instruction(description="沙哑的老者") == "沙哑的老者"


# ── 3. PCM 解码 ───────────────────────────────────────────────

def test_decode_empty():
    assert breeze.decode_pcm_s16le(b"") == []


def test_decode_odd_length_drops_tail():
    """流被截断时丢掉半个样本，不抛 struct 错误。"""
    assert len(breeze.decode_pcm_s16le(b"\x00\x01\x02")) == 1


def test_decode_full_scale():
    import struct

    pcm = struct.pack("<hh", 32767, -32768)
    got = breeze.decode_pcm_s16le(pcm)
    assert len(got) == 2
    assert got[0] == pytest.approx(0.99997, abs=1e-4)
    assert got[1] == pytest.approx(-1.0, abs=1e-6)


def test_pcm_to_float32_shape():
    import struct

    arr = breeze.pcm_to_float32(struct.pack("<hhh", 0, 1000, -1000))
    assert arr is not None
    assert arr.dtype.name == "float32"
    assert arr.shape == (3,)


# ── 4. HTTP 行为 ──────────────────────────────────────────────

class _FakeResp:
    def __init__(self, status=200, content=b"", text=""):
        self.status_code = status
        self._content = content
        self.text = text

    def iter_content(self, chunk_size=16384):
        yield self._content


def test_synthesize_ok(monkeypatch):
    monkeypatch.setenv(breeze.ENV_URL, "http://127.0.0.1:7860")
    import requests

    captured = {}

    def fake_post(url, **kw):
        captured["url"] = url
        captured["data"] = kw.get("data")
        return _FakeResp(content=b"\x00\x00" * 2000)  # 2000 样本 > 480 字节门槛

    monkeypatch.setattr(requests, "post", fake_post)
    got = breeze.synthesize("你好", instruction="一位成年男声")
    assert got is not None
    pcm, sr = got
    assert sr == breeze.OUTPUT_SAMPLE_RATE == 24000
    assert len(pcm) == 4000
    assert captured["url"].endswith("/v1/audio/speech")
    assert captured["data"]["text"] == "你好"
    assert captured["data"]["instruction"] == "一位成年男声"
    assert captured["data"]["cfg_scale"] == str(breeze.DEFAULT_CFG_SCALE)


def test_synthesize_http_error_returns_none(monkeypatch):
    monkeypatch.setenv(breeze.ENV_URL, "http://127.0.0.1:7860")
    import requests

    monkeypatch.setattr(
        requests, "post",
        lambda *a, **k: _FakeResp(status=409, text="busy"),
    )
    assert breeze.synthesize("你好") is None


def test_synthesize_empty_audio_returns_none(monkeypatch):
    """服务回 200 但音频为空（模型崩了）⇒ 必须 None，不能当成功。"""
    monkeypatch.setenv(breeze.ENV_URL, "http://127.0.0.1:7860")
    import requests

    monkeypatch.setattr(requests, "post", lambda *a, **k: _FakeResp(content=b"\x00" * 20))
    assert breeze.synthesize("你好") is None


def test_synthesize_network_error_returns_none(monkeypatch):
    monkeypatch.setenv(breeze.ENV_URL, "http://127.0.0.1:7860")
    import requests

    def boom(*a, **k):
        raise ConnectionError("refused")

    monkeypatch.setattr(requests, "post", boom)
    assert breeze.synthesize("你好") is None


def test_cfg_scale_falls_back_on_garbage(monkeypatch):
    monkeypatch.setenv(breeze.ENV_CFG, "not-a-number")
    assert breeze.breeze_cfg_scale() == breeze.DEFAULT_CFG_SCALE


def test_probe_returns_false_when_unreachable(monkeypatch):
    monkeypatch.setenv(breeze.ENV_URL, "http://127.0.0.1:7860")
    import requests

    def boom(*a, **k):
        raise ConnectionError("refused")

    monkeypatch.setattr(requests, "get", boom)
    assert breeze.probe_service() is False
