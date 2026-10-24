# -*- coding: utf-8 -*-
"""冒烟：旋转/锚点/position KF / LUT atlas / clip_transform 拆分。"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from app.modules.lego.clip_transform import (
    normalize_clip_transform,
    apply_normalized_transform,
    resolve_anchor,
    composite_overlay_bgr,
    lut_to_2d_atlas,
)


def main():
    errors = []
    ax, ay = resolve_anchor("右下")
    if abs(ax - 1.0) > 1e-6 or abs(ay - 1.0) > 1e-6:
        errors.append(f"anchor 右下 bad: {ax},{ay}")

    c = {}
    apply_normalized_transform(
        c, x=0.2, y=0.8, scale=0.4, rotation=15, anchor="左上",
        frame_w=1920, frame_h=1080,
    )
    t = normalize_clip_transform(c, 1920, 1080)
    if abs(t["rotation"] - 15) > 1e-3 or t["anchor"] != "左上":
        errors.append(f"rot/anchor roundtrip bad: {t}")

    # 关键帧覆盖
    c2 = {"transform": {"x": 0.5, "y": 0.5, "scale": 1.0},
          "effects": {"_tf_x": 0.1, "_tf_y": 0.9, "_tf_rot": -30}}
    t2 = normalize_clip_transform(c2, 1920, 1080)
    if abs(t2["x"] - 0.1) > 1e-6 or abs(t2["rotation"] + 30) > 1e-3:
        errors.append(f"kf override bad: {t2}")

    import numpy as np
    base = np.zeros((100, 100, 3), dtype=np.float32)
    base[:] = 10
    ov = np.zeros((100, 100, 3), dtype=np.float32)
    ov[:] = 200
    out = composite_overlay_bgr(
        base, ov,
        {"x": 0.5, "y": 0.5, "scale": 0.5, "rotation": 20,
         "anchor_x": 0.5, "anchor_y": 0.5},
        1.0,
    )
    if out is None or out.shape != base.shape:
        errors.append("composite shape bad")
    if float(out.mean()) <= 10.1:
        errors.append("composite did not paint overlay")

    # LUT atlas
    s = 4
    data = np.random.rand(s, s, s, 3).astype(np.float32)
    atlas = lut_to_2d_atlas(data, s)
    if atlas.shape != (s, s * s, 3):
        errors.append(f"atlas shape bad: {atlas.shape}")

    # video_processor re-export
    from app.modules.lego.video_processor import normalize_clip_transform as n2
    if n2 is not normalize_clip_transform and n2({}, 100, 100)["scale"] <= 0:
        errors.append("reexport broken")

    if errors:
        print("FAIL")
        for e in errors:
            print(" -", e)
        sys.exit(1)
    print("PASS rot/anchor/kf/composite/lut_atlas")
    sys.exit(0)


if __name__ == "__main__":
    main()
