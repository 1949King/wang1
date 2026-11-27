"""
高光预览管理器
================
负责高光识别结果的统一管理和时间轴可视化

核心功能：
1. 统一的高光片段数据模型
2. 复用现有 AutoClipIntegration / DramaUnderstandingEngine 的检测能力
3. 提供异步检测接口和信号通知
4. 管理AI插帧节点标记
"""

from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
from PySide6.QtCore import QObject, Signal, QThread
import logging
import threading
import time

logger = logging.getLogger("AI短剧编辑器.highlight_preview")


class HighlightType(Enum):
    """高光类型"""
    EMOTION = "emotion"
    ACTION = "action"
    DIALOG = "dialog"
    SCENE_CHANGE = "scene_change"
    COMPOSITE = "composite"
    AI_GENERATED = "ai_generated"


class InterpolationType(Enum):
    """插帧类型"""
    SMOOTH = "smooth"
    CONTEXT_FILL = "context_fill"
    MOTION_COMPENSATION = "motion_compensation"
    GENERATIVE = "generative"


@dataclass
class HighlightSegment:
    """高光片段数据模型"""
    id: str
    start_time: float
    end_time: float
    score: float
    highlight_type: HighlightType = HighlightType.COMPOSITE
    label: str = ""
    reasons: List[str] = field(default_factory=list)
    color: str = "#ffd700"

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration": self.duration,
            "score": self.score,
            "highlight_type": self.highlight_type.value,
            "label": self.label,
            "reasons": self.reasons,
            "color": self.color,
        }


@dataclass
class InterpolationMarker:
    """线性补帧节点标记（非神经网络）"""
    id: str
    time: float
    interpolation_type: InterpolationType = InterpolationType.SMOOTH
    confidence: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    color: str = "#00ff88"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "time": self.time,
            "interpolation_type": self.interpolation_type.value,
            "confidence": self.confidence,
            "metadata": self.metadata,
            "color": self.color,
        }


class HighlightDetectorThread(QThread):
    """高光检测线程"""
    
    # 2026-10-09 修：原信号声明误用 List[HighlightSegment] 泛型。
    # Signal 不接受 typing 泛型别名（_GenericAlias），会在类体执行期抛
    # TypeError 导致**整个模块 import 失败**（详见 _verify/check_qt_signal_types.py）。
    detection_progress = Signal(int, str)
    detection_completed = Signal(object)
    detection_failed = Signal(str)

    def __init__(self, video_path: str, target_duration: float = 60.0):
        super().__init__()
        self._video_path = video_path
        self._target_duration = target_duration
        self._running = True

    def run(self):
        highlights = []
        try:
            self.detection_progress.emit(10, "启动高光检测...")
            
            from app.integrations.autoclip import AutoClipIntegration
            ac = AutoClipIntegration()
            if ac.initialized:
                self.detection_progress.emit(30, "使用 AutoClip 检测...")
                raw_highlights = ac._detect_highlights(
                    self._video_path,
                    target_duration=self._target_duration,
                    highlight_ratio=0.3
                )
                if raw_highlights:
                    for i, seg in enumerate(raw_highlights):
                        progress = 30 + min(50, int((i + 1) / len(raw_highlights) * 50))
                        self.detection_progress.emit(progress, f"分析片段 {i + 1}/{len(raw_highlights)}")
                        
                        highlight_type = self._classify_highlight(seg)
                        highlights.append(HighlightSegment(
                            id=f"auto_{i}",
                            start_time=seg.get("start", 0),
                            end_time=seg.get("end", 0),
                            score=seg.get("score", 0.8),
                            highlight_type=highlight_type,
                            label=self._generate_label(highlight_type, i),
                            reasons=[seg.get("reason", "AutoClip检测")],
                            color=self._get_highlight_color(highlight_type),
                        ))
            else:
                self.detection_progress.emit(30, "回退到启发式检测...")
                highlights = self._fallback_detection(self._video_path, self._target_duration)

            self.detection_progress.emit(100, "检测完成")
            self.detection_completed.emit(highlights)
            
        except Exception as e:
            logger.error(f"高光检测失败: {e}", exc_info=True)
            self.detection_failed.emit(str(e))

    def _classify_highlight(self, seg: Dict) -> HighlightType:
        score_components = seg.get("scores", {})
        motion = score_components.get("motion", 0)
        audio = score_components.get("audio", 0)
        scene_change = score_components.get("scene_change", 0)
        
        if motion > 0.7:
            return HighlightType.ACTION
        elif audio > 0.7:
            return HighlightType.DIALOG
        elif scene_change > 0.5:
            return HighlightType.SCENE_CHANGE
        return HighlightType.COMPOSITE

    def _generate_label(self, highlight_type: HighlightType, index: int) -> str:
        labels = {
            HighlightType.ACTION: f"动作高光 {index + 1}",
            HighlightType.DIALOG: f"对话高光 {index + 1}",
            HighlightType.SCENE_CHANGE: f"转场 {index + 1}",
            HighlightType.EMOTION: f"情感高光 {index + 1}",
            HighlightType.COMPOSITE: f"高光片段 {index + 1}",
            HighlightType.AI_GENERATED: f"AI生成 {index + 1}",
        }
        return labels.get(highlight_type, f"高光 {index + 1}")

    def _get_highlight_color(self, highlight_type: HighlightType) -> str:
        colors = {
            HighlightType.ACTION: "#ff6b6b",
            HighlightType.DIALOG: "#4ecdc4",
            HighlightType.SCENE_CHANGE: "#a855f7",
            HighlightType.EMOTION: "#f97316",
            HighlightType.COMPOSITE: "#ffd700",
            HighlightType.AI_GENERATED: "#22c55e",
        }
        return colors.get(highlight_type, "#ffd700")

    def _fallback_detection(self, video_path: str, target_duration: float) -> List[HighlightSegment]:
        highlights = []
        try:
            if CV2_AVAILABLE:
                import cv2
                cap = cv2.VideoCapture(video_path, cv2.CAP_FFMPEG)
                if cap.isOpened():
                    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
                    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                    duration = total_frames / fps
                    
                    segments = max(3, min(10, int(duration / 15)))
                    segment_duration = duration / segments
                    
                    for i in range(segments):
                        start = i * segment_duration
                        end = min(start + segment_duration * 0.8, duration)
                        highlights.append(HighlightSegment(
                            id=f"fallback_{i}",
                            start_time=start,
                            end_time=end,
                            score=0.7 + (i % 3) * 0.05,
                            highlight_type=HighlightType.COMPOSITE,
                            label=f"高光片段 {i + 1}",
                            color="#ffd700",
                        ))
                    cap.release()
        except Exception as e:
            logger.warning(f"[HighlightPreview] 高光检测失败: {e}")
        
        if not highlights:
            highlights.append(HighlightSegment(
                id="default_1",
                start_time=0,
                end_time=min(target_duration, 30),
                score=0.8,
                highlight_type=HighlightType.COMPOSITE,
                label="高光片段",
                color="#ffd700",
            ))
        
        return highlights

    def stop(self):
        self._running = False


class HighlightPreviewManager(QObject):
    """高光预览管理器"""
    
    # 同 HighlightDetectorThread 的修复理由：typing 泛型不能进 Signal。
    highlights_updated = Signal(object)
    interpolation_markers_updated = Signal(object)
    detection_progress = Signal(int, str)

    def __init__(self):
        super().__init__()
        self._highlights: List[HighlightSegment] = []
        self._interpolation_markers: List[InterpolationMarker] = []
        self._current_video = ""
        self._detector_thread = None
        self._lock = threading.Lock()

    def detect_highlights(self, video_path: str, target_duration: float = 60.0):
        """异步检测视频高光"""
        if self._detector_thread and self._detector_thread.isRunning():
            self._detector_thread.stop()
            self._detector_thread.wait()

        self._current_video = video_path
        self._detector_thread = HighlightDetectorThread(video_path, target_duration)
        self._detector_thread.detection_progress.connect(self.detection_progress.emit)
        self._detector_thread.detection_completed.connect(self._on_detection_completed)
        self._detector_thread.detection_failed.connect(self._on_detection_failed)
        self._detector_thread.start()

    def _on_detection_completed(self, highlights: List[HighlightSegment]):
        with self._lock:
            self._highlights = highlights
        self.highlights_updated.emit(highlights)
        logger.info(f"高光检测完成: {len(highlights)} 个片段")

    def _on_detection_failed(self, error_msg: str):
        logger.error(f"高光检测失败: {error_msg}")

    def get_highlights(self) -> List[HighlightSegment]:
        """获取当前高光片段列表"""
        with self._lock:
            return [h for h in self._highlights]

    def clear_highlights(self):
        """清除所有高光标记"""
        with self._lock:
            self._highlights = []
        self.highlights_updated.emit([])

    def add_interpolation_marker(self, marker: InterpolationMarker):
        """添加线性补帧节点标记"""
        with self._lock:
            existing = [m for m in self._interpolation_markers if abs(m.time - marker.time) < 0.05]
            if not existing:
                self._interpolation_markers.append(marker)
                self._interpolation_markers.sort(key=lambda m: m.time)
                self.interpolation_markers_updated.emit(self._interpolation_markers.copy())

    def remove_interpolation_marker(self, marker_id: str):
        """移除AI插帧节点标记"""
        with self._lock:
            self._interpolation_markers = [
                m for m in self._interpolation_markers if m.id != marker_id
            ]
        self.interpolation_markers_updated.emit(self._interpolation_markers.copy())

    def get_interpolation_markers(self) -> List[InterpolationMarker]:
        """获取AI插帧节点标记列表"""
        with self._lock:
            return [m for m in self._interpolation_markers]

    def clear_interpolation_markers(self):
        """清除所有AI插帧节点标记"""
        with self._lock:
            self._interpolation_markers = []
        self.interpolation_markers_updated.emit([])

    def shutdown(self):
        """关闭管理器"""
        if self._detector_thread and self._detector_thread.isRunning():
            self._detector_thread.stop()
            self._detector_thread.wait()
        self.clear_highlights()
        self.clear_interpolation_markers()


try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False


highlight_preview_manager = HighlightPreviewManager()