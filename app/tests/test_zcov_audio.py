# -*- coding: utf-8 -*-
"""app/tests/test_zcov_audio.py — 四个零覆盖音频模块的补测（2026-10-09）。

对象模块（此前 0% 覆盖）：
  · app/core/audio_processor.py        （节拍/去口水音/变声/闪避/降噪编排）
  · app/core/music_recommendation.py   （配乐筛选/情绪/节奏/打分/排序/自动同步）
  · app/core/voice_generator.py        （多 TTS 引擎编排 + 特效推荐）
  · app/core/lip_sync.py               （音频特征/Viseme/能量→嘴型/ASR 对齐/导出）

测试纪律：
  · 绝不触发真实 TTS / 云端 API / 真实音频解码 —— 一律 monkeypatch 掉
    （gTTS 已安装，若不隔离会真的联网！）。只测**我们的编排逻辑**。
  · 每个用例都断言**可观察行为**，无 `assert True` 之类空断言。
  · 只用 offscreen 解释器运行，不跑全量套件。
"""

import sys
import json
import types
import wave

import numpy as np
import pytest


# ═══════════════════════════════════════════════════════════════════════════
#  通用工具
# ═══════════════════════════════════════════════════════════════════════════

def _disable_import(monkeypatch, *names):
    """把顶层模块塞进 sys.modules 为 None，令后续 `import X` 抛 ImportError。

    这是隔离第三方依赖（gTTS / TTS / soundfile / faster_whisper…）的关键手段：
    既不改源码，也不引入网络/IO。
    """
    for n in names:
        monkeypatch.setitem(sys.modules, n, None)


def _make_sine(seconds=1.0, sr=22050, freq=220.0, amp=0.3, dtype=np.float32):
    t = np.linspace(0, seconds, int(seconds * sr), endpoint=False)
    return (np.sin(2 * np.pi * freq * t) * amp).astype(dtype)


# ═══════════════════════════════════════════════════════════════════════════
#  § 1  audio_processor
# ═══════════════════════════════════════════════════════════════════════════

from app.core.audio_processor import (  # noqa: E402
    AudioProcessor, AudioSegment, BeatPoint, BGMBeatDetector,
    VoiceChanger, VoiceCleanup, VoiceDucking, VoiceProfile,
)


def test_audio_segment_duration_and_samples():
    seg = AudioSegment(id="a", start_time=1.0, end_time=3.5,
                       audio_data=np.zeros(10, dtype=np.float32), sample_rate=100)
    assert seg.duration == pytest.approx(2.5)
    assert seg.samples == 250                       # 2.5s * 100Hz


def test_beatpoint_and_voiceprofile_to_dict_roundtrip():
    bp = BeatPoint(time=1.25, intensity=0.8, type="downbeat")
    assert bp.to_dict() == {"time": 1.25, "intensity": 0.8, "type": "downbeat"}

    vp = VoiceProfile(name="x", pitch_shift=-2.0, speed_factor=0.9,
                      volume_adjust=0.1, eq_bands={"low": 1.2})
    d = vp.to_dict()
    assert d["name"] == "x" and d["pitch_shift"] == -2.0
    assert d["eq_bands"] == {"low": 1.2}


def test_detect_beats_on_click_track_is_monotonic_and_bounded():
    sr = 22050
    sig = np.zeros(sr * 3, dtype=np.float32)
    for t in (0.5, 1.0, 1.5, 2.0):                 # 4 次点击（间隔 0.5s > 0.3s 最小间隔）
        i = int(t * sr)
        sig[i:i + 200] = 0.9

    progress = []
    beats = BGMBeatDetector().detect_beats(
        sig, sr, progress_callback=lambda p, m: progress.append(p))

    assert len(beats) >= 1
    times = [b.time for b in beats]
    assert times == sorted(times), "节拍时间必须单调不减"
    assert all(0.0 <= b.intensity <= 1.0 for b in beats), "强度须归一化到 [0,1]"
    assert all(b.type == "beat" for b in beats)
    assert progress[0] == 0 and progress[-1] == 100, "进度回调须从 0 到 100"


def test_detect_beats_too_short_returns_empty_not_crash():
    # 音频短于一个帧（1024）：能量序列为空 → 不得抛异常，返回 []
    bd = BGMBeatDetector()
    assert bd.detect_beats(np.zeros(10, dtype=np.float32), 22050) == []


def test_get_beats_returns_copy_and_clear_works():
    bd = BGMBeatDetector()
    sig = np.zeros(22050 * 2, dtype=np.float32)
    for t in (0.4, 0.9, 1.4):
        i = int(t * 22050)
        sig[i:i + 200] = 0.8
    bd.detect_beats(sig, 22050)
    snapshot = bd.get_beats()
    assert len(snapshot) == len(bd.get_beat_times()) > 0
    snapshot.clear()                                # 改返回值不得影响内部状态
    assert len(bd.get_beats()) > 0
    bd.clear_beats()
    assert bd.get_beats() == [] and bd.get_beat_times() == []


def test_voice_cleanup_returns_equal_copy_without_mutating_input():
    audio = _make_sine(0.2, amp=0.5)
    original = audio.copy()
    out = VoiceCleanup().remove_mouth_sounds(audio, 22050)
    assert out is not audio                          # 返回副本
    assert np.array_equal(audio, original), "不得原地修改入参"
    assert out.shape == original.shape


def test_voice_changer_unknown_profile_is_identity_no_copy():
    vc = VoiceChanger()
    audio = _make_sine(0.1)
    out = vc.apply_voice_change(audio, 22050, "no_such_profile")
    assert out is audio, "未知声线须原样返回（不伪造变声结果）"


def test_voice_changer_flat_profile_preserves_signal():
    vc = VoiceChanger()
    vc.add_profile(VoiceProfile(name="flat"))       # pitch=0 speed=1 vol=0 eq={}
    audio = np.linspace(-0.5, 0.5, 2000).astype(np.float32)
    out = vc.apply_voice_change(audio, 22050, "flat")
    assert out is not audio and out.dtype == np.float32
    assert len(out) == len(audio)
    assert np.allclose(out, audio, atol=1e-4), "无任何调整时应近似直通"


def test_voice_changer_volume_adjust_scales_amplitude():
    vc = VoiceChanger()
    vc.add_profile(VoiceProfile(name="vol", volume_adjust=0.5))
    audio = np.linspace(-0.4, 0.4, 2000).astype(np.float32)
    out = vc.apply_voice_change(audio, 22050, "vol")
    ratio = float(np.max(np.abs(out)) / np.max(np.abs(audio)))
    assert ratio == pytest.approx(1.5, rel=1e-3), "volume_adjust=0.5 应放大 1.5 倍"


def test_voice_changer_speed_change_with_zero_pitch_now_works():
    """回归锁（2026-10-09 修）：pitch_shift==0 时改 speed_factor 曾被静默丢弃。

    根因：`signal` 只在 pitch 分支内 `from scipy import signal`，但 speed 分支也
    引用它 → UnboundLocalError 被外层 except 吞掉 → 原样返回入参。
    修法：import 提到方法开头一次绑定。
    """
    vc = VoiceChanger()
    vc.add_profile(VoiceProfile(name="spd", pitch_shift=0.0, speed_factor=2.0))
    audio = _make_sine(0.1, amp=0.4)
    out = vc.apply_voice_change(audio, 22050, "spd")
    assert len(out) == pytest.approx(len(audio) / 2, abs=2), \
        "speed_factor=2.0 应把样本数减半（修复前完全没变）"


def test_voice_changer_custom_pitch_profile_changes_length():
    # 自定义 profile 不含 eq_bands，可干净验证「音高分支」的编排（会绑定 signal）
    vc = VoiceChanger()
    vc.add_profile(VoiceProfile(name="pit", pitch_shift=3.0))
    audio = _make_sine(0.1, amp=0.5)
    out = vc.apply_voice_change(audio, 22050, "pit")
    assert out.dtype == np.float32
    assert len(out) == pytest.approx(len(audio) * 1.25, abs=2), \
        "pitch_shift=+3 半音应把样本数放大 ~1.25 倍"
    assert float(np.max(np.abs(out))) <= 1.0, "输出须裁剪到 [-1,1]"


def test_voice_changer_default_profile_now_applies():
    """回归锁（2026-10-09 修）：默认声线在 22050Hz 下变声曾**整体静默失效**。

    根因：`_apply_band_eq` 的 "high" 频段写死 high_freq=20000，对 nyquist=11025Hz
    的音频 high/nyquist > 1 → scipy.butter 抛 ValueError；`_apply_band_eq` 只捕
    ImportError，ValueError 冒泡到 apply_voice_change 的 except 被吞 ⇒ **原样返回
    入参**。5 个内置声线的 eq_bands 都含 "high" ⇒ 全部变声无效且无提示。
    修法：频点夹进 (0, nyquist) 开区间 + 补 ValueError 兜底。
    """
    vc = VoiceChanger()
    audio = _make_sine(0.1, amp=0.5)
    out = vc.apply_voice_change(audio, 22050, "male_deep")   # pitch=-2 speed=0.95
    assert out is not audio, "不该原样回传入参（那意味着变声整条链被吞）"
    assert len(out) != len(audio), "pitch=-2 + speed=0.95 应改变样本数"
    assert out.dtype == np.float32
    assert float(np.max(np.abs(out))) <= 1.0


def test_voice_changer_profile_crud():
    vc = VoiceChanger()
    names = sorted(vc._profiles.keys())
    assert names == ["child_cute", "female_mature", "female_sweet",
                     "male_deep", "male_normal"]
    assert vc.get_profile("male_deep").pitch_shift == pytest.approx(-2.0)
    assert vc.get_profile("nope") is None
    assert len(vc.get_profiles()) == 5

    vc.add_profile(VoiceProfile(name="custom"))
    assert vc.get_profile("custom") is not None
    assert vc.remove_profile("custom") is True
    assert vc.remove_profile("custom") is False, "重复移除应返回 False"


def test_voice_ducking_trims_to_min_length_and_lowers_bgm():
    vd = VoiceDucking()
    voice = np.zeros(4000, dtype=np.float32)
    voice[:2048] = 1.0                               # 前半段有声，后半段静音（能量须有起伏）
    bgm = np.ones(5000, dtype=np.float32)            # 比 voice 长
    v, d = vd.apply_ducking(voice, bgm, 22050)       # 默认 ducking_amount=0.7
    assert v.shape == d.shape == (4000,), "两轨须对齐到较短长度"
    assert float(d.min()) < 1.0, "有声段落 BGM 应被压低（闪避生效）"
    assert float(v.max()) == pytest.approx(1.0), "原始人声轨不应被改写"


def test_voice_ducking_silent_voice_keeps_bgm_near_unity():
    vd = VoiceDucking()
    voice = np.zeros(4000, dtype=np.float32)         # 全程静音 → 无闪避触发
    bgm = np.ones(4000, dtype=np.float32)
    _, d = vd.apply_ducking(voice, bgm, 22050)
    assert float(d.min()) > 0.99, "无人声时 BGM 应基本保持原音量"


def test_audio_processor_delegates_beats_and_profiles():
    proc = AudioProcessor()
    assert len(proc.get_voice_profiles()) == 5
    sig = np.zeros(22050 * 2, dtype=np.float32)
    for t in (0.4, 0.9, 1.4):
        i = int(t * 22050)
        sig[i:i + 200] = 0.8
    beats = proc.detect_bgm_beats(sig, 22050)
    assert len(beats) == len(proc.get_beat_points()) > 0
    proc.clear_beats()
    assert proc.get_beat_points() == []


def test_audio_processor_denoise_falls_back_to_scipy_highpass(monkeypatch):
    # 强制 noisereduce 不可用 → 回退到 scipy 高通；不得抛异常、不得改长度
    _disable_import(monkeypatch, "noisereduce")
    audio = _make_sine(0.1, amp=0.5)
    out = AudioProcessor().denoise(audio, 22050)
    assert out.shape == audio.shape


def test_audio_processor_compressor_and_reverb_fallback_passthrough(monkeypatch):
    _disable_import(monkeypatch, "pedalboard")       # 强制走 except ImportError 分支
    proc = AudioProcessor()
    audio = _make_sine(0.05, amp=0.5)
    assert np.array_equal(proc.compressor(audio, 22050), audio)
    assert np.array_equal(proc.add_reverb(audio, 22050), audio)


def test_audio_processor_loudness_fallback_peak_normalizes(monkeypatch):
    _disable_import(monkeypatch, "pyloudnorm")       # 强制走峰值归一化回退
    proc = AudioProcessor()
    audio = np.array([0.1, -0.2, 0.3], dtype=np.float32)
    out = proc.loudness_normalize(audio, 22050, target_lufs=-16.0)
    assert float(np.max(np.abs(out))) == pytest.approx(0.9, rel=1e-4)


def test_audio_processor_eq_all_zero_gains_is_passthrough():
    proc = AudioProcessor()
    audio = _make_sine(0.05, amp=0.5)
    out = proc.eq_equalizer(audio, 22050, [0] * 10)  # 全 0：不触发任何滤波
    assert np.allclose(out, audio)


# ═══════════════════════════════════════════════════════════════════════════
#  § 2  music_recommendation
# ═══════════════════════════════════════════════════════════════════════════

from app.core.music_recommendation import (  # noqa: E402
    MusicAutoSync, MusicGenre, MusicMood, MusicRecommendationEngine,
    MusicTempo, MusicTrack, SceneMusicRequirement,
)


@pytest.fixture
def music_engine():
    return MusicRecommendationEngine()


def test_music_library_initialized_with_ten_tracks(music_engine):
    lib = music_engine.get_music_library()
    assert len(lib) == 10
    assert "music_001" in lib and lib["music_004"].genre is MusicGenre.EPIC
    # get_music_library 返回副本
    lib.clear()
    assert len(music_engine.get_music_library()) == 10


def test_music_track_to_dict(music_engine):
    t = music_engine.get_music_library()["music_001"]
    d = t.to_dict()
    assert d["genre"] == "pop" and d["mood"] == "happy"
    assert d["tempo"] == "medium" and d["bpm"] == 120
    assert d["tags"] == ["happy", "upbeat", "energetic"]


def test_recommend_sad_long_scene_picks_melancholy_slow(music_engine):
    req = SceneMusicRequirement(scene_type="x", emotion="sad", duration=200.0)
    res = music_engine.recommend_music(req)
    assert [t.id for t in res] == ["music_006"]
    assert res[0].mood is MusicMood.MELANCHOLY
    assert res[0].confidence > 0
    assert music_engine.get_recommendations() == res, "结果须缓存到 _recommendations"


def test_recommend_sorted_desc_by_confidence(music_engine):
    req = SceneMusicRequirement(scene_type="x", emotion="happy", duration=60.0)
    res = music_engine.recommend_music(req)
    ids = [t.id for t in res]
    assert set(ids) == {"music_001", "music_008", "music_010"}
    assert all(t.tempo is MusicTempo.MEDIUM for t in res)
    confs = [t.confidence for t in res]
    assert confs == sorted(confs, reverse=True), "须按置信度降序"


def test_recommend_honors_excluded_genres(music_engine):
    req = SceneMusicRequirement(scene_type="x", emotion="sad", duration=200.0,
                                excluded_genres=["drama"])
    res = music_engine.recommend_music(req)
    assert res, "排除唯一 sad 匹配后应回退到全部候选再按节奏筛"
    assert all(t.genre.value != "drama" for t in res), "drama 必须被排除"


def test_recommend_mood_fallback_returns_all_when_no_mood_match(music_engine):
    # 情绪 "surprised" 只映射 MYSTERIOUS，若被类型排除后无匹配，_match_mood 回退全集
    req = SceneMusicRequirement(scene_type="x", emotion="surprised", duration=200.0)
    res = music_engine.recommend_music(req)
    assert [t.id for t in res] == ["music_009"]     # ambient/mysterious/slow


def test_recommend_empty_when_tempo_filter_excludes_all(music_engine):
    # duration<30 推断 FAST；sad 匹配只有 SLOW 的 melanchol → 空
    req = SceneMusicRequirement(scene_type="x", emotion="sad", duration=10.0)
    assert music_engine.recommend_music(req) == []


def test_match_tempo_bpm_filters(music_engine):
    # duration=0 时跳过「节奏类型」筛选，只留 BPM 过滤，便于单测
    req = SceneMusicRequirement(scene_type="x", emotion="neutral", duration=0.0,
                                min_bpm=121, max_bpm=150)
    lib = list(music_engine.get_music_library().values())
    out = music_engine._match_tempo(lib, req)
    assert sorted(t.id for t in out) == ["music_004", "music_007"]  # 140 / 128

    # 边界包含：min_bpm=120 时 bpm=120 的 music_001 也应入选
    req2 = SceneMusicRequirement(scene_type="x", emotion="neutral", duration=0.0,
                                 min_bpm=120, max_bpm=120)
    out2 = music_engine._match_tempo(lib, req2)
    assert [t.id for t in out2] == ["music_001"]

    # 无 bpm 的曲目会被 BPM 过滤剔除
    no_bpm = MusicTrack(id="nb", title="nb", artist="a", genre=MusicGenre.POP,
                        mood=MusicMood.CALM, tempo=MusicTempo.MEDIUM,
                        duration=100.0, file_path="x", bpm=None)
    assert music_engine._match_tempo([no_bpm], req) == []


def test_match_mood_returns_subset_or_all(music_engine):
    lib = list(music_engine.get_music_library().values())
    happy = music_engine._match_mood(lib, "happy")
    assert happy and all(t.mood in (MusicMood.HAPPY, MusicMood.HOPEFUL) for t in happy)
    assert len(happy) < len(lib), "应返回匹配子集而非全集"
    # 传入的曲目情绪都不匹配 "happy" 时 → 回退返回全职（不丢候选）
    calm = [t for t in lib if t.mood is MusicMood.CALM]
    assert music_engine._match_mood(calm, "happy") == calm


def test_related_tempos_boundaries(music_engine):
    def rt(dur):
        return music_engine._get_related_tempos(
            SceneMusicRequirement("x", "happy", dur))
    assert rt(29.0) == ["fast", "medium"]
    assert rt(30.0) == ["medium", "slow"]
    assert rt(119.0) == ["medium", "slow"]
    assert rt(120.0) == ["slow"]


def test_related_genres_single_works_multi_genre_bug(music_engine):
    assert sorted(music_engine._get_related_genres(["pop"])) == ["electronic", "rnb"]
    # ★ 缺陷记录：多类型时循环内 `related = ...` 覆盖上一轮结果，只保留最后一个类型的关联
    got = sorted(music_engine._get_related_genres(["pop", "rock"]))
    assert got == ["electronic", "hiphop"], "（缺陷）第一个类型的关联被丢弃"


def test_calculate_match_score_orders_exact_related_unrelated(music_engine):
    req = SceneMusicRequirement(scene_type="x", emotion="happy", duration=60.0)
    dur, genre, tempo = 60.0, MusicGenre.POP, MusicTempo.MEDIUM

    def mk(track_id, mood):
        return MusicTrack(id=track_id, title=track_id, artist="a", genre=genre,
                          mood=mood, tempo=tempo, duration=dur, file_path="x", bpm=120)

    exact = music_engine._calculate_match_score(mk("e", MusicMood.HAPPY), req)
    related = music_engine._calculate_match_score(mk("r", MusicMood.HOPEFUL), req)
    unrelated = music_engine._calculate_match_score(mk("u", MusicMood.SAD), req)
    assert exact > related > unrelated
    assert exact == pytest.approx(0.7, abs=1e-6)      # 0.4 + 0.2 tempo + 0.1 duration


def test_generate_match_reason_content(music_engine):
    req = SceneMusicRequirement(scene_type="x", emotion="happy", duration=100.0,
                                min_bpm=100)
    exact = MusicTrack(id="e", title="e", artist="a", genre=MusicGenre.POP,
                       mood=MusicMood.HAPPY, tempo=MusicTempo.MEDIUM,
                       duration=100.0, file_path="x", bpm=120)
    reason = music_engine._generate_match_reason(exact, req)
    assert "情绪匹配(happy)" in reason and "时长接近" in reason and "节奏符合" in reason

    plain = MusicTrack(id="p", title="p", artist="a", genre=MusicGenre.JAZZ,
                       mood=MusicMood.SAD, tempo=MusicTempo.SLOW,
                       duration=1000.0, file_path="x", bpm=None)
    assert music_engine._generate_match_reason(plain, req) == "综合推荐"


def test_search_music_by_tag_then_genre_then_mood(music_engine):
    assert [t.id for t in music_engine.search_music("epic")] == ["music_004"]
    by_genre = music_engine.search_music("zzz", genre=MusicGenre.ROMANTIC)
    assert [t.id for t in by_genre] == ["music_002"]
    by_mood = music_engine.search_music("zzz", mood=MusicMood.TENSE)
    assert [t.id for t in by_mood] == ["music_003"]


def test_music_library_add_remove_and_clear(music_engine):
    new = MusicTrack(id="new", title="t", artist="a", genre=MusicGenre.POP,
                     mood=MusicMood.HAPPY, tempo=MusicTempo.FAST,
                     duration=100.0, file_path="f")
    assert music_engine.add_music(new) is True
    assert music_engine.get_music_library()["new"] is new
    assert music_engine.remove_music("new") is True
    assert music_engine.remove_music("new") is False

    music_engine.recommend_music(SceneMusicRequirement("x", "sad", 200.0))
    assert music_engine.get_recommendations()
    music_engine.clear_recommendations()
    assert music_engine.get_recommendations() == []


def test_export_library_success_and_failure(music_engine, tmp_path):
    ok = tmp_path / "lib.json"
    assert music_engine.export_library(str(ok)) is True
    data = json.loads(ok.read_text(encoding="utf-8"))
    assert data["total_tracks"] == 10 and len(data["tracks"]) == 10
    # 目录当文件写 → 失败返回 False（不得抛异常）
    assert music_engine.export_library(str(tmp_path)) is False


def test_auto_sync_music_to_timeline(music_engine):
    syncer = MusicAutoSync(music_engine)
    progress = []
    out = syncer.auto_sync_music_to_timeline(
        [{"type": "s", "emotion": "sad", "duration": 200.0,
          "start_time": 0.0, "end_time": 10.0}],
        progress_callback=lambda p, m: progress.append(p))
    assert out["total_scenes"] == 1 and out["synced_scenes"] == 1
    assert len(out["sync_results"]) == 1
    assert out["sync_results"][0]["recommended_music"]["id"] == "music_006"
    assert out["average_confidence"] == pytest.approx(
        out["sync_results"][0]["sync_confidence"])
    assert progress[-1] == 100

    empty = syncer.auto_sync_music_to_timeline([])
    assert empty == {"total_scenes": 0, "synced_scenes": 0,
                     "sync_results": [], "average_confidence": 0.0}


# ═══════════════════════════════════════════════════════════════════════════
#  § 3  voice_generator  —— 重点：降级链 / 诚实失败铁律
# ═══════════════════════════════════════════════════════════════════════════

from app.core.voice_generator import (  # noqa: E402
    AIVoiceGenerator, EffectRecommendationEngine, VoiceGenerationRequest,
    VoiceGenerationResult, VoiceGenerator, VoiceProfile as VGVoiceProfile,
    VoiceGender, VoiceStyle, VoiceAge,
)


@pytest.fixture
def vgen():
    return AIVoiceGenerator()


def test_default_profiles_and_alias(vgen):
    profiles = vgen.get_voice_profiles()
    assert len(profiles) == 6
    assert all(p.is_default for p in profiles)
    assert VoiceGenerator is AIVoiceGenerator, "兼容别名须指向同一类"


def test_dataclasses_to_dict(vgen):
    p = vgen.get_voice_profile("female_young_casual")
    d = p.to_dict()
    assert d["gender"] == "female" and d["age"] == "young" and d["style"] == "casual"
    req = VoiceGenerationRequest(text="hi", voice_profile_id=p.id, speed=1.2)
    assert req.to_dict()["speed"] == 1.2
    res = VoiceGenerationResult(request_id="1", audio_data=None, audio_path=None,
                                duration=0.0, sample_rate=0, success=False)
    assert res.to_dict()["success"] is False and res.created_at


def test_generate_voice_unknown_profile_fails_honestly(vgen):
    res = vgen.generate_voice(VoiceGenerationRequest("hi", "nope"))
    assert res.success is False
    assert res.audio_data is None and res.audio_path is None
    assert res.sample_rate == 0 and res.duration == 0.0
    assert "声线配置不存在" in res.error_message


def test_generate_voice_success_path_orchestration(vgen, monkeypatch):
    fixed = np.linspace(-0.5, 0.5, 11025).astype(np.float32)
    monkeypatch.setattr(vgen, "_generate_tts_audio", lambda req, prof: fixed)
    progress = []
    res = vgen.generate_voice(
        VoiceGenerationRequest("你好世界", "male_adult_calm", speed=1.0),
        progress_callback=lambda p, m: progress.append(p))

    assert res.success is True and res.audio_data is fixed
    prof = vgen.get_voice_profile("male_adult_calm")
    assert res.sample_rate == prof.sample_rate
    assert res.duration == pytest.approx(len(fixed) / prof.sample_rate)
    assert res.generation_time >= 0.0
    assert vgen.get_generation_result(res.request_id) is res, "成功结果须可被检索"
    assert progress[0] == 0 and progress[-1] == 100


def test_generate_voice_engine_exception_fails_honestly(vgen, monkeypatch):
    def boom(req, prof):
        raise RuntimeError("引擎炸了")
    monkeypatch.setattr(vgen, "_generate_tts_audio", boom)
    res = vgen.generate_voice(VoiceGenerationRequest("hi", "male_adult_calm"))
    assert res.success is False
    assert res.audio_data is None, "异常时绝不能返回任何音频"
    assert res.error_message == "引擎炸了"


def test_IRON_LAW_all_engines_unavailable_fails_honestly(vgen, monkeypatch):
    """★ 铁律：所有 TTS 引擎不可用 ⇒ **诚实失败**，绝不返回假音频。

    修前（2026-10-09 之前）：`_generate_tts_audio` 合成 220Hz 正弦波、
    `generate_voice` 无条件 success=True ⇒ 用户拿到"时长对、内容全是嗡声"的
    配音却毫无察觉。修后：返回 None → generate_voice 给 success=False +
    可读的 error_message；正弦波只在 SHIGUANG_ALLOW_PLACEHOLDER_TTS=1 下出现，
    且被标 is_placeholder=True。
    """
    _disable_import(monkeypatch, "TTS", "gtts")
    monkeypatch.delenv("SHIGUANG_ALLOW_PLACEHOLDER_TTS", raising=False)

    class _R:
        returncode = 1
        stdout = b""
    monkeypatch.setattr("subprocess.run", lambda *a, **k: _R())

    prof = vgen.get_voice_profile("male_adult_calm")
    assert vgen._generate_tts_audio(VoiceGenerationRequest("测试文本", prof.id), prof) is None

    res = vgen.generate_voice(VoiceGenerationRequest("测试文本", prof.id))
    assert res.success is False, "引擎全挂时必须诚实失败"
    assert res.audio_data is None, "绝不能返回假音频"
    assert res.is_placeholder is False
    assert "TTS" in res.error_message and "SHIGUANG_ALLOW_PLACEHOLDER_TTS" in res.error_message


def test_placeholder_opt_in_returns_sine_and_is_marked(vgen, monkeypatch):
    """显式打开开关才给占位音，且必须**留痕**（is_placeholder=True）。"""
    _disable_import(monkeypatch, "TTS", "gtts")
    monkeypatch.setenv("SHIGUANG_ALLOW_PLACEHOLDER_TTS", "1")

    class _R:
        returncode = 1
        stdout = b""
    monkeypatch.setattr("subprocess.run", lambda *a, **k: _R())

    prof = vgen.get_voice_profile("male_adult_calm")
    res = vgen.generate_voice(VoiceGenerationRequest("测试文本", prof.id))
    assert res.success is True and res.audio_data is not None
    assert res.is_placeholder is True, "占位音必须在结果里留痕"
    assert res.to_dict()["is_placeholder"] is True, "to_dict 必须带上该字段"
    assert float(np.max(np.abs(res.audio_data))) == pytest.approx(0.3, abs=1e-3)


def test_placeholder_flag_does_not_leak_across_calls(vgen, monkeypatch):
    """上一轮用了占位音，下一轮真实引擎成功时不能再标 is_placeholder。"""
    _disable_import(monkeypatch, "TTS", "gtts")
    monkeypatch.setenv("SHIGUANG_ALLOW_PLACEHOLDER_TTS", "1")

    class _R:
        returncode = 1
        stdout = b""
    monkeypatch.setattr("subprocess.run", lambda *a, **k: _R())

    prof = vgen.get_voice_profile("male_adult_calm")
    vgen.generate_voice(VoiceGenerationRequest("测试文本", prof.id))  # 占位

    # 换成一个"真实引擎成功"的假实现
    real = _make_sine(0.05)
    monkeypatch.setattr(vgen, "_generate_tts_audio", lambda req, p: real)
    res = vgen.generate_voice(VoiceGenerationRequest("测试文本", prof.id))
    assert res.is_placeholder is False, "is_placeholder 不该串味"


def test_generate_tts_audio_sine_fallback_shape(vgen, monkeypatch):
    """占位音的**形状**契约：float32 / 时长 = max(1.0, len*0.15) / 幅值 0.3。"""
    _disable_import(monkeypatch, "TTS", "gtts")
    monkeypatch.setenv("SHIGUANG_ALLOW_PLACEHOLDER_TTS", "1")

    class _R:
        returncode = 1
        stdout = b""
    monkeypatch.setattr("subprocess.run", lambda *a, **k: _R())

    prof = vgen.get_voice_profile("male_adult_calm")
    audio = vgen._generate_tts_audio(VoiceGenerationRequest("ab", prof.id), prof)
    assert isinstance(audio, np.ndarray) and audio.dtype == np.float32
    assert len(audio) == prof.sample_rate          # duration_sec = max(1.0, 2*0.15)=1.0
    assert float(np.max(np.abs(audio))) == pytest.approx(0.3, abs=1e-3)


def test_generate_tts_audio_applies_speed_and_pitch(vgen, monkeypatch):
    _disable_import(monkeypatch, "TTS", "gtts")
    monkeypatch.setenv("SHIGUANG_ALLOW_PLACEHOLDER_TTS", "1")

    class _R:
        returncode = 1
        stdout = b""
    monkeypatch.setattr("subprocess.run", lambda *a, **k: _R())

    prof = vgen.get_voice_profile("male_adult_calm")
    base = vgen._generate_tts_audio(VoiceGenerationRequest("ab", prof.id), prof)

    sped = vgen._generate_tts_audio(
        VoiceGenerationRequest("ab", prof.id, speed=2.0), prof)
    assert len(sped) == pytest.approx(len(base) / 2, rel=0.02), "speed 应缩短时长"

    loud = vgen._generate_tts_audio(
        VoiceGenerationRequest("ab", prof.id, pitch=2.0), prof)
    assert float(np.max(np.abs(loud))) == pytest.approx(0.6, abs=2e-3), "pitch 应放大幅值"


def test_generate_audio_empty_text_fails(vgen):
    assert vgen.generate_audio("   ") == {"success": False, "error": "文本为空"}


def test_generate_audio_writes_wav_on_success(vgen, monkeypatch, tmp_path):
    monkeypatch.setattr(vgen, "_generate_tts_audio",
                        lambda req, prof: _make_sine(0.05))
    out = tmp_path / "out.wav"
    res = vgen.generate_audio("你好", output_path=str(out))
    assert res["success"] is True and res["guarded"] is False
    assert res["audio_path"] == str(out) and out.exists()
    with wave.open(str(out), "rb") as wf:
        assert wf.getnchannels() == 1 and wf.getsampwidth() == 2
        assert wf.getnframes() > 0


def test_generate_audio_engine_failure_returns_error_without_file(vgen, monkeypatch, tmp_path):
    monkeypatch.setattr(vgen, "_generate_tts_audio",
                        lambda req, prof: (_ for _ in ()).throw(RuntimeError("no engine")))
    out = tmp_path / "should_not_exist.wav"
    res = vgen.generate_audio("你好", output_path=str(out))
    assert res["success"] is False and "no engine" in res["error"]
    assert not out.exists(), "失败时绝不能落盘假产物"


def test_generate_audio_guard_passthrough(vgen, monkeypatch):
    sentinel = {"success": True, "guarded": True, "segments": 3, "audio_path": "x"}
    monkeypatch.setattr(vgen, "_generate_audio_guarded", lambda *a, **k: sentinel)
    assert vgen.generate_audio("很长很长", guard=True) is sentinel


def test_generate_audio_guard_none_falls_through(vgen, monkeypatch):
    monkeypatch.setattr(vgen, "_generate_audio_guarded", lambda *a, **k: None)
    monkeypatch.setattr(vgen, "_generate_tts_audio", lambda req, prof: _make_sine(0.05))
    res = vgen.generate_audio("短句", guard=True)
    assert res["success"] is True and res["guarded"] is False


def test_generate_audio_guarded_short_text_returns_none(vgen, monkeypatch):
    # plan_tts 只给一段 → 视为短句，返回 None 让调用方走原路径
    import app.core.ai.tts_guard as tg
    monkeypatch.setattr(tg, "plan_tts",
                        lambda text, max_chars=40, llm=None: {"segments": [{"index": 0, "text": text}]})
    assert vgen._generate_audio_guarded("短", voice_profile_id="male_adult_calm") is None


def test_generate_audio_guarded_merges_segments(vgen, monkeypatch, tmp_path):
    import app.core.ai.tts_guard as tg
    monkeypatch.setattr(tg, "plan_tts",
                        lambda text, max_chars=40, llm=None: {"segments": [
                            {"index": 0, "text": "第一段"},
                            {"index": 1, "text": "第二段"},
                            {"index": 2, "text": "第三段"}]})

    def fake_gen(req):
        return VoiceGenerationResult(request_id=req.text, audio_data=np.ones(10, np.float32),
                                     audio_path=None, duration=0.0, sample_rate=22050,
                                     success=True)
    monkeypatch.setattr(vgen, "generate_voice", fake_gen)

    out = tmp_path / "guarded.wav"
    res = vgen._generate_audio_guarded("x", output_path=str(out),
                                       voice_profile_id="male_adult_calm")
    assert res["success"] is True and res["guarded"] is True and res["segments"] == 3
    with wave.open(str(out), "rb") as wf:
        assert wf.getnframes() == 30, "三段各 10 采样须拼接为 30"


def test_generate_audio_guarded_segment_failure_is_honest(vgen, monkeypatch):
    import app.core.ai.tts_guard as tg
    monkeypatch.setattr(tg, "plan_tts",
                        lambda text, max_chars=40, llm=None: {"segments": [
                            {"index": 0, "text": "a"}, {"index": 1, "text": "b"}]})
    calls = {"n": 0}

    def fake_gen(req):
        calls["n"] += 1
        if calls["n"] == 2:
            return VoiceGenerationResult(request_id="1", audio_data=None, audio_path=None,
                                         duration=0.0, sample_rate=0, success=False,
                                         error_message="引擎缺失")
        return VoiceGenerationResult(request_id="1", audio_data=np.ones(5, np.float32),
                                     audio_path=None, duration=0.0, sample_rate=22050,
                                     success=True)
    monkeypatch.setattr(vgen, "generate_voice", fake_gen)

    res = vgen._generate_audio_guarded("x", voice_profile_id="male_adult_calm")
    assert res["success"] is False and res["guarded"] is True and res["segments"] == 2
    assert "第 2/2 段合成失败" in res["error"] and "引擎缺失" in res["error"]


def test_generate_audio_guarded_max_chars_fallback(vgen, monkeypatch):
    import app.core.ai.tts_guard as tg
    seen = {}

    def fake_plan(text, max_chars=40, llm=None):
        seen["max_chars"] = max_chars
        return {"segments": [{"index": 0, "text": text}]}
    monkeypatch.setattr(tg, "plan_tts", fake_plan)
    # guard_max_chars="abc" 无法转 int → 回退默认 40
    vgen._generate_audio_guarded("x", voice_profile_id="male_adult_calm",
                                 guard_max_chars="abc")
    assert seen["max_chars"] == 40


def test_write_wav_success_returns_none_and_failure_returns_message(tmp_path):
    ok = tmp_path / "w.wav"
    assert AIVoiceGenerator._write_wav(str(ok), np.ones(100, np.float32), 22050) is None
    assert ok.exists()
    # 目标是一个已存在的目录 → 打开失败 → 返回错误字符串
    err = AIVoiceGenerator._write_wav(str(tmp_path), np.ones(10, np.float32), 22050)
    assert isinstance(err, str) and err


def test_write_wav_clips_out_of_range(tmp_path):
    out = tmp_path / "clip.wav"
    data = np.array([2.0, -2.0, 0.0], dtype=np.float32)
    assert AIVoiceGenerator._write_wav(str(out), data, 22050) is None
    with wave.open(str(out), "rb") as wf:
        frames = np.frombuffer(wf.readframes(3), dtype=np.int16)
    assert frames[0] == 32767 and frames[1] == -32767 and frames[2] == 0


def test_batch_generate_count_and_progress(vgen, monkeypatch):
    monkeypatch.setattr(vgen, "generate_voice",
                        lambda req, *a, **k: VoiceGenerationResult(
                            request_id=req.text, audio_data=np.ones(1, np.float32),
                            audio_path=None, duration=0.0, sample_rate=22050, success=True))
    reqs = [VoiceGenerationRequest(f"t{i}", "male_adult_calm") for i in range(3)]
    progress = []
    results = vgen.batch_generate(reqs, progress_callback=lambda p, m: progress.append(p))
    assert len(results) == 3 and all(r.success for r in results)
    assert progress == [33, 66, 100]


def test_profile_crud_results_and_export(vgen, tmp_path):
    prof = VGVoiceProfile(id="custom", name="自定义", gender=VoiceGender.NEUTRAL,
                          age=VoiceAge.ADULT, style=VoiceStyle.PROFESSIONAL)
    assert vgen.add_voice_profile(prof) is True
    assert vgen.get_voice_profile("custom") is prof
    assert vgen.remove_voice_profile("custom") is True
    assert vgen.remove_voice_profile("custom") is False

    # clear_results 清空生成结果表
    vgen._results["k"] = object()
    vgen.clear_results()
    assert vgen.get_generation_result("k") is None

    ok = tmp_path / "profiles.json"
    assert vgen.export_profiles(str(ok)) is True
    data = json.loads(ok.read_text(encoding="utf-8"))
    assert data["total_profiles"] == 6
    assert vgen.export_profiles(str(tmp_path)) is False


def test_effect_recommendation_engine_dedup_and_sort():
    eng = EffectRecommendationEngine()
    recs = eng.recommend_effects("climax", "happy", "counterattack", confidence=1.0)
    assert recs, "命中三类规则应有推荐"
    ids = [r["effect_id"] for r in recs]
    assert len(ids) == len(set(ids)), "必须去重"
    confs = [r["confidence"] for r in recs]
    assert confs == sorted(confs, reverse=True), "须按置信度降序"
    assert len(recs) <= 10
    # gold_rush 同时出现在 scene(climax) 与 genre(counterattack)，应保留置信度更高的来源
    gold = [r for r in recs if r["effect_id"] == "gold_rush"]
    assert gold and gold[0]["confidence"] == pytest.approx(1.0 * 0.9)

    assert eng.recommend_effects("unknown", "unknown", "unknown") == []


def test_effect_recommendation_custom_rules():
    eng = EffectRecommendationEngine()
    # 自定义规则须挂到 recommend_effects 会查询的三张内置表之一（genre_to_effect）
    eng.add_custom_rule("genre_to_effect", "my_genre", ["eff_a"])
    recs = eng.recommend_effects("unknown", "unknown", "my_genre")
    assert [r["effect_id"] for r in recs] == ["eff_a"]
    art = recs[0]
    assert art["source"] == "genre" and art["confidence"] == pytest.approx(0.8 * 0.8)
    eng.remove_custom_rule("genre_to_effect", "my_genre")
    assert eng.recommend_effects("unknown", "unknown", "my_genre") == []


# ═══════════════════════════════════════════════════════════════════════════
#  § 4  lip_sync
# ═══════════════════════════════════════════════════════════════════════════

from app.core.lip_sync import (  # noqa: E402
    LipSyncEngine, MouthParams, VISEME_TABLE,
)


@pytest.fixture
def ls():
    return LipSyncEngine(fps=25, smoothing_window=3)


def test_viseme_table_structure(ls):
    assert len(VISEME_TABLE) == 13
    assert "REST" in VISEME_TABLE and "A" in VISEME_TABLE
    info = ls.get_viseme_table_info()
    assert len(info) == 13
    assert set(info[0].keys()) == {"id", "name", "description", "phonemes", "params"}
    assert set(info[0]["params"].keys()) == {"jaw_open", "mouth_width", "lip_round", "lip_pucker"}


def test_viseme_to_params_intensity_clamp_and_rest(ls):
    vp = ls.viseme_to_params("A", intensity=0.5)
    assert vp.jaw_open == pytest.approx(0.8 * 0.5)
    assert vp.is_speaking is True and vp.rms_energy == pytest.approx(0.5)
    # intensity >1.25 时 jaw_open 被钳制到 1.0
    big = ls.viseme_to_params("A", intensity=5.0)
    assert big.jaw_open == 1.0
    rest = ls.viseme_to_params("REST")
    assert rest.is_speaking is False and rest.jaw_open == 0.0
    unknown = ls.viseme_to_params("QQQ")
    # ★ 注意：未知 viseme 会回落到 REST 的**几何参数**，但 is_speaking 只看传入 id
    #   （`viseme_id != "REST"`）⇒ 被误判为「在说话」。此处钉住该可观察行为。
    assert unknown.jaw_open == 0.0 and unknown.mouth_width == 0.5
    assert unknown.is_speaking is True, "（缺陷）未知 id 回落到 REST 却仍标记为说话"


def test_phoneme_to_viseme_lookup_chain(ls):
    assert ls.phoneme_to_viseme("a") == "A"          # 直接命中 example_phonemes
    assert ls.phoneme_to_viseme("th") == "TH"
    assert ls.phoneme_to_viseme("b") == "B"          # 声母映射
    assert ls.phoneme_to_viseme("x") == "D"
    assert ls.phoneme_to_viseme("ai") == "I"         # 韵母映射
    assert ls.phoneme_to_viseme("ong") == "O"
    assert ls.phoneme_to_viseme("zhang") == "A"      # 先 endswith("ang") 命中韵母映射
    assert ls.phoneme_to_viseme("9") == "REST"       # 完全无法识别


def test_resample_1d_same_and_different_length(ls):
    same = ls._resample_1d(np.arange(5), 5)
    assert len(same) == 5 and same.dtype == np.float64 and same.tolist() == [0, 1, 2, 3, 4]
    up = ls._resample_1d(np.array([0.0, 1.0]), 5)
    assert len(up) == 5 and up[0] == pytest.approx(0.0) and up[-1] == pytest.approx(1.0)


def test_smooth_1d_short_and_long(ls):
    short = np.arange(3.0)
    assert np.array_equal(ls._smooth_1d(short, window=3), short)
    out = ls._smooth_1d(np.array([0.0, 0.0, 3.0, 0.0, 0.0]), window=3)
    assert len(out) == 5 and out[2] < 3.0, "尖峰应被均值平滑拉低"


def test_energy_to_mouth_params_frame_count_silence_and_speech(ls):
    rms = np.array([0.0, 0.0, 0.5, 1.0, 0.3, 0.0, 0.0])
    params = ls.energy_to_mouth_params(rms, audio_duration=1.0)
    assert len(params) == 25, "1s @ 25fps = 25 帧"
    assert params[0].time == 0.0
    assert params[1].time == pytest.approx(1 / 25)
    assert params[0].is_speaking is False and params[0].jaw_open == 0.0
    assert params[0].mouth_width == 0.5, "静音帧默认嘴宽 0.5"
    assert any(p.is_speaking for p in params), "存在有声帧"
    assert ls.energy_to_mouth_params(rms, audio_duration=0.0) == []


def test_energy_to_mouth_params_all_zero_energy(ls):
    params = ls.energy_to_mouth_params(np.zeros(10), audio_duration=0.5)
    assert all(p.is_speaking is False and p.jaw_open == 0.0 for p in params)


def test_extract_audio_features_shapes_and_silence(ls):
    sig = np.zeros(4096)
    feats = ls.extract_audio_features(sig, 22050)
    assert set(feats.keys()) == {"rms", "zcr", "spectral_centroid", "mfcc"}
    # n_frames = 1 + (4096-2048)//512 = 5
    assert feats["rms"].shape == (5,) and feats["zcr"].shape == (5,)
    assert feats["mfcc"].shape == (5, 13)
    assert np.all(feats["spectral_centroid"] == 0), "静音时谱质心为 0（走 else 分支）"

    short = ls.extract_audio_features(np.zeros(100), 22050)
    assert short["rms"].shape == (1,), "样本不足一帧时至少 1 帧"

    stereo = ls.extract_audio_features(np.zeros((2048, 2)), 22050)
    assert stereo["rms"].shape == (1,), "立体声须先混单声道"


def test_create_mel_filters_shape_and_nonneg(ls):
    filters = ls._create_mel_filters(40, 2048, 22050)
    assert filters.shape == (40, 1025)
    assert np.all(filters >= 0)
    assert all(filters[m].sum() > 0 for m in range(40)), "每个三角滤波器应有非零响应"


def test_asr_segments_to_params_empty_and_zero_duration(ls):
    assert ls.asr_segments_to_params([], audio_duration=0.0) == []
    params = ls.asr_segments_to_params([], audio_duration=1.0)
    assert len(params) == 25
    assert all(p.is_speaking is False for p in params), "无片段时间轴全静音"


def test_asr_segments_to_params_maps_viseme(ls, monkeypatch):
    monkeypatch.setattr(ls, "_text_to_phonemes", lambda text: ["a"])
    params = ls.asr_segments_to_params(
        [{"start": 0.0, "end": 0.5, "text": "阿"}], audio_duration=1.0)
    assert len(params) == 25
    speaking = [p for p in params if p.is_speaking]
    assert speaking, "片段覆盖帧应判定为说话"
    assert all(0.0 <= p.time <= 1.0 for p in params)


def test_asr_segments_to_params_low_energy_forces_rest(ls, monkeypatch):
    monkeypatch.setattr(ls, "_text_to_phonemes", lambda text: ["a"])
    # 仅首帧有能量、其余接近 0：归一化后低能量帧应被强制 REST（不张嘴）。
    # 注意：全 0 的 RMS 因 max_val==0 会令 rms_norm 保持 None，反而不触发该分支，
    #   故此处用「一个尖峰 + 大量微小值」构造 min/max 有落差的曲线。
    rms = np.full(25, 1e-4)
    rms[0] = 1.0
    params = ls.asr_segments_to_params(
        [{"start": 0.0, "end": 1.0, "text": "阿"}], audio_duration=1.0,
        rms_energy=rms)
    assert params[0].is_speaking is True, "高能量帧应张嘴"
    assert params[-1].is_speaking is False, "低能量帧应被强制 REST"


def test_asr_segment_indices_clamped_out_of_range(ls, monkeypatch):
    monkeypatch.setattr(ls, "_text_to_phonemes", lambda text: ["a"])
    # end 远超时长、start 为负 → 必须钳制到 [0, n_frames]，不越界
    params = ls.asr_segments_to_params(
        [{"start": -5.0, "end": 999.0, "text": "阿"}], audio_duration=0.5)
    assert len(params) == int(0.5 * 25)


def test_smooth_params_silence_and_mean(ls):
    silent = [MouthParams(time=i * 0.04, jaw_open=0.9, is_speaking=False) for i in range(5)]
    out = ls._smooth_params(silent)
    assert len(out) == 5
    assert all(p.jaw_open == 0.0 and p.mouth_width == 0.5 for p in out), \
        "全静音窗口须强制回静止"

    mixed = [MouthParams(time=i * 0.04, jaw_open=1.0, is_speaking=True) for i in range(5)]
    smoothed = ls._smooth_params(mixed)
    assert all(0.0 <= p.jaw_open <= 1.0 for p in smoothed)
    # 长度 <= window 时原样返回
    assert ls._smooth_params(mixed[:3]) is not None


def test_text_to_phonemes_via_annotate(ls, monkeypatch):
    import app.core.ai.pinyin_dict as pd
    monkeypatch.setattr(pd, "annotate", lambda text, **kw: {
        "ok": True,
        "chars": [
            {"cjk": True, "known": True, "pinyin": "zhang"},   # 声母zh + 韵母ang
            {"cjk": True, "known": True, "pinyin": "ni"},      # 声母n + 韵母i
            {"cjk": False, "known": False, "pinyin": None},    # 非汉字 → 不进音素
        ],
    })
    assert ls._text_to_phonemes("张你a") == ["zh", "ang", "n", "i"]


def test_text_to_phonemes_fallback_when_annotate_not_ok(ls, monkeypatch):
    import app.core.ai.pinyin_dict as pd
    monkeypatch.setattr(pd, "annotate", lambda text, **kw: {"ok": False, "message": "无字典"})
    # 降级到字符级：汉字→a，字母→小写，其他→sil
    assert ls._text_to_phonemes("好a1") == ["a", "a", "sil"]


def test_text_to_phonemes_fallback_when_annotate_raises(ls, monkeypatch):
    import app.core.ai.pinyin_dict as pd
    monkeypatch.setattr(pd, "annotate",
                        lambda text, **kw: (_ for _ in ()).throw(RuntimeError("boom")))
    assert ls._text_to_phonemes("hi") == ["h", "i"]
    assert ls._text_to_phonemes("") == ["a"], "空串须兜底为单音素"


def test_export_blendshapes_and_csv(ls, tmp_path):
    params = ls.energy_to_mouth_params(np.array([0.0, 0.5, 1.0]), audio_duration=0.4)
    assert ls.export_blendshapes([], str(tmp_path / "e.json")) is False

    jpath = tmp_path / "frames.json"
    assert ls.export_blendshapes(params, str(jpath)) is True
    data = json.loads(jpath.read_text(encoding="utf-8"))
    assert data["fps"] == 25 and data["frame_count"] == len(params)
    assert data["duration"] == pytest.approx(round(params[-1].time, 3))
    assert "jawOpen" in data["frames"][0]["blendshapes"]

    assert ls.export_keyframe_csv([], str(tmp_path / "e.csv")) is False
    cpath = tmp_path / "frames.csv"
    assert ls.export_keyframe_csv(params, str(cpath)) is True
    lines = cpath.read_text(encoding="utf-8").strip().splitlines()
    assert lines[0] == "time,jawOpen,mouthWidth,mouthPucker,mouthRound,energy"
    assert len(lines) == len(params) + 1


def test_analyze_audio_missing_soundfile_fails_honestly(ls, monkeypatch):
    _disable_import(monkeypatch, "soundfile")
    assert ls.analyze_audio("whatever.wav") == [], "音频库不可用须诚实返回空"


def test_analyze_audio_energy_mode_with_injected_soundfile(ls, monkeypatch):
    fake = types.ModuleType("soundfile")
    fake.read = lambda path: (_make_sine(0.4, sr=22050, amp=0.6), 22050)
    monkeypatch.setitem(sys.modules, "soundfile", fake)
    params = ls.analyze_audio("fake.wav", use_asr=False)
    assert len(params) == int(0.4 * 25) == 10
    assert any(p.is_speaking for p in params)


def test_analyze_audio_asr_mode_calls_asr(ls, monkeypatch):
    fake = types.ModuleType("soundfile")
    fake.read = lambda path: (_make_sine(0.4, sr=22050, amp=0.6), 22050)
    monkeypatch.setitem(sys.modules, "soundfile", fake)
    captured = {}

    def fake_asr(audio_path, language, model_size):
        captured["args"] = (audio_path, language, model_size)
        return [{"start": 0.0, "end": 0.4, "text": "阿"}]
    monkeypatch.setattr(ls, "_run_asr", fake_asr)
    monkeypatch.setattr(ls, "_text_to_phonemes", lambda text: ["a"])
    params = ls.analyze_audio("fake.wav", use_asr=True, asr_language="zh",
                              asr_model_size="tiny")
    assert captured["args"] == ("fake.wav", "zh", "tiny")
    assert len(params) == 10 and any(p.is_speaking for p in params)


def test_run_asr_no_engine_returns_empty(ls, monkeypatch):
    _disable_import(monkeypatch, "faster_whisper", "whisper")
    assert ls._run_asr("x.wav", "zh", "base") == []


def test_run_asr_maps_faster_whisper_segments(ls):
    class _Seg:
        def __init__(self, s, e, t):
            self.start, self.end, self.text = s, e, t

    class _Model:
        def transcribe(self, path, beam_size=5, language="zh"):
            return iter([_Seg(0.0, 0.5, "你好"), _Seg(0.5, 1.0, "世界")]), {"lang": "zh"}

    ls._asr_model = _Model()
    ls._use_original_whisper = False
    segs = ls._run_asr("x.wav", "zh", "base")
    assert segs == [{"start": 0.0, "end": 0.5, "text": "你好"},
                    {"start": 0.5, "end": 1.0, "text": "世界"}]
