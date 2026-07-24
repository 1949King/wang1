"""
音频波形生成器 (WaveformGenerator)
===================================
对标 OpenShot/Shotcut 的时间线波形显示。

特性:
- PyAV 提取音频 PCM
- RMS 峰值降采样
- 多线程后台生成
- 缓存避免重复计算
- 输出 peaks 列表用于绘制
"""
import os
import math
import logging
import threading
from typing import List, Optional, Callable
from dataclasses import dataclass

logger = logging.getLogger("AI短剧编辑器.waveform")

# PyAV 不可用时使用 wave 库作为回退
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

try:
    import wave
    HAS_WAVE = True
except ImportError:
    HAS_WAVE = False


@dataclass
class WaveformData:
    """波形数据"""
    peaks: List[float]      # 峰值 (0.0 - 1.0), 长度 = num_samples
    duration: float         # 音频时长 (秒)
    sample_rate: int        # 采样率
    num_samples: int        # 采样点数
    cached_at: float        # 缓存时间戳


class WaveformGenerator:
    """
    音频波形生成器 (单例)
    - 懒加载
    - 缓存结果
    - 后台线程生成
    """

    _instance: Optional["WaveformGenerator"] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._init = False
        return cls._instance

    def __init__(self):
        if self._init:
            return
        self._init = True
        self._cache: dict = {}  # path -> (num_samples, WaveformData)
        self._cache_lock = threading.Lock()
        self._max_cache = 50

    def generate(self, audio_path: str, num_samples: int = 1000,
                 progress_cb: Optional[Callable] = None) -> Optional[WaveformData]:
        """
        生成音频波形数据

        Args:
            audio_path: 音频/视频文件路径
            num_samples: 降采样点数 (通常 500-2000)
            progress_cb: 进度回调

        Returns:
            WaveformData 或 None
        """
        if not os.path.exists(audio_path):
            return None

        # 检查缓存
        cache_key = f"{audio_path}#{num_samples}"
        with self._cache_lock:
            if cache_key in self._cache:
                return self._cache[cache_key][1]

        # 生成波形
        try:
            data = self._generate_internal(audio_path, num_samples, progress_cb)
            if data:
                with self._cache_lock:
                    if len(self._cache) >= self._max_cache:
                        # 删除最旧
                        oldest = min(self._cache.items(), key=lambda x: x[1][1].cached_at)
                        self._cache.pop(oldest[0], None)
                    import time
                    data.cached_at = time.time()
                    self._cache[cache_key] = (num_samples, data)
            return data
        except Exception as e:
            logger.error(f"生成波形失败 [{audio_path}]: {e}")
            return None

    def generate_async(self, audio_path: str, num_samples: int = 1000,
                       on_complete: Optional[Callable] = None):
        """异步生成"""
        thread = threading.Thread(
            target=lambda: self._async_run(audio_path, num_samples, on_complete),
            daemon=True,
        )
        thread.start()

    def _async_run(self, audio_path, num_samples, callback):
        data = self.generate(audio_path, num_samples)
        if callback:
            try:
                callback(data)
            except Exception:
                pass

    def _generate_internal(self, path: str, num_samples: int,
                           progress_cb=None) -> Optional[WaveformData]:
        """实际生成逻辑"""
        # 优先使用 PyAV
        try:
            return self._generate_pyav(path, num_samples, progress_cb)
        except Exception as e:
            logger.debug(f"PyAV 波形生成失败, 尝试回退: {e}")

        # 回退到 FFmpeg (支持所有格式)
        try:
            return self._generate_ffmpeg(path, num_samples, progress_cb)
        except Exception as e:
            logger.debug(f"FFmpeg 波形生成失败: {e}")

        # 回退到 wave 库 (仅 WAV)
        if HAS_WAVE and path.lower().endswith('.wav'):
            try:
                return self._generate_wave(path, num_samples, progress_cb)
            except Exception as e:
                logger.debug(f"wave 库波形生成失败: {e}")

        # 最终回退: 生成零波形
        return self._generate_silent(num_samples, 0.0)

    def _generate_pyav(self, path: str, num_samples: int,
                       progress_cb=None) -> WaveformData:
        """使用 PyAV 提取音频并降采样"""
        import time
        start = time.time()

        try:
            import av
        except ImportError:
            raise RuntimeError("PyAV not available")

        peaks = []
        duration = 0.0
        sample_rate = 44100
        total_samples_collected = 0

        with av.open(path, mode='r') as container:
            if not container.streams.audio:
                raise RuntimeError("No audio stream")

            audio_stream = container.streams.audio[0]
            sample_rate = audio_stream.rate or 44100

            # 估算音频总帧数
            if container.duration:
                duration = float(container.duration) / av.time_base
            else:
                duration = 0.0

            # 收集所有 PCM 样本
            all_pcm = []
            for frame in container.decode(audio_stream):
                pcm = frame.to_ndarray()
                # 转为单声道
                if pcm.ndim > 1:
                    pcm = pcm.mean(axis=0)
                all_pcm.append(pcm)
                total_samples_collected += len(pcm)

                if progress_cb and duration > 0:
                    current_time = float(frame.pts * frame.time_base) if frame.pts else 0
                    progress_cb(min(90, current_time / duration * 100))

            if not all_pcm:
                raise RuntimeError("No audio data")

            if HAS_NUMPY:
                full = np.concatenate(all_pcm)
                # 归一化到 [-1, 1]
                max_val = max(abs(full.max()), abs(full.min()), 1e-6)
                full = full / max_val

                # 分桶, 每桶取 RMS
                bucket_size = max(1, len(full) // num_samples)
                peaks = []
                for i in range(0, len(full), bucket_size):
                    bucket = full[i:i + bucket_size]
                    if len(bucket) > 0:
                        rms = float(np.sqrt(np.mean(bucket ** 2)))
                        peaks.append(min(1.0, rms))
                peaks = peaks[:num_samples]
            else:
                # 纯 Python 回退
                full = []
                for arr in all_pcm:
                    full.extend(arr.tolist() if hasattr(arr, 'tolist') else list(arr))
                max_val = max(abs(min(full)), abs(max(full)), 1e-6) if full else 1
                full = [s / max_val for s in full]
                bucket_size = max(1, len(full) // num_samples)
                peaks = []
                for i in range(0, len(full), bucket_size):
                    bucket = full[i:i + bucket_size]
                    if bucket:
                        rms = math.sqrt(sum(x * x for x in bucket) / len(bucket))
                        peaks.append(min(1.0, rms))
                peaks = peaks[:num_samples]

            # 填充不足
            while len(peaks) < num_samples:
                peaks.append(0.0)

        return WaveformData(
            peaks=peaks,
            duration=duration,
            sample_rate=sample_rate,
            num_samples=num_samples,
            cached_at=time.time(),
        )

    def _generate_wave(self, path: str, num_samples: int,
                       progress_cb=None) -> WaveformData:
        """使用 wave 库 (仅 WAV)"""
        import time
        with wave.open(path, 'rb') as wf:
            sample_rate = wf.getframerate()
            n_frames = wf.getnframes()
            n_channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            duration = n_frames / sample_rate

            raw = wf.readframes(n_frames)

            # 解析为整数样本
            if sample_width == 1:
                samples = [b - 128 for b in raw]
            elif sample_width == 2:
                import struct
                samples = list(struct.unpack(f'<{n_frames * n_channels}h', raw))
            elif sample_width == 4:
                import struct
                samples = list(struct.unpack(f'<{n_frames * n_channels}i', raw))
            else:
                raise RuntimeError(f"Unsupported sample width: {sample_width}")

            # 转为单声道
            if n_channels > 1:
                samples = samples[::n_channels]

            max_val = max(abs(min(samples)), abs(max(samples)), 1)
            samples = [s / max_val for s in samples]

            bucket_size = max(1, len(samples) // num_samples)
            peaks = []
            for i in range(0, len(samples), bucket_size):
                bucket = samples[i:i + bucket_size]
                if bucket:
                    rms = math.sqrt(sum(x * x for x in bucket) / len(bucket))
                    peaks.append(min(1.0, rms))
            peaks = peaks[:num_samples]
            while len(peaks) < num_samples:
                peaks.append(0.0)

        return WaveformData(
            peaks=peaks,
            duration=duration,
            sample_rate=sample_rate,
            num_samples=num_samples,
            cached_at=time.time(),
        )

    def _generate_ffmpeg(self, path: str, num_samples: int,
                         progress_cb=None) -> WaveformData:
        """使用 FFmpeg 提取音频并降采样（支持所有格式）"""
        import subprocess
        import struct
        
        # 查找 FFmpeg 路径
        ffmpeg_path = self._find_ffmpeg_path()
        
        # 提取音频 PCM (单声道, 44100Hz, 16位)
        cmd = [
            ffmpeg_path, "-i", path,
            "-ac", "1", "-ar", "44100",
            "-f", "s16le", "-vcodec", "none", "-"
        ]
        
        result = subprocess.run(cmd, capture_output=True, timeout=60)
        if result.returncode != 0 or not result.stdout:
            raise RuntimeError(f"FFmpeg 提取音频失败: {result.stderr.decode('utf-8', errors='ignore')}")
        
        # 解析 PCM 数据
        raw_data = result.stdout
        # 每样本 2 字节 (16位)
        num_raw_samples = len(raw_data) // 2
        samples = struct.unpack(f"<{num_raw_samples}h", raw_data)
        samples = list(samples)
        
        # 归一化到 [-1, 1]
        max_val = max(abs(min(samples)), abs(max(samples)), 1)
        samples = [s / max_val for s in samples]
        
        # 降采样为 num_samples 个峰值
        bucket_size = max(1, len(samples) // num_samples)
        peaks = []
        for i in range(0, len(samples), bucket_size):
            bucket = samples[i:i + bucket_size]
            if bucket:
                rms = math.sqrt(sum(x * x for x in bucket) / len(bucket))
                peaks.append(min(1.0, rms))
        peaks = peaks[:num_samples]
        
        # 填充不足
        while len(peaks) < num_samples:
            peaks.append(0.0)
        
        # 估算时长
        duration = len(samples) / 44100.0
        
        return WaveformData(
            peaks=peaks,
            duration=duration,
            sample_rate=44100,
            num_samples=num_samples,
            cached_at=time.time(),
        )
    
    def _find_ffmpeg_path(self) -> str:
        """查找 FFmpeg 可执行文件路径"""
        import os
        
        # 优先使用项目内的 FFmpeg
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        candidates = [
            os.path.join(project_root, "thirdparty", "ffmpeg", "bin", "ffmpeg.exe"),
            os.path.join(project_root, "thirdparty", "mlt", "Shotcut", "ffmpeg.exe"),
        ]
        
        for path in candidates:
            if os.path.exists(path):
                return path
        
        # 查找系统 PATH
        for path in os.environ.get("PATH", "").split(os.pathsep):
            ffmpeg_path = os.path.join(path, "ffmpeg.exe")
            if os.path.exists(ffmpeg_path):
                return ffmpeg_path
        
        return "ffmpeg"
    
    def _generate_silent(self, num_samples: int, duration: float) -> WaveformData:
        """生成静音波形 (回退)"""
        return WaveformData(
            peaks=[0.0] * num_samples,
            duration=duration,
            sample_rate=44100,
            num_samples=num_samples,
            cached_at=0,
        )

    def clear_cache(self):
        """清空缓存"""
        with self._cache_lock:
            self._cache.clear()


# 全局实例
waveform_generator = WaveformGenerator()
