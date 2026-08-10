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
    peaks: List[float]      # 峰值 (0.0 - 1.0), 长度 = num_samples（向后兼容，RMS）
    duration: float         # 音频时长 (秒)
    sample_rate: int        # 采样率
    num_samples: int        # 采样点数
    cached_at: float        # 缓存时间戳
    min_peaks: List[float] = None   # 每桶最小样本值 (-1.0 ~ 0)，负半区着色用
    max_peaks: List[float] = None   # 每桶最大样本值 (0 ~ 1.0)，正半区着色用


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

        # 检查缓存（加 #v2 让旧版本——没有 min_peaks/max_peaks 的缓存自动失效）
        cache_key = f"{audio_path}#{num_samples}#v2"
        with self._cache_lock:
            if cache_key in self._cache:
                cached = self._cache[cache_key][1]
                # 防御：万一缓存里仍是旧对象（min_peaks=None），也丢掉重算
                if cached is not None and cached.min_peaks and cached.max_peaks:
                    return cached

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
            except Exception as e:
                logger.debug(f"[WaveformGenerator] 回调执行失败: {e}")

    def _generate_internal(self, path: str, num_samples: int,
                           progress_cb=None) -> Optional[WaveformData]:
        """实际生成逻辑。全部失败返回 None（不再静默全 0）。"""
        # 优先使用 PyAV
        try:
            data = self._generate_pyav(path, num_samples, progress_cb)
            if data and data.peaks and max(data.peaks) > 1e-6:
                return data
        except Exception as e:
            logger.debug(f"PyAV 波形生成失败, 尝试回退: {e}")

        # 回退到 FFmpeg (支持所有格式)
        try:
            data = self._generate_ffmpeg(path, num_samples, progress_cb)
            if data and data.peaks and max(data.peaks) > 1e-6:
                return data
        except Exception as e:
            logger.debug(f"FFmpeg 波形生成失败: {e}")

        # 回退到 wave 库 (仅 WAV)
        if HAS_WAVE and path.lower().endswith('.wav'):
            try:
                data = self._generate_wave(path, num_samples, progress_cb)
                if data and data.peaks and max(data.peaks) > 1e-6:
                    return data
            except Exception as e:
                logger.debug(f"wave 库波形生成失败: {e}")

        logger.warning(f"波形生成全部失败: {path}")
        return None

    @staticmethod
    def _pcm_to_mono(pcm):
        """将 PyAV frame.to_ndarray() 结果转为 1D 单声道。"""
        if not hasattr(pcm, "ndim"):
            return pcm
        if pcm.ndim == 1:
            return pcm
        if pcm.ndim == 2:
            # (channels, samples) 或 (samples, channels)
            if pcm.shape[0] <= 8 and pcm.shape[0] < pcm.shape[1]:
                return pcm.mean(axis=0)
            return pcm.mean(axis=1)
        return pcm.reshape(-1)

    def _generate_pyav(self, path: str, num_samples: int,
                       progress_cb=None) -> WaveformData:
        """使用 PyAV 提取音频并降采样"""
        import time

        try:
            import av
        except ImportError:
            raise RuntimeError("PyAV not available")

        peaks = []
        duration = 0.0
        sample_rate = 44100

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
                pcm = self._pcm_to_mono(frame.to_ndarray())
                all_pcm.append(pcm)

                if progress_cb and duration > 0:
                    current_time = float(frame.pts * frame.time_base) if frame.pts else 0
                    progress_cb(min(90, current_time / duration * 100))

            if not all_pcm:
                raise RuntimeError("No audio data")

            if HAS_NUMPY:
                full = np.concatenate(all_pcm)
                # 归一化到 [-1, 1]
                max_val = max(abs(float(full.max())), abs(float(full.min())), 1e-6)
                full = full / max_val

                # 分桶, 每桶取 RMS + min + max（负正半区着色用）
                bucket_size = max(1, len(full) // num_samples)
                peaks = []
                min_peaks = []
                max_peaks = []
                for i in range(0, len(full), bucket_size):
                    bucket = full[i:i + bucket_size]
                    if len(bucket) > 0:
                        rms = float(np.sqrt(np.mean(bucket ** 2)))
                        peaks.append(min(1.0, rms))
                        min_peaks.append(float(bucket.min()))  # -1~0
                        max_peaks.append(float(bucket.max()))  # 0~1
                peaks = peaks[:num_samples]
                min_peaks = min_peaks[:num_samples]
                max_peaks = max_peaks[:num_samples]
            else:
                # 纯 Python 回退
                full = []
                for arr in all_pcm:
                    full.extend(arr.tolist() if hasattr(arr, 'tolist') else list(arr))
                max_val = max(abs(min(full)), abs(max(full)), 1e-6) if full else 1
                full = [s / max_val for s in full]
                bucket_size = max(1, len(full) // num_samples)
                peaks = []
                min_peaks = []
                max_peaks = []
                for i in range(0, len(full), bucket_size):
                    bucket = full[i:i + bucket_size]
                    if bucket:
                        rms = math.sqrt(sum(x * x for x in bucket) / len(bucket))
                        peaks.append(min(1.0, rms))
                        min_peaks.append(min(bucket))
                        max_peaks.append(max(bucket))
                peaks = peaks[:num_samples]
                min_peaks = min_peaks[:num_samples]
                max_peaks = max_peaks[:num_samples]

            # 填充不足
            while len(peaks) < num_samples:
                peaks.append(0.0)
                min_peaks.append(0.0)
                max_peaks.append(0.0)

        return WaveformData(
            peaks=peaks,
            duration=duration,
            sample_rate=sample_rate,
            num_samples=num_samples,
            cached_at=time.time(),
            min_peaks=min_peaks,
            max_peaks=max_peaks,
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
            min_peaks = []
            max_peaks = []
            for i in range(0, len(samples), bucket_size):
                bucket = samples[i:i + bucket_size]
                if bucket:
                    rms = math.sqrt(sum(x * x for x in bucket) / len(bucket))
                    peaks.append(min(1.0, rms))
                    min_peaks.append(min(bucket))
                    max_peaks.append(max(bucket))
            peaks = peaks[:num_samples]
            min_peaks = min_peaks[:num_samples]
            max_peaks = max_peaks[:num_samples]
            while len(peaks) < num_samples:
                peaks.append(0.0)
                min_peaks.append(0.0)
                max_peaks.append(0.0)

        return WaveformData(
            peaks=peaks,
            duration=duration,
            sample_rate=sample_rate,
            num_samples=num_samples,
            cached_at=time.time(),
            min_peaks=min_peaks,
            max_peaks=max_peaks,
        )

    def _generate_ffmpeg(self, path: str, num_samples: int,
                         progress_cb=None) -> WaveformData:
        """使用 FFmpeg 提取音频并降采样（支持所有格式）"""
        import subprocess
        import struct
        import time
        
        # 查找 FFmpeg 路径
        ffmpeg_path = self._find_ffmpeg_path()
        logger.debug(f"波形生成 FFmpeg路径: {ffmpeg_path}")
        
        # 提取音频 PCM (单声道, 44100Hz, 16位)
        # 限制提取前60秒，避免长视频内存溢出
        cmd = [
            ffmpeg_path, "-i", path,
            "-ac", "1", "-ar", "44100",
            "-t", "60",  # 限制提取时长
            "-f", "s16le", "-vn", "-"  # -vn 禁用视频，-f s16le 输出原始PCM
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=60,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        logger.debug(f"波形生成返回码: {result.returncode}, 输出长度: {len(result.stdout)}")
        
        if result.returncode != 0 or not result.stdout:
            # 打印错误信息便于调试
            stderr_msg = result.stderr.decode('utf-8', errors='ignore')[:500]
            logger.error(f"FFmpeg 提取音频失败: {stderr_msg}")
            raise RuntimeError(f"FFmpeg 提取音频失败: {stderr_msg}")
        
        # 解析 PCM 数据
        raw_data = result.stdout
        # 每样本 2 字节 (16位)
        num_raw_samples = len(raw_data) // 2
        samples = struct.unpack(f"<{num_raw_samples}h", raw_data)
        samples = list(samples)
        
        logger.debug(f"波形生成原始采样数: {len(samples)}")
        if samples:
            logger.debug(f"波形生成原始采样范围: {min(samples)} ~ {max(samples)}")
        
        # 归一化到 [-1, 1]
        max_val = max(abs(min(samples)), abs(max(samples)), 1)
        logger.debug(f"波形生成 max_val: {max_val}")
        samples = [s / max_val for s in samples]
        
        # 降采样为 num_samples 个峰值
        bucket_size = max(1, len(samples) // num_samples)
        peaks = []
        min_peaks = []
        max_peaks = []
        for i in range(0, len(samples), bucket_size):
            bucket = samples[i:i + bucket_size]
            if bucket:
                rms = math.sqrt(sum(x * x for x in bucket) / len(bucket))
                peaks.append(min(1.0, rms))
                min_peaks.append(min(bucket))
                max_peaks.append(max(bucket))
        peaks = peaks[:num_samples]
        min_peaks = min_peaks[:num_samples]
        max_peaks = max_peaks[:num_samples]

        logger.debug(f"波形生成峰值数: {len(peaks)}, 峰值范围: {min(peaks) if peaks else 0} ~ {max(peaks) if peaks else 0}")

        # 填充不足
        while len(peaks) < num_samples:
            peaks.append(0.0)
            min_peaks.append(0.0)
            max_peaks.append(0.0)

        # 估算时长
        duration = len(samples) / 44100.0

        return WaveformData(
            peaks=peaks,
            duration=duration,
            sample_rate=44100,
            num_samples=num_samples,
            cached_at=time.time(),
            min_peaks=min_peaks,
            max_peaks=max_peaks,
        )
    
    def _find_ffmpeg_path(self) -> str:
        """查找 FFmpeg 可执行文件路径 - 复用统一的检测工具"""
        import os
        try:
            from .ffmpeg_utils import find_ffmpeg
            ffmpeg_path = find_ffmpeg()
            if ffmpeg_path and os.path.exists(ffmpeg_path):
                return ffmpeg_path
        except ImportError as e:
            logger.debug(f"[WaveformGenerator] 导入find_ffmpeg失败: {e}")
        
        # 回退到原逻辑
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        candidates = [
            os.path.join(project_root, "thirdparty", "ffmpeg", "bin", "ffmpeg.exe"),
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
            min_peaks=[0.0] * num_samples,
            max_peaks=[0.0] * num_samples,
        )

    def clear_cache(self):
        """清空缓存"""
        with self._cache_lock:
            self._cache.clear()


# 全局实例
waveform_generator = WaveformGenerator()
