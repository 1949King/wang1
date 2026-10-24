"""app/tests/test_zcov_media.py — 媒体类零覆盖模块补充用例。

覆盖 4 个此前 0% 的 core 模块：
  - app/core/subtitle_manager.py   （字幕对象/样式/解析/导出/ASS 时间码）
  - app/core/subtitle_generator.py （转写/纠错/样式/多格式导出）
  - app/core/lut_loader.py         （.cube/.3dl 解析、预设、缓存、LUT 应用）
  - app/core/waveform_generator.py （PCM 分桶降采样、WAV 回退、缓存）

原则（对齐 test_frame_cache.py 的风格）：
  - 每个用例断言**可观察行为**（返回值 / 异常 / 副作用 / 状态变化），不写空断言。
  - 纯函数优先测边界值（空/None/非法/临界）。
  - 需要外部二进制或模型的分支用 monkeypatch / tmp_path 隔离，不真联网、不真编码。
  - 该文件不修改任何源码；发现的可疑点见文末「DEFECT」用例的 docstring 与最终报告。

运行：
  cd /d/拾光剪影 && QT_QPA_PLATFORM=offscreen .venv312/Scripts/python.exe \
      -m pytest app/tests/test_zcov_media.py -q
"""
import os
import math
import json
import struct
import wave
import threading

import numpy as np
import pytest

from app.core.subtitle_manager import SubtitleManager
from app.core.subtitle_generator import (
    SubtitleFormat,
    SubtitleStyle,
    SubtitlePosition,
    SubtitleSegment,
    SubtitleStyleConfig,
    TypoCorrector,
    SubtitleStyler,
    WhisperTranscriber,
    SubtitleGenerator,
)
from app.core.lut_loader import LUTLoader, LUT3D
from app.core.waveform_generator import WaveformGenerator, WaveformData


# ══════════════════════════════════════════════════════════════════
# 公共辅助
# ══════════════════════════════════════════════════════════════════

def _write_wav(path, samples, channels=1, sampwidth=2, rate=44100):
    """把整数样本写成 WAV。samples 为单声道序列（多声道时会被复制到各声道）。"""
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sampwidth)
        wf.setframerate(rate)
        if sampwidth == 2:
            if channels == 1:
                data = struct.pack(f"<{len(samples)}h", *samples)
            else:
                data = struct.pack(f"<{len(samples) * channels}h",
                                   *[s for s in samples for _ in range(channels)])
        elif sampwidth == 1:
            data = bytes(samples)
        else:
            data = b"\x00" * (len(samples) * channels * sampwidth)
        wf.writeframes(data)
    return str(path)


def _ramp(n=2000):
    """-16000 ~ +16000 的线性斜坡（保证 RMS > 0，非静音）。"""
    return [int(-16000 + 32000 * i / (n - 1)) for i in range(n)]


def _write_cube(path, size, value_fn):
    """按 .cube 规范（红变化最快）写文件：value_fn(r_idx, g_idx, b_idx) -> (R,G,B)。"""
    lines = [f"LUT_3D_SIZE {size}"]
    for b in range(size):
        for g in range(size):
            for r in range(size):
                rr, gg, bb = value_fn(r, g, b)
                lines.append(f"{rr} {gg} {bb}")
    with open(str(path), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return str(path)


# ══════════════════════════════════════════════════════════════════
# ═══ subtitle_manager ═══
# ══════════════════════════════════════════════════════════════════

def test_create_subtitle_fields_and_id_sequence():
    """create_subtitle 生成递增 id、默认位置/可见性，并真正落入列表。"""
    mgr = SubtitleManager()
    s1 = mgr.create_subtitle("A", 1.0, 2.0)
    s2 = mgr.create_subtitle("B", 3.0, 4.0, style="title")
    assert s1["id"] == "subtitle_1" and s2["id"] == "subtitle_2"
    assert s1["position"] == {"x": 0.5, "y": 0.85}
    assert s1["visible"] is True
    assert s2["style"] == "title"
    assert len(mgr.subtitles) == 2


def test_update_delete_get_subtitle_return_paths():
    """update/get 命中→成功，未命中→False/None；delete 恒返回 True（设计如此）。"""
    mgr = SubtitleManager()
    mgr.create_subtitle("A", 0.0, 1.0)
    assert mgr.update_subtitle("subtitle_1", text="A2") is True
    assert mgr.get_subtitle("subtitle_1")["text"] == "A2"
    assert mgr.update_subtitle("nope") is False
    assert mgr.get_subtitle("nope") is None
    assert mgr.delete_subtitle("subtitle_1") is True
    assert mgr.list_subtitles() == []


def test_search_subtitles_is_case_insensitive():
    mgr = SubtitleManager()
    mgr.create_subtitle("Hello World", 0.0, 1.0)
    mgr.create_subtitle("other", 1.0, 2.0)
    hits = mgr.search_subtitles("hello")
    assert len(hits) == 1 and hits[0]["text"] == "Hello World"


def test_sort_subtitles_by_each_key():
    mgr = SubtitleManager()
    mgr.create_subtitle("B", 2.0, 3.0)
    mgr.create_subtitle("A", 1.0, 5.0)
    mgr.sort_subtitles("start_time")
    assert [s["text"] for s in mgr.subtitles] == ["A", "B"]
    mgr.sort_subtitles("end_time")
    assert [s["text"] for s in mgr.subtitles] == ["B", "A"]
    mgr.sort_subtitles("text")
    assert [s["text"] for s in mgr.subtitles] == ["A", "B"]


def test_style_crud_and_default_protection():
    """样式增删改查；default 样式不可删（返回 False）。"""
    mgr = SubtitleManager()
    st = mgr.create_subtitle_style("mine", font_size=40)
    assert st["name"] == "mine" and st["font_size"] == 40
    assert "mine" in mgr.subtitle_styles
    assert mgr.update_subtitle_style("mine", color="#123456") is True
    assert mgr.subtitle_styles["mine"]["color"] == "#123456"
    assert mgr.update_subtitle_style("ghost", color="#000") is False
    assert mgr.delete_subtitle_style("default") is False
    assert mgr.delete_subtitle_style("mine") is True
    assert mgr.delete_subtitle_style("mine") is False


def test_get_subtitle_style_falls_back_to_default():
    mgr = SubtitleManager()
    assert mgr.get_subtitle_style("does_not_exist") == mgr.subtitle_styles["default"]
    assert mgr.get_subtitle_style("title")["font_size"] == 32
    assert len(mgr.list_subtitle_styles()) == len(mgr.subtitle_styles)


def test_apply_style_to_subtitle_requires_existing_style_and_subtitle():
    mgr = SubtitleManager()
    mgr.create_subtitle("A", 0.0, 1.0)
    assert mgr.apply_style_to_subtitle("subtitle_1", "title") is True
    assert mgr.get_subtitle("subtitle_1")["style"] == "title"
    assert mgr.apply_style_to_subtitle("subtitle_1", "no_such_style") is False
    assert mgr.apply_style_to_subtitle("no_such_sub", "title") is False


def test_batch_create_subtitles_allows_missing_fields():
    """批量创建：缺失 text/时间时应原样填入 None（不抛异常）。"""
    mgr = SubtitleManager()
    created = mgr.batch_create_subtitles([
        {"text": "x", "start_time": 0.0, "end_time": 1.0},
        {"text": "y"},                     # 缺时间
        {"start_time": 2.0, "end_time": 3.0},  # 缺 text
    ])
    assert len(created) == 3
    assert created[1]["start_time"] is None
    assert created[2]["text"] is None


def test_add_subtitle_is_alias_of_create():
    mgr = SubtitleManager()
    s = mgr.add_subtitle("alias", 0.0, 1.0)
    assert s is mgr.subtitles[-1] and s["text"] == "alias"


def test_sec_to_srt_and_sec_to_ass_boundaries():
    """时间码格式化：零点、进位、以及 cs 四舍五入到 100 时的秒进位。"""
    mgr = SubtitleManager()
    assert mgr._sec_to_srt(0) == "00:00:00,000"
    assert mgr._sec_to_srt(3661.5) == "01:01:01,500"
    assert mgr._sec_to_ass(0) == "0:00:00.00"
    assert mgr._sec_to_ass(3661.5) == "1:01:01.50"
    # 1.999 → 厘秒 99.9 round→100 → 归零并进 1 秒
    assert mgr._sec_to_ass(1.999) == "0:00:02.00"
    # 负数被钳到 0
    assert mgr._sec_to_ass(-5) == "0:00:00.00"


def test_hex_to_ass_color_variants():
    """#RRGGBB / AARRGGBB / 命名色 / transparent / 短码 / 非法值 全覆盖。"""
    f = SubtitleManager._hex_to_ass_color
    assert f("#FFFFFF") == "&H00FFFFFF"
    assert f("#000000", 128) == "&H80000000"
    assert f("transparent") == "&H00000000"
    assert f("#FF0000") == "&H000000FF"
    assert f("红") == "&H000000FF"
    # AARRGGBB：CSS alpha 0x80=128(半透) → ASS alpha = 255-128 = 0x7F
    assert f("#80FF0000") == "&H7F0000FF"
    # 短码/非法 → 白色兜底
    assert f("FFF") == "&H00FFFFFF"
    assert f("ZZZZZZ") == "&H00FFFFFF"
    assert f(None) == "&H00FFFFFF"


def test_ass_escape_text_escapes_specials():
    t = SubtitleManager._ass_escape_text("a\nb{c}\\d")
    assert t == "a\\Nb\\{c\\}\\\\d"


def test_build_ass_anim_tag_positions_fades_and_transforms():
    """入场/出场动画标签：位置、淡入淡出、缩放、旋转、滑动。"""
    mgr = SubtitleManager()
    b = mgr._build_ass_anim_tag
    # 无动画：仅定位
    assert b("无", "无", 500, 100, 200, 2000) == "\\pos(100,200)"
    # 滑入左：move 从 (px-120,py) 到 (px,py)
    assert b("滑入左", "无", 500, 100, 200, 2000) == "\\move(-20,200,100,200,0,500)"
    # 淡出：fad(0,d)
    assert b("无", "淡出", 500, 100, 200, 2000) == "\\pos(100,200)\\fad(0,500)"
    # 缩放进入
    assert b("缩放进入", "无", 400, 100, 200, 2000) == (
        "\\pos(100,200)\\fscx20\\fscy20\\t(0,400,\\fscx100\\fscy100)")
    # 旋转进入
    assert b("旋转进入", "无", 400, 10, 20, 2000) == "\\pos(10,20)\\frz-30\\t(0,400,\\frz0)"
    # 滑出右：move 从 (px,py) 到 (px+120,py)，起点时间 = total-d
    assert b("无", "滑出右", 500, 100, 200, 2000) == "\\move(100,200,220,200,1500,2000)"
    # 淡入 + 缩放退出 复合
    assert b("淡入", "缩放退出", 500, 100, 200, 2000) == (
        "\\pos(100,200)\\fad(500,0)\\t(1500,2000,\\fscx20\\fscy20)")


def test_parse_srt_parses_blocks_and_times():
    """SRT 解析：时间码 逗号/点 均可，文本保留换行。"""
    mgr = SubtitleManager()
    content = ("1\n00:00:01,000 --> 00:00:02,500\nHello\n\n"
               "2\n00:00:03.250 --> 00:00:04,000\nLine1\nLine2\n")
    subs = mgr._parse_srt(content)
    assert len(subs) == 2
    assert subs[0]["start_time"] == 1.0 and subs[0]["end_time"] == 2.5
    assert subs[0]["text"] == "Hello"
    assert subs[1]["start_time"] == 3.25
    assert subs[1]["text"] == "Line1\nLine2"
    # _parse_srt 通过 create_subtitle 落库
    assert len(mgr.subtitles) == 2


def test_parse_srt_skips_malformed_blocks():
    """缺时间码/单行块应被跳过，不抛异常。"""
    mgr = SubtitleManager()
    subs = mgr._parse_srt("garbage\n\n1\nnot a timecode\nX\n")
    assert subs == []


def test_parse_vtt_strips_header_with_indexed_cue():
    """VTT：去掉 WEBVTT 头后按 SRT 逻辑解析（需带 cue 序号）。"""
    mgr = SubtitleManager()
    content = "WEBVTT\n\n1\n00:00:01.000 --> 00:00:02.000\nHi\n"
    subs = mgr._parse_vtt(content)
    assert len(subs) == 1 and subs[0]["text"] == "Hi"
    assert subs[0]["start_time"] == 1.0


def test_import_subtitles_missing_file_returns_empty(tmp_path):
    mgr = SubtitleManager()
    assert mgr.import_subtitles(str(tmp_path / "nope.srt")) == []
    assert mgr.subtitles == []


def test_import_subtitles_does_not_double_append(tmp_path):
    """回归锁（2026-10-09 修）：import_subtitles 曾把每条字幕插入两次。

    根因：_parse_srt 内部调用 create_subtitle 已 append 到 self.subtitles，
    返回后 import_subtitles 又遍历 imported 再 append 一遍。
    现象：导入 1 条 → self.subtitles 出现 2 条（时间线叠两层重合字幕）。
    修法：删掉那次重复 append。
    """
    p = tmp_path / "one.srt"
    p.write_text("1\n00:00:01,000 --> 00:00:02,000\n你好\n", encoding="utf-8")
    mgr = SubtitleManager()
    imported = mgr.import_subtitles(str(p), format="srt")
    assert len(imported) == 1
    assert len(mgr.subtitles) == 1, f"应只插入 1 条，实际 {len(mgr.subtitles)} 条"


def test_import_subtitles_multi_entry_counts_match(tmp_path):
    """多条也要对得上：N 条进 → N 条在库。"""
    p = tmp_path / "three.srt"
    p.write_text(
        "1\n00:00:01,000 --> 00:00:02,000\n甲\n\n"
        "2\n00:00:03,000 --> 00:00:04,000\n乙\n\n"
        "3\n00:00:05,000 --> 00:00:06,000\n丙\n",
        encoding="utf-8")
    mgr = SubtitleManager()
    imported = mgr.import_subtitles(str(p), format="srt")
    assert len(imported) == 3
    assert len(mgr.subtitles) == 3
    assert [s["text"] for s in mgr.subtitles] == ["甲", "乙", "丙"]


def test_export_srt_excludes_invisible_and_sorts(tmp_path):
    mgr = SubtitleManager()
    mgr.create_subtitle("later", 5.0, 6.0)
    mgr.create_subtitle("earlier", 1.0, 2.0)
    mgr.create_subtitle("hidden", 3.0, 4.0)
    mgr.toggle_subtitle_visibility("subtitle_3", visible=False)
    out = tmp_path / "out.srt"
    assert mgr.export_subtitles(str(out)) is True
    txt = out.read_text(encoding="utf-8")
    assert "earlier" in txt and "later" in txt and "hidden" not in txt
    # 排序：earlier 在 later 之前
    assert txt.index("earlier") < txt.index("later")
    assert "00:00:01,000 --> 00:00:02,000" in txt


def test_export_subtitles_ass_structure_and_sanitized_style(tmp_path):
    """ASS 导出：含样式表/事件区；非字母数字样式名被替换为下划线。"""
    mgr = SubtitleManager()
    mgr.create_subtitle("HI", 1.0, 2.0)
    mgr.subtitles[0]["style"] = "my style!"  # 直接改 dict 以测试 safe_name 清洗
    out = tmp_path / "o.ass"
    assert mgr.export_subtitles_ass(str(out), play_res=(1280, 720)) is True
    txt = out.read_text(encoding="utf-8-sig")
    assert "[Script Info]" in txt and "PlayResX: 1280" in txt and "PlayResY: 720" in txt
    assert "[V4+ Styles]" in txt and "[Events]" in txt
    assert "Style: my_style_," in txt
    assert "Dialogue: 0," in txt and "\\an5" in txt and "HI" in txt


def test_export_subtitles_ass_skips_hidden_and_empty(tmp_path):
    mgr = SubtitleManager()
    mgr.create_subtitle("VISIBLE", 1.0, 2.0)
    mgr.create_subtitle("HIDDEN", 3.0, 4.0)
    mgr.create_subtitle("", 5.0, 6.0)  # 空文本应被跳过
    mgr.toggle_subtitle_visibility("subtitle_2", visible=False)
    out = tmp_path / "o2.ass"
    assert mgr.export_subtitles_ass(str(out)) is True
    txt = out.read_text(encoding="utf-8-sig")
    assert "VISIBLE" in txt
    assert "HIDDEN" not in txt
    # 只有 1 行 Dialogue
    assert txt.count("Dialogue:") == 1


def test_export_subtitles_dispatches_ass_by_format(tmp_path):
    mgr = SubtitleManager()
    mgr.create_subtitle("X", 0.0, 1.0)
    out = tmp_path / "d.ass"
    assert mgr.export_subtitles(str(out), format=".ASS") is True
    assert "[V4+ Styles]" in out.read_text(encoding="utf-8-sig")


def test_sync_adjust_position_visibility_state_machine():
    mgr = SubtitleManager()
    mgr.create_subtitle("A", 1.0, 2.0)
    assert mgr.sync_subtitles(0.5) is True
    assert mgr.get_subtitle("subtitle_1")["start_time"] == 1.5
    assert mgr.adjust_subtitle_duration("subtitle_1", 1.0) is True
    # sync 已把 end 1.0→2.5，再 +1.0 ⇒ 3.5
    assert mgr.get_subtitle("subtitle_1")["end_time"] == 3.5
    assert mgr.adjust_subtitle_duration("nope", 1.0) is False
    assert mgr.set_subtitle_position("subtitle_1", 0.3, 0.7) is True
    assert mgr.get_subtitle("subtitle_1")["position"] == {"x": 0.3, "y": 0.7}
    assert mgr.set_subtitle_position("nope", 0, 0) is False
    assert mgr.toggle_subtitle_visibility("subtitle_1") is True
    assert mgr.get_subtitle("subtitle_1")["visible"] is False
    assert mgr.toggle_subtitle_visibility("subtitle_1", visible=True) is True
    assert mgr.get_subtitle("subtitle_1")["visible"] is True
    assert mgr.toggle_subtitle_visibility("nope") is False


def test_duplicate_split_merge_subtitles():
    mgr = SubtitleManager()
    mgr.create_subtitle("A", 1.0, 2.0)
    dup = mgr.duplicate_subtitle("subtitle_1")
    assert dup["id"] == "subtitle_2" and dup["start_time"] == 2.0 and dup["end_time"] == 3.0
    assert mgr.duplicate_subtitle("nope") is None

    mgr2 = SubtitleManager()
    mgr2.create_subtitle("mid", 0.0, 10.0)
    parts = mgr2.split_subtitle("subtitle_1", 4.0)
    assert parts is not None and len(parts) == 2
    assert parts[0]["end_time"] == 4.0 and parts[1]["start_time"] == 4.0
    # 分割点不在区间内 → None
    assert mgr2.split_subtitle("subtitle_1", 99.0) is None
    assert mgr2.split_subtitle("nope", 4.0) is None

    mgr3 = SubtitleManager()
    mgr3.create_subtitle("first", 0.0, 1.0)
    mgr3.create_subtitle("second", 2.0, 5.0)
    # 传入乱序，验证内部按 start 排序并删除正确条目
    merged = mgr3.merge_subtitles("subtitle_2", "subtitle_1")
    assert merged["text"] == "first second"
    assert merged["end_time"] == 5.0
    assert len(mgr3.subtitles) == 1
    assert mgr3.merge_subtitles("a", "b") is None


def test_preview_subtitle_html_and_missing():
    mgr = SubtitleManager()
    mgr.create_subtitle("T", 0.0, 1.0)
    pv = mgr.preview_subtitle("subtitle_1")
    assert pv["subtitle"]["text"] == "T"
    assert pv["style"]["font"] == "Arial"
    assert "T" in pv["preview_html"] and "font-family:Arial" in pv["preview_html"]
    assert mgr.preview_subtitle("nope") is None


def test_render_to_frame_draws_only_active():
    """cv2 可用：活动字幕改变像素；无活动字幕原样返回。"""
    mgr = SubtitleManager()
    mgr.create_subtitle("HELLO", 1.0, 3.0)
    frame = np.zeros((120, 400, 3), dtype=np.uint8)
    inside = mgr.render_to_frame(frame, 2.0)
    outside = mgr.render_to_frame(frame, 5.0)
    assert inside.shape == frame.shape
    assert int(inside.sum()) > int(frame.sum()), "活动字幕应写入像素"
    assert np.array_equal(outside, frame), "无活动字幕应原样返回"
    assert np.array_equal(frame, np.zeros((120, 400, 3), dtype=np.uint8)), "输入帧不应被就地修改"


def test_compute_frame_bindings_maps_timeline_frames():
    """compute_frame_bindings 走 text_frame_map：timeline 帧范围可预测。"""
    mgr = SubtitleManager()
    mgr.create_subtitle("hello", 1.0, 2.0)
    clip = {"id": "c1", "start_time": 0.0, "in_point": 0.0, "out_point": 10.0, "speed": 1.0}
    bindings = mgr.compute_frame_bindings(clip, fps=30.0)
    assert len(bindings) == 1
    b = bindings[0]
    # floor(1.0*30)=30, ceil(2.0*30)=60（半开区间）
    assert b.timeline_frame_in == 30 and b.timeline_frame_out == 60
    assert b.source_frame_in == 30 and b.source_frame_out == 60
    assert b.clip_id == "c1"


# ══════════════════════════════════════════════════════════════════
# ═══ subtitle_generator ═══
# ══════════════════════════════════════════════════════════════════

def test_subtitle_segment_duration_and_to_dict():
    seg = SubtitleSegment(id="s1", start_time=1.0, end_time=2.5, text="x", confidence=0.9)
    assert seg.duration == 1.5
    d = seg.to_dict()
    assert d["style"] == "classic" and d["position"] == "bottom_center"
    assert d["end_time"] == 2.5 and d["speaker"] is None


def test_subtitle_style_config_to_dict_roundtrip_keys():
    cfg = SubtitleStyleConfig(font_size=30, alignment="left")
    d = cfg.to_dict()
    assert d["font_size"] == 30 and d["alignment"] == "left"
    assert set(d.keys()) == {
        "font_name", "font_size", "font_color", "background_color", "background_opacity",
        "border_color", "border_width", "shadow_color", "shadow_offset", "line_spacing", "alignment"}


def test_typo_corrector_is_noop_by_default():
    """默认无规则：不得擅自替换常用字（避免改坏对白）。"""
    tc = TypoCorrector()
    out = tc.correct_text("我在家")
    assert out.corrected_text == "我在家" and out.corrections == []


def test_typo_corrector_applies_rule_and_respects_confidence():
    tc = TypoCorrector()
    tc.add_correction("在见", "再见")
    # 置信度 > 0.7 才替换
    hi = tc.correct_text("在见", confidence=0.9)
    assert hi.corrected_text == "再见" and hi.corrections[0]["corrected"] == "再见"
    lo = tc.correct_text("在见", confidence=0.5)
    assert lo.corrected_text == "在见" and lo.corrections == []
    tc.remove_correction("在见")
    assert tc.correct_text("在见", 0.9).corrected_text == "在见"


def test_styler_apply_style_and_unknown_fallback():
    st = SubtitleStyler()
    segs = [SubtitleSegment(id="a", start_time=0, end_time=1, text="t", confidence=1.0)]
    out = st.apply_style(segs, SubtitleStyle.MODERN)
    assert out[0] is not segs[0]  # 生成新对象
    assert out[0].style is SubtitleStyle.MODERN
    # 未知样式（CUSTOM 未在默认表）→ 回退经典配置但保留请求的 style 标记
    out2 = st.apply_style(segs, SubtitleStyle.CUSTOM)
    assert out2[0].style is SubtitleStyle.CUSTOM
    assert st.get_style_config(SubtitleStyle.CUSTOM) is None


def test_styler_config_crud_and_available_styles():
    st = SubtitleStyler()
    available = st.get_available_styles()
    assert SubtitleStyle.CLASSIC in available and SubtitleStyle.PLAYFUL in available
    assert SubtitleStyle.CUSTOM not in available
    cfg = SubtitleStyleConfig(font_size=99)
    st.set_style_config(SubtitleStyle.CUSTOM, cfg)
    assert st.get_style_config(SubtitleStyle.CUSTOM) is cfg


def test_whisper_transcriber_offline_reports_and_returns_empty(monkeypatch):
    """未安装 Whisper 时：返回空并回调进度 100 与原因，不再产出假文案。"""
    import app.core.ai.whisper_asr as wa
    monkeypatch.setattr(wa, "is_available", lambda: False)
    calls = []
    segs = WhisperTranscriber().transcribe_audio("x.wav", progress_callback=lambda p, m: calls.append((p, m)))
    assert segs == []
    assert calls and calls[-1][0] == 100 and "未安装" in calls[-1][1]


def test_whisper_transcriber_parses_backend_segments(monkeypatch):
    """可用路径：解析后端原始段，跳过空文本，映射 avg_logprob→confidence。"""
    import app.core.ai.whisper_asr as wa
    monkeypatch.setattr(wa, "is_available", lambda: True)
    monkeypatch.setattr(wa, "get_backend", lambda: "fake")
    monkeypatch.setattr(wa, "transcribe", lambda *a, **k: [
        {"text": "  hi  ", "start": 0.0, "end": 1.0, "avg_logprob": -0.2},
        {"text": "   ", "start": 1.0, "end": 2.0},
    ])
    segs = WhisperTranscriber().transcribe_audio("x.wav")
    assert len(segs) == 1
    assert segs[0].id == "seg_0" and segs[0].text == "hi"
    assert segs[0].end_time == 1.0 and abs(segs[0].confidence + 0.2) < 1e-9


def test_simulate_transcription_is_disabled():
    calls = []
    out = WhisperTranscriber()._simulate_transcription("x.wav", lambda p, m: calls.append(p))
    assert out == [] and calls == [100]


def test_subtitle_generator_generate_pipeline_with_stubs():
    """端到端（打桩转写器）：纠错 + 样式应作用到返回片段。"""
    gen = SubtitleGenerator()
    gen._typo_corrector.add_correction("在见", "再见")
    gen._transcriber.transcribe_audio = lambda *a, **k: [
        SubtitleSegment(id="s0", start_time=0.0, end_time=1.0, text="在见", confidence=0.9)]
    steps = []
    out = gen.generate_subtitles("a.wav", correct_typos=True,
                                 apply_style=SubtitleStyle.MODERN,
                                 progress_callback=lambda p, m: steps.append(p))
    assert len(out) == 1
    assert out[0].text == "再见"
    assert out[0].style is SubtitleStyle.MODERN
    assert steps[-1] == 100
    assert gen.get_segments()[0].text == "再见"


def test_subtitle_generator_returns_empty_when_transcriber_empty():
    gen = SubtitleGenerator()
    gen._transcriber.transcribe_audio = lambda *a, **k: []
    assert gen.generate_subtitles("a.wav") == []


def test_subtitle_generator_get_segments_is_copy_and_clear():
    gen = SubtitleGenerator()
    gen._segments = [SubtitleSegment(id="s", start_time=0, end_time=1, text="t", confidence=1.0)]
    snapshot = gen.get_segments()
    snapshot.clear()
    assert len(gen.get_segments()) == 1, "get_segments 应返回副本"
    gen.clear_subtitles()
    assert gen.get_segments() == []


def test_export_all_formats_content():
    gen = SubtitleGenerator()
    segs = [SubtitleSegment(id="s", start_time=3661.5, end_time=3662.0, text="hi", confidence=1.0)]
    srt = gen.export_subtitles(segs, SubtitleFormat.SRT)
    assert srt.startswith("1\n01:01:01,500 --> 01:01:02,000\nhi\n")
    ass = gen.export_subtitles(segs, SubtitleFormat.ASS)
    assert "[V4+ Styles]" in ass
    # 注意：_format_ass_time 不补零（1:1:1.50），与 SubtitleManager._sec_to_ass 的 0:00:00.00 不一致（见报告）
    assert "Dialogue: 0,1:1:1.50,1:1:2.00,Default,,0,0,0,,hi" in ass
    vtt = gen.export_subtitles(segs, SubtitleFormat.VTT)
    assert vtt.startswith("WEBVTT\n\n01:01:01.500 --> 01:01:02.000\nhi\n")
    txt = gen.export_subtitles(segs, SubtitleFormat.TXT)
    assert txt == "[3661.50 - 3662.00]\nhi\n\n"


def test_export_subtitles_to_file_returns_path(tmp_path):
    gen = SubtitleGenerator()
    segs = [SubtitleSegment(id="s", start_time=0.0, end_time=1.0, text="x", confidence=1.0)]
    p = tmp_path / "out.srt"
    ret = gen.export_subtitles(segs, SubtitleFormat.SRT, file_path=str(p))
    assert ret == str(p) and p.read_text(encoding="utf-8").startswith("1\n")


def test_format_time_functions():
    gen = SubtitleGenerator()
    assert gen._format_srt_time(3661.5) == "01:01:01,500"
    # 注意：_format_ass_time 不补零（时/分/秒），产出 "1:1:1.50"
    assert gen._format_ass_time(3661.5) == "1:1:1.50"
    assert gen._format_vtt_time(1.5) == "00:00:01.500"
    assert gen._format_srt_time(0) == "00:00:00,000"


def test_get_statistics_empty_and_values():
    gen = SubtitleGenerator()
    assert gen.get_statistics() == {}
    gen._segments = [
        SubtitleSegment(id="a", start_time=0.0, end_time=1.0, text="x", confidence=0.5, language="zh"),
        SubtitleSegment(id="b", start_time=1.0, end_time=3.0, text="y", confidence=1.0,
                        language="en", speaker="S1"),
    ]
    st = gen.get_statistics()
    assert st["total_segments"] == 2
    assert st["total_duration"] == 3.0
    assert st["average_duration"] == 1.5
    assert abs(st["average_confidence"] - 0.75) < 1e-9
    assert set(st["languages"]) == {"zh", "en"}
    assert st["speakers"] == ["S1"]


# ══════════════════════════════════════════════════════════════════
# ═══ lut_loader ═══
# ══════════════════════════════════════════════════════════════════

def test_lut_loader_is_singleton():
    assert LUTLoader() is LUTLoader()


def test_builtin_presets_registered():
    ll = LUTLoader()
    keys = ll.list_presets()
    for k in ("cinema_warm", "vivid", "vintage", "bw", "teal_orange", "cyberpunk"):
        assert k in keys
    lut = ll.get_preset("cinema_warm")
    assert isinstance(lut, LUT3D) and lut.size == 17 and lut.data is not None


def test_get_preset_none_like_returns_none():
    ll = LUTLoader()
    for key in ("", "无", "none", "None"):
        assert ll.get_preset(key) is None


def test_lut3d_apply_intensity_zero_and_none_data():
    """强度 0 或 data 缺失时应原样返回输入（不改变像素）。"""
    arr = np.array([[[0.2, 0.4, 0.6]]], dtype=np.float32)
    ld = LUT3D(name="n", size=2, data=None)
    assert np.array_equal(ld.apply(arr, 1.0), arr)
    ident = _write_cube_to_mem_identity(size=2)
    assert np.array_equal(LUT3D(name="i", size=2, data=ident).apply(arr, 0.0), arr)


def _write_cube_to_mem_identity(size=2):
    data = np.zeros((size, size, size, 3), dtype=np.float32)
    scale = size - 1
    for r in range(size):
        for g in range(size):
            for b in range(size):
                data[r, g, b] = (r / scale, g / scale, b / scale)
    return data


def test_load_cube_identity_shape_dtype_range(tmp_path):
    """恒等 cube 正常加载：shape/dtype 正确，apply 输出落在 [0,1] 且形状不变。

    注意：恒等 LUT 的非原色输入**不会**原样返回（R/B 轴交换缺陷，见
    test_load_cube_DEFECT_rb_axis_swapped），故此处只断言形状与值域。
    """
    p = _write_cube(tmp_path / "id.cube", 2, lambda r, g, b: (r, g, b))
    ll = LUTLoader()
    lut = ll.load(p)
    assert lut is not None and lut.size == 2
    assert lut.data.shape == (2, 2, 2, 3) and lut.data.dtype == np.float32
    arr = np.array([[[0.0, 0.5, 1.0]]], dtype=np.float32)
    out = lut.apply(arr, 1.0)
    assert out.shape == arr.shape
    assert float(out.min()) >= 0.0 and float(out.max()) <= 1.0


def test_load_cube_TITLE_and_domain(tmp_path):
    p = tmp_path / "t.cube"
    p.write_text(
        'TITLE "My LUT"\nLUT_3D_SIZE 2\nDOMAIN_MIN 0 0 0\nDOMAIN_MAX 1 1 1\n'
        + "\n".join(["0 0 0", "1 0 0", "0 1 0", "1 1 0", "0 0 1", "1 0 1", "0 1 1", "1 1 1"]) + "\n",
        encoding="utf-8")
    lut = LUTLoader().load(str(p))
    assert lut is not None and lut.title == "My LUT"
    assert lut.domain_min == (0.0, 0.0, 0.0) and lut.domain_max == (1.0, 1.0, 1.0)
    assert lut.name == "t.cube"


def test_load_missing_and_unsupported_and_incomplete(tmp_path):
    ll = LUTLoader()
    assert ll.load(str(tmp_path / "nope.cube")) is None
    # 不支持的扩展名
    bad = tmp_path / "x.txt"
    bad.write_text("hi", encoding="utf-8")
    assert ll.load(str(bad)) is None
    # size 与值数量不匹配 → None
    p = tmp_path / "bad.cube"
    p.write_text("LUT_3D_SIZE 2\n0 0 0\n1 1 1\n", encoding="utf-8")
    assert LUTLoader().load(str(p)) is None


def test_load_3dl_parses_and_empty_none(tmp_path):
    ll = LUTLoader()
    p = tmp_path / "a.3dl"
    p.write_text("\n".join("0 0 0" for _ in range(27)) + "\n", encoding="utf-8")
    lut = ll.load(str(p))
    assert lut is not None and lut.size == 3 and lut.data.shape == (3, 3, 3, 3)
    empty = tmp_path / "e.3dl"
    empty.write_text("# only comments\n", encoding="utf-8")
    assert LUTLoader().load(str(empty)) is None


def test_register_and_get_preset_and_list(tmp_path):
    ll = LUTLoader()
    assert ll.register("", LUT3D("x", 2, None)) == ""
    assert ll.register("k1", None) == ""
    lut = LUT3D(name="mine", size=2, data=None)
    assert ll.register("userkey_zzz", lut) == "userkey_zzz"
    assert ll.get_preset("userkey_zzz") is lut
    assert "userkey_zzz" in ll.list_presets()


def test_clear_cache_keeps_user_lut(tmp_path):
    ll = LUTLoader()
    lut = LUT3D(name="keep", size=2, data=None)
    ll.register("keepme_zzz", lut)
    p = _write_cube(tmp_path / "c.cube", 2, lambda r, g, b: (r, g, b))
    ll.load(p)
    assert p in ll._cache
    ll.clear_cache()
    assert p not in ll._cache, "文件缓存应被清空"
    assert ll.get_preset("keepme_zzz") is lut, "用户注册 LUT 应保留"


def test_register_file_loads_and_names_by_file(tmp_path):
    ll = LUTLoader()
    assert ll.register_file(str(tmp_path / "missing.cube")) is None
    p = _write_cube(tmp_path / "named.cube", 2, lambda r, g, b: (r, g, b))
    lut = ll.register_file(p)
    assert lut is not None and lut.name == "named.cube"
    assert ll.get_preset(os.path.abspath(p)) is lut


def test_get_preset_by_file_path(tmp_path):
    ll = LUTLoader()
    p = _write_cube(tmp_path / "bypath.cube", 2, lambda r, g, b: (r, g, b))
    lut = ll.get_preset(p)  # 首次：走 os.path.isfile 分支
    assert lut is not None and lut.name == "bypath.cube"
    assert ll.get_preset(p) is lut  # 之后命中缓存


def test_load_cube_rb_axes_are_not_swapped(tmp_path):
    """回归锁（2026-10-09 修）：.cube 的 R/B 轴曾被交换。

    .cube 按规范「红变化最快」写入、_load_cube 直接 reshape 成 (size,size,size,3)
    得到的是 data[b,g,r]；而 LUT3D.apply 用 data[r0,g0,b0] 取值 ⇒ R/B 轴被交换，
    所有 .cube 外观的颜色都是错的（红蓝互换）且不报错。
    修法：reshape 后 transpose(2,1,0,3)。

    判别性用例：构造 out=(1-R, G, B) 的非对称 LUT。纯红 (1,0,0) 正确应得 (0,0,0)；
    若实现改回不转置，这里会得 (1,0,1) 而红。
    """
    p = _write_cube(tmp_path / "invR.cube", 2, lambda r, g, b: (1 - r, g, b))
    lut = LUTLoader().load(p)
    red = np.array([[[1.0, 0.0, 0.0]]], dtype=np.float32)
    out = lut.apply(red, 1.0).reshape(-1)
    assert np.allclose(out, [0.0, 0.0, 0.0]), f"R/B 轴仍被交换：{out}"


def test_load_cube_pure_green_and_blue_land_on_right_axes(tmp_path):
    """再补两个轴：把三原色都走一遍，任何单轴错位都会被抓到。"""
    p = _write_cube(tmp_path / "swap.cube", 2, lambda r, g, b: (b, g, r))
    lut = LUTLoader().load(p)
    red = lut.apply(np.array([[[1.0, 0.0, 0.0]]], dtype=np.float32), 1.0).reshape(-1)
    blue = lut.apply(np.array([[[0.0, 0.0, 1.0]]], dtype=np.float32), 1.0).reshape(-1)
    green = lut.apply(np.array([[[0.0, 1.0, 0.0]]], dtype=np.float32), 1.0).reshape(-1)
    assert np.allclose(red, [0.0, 0.0, 1.0]), "R→B 映射失败"
    assert np.allclose(blue, [1.0, 0.0, 0.0]), "B→R 映射失败"
    assert np.allclose(green, [0.0, 1.0, 0.0]), "G 轴不该被动"


# ══════════════════════════════════════════════════════════════════
# ═══ waveform_generator ═══
# ══════════════════════════════════════════════════════════════════

def test_waveform_generator_is_singleton():
    assert WaveformGenerator() is WaveformGenerator()


def test_generate_missing_file_returns_none(tmp_path):
    assert WaveformGenerator().generate(str(tmp_path / "nope.wav")) is None


def test_generate_wave_direct_precise(tmp_path):
    """wave 回退路径：peaks/min/max 长度 = num_samples，时长/采样率精确，非静音。"""
    path = _write_wav(tmp_path / "ramp.wav", _ramp())
    data = WaveformGenerator()._generate_wave(path, num_samples=64)
    assert isinstance(data, WaveformData)
    assert len(data.peaks) == 64
    assert len(data.min_peaks) == 64 and len(data.max_peaks) == 64
    assert data.sample_rate == 44100
    assert max(data.peaks) > 1e-6
    # 每个桶的 min/max 都在样本值域 [-1,1] 内（注意：单桶不跨零时 min 可为正、max 可为负，
    # 与 dataclass 注释「min_peaks∈[-1,0] / max_peaks∈[0,1]」不符，见报告）
    assert min(data.min_peaks) >= -1.0 - 1e-6 and max(data.min_peaks) <= 1.0 + 1e-6
    assert min(data.max_peaks) >= -1.0 - 1e-6 and max(data.max_peaks) <= 1.0 + 1e-6
    assert abs(data.duration - 2000 / 44100) < 1e-3


def test_generate_pipeline_returns_full_length(tmp_path):
    """端到端 generate()（自动选后端）：返回非 None 且长度为 num_samples 的非静音波形。"""
    path = _write_wav(tmp_path / "g.wav", _ramp())
    data = WaveformGenerator().generate(path, num_samples=64)
    assert isinstance(data, WaveformData)
    assert len(data.peaks) == 64 and max(data.peaks) > 1e-6
    assert data.sample_rate == 44100


def test_generate_hits_cache_for_same_params(tmp_path):
    gen = WaveformGenerator()
    gen.clear_cache()
    path = _write_wav(tmp_path / "c.wav", _ramp())
    a = gen.generate(path, 32)
    b = gen.generate(path, 32)
    assert a is not None and b is a, "相同 path+num_samples 应命中缓存同一对象"


def test_generate_wave_8bit_and_stereo(tmp_path):
    gen = WaveformGenerator()
    # 8-bit 单声道：字节即无符号 0..255
    p8 = _write_wav(tmp_path / "u8.wav", list(range(0, 256)), sampwidth=1)
    d8 = gen._generate_wave(p8, 16)
    assert len(d8.peaks) == 16 and max(d8.peaks) > 0
    # 16-bit 立体声：取单声道下采样后仍非静音
    ps = _write_wav(tmp_path / "st.wav", _ramp(1000), channels=2)
    ds = gen._generate_wave(ps, 16)
    assert len(ds.peaks) == 16 and max(ds.peaks) > 0


def test_generate_wave_unsupported_sample_width_raises(tmp_path):
    p = tmp_path / "w24.wav"
    with wave.open(str(p), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(3)
        wf.setframerate(44100)
        wf.writeframes(b"\x00" * 30)
    with pytest.raises(RuntimeError):
        WaveformGenerator()._generate_wave(str(p), 8)


def test_pcm_to_mono_variants():
    mono = WaveformGenerator._pcm_to_mono
    a1 = np.zeros(10, dtype=np.float32)
    assert mono(a1) is a1
    # (channels, samples) → 声道平均
    cfirst = np.array([[0.0, 1.0, 0.0], [2.0, 2.0, 2.0]], dtype=np.float32)
    assert np.allclose(mono(cfirst), [1.0, 1.5, 1.0])
    # (samples, channels) → 声道平均
    clast = np.ones((100, 2), dtype=np.float32)
    assert mono(clast).shape == (100,)
    # 3D → 展平
    assert mono(np.zeros((2, 3, 4), dtype=np.float32)).shape == (24,)
    # 非 ndarray → 原样返回
    assert mono([1, 2, 3]) == [1, 2, 3]


def test_generate_silent_helper():
    d = WaveformGenerator()._generate_silent(8, 2.0)
    assert d.peaks == [0.0] * 8 and d.min_peaks == [0.0] * 8 and d.max_peaks == [0.0] * 8
    assert d.duration == 2.0 and d.sample_rate == 44100


def test_find_ffmpeg_path_returns_str():
    assert isinstance(WaveformGenerator()._find_ffmpeg_path(), str)


def test_generate_async_invokes_callback(tmp_path):
    """异步 API：回调必须在超时内被调用（用 Event 同步，不靠 sleep）。"""
    gen = WaveformGenerator()
    ev = threading.Event()
    box = {}
    def cb(data):
        box["data"] = data
        ev.set()
    gen.generate_async(str(tmp_path / "missing.wav"), 16, cb)
    assert ev.wait(timeout=10), "回调未在超时内触发"
    assert box["data"] is None


def test_clear_cache_empties_cache(tmp_path):
    gen = WaveformGenerator()
    gen.clear_cache()
    path = _write_wav(tmp_path / "cc.wav", _ramp())
    gen.generate(path, 16)
    assert len(gen._cache) >= 1
    gen.clear_cache()
    assert gen._cache == {}
