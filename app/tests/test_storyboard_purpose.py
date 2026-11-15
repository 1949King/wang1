# -*- coding: utf-8 -*-
"""拆镜时自动标作用（叙事层 · 2026-11-15 加）

为什么值得测：这是「拆分镜 → 得到 N 张已经标好作用的镜头卡」的**唯一**实现。
它坏了不会报错，只会让用户拿到 10 张「推进」——看起来正常，但没省掉任何点击，
也就是说这个功能的全部价值（少点 10 次）静默消失。

锁四件事：
1. 位置规则：首镜铺垫、末镜收尾、中间推进；
2. **转折词优先于位置** —— 「她推开门，突然发现屋里没人」这种才是真转折，
   哪怕它在第一镜；
3. 中文别名归一（LLM 很可能输出「转折」而不是 turn）；
4. 无法识别时返回空串（让调用方回落），**不要瞎猜成 advance**。
"""
from app.core.aigc_shot_purpose import infer_shot_purpose, normalize_shot_purpose
from app.core.canvas_aigc import _heuristic_storyboard


def test_position_rules():
    """首镜铺垫 / 中间推进 / 末镜收尾。"""
    assert infer_shot_purpose(0, 3, "雨夜街景") == "setup"
    assert infer_shot_purpose(1, 3, "她走向货架") == "advance"
    assert infer_shot_purpose(2, 3, "黑场") == "close"


def test_turn_word_beats_position():
    """转折词命中时，即使在首镜/末镜也判转折。"""
    assert infer_shot_purpose(0, 3, "她推开门，突然发现屋里没人") == "turn"
    assert infer_shot_purpose(2, 3, "原来那张脸一直是他") == "turn"
    assert infer_shot_purpose(1, 3, "没想到她笑了") == "turn"


def test_single_shot_is_setup():
    """只有一镜时不该判成 close（否则整条片子连铺垫都没有）。"""
    assert infer_shot_purpose(0, 1, "唯一一镜") == "setup"


def test_normalize_chinese_alias():
    assert normalize_shot_purpose("转折") == "turn"
    assert normalize_shot_purpose("收尾") == "close"
    assert normalize_shot_purpose("铺垫") == "setup"
    assert normalize_shot_purpose("推动") == ""  # 不认识的别瞎猜


def test_normalize_english_key_passthrough():
    for key in ("setup", "advance", "turn", "close"):
        assert normalize_shot_purpose(key) == key
    assert normalize_shot_purpose("TURN") == "turn"  # 大小写不敏感


def test_heuristic_storyboard_emits_purpose():
    """启发式拆镜必须每镜都带 purpose，且首尾符合叙事弧。"""
    script = "雨夜街景。她推门进店。夹起关东煮。突然发现没有影子。黑场。"
    shots = _heuristic_storyboard(script)
    assert len(shots) >= 3
    assert all(s.get("purpose") for s in shots), "有镜头缺 purpose"
    assert shots[0]["purpose"] == "setup"
    assert shots[-1]["purpose"] == "close"
    # 「突然」那一段应被判为转折
    assert any(s["purpose"] == "turn" for s in shots)
