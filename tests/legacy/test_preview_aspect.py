#!/usr/bin/env python3
"""验收：预览降采样保持片源宽高比（勿硬拉 16:9）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "app"))

from app.core.preview_manager import PreviewManager


def find_media():
    preferred = os.path.join(
        "assets", "videos", "d7b42fee1ea2e8792219d565bc70a58a_1784898729.mp4"
    )
    if os.path.isfile(preferred):
        return preferred
    for root, dirs, files in os.walk("."):
        if any(x in root for x in (".venv", "thirdparty", "__pycache__", ".git")):
            continue
        for f in files:
            if f.lower().endswith((".mp4", ".mov", ".mkv")):
                return os.path.join(root, f)
    return None


def main():
    path = find_media()
    assert path, "no media"
    pm = PreviewManager()
    assert pm.open_video(path)
    vw, vh = pm._video_width, pm._video_height
    native_ar = vw / vh
    print(f"native {vw}x{vh} ar={native_ar:.3f}")

    for q in ("low", "medium", "high"):
        pm.set_preview_quality(q)
        # 清缓存，避免命中上一质量帧
        with pm._lock:
            pm.preview_cache.clear()
            pm.raw_frame_cache.clear()
        img = pm.get_frame_at(0.4)
        assert img is not None, f"{q}: no frame"
        ar = img.width() / max(1, img.height())
        print(f"{q}: {img.width()}x{img.height()} ar={ar:.3f}")
        assert abs(ar - native_ar) < 0.05, (
            f"{q} aspect broken: got {ar:.3f}, want ~{native_ar:.3f}"
        )

    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
