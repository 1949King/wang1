"""FFmpeg解码服务 - 独立线程运行，输出帧和波形数据"""

import os
import subprocess
import json
import logging
import time
from typing import Dict, Any, Optional

from PyQt6.QtCore import QThread, QObject, pyqtSignal

logger = logging.getLogger("AI短剧编辑器.ffmpeg_service")


class FFmpegDecodeThread(QThread):
    frame_decoded = pyqtSignal(int, bytes)
    waveform_extracted = pyqtSignal(list)
    metadata_loaded = pyqtSignal(dict)
    thumbnail_generated = pyqtSignal(int, bytes)
    progress_updated = pyqtSignal(int)
    error_occurred = pyqtSignal(str)
    task_completed = pyqtSignal()

    def __init__(self, ffmpeg_path: str, media_path: str, task_type: str = "metadata"):
        super().__init__()
        self._ffmpeg_path = ffmpeg_path
        self._media_path = media_path
        self._task_type = task_type
        self._stop_flag = False

    def stop(self):
        self._stop_flag = True

    def run(self):
        try:
            if self._task_type == "metadata":
                self._extract_metadata()
            elif self._task_type == "waveform":
                self._extract_waveform()
            elif self._task_type == "thumbnail":
                self._generate_thumbnail()
            elif self._task_type == "decode":
                self._decode_frames()
        except Exception as e:
            self.error_occurred.emit(str(e))
            logger.error(f"解码任务失败: {e}")

    def _extract_metadata(self):
        cmd = [
            self._ffmpeg_path, "-i", self._media_path,
            "-f", "json", "-", "-hide_banner", "-loglevel", "error"
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                metadata = self._parse_error_metadata()
            else:
                metadata = self._parse_metadata(result.stdout)
            self.metadata_loaded.emit(metadata)
        except subprocess.TimeoutExpired:
            self.metadata_loaded.emit(self._parse_error_metadata())
        self.task_completed.emit()

    def _parse_metadata(self, output: str) -> dict:
        try:
            info = json.loads(output)
            streams = info.get('streams', [])
            metadata = {
                "video_width": 1920,
                "video_height": 1080,
                "duration": 0,
                "has_audio": False,
                "has_video": False,
                "frame_count": 0,
            }

            for stream in streams:
                codec_type = stream.get('codec_type', '')
                if codec_type == 'video':
                    metadata['has_video'] = True
                    metadata['video_width'] = stream.get('width', 1920)
                    metadata['video_height'] = stream.get('height', 1080)
                elif codec_type == 'audio':
                    metadata['has_audio'] = True

            format_info = info.get('format', {})
            duration_str = format_info.get('duration', '0')
            try:
                metadata['duration'] = float(duration_str)
            except ValueError as e:
                logger.debug(f"[FFmpegService] 解析时长失败: {e}")
                metadata['duration'] = 0

            return metadata
        except Exception as e:
            logger.debug(f"[FFmpegService] 解析元数据失败: {e}")
            return self._parse_error_metadata()

    def _parse_error_metadata(self) -> dict:
        return {
            "video_width": 1920,
            "video_height": 1080,
            "duration": 10.0,
            "has_audio": True,
            "has_video": True,
            "frame_count": 300,
        }

    def _extract_waveform(self):
        sample_rate = 44100
        duration = 10
        cmd = [
            self._ffmpeg_path, "-i", self._media_path,
            "-ac", "1", "-ar", str(sample_rate),
            "-t", str(duration),
            "-f", "s16le", "-"
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=60)
            if result.returncode == 0 and result.stdout:
                import struct
                samples = struct.unpack(f"<{len(result.stdout)//2}h", result.stdout)
                samples = list(samples)
                num_bars = 200
                bar_size = len(samples) // num_bars
                peaks = []
                for i in range(num_bars):
                    start = i * bar_size
                    end = start + bar_size
                    bar_samples = samples[start:end]
                    if bar_samples:
                        max_val = max(abs(s) for s in bar_samples)
                        peaks.append(max_val / 32768.0)
                    else:
                        peaks.append(0.0)
                self.waveform_extracted.emit(peaks)
            else:
                self.waveform_extracted.emit([])
        except Exception as e:
            logger.error(f"波形提取失败: {e}")
            self.waveform_extracted.emit([])
        self.task_completed.emit()

    def _generate_thumbnail(self):
        cmd = [
            self._ffmpeg_path, "-i", self._media_path,
            "-vframes", "1", "-s", "320x240",
            "-f", "image2pipe", "-vcodec", "png", "-"
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=30)
            if result.returncode == 0 and result.stdout:
                self.thumbnail_generated.emit(0, result.stdout)
        except Exception as e:
            logger.error(f"缩略图生成失败: {e}")
        self.task_completed.emit()

    def _decode_frames(self):
        cmd = [
            self._ffmpeg_path, "-i", self._media_path,
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-"
        ]
        try:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            frame_num = 0
            frame_size = 1920 * 1080 * 3
            while not self._stop_flag:
                frame_data = process.stdout.read(frame_size)
                if not frame_data:
                    break
                self.frame_decoded.emit(frame_num, frame_data)
                frame_num += 1
                if frame_num % 30 == 0:
                    self.progress_updated.emit(int((frame_num / 3000) * 100))
            process.wait()
        except Exception as e:
            logger.error(f"帧解码失败: {e}")
        self.task_completed.emit()


class FFmpegService(QObject):
    metadata_ready = pyqtSignal(str, dict)
    waveform_ready = pyqtSignal(str, list)
    frame_ready = pyqtSignal(str, int, bytes)
    thumbnail_ready = pyqtSignal(str, bytes)
    decode_progress = pyqtSignal(str, int)
    decode_error = pyqtSignal(str, str)

    def __init__(self):
        super().__init__()
        self._ffmpeg_path = self._find_ffmpeg()
        self._threads = {}
        logger.info(f"FFmpeg服务初始化，FFmpeg路径: {self._ffmpeg_path}")

    def _find_ffmpeg(self) -> str:
        """复用统一的 FFmpeg 路径检测工具，避免重复逻辑和路径优先级问题"""
        try:
            from .ffmpeg_utils import find_ffmpeg
            ffmpeg_path = find_ffmpeg()
            if ffmpeg_path and os.path.exists(ffmpeg_path):
                return ffmpeg_path
        except ImportError as e:
            logger.debug(f"[FFmpegService] 导入find_ffmpeg失败: {e}")

        # 回退到原逻辑（优先项目内置，最后才用 Shotcut 的 FFmpeg）
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        project_ffmpeg = os.path.join(
            project_root, "thirdparty", "ffmpeg", "bin", "ffmpeg.exe"
        )
        if os.path.exists(project_ffmpeg):
            return project_ffmpeg

        venv_ffmpeg = os.path.join(
            project_root, ".venv312", "Scripts", "ffmpeg.exe"
        )
        if os.path.exists(venv_ffmpeg):
            return venv_ffmpeg

        env_ffmpeg = os.environ.get("FFMPEG_PATH", "")
        if env_ffmpeg and os.path.exists(env_ffmpeg):
            return env_ffmpeg

        for path in os.environ.get("PATH", "").split(os.pathsep):
            ffmpeg_path = os.path.join(path, "ffmpeg.exe")
            if os.path.exists(ffmpeg_path):
                return ffmpeg_path

        # Shotcut 的 FFmpeg 缺少关键编解码器，仅作为最后回退
        shotcut_ffmpeg = os.path.join(
            project_root, "thirdparty", "mlt", "Shotcut", "ffmpeg.exe"
        )
        if os.path.exists(shotcut_ffmpeg):
            return shotcut_ffmpeg

        return "ffmpeg"

    def extract_metadata(self, media_path: str) -> str:
        task_id = f"meta_{int(time.time() * 1000)}"
        thread = FFmpegDecodeThread(self._ffmpeg_path, media_path, "metadata")
        thread.metadata_loaded.connect(lambda meta: self.metadata_ready.emit(task_id, meta))
        thread.error_occurred.connect(lambda err: self.decode_error.emit(task_id, err))
        thread.task_completed.connect(lambda: self._cleanup_thread(task_id))
        self._threads[task_id] = thread
        thread.start()
        return task_id

    def extract_waveform(self, media_path: str) -> str:
        task_id = f"wave_{int(time.time() * 1000)}"
        thread = FFmpegDecodeThread(self._ffmpeg_path, media_path, "waveform")
        thread.waveform_extracted.connect(lambda data: self.waveform_ready.emit(task_id, data))
        thread.error_occurred.connect(lambda err: self.decode_error.emit(task_id, err))
        thread.task_completed.connect(lambda: self._cleanup_thread(task_id))
        self._threads[task_id] = thread
        thread.start()
        return task_id

    def generate_thumbnail(self, media_path: str) -> str:
        task_id = f"thumb_{int(time.time() * 1000)}"
        thread = FFmpegDecodeThread(self._ffmpeg_path, media_path, "thumbnail")
        thread.thumbnail_generated.connect(lambda _, data: self.thumbnail_ready.emit(task_id, data))
        thread.error_occurred.connect(lambda err: self.decode_error.emit(task_id, err))
        thread.task_completed.connect(lambda: self._cleanup_thread(task_id))
        self._threads[task_id] = thread
        thread.start()
        return task_id

    def decode_frames(self, media_path: str) -> str:
        task_id = f"decode_{int(time.time() * 1000)}"
        thread = FFmpegDecodeThread(self._ffmpeg_path, media_path, "decode")
        thread.frame_decoded.connect(lambda num, data: self.frame_ready.emit(task_id, num, data))
        thread.progress_updated.connect(lambda p: self.decode_progress.emit(task_id, p))
        thread.error_occurred.connect(lambda err: self.decode_error.emit(task_id, err))
        thread.task_completed.connect(lambda: self._cleanup_thread(task_id))
        self._threads[task_id] = thread
        thread.start()
        return task_id

    def stop_task(self, task_id: str):
        if task_id in self._threads:
            self._threads[task_id].stop()
            self._threads[task_id].wait()

    def _cleanup_thread(self, task_id: str):
        if task_id in self._threads:
            del self._threads[task_id]

    def extract_frame(self, media_path: str, timestamp: float = 0.0, width: int = 0, height: int = 96):
        """同步提取视频单帧，返回 QPixmap 或 None。

        时间线缩略图：按高度缩放、保持比例，绝不 pad。
        黑边 pad 会在 Expanding 绘制后仍呈「中间细条」。
        width<=0 时只约束高度（scale=-2:h）；两者都 >0 时用 increase+crop 铺满目标框。
        """
        try:
            from PyQt6.QtGui import QPixmap
            from PyQt6.QtCore import QByteArray

            h = max(8, int(height))
            w = int(width)
            if w > 0:
                w = max(8, w)
                # 偶数尺寸，兼容部分编码器
                w -= w % 2
                h -= h % 2
                vf = (
                    f"scale={w}:{h}:force_original_aspect_ratio=increase,"
                    f"crop={w}:{h}"
                )
            else:
                h -= h % 2
                vf = f"scale=-2:{h}"
            cmd = [
                self._ffmpeg_path, "-ss", str(timestamp),
                "-i", media_path,
                "-vframes", "1",
                "-vf", vf,
                "-f", "image2pipe", "-vcodec", "png", "-"
            ]
            
            result = subprocess.run(cmd, capture_output=True, timeout=10)
            if result.returncode == 0 and result.stdout:
                byte_array = QByteArray(result.stdout)
                pixmap = QPixmap()
                pixmap.loadFromData(byte_array)
                if not pixmap.isNull():
                    return pixmap
        except Exception as e:
            logger.error(f"帧提取失败: {e}")
        
        return None

    def extract_frames_batch(
        self, media_path: str, timestamps, height: int = 96, width: int = 0
    ):
        """批量抽帧（OpenCV 不可用时的胶片条回退）。返回 list[QPixmap]。"""
        out = []
        for t in timestamps or []:
            pm = self.extract_frame(media_path, float(t), width=width, height=height)
            if pm is not None and not pm.isNull():
                out.append(pm)
        return out


ffmpeg_service = FFmpegService()
