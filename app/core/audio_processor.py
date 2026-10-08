"""
专业音频处理引擎
提供BGM智能卡点、配音去口水音、声线变声、人声闪避等功能
"""

import numpy as np
from typing import Dict, List, Optional, Tuple, Callable
from dataclasses import dataclass, field
from enum import Enum
from threading import RLock
import os


import logging
logger = logging.getLogger("AI短剧编辑器.core.audio_processor")

class AudioEffectType(Enum):
    """音频效果类型"""
    BGM_BEAT = "bgm_beat"
    VOICE_CLEANUP = "voice_cleanup"
    VOICE_CHANGE = "voice_change"
    VOICE_DUCKING = "voice_ducking"
    NOISE_REDUCTION = "noise_reduction"
    VOLUME_NORMALIZATION = "volume_normalization"


@dataclass
class AudioSegment:
    """音频片段"""
    id: str
    start_time: float
    end_time: float
    audio_data: np.ndarray
    sample_rate: int
    volume: float = 1.0
    muted: bool = False
    solo: bool = False
    
    @property
    def duration(self) -> float:
        """片段时长"""
        return self.end_time - self.start_time
    
    @property
    def samples(self) -> int:
        """采样点数"""
        return int(self.duration * self.sample_rate)


@dataclass
class BeatPoint:
    """节拍点"""
    time: float
    intensity: float
    type: str = "beat"
    
    def to_dict(self) -> Dict:
        return {
            "time": self.time,
            "intensity": self.intensity,
            "type": self.type
        }


@dataclass
class VoiceProfile:
    """声线配置"""
    name: str
    pitch_shift: float = 0.0
    speed_factor: float = 1.0
    volume_adjust: float = 0.0
    eq_bands: Dict[str, float] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "pitch_shift": self.pitch_shift,
            "speed_factor": self.speed_factor,
            "volume_adjust": self.volume_adjust,
            "eq_bands": self.eq_bands
        }


class BGMBeatDetector:
    """BGM节拍检测器"""
    
    def __init__(self):
        self._beats: List[BeatPoint] = []
        self._lock = RLock()
    
    def detect_beats(self, audio_data: np.ndarray, 
                    sample_rate: int,
                    progress_callback: Optional[Callable[[int, str], None]] = None) -> List[BeatPoint]:
        """检测节拍点"""
        if progress_callback:
            progress_callback(0, "开始检测节拍...")
        
        with self._lock:
            try:
                # 简化的节拍检测算法
                # 实际应用中应使用更专业的音频分析库
                
                if progress_callback:
                    progress_callback(20, "计算能量包络...")
                
                # 计算音频能量
                frame_size = 1024
                hop_size = 512
                energy = []
                
                for i in range(0, len(audio_data) - frame_size, hop_size):
                    frame = audio_data[i:i + frame_size]
                    energy.append(np.sum(np.abs(frame)))
                
                if progress_callback:
                    progress_callback(40, "检测峰值...")
                
                # 检测能量峰值
                energy = np.array(energy)
                threshold = np.mean(energy) + np.std(energy)
                peaks = np.where(energy > threshold)[0]
                
                if progress_callback:
                    progress_callback(60, "过滤节拍点...")
                
                # 过滤节拍点（去除过于密集的点）
                min_interval = int(sample_rate * 0.3)  # 最小间隔0.3秒
                filtered_peaks = []
                last_peak = -min_interval * 2
                
                for peak in peaks:
                    if peak - last_peak >= min_interval:
                        filtered_peaks.append(peak)
                        last_peak = peak
                
                if progress_callback:
                    progress_callback(80, "生成节拍点...")
                
                # 生成节拍点
                self._beats = []
                for peak in filtered_peaks:
                    time = (peak * hop_size) / sample_rate
                    intensity = energy[peak] / np.max(energy)
                    self._beats.append(BeatPoint(time=time, intensity=intensity))
                
                if progress_callback:
                    progress_callback(100, "节拍检测完成")
                
                return self._beats
                
            except Exception as e:
                logger.error(f'节拍检测失败: {e}')
                return []
    
    def get_beats(self) -> List[BeatPoint]:
        """获取节拍点"""
        return self._beats.copy()
    
    def get_beat_times(self) -> List[float]:
        """获取节拍时间列表"""
        return [beat.time for beat in self._beats]
    
    def clear_beats(self):
        """清除节拍点"""
        with self._lock:
            self._beats.clear()


class VoiceCleanup:
    """配音去口水音"""
    
    def __init__(self):
        self._lock = RLock()
    
    def remove_mouth_sounds(self, audio_data: np.ndarray,
                          sample_rate: int,
                          progress_callback: Optional[Callable[[int, str], None]] = None) -> np.ndarray:
        """去除口水音"""
        if progress_callback:
            progress_callback(0, "开始去除口水音...")
        
        with self._lock:
            try:
                result = audio_data.copy()
                
                if progress_callback:
                    progress_callback(20, "检测静音段...")
                
                # 检测静音段
                frame_size = 1024
                hop_size = 512
                energy = []
                
                for i in range(0, len(audio_data) - frame_size, hop_size):
                    frame = audio_data[i:i + frame_size]
                    energy.append(np.sum(np.abs(frame)))
                
                energy = np.array(energy)
                threshold = np.mean(energy) * 0.1  # 静音阈值
                
                if progress_callback:
                    progress_callback(40, "标记口水音...")
                
                # 标记可能的口水音（短促的低能量段）
                mouth_sounds = []
                for i in range(1, len(energy) - 1):
                    if (energy[i] > threshold and 
                        energy[i] > energy[i-1] * 2 and 
                        energy[i] > energy[i+1] * 2 and
                        energy[i] < np.mean(energy) * 0.5):
                        mouth_sounds.append(i)
                
                if progress_callback:
                    progress_callback(60, "应用降噪...")
                
                # 应用降噪
                for i in mouth_sounds:
                    start = i * hop_size
                    end = min(start + frame_size, len(result))
                    # 简单的平滑处理
                    if start > 0 and end < len(result):
                        result[start:end] = (result[start-1] + result[end+1]) / 2
                
                if progress_callback:
                    progress_callback(100, "口水音去除完成")
                
                return result
                
            except Exception as e:
                logger.error(f'去除口水音失败: {e}')
                return audio_data


class VoiceChanger:
    """声线变声"""
    
    def __init__(self):
        self._profiles: Dict[str, VoiceProfile] = {}
        self._lock = RLock()
        self._initialize_default_profiles()
    
    def _initialize_default_profiles(self):
        """初始化默认声线配置"""
        self._profiles = {
            "male_deep": VoiceProfile(
                name="男声深沉",
                pitch_shift=-2.0,
                speed_factor=0.95,
                volume_adjust=0.1,
                eq_bands={"low": 1.2, "mid": 0.9, "high": 0.8}
            ),
            "male_normal": VoiceProfile(
                name="男声正常",
                pitch_shift=0.0,
                speed_factor=1.0,
                volume_adjust=0.0,
                eq_bands={"low": 1.0, "mid": 1.0, "high": 1.0}
            ),
            "female_sweet": VoiceProfile(
                name="女声甜美",
                pitch_shift=3.0,
                speed_factor=1.05,
                volume_adjust=-0.05,
                eq_bands={"low": 0.8, "mid": 1.1, "high": 1.2}
            ),
            "female_mature": VoiceProfile(
                name="女声成熟",
                pitch_shift=1.0,
                speed_factor=1.0,
                volume_adjust=0.0,
                eq_bands={"low": 0.9, "mid": 1.0, "high": 1.1}
            ),
            "child_cute": VoiceProfile(
                name="童声可爱",
                pitch_shift=5.0,
                speed_factor=1.1,
                volume_adjust=0.1,
                eq_bands={"low": 0.7, "mid": 1.2, "high": 1.3}
            )
        }
    
    def apply_voice_change(self, audio_data: np.ndarray,
                        sample_rate: int,
                        profile_name: str,
                        progress_callback: Optional[Callable[[int, str], None]] = None) -> np.ndarray:
        """应用声线变声"""
        if progress_callback:
            progress_callback(0, f"应用声线变声: {profile_name}")
        
        with self._lock:
            try:
                profile = self._profiles.get(profile_name)
                if not profile:
                    logger.info(f'声线配置不存在: {profile_name}')
                    return audio_data

                # 2026-10-09 修（UnboundLocalError 静默吞掉）：
                # 原来 `from scipy import signal` 只写在 pitch 分支**里面**，而
                # speed 分支也引用 signal ⇒ pitch_shift==0 但 speed_factor!=1 时
                # 抛 UnboundLocalError，被外层 except 吞掉后**原样返回入参**
                # —— 用户以为变速生效了，其实什么都没发生，且没有任何日志级别
                # 的提示。现把 import 提到方法开头，一次绑定、两处共用。
                try:
                    from scipy import signal
                except ImportError:
                    signal = None

                result = audio_data.copy().astype(np.float64)

                if progress_callback:
                    progress_callback(20, "调整音高...")

                # 简化的音高调整（实际应使用更专业的算法）
                if profile.pitch_shift != 0 and signal is not None:
                    # 使用重采样实现简单的音高调整
                    new_sample_rate = int(sample_rate * (1 + profile.pitch_shift / 12))
                    result = signal.resample(result, int(len(result) * new_sample_rate / sample_rate))

                if progress_callback:
                    progress_callback(40, "调整速度...")

                # 调整速度
                if profile.speed_factor != 1.0:
                    if signal is None:
                        logger.warning("[AudioProcessor] 缺 scipy ⇒ 变速被跳过（profile=%s）",
                                       profile_name)
                    else:
                        new_length = max(1, int(len(result) / profile.speed_factor))
                        result = signal.resample(result, new_length)
                
                if progress_callback:
                    progress_callback(60, "调整音量...")
                
                # 调整音量
                if profile.volume_adjust != 0:
                    result = result * (1 + profile.volume_adjust)
                
                if progress_callback:
                    progress_callback(80, "应用EQ...")
                
                # 应用EQ
                if profile.eq_bands:
                    # 简化的EQ处理
                    if "low" in profile.eq_bands:
                        low_freq = profile.eq_bands["low"]
                        result = self._apply_band_eq(result, sample_rate, 100, 300, low_freq)
                    
                    if "mid" in profile.eq_bands:
                        mid_freq = profile.eq_bands["mid"]
                        result = self._apply_band_eq(result, sample_rate, 300, 3000, mid_freq)
                    
                    if "high" in profile.eq_bands:
                        high_freq = profile.eq_bands["high"]
                        result = self._apply_band_eq(result, sample_rate, 3000, 20000, high_freq)
                
                if progress_callback:
                    progress_callback(100, "声线变声完成")
                
                return np.clip(result, -1.0, 1.0).astype(np.float32)
                
            except Exception as e:
                logger.error(f'声线变声失败: {e}')
                return audio_data
    
    def _apply_band_eq(self, audio_data: np.ndarray, sample_rate: int,
                     low_freq: int, high_freq: int, gain: float) -> np.ndarray:
        """应用频段 EQ。

        2026-10-09 修（默认声线整体静默失效）：
            原来直接把 `high_freq / nyquist` 当归一化截止频率，而调用方给
            "high" 频段写死了 20000Hz。对 nyquist=11025 的 22050Hz 音频，
            high = 20000/11025 ≈ 1.81 > 1 ⇒ scipy.butter 抛 ValueError
            「Digital filter critical frequencies must be 0 < Wn < 1」；
            而这里只捕获 ImportError，ValueError 冒泡到 apply_voice_change 的
            except 被吞掉 ⇒ **原样返回入参**。因为 5 个内置声线的 eq_bands 都含
            "high"，等于**整个变声功能对默认声线全部无效**，且没有任何提示。
        修法：把频点夹进 (0, nyquist) 的开区间（留 1% 余量），
            频段非法就不做 EQ 而不是抛；同时补上 ValueError 兜底。
        """
        try:
            from scipy import signal
            nyquist = sample_rate / 2.0
            # 归一化到 (0, 1) 开区间：留 1% 余量，避免恰好在 nyquist 上被拒
            low = max(1e-4, min(low_freq / nyquist, 0.99))
            high = min(high_freq / nyquist, 0.99)
            if low >= high:
                logger.debug("[AudioProcessor] EQ 频段非法（%s-%s @ %sHz），跳过",
                             low_freq, high_freq, sample_rate)
                return audio_data
            b, a = signal.butter(2, [low, high], btype='band')
            filtered = signal.filtfilt(b, a, audio_data)
            return audio_data * (1 - gain * 0.5) + filtered * gain * 0.5
        except ImportError:
            return audio_data
        except ValueError as e:
            # 频段/参数异常不该把整条变声链带崩（旧行为正是这样静默失效的）
            logger.warning("[AudioProcessor] EQ 滤波参数非法，跳过该频段: %s", e)
            return audio_data
    
    def get_profiles(self) -> List[VoiceProfile]:
        """获取所有声线配置"""
        return list(self._profiles.values())
    
    def get_profile(self, name: str) -> Optional[VoiceProfile]:
        """获取声线配置"""
        return self._profiles.get(name)
    
    def add_profile(self, profile: VoiceProfile):
        """添加声线配置"""
        with self._lock:
            self._profiles[profile.name] = profile
    
    def remove_profile(self, name: str) -> bool:
        """移除声线配置"""
        with self._lock:
            if name in self._profiles:
                del self._profiles[name]
                return True
            return False


class VoiceDucking:
    """人声闪避"""
    
    def __init__(self):
        self._lock = RLock()
    
    def apply_ducking(self, voice_audio: np.ndarray,
                    bgm_audio: np.ndarray,
                    sample_rate: int,
                    ducking_amount: float = 0.7,
                    attack_time: float = 0.1,
                    release_time: float = 0.5,
                    progress_callback: Optional[Callable[[int, str], None]] = None) -> Tuple[np.ndarray, np.ndarray]:
        """应用人声闪避"""
        if progress_callback:
            progress_callback(0, "开始人声闪避...")
        
        with self._lock:
            try:
                # 确保音频长度一致
                min_length = min(len(voice_audio), len(bgm_audio))
                voice = voice_audio[:min_length]
                bgm = bgm_audio[:min_length]
                
                if progress_callback:
                    progress_callback(20, "分析人声能量...")
                
                # 分析人声能量
                frame_size = 1024
                hop_size = 512
                voice_energy = []
                
                for i in range(0, len(voice) - frame_size, hop_size):
                    frame = voice[i:i + frame_size]
                    voice_energy.append(np.sum(np.abs(frame)))
                
                voice_energy = np.array(voice_energy)
                
                if progress_callback:
                    progress_callback(40, "计算闪避增益...")
                
                # 计算闪避增益
                ducking_gain = np.ones_like(voice_energy)
                attack_samples = int(attack_time * sample_rate / hop_size)
                release_samples = int(release_time * sample_rate / hop_size)
                
                for i in range(len(voice_energy)):
                    if voice_energy[i] > np.mean(voice_energy):
                        # 人声存在，降低BGM
                        target_gain = 1.0 - ducking_amount
                        ducking_gain[i] = ducking_gain[i-1] * 0.9 + target_gain * 0.1
                    else:
                        # 人声不存在，恢复BGM
                        target_gain = 1.0
                        ducking_gain[i] = ducking_gain[i-1] * 0.95 + target_gain * 0.05
                
                if progress_callback:
                    progress_callback(60, "应用闪避到BGM...")
                
                # 应用闪避到BGM
                ducked_bgm = bgm.copy()
                for i in range(len(ducking_gain)):
                    start = i * hop_size
                    end = min(start + hop_size, len(ducked_bgm))
                    ducked_bgm[start:end] *= ducking_gain[i]
                
                if progress_callback:
                    progress_callback(100, "人声闪避完成")
                
                return voice, ducked_bgm
                
            except Exception as e:
                logger.error(f'人声闪避失败: {e}')
                return voice_audio, bgm_audio


class AudioProcessor:
    """音频处理器（整合所有音频处理功能）"""
    
    def __init__(self):
        self._beat_detector = BGMBeatDetector()
        self._voice_cleanup = VoiceCleanup()
        self._voice_changer = VoiceChanger()
        self._voice_ducking = VoiceDucking()
        self._lock = RLock()
    
    def detect_bgm_beats(self, audio_data: np.ndarray,
                         sample_rate: int,
                         progress_callback: Optional[Callable[[int, str], None]] = None) -> List[BeatPoint]:
        """检测BGM节拍"""
        return self._beat_detector.detect_beats(audio_data, sample_rate, progress_callback)
    
    def remove_mouth_sounds(self, audio_data: np.ndarray,
                          sample_rate: int,
                          progress_callback: Optional[Callable[[int, str], None]] = None) -> np.ndarray:
        """去除口水音"""
        return self._voice_cleanup.remove_mouth_sounds(audio_data, sample_rate, progress_callback)
    
    def apply_voice_change(self, audio_data: np.ndarray,
                        sample_rate: int,
                        profile_name: str,
                        progress_callback: Optional[Callable[[int, str], None]] = None) -> np.ndarray:
        """应用声线变声"""
        return self._voice_changer.apply_voice_change(audio_data, sample_rate, profile_name, progress_callback)
    
    def apply_voice_ducking(self, voice_audio: np.ndarray,
                          bgm_audio: np.ndarray,
                          sample_rate: int,
                          ducking_amount: float = 0.7,
                          progress_callback: Optional[Callable[[int, str], None]] = None) -> Tuple[np.ndarray, np.ndarray]:
        """应用人声闪避"""
        return self._voice_ducking.apply_ducking(voice_audio, bgm_audio, sample_rate, 
                                            ducking_amount, 0.1, 0.5, progress_callback)
    
    def get_voice_profiles(self) -> List[VoiceProfile]:
        """获取所有声线配置"""
        return self._voice_changer.get_profiles()
    
    def get_beat_points(self) -> List[BeatPoint]:
        """获取节拍点"""
        return self._beat_detector.get_beats()
    
    def clear_beats(self):
        """清除节拍点"""
        self._beat_detector.clear_beats()

    def denoise(self, audio: np.ndarray, sample_rate: int) -> np.ndarray:
        """专业降噪 - 优先使用noisereduce频谱减法，回退到SciPy滤波"""
        try:
            import noisereduce as nr
            return nr.reduce_noise(y=audio, sr=sample_rate, stationary=True, prop_decrease=0.85)
        except ImportError:
            try:
                from scipy.signal import butter, sosfilt
                sos = butter(8, 80, btype='high', fs=sample_rate, output='sos')
                return sosfilt(sos, audio)
            except ImportError:
                return audio

    def compressor(self, audio: np.ndarray, sample_rate: int,
                   threshold_db: float = -20, ratio: float = 4.0,
                   attack_ms: float = 5, release_ms: float = 50,
                   makeup_db: float = 0) -> np.ndarray:
        """音量压缩器"""
        try:
            from pedalboard import Compressor
            c = Compressor(threshold_db=threshold_db, ratio=ratio)
            return c(audio, sample_rate)
        except ImportError:
            return audio

    def eq_equalizer(self, audio: np.ndarray, sample_rate: int,
                     gains_db: list = None) -> np.ndarray:
        """10段图形均衡器 - 使用pedalboard或scipy"""
        if gains_db is None:
            bands = [32, 64, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]
            gains_db = [0] * 10
        try:
            from scipy.signal import butter, sosfilt
            output = np.zeros_like(audio)
            for i, (freq, gain) in enumerate(zip(
                    [32, 64, 125, 250, 500, 1000, 2000, 4000, 8000, 16000],
                    gains_db)):
                if gain == 0:
                    continue
                bw = freq * 0.5 if i < 9 else freq * 0.3
                low = max(20, freq - bw) / (sample_rate / 2)
                high = min(freq + bw, sample_rate / 2 - 1) / (sample_rate / 2)
                sos = butter(4, [low, high], btype='band', output='sos')
                output += sosfilt(sos, audio) * (10 ** (gain / 20) - 1)
            return audio + output
        except ImportError:
            return audio

    def loudness_normalize(self, audio: np.ndarray, sample_rate: int,
                           target_lufs: float = -16.0) -> np.ndarray:
        """LUFS响度归一化"""
        try:
            import pyloudnorm as pyln
            meter = pyln.Meter(sample_rate)
            current_lufs = meter.integrated_loudness(audio)
            return pyln.normalize.loudness(audio, current_lufs, target_lufs)
        except ImportError:
            peak = max(abs(audio))
            return audio / max(peak, 1e-10) * 0.9 if peak > 0 else audio

    def add_reverb(self, audio: np.ndarray, sample_rate: int,
                   room_size: float = 0.5) -> np.ndarray:
        """混响效果"""
        try:
            from pedalboard import Reverb
            return Reverb(room_size=room_size)(audio, sample_rate)
        except ImportError:
            return audio
