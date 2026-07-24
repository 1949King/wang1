"""
音频示波器 (Audio Scopes)
===========================
对标 OpenShot 的 Audio Scopes (波形/频谱/响度/相位等)。

特性:
- 5 种示波器: 波形, 频谱, 响度计, 峰值表, 相位矢量
- numpy FFT 计算
- 实时更新支持
"""
import math
import logging
from typing import List, Optional, Tuple
from dataclasses import dataclass

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

logger = logging.getLogger("AI短剧编辑器.audio_scopes")


@dataclass
class ScopeData:
    """示波器数据"""
    scope_type: str
    data: object           # numpy 数组
    timestamp: float
    min_val: float
    max_val: float


class WaveformScope:
    """波形示波器"""

    def compute(self, pcm: "np.ndarray", width: int = 512) -> Optional["np.ndarray"]:
        """
        计算波形 (L/R 通道, 归一化)

        Args:
            pcm: shape=(N,) 或 (N, 2) 音频数据
            width: 输出宽度
        """
        if not HAS_NUMPY or pcm is None or len(pcm) == 0:
            return None
        if pcm.ndim == 1:
            pcm = pcm.reshape(-1, 1)
        num_channels = pcm.shape[1] if pcm.ndim > 1 else 1
        bucket_size = max(1, len(pcm) // width)
        result = np.zeros((width, 2), dtype=np.float32) if num_channels >= 2 else np.zeros((width, 1), dtype=np.float32)
        for ch in range(min(num_channels, 2)):
            for i in range(width):
                start = i * bucket_size
                end = min(start + bucket_size, len(pcm))
                if end > start:
                    bucket = pcm[start:end, ch]
                    min_v = float(np.min(bucket))
                    max_v = float(np.max(bucket))
                    if num_channels >= 2:
                        result[i, ch] = max(abs(min_v), abs(max_v))
                    else:
                        result[i, 0] = max(abs(min_v), abs(max_v))
        return result


class SpectrumScope:
    """频谱示波器 (FFT)"""

    def compute(self, pcm: "np.ndarray", sample_rate: int = 44100,
                fft_size: int = 2048, num_bands: int = 64) -> Optional["np.ndarray"]:
        """
        计算频谱 (分贝值)

        Args:
            pcm: 音频数据
            sample_rate: 采样率
            fft_size: FFT 窗口大小
            num_bands: 频段数
        """
        if not HAS_NUMPY or pcm is None or len(pcm) < fft_size:
            return None
        if pcm.ndim > 1:
            pcm = pcm.mean(axis=1)
        # 取最后一个 fft_size 样本
        samples = pcm[-fft_size:].astype(np.float32)
        # Hann 窗
        window = np.hanning(fft_size)
        samples = samples * window
        # FFT
        fft = np.fft.rfft(samples)
        magnitude = np.abs(fft) / fft_size
        # 转 dB
        magnitude_db = 20 * np.log10(magnitude + 1e-10)
        magnitude_db = np.clip(magnitude_db, -80, 0)
        # 频率分桶 (对数分布)
        freqs = np.fft.rfftfreq(fft_size, 1.0 / sample_rate)
        result = np.zeros(num_bands, dtype=np.float32)
        for i in range(num_bands):
            # 对数分布
            f_low = 20 * (20000 / 20) ** (i / num_bands)
            f_high = 20 * (20000 / 20) ** ((i + 1) / num_bands)
            mask = (freqs >= f_low) & (freqs < f_high)
            if np.any(mask):
                result[i] = float(np.mean(magnitude_db[mask]))
            else:
                result[i] = -80.0
        return result


class LoudnessScope:
    """响度计 (简化 LUFS)"""

    def compute(self, pcm: "np.ndarray", sample_rate: int = 44100) -> dict:
        """
        计算响度 (RMS-based, 近似 LUFS)

        Returns:
            {rms_db, peak_db, lufs_approx, true_peak}
        """
        if not HAS_NUMPY or pcm is None or len(pcm) == 0:
            return {"rms_db": -120, "peak_db": -120, "lufs_approx": -120, "true_peak": -120}
        if pcm.ndim > 1:
            pcm = pcm.mean(axis=1)
        # 归一化 (假设输入为 [-1, 1])
        pcm = np.clip(pcm, -1, 1).astype(np.float32)
        # RMS
        rms = float(np.sqrt(np.mean(pcm ** 2)))
        rms_db = 20 * math.log10(rms + 1e-10)
        # Peak
        peak = float(np.max(np.abs(pcm)))
        peak_db = 20 * math.log10(peak + 1e-10)
        # 简化 LUFS (近似): rms_db - 0.691
        lufs_approx = rms_db - 0.691
        return {
            "rms_db": max(-120, rms_db),
            "peak_db": max(-120, peak_db),
            "lufs_approx": max(-120, lufs_approx),
            "true_peak": max(-120, peak_db + 0.5),
        }


class PeakMeterScope:
    """峰值表 (立体声)"""

    def compute(self, pcm: "np.ndarray", num_segments: int = 32) -> Optional["np.ndarray"]:
        """
        立体声峰值表 (L/R 通道分别)

        Returns:
            shape=(num_segments, 2) 范围 0-1
        """
        if not HAS_NUMPY or pcm is None or len(pcm) == 0:
            return None
        if pcm.ndim == 1:
            pcm = pcm.reshape(-1, 1)
        num_channels = min(pcm.shape[1], 2)
        result = np.zeros((num_segments, 2), dtype=np.float32)
        chunk_size = max(1, len(pcm) // num_segments)
        for ch in range(num_channels):
            for i in range(num_segments):
                start = i * chunk_size
                end = min(start + chunk_size, len(pcm))
                if end > start:
                    chunk = pcm[start:end, ch]
                    result[i, ch] = float(np.max(np.abs(chunk)))
        return result


class PhaseVectorScope:
    """相位矢量示波器 (Lissajous)"""

    def compute(self, pcm: "np.ndarray", num_points: int = 512) -> Optional["np.ndarray"]:
        """
        相位矢量 (L vs R)
        Returns: shape=(num_points, 2), values in [-1, 1]
        """
        if not HAS_NUMPY or pcm is None or len(pcm) == 0:
            return None
        if pcm.ndim < 2 or pcm.shape[1] < 2:
            return None
        # 取样本
        if len(pcm) > num_points:
            indices = np.linspace(0, len(pcm) - 1, num_points).astype(int)
            left = pcm[indices, 0]
            right = pcm[indices, 1]
        else:
            left = pcm[:, 0]
            right = pcm[:, 1]
        return np.stack([left, right], axis=1)


class AudioScopeManager:
    """音频示波器管理器 (单例)"""

    _instance: Optional["AudioScopeManager"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init = False
        return cls._instance

    def __init__(self):
        if self._init:
            return
        self._init = True
        self.waveform = WaveformScope()
        self.spectrum = SpectrumScope()
        self.loudness = LoudnessScope()
        self.peak_meter = PeakMeterScope()
        self.phase = PhaseVectorScope()

    def analyze(self, pcm: "np.ndarray", sample_rate: int = 44100) -> dict:
        """一次性计算所有示波器数据"""
        return {
            "waveform": self.waveform.compute(pcm),
            "spectrum": self.spectrum.compute(pcm, sample_rate),
            "loudness": self.loudness.compute(pcm, sample_rate),
            "peak_meter": self.peak_meter.compute(pcm),
            "phase": self.phase.compute(pcm),
        }


audio_scope_manager = AudioScopeManager()
