# -*- coding: utf-8 -*-
"""冒烟：归一化变换 + scale 关键帧分段。"""
import os
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from app.modules.lego.video_processor import (
    normalize_clip_transform,
    apply_normalized_transform,
    _build_scale_segments,
    bake_clip_transform,
)


def main():
    errors = []
    c = {}
    t = normalize_clip_transform(c, 1920, 1080, {"x": 0.75, "y": 0.8, "scale": 0.35})
    if abs(t["x"] - 0.75) > 1e-6 or abs(t["scale"] - 0.35) > 1e-6:
        errors.append(f"default transform bad: {t}")

    apply_normalized_transform(c, x=0.2, y=0.3, scale=0.5, frame_w=1920, frame_h=1080)
    t2 = normalize_clip_transform(c, 1920, 1080)
    if abs(t2["x"] - 0.2) > 1e-6 or abs(t2["scale"] - 0.5) > 1e-6:
        errors.append(f"roundtrip bad: {t2}")
    if "pip_x" not in c or abs(float(c["pip_x"]) - 0.2) > 1e-6:
        errors.append(f"pip sync bad: {c.get('pip_x')}")

    # 旧 position 像素兼容
    old = {"position": {"x": 0, "y": 0}}
    tp = normalize_clip_transform(old, 1920, 1080)
    if abs(tp["x"] - 0.5) > 1e-6:
        errors.append(f"position compat bad: {tp}")

    segs = _build_scale_segments([(0.0, 0.5), (1.0, 1.5)], 2.0)
    if len(segs) < 2:
        errors.append(f"scale segments too few: {segs}")
    scales = [s[2] for s in segs]
    if min(scales) >= 0.9 or max(scales) <= 0.9:
        errors.append(f"scale range not animated: {scales}")

    # 可选：真实 bake（需 ffmpeg + 源片）
    src = os.path.join(os.path.dirname(__file__), "srcA.mp4")
    if os.path.isfile(src):
        try:
            from app.core.ffmpeg_utils import find_ffmpeg
            ff = find_ffmpeg() or "ffmpeg"
        except Exception:
            ff = "ffmpeg"
        out = os.path.join(os.path.dirname(__file__), "bake_scale_kf.mp4")
        ok = bake_clip_transform(
            src,
            out,
            scale=1.0,
            scale_keyframes=[(0.0, 0.5), (1.0, 1.2)],
            frame_width=640,
            frame_height=360,
            ffmpeg_path=ff,
        )
        if not ok or not os.path.isfile(out):
            errors.append("bake_clip_transform scale_keyframes failed")
        else:
            print("bake_scale_kf ok", os.path.getsize(out))

    if errors:
        print("FAIL")
        for e in errors:
            print(" -", e)
        sys.exit(1)
    print("PASS", {"t2": t2, "nsegs": len(segs), "first_segs": segs[:3]})
    sys.exit(0)


if __name__ == "__main__":
    main()
