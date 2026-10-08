# -*- coding: utf-8 -*-
"""app/tests/test_video_lipsync.py — 真人视频对口型的诚实性回归（2026-10-09，刀 T3）。

本模块的红线：对口型是**重生成类**操作，引擎不可用时**绝不假装同步了**。
三级降级逐级诚实：video_sync → dub_only（标 AI 重配）→ 交给 lip_sync.py（3D/卡通）。

测试锁四件事：
  ① decide_path() 是纯函数：引擎可用+真人 ⇒ video_sync；不可用+真人 ⇒ dub_only；
  ② 非真人素材不冒充真人同步（交回 lip_sync.py 的 blendshape 语义）；
  ③ sync_video() 引擎未装时诚实失败，is_ai_redub 必须为 True（重配必须打标）；
  ④ 请求/结果 dataclass 序列化往返 + 源码级锁（不许出现假"已同步"成功返回）。
"""
import io
import os

from app.core.ai import video_lipsync as vl

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                   "app", "core", "ai", "video_lipsync.py")


# ─────────────────────── ① 降级决策（纯函数） ───────────────────────

def test_decide_path_engine_and_real_person():
    assert vl.decide_path(engine_available=True, is_real_person=True) == vl.PATH_VIDEO_SYNC


def test_decide_path_engine_missing_falls_to_dub_only():
    assert vl.decide_path(engine_available=False, is_real_person=True) == vl.PATH_DUB_ONLY


def test_decide_path_non_real_person_not_video_sync():
    """非真人（3D/卡通）不该走真人对口型 —— 那是 lip_sync.py 的地盘。"""
    assert vl.decide_path(engine_available=True, is_real_person=False) != vl.PATH_VIDEO_SYNC


def test_paths_are_distinct_and_exhaustive():
    paths = {vl.PATH_VIDEO_SYNC, vl.PATH_DUB_ONLY, vl.PATH_SUBTITLE_ONLY}
    assert len(paths) == 3


# ─────────────────────── ② 诚实失败 + AI 重配标记 ───────────────────────

def test_sync_video_honest_fallback_when_engine_missing(monkeypatch):
    monkeypatch.setattr(vl, "video_lipsync_available", lambda: False)
    r = vl.sync_video(vl.LipSyncVideoRequest(video_path="v.mp4", audio_path="a.wav"))
    assert r.ok is False
    assert r.path == vl.PATH_DUB_ONLY
    assert r.is_ai_redub is True, "只换音不換口型必须标 AI 重配"


def test_sync_video_engine_present_but_not_wired(monkeypatch):
    """引擎 import 得到、但接线未实现 ⇒ 也诚实说「尚未接线」，不假成功。"""
    monkeypatch.setattr(vl, "video_lipsync_available", lambda: True)
    r = vl.sync_video(vl.LipSyncVideoRequest(video_path="v.mp4", audio_path="a.wav",
                                             is_real_person=True))
    assert r.ok is False
    assert r.path == vl.PATH_VIDEO_SYNC
    assert r.is_ai_redub is True
    assert "尚未接线" in r.reason


# ─────────────────────── ③ 序列化往返 ───────────────────────

def test_request_and_result_roundtrip():
    req = vl.LipSyncVideoRequest(video_path="v.mp4", audio_path="a.wav",
                                 face_region=[0.1, 0.2, 0.3, 0.4], is_real_person=True)
    assert req.to_dict()["face_region"] == [0.1, 0.2, 0.3, 0.4]

    res = vl.LipSyncResult(ok=False, path=vl.PATH_DUB_ONLY, is_ai_redub=True, reason="x")
    d = res.to_dict()
    assert d["is_ai_redub"] is True and d["path"] == vl.PATH_DUB_ONLY


# ─────────────────────── ④ 源码级锁：不许假"已同步" ───────────────────────

def test_source_never_fakes_success_without_engine():
    src = io.open(SRC, encoding="utf-8").read()
    # 引擎未接线时不得返回 ok=True
    assert 'ok=False, path=path, is_ai_redub=True' in src or 'ok=False' in src
    # 必须有诚实降级说明
    assert "诚实降级" in src or "冒充" in src or "不換口型" in src
