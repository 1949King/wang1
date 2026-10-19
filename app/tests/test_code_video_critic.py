# -*- coding: utf-8 -*-
"""渲染质检纯函数测试（V4.45 · 2026-10-19）。"""
from app.core.code_video.video_critic import (
    build_report,
    choose_sample_ts,
    compare_dual_shuffle,
    flat_frame_check,
    text_safe_area_check,
)


def _manifest(frames):
    return {"frames": frames}


def _frame(t, sha, rects=None):
    return {"t": t, "sha256": sha, "text_rects": rects or []}


def test_choose_sample_ts():
    assert choose_sample_ts({"canvas": {"duration": 10.0}}, 5) == [1.0, 3.0, 5.0, 7.0, 9.0]
    assert choose_sample_ts({"canvas": {"duration": 0}}, 5) == []


def test_dual_shuffle_pass_ignores_order():
    a = _manifest([_frame(1.0, "x"), _frame(2.0, "y")])
    b = _manifest([_frame(2.0, "y"), _frame(1.0, "x")])
    assert compare_dual_shuffle(a, b)["status"] == "pass"


def test_dual_shuffle_mismatch_reports_t():
    a = _manifest([_frame(1.0, "x"), _frame(2.0, "y")])
    b = _manifest([_frame(1.0, "x"), _frame(2.0, "z")])
    check = compare_dual_shuffle(a, b)
    assert check["status"] == "fail"
    assert "2.0s" in check["detail"]


def test_dual_shuffle_missing_t():
    a = _manifest([_frame(1.0, "x")])
    b = _manifest([_frame(2.0, "x")])
    assert compare_dual_shuffle(a, b)["status"] == "fail"


def test_dual_shuffle_empty():
    assert compare_dual_shuffle(_manifest([]), _manifest([]))["status"] == "fail"


def test_text_safe_area_pass():
    rects = [{"x": 50, "y": 800, "width": 440, "height": 40, "text": "字幕"}]
    check = text_safe_area_check(_manifest([_frame(1.0, "x", rects)]), 540, 960)
    assert check["status"] == "pass"


def test_text_safe_area_fail():
    rects = [{"x": 0, "y": 0, "width": 540, "height": 60, "text": "越界"}]
    check = text_safe_area_check(_manifest([_frame(1.0, "x", rects)]), 540, 960)
    assert check["status"] == "fail"
    assert "越界" in check["detail"]


def test_text_safe_area_not_wired():
    check = text_safe_area_check(_manifest([_frame(1.0, "x")]), 540, 960)
    assert check["status"] == "not_wired"
    assert "data-sg-text" in check["detail"]


def test_text_safe_area_custom_margin():
    rects = [{"x": 20, "y": 20, "width": 100, "height": 20, "text": "x"}]
    ok = text_safe_area_check(_manifest([_frame(1.0, "x", rects)]), 540, 960,
                              [0.0, 0.0, 0.0, 0.0])
    bad = text_safe_area_check(_manifest([_frame(1.0, "x", rects)]), 540, 960)
    assert ok["status"] == "pass"
    assert bad["status"] == "fail"


def test_flat_frame_detects_solid_and_gradient(tmp_path):
    from PIL import Image

    solid = tmp_path / "solid.png"
    Image.new("RGB", (32, 32), (0, 0, 0)).save(solid)
    grad = tmp_path / "grad.png"
    img = Image.new("RGB", (32, 32))
    for x in range(32):
        for y in range(32):
            img.putpixel((x, y), (x * 8, y * 8, 128))
    img.save(grad)
    check = flat_frame_check([str(solid), str(grad)])
    assert check["status"] == "warning"
    assert "solid.png" in check["detail"]


def test_flat_frame_all_normal(tmp_path):
    from PIL import Image

    paths = []
    for i in range(2):
        p = tmp_path / f"n{i}.png"
        img = Image.new("RGB", (16, 16), (0, 0, 0))
        img.paste((255, 255, 255), (0, 0, 8, 16))  # 黑白各半 ⇒ 方差高
        img.save(p)
        paths.append(str(p))
    assert flat_frame_check(paths)["status"] == "pass"
    assert flat_frame_check([])["status"] == "not_wired"


def test_build_report():
    report, warnings = build_report([
        {"name": "a", "status": "pass", "detail": "ok"},
        {"name": "b", "status": "warning", "detail": "warn"},
        {"name": "c", "status": "not_wired", "detail": "skip"},
    ])
    assert report["ok"] is True
    assert len(warnings) == 2
    bad, _ = build_report([{"name": "a", "status": "fail", "detail": "bad"}])
    assert bad["ok"] is False
