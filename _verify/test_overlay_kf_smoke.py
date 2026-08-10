# -*- coding: utf-8 -*-
"""冒烟：叠轨 transform 关键帧走连续 overlay 表达式。"""
import os
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)


def main():
    errors = []
    from app.modules.lego.video_processor import overlay_timeline_videos

    src = os.path.join(os.path.dirname(__file__), "srcA.mp4")
    if not os.path.isfile(src):
        print("SKIP no srcA.mp4")
        sys.exit(0)

    try:
        from app.core.ffmpeg_utils import find_ffmpeg
        ff = find_ffmpeg() or "ffmpeg"
    except Exception:
        ff = "ffmpeg"

    base = os.path.join(os.path.dirname(__file__), "bake_zoompan_kf.mp4")
    if not os.path.isfile(base):
        base = src

    out = os.path.join(os.path.dirname(__file__), "overlay_kf_cont.mp4")
    overlays = [{
        "path": src,
        "start_time": 0.0,
        "in_point": 0.0,
        "out_point": 1.0,
        "duration": 1.0,
        "pip_x": 0.75,
        "pip_y": 0.8,
        "pip_scale": 0.35,
        "opacity": 1.0,
        "rotation": 0.0,
        "_sc_kfs": [(0.0, 0.25), (0.9, 0.45)],
        "_x_kfs": [(0.0, 0.7), (0.9, 0.85)],
        "_y_kfs": [(0.0, 0.75), (0.9, 0.85)],
        "_rot_kfs": [(0.0, 0.0), (0.9, 15.0)],
    }]
    ok = overlay_timeline_videos(base, overlays, out, ff, (640, 360))
    if not ok or not os.path.isfile(out) or os.path.getsize(out) < 1000:
        errors.append("continuous overlay_timeline_videos failed")
    else:
        print("overlay_kf_cont ok", os.path.getsize(out))

    # 静态路径仍可用
    out2 = os.path.join(os.path.dirname(__file__), "overlay_static.mp4")
    ok2 = overlay_timeline_videos(
        base,
        [{
            "path": src,
            "start_time": 0.0,
            "in_point": 0.0,
            "out_point": 0.8,
            "pip_x": 0.75,
            "pip_y": 0.8,
            "pip_scale": 0.3,
        }],
        out2,
        ff,
        (640, 360),
    )
    if not ok2:
        errors.append("static overlay regression")

    if errors:
        print("FAIL")
        for e in errors:
            print(" -", e)
        sys.exit(1)
    print("PASS overlay continuous kf")
    sys.exit(0)


if __name__ == "__main__":
    main()
