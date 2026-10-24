# -*- coding: utf-8 -*-
"""冒烟：变换关键帧连续 bake（表达式而非仅分段阶跃）。"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)


def main():
    errors = []
    from app.modules.lego.video_processor import (
        _clamped_transform_expr,
        _piecewise_linear_expr,
        bake_clip_transform,
    )

    e = _clamped_transform_expr([(0.0, 0.5), (1.0, 1.2)], 1.0, 0.05, 4.0)
    if "if(lt(t" not in e.replace("\\", ""):
        # escaped form still contains if(lt(t
        if "if(lt(t" not in e and "if(lt(t\\" not in e:
            errors.append(f"expr missing piecewise: {e}")
    if "0.500000" not in e and "0.5" not in e:
        errors.append(f"expr missing start value: {e}")

    const = _clamped_transform_expr(None, 0.75, 0.0, 1.0)
    if abs(float(const) - 0.75) > 1e-6:
        errors.append(f"const expr bad: {const}")

    # 线性中点应接近 0.85
    mid = 0.5
    pts = [(0.0, 0.5), (1.0, 1.2)]
    # 用 python lerp 对照
    expect = 0.5 + (1.2 - 0.5) * mid
    from app.modules.lego.video_processor import _lerp_kf_value
    got = _lerp_kf_value(pts, mid)
    if abs(got - expect) > 1e-6:
        errors.append(f"lerp mid bad: {got}")

    src = os.path.join(os.path.dirname(__file__), "srcA.mp4")
    if os.path.isfile(src):
        try:
            from app.core.ffmpeg_utils import find_ffmpeg
            ff = find_ffmpeg() or "ffmpeg"
        except Exception:
            ff = "ffmpeg"
        out = os.path.join(os.path.dirname(__file__), "bake_zoompan_kf.mp4")
        ok = bake_clip_transform(
            src,
            out,
            scale=1.0,
            x=0.5,
            y=0.5,
            rotation=0.0,
            scale_keyframes=[(0.0, 0.5), (1.0, 1.2)],
            x_keyframes=[(0.0, 0.2), (1.0, 0.8)],
            y_keyframes=[(0.0, 0.3), (1.0, 0.7)],
            rotation_keyframes=[(0.0, -10.0), (1.0, 25.0)],
            frame_width=640,
            frame_height=360,
            ffmpeg_path=ff,
        )
        if not ok or not os.path.isfile(out) or os.path.getsize(out) < 1000:
            errors.append("continuous bake_clip_transform failed")
        else:
            print("bake_zoompan_kf ok", os.path.getsize(out))
    else:
        print("skip ffmpeg bake (no srcA.mp4)")

    # 表达式自身可被 piecewise 生成
    pe = _piecewise_linear_expr([(0.0, 0.5), (1.0, 1.2)], "t")
    if "1.200000" not in pe:
        errors.append(f"piecewise end missing: {pe}")

    if errors:
        print("FAIL")
        for err in errors:
            print(" -", err)
        sys.exit(1)
    print("PASS continuous transform expr")
    sys.exit(0)


if __name__ == "__main__":
    main()
