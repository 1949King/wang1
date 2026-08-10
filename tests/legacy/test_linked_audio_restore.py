#!/usr/bin/env python3
"""验收：导入仅含视频的旧工程时自动补联动音频。"""
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication, QMessageBox

app = QApplication(sys.argv)

# 避免弹窗打断
QMessageBox.information = staticmethod(lambda *a, **k: None)

from app.modules.lego.editor_module import EditorModule


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
            if f.lower().endswith(".mp4"):
                return os.path.join(root, f)
    return None


def main():
    path = find_media()
    assert path, "no media"
    # 模拟旧 autosave：只有视频、无 type、无联动音频
    payload = {
        "version": "1.1",
        "clips": [
            {
                "id": "clip_test_only_video",
                "name": os.path.basename(path),
                "path": path,
                "start_time": 0.0,
                "duration": 5.0,
                "in_point": 0,
                "out_point": 5.0,
                "track": 0,
                "effects": {},
                "transitions": [],
            }
        ],
        "timeline_zoom": 100,
        "subtitles": [],
        "master_volume": 1.0,
    }
    fd, tmp = tempfile.mkstemp(suffix=".timeline")
    os.close(fd)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f)

    em = EditorModule()
    # 跳过媒体预览依赖：import_project 末尾会试 open_video
    em.import_project(tmp)
    try:
        os.remove(tmp)
    except Exception:
        pass

    types = [str(c.get("type", "")).lower() for c in em._clips]
    audio_n = sum(1 for t in types if t == "audio")
    video_n = sum(1 for c in em._clips if str(c.get("type", "video")).lower() != "audio")
    print("clips:", len(em._clips), "video~", video_n, "audio", audio_n)
    assert audio_n >= 1, "should synthesize linked audio clip"
    aw = None
    for w in em._timeline_widget.all_clip_widgets():
        if w._is_audio_clip():
            aw = w
            break
    assert aw is not None, "audio ClipWidget missing"

    deadline = time.time() + 25
    while time.time() < deadline:
        app.processEvents()
        if aw._waveform_peaks is not None or aw._waveform_failed:
            break
        time.sleep(0.05)
    print(
        "waveform_failed:",
        aw._waveform_failed,
        "peaks:",
        None if aw._waveform_peaks is None else len(aw._waveform_peaks),
    )
    assert not aw._waveform_failed
    assert aw._waveform_peaks and max(aw._waveform_peaks) > 1e-6
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
