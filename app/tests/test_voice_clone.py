# -*- coding: utf-8 -*-
"""app/tests/test_voice_clone.py — 多角色音色库 / 克隆 / 情感解耦 的诚实性回归（2026-10-09，刀 T2）。

本模块的红线：**克隆引擎未装时必须诚实失败，绝不返回假音频、绝不用枚举声线冒充克隆结果**。
（和 speaker_diarize 的"绝不伪造说话人"是同一类诚实纪律。）

锁四件事：
  ① VoiceAsset 序列化往返（serialization-field-symmetry）；
  ② 角色↔音色绑定是**纯函数**：不改原对象、加/删 voice_id、读回正确；
  ③ clone_voice() 在引擎未装时诚实失败（ok=False、available=False、asset=None、reason 有指引）；
  ④ 情感解耦契约：build_voice_request 把音色与情感分开，非法情感回落 neutral。
"""
import io
import os

from app.core.ai import voice_clone as vc

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                   "app", "core", "ai", "voice_clone.py")


# ─────────────────────── ① 序列化往返 ───────────────────────

def test_voice_asset_roundtrip():
    a = vc.VoiceAsset(voice_id="v1", name="女主", character_id="c1",
                      reference_audio="/tmp/ref.wav", engine="cosyvoice2",
                      created_at="2026-10-09")
    b = vc.VoiceAsset.from_dict(a.to_dict())
    assert b == a
    assert b.character_id == "c1"
    assert b.reference_audio == "/tmp/ref.wav"


def test_voice_asset_from_dict_tolerates_missing():
    b = vc.VoiceAsset.from_dict({})
    assert b.voice_id == "" and b.character_id is None and b.reference_audio is None


# ─────────────────────── ② 角色↔音色绑定（纯函数） ───────────────────────

def test_bind_adds_voice_id_without_mutating_original():
    c = {"id": "c1", "name": "林总"}
    out = vc.bind_character_voice(c, "v1")
    assert out["voice_id"] == "v1"
    assert "voice_id" not in c, "不能改原对象"


def test_bind_empty_voice_id_is_unbind():
    c = {"id": "c1", "voice_id": "v1"}
    assert vc.bind_character_voice(c, "") == {"id": "c1"}


def test_unbind_and_read():
    c = {"id": "c1", "voice_id": "v1"}
    assert vc.unbind_character_voice(c) == {"id": "c1"}
    assert vc.character_voice_id(c) == "v1"
    assert vc.character_voice_id({"id": "c2"}) is None


# ─────────────────────── ③ 克隆诚实失败 ───────────────────────

def test_clone_honest_fallback_when_engine_missing(monkeypatch):
    monkeypatch.setattr(vc, "clone_available", lambda: False)
    # 占位路径在 Windows 不存在 ⇒ 让文件校验放行（本测试焦点是引擎未装的诚实失败）
    import os
    monkeypatch.setattr(os.path, "isfile", lambda p: True)
    r = vc.clone_voice("/tmp/ref.wav", "女主", character_id="c1")
    assert r["ok"] is False
    assert r["available"] is False
    assert r["asset"] is None
    assert "CosyVoice" in r["reason"] or "IndexTTS" in r["reason"]


def test_clone_honest_when_engine_present_but_not_wired(monkeypatch):
    """引擎 import 得到、但接线未实现 ⇒ 也要诚实说「尚未接线」，不假成功。"""
    monkeypatch.setattr(vc, "clone_available", lambda: True)
    import os
    monkeypatch.setattr(os.path, "isfile", lambda p: True)
    r = vc.clone_voice("/tmp/ref.wav", "女主")
    assert r["ok"] is False
    assert r["available"] is True
    assert r["asset"] is None


# ─────────────────────── ④ 情感解耦契约 ───────────────────────

def test_build_voice_request_decouples_voice_and_emotion():
    r = vc.build_voice_request("你好", "v1", emotion="angry")
    assert r == {"text": "你好", "voice_id": "v1", "emotion": "angry"}


def test_build_voice_request_falls_back_to_neutral():
    assert vc.build_voice_request("x", "v1", emotion="不存在的情感")["emotion"] == "neutral"


def test_emotions_are_valid_labels():
    assert "neutral" in vc.EMOTIONS and "angry" in vc.EMOTIONS
    assert len(vc.EMOTIONS) >= 8
    # 无重复
    assert len(set(vc.EMOTIONS)) == len(vc.EMOTIONS)


# ─────────────────────── ⑤ 源码级锁：不许冒充克隆 ───────────────────────

def test_source_does_not_fake_clone():
    src = io.open(SRC, encoding="utf-8").read()
    # 克隆失败时必须返回 ok=False / asset=None，而非兜底成枚举声线
    assert '"ok": False, "available": False' in src
    # 必须有诚实失败指引
    assert "诚实降级" in src or "冒充" in src


# ─────────────────────── 参考音频校验（2026-10-09 优化回归）───────────────────────

def test_clone_rejects_missing_reference_audio(monkeypatch):
    """参考音频不存在 ⇒ 给出**准确的**错误（而不是误导性的「引擎未装」）。"""
    monkeypatch.setattr(vc, "clone_available", lambda: True)   # 引擎假装在位，证明错误来自文件
    r = vc.clone_voice("/不存在的路径/ref.wav", "女主")
    assert r["ok"] is False
    assert "参考音频不存在" in r["reason"]
    assert "CosyVoice" not in r["reason"], "不得误导成引擎问题"
