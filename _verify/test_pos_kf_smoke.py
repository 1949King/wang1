# -*- coding: utf-8 -*-
"""冒烟：position/rotation 关键帧分段 + 主轨 bake。"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from app.modules.lego.video_processor import (
    _build_transform_segments,
    bake_clip_transform,
)


def main():
    errors = []
    segs = _build_transform_segments(
        2.0,
        scale=1.0, x=0.2, y=0.3, rotation=0.0,
        x_keyframes=[(0.0, 0.2), (1.5, 0.8)],
        y_keyframes=[(0.0, 0.3), (1.5, 0.7)],
        rotation_keyframes=[(0.0, 0.0), (1.5, 30.0)],
        scale_keyframes=[(0.0, 0.5), (1.5, 1.0)],
    )
    if len(segs) < 2:
        errors.append(f"too few segs: {segs}")
    xs = [s[3] for s in segs]
    if max(xs) - min(xs) < 0.2:
        errors.append(f"x not animated: {xs}")

    src = os.path.join(os.path.dirname(__file__), "srcA.mp4")
    if os.path.isfile(src):
        try:
            from app.core.ffmpeg_utils import find_ffmpeg
            ff = find_ffmpeg() or "ffmpeg"
        except Exception:
            ff = "ffmpeg"
        out = os.path.join(os.path.dirname(__file__), "bake_pos_kf.mp4")
        ok = bake_clip_transform(
            src, out,
            scale=1.0, x=0.5, y=0.5, rotation=0.0,
            x_keyframes=[(0.0, 0.2), (1.0, 0.8)],
            y_keyframes=[(0.0, 0.2), (1.0, 0.8)],
            rotation_keyframes=[(0.0, -10.0), (1.0, 20.0)],
            scale_keyframes=[(0.0, 0.6), (1.0, 1.0)],
            frame_width=640, frame_height=360,
            ffmpeg_path=ff,
        )
        if not ok or not os.path.isfile(out):
            errors.append("bake position/rotation keyframes failed")
        else:
            print("bake_pos_kf ok", os.path.getsize(out))

    if errors:
        print("FAIL")
        for e in errors:
            print(" -", e)
        sys.exit(1)
    print("PASS pos/rot kf segments", len(segs))
    sys.exit(0)


if __name__ == "__main__":
    main()
