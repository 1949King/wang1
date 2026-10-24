# -*- coding: utf-8 -*-
"""种子贯通（抽卡闭环 P0a，2026-09-27 用户裁定「该解冻的就解冻去做」）

抽卡账本的 best_seed 字段能不能填，取决于生成链是否真的把种子发出去并回显。
本测试覆盖：

- _normalize_seed：显式合法 → 原样透传；缺省/非法 → 密码学随机自动生成
- 硅基流动渠道：恒发送 seed（含自动种子）→ 结果可复现
- 非硅基渠道：仅在显式传入时发送（自动种子不外发，防严格校验 provider 400），
  但 seed 恒回显；seed_sent=False 提示账本侧不要记 best_seed（无法复现）
- img2img 路径同样注入 seed
"""
from __future__ import annotations

import json

import app.core.canvas_bridge  # noqa: F401  # 先全量初始化桥接层（其顶部 import
# canvas_server 完整后再 re-export），避免直接 import 触发「部分初始化模块」循环导入。
import app.core.ai.draw_ledger as dl
import app.core.canvas_aigc as aigc

# V4.40.8 起 _normalize_seed/_SEED_MAX 迁到接线层 app/core/ai/draw_ledger.py
# （canvas_aigc 顶到规模守卫容差上限）；canvas_aigc 内改为函数内惰性导入。
_normalize_seed = dl.normalize_seed
_SEED_MAX = dl._SEED_MAX


# ── _normalize_seed ─────────────────────────────────────────────────────────


def test_normalize_seed_explicit_passthrough():
    assert _normalize_seed(12345) == (12345, True)
    assert _normalize_seed("678") == (678, True)
    assert _normalize_seed(_SEED_MAX) == (_SEED_MAX, True)


def test_normalize_seed_auto_random_on_missing_or_invalid():
    for bad in (None, 0, -5, "abc", "", _SEED_MAX + 1, 2**40):
        s, explicit = _normalize_seed(bad)
        assert explicit is False, f"{bad!r} 应判为自动"
        assert 0 < s <= _SEED_MAX
    # 两次自动生成几乎必然不同（密码学随机，撞车概率 ~1/2^31）
    assert _normalize_seed(None)[0] != _normalize_seed(None)[0]


# ── 请求体注入 + 回显 ───────────────────────────────────────────────────────


class _FakeResp:
    """模拟 images/generations 返回 b64_json（走最短的解析路径，不触发外链下载）。"""

    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _patch_channel(monkeypatch, base_url):
    monkeypatch.setattr(
        aigc,
        "build_host_ai_config_patch",
        lambda: {
            "channels": [
                {
                    "id": "c1",
                    "name": "测试渠道",
                    "baseUrl": base_url,
                    "apiKey": "k",
                    "models": [{"name": "m1", "capability": "image"}],
                }
            ],
            "defaults": {},
        },
    )


def _capture_request(monkeypatch, captured):
    def fake_open(req, timeout=120, **kw):
        captured.append(json.loads(req.data.decode("utf-8")))
        return _FakeResp({"data": [{"b64_json": "QUJD"}]})

    monkeypatch.setattr(aigc, "_open_url_cancellable", fake_open)


def test_siliconflow_always_sends_seed(monkeypatch):
    """硅基渠道：自动种子也发送 → 每次结果可用 seed 复现。"""
    _patch_channel(monkeypatch, "https://api.siliconflow.cn/v1")
    captured = []
    _capture_request(monkeypatch, captured)
    res = aigc.generate_image_openai_compatible(
        prompt="测试", channel_id="c1", quality="draft"
    )
    assert res["ok"] is True
    assert res["seed_sent"] is True
    assert 0 < res["seed"] <= _SEED_MAX
    assert captured[0]["seed"] == res["seed"]


def test_explicit_seed_echoed_and_sent_to_any_provider(monkeypatch):
    """显式 seed：任何渠道都发送并原值回显（抽卡复现 / best_seed 锁定）。"""
    _patch_channel(monkeypatch, "https://api.openai.com/v1")
    captured = []
    _capture_request(monkeypatch, captured)
    res = aigc.generate_image_openai_compatible(
        prompt="测试", channel_id="c1", quality="draft", seed=42
    )
    assert res["ok"] is True
    assert res["seed"] == 42
    assert res["seed_sent"] is True
    assert captured[0]["seed"] == 42


def test_auto_seed_not_sent_to_unknown_provider(monkeypatch):
    """非硅基渠道 + 自动种子：不外发（防严格校验 400），但仍回显，seed_sent=False。"""
    _patch_channel(monkeypatch, "https://api.openai.com/v1")
    captured = []
    _capture_request(monkeypatch, captured)
    res = aigc.generate_image_openai_compatible(
        prompt="测试", channel_id="c1", quality="draft"
    )
    assert res["ok"] is True
    assert res["seed_sent"] is False
    assert "seed" not in captured[0]
    assert 0 < res["seed"] <= _SEED_MAX


def test_img2img_body_also_carries_seed(monkeypatch):
    """图生图路径：seed 注入 img2img 请求体（reference_image 生效时）。"""
    _patch_channel(monkeypatch, "https://api.siliconflow.cn/v1")
    captured = []
    _capture_request(monkeypatch, captured)
    res = aigc.generate_image_openai_compatible(
        prompt="测试",
        channel_id="c1",
        quality="draft",
        seed=777,
        reference_image="data:image/png;base64,QUJD",
    )
    assert res["ok"] is True
    assert res["seed"] == 777
    assert res["mode"] == "img2img"
    assert captured[0]["seed"] == 777
    assert "image" in captured[0]
