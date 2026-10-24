# -*- coding: utf-8 -*-
"""冒烟：editor_burn / build_edited_video 抽出后可导入。"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)


def main():
    from app.modules.lego import editor_export, editor_burn
    assert hasattr(editor_export, "build_edited_video")
    assert hasattr(editor_export, "finalize_multitrack_export")
    assert hasattr(editor_burn, "burn_subtitles_if_any")
    assert hasattr(editor_burn, "burn_stickers_if_any")
    # empty path no-op
    class H:
        _clips = []
        _active_stickers = []
        def _ensure_subtitle_manager(self):
            return None
        def _get_ffmpeg(self):
            return None
    assert editor_burn.burn_subtitles_if_any(H(), "") == ""
    assert editor_burn.burn_stickers_if_any(H(), "") == ""
    assert editor_export.build_edited_video(H(), "out.mp4") is False
    print("PASS editor split burn/build")
    sys.exit(0)


if __name__ == "__main__":
    main()
