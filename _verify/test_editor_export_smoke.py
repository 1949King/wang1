# -*- coding: utf-8 -*-
"""冒烟：editor_export 抽出后接口可用。"""
import os
import sys
from types import SimpleNamespace

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)


class _Host:
    def __init__(self):
        self._clips = [
            {"id": "v1", "path": __file__, "track": 0, "type": "video", "start_time": 0},
            {
                "id": "a1", "path": "x.mp3", "track": 1, "type": "audio",
                "start_time": 0, "volume": 0.8,
            },
            {
                "id": "v2", "path": __file__, "track": 2, "type": "video",
                "start_time": 0, "transform": {"x": 0.7, "y": 0.8, "scale": 0.3},
                "keyframes": [
                    {"prop": "scale", "time_offset": 0.0, "value": 0.3},
                    {"prop": "scale", "time_offset": 1.0, "value": 0.5},
                ],
            },
        ]
        self._timeline_store = SimpleNamespace(snapshot=lambda: list(self._clips))
        self._timeline_widget = type("T", (), {"_tracks": [
            {"type": "video", "volume": 1.0},
            {"type": "audio", "volume": 1.0},
            {"type": "video", "volume": 1.0},
        ]})()
        self._master_volume = 1.0
        self._pip_x = self._pip_y = self._pip_size = None
        self.msgs = []

    def _preview_frame_size(self):
        return 640, 360

    def _track_volume_for_clip(self, clip):
        return 1.0

    def _is_linked_video_audio_clip(self, clip):
        return False

    def _notify_edit(self, msg):
        self.msgs.append(msg)


def main():
    from app.modules.lego.editor_export import (
        is_export_audio_clip,
        collect_export_overlay_clips,
        collect_export_audio_clips,
        prebake_overlay_clips_for_export,
    )
    h = _Host()
    assert is_export_audio_clip(h, h._clips[1])
    assert not is_export_audio_clip(h, h._clips[0])
    ov = collect_export_overlay_clips(h, base_track=0)
    assert len(ov) == 1 and ov[0].get("_sc_kfs"), ov
    prepared = prebake_overlay_clips_for_export(ov)
    assert prepared and "_sc_kfs" in prepared[0]
    assert "_prebake_transform" not in prepared[0]
    aud = collect_export_audio_clips(h)
    # path x.mp3 不存在 → 空
    assert aud == []
    print("PASS editor_export extract", {"ov": len(ov), "kf": len(prepared[0]["_sc_kfs"])})
    sys.exit(0)


if __name__ == "__main__":
    main()
