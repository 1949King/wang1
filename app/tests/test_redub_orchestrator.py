# -*- coding: utf-8 -*-
"""app/tests/test_redub_orchestrator.py — 一键换词重配编排器的诚实性回归（2026-10-09，刀 T4）。

本模块的红线只有一条：**编排器必须逐级诚实降级，绝不在"不知道给谁配 / 引擎未装"时假装成功**。

锁四件事：
  ① plan_redub() 是纯函数：目标角色未知 ⇒ ok=False（不瞎猜）；各环节可用性 → 正确降级矩阵；
  ② 最终产物必须携带诚实标记（is_ai_redub / voice=fallback / lipsync=fallback）；
  ③ execute_redub() 真正调用 T1/T2/T3 骨架（不是平行重造），引擎未装时产物为空是**预期**；
  ④ 序列化往返 + 源码级锁（不许出现"不知道给谁配却返回 ok=True"）。
"""
import io
import os

from app.core.ai import redub_orchestrator as ro

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                   "app", "core", "ai", "redub_orchestrator.py")


def _req(character=None):
    return ro.RedubRequest(video_path="v.mp4", new_line="新台词", target_character=character)


# ─────────────────────── ① 编排纯函数 ───────────────────────

def test_plan_fails_when_character_unknown():
    """红线：不知道给谁配 ⇒ ok=False，不瞎猜角色。"""
    p = ro.plan_redub(_req(character=None), diarize_available=True,
                      voice_available=True, lipsync_available=True,
                      character_voice_known=False)
    assert p.ok is False
    assert "不知道给谁配" in p.reason


def test_plan_ok_when_character_given():
    p = ro.plan_redub(_req(character="女主"), diarize_available=True,
                      voice_available=True, lipsync_available=True,
                      character_voice_known=False)
    assert p.ok is True
    names = [s.name for s in p.steps]
    assert names == ["识别角色", "匹配音色", "克隆重配", "对口型", "出片"]


def test_plan_fallback_marks_when_engines_missing():
    """引擎全缺 ⇒ 各步降级，且最终标记 voice=fallback + lipsync=fallback + is_ai_redub。"""
    p = ro.plan_redub(_req(character="女主"), diarize_available=False,
                      voice_available=False, lipsync_available=False,
                      character_voice_known=False)
    assert p.ok is True
    assert "voice=fallback" in p.final_marks
    assert "lipsync=fallback" in p.final_marks
    assert "is_ai_redub=True" in p.final_marks
    # 对口型那一步是 fallback（不是 real）
    lip_step = next(s for s in p.steps if s.capability == "lipsync")
    assert lip_step.path == "fallback"


def test_plan_real_paths_when_engines_available():
    p = ro.plan_redub(_req(character="女主"), diarize_available=True,
                      voice_available=True, lipsync_available=True,
                      character_voice_known=False)
    assert all(s.path == "real" for s in p.steps if s.capability != "diarize")
    assert "voice=fallback" not in p.final_marks


def test_plan_character_from_binding_inference():
    """目标角色可由角色↔音色绑定推断时，即使没显式给角色也能成功。"""
    p = ro.plan_redub(_req(character=None), diarize_available=False,
                      voice_available=True, lipsync_available=True,
                      character_voice_known=True)
    assert p.ok is True
    assert "推断" in p.steps[0].note


# ─────────────────────── ② 执行入口（真调用骨架）──────────────────────

def test_execute_returns_plan_and_honest_empty_artifacts():
    """引擎未装时，execute 仍返回完整 plan，且产物为空是**预期**（不假成功）。"""
    r = ro.execute_redub(_req(character="女主"))
    assert r["ok"] is True
    assert r["plan"]["ok"] is True
    assert "is_ai_redub=True" in r["marks"]
    # voice_id 为 None（引擎未接），lipsync 结果诚实
    assert r["artifacts"]["voice_id"] is None


def test_execute_fails_when_character_unknown():
    r = ro.execute_redub(_req(character=None), character_voice=None)
    assert r["ok"] is False
    assert "不知道给谁配" in r["reason"]


# ─────────────────────── ③ 序列化往返 ───────────────────────

def test_plan_roundtrip():
    p = ro.plan_redub(_req(character="女主"), diarize_available=False,
                      voice_available=False, lipsync_available=False,
                      character_voice_known=False)
    d = p.to_dict()
    assert d["ok"] is True
    assert len(d["steps"]) == 5
    assert "is_ai_redub=True" in d["final_marks"]


# ─────────────────────── ④ 源码级锁：不假成功 ───────────────────────

def test_source_never_succeeds_without_character():
    src = io.open(SRC, encoding="utf-8").read()
    # 目标角色未知时返回的 RedubPlan 必须 ok=False
    assert 'RedubPlan(ok=False' in src
    assert "不知道给谁配" in src


# ─────────────────────── 预检（V4.41.7 升级回归）───────────────────────

def test_preflight_reports_missing_pieces():
    """引擎全缺 ⇒ 预检如实列出缺什么、预期质量是降级版。"""
    r = ro.preflight_check(_req(character="女主"))
    assert r["character_resolved"] is True
    assert isinstance(r["missing"], list)
    assert "降级版" in r["expected_quality"] or "完整效果" in r["expected_quality"]
    # 预检不抛异常（即使无 CUDA）
    assert "vram" in r


def test_preflight_flags_missing_character():
    r = ro.preflight_check(_req(character=None), character_voice=None)
    assert r["character_resolved"] is False
    assert any("角色" in m for m in r["missing"])
    assert r["ready"] is False
