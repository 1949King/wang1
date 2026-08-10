#!/usr/bin/env python3
"""验收：音频轨波形生成与 ClipWidget 判定。"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)

from app.core.waveform_generator import waveform_generator
from app.modules.lego.timeline_widget import TimelineWidget


def find_media():
    for root, dirs, files in os.walk("素材库"):
        dirs[:] = [d for d in dirs if d not in (".venv", "__pycache__")]
        for f in files:
            if f.lower().endswith((".mp4", ".mp3", ".wav", ".mov", ".mkv", ".m4a")):
                return os.path.join(root, f)
    for root, dirs, files in os.walk("."):
        if any(x in root for x in (".venv", "thirdparty", "__pycache__", ".git")):
            continue
        for f in files:
            if f.lower().endswith((".mp4", ".mp3", ".wav")):
                return os.path.join(root, f)
    return None


def main():
    path = find_media()
    print("media:", path)
    assert path, "no media file found"

    data = waveform_generator.generate(path, num_samples=64)
    print(
        "generate:",
        None
        if data is None
        else f"peaks={len(data.peaks)} max={max(data.peaks):.4f}",
    )
    assert data is not None, "waveform generate returned None"
    assert max(data.peaks) > 1e-6, "peaks are all near zero"

    none_data = waveform_generator.generate("__no_such_file__.mp4", num_samples=32)
    print("missing file ->", none_data)
    assert none_data is None

    tw = TimelineWidget()
    print("tracks:", [(i, t["type"]) for i, t in enumerate(tw._tracks)])
    assert tw.find_track_index_by_type("audio") == 1

    tw.add_track("视频轨2", "video")
    ai = tw.find_track_index_by_type("audio")
    print("audio track index after extra video:", ai)
    assert tw._tracks[ai]["type"] == "audio"

    audio_clip = {
        "id": "a1",
        "path": path,
        "name": os.path.basename(path) + " (音频)",
        "start_time": 0,
        "duration": 5.0,
        "in_point": 0,
        "out_point": 5.0,
        "type": "audio",
        "track": ai,
    }
    w = tw.add_clip(audio_clip, ai)
    assert w is not None
    assert w._is_audio_clip() is True
    print("is_audio_clip:", w._is_audio_clip())

    deadline = time.time() + 20
    while time.time() < deadline:
        app.processEvents()
        if w._waveform_peaks is not None or w._waveform_failed:
            break
        time.sleep(0.05)

    print("waveform_failed:", w._waveform_failed)
    print(
        "peaks ready:",
        None
        if w._waveform_peaks is None
        else f"n={len(w._waveform_peaks)} max={max(w._waveform_peaks) if w._waveform_peaks else 0:.4f}",
    )
    assert not w._waveform_failed, "waveform generation failed for media with audio"
    assert w._waveform_peaks and max(w._waveform_peaks) > 1e-6

    vi = tw.find_track_index_by_type("video")
    vc = {
        "id": "v1",
        "path": path,
        "name": "v",
        "start_time": 0,
        "duration": 5,
        "type": "video",
        "track": vi,
    }
    vw = tw.add_clip(vc, vi)
    assert vw._is_audio_clip() is False
    print("video is_audio_clip:", vw._is_audio_clip())

    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        import traceback

        traceback.print_exc()
        raise SystemExit(1)
