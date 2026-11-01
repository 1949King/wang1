# -*- coding: utf-8 -*-
"""B/C 项单测（2026-11-01）：分档负向词库 + 人物卡提示词模板。"""
from __future__ import annotations

from app.core.ai import negative_presets as N
from app.core.ai import prompt_template as T


# ── B：分档负向词库 ──────────────────────────────────
def test_guess_genre_by_keywords():
    assert N.guess_genre("古装少女站在宫殿前") == "ancient"
    assert N.guess_genre("二次元Q版角色") == "anime"
    assert N.guess_genre("产品静物拍摄") == "product"
    assert N.guess_genre("职场白领通勤") == "office"
    assert N.guess_genre("一位女生在街边") == "short_drama"   # 默认


def test_negative_contains_base_and_genre_words():
    neg = N.build_negatives(prompt="古装少女")
    assert "bad hands" in neg
    assert "modern clothing" in neg          # ancient 专属
    assert "lowres" in neg


def test_negative_keeps_user_words_first_and_dedups():
    neg = N.build_negatives(prompt="一位女生", user_negative="my own word, lowres")
    assert neg.startswith("my own word")
    # lowres 只出现一次（用户词与 base 去重）
    assert [w.strip() for w in neg.split(",")].count("lowres") == 1


def test_negative_genre_override_by_env(monkeypatch):
    monkeypatch.setenv("SHIGUANG_NEGATIVE_GENRE", "anime")
    neg = N.build_negatives(prompt="一位女生")      # 关键词没有题材
    assert "photorealistic" in neg                  # anime 档专属压制


def test_describe_shape():
    d = N.describe("office")
    assert d["genre"] == "office" and d["label"] and d["words"]


# ── C：人物卡提示词模板 ──────────────────────────────
def test_render_prompt_fixed_order():
    out = T.render_prompt({
        "style": "写实", "lighting": "暖光", "setting": "咖啡馆",
        "outfit": "白衬衫", "hair": "黑长直", "gender": "女生",
    })
    # 顺序：主体 → 发型 → 服装 → 场景 → 光照 → 风格
    assert out == "young woman, long straight black hair, white shirt, cafe, warm lighting, photorealistic"


def test_render_prompt_drops_unknown_fields_and_keeps_english():
    out = T.render_prompt({"gender": "女生", "garbage_field": "xxx", "hair": "long black hair"})
    assert "xxx" not in out
    assert "long black hair" in out          # 英文原样透传


def test_render_prompt_trims_tail_over_limit():
    card = {
        "gender": "女生", "hair": "黑长直", "outfit": "白衬衫",
        "setting": "咖啡馆", "lighting": "暖光", "mood": "温馨", "style": "写实",
    }
    out = T.render_prompt(card, max_words=6)
    words = [w for w in out.replace(",", " ").split() if w]
    assert len(words) <= 6
    assert "young woman" in out              # 主体不能被裁掉


def test_has_card_and_empty_card():
    assert T.has_card({"gender": "女生"})
    assert not T.has_card({})
    assert not T.has_card(None)
    assert T.render_prompt(None) == ""


def test_render_prompt_translates_unknown_chinese(monkeypatch):
    """字典没收录的中文姿态也必须翻掉（否则中文漏进英文提示词 = 噪音）。"""
    from app.core.ai import prompt_bridge as PB

    monkeypatch.setattr(PB, "has_cjk", lambda s: any("\u4e00" <= c <= "\u9fff" for c in s))
    monkeypatch.setattr(PB, "translate", lambda s, **k: "young woman, looking back over shoulder")
    out = T.render_prompt({"gender": "女生", "pose": "侧身回眸"})
    assert "侧身回眸" not in out
    assert "young woman" in out


def test_card_chinese_decides_genre():
    """人物卡里写「汉服」但没自由文本 ⇒ 仍应判为古装档（不能拿渲染后的英文去猜）。"""
    from app.core.ai import local_image_plan as LP

    class _Eng:
        def __init__(self):
            self.calls = []

        def generate(self, model_id, **kw):
            self.calls.append(kw)
            return {"ok": True}

        def request_precision(self, *a, **k):
            return None

    eng = _Eng()
    kw = LP.generate_kwargs(backend=eng, model_id="sd15-t2i", quality="standard",
                            prompt="", person_card={"outfit": "汉服", "setting": "古建筑"},
                            genre="")
    assert "modern clothing" in kw["negative_prompt"]     # ancient 档专属词
