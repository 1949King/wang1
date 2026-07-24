"""全局状态管理器 - 单例模式，统一管理轨道数据和选中状态"""

from typing import Dict, Any, Optional, List
from PyQt6.QtCore import QObject, pyqtSignal


class TrackData:
    def __init__(self, track_id: str, name: str, track_type: str = "video"):
        self.track_id = track_id
        self.name = name
        self.type = track_type
        self.clips: List[ClipData] = []
        self.muted = False
        self.solo = False
        self.locked = False
        self.volume = 1.0


class ClipData:
    def __init__(self, clip_id: str, media_path: str, start_time: float = 0, duration: float = 10):
        self.clip_id = clip_id
        self.media_path = media_path
        self.start_time = start_time
        self.duration = duration
        self.in_point = 0
        self.out_point = duration
        self.effects: Dict[str, Any] = {}
        self.filters: List[str] = []
        self.waveform_data: List[float] = []
        self.thumbnail_data: bytes = b""


class AppState(QObject):
    track_added = pyqtSignal(str)
    track_removed = pyqtSignal(str)
    track_muted = pyqtSignal(str, bool)
    track_locked = pyqtSignal(str, bool)
    
    clip_added = pyqtSignal(str, str)
    clip_removed = pyqtSignal(str, str)
    clip_selected = pyqtSignal(str, str)
    clip_deselected = pyqtSignal(str, str)
    clip_updated = pyqtSignal(str, str)
    
    playhead_moved = pyqtSignal(float)
    playback_state_changed = pyqtSignal(bool)
    tool_state_changed = pyqtSignal(bool)

    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = AppState()
        return cls._instance

    def __init__(self):
        super().__init__()
        self._tracks: Dict[str, TrackData] = {}
        self._current_track_id: Optional[str] = None
        self._selected_clip: Optional[ClipData] = None
        self._selected_track_id: Optional[str] = None
        self._playhead_position = 0.0
        self._is_playing = False

    def add_track(self, track_id: str, name: str, track_type: str = "video") -> TrackData:
        track = TrackData(track_id, name, track_type)
        self._tracks[track_id] = track
        self.track_added.emit(track_id)
        return track

    def remove_track(self, track_id: str):
        if track_id in self._tracks:
            del self._tracks[track_id]
            self.track_removed.emit(track_id)

    def get_track(self, track_id: str) -> Optional[TrackData]:
        return self._tracks.get(track_id)

    def get_all_tracks(self) -> List[TrackData]:
        return list(self._tracks.values())

    def add_clip(self, track_id: str, clip_data: ClipData):
        track = self._tracks.get(track_id)
        if track:
            track.clips.append(clip_data)
            self.clip_added.emit(track_id, clip_data.clip_id)

    def remove_clip(self, track_id: str, clip_id: str):
        track = self._tracks.get(track_id)
        if track:
            track.clips = [c for c in track.clips if c.clip_id != clip_id]
            self.clip_removed.emit(track_id, clip_id)

    def get_clip(self, track_id: str, clip_id: str) -> Optional[ClipData]:
        track = self._tracks.get(track_id)
        if track:
            return next((c for c in track.clips if c.clip_id == clip_id), None)
        return None

    def select_clip(self, track_id: str, clip_id: str):
        self._selected_track_id = track_id
        self._selected_clip = self.get_clip(track_id, clip_id)
        self.clip_selected.emit(track_id, clip_id)
        self.tool_state_changed.emit(self._selected_clip is not None)

    def deselect_clip(self):
        if self._selected_clip and self._selected_track_id:
            old_track = self._selected_track_id
            old_clip = self._selected_clip.clip_id
            self._selected_clip = None
            self._selected_track_id = None
            self.clip_deselected.emit(old_track, old_clip)
            self.tool_state_changed.emit(False)

    def get_selected_clip(self) -> Optional[ClipData]:
        return self._selected_clip

    def set_playhead_position(self, position: float):
        self._playhead_position = position
        self.playhead_moved.emit(position)

    def get_playhead_position(self) -> float:
        return self._playhead_position

    def set_playback_state(self, playing: bool):
        self._is_playing = playing
        self.playback_state_changed.emit(playing)

    def is_playing(self) -> bool:
        return self._is_playing


def get_app_state() -> AppState:
    return AppState.get_instance()
