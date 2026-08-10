# -*- coding: utf-8 -*-
"""冒烟：画布缩放把手命中与包围盒。"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)


def main():
    errors = []
    from app.modules.lego.editor_module import EditorModule

    class _HitHost:
        _clip_box_norm = staticmethod(EditorModule._clip_box_norm)

    inst = _HitHost()
    tf = {"x": 0.5, "y": 0.5, "scale": 0.4}
    left, top, right, bottom, cx, cy = EditorModule._clip_box_norm(tf)
    if abs(right - left - 0.4) > 1e-6:
        errors.append(f"box width bad: {left},{right}")
    if abs(cx - 0.5) > 0.05:
        errors.append(f"center x bad: {cx}")

    mode = EditorModule._hit_preview_transform_mode(inst, left, top, tf, alt=False)
    if mode != "scale":
        errors.append(f"corner should scale, got {mode}")
    mode = EditorModule._hit_preview_transform_mode(inst, 0.5, 0.5, tf, alt=True)
    if mode != "rotate":
        errors.append(f"alt should rotate, got {mode}")
    mode = EditorModule._hit_preview_transform_mode(inst, cx, cy, tf, alt=False)
    if mode != "move":
        errors.append(f"center should move, got {mode}")

    if errors:
        print("FAIL")
        for e in errors:
            print(" -", e)
        sys.exit(1)
    print("PASS canvas scale hit", {"box": (left, top, right, bottom)})
    sys.exit(0)


if __name__ == "__main__":
    main()
