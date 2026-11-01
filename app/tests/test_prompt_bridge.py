# -*- coding: utf-8 -*-
"""提示词桥（2026-11-01）：中文→英文，失败不阻塞生成。

这几条用例守的是"**宁可不翻也不搞砸**"：翻译是增强，绝不能成为新的失败点。
"""
from __future__ import annotations

import app.core.ai.prompt_bridge as PB


def test_has_cjk():
    assert PB.has_cjk("一位女生站在店里")
    assert not PB.has_cjk("a young woman in a shop")
    assert not PB.has_cjk("")


def test_disabled_by_env(monkeypatch):
    monkeypatch.setenv("SHIGUANG_PROMPT_TRANSLATE", "0")
    used, info = PB.prepare_for_local("一位女生")
    assert used == "一位女生"          # 原文透传
    assert info["translated"] is False
    assert "已关闭" in info["reason"]


def test_passthrough_when_no_cjk(monkeypatch):
    monkeypatch.setenv("SHIGUANG_PROMPT_TRANSLATE", "1")
    used, info = PB.prepare_for_local("a young woman, mug, shop")
    assert used == "a young woman, mug, shop"
    assert info["translated"] is False
    assert "无中文" in info["reason"]


def test_translate_failure_keeps_original(monkeypatch):
    """Ollama 挂了 ⇒ 原文 + 明确原因（绝不抛异常、绝不返回空提示词）。"""
    monkeypatch.setenv("SHIGUANG_PROMPT_TRANSLATE", "1")
    PB._CACHE.clear()
    monkeypatch.setattr(PB, "translate", lambda *a, **k: "")
    used, info = PB.prepare_for_local("一位女生站在店里")
    assert used == "一位女生站在店里"
    assert info["translated"] is False
    assert "翻译失败" in info["reason"]


def test_translate_success_and_cache(monkeypatch):
    monkeypatch.setenv("SHIGUANG_PROMPT_TRANSLATE", "1")
    PB._CACHE.clear()
    calls = {"n": 0}

    def fake(text, **kw):
        calls["n"] += 1
        return "young woman in a shop, warm light"

    monkeypatch.setattr(PB, "translate", fake)
    src = "一位女生站在店里，暖光"
    used, info = PB.prepare_for_local(src)
    assert used == "young woman in a shop, warm light"
    assert info["translated"] is True
    # 第二次：命中缓存，不再调用 translate（用户反复点生成不重复烧 LLM）
    used2, info2 = PB.prepare_for_local(src)
    assert used2 == used and info2.get("cached") is True
    assert calls["n"] == 1
    assert PB.cached_out(src) == used


def test_translate_rejects_cjk_output(monkeypatch):
    """模型返回仍含中文 ⇒ 视为失败（不能把中文塞进 CLIP）。"""
    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            import json

            return json.dumps({"response": "一位女生"}).encode("utf-8")

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _Resp())
    monkeypatch.setattr(PB, "_pick_model", lambda: "fake:model")
    assert PB.translate("一位女生") == ""
