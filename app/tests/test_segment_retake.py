# -*- coding: utf-8 -*-
"""app/tests/test_segment_retake.py — 片段重拍回归（2026-10-06）。

★ 这个模块的诚实纪律
==================
① **接缝是真实的**：模块必须报告接缝位置与风险，**不许假装无缝**；
② **时长必须对齐**：新段与原段不一样长时，默认对齐到原时长（裁/补）并**如实说明**，
   否则整条片子的时间轴会悄悄错位；
③ **越界/非法输入必须拒绝**（不静默改用户的输入）。

真机端到端用**颜色证据**验证：原片红→绿→蓝，替换中段为黄 ⇒
输出必须是「红 / 黄 / 蓝」且总时长基本不变、音轨还在。
"""
import glob
import os
import subprocess

import numpy as np
import pytest

from app.core import segment_retake as sr

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─────────────────────── ① 规划（纯函数） ───────────────────────

def test_plan_rejects_bad_input():
    assert sr.plan_retake(0, 1, 2)["ok"] is False                       # 没时长
    assert sr.plan_retake(10, -1, 2)["ok"] is False                    # 负时间
    assert sr.plan_retake(10, 3, 3)["ok"] is False                     # 空区间
    assert sr.plan_retake(10, 3, 2)["ok"] is False                     # 倒置
    assert sr.plan_retake(10, 1, 30)["ok"] is False                    # 越界
    assert sr.plan_retake(10, 1, 1.05)["ok"] is False                  # 太短
    for bad in (sr.plan_retake(0, 1, 2), sr.plan_retake(10, 1, 30)):
        assert "reason" in bad, "失败必须说明原因（不许静默）"


def test_plan_keep_segments_math():
    p = sr.plan_retake(10.0, 2.0, 5.0)
    assert p["ok"] and p["length"] == pytest.approx(3.0)
    assert p["keep_before"] == pytest.approx(2.0)
    assert p["keep_after"] == pytest.approx(5.0)


def test_plan_snaps_to_nearest_cut():
    p = sr.plan_retake(10.0, 2.05, 4.95, cuts=[2.0, 5.0])
    assert p["ok"] and p["snapped"] is True
    assert p["start"] == pytest.approx(2.0)
    assert p["end"] == pytest.approx(5.0)
    assert p["seam_risk"] == "low", "边界落在切点上就该报低风险"


def test_plan_no_cuts_reports_medium_not_low():
    """没有切点信息 ⇒ 不许报 low（那是不知道，不是没风险）。"""
    p = sr.plan_retake(10.0, 3.0, 5.0)
    assert p["ok"] and p["seam_risk"] == "medium"
    assert "切点" in p["note"]


def test_plan_far_from_cut_reports_medium():
    p = sr.plan_retake(10.0, 3.0, 7.0, cuts=[0.5, 9.5])
    assert p["seam_risk"] == "medium"
    assert p["snapped"] is False


def test_nearest_cut():
    assert sr.nearest_cut(2.1, [2.0, 5.0])[0] == 2.0
    assert sr.nearest_cut(3.0, [])[0] is None
    assert sr.nearest_cut(3.0, [])[1] == float("inf")


# ─────────────────────── ② 真机端到端（颜色证据） ───────────────────────

FF = sr._ffmpeg()


def _mk_clip(path: str, color: str, dur: float, audio: bool = True):
    cmd = [FF, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
           "-i", f"color=c={color}:s=320x240:d={dur}:r=10"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={dur}"]
    cmd += ["-pix_fmt", "yuv420p"]
    if audio:
        cmd += ["-c:a", "aac", "-shortest"]
    cmd += [path]
    subprocess.run(cmd, check=True)


def _frame_bgr(video: str, t: float, tmp: str, tag: str):
    p = os.path.join(tmp, f"f_{tag}.jpg")
    subprocess.run([FF, "-y", "-hide_banner", "-loglevel", "error", "-ss", str(t),
                    "-i", video, "-frames:v", "1", p], check=True)
    buf = np.fromfile(p, dtype=np.uint8)
    im = cv2_imdecode(buf)
    return im.reshape(-1, 3).mean(axis=0)   # BGR


def cv2_imdecode(buf):
    import cv2
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


@pytest.mark.skipif(not FF, reason="本机无 ffmpeg")
def test_e2e_replace_middle_keeps_rest_and_audio(tmp_path):
    d = str(tmp_path)
    segs = []
    for i, c in enumerate(("red", "green", "blue")):
        p = os.path.join(d, f"o{i}.mp4")
        _mk_clip(p, c, 1.0)
        segs.append(p)
    lst = os.path.join(d, "list.txt")
    with open(lst, "w", encoding="utf-8") as fh:
        for p in segs:
            fh.write("file '%s'\n" % os.path.abspath(p).replace("\\", "/"))
    orig = os.path.join(d, "orig.mp4")
    subprocess.run([FF, "-y", "-hide_banner", "-loglevel", "error", "-f", "concat",
                    "-safe", "0", "-i", lst, "-c", "copy", orig], check=True)
    rep = os.path.join(d, "rep.mp4")
    _mk_clip(rep, "yellow", 0.5)

    plan = sr.plan_retake(sr.probe_duration(orig), 1.0, 2.0, cuts=[1.0, 2.0])
    assert plan["ok"] and plan["seam_risk"] == "low"

    out = os.path.join(d, "out.mp4")
    res = sr.splice_retake(orig, rep, out, start=1.0, end=2.0, cuts=[1.0, 2.0])
    assert res.get("ok") is True, res.get("reason")
    # 新段比目标短 ⇒ 补到目标时长，且**如实报告**
    assert res["conformed"] == "padded"
    assert "补到" in res["note"]
    # 时间轴基本不变（原 3.0s）
    assert abs(res["out_duration"] - sr.probe_duration(orig)) < 0.25

    # ★ 颜色证据：红 / 黄 / 蓝
    b0, g0, r0 = _frame_bgr(out, 0.5, d, "before")
    b1, g1, r1 = _frame_bgr(out, 1.5, d, "middle")
    b2, g2, r2 = _frame_bgr(out, 2.5, d, "after")
    assert r0 > 180 and g0 < 80, f"0.5s 本该是红，实得 {b0:.0f}/{g0:.0f}/{r0:.0f}"
    assert r1 > 180 and g1 > 180 and b1 < 80, f"1.5s 本该是黄（新段），实得 {b1:.0f}/{g1:.0f}/{r1:.0f}"
    assert b2 > 180 and r2 < 80, f"2.5s 本该是蓝，实得 {b2:.0f}/{g2:.0f}/{r2:.0f}"

    # 音轨还在
    info = subprocess.run([FF, "-i", out], capture_output=True, text=True).stderr or ""
    assert "Audio:" in info

    # ★ 纪律回归：项目根不许出现临时文件
    assert glob.glob(os.path.join(ROOT, "_rb_*.jpg")) == []
    assert glob.glob(os.path.join(ROOT, "f_*.jpg")) == []


@pytest.mark.skipif(not FF, reason="本机无 ffmpeg")
def test_e2e_rejects_out_of_range_without_writing(tmp_path):
    d = str(tmp_path)
    orig = os.path.join(d, "o.mp4")
    _mk_clip(orig, "red", 1.0)
    rep = os.path.join(d, "r.mp4")
    _mk_clip(rep, "blue", 0.5)
    out = os.path.join(d, "out.mp4")
    res = sr.splice_retake(orig, rep, out, start=0.0, end=99.0)
    assert res.get("ok") is False
    assert not os.path.exists(out), "非法输入却写出了产物"


def test_missing_file():
    r = sr.splice_retake("nope.mp4", "nope2.mp4", "out.mp4", start=0, end=1)
    assert r["ok"] is False and "找不到文件" in r["reason"]
