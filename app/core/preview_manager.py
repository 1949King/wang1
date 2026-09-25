from enum import Enum
from app.modules.utils.logger import logger
from typing import Optional, Dict, Any, Tuple, List, Callable
from pathlib import Path
from PyQt6.QtCore import QObject, pyqtSignal, QTimer, Qt, QThread, QSemaphore, QMutex
from PyQt6.QtGui import QImage, QPixmap
import threading
import time
from collections import OrderedDict
import gc
import os
import queue

import numpy as np
try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    logger.warning("cv2 未安装，将使用降级模式")


def _lazy_get_memory_pool():
    try:
        from core.memory_optimization import get_memory_pool, MemoryStrategy
        return get_memory_pool(max_size_mb=512, strategy=MemoryStrategy.LRU)
    except Exception:
        return None


class PreviewQuality(Enum):
    """预览质量等级"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    ULTRA = "ultra"


class RenderMode(Enum):
    """渲染模式"""
    SOFTWARE = "software"
    GPU_ACCELERATED = "gpu_accelerated"
    HYBRID = "hybrid"


class FrameReaderThread(QThread):
    """帧读取线程 - 使用 QElapsedTimer 精确帧调度，避免累积漂移"""
    frame_ready = pyqtSignal(np.ndarray, float)
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, video_path: str, fps: float = 30.0):
        super().__init__()
        self.video_path = video_path
        self.fps = fps
        self.is_playing = False
        self.seek_request = None
        self._seek_lock = threading.Lock()
        self._play_lock = threading.Lock()
        self.cap = None
        self.current_frame = 0
        self.total_frames = 0
        self._frame_queue = queue.Queue(maxsize=8)  # 增加队列大小
        self._running = True
        self._speed = 1.0  # 播放速度

    def set_speed(self, speed: float):
        """设置播放速度"""
        self._speed = max(0.1, min(10.0, speed))

    def run(self):
        """帧读取线程主循环 - 单时钟驱动，跳帧保实时"""
        if not CV2_AVAILABLE:
            self.error.emit("cv2 不可用")
            return

        try:
            self.cap = cv2.VideoCapture(self.video_path, cv2.CAP_FFMPEG)
            if not self.cap.isOpened():
                self.error.emit(f"无法打开视频: {self.video_path}")
                return

            self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
            
            # 使用 QElapsedTimer 精确计时（只在 play/seek 时 restart）
            from PyQt6.QtCore import QElapsedTimer
            timer = QElapsedTimer()
            timer_running = False
            
            while self._running:
                with self._play_lock:
                    if not self.is_playing:
                        time.sleep(0.01)
                        continue

                # 首次播放时启动计时器
                if not timer_running:
                    timer.restart()
                    timer_running = True

                # 处理 seek 请求
                with self._seek_lock:
                    if self.seek_request is not None:
                        self.cap.set(cv2.CAP_PROP_POS_FRAMES, self.seek_request)
                        self.current_frame = self.seek_request
                        self.seek_request = None
                        timer.restart()

                # 计算目标帧号（基于实际流逝时间，不重置计时器）
                elapsed_ms = timer.elapsed()
                target_frame = int(self.current_frame + (elapsed_ms / 1000.0) * self.fps * self._speed)

                # 跳帧策略：优先丢弃帧追赶，差距大时才seek
                frame_diff = target_frame - self.current_frame
                if frame_diff > 0:
                    # 差距超过5帧时使用seek（高开销，但能快速追赶）
                    if frame_diff > 5:
                        # 不再用 CAP_PROP_FRAME_COUNT 硬 clamp —— H.264/H.265 编码该值经常不准
                        # 直接 seek，read() 返回 False 时循环自然 break
                        self.cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
                        self.current_frame = target_frame
                        timer.restart()
                    # 差距较小（2-5帧）时，丢弃中间帧追赶（低开销）
                    elif frame_diff > 1:
                        for _ in range(frame_diff - 1):
                            if not self.cap.grab():
                                break
                            self.current_frame += 1

                ret, frame = self.cap.read()
                if not ret:
                    logger.warning(
                        "[FrameReaderThread] cap.read() 返回 False, "
                        f"current_frame={self.current_frame} total_frames={self.total_frames} "
                        f"CAP_PROP_POS_FRAMES={self.cap.get(cv2.CAP_PROP_POS_FRAMES) if self.cap else -1}"
                    )
                    break

                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                frame_time = self.current_frame / self.fps

                try:
                    self._frame_queue.put((frame.copy(), frame_time), timeout=0.1)
                except queue.Full:
                    logger.debug("忽略异常（原为 pass）: preview_manager.py", exc_info=True)

                self.frame_ready.emit(frame.copy(), frame_time)

                self.current_frame += 1

            self.finished.emit()
        except Exception as e:
            self.error.emit(f"读取帧失败: {str(e)}")
        finally:
            if self.cap:
                self.cap.release()

    def play(self):
        with self._play_lock:
            self.is_playing = True

    def pause(self):
        with self._play_lock:
            self.is_playing = False

    def seek_to(self, frame_idx: int):
        with self._seek_lock:
            self.seek_request = frame_idx
            self._frame_queue.queue.clear()

    def stop(self):
        self._running = False
        self.is_playing = False
        self.quit()
        self.wait()

    def get_frame_from_queue(self) -> Optional[Tuple[np.ndarray, float]]:
        try:
            return self._frame_queue.get_nowait()
        except queue.Empty:
            return None


class EffectsWorkerThread(QThread):
    effect_ready = pyqtSignal(np.ndarray, float)
    error = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._frame_queue = queue.Queue(maxsize=3)
        self._effects_queue = queue.Queue(maxsize=1)
        self._lock = threading.Lock()
        self._running = True
        self._current_effects = None

    def run(self):
        while self._running:
            try:
                frame, frame_time = self._frame_queue.get(timeout=0.05)
            except queue.Empty:
                time.sleep(0.005)
                continue

            effects = self._current_effects

            if effects:
                try:
                    result = self._apply_effects(frame, effects)
                    self.effect_ready.emit(result, frame_time)
                except Exception as e:
                    self.error.emit(f"应用特效失败: {str(e)}")
                    self.effect_ready.emit(frame, frame_time)
            else:
                self.effect_ready.emit(frame, frame_time)

    def apply_effects(self, frame: np.ndarray, effects: Dict, frame_time: float = 0.0):
        try:
            self._frame_queue.put((frame.copy(), frame_time), timeout=0.1)
        except queue.Full:
            logger.debug("忽略异常（原为 pass）: preview_manager.py", exc_info=True)

    def update_effects(self, effects: Dict):
        self._current_effects = effects

    def _apply_effects(self, frame: np.ndarray, effects: Dict) -> np.ndarray:
        try:
            result = frame.astype(np.float32)

            brightness = effects.get('brightness', 0)
            if brightness != 0:
                result = result + brightness

            contrast = effects.get('contrast', 1.0)
            if contrast != 1.0:
                mean = result.mean()
                result = (result - mean) * contrast + mean

            saturation = effects.get('saturation', 1.0)
            if saturation != 1.0 and result.shape[2] >= 3:
                gray = result[:, :, :3].mean(axis=2, keepdims=True)
                result[:, :, :3] = gray + (result[:, :, :3] - gray) * saturation

            exposure = effects.get('exposure', 0)
            if exposure != 0:
                result = result * (2.0 ** exposure)

            gamma = effects.get('gamma', 1.0)
            if gamma != 1.0:
                result = 255.0 * ((result / 255.0) ** (1.0 / gamma))

            highlights = effects.get('highlights', 0)
            if highlights != 0 and result.shape[2] >= 3:
                mask = result[:, :, :3] > 128
                result[:, :, :3][mask] = result[:, :, :3][mask] + highlights

            shadows = effects.get('shadows', 0)
            if shadows != 0 and result.shape[2] >= 3:
                mask = result[:, :, :3] <= 128
                result[:, :, :3][mask] = result[:, :, :3][mask] + shadows

            hue_shift = effects.get('hue', 0)
            if hue_shift != 0 and CV2_AVAILABLE and result.shape[2] >= 3:
                hsv = cv2.cvtColor(result.astype(np.uint8), cv2.COLOR_RGB2HSV)
                hsv[:, :, 0] = (hsv[:, :, 0].astype(np.float32) + float(hue_shift)) % 180
                result = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB).astype(np.float32)

            sharpen = effects.get('sharpen', 0)
            if sharpen != 0 and CV2_AVAILABLE:
                kernel = np.array([
                    [-1, -1, -1],
                    [-1, 9 + sharpen, -1],
                    [-1, -1, -1]
                ], dtype=np.float32) / (1.0 + abs(sharpen) * 0.1)
                for c in range(min(3, result.shape[2])):
                    result[:, :, c] = cv2.filter2D(
                        result[:, :, c].astype(np.uint8), -1, kernel)

            blur_radius = effects.get('blur', 0)
            if blur_radius > 0 and CV2_AVAILABLE:
                ksize = int(blur_radius) * 2 + 1
                result = cv2.GaussianBlur(result.astype(np.uint8),
                                           (ksize, ksize), 0).astype(np.float32)

            vignette = effects.get('vignette', 0)
            if vignette > 0 and CV2_AVAILABLE:
                h, w = result.shape[:2]
                yy, xx = np.ogrid[:h, :w]
                cx, cy = w / 2, h / 2
                dx = (xx - cx) / cx
                dy = (yy - cy) / cy
                dist = np.sqrt(dx * dx + dy * dy)
                mask = 1.0 - dist * vignette
                mask = np.clip(mask, 0.2, 1.0)
                result = result * mask[:, :, np.newaxis]

            result = np.clip(result, 0, 255).astype(np.uint8)

            opacity = effects.get("opacity", 1.0)
            try:
                opacity = float(opacity)
            except Exception:
                opacity = 1.0
            if 0.0 <= opacity < 0.999:
                result = (result.astype(np.float32) * opacity).astype(np.uint8)

            scale = effects.get("scale", 1.0)
            try:
                scale = float(scale)
            except Exception:
                scale = 1.0
            if CV2_AVAILABLE and abs(scale - 1.0) > 0.01 and scale > 0:
                h, w = result.shape[:2]
                nh, nw = max(1, int(h * scale)), max(1, int(w * scale))
                scaled = cv2.resize(result, (nw, nh))
                canvas = np.zeros_like(result)
                y0 = max(0, (h - nh) // 2)
                x0 = max(0, (w - nw) // 2)
                y1, x1 = min(h, y0 + nh), min(w, x0 + nw)
                sy1, sx1 = min(nh, y1 - y0), min(nw, x1 - x0)
                canvas[y0:y0 + sy1, x0:x0 + sx1] = scaled[:sy1, :sx1]
                result = canvas

            return result

        except Exception as e:
            logger.error(f"应用效果失败: {e}")
            return frame

    def stop(self):
        self._running = False
        self.quit()
        self.wait()


class FramePreloaderThread(QThread):
    """帧预加载线程 - 参考 Olive 实时预览引擎的增量渲染策略"""
    preload_complete = pyqtSignal(int)
    progress = pyqtSignal(int)

    def __init__(self, video_path: str, fps: float, cache_callback: Callable):
        super().__init__()
        self.video_path = video_path
        self.fps = fps
        self._cache_callback = cache_callback
        self._running = True
        self._target_range = None
        self._range_lock = threading.Lock()
        self._cap = None

    def run(self):
        if not CV2_AVAILABLE:
            return

        try:
            self._cap = cv2.VideoCapture(self.video_path, cv2.CAP_FFMPEG)
            if not self._cap.isOpened():
                return

            total_frames = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT))

            while self._running:
                target_range = None
                with self._range_lock:
                    if self._target_range is not None:
                        target_range = self._target_range
                        self._target_range = None

                if target_range is None:
                    time.sleep(0.05)
                    continue

                start_frame, end_frame = target_range
                start_frame = max(0, start_frame)
                end_frame = min(total_frames - 1, end_frame)

                if start_frame >= end_frame:
                    continue

                self._cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
                preloaded = 0

                for frame_idx in range(start_frame, end_frame + 1):
                    if not self._running:
                        break

                    ret, frame = self._cap.read()
                    if not ret:
                        break

                    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    self._cache_callback(frame_idx, frame)
                    preloaded += 1

                    if preloaded % 10 == 0:
                        self.progress.emit(int((preloaded / (end_frame - start_frame)) * 100))

                self.preload_complete.emit(preloaded)

        except Exception as e:
            logger.error(f"帧预加载失败: {e}")
        finally:
            if self._cap:
                self._cap.release()

    def set_preload_range(self, start_time: float, end_time: float):
        start_frame = int(start_time * self.fps)
        end_frame = int(end_time * self.fps) + 10
        with self._range_lock:
            self._target_range = (start_frame, end_frame)

    def stop(self):
        self._running = False
        self.quit()
        self.wait()


class PreviewManager(QObject):
    frame_ready = pyqtSignal(QImage)
    timecode_updated = pyqtSignal(str)
    preload_progress = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self.current_time = 0.0
        self.is_playing = False
        self.playing_speed = 1.0
        self.preview_window = None
        self.timecode_visible = True

        self.preview_cache = OrderedDict()
        self.raw_frame_cache = {}
        self.max_cache_size = 300
        self.max_raw_cache_size = 100
        self.proxy_preview_enabled = True
        self.preview_quality = 'high'
        self.render_mode = RenderMode.SOFTWARE
        self._lock = threading.RLock()

        self._memory_pool = _lazy_get_memory_pool()

        self._video_source: Optional[str] = None
        self._video_capture: Optional[Any] = None
        self._video_fps: float = 30.0
        self._video_duration: float = 0.0
        self._video_width: int = 1920
        self._video_height: int = 1080
        self._video_frame_count: int = 0

        self._playback_timer = QTimer()
        self._playback_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._playback_timer.timeout.connect(self._playback_tick)
        self._playback_interval_ms = 33

        self._cleanup_timer = QTimer()
        self._cleanup_timer.timeout.connect(self._cleanup_cache)
        self._cleanup_timer.start(30000)

        self._frame_reader_thread = None
        self._effects_worker_thread = None
        self._preloader_thread = None
        self._use_threaded_reading = False
        self._enable_preloading = False
        
        self._interpolation_enabled = False
        self._interpolation_mode = 'smart'
        self._interpolation_frame_queue = []
        self._interpolation_lock = threading.Lock()

    def open_video(self, video_path: str, *, preload: bool = True, for_scrub: bool = False) -> bool:
        """
        打开视频源。

        preload: 是否同步预载若干关键帧（跨片 scrub 应关）。
        for_scrub: 仅打开主 capture，不拉起预读/特效线程（拖 scrub 跨 clip 降载）。
        """
        with self._lock:
            self._close_video()
            path = Path(video_path)
            if not path.exists():
                logger.error(f"视频文件不存在: {video_path}")
                return False

            if not CV2_AVAILABLE:
                # 无 cv2 就无法真正解码任何帧；伪造 10s 占位会让上层误以为播放正常
                logger.error(
                    f"无法打开视频文件（缺少 opencv-python，预览/播放不可用）: {video_path}"
                )
                return False

            cap = cv2.VideoCapture(video_path, cv2.CAP_FFMPEG)
            if not cap.isOpened():
                logger.error(f"无法打开视频文件: {video_path}")
                return False
            self._video_capture = cap
            self._video_fps = cap.get(cv2.CAP_PROP_FPS)
            if self._video_fps <= 0:
                self._video_fps = 30.0
            self._video_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            self._video_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            self._video_frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            self._video_duration = self._video_frame_count / self._video_fps \
                if self._video_fps > 0 else 0.0

            self._video_source = video_path
            self.current_time = 0.0
            self._cap_next_idx = 0  # 顺序解码游标：主 capture 下一帧将读出的帧号
            self._playback_interval_ms = int(1000 / self._video_fps)

            # 校正 CAP_PROP_FRAME_COUNT —— H.264/H.265 编码该值常不准（会导致 7-8s 后黑屏）
            # scrub 跨片频繁 open：跳过探针，避免每次拖进度都多轮 seek
            if CV2_AVAILABLE and self._video_frame_count > 0 and not for_scrub:
                self._validate_and_fix_frame_count(cap)

            if not for_scrub and self._use_threaded_reading and CV2_AVAILABLE:
                self._start_frame_reader_thread()

            if preload and self._enable_preloading:
                self._preload_frames()
            # 预载会把 _cap_next_idx 拉到末尾；打开后复位，避免首帧/播放起点 seek 错乱
            self._cap_next_idx = 0
            try:
                if self._video_capture is not None and CV2_AVAILABLE:
                    self._video_capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
            except Exception:
                logger.debug("忽略异常（原为 pass）: preview_manager.py", exc_info=True)
            logger.info(f"视频已打开: {video_path} "
                        f"({self._video_width}x{self._video_height}, "
                        f"{self._video_fps:.1f}fps, "
                        f"{self._video_duration:.1f}s"
                        f"{', scrub轻量' if for_scrub else ''})")
            return True

    def _start_frame_reader_thread(self):
        if self._frame_reader_thread:
            self._frame_reader_thread.stop()

        self._frame_reader_thread = FrameReaderThread(self._video_source, self._video_fps)
        self._frame_reader_thread.frame_ready.connect(self._on_thread_frame_ready)
        self._frame_reader_thread.finished.connect(self._on_read_finished)
        self._frame_reader_thread.error.connect(self._on_read_error)
        self._frame_reader_thread.start()

        if self._effects_worker_thread:
            self._effects_worker_thread.stop()

        self._effects_worker_thread = EffectsWorkerThread()
        self._effects_worker_thread.effect_ready.connect(self._on_effects_ready)
        self._effects_worker_thread.error.connect(self._on_effects_error)
        self._effects_worker_thread.start()

        if self._enable_preloading and self._preloader_thread is None:
            self._preloader_thread = FramePreloaderThread(
                self._video_source, self._video_fps, self._cache_raw_frame
            )
            self._preloader_thread.preload_complete.connect(self._on_preload_complete)
            self._preloader_thread.progress.connect(self._on_preload_progress)
            self._preloader_thread.start()

    def _cache_raw_frame(self, frame_idx: int, frame: np.ndarray):
        """缓存原始帧数据（int 帧号做 key，min() 淘汰顺序才正确）"""
        with self._lock:
            self.raw_frame_cache[int(frame_idx)] = frame.copy()
            while len(self.raw_frame_cache) > self.max_raw_cache_size:
                oldest = min(self.raw_frame_cache.keys())
                del self.raw_frame_cache[oldest]

    def _on_preload_complete(self, count: int):
        logger.debug(f"帧预加载完成: {count} 帧")

    def _on_preload_progress(self, progress: int):
        self.preload_progress.emit(progress)

    def _on_thread_frame_ready(self, frame: np.ndarray, frame_time: float):
        if not self.is_playing:
            return

        self._cache_raw_frame(int(round(frame_time * self._video_fps)), frame)
        frame = self._resize_if_needed(frame)
        
        if self._interpolation_enabled:
            from app.core.ai_interpolation import ai_interpolation_engine
            ai_interpolation_engine.process_frame(frame, frame_time)
        
        current_effects = getattr(self, '_current_effects', None)

        if current_effects and self._effects_worker_thread:
            self._effects_worker_thread.apply_effects(frame, current_effects, frame_time)
        else:
            qimage = self._ndarray_to_qimage(frame)
            self.frame_ready.emit(qimage)
            self.current_time = frame_time
            tc = self.format_timecode(self.current_time)
            self.timecode_updated.emit(tc)

    def _on_effects_ready(self, frame: np.ndarray, frame_time: float):
        self._process_interpolated_frames(frame_time)
        qimage = self._ndarray_to_qimage(frame)
        self.frame_ready.emit(qimage)
        self.current_time = frame_time
        tc = self.format_timecode(self.current_time)
        self.timecode_updated.emit(tc)
    
    def _process_interpolated_frames(self, base_time: float):
        """处理线性补帧生成的帧"""
        from app.core.ai_interpolation import ai_interpolation_engine
        
        with self._interpolation_lock:
            markers = ai_interpolation_engine._interpolator._markers
            for marker in markers:
                if base_time - 0.05 < marker['time'] <= base_time:
                    inserted_frames = marker.get('frames', [])
                    for i, interp_frame in enumerate(inserted_frames):
                        interp_time = marker['time'] + (i + 1) * (base_time - marker['time']) / (len(inserted_frames) + 1)
                        qimage = self._ndarray_to_qimage(interp_frame)
                        self.frame_ready.emit(qimage)
                        tc = self.format_timecode(interp_time)
                        self.timecode_updated.emit(tc)

    def _on_read_finished(self):
        if self.is_playing:
            self.pause_preview()
            self.current_time = 0.0

    def _on_read_error(self, error_msg: str):
        logger.error(f"帧读取错误: {error_msg}")

    def _on_effects_error(self, error_msg: str):
        logger.error(f"特效处理错误: {error_msg}")

    def _close_video(self):
        if self._video_capture is not None and CV2_AVAILABLE:
            self._video_capture.release()

        if self._frame_reader_thread:
            self._frame_reader_thread.stop()
            self._frame_reader_thread = None

        if self._effects_worker_thread:
            self._effects_worker_thread.stop()
            self._effects_worker_thread = None

        if self._preloader_thread:
            self._preloader_thread.stop()
            self._preloader_thread = None

        self._video_capture = None
        self._video_source = None
        self.clear_preview_cache()

    def _validate_and_fix_frame_count(self, cap):
        """用二分探针验证 CAP_PROP_FRAME_COUNT 是否准确。

        H.264/H.265 容器的 CAP_PROP_FRAME_COUNT 经常不准（偏小/偏大），
        用二分 seek + read 确认真正的最后帧位置。probe 过程 <= 20 次 seek，几乎无感。
        """
        if not CV2_AVAILABLE or cap is None or not cap.isOpened():
            return
        nominal = int(self._video_frame_count or 0)
        if nominal <= 0:
            return
        lo, hi = 0, nominal - 1
        true_last = -1
        # 先用 POS_MSEC 粗探：直接 seek 到文件头 + 读取总时长再换算
        # 多数情况下 msec 方式最准
        try:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            dur_msec = cap.get(cv2.CAP_PROP_POS_MSEC)
            cap.set(cv2.CAP_PROP_POS_FRAMES, nominal - 1)
            end_msec = cap.get(cv2.CAP_PROP_POS_MSEC)
            if dur_msec > 0 and end_msec > dur_msec:
                # end_msec < dur_msec → nominal 偏大 → 二分
                pass
            if dur_msec > 0 and end_msec > dur_msec * 0.9:
                # ok, 接近预期
                return
        except Exception:
            logger.debug("忽略异常（原为 pass）: preview_manager.py", exc_info=True)

        # 二分找最后一个能 read 成功的帧
        for _ in range(20):  # 最多 20 次 seek
            if lo > hi:
                break
            mid = (lo + hi) // 2
            cap.set(cv2.CAP_PROP_POS_FRAMES, mid)
            cap.grab()
            ret, _ = cap.read()
            if ret:
                true_last = mid
                lo = mid + 1
            else:
                hi = mid - 1

        if 0 < true_last < nominal - 1:
            old = self._video_frame_count
            self._video_frame_count = true_last + 1
            if self._video_fps > 0:
                self._video_duration = self._video_frame_count / self._video_fps
            logger.info(
                f"[PreviewManager] 校正帧计数: CAP_PROP={old} → 实际={self._video_frame_count} "
                f"(duration={self._video_duration:.2f}s)"
            )
        elif true_last >= nominal - 1:
            logger.debug(
                f"[PreviewManager] CAP_PROP_FRAME_COUNT={nominal} 准确，无需校正"
            )
        # 恢复到帧 0，不污染后续逻辑
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    def _seek_to(self, time_sec: float):
        frame_idx = int(time_sec * self._video_fps)
        frame_idx = max(0, min(frame_idx, self._video_frame_count - 1))

        if self._frame_reader_thread:
            self._frame_reader_thread.seek_to(frame_idx)
        elif self._video_capture is not None and CV2_AVAILABLE:
            self._video_capture.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)

        self.current_time = time_sec

    def _read_frame(self) -> Optional[np.ndarray]:
        """读一帧 RGB。失败返回 None（勿返回占位图，否则 UI 会当成「成功首帧」）。"""
        if self._video_capture is not None and CV2_AVAILABLE:
            ret, frame = self._video_capture.read()
            if ret:
                return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            return None
        return None

    def _get_target_size(self) -> tuple:
        """按质量档位限制长边，始终保持片源宽高比（禁止硬拉 16:9）。"""
        vw = max(1, int(self._video_width or 1280))
        vh = max(1, int(self._video_height or 720))
        if self.preview_quality == 'low':
            long_edge = 640
        elif self.preview_quality == 'medium':
            long_edge = 960
        else:
            return vw, vh
        src_long = max(vw, vh)
        if src_long <= long_edge:
            return vw, vh
        scale = long_edge / float(src_long)
        tw = max(2, int(round(vw * scale)))
        th = max(2, int(round(vh * scale)))
        # 偶数边，兼容部分下游
        tw -= tw % 2
        th -= th % 2
        return max(2, tw), max(2, th)

    def _get_target_width(self) -> int:
        return self._get_target_size()[0]

    def _get_target_height(self) -> int:
        return self._get_target_size()[1]

    def _gen_placeholder(self, width: int, height: int) -> np.ndarray:
        """灰底占位（仅显式空工程 UI 用）。勿用中文：Hershey 会画成 ????。"""
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        frame[:, :] = [30, 30, 30]
        text = "No Signal"
        font_scale = max(0.8, min(width, height) / 500)
        thickness = max(1, int(min(width, height) / 400))
        if CV2_AVAILABLE:
            (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness)
            tx = (width - tw) // 2
            ty = (height + th) // 2
            cv2.putText(frame, text, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX,
                        font_scale, (150, 150, 150), thickness, cv2.LINE_AA)
        return frame

    def get_first_frame(self, effects: Optional[Dict] = None) -> Optional[QImage]:
        """可靠读取片源第 0 帧（导入/恢复工程用，避免 No Signal 假成功）。

        优先级：OpenCV 直接读 → 整文件重开再读 → FFmpeg CLI 回退（打包环境兜底）。
        """
        src = getattr(self, "_video_source", None)
        if not src:
            return None
        if effects is None:
            effects = getattr(self, "_current_effects", None)

        # —— 路径 1：OpenCV（含重开重试）——
        if CV2_AVAILABLE:
            cap = self._video_capture
            if cap is None or not cap.isOpened():
                if not self.open_video(src, preload=False):
                    cap = None
                else:
                    cap = self._video_capture
            if cap is not None and cap.isOpened():
                frame = None
                try:
                    # POS_FRAMES + POS_MSEC 双路径；部分 H.264 首帧 seek 需预热
                    for setter in (
                        lambda: cap.set(cv2.CAP_PROP_POS_FRAMES, 0),
                        lambda: cap.set(cv2.CAP_PROP_POS_MSEC, 0),
                    ):
                        try:
                            setter()
                        except Exception as e:
                            logger.debug("首帧 seek 预热 set 失败（继续下一路径）: %s", e)
                        cap.grab()
                        ret, bgr = cap.read()
                        if ret and bgr is not None:
                            frame = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                            break
                    if frame is None:
                        # 整文件重开再读
                        try:
                            cap.release()
                        except Exception as e:
                            logger.debug("旧 capture 释放失败（继续重开路径）: %s", e)
                        cap2 = cv2.VideoCapture(src, cv2.CAP_FFMPEG)
                        if cap2.isOpened():
                            self._video_capture = cap2
                            cap2.set(cv2.CAP_PROP_POS_FRAMES, 0)
                            ret, bgr = cap2.read()
                            if ret and bgr is not None:
                                frame = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                    if frame is not None:
                        self._cap_next_idx = 1
                        self._cache_raw_frame(0, frame)
                        frame = self._resize_if_needed(frame)
                        if effects:
                            frame = self._apply_effects_sync(frame, effects)
                        return self._ndarray_to_qimage(frame)
                except Exception as e:
                    logger.debug("get_first_frame OpenCV 路径失败: %s", e)

        # —— 路径 2：FFmpeg CLI 回退（打包环境下 OpenCV 解码异常时的兜底）——
        try:
            from app.core.ffmpeg_service import ffmpeg_service
            pixmap = ffmpeg_service.extract_frame(src, 0.0, width=0, height=720)
            if pixmap is not None and not pixmap.isNull():
                # QPixmap → QImage → ndarray → QImage（走统一的 resize/effects 管线）
                img = pixmap.toImage()
                if not img.isNull():
                    # 转成 ndarray 以便复用 resize/effects 管线
                    from PyQt6.QtGui import QImage as _QImage
                    img = img.convertToFormat(_QImage.Format.Format_RGB888)
                    w, h = img.width(), img.height()
                    ptr = img.bits()
                    ptr.setsize(h * w * 3)
                    frame_arr = np.frombuffer(ptr, dtype=np.uint8).reshape((h, w, 3)).copy()
                    self._cache_raw_frame(0, frame_arr)
                    frame_arr = self._resize_if_needed(frame_arr)
                    if effects:
                        frame_arr = self._apply_effects_sync(frame_arr, effects)
                    logger.info("get_first_frame 使用 FFmpeg CLI 回退成功: %dx%d", w, h)
                    return self._ndarray_to_qimage(frame_arr)
        except Exception as e:
            logger.debug("get_first_frame FFmpeg 回退失败: %s", e)

        return None

    def get_frame_at(self, time_sec: float, effects: Optional[Dict] = None) -> Optional[QImage]:
        if effects is None:
            effects = getattr(self, "_current_effects", None)
        # 首帧专用稳妥路径（导入/恢复最常见）
        if float(time_sec or 0) <= 1e-4:
            first = self.get_first_frame(effects)
            if first is not None:
                return first
        # capture 丢失但有源：自动重开
        if (self._video_capture is None or not (
            CV2_AVAILABLE and self._video_capture.isOpened()
        )) and getattr(self, "_video_source", None):
            try:
                self.open_video(self._video_source, preload=False)
            except Exception as e:
                logger.debug("get_frame_at 自动重开视频失败: %s", e)
        # 帧号量化：缓存按帧索引命中（浮点时间字符串 key 永远打不中预加载缓存）
        frame_idx = int(round(float(time_sec) * self._video_fps))
        if self._video_frame_count > 0:
            frame_idx = max(0, min(frame_idx, self._video_frame_count - 1))
        eff_sig = ""
        if effects:
            try:
                eff_sig = str(sorted((k, str(effects.get(k))) for k in effects.keys()))
            except Exception:
                eff_sig = str(id(effects))
        cache_key = f"frame:{frame_idx}:{hash(eff_sig)}"
        with self._lock:
            cached = self.preview_cache.get(cache_key)
            if cached is not None:
                return cached

            raw_frame = self.raw_frame_cache.get(frame_idx)
            if raw_frame is not None:
                frame = raw_frame.copy()
                frame = self._resize_if_needed(frame)
                if effects:
                    frame = self._apply_effects_sync(frame, effects)
                qimage = self._ndarray_to_qimage(frame)
                self.preview_cache[cache_key] = qimage
                while len(self.preview_cache) > self.max_cache_size:
                    self.preview_cache.popitem(last=False)
                return qimage

        # 顺序读取快进路：播放时优先 grab/read，避免每帧昂贵的 cv2 seek
        frame = None
        if (self._video_capture is not None and CV2_AVAILABLE):
            cap_next = int(getattr(self, "_cap_next_idx", -1))
            gap = frame_idx - cap_next
            if gap == 0:
                frame = self._read_frame()
            elif 0 < gap <= 48:
                # 落后几帧：grab 丢弃追赶（比 POS_FRAMES seek 便宜一个数量级）
                for _ in range(gap):
                    if not self._video_capture.grab():
                        break
                frame = self._read_frame()
            else:
                # 大跳 / 回退才 seek
                self._video_capture.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
                frame = self._read_frame()
                # seek 后 read 失败 —— 再重试一次（OpenCV seek 后常需一帧预热）
                if frame is None:
                    logger.warning(
                        f"[PreviewManager] seek 到 frame {frame_idx} 后 read 返回 None，重试一次"
                    )
                    self._video_capture.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
                    # 先 grab 一帧预热（某些 OpenCV 后端在 seek 后第一帧读不到）
                    self._video_capture.grab()
                    frame = self._read_frame()
            # 仅成功读帧才推进游标，避免失败后 gap 错乱导致后续连续 None
            if frame is not None:
                self._cap_next_idx = frame_idx + 1
        else:
            frame = self._read_frame()
            if frame is not None:
                self._cap_next_idx = frame_idx + 1

        if frame is None:
            # 与 QMediaPlayer 同开一文件时，OpenCV 偶发 read 失败：重开 capture 再试一次
            logger.warning(
                f"[PreviewManager] get_frame_at({time_sec:.3f}s) 返回 None, "
                f"frame_idx={frame_idx}, cap_next={getattr(self,'_cap_next_idx',None)}, "
                f"CAP_PROP_POS_FRAMES="
                f"{self._video_capture.get(cv2.CAP_PROP_POS_FRAMES) if self._video_capture else -1}"
            )
            src = getattr(self, "_video_source", None)
            if src and CV2_AVAILABLE:
                try:
                    if self._video_capture is not None:
                        self._video_capture.release()
                    cap = cv2.VideoCapture(src, cv2.CAP_FFMPEG)
                    if cap.isOpened():
                        self._video_capture = cap
                        if frame_idx <= 0:
                            return self.get_first_frame(effects)
                        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
                        cap.grab()
                        frame = self._read_frame()
                        if frame is not None:
                            self._cap_next_idx = frame_idx + 1
                except Exception as e:
                    logger.debug("get_frame_at 重开 capture 失败: %s", e)
            if frame is None:
                # OpenCV 全路径失败 → FFmpeg CLI 回退（打包环境兜底，seek 场景）
                src = getattr(self, "_video_source", None)
                if src:
                    try:
                        from app.core.ffmpeg_service import ffmpeg_service
                        target_h = max(240, int(self._get_target_height() or 480))
                        pixmap = ffmpeg_service.extract_frame(
                            src, float(time_sec), width=0, height=target_h
                        )
                        if pixmap is not None and not pixmap.isNull():
                            img = pixmap.toImage()
                            if not img.isNull():
                                from PyQt6.QtGui import QImage as _QImage
                                img = img.convertToFormat(_QImage.Format.Format_RGB888)
                                w, h = img.width(), img.height()
                                ptr = img.bits()
                                ptr.setsize(h * w * 3)
                                frame = np.frombuffer(
                                    ptr, dtype=np.uint8
                                ).reshape((h, w, 3)).copy()
                                logger.info(
                                    "get_frame_at 使用 FFmpeg CLI 回退成功: t=%.3fs %dx%d",
                                    time_sec, w, h
                                )
                    except Exception as e:
                        logger.debug("get_frame_at FFmpeg 回退失败: %s", e)
            if frame is None:
                return None

        self._cache_raw_frame(frame_idx, frame)
        frame = self._resize_if_needed(frame)
        if effects:
            frame = self._apply_effects_sync(frame, effects)

        qimage = self._ndarray_to_qimage(frame)
        with self._lock:
            self.preview_cache[cache_key] = qimage
            while len(self.preview_cache) > self.max_cache_size:
                self.preview_cache.popitem(last=False)
        return qimage

    def preload_range(self, start_time: float, end_time: float):
        """预加载指定时间范围内的帧（参考 Olive 增量渲染策略）"""
        if self._preloader_thread and self._enable_preloading:
            self._preloader_thread.set_preload_range(start_time, end_time)

    def _resize_if_needed(self, frame: np.ndarray) -> np.ndarray:
        tw, th = self._get_target_size()
        fh, fw = frame.shape[:2]
        if fw == tw and fh == th:
            return frame
        if CV2_AVAILABLE:
            return cv2.resize(frame, (tw, th), interpolation=cv2.INTER_AREA)
        scale = min(tw / max(1, fw), th / max(1, fh))
        new_w = max(1, int(fw * scale))
        new_h = max(1, int(fh * scale))
        return np.array(frame[::max(1, fh // new_h), ::max(1, fw // new_w)])

    def _ndarray_to_qimage(self, frame: np.ndarray) -> QImage:
        h, w = frame.shape[:2]
        if frame.ndim == 3 and frame.shape[2] == 3:
            return QImage(frame.data, w, h, w * 3, QImage.Format.Format_RGB888).copy()
        elif frame.ndim == 3 and frame.shape[2] == 4:
            return QImage(frame.data, w, h, w * 4, QImage.Format.Format_RGBA8888).copy()
        else:
            return QImage(frame.data, w, h, w, QImage.Format.Format_Grayscale8).copy()

    def _playback_tick(self):
        """计时器模式的播放回调 - 仅在没有 FrameReaderThread 时使用"""
        if not self.is_playing or self._video_duration <= 0:
            return

        # 仅在非线程模式下主动读帧
        if not self._use_threaded_reading or not self._frame_reader_thread:
            self.current_time += self._playback_interval_ms / 1000.0 * self.playing_speed

            if self.current_time >= self._video_duration:
                self.current_time = self._video_duration
                self.pause_preview()
                self.current_time = 0.0
                return

            with self._lock:
                frame = self._read_frame()
            if frame is None:
                return

            frame = self._resize_if_needed(frame)
            current_effects = getattr(self, '_current_effects', None)
            if current_effects:
                frame = self._apply_effects_sync(frame, current_effects)

            qimage = self._ndarray_to_qimage(frame)
            self.frame_ready.emit(qimage)

            tc = self.format_timecode(self.current_time)
            self.timecode_updated.emit(tc)

    def _apply_effects_sync(self, frame: np.ndarray, effects: Dict) -> np.ndarray:
        try:
            effects = self._normalize_effects(effects)
            preview_fast = bool(effects.get("_preview_fast"))
            result = frame.astype(np.float32)

            fname = effects.get("filter") or effects.get("filter_name")
            # scrub/播放 fast：CPU 跳过命名滤镜（Editor GL 路径负责；纯 CPU 路径以响应为先）
            if fname and not preview_fast:
                intens = float(effects.get("filter_intensity", 0.7) or 0.7)
                result = self._apply_named_filter(
                    np.clip(result, 0, 255).astype(np.uint8), str(fname), intens
                ).astype(np.float32)

            brightness = effects.get('brightness', 0)
            if brightness != 0:
                b = float(brightness)
                if abs(b) > 1.5:
                    b = b / 100.0 * 80.0
                else:
                    b = b * 80.0
                result = result + b

            contrast = effects.get('contrast', 1.0)
            if contrast != 1.0:
                mean = result.mean()
                result = (result - mean) * float(contrast) + mean

            saturation = effects.get('saturation', 1.0)
            if saturation != 1.0 and result.shape[2] >= 3:
                gray = result[:, :, :3].mean(axis=2, keepdims=True)
                result[:, :, :3] = gray + (result[:, :, :3] - gray) * float(saturation)

            cp = effects.get("color_params") if isinstance(effects.get("color_params"), dict) else {}

            if not preview_fast:
                exposure = effects.get('exposure', 0)
                if exposure != 0:
                    result = result * (2.0 ** exposure)

                gamma = effects.get('gamma', 1.0)
                if gamma != 1.0:
                    result = 255.0 * ((np.clip(result, 0, 255) / 255.0) ** (1.0 / float(gamma)))

                hue_shift = effects.get('hue', 0)
                if hue_shift != 0 and CV2_AVAILABLE and result.shape[2] >= 3:
                    hsv = cv2.cvtColor(np.clip(result, 0, 255).astype(np.uint8), cv2.COLOR_RGB2HSV)
                    shift = float(hue_shift)
                    if abs(shift) > 180:
                        shift = shift / 2.0
                    hsv[:, :, 0] = (hsv[:, :, 0].astype(np.float32) + shift / 2.0) % 180
                    result = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB).astype(np.float32)

                temperature = cp.get('temperature', 0) if cp else 0
                if temperature and result.shape[2] >= 3:
                    # 色温：正值偏暖（R↑B↓），负值偏冷（R↓B↑），R/B 通道假设为 RGB 序
                    shift = float(temperature) / 100.0 * 40.0
                    result[:, :, 0] = result[:, :, 0] + shift
                    result[:, :, 2] = result[:, :, 2] - shift

            # 预设 LUT（调色页接线）；拖动/播放可用半分辨率快速路径
            lut_name = effects.get("lut")
            lut_fast = bool(effects.get("lut_fast") or effects.get("_preview_fast"))
            if not lut_name and cp:
                lut_name = cp.get("lut")
                lut_fast = lut_fast or bool(cp.get("lut_fast"))
            if lut_name:
                try:
                    from app.core.lut_loader import lut_loader
                    lut = lut_loader.get_preset(str(lut_name))
                    if lut is not None and lut.data is not None:
                        intens = float(
                            effects.get("lut_intensity", cp.get("lut_intensity", 1.0)) or 1.0
                        )
                        rgb01 = np.clip(result[:, :, :3], 0, 255).astype(np.float32) / 255.0
                        if lut_fast and CV2_AVAILABLE:
                            h0, w0 = rgb01.shape[:2]
                            small = cv2.resize(rgb01, (max(1, w0 // 2), max(1, h0 // 2)))
                            out = lut.apply(small, intensity=intens)
                            out = cv2.resize(out, (w0, h0))
                        else:
                            out = lut.apply(rgb01, intensity=intens)
                        result[:, :, :3] = np.clip(out * 255.0, 0, 255)
                except Exception as e:
                    logger.debug(f"LUT 应用跳过: {e}")

            if effects.get("_preview_fast"):
                # 播放/拖 scrub：跳过后续锐化/模糊/暗角
                result = np.clip(result, 0, 255).astype(np.uint8)
                opacity = effects.get("opacity", 1.0)
                try:
                    opacity = float(opacity)
                except Exception:
                    opacity = 1.0
                if 0.0 <= opacity < 0.999:
                    result = (result.astype(np.float32) * opacity).astype(np.uint8)
                # 仍处理 scale（关键帧轻量）
                scale = effects.get("scale", 1.0)
                try:
                    scale = float(scale)
                except Exception:
                    scale = 1.0
                if CV2_AVAILABLE and abs(scale - 1.0) > 0.01 and scale > 0:
                    h, w = result.shape[:2]
                    nh, nw = max(1, int(h * scale)), max(1, int(w * scale))
                    scaled = cv2.resize(result, (nw, nh))
                    canvas = np.zeros_like(result)
                    y0 = max(0, (h - nh) // 2)
                    x0 = max(0, (w - nw) // 2)
                    y1, x1 = min(h, y0 + nh), min(w, x0 + nw)
                    canvas[y0:y0 + (y1 - y0), x0:x0 + (x1 - x0)] = scaled[: y1 - y0, : x1 - x0]
                    result = canvas
                return result

            sharpen = effects.get('sharpen', 0)
            if sharpen != 0 and CV2_AVAILABLE:
                kernel = np.array([
                    [-1, -1, -1],
                    [-1, 9 + sharpen, -1],
                    [-1, -1, -1]
                ], dtype=np.float32) / (1.0 + abs(float(sharpen)) * 0.1)
                for c in range(min(3, result.shape[2])):
                    result[:, :, c] = cv2.filter2D(
                        result[:, :, c].astype(np.uint8), -1, kernel)

            blur_radius = effects.get('blur', 0)
            if blur_radius > 0 and CV2_AVAILABLE:
                ksize = int(blur_radius) * 2 + 1
                result = cv2.GaussianBlur(np.clip(result, 0, 255).astype(np.uint8),
                                           (ksize, ksize), 0).astype(np.float32)

            vignette = effects.get('vignette', 0)
            if vignette > 0 and CV2_AVAILABLE:
                h, w = result.shape[:2]
                yy, xx = np.ogrid[:h, :w]
                cx, cy = w / 2, h / 2
                dx = (xx - cx) / cx
                dy = (yy - cy) / cy
                dist = np.sqrt(dx * dx + dy * dy)
                mask = 1.0 - dist * float(vignette)
                mask = np.clip(mask, 0.2, 1.0)
                result = result * mask[:, :, np.newaxis]

            result = np.clip(result, 0, 255).astype(np.uint8)

            opacity = effects.get("opacity", 1.0)
            try:
                opacity = float(opacity)
            except Exception:
                opacity = 1.0
            if 0.0 <= opacity < 0.999:
                result = (result.astype(np.float32) * opacity).astype(np.uint8)

            scale = effects.get("scale", 1.0)
            try:
                scale = float(scale)
            except Exception:
                scale = 1.0
            if CV2_AVAILABLE and abs(scale - 1.0) > 0.01 and scale > 0:
                h, w = result.shape[:2]
                nh, nw = max(1, int(h * scale)), max(1, int(w * scale))
                scaled = cv2.resize(np.clip(result, 0, 255).astype(np.uint8), (nw, nh))
                canvas = np.zeros((h, w, result.shape[2] if result.ndim == 3 else 1), dtype=np.uint8)
                if result.ndim == 2:
                    canvas = np.zeros((h, w), dtype=np.uint8)
                y0 = max(0, (h - nh) // 2)
                x0 = max(0, (w - nw) // 2)
                y1, x1 = min(h, y0 + nh), min(w, x0 + nw)
                sy1, sx1 = min(nh, y1 - y0), min(nw, x1 - x0)
                canvas[y0:y0 + sy1, x0:x0 + sx1] = scaled[:sy1, :sx1]
                result = canvas

            return result

        except Exception as e:
            logger.error(f"应用效果失败: {e}")
            return frame

    def _preload_frames(self, count: int = 30):
        if self._video_duration < 2.0:
            count = max(1, int(count * self._video_duration / 2.0))
        for i in range(count):
            t = i * (self._video_duration / count)
            try:
                self.get_frame_at(t)
            except Exception:
                break

    def update_preview(self, time_sec, video_data=None, effects=None):
        self.current_time = time_sec
        if effects is not None:
            self._current_effects = effects
        elif effects is None and video_data is None:
            effects = getattr(self, "_current_effects", None)
        # 不依赖 preview_window：Editor 用 frame_ready 信号刷新预览标签
        qimage = self.get_frame_at(time_sec, effects)
        if qimage is not None:
            self.frame_ready.emit(qimage)
            tc = self.format_timecode(time_sec)
            self.timecode_updated.emit(tc)

    def drag_timeline_preview(self, start_time, end_time, current_time):
        logger.info(f"拖拽时间轴预览: 从 {start_time:.2f} 到 {end_time:.2f}，当前 {current_time:.2f}")
        self.update_preview(current_time)
        return True

    def set_active_effects(self, effects: Optional[Dict]):
        """设置当前效果参数 - 只标记效果变更，不立即清空全部缓存"""
        self._current_effects = effects
        # 只清除最近几帧的缓存，保留历史帧缓存以提高性能
        try:
            with self._lock:
                # 清除最近5帧缓存
                if len(self.preview_cache) > 5:
                    keys_to_remove = list(self.preview_cache.keys())[:5]
                    for key in keys_to_remove:
                        self.preview_cache.pop(key, None)
        except Exception as e:
            logger.debug(f"[PreviewManager] 清理预览缓存失败: {e}")

    def _normalize_effects(self, effects: Optional[Dict]) -> Dict:
        if not effects:
            return {}
        out: Dict[str, Any] = {}
        for k, v in effects.items():
            if k == "color_params" and isinstance(v, dict):
                out.update(v)
            else:
                out[k] = v
        return out

    def _apply_named_filter(self, frame: np.ndarray, name: str, intensity: float) -> np.ndarray:
        intensity = max(0.0, min(1.0, float(intensity)))
        if not name or intensity <= 0:
            return frame
        base = frame.astype(np.float32)
        result = base.copy()

        def _mix(processed: np.ndarray) -> np.ndarray:
            return base * (1.0 - intensity) + processed * intensity

        try:
            if name == "黑白":
                gray = result.mean(axis=2, keepdims=True)
                result = _mix(np.repeat(gray, 3, axis=2))
            elif name in ("暖色调", "黄昏"):
                processed = result.copy()
                processed[:, :, 0] = np.clip(processed[:, :, 0] * 1.12, 0, 255)
                processed[:, :, 2] = np.clip(processed[:, :, 2] * 0.90, 0, 255)
                result = _mix(processed)
            elif name in ("冷色调", "都市"):
                processed = result.copy()
                processed[:, :, 0] = np.clip(processed[:, :, 0] * 0.92, 0, 255)
                processed[:, :, 2] = np.clip(processed[:, :, 2] * 1.10, 0, 255)
                result = _mix(processed)
            elif name == "清新":
                mean = result.mean()
                processed = (result - mean) * 1.15 + mean + 8
                result = _mix(np.clip(processed, 0, 255))
            elif name in ("复古", "电影感"):
                mean = result.mean()
                processed = (result - mean) * 1.12 + mean
                sat = processed.mean(axis=2, keepdims=True)
                processed = sat + (processed - sat) * 0.85
                result = _mix(np.clip(processed, 0, 255))
                if CV2_AVAILABLE and intensity > 0.2:
                    h, w = result.shape[:2]
                    yy, xx = np.ogrid[:h, :w]
                    dist = np.sqrt(((xx - w / 2) / max(w / 2, 1)) ** 2 + ((yy - h / 2) / max(h / 2, 1)) ** 2)
                    mask = np.clip(1.0 - dist * (0.35 * intensity), 0.35, 1.0)
                    result = result * mask[:, :, np.newaxis]
            elif name in ("梦幻", "柔和") and CV2_AVAILABLE:
                k = 1 + int(2 * intensity) * 2
                blurred = cv2.GaussianBlur(frame, (k, k), 0).astype(np.float32)
                result = _mix(blurred)
            elif name == "锐利" and CV2_AVAILABLE:
                kernel = np.array([[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]], dtype=np.float32)
                sharp = cv2.filter2D(frame, -1, kernel).astype(np.float32)
                result = _mix(np.clip(sharp, 0, 255))
            else:
                gray = result.mean(axis=2, keepdims=True)
                processed = gray + (result - gray) * (1.0 + 0.25 * intensity)
                result = np.clip(processed, 0, 255)
        except Exception as e:
            logger.error(f"命名滤镜失败 {name}: {e}")
            return frame
        return np.clip(result, 0, 255).astype(np.uint8)

    def format_timecode(self, seconds):
        seconds = max(0, seconds)
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        ms = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}.{ms:03d}"

    def set_timecode_visibility(self, visible):
        self.timecode_visible = visible
        logger.info(f"时间码可见性: {visible}")
        return True

    def set_preview_window(self, window):
        self.preview_window = window
        logger.info("设置预览窗口成功")
        return True

    def play_preview(self, start_time=None, speed=1.0):
        """开始预览播放 - 统一使用 FrameReaderThread 读取帧"""
        if start_time is not None:
            self._seek_to(start_time)
            self.current_time = start_time
        self.playing_speed = speed
        self.is_playing = True

        if self._frame_reader_thread:
            self._frame_reader_thread.play()
        else:
            # 回退到计时器模式（不推荐）
            self._playback_timer.start(self._playback_interval_ms)

        logger.info(f"开始预览播放，从 {self.current_time:.2f}s，速度: {speed}x")

    def pause_preview(self):
        self.is_playing = False
        self._playback_timer.stop()

        if self._frame_reader_thread:
            self._frame_reader_thread.pause()

        logger.info(f"暂停预览播放，当前时间: {self.current_time:.2f}s")

    def stop_preview(self):
        self.is_playing = False
        self._playback_timer.stop()
        self._seek_to(0.0)
        self.current_time = 0.0

        if self._frame_reader_thread:
            self._frame_reader_thread.seek_to(0)
        
        if self._interpolation_enabled:
            from app.core.ai_interpolation import ai_interpolation_engine
            ai_interpolation_engine.stop()

        logger.info("停止预览播放")

    def set_interpolation_enabled(self, enabled: bool):
        """启用/禁用线性补帧（非神经网络）"""
        self._interpolation_enabled = enabled
        if enabled:
            from app.core.ai_interpolation import ai_interpolation_engine
            ai_interpolation_engine.enable(True)
            ai_interpolation_engine.start()
            logger.info("线性补帧已启用（帧差+线性混合，非 AI 模型）")
        else:
            from app.core.ai_interpolation import ai_interpolation_engine
            ai_interpolation_engine.stop()
            ai_interpolation_engine.enable(False)
            logger.info("线性补帧已禁用")

    def set_interpolation_mode(self, mode: str):
        """设置补帧模式: disabled, auto, always, smart"""
        self._interpolation_mode = mode
        from app.core.ai_interpolation import ai_interpolation_engine, InterpolationMode
        mode_enum = InterpolationMode(mode)
        ai_interpolation_engine.set_mode(mode_enum)
        logger.info(f"补帧模式设置为: {mode}")

    def set_proxy_preview_enabled(self, enabled: bool):
        self.proxy_preview_enabled = enabled
        logger.info(f"代理预览: {'启用' if enabled else '禁用'}")

    def set_preview_quality(self, quality: str):
        q = str(quality or "high").strip().lower()
        if q not in ("low", "medium", "high"):
            q = "high"
        # 同档位不整表清空：scrub 反复 low↔user 时避免每轮刷掉刚解码的帧
        if q == getattr(self, "preview_quality", None):
            return
        self.preview_quality = q
        # 分辨率档位变化后旧缓存尺寸不一致，清掉避免错帧
        try:
            self.clear_preview_cache()
        except Exception as e:
            logger.debug(f"[PreviewManager] 清理预览缓存失败: {e}")
        logger.info(f"预览质量设置为: {q}")

    def clear_preview_cache(self):
        with self._lock:
            self.preview_cache.clear()
        logger.info("预览缓存已清理")

    def get_cache_stats(self) -> Dict[str, Any]:
        memory_stats = self._memory_pool.get_stats() if self._memory_pool else {}
        with self._lock:
            cache_size = len(self.preview_cache)
        return {
            'cache_size': cache_size,
            'max_size': self.max_cache_size,
            'usage_percent': cache_size / self.max_cache_size * 100 if self.max_cache_size > 0 else 0,
            'memory_pool_stats': memory_stats
        }

    @property
    def video_duration(self) -> float:
        return self._video_duration

    @property
    def video_fps(self) -> float:
        return self._video_fps

    @property
    def video_size(self) -> Tuple[int, int]:
        return (self._video_width, self._video_height)

    def _cleanup_cache(self):
        with self._lock:
            while len(self.preview_cache) > self.max_cache_size:
                self.preview_cache.popitem(last=False)
        self._memory_pool.optimize_memory() if self._memory_pool else None
        gc.collect()

    def optimize_memory(self):
        self._cleanup_cache()
        gc.collect()
        stats = self.get_cache_stats()
        logger.info(f"内存优化完成: 缓存大小={stats['cache_size']}")

    def shutdown(self):
        self.stop_preview()
        self._cleanup_timer.stop()
        self._close_video()
        self.clear_preview_cache()
        self._memory_pool.clear() if self._memory_pool else None
        gc.collect()
        logger.info("预览管理器已关闭")