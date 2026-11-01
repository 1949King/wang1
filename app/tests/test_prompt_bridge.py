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


# ── 人种锚定（2026-11-01）──────────────────────────────────
def test_face_bias_default_east_asian(monkeypatch):
    """默认锚东亚：SD 底座先验偏西方，不锚就全是美式脸。"""
    monkeypatch.delenv("SHIGUANG_FACE_BIAS", raising=False)
    p, neg = PB.apply_face_bias("young woman with black hair", "一位年轻女生")
    assert p.startswith("East Asian, ")
    assert "caucasian" in neg


def test_face_bias_respects_west_request(monkeypatch):
    """用户明确要欧美 ⇒ 不锚、不加负向（尊重用户）。"""
    monkeypatch.delenv("SHIGUANG_FACE_BIAS", raising=False)
    p, neg = PB.apply_face_bias("young woman", "欧美风格的白人女生")
    assert p == "young woman" and neg == ""


def test_face_bias_no_duplicate_tokens(monkeypatch):
    """英文里已有 chinese/asian ⇒ 不叠词，但仍补负向。"""
    monkeypatch.delenv("SHIGUANG_FACE_BIAS", raising=False)
    p, neg = PB.apply_face_bias("chinese girl in hanfu", "汉服女生")
    assert p == "chinese girl in hanfu"
    assert "caucasian" in neg


def test_face_bias_can_be_disabled(monkeypatch):
    monkeypatch.setenv("SHIGUANG_FACE_BIAS", "none")
    p, neg = PB.apply_face_bias("young woman", "一位女生")
    assert (p, neg) == ("young woman", "")


def test_detect_face_bias_markers():
    assert PB.detect_face_bias("中国古风少女") == "east"
    assert PB.detect_face_bias("欧美金发女郎") == "west"
    assert PB.detect_face_bias("一位女生") == ""


def test_sanitize_drops_chinese_segments():
    """含中文片段时只剔掉那几段，保留英文 —— 旧逻辑整段丢弃导致"人物消失"。"""
    out = PB.sanitize_en("young woman, black long straight hair, 空气刘海, holding mug, cozy shop")
    assert "young woman" in out and "holding mug" in out
    assert "空气刘海" not in out
    assert out == "young woman, black long straight hair, holding mug, cozy shop"


def test_sanitize_returns_empty_when_mostly_chinese():
    assert PB.sanitize_en("一位女生, 站在店铺, ok") == ""   # 英文不足 3 词 ⇒ 宁可不翻


def test_cap_words_by_comma_boundary():
    """超长翻译按逗号边界截断（CLIP 会静默截尾，我们主动截才有确定性）。"""
    long = "young woman, black hair, mug, cream shirt, shop, warm light, cozy, photorealistic, cinematic"
    out = PB.cap_words(long, max_words=8)
    assert len(out.split()) <= 8
    assert out.startswith("young woman")   # 主体不被丢


def test_prepare_caps_translated_length(monkeypatch):
    monkeypatch.setenv("SHIGUANG_PROMPT_TRANSLATE", "1")
    PB._CACHE.clear()
    long_en = ", ".join(["word"] * 60)
    monkeypatch.setattr(PB, "translate", lambda *a, **k: long_en)
    used, info = PB.prepare_for_local("一位女生")
    assert info["translated"] is True
    assert len(used.split()) <= PB.MAX_EN_WORDS
