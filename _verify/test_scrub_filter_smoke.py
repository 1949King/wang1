# -*- coding: utf-8 -*-
"""冒烟：scrub + 滤镜预览降载路径（静态约定 + PreviewManager 单测）。"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "app"))


def _check_editor_src():
    errors = []
    path = os.path.join(ROOT, "app", "modules", "lego", "editor_module.py")
    src = open(path, encoding="utf-8").read()

    if "_scrub_preview_timer" not in src:
        errors.append("missing _scrub_preview_timer coalesce")
    if "_scrub_render_busy" not in src:
        errors.append("missing _scrub_render_busy drop")
    if "_scrub_busy_drops" not in src:
        errors.append("missing _scrub_busy_drops counter")
    if "for_scrub=True" not in src:
        errors.append("missing open_video for_scrub light path")
    if "_preview_scrubbing" not in src or "_overlay_subtitles_on_qimage" not in src:
        errors.append("missing scrub overlay skip path markers")
    # scrub 时应跳过叠层
    i = src.find("def _show_frame_gl")
    gl_body = src[i:i + 900]
    if "_preview_scrubbing" not in gl_body:
        errors.append("_show_frame_gl should skip overlays while scrubbing")
    if "_render_scrub_preview_at" not in src:
        errors.append("missing _render_scrub_preview_at")
    if "_sync_scrub_audio_position" not in src:
        errors.append("missing deferred scrub audio sync")
    chunk = src.split("_begin_preview_scrub")[1].split("def _end_preview_scrub")[0]
    if "getattr(pm, \"preview_quality\"" not in chunk and "getattr(pm, 'preview_quality'" not in chunk:
        errors.append("_begin_preview_scrub should read preview_quality")
    if "getattr(pm, \"_preview_quality\"" in chunk or "getattr(pm, '_preview_quality'" in chunk:
        errors.append("_begin_preview_scrub still uses wrong _preview_quality attr")
    if "pm._preview_quality" in chunk:
        errors.append("_begin_preview_scrub still uses pm._preview_quality")

    i = src.find("def _on_timeline_playhead_moved")
    body = src[i:i + 800]
    if "_timeline_playing" not in body or "return" not in body:
        errors.append("_on_timeline_playhead_moved missing playing early-return")
    if "_scrub_preview_pending" not in body:
        errors.append("_on_timeline_playhead_moved missing scrub coalesce pending")

    i = src.find("def _lighten_effects_for_playback")
    body = src[i:i + 500]
    if "_preview_scrubbing" not in body:
        errors.append("_lighten_effects_for_playback missing scrub fast path")

    # PreviewManager open_video signature
    pm_path = os.path.join(ROOT, "app", "core", "preview_manager.py")
    pm_src = open(pm_path, encoding="utf-8").read()
    if "for_scrub: bool = False" not in pm_src:
        errors.append("preview_manager.open_video missing for_scrub param")
    if "if preload:" not in pm_src:
        errors.append("preview_manager.open_video should gate _preload_frames")

    return errors


def _check_preview_manager():
    errors = []
    from core.preview_manager import PreviewManager
    import numpy as np

    pm = PreviewManager()
    frame = np.zeros((120, 160, 3), dtype=np.uint8)
    frame[:, :, 0] = 180
    frame[:, :, 1] = 90

    full = pm._apply_effects_sync(
        frame.copy(),
        {"filter": "暖色调", "filter_intensity": 0.8, "brightness": 10},
    )
    fast = pm._apply_effects_sync(
        frame.copy(),
        {
            "filter": "暖色调",
            "filter_intensity": 0.8,
            "brightness": 10,
            "_preview_fast": True,
        },
    )
    if np.array_equal(full, fast):
        errors.append("fast path should skip CPU named filter (outputs differ)")
    # fast 仍应应用 brightness
    if not np.any(fast[:, :, 0] > frame[0, 0, 0]):
        errors.append("fast path should still apply cheap color ops")

    return errors


def main():
    errors = _check_editor_src()
    try:
        errors.extend(_check_preview_manager())
    except Exception as e:
        errors.append(f"PreviewManager test failed: {e}")

    if errors:
        print("FAIL")
        for e in errors:
            print(" -", e)
        sys.exit(1)
    print("PASS scrub filter load reduction")
    sys.exit(0)


if __name__ == "__main__":
    main()
