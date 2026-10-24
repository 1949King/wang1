"""
逐帧导航器 (FrameNavigator)
============================
对标 Shotcut/OpenShot 的逐帧精确导航。

特性:
- 步进控制: 上一帧/下一帧
- 跳转到关键帧/标记/片段头尾
- 支持自定义步长 (1, 2, 5, 10 帧)
- 时间码显示 (HH:MM:SS:FF)
- 信号槽驱动
"""
import logging
from typing import List, Optional
from dataclasses import dataclass

logger = logging.getLogger("AI短剧编辑器.frame_navigator")


def timecode_to_frames(timecode: str, fps: float) -> int:
    """时间码 (HH:MM:SS:FF) 转帧号"""
    parts = timecode.split(':')
    if len(parts) != 4:
        return 0
    h, m, s, f = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
    return int((h * 3600 + m * 60 + s) * fps + f)


def frames_to_timecode(frames: int, fps: float, drop_frame: bool = False) -> str:
    """帧号转时间码 (HH:MM:SS:FF)"""
    if fps <= 0:
        return "00:00:00:00"
    total_seconds = frames / fps
    h = int(total_seconds // 3600)
    m = int((total_seconds % 3600) // 60)
    s = int(total_seconds % 60)
    f = int(frames % int(fps))
    return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"


def seconds_to_timecode(seconds: float, fps: float) -> str:
    """秒数转时间码"""
    return frames_to_timecode(int(seconds * fps), fps)


def timecode_to_seconds(timecode: str, fps: float) -> float:
    """时间码转秒数"""
    return timecode_to_frames(timecode, fps) / fps if fps else 0


@dataclass
class NavigationTarget:
    """导航目标点"""
    time: float
    label: str
    target_type: str  # marker, keyframe, clip_start, clip_end
    metadata: dict = None


class FrameNavigator:
    """
    逐帧导航器 (单例)

    维护当前位置, 支持:
    - 步进
    - 跳转
    - 查找目标
    """

    _instance: Optional["FrameNavigator"] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init = False
        return cls._instance

    def __init__(self, fps: float = 30.0):
        if self._init:
            return
        self._init = True
        self._fps = fps
        self._current_time = 0.0
        self._duration = 0.0
        self._targets: List[NavigationTarget] = []

    def set_fps(self, fps: float):
        self._fps = max(1.0, fps)

    def set_duration(self, duration: float):
        self._duration = max(0, duration)

    def set_current_time(self, time: float):
        self._current_time = max(0, min(self._duration, time))

    def get_current_time(self) -> float:
        return self._current_time

    def get_current_frame(self) -> int:
        return int(self._current_time * self._fps)

    def get_current_timecode(self) -> str:
        return seconds_to_timecode(self._current_time, self._fps)

    # ---- 步进 ----

    def step_forward(self, frames: int = 1) -> float:
        """前进步进"""
        new_time = self._current_time + frames / self._fps
        self._current_time = min(self._duration, new_time)
        return self._current_time

    def step_backward(self, frames: int = 1) -> float:
        """后退步进"""
        new_time = self._current_time - frames / self._fps
        self._current_time = max(0, new_time)
        return self._current_time

    def step_seconds_forward(self, seconds: float = 1.0) -> float:
        return self.step_forward(int(seconds * self._fps))

    def step_seconds_backward(self, seconds: float = 1.0) -> float:
        return self.step_backward(int(seconds * self._fps))

    def goto_start(self) -> float:
        self._current_time = 0
        return 0

    def goto_end(self) -> float:
        self._current_time = self._duration
        return self._duration

    # ---- 目标点管理 ----

    def set_targets(self, targets: List[NavigationTarget]):
        """设置可导航的目标点 (markers, keyframes, clip boundaries)"""
        self._targets = sorted(targets, key=lambda t: t.time)

    def add_target(self, target: NavigationTarget):
        """添加目标点"""
        self._targets.append(target)
        self._targets.sort(key=lambda t: t.time)

    def clear_targets(self):
        self._targets.clear()

    def goto_next_target(self) -> Optional[NavigationTarget]:
        """跳到下一个目标点"""
        for t in self._targets:
            if t.time > self._current_time + 0.01:
                self._current_time = t.time
                return t
        return None

    def goto_prev_target(self) -> Optional[NavigationTarget]:
        """跳到上一个目标点"""
        prev = None
        for t in self._targets:
            if t.time < self._current_time - 0.01:
                prev = t
            else:
                break
        if prev:
            self._current_time = prev.time
        return prev

    # ---- 时间码转换 ----

    def time_to_frame(self, time: float) -> int:
        return int(time * self._fps)

    def frame_to_time(self, frame: int) -> float:
        return frame / self._fps if self._fps else 0

    def to_timecode(self, time: float) -> str:
        return seconds_to_timecode(time, self._fps)

    def from_timecode(self, timecode: str) -> float:
        return timecode_to_seconds(timecode, self._fps)


# 全局实例
frame_navigator = FrameNavigator()
