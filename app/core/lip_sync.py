"""
嘴型同步引擎 (Lip Sync Engine)
===============================
将音频波形映射为嘴型参数，支持多种输出格式。

功能:
  1. 音频特征提取 (RMS能量, MFCC, 频谱质心, 过零率)
  2. Viseme映射表 (12个基本嘴型 → 嘴部开合/宽度/圆度参数)
  3. ASR时间对齐 (Whisper segment → phoneme → viseme)
  4. 多输出模式: ARKit blendshapes / 2D卡通嘴型 / JSON关键帧
  5. 平滑插值 (确保动画自然流畅)

使用示例:
    >>> from app.core.lip_sync import LipSyncEngine
    >>> engine = LipSyncEngine()
    >>> params = engine.analyze_audio("speech.wav", use_asr=True)
    >>> # params: list[{time, jaw_open, mouth_width, lip_round, ...}]
    >>> engine.export_blendshapes(params, "output.json")
"""

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Union

import numpy as np

logger = logging.getLogger("AI短剧编辑器.lip_sync")


# ═══════════════════════════════════════════════════════════
# 数据结构定义
# ═══════════════════════════════════════════════════════════

@dataclass
class MouthParams:
    """单帧嘴型参数"""
    time: float                    # 时间戳 (秒)
    jaw_open: float = 0.0          # 下巴开合 (0.0-1.0)
    mouth_width: float = 0.0       # 嘴宽 (0.0-1.0)
    lip_round: float = 0.0         # 嘴唇圆度 (0.0-1.0)
    lip_pucker: float = 0.0        # 嘴唇撅起 (0.0-1.0)
    tongue_tip: float = 0.0        # 舌尖位置 (0.0-1.0)
    # 音量辅助
    rms_energy: float = 0.0        # RMS能量
    is_speaking: bool = False      # 是否在说话


@dataclass 
class VisemeConfig:
    """Viseme嘴型配置"""
    name: str
    jaw_open: float
    mouth_width: float
    lip_round: float
    lip_pucker: float
    tongue_tip: float = 0.0
    example_phonemes: List[str] = field(default_factory=list)
    description: str = ""


# ═══════════════════════════════════════════════════════════
# 12-Viseme 嘴型映射表 (基于中文拼音 + 英文IPA)
# ═══════════════════════════════════════════════════════════

VISEME_TABLE: Dict[str, VisemeConfig] = {
    # -------------------------------------------------------
    # 中文拼音12个基本嘴型，映射为5维参数
    #   jaw_open:    0=闭, 1=最大张开
    #   mouth_width: 0=窄, 1=最宽 (微笑状)
    #   lip_round:   0=不圆, 1=最圆 (O型)
    #   lip_pucker:  0=不噘, 1=最大嘟嘴
    #   tongue_tip:  0=低, 1=最高
    # -------------------------------------------------------
    "A": VisemeConfig("A/阿", 
        jaw_open=0.80, mouth_width=0.35, lip_round=0.15, lip_pucker=0.0,
        example_phonemes=["a", "aa", "ah", "ae"], 
        description="大开嘴 (元音a)"),
    "E": VisemeConfig("E/鹅", 
        jaw_open=0.40, mouth_width=0.45, lip_round=0.10, lip_pucker=0.0,
        example_phonemes=["e", "eh", "er"], 
        description="半开嘴 (元音e)"),
    "I": VisemeConfig("I/衣",
        jaw_open=0.20, mouth_width=0.70, lip_round=0.0, lip_pucker=0.0,
        example_phonemes=["i", "ih", "iy"], 
        description="宽扁嘴 (元音i)"),
    "O": VisemeConfig("O/哦",
        jaw_open=0.50, mouth_width=0.20, lip_round=0.80, lip_pucker=0.10,
        example_phonemes=["o", "ou", "ow"], 
        description="圆嘴 (元音o)"),
    "U": VisemeConfig("U/乌",
        jaw_open=0.15, mouth_width=0.10, lip_round=0.90, lip_pucker=0.50,
        example_phonemes=["u", "uu", "uw"], 
        description="嘟嘴 (元音u)"),
    "B": VisemeConfig("B/闭",
        jaw_open=0.0, mouth_width=0.50, lip_round=0.0, lip_pucker=0.0,
        example_phonemes=["b", "p", "m"], 
        description="双唇闭合"),
    "F": VisemeConfig("F/唇齿",
        jaw_open=0.05, mouth_width=0.40, lip_round=0.0, lip_pucker=0.0,
        example_phonemes=["f", "v"], 
        description="唇齿接触"),
    "TH": VisemeConfig("TH/舌齿",
        jaw_open=0.10, mouth_width=0.35, lip_round=0.0, lip_pucker=0.0,
        tongue_tip=0.70,
        example_phonemes=["th"], 
        description="舌尖齿间"),
    "D": VisemeConfig("D/齿龈",
        jaw_open=0.15, mouth_width=0.30, lip_round=0.0, lip_pucker=0.0,
        tongue_tip=0.60,
        example_phonemes=["d", "t", "n", "l", "z", "c", "s", "zh", "ch", "sh", "r"],
        description="舌尖上齿龈"),
    "G": VisemeConfig("G/软腭",
        jaw_open=0.25, mouth_width=0.35, lip_round=0.0, lip_pucker=0.0,
        tongue_tip=0.10,
        example_phonemes=["g", "k", "h", "ng"],
        description="舌根软腭"),
    "W": VisemeConfig("W/双唇圆",
        jaw_open=0.08, mouth_width=0.10, lip_round=0.85, lip_pucker=0.45,
        example_phonemes=["w"], 
        description="双唇收圆"),
    "REST": VisemeConfig("REST/静止",
        jaw_open=0.0, mouth_width=0.50, lip_round=0.0, lip_pucker=0.0,
        example_phonemes=["sil", "sp"],
        description="沉默/静止"),
    "Y": VisemeConfig("Y/半元音",
        jaw_open=0.30, mouth_width=0.60, lip_round=0.05, lip_pucker=0.0,
        example_phonemes=["y", "j"], 
        description="半元音过渡"),
}


# ═══════════════════════════════════════════════════════════
# 拼音到Viseme的快速映射表
# ═══════════════════════════════════════════════════════════

_PINYIN_INITIAL_TO_VISEME: Dict[str, str] = {
    "b": "B", "p": "B", "m": "B",
    "f": "F",
    "d": "D", "t": "D", "n": "D", "l": "D",
    "z": "D", "c": "D", "s": "D",
    "zh": "D", "ch": "D", "sh": "D", "r": "D",
    "j": "D", "q": "D", "x": "D",
    "g": "G", "k": "G", "h": "G",
    "w": "W", "y": "Y",
}

_PINYIN_FINAL_TO_VISEME: Dict[str, str] = {
    "a": "A", "ia": "A", "ua": "A",
    "o": "O", "uo": "O",
    "e": "E", "ie": "E", "ue": "E", "ve": "E",
    "i": "I", "ai": "I", "ei": "I", "ui": "I",
    "u": "U", "ou": "U", "iu": "U",
    "v": "U",
    "an": "A", "en": "E", "in": "I", "un": "U", "vn": "U",
    "ang": "A", "eng": "E", "ing": "I", "ong": "O",
    "er": "E",
}


# ═══════════════════════════════════════════════════════════
# 嘴型同步引擎核心类
# ═══════════════════════════════════════════════════════════

class LipSyncEngine:
    """嘴型同步引擎 - 音频波形 → 嘴型参数映射"""

    def __init__(self, fps: int = 25, smoothing_window: int = 3):
        """
        初始化引擎。

        Args:
            fps: 输出帧率 (默认25fps)
            smoothing_window: 平滑窗口大小 (帧数, 默认3帧)
        """
        self.fps = fps
        self.smoothing_window = smoothing_window
        self._asr_model = None

    # ─── 音频特征提取 ──────────────────────────────────

    def extract_audio_features(
        self,
        audio: np.ndarray,
        sample_rate: int,
        frame_size: int = 2048,
        hop_size: int = 512
    ) -> Dict[str, np.ndarray]:
        """
        从音频数据中提取多维度特征。

        Returns:
            dict with keys: rms, zcr, spectral_centroid, mfcc(13维)
        """
        if len(audio.shape) > 1:
            audio = audio.mean(axis=1)  # 转单声道

        n_frames = 1 + (len(audio) - frame_size) // hop_size
        if n_frames < 1:
            n_frames = 1

        rms = np.zeros(n_frames)
        zcr = np.zeros(n_frames)
        spectral_centroid = np.zeros(n_frames)

        for i in range(n_frames):
            start = i * hop_size
            end = start + frame_size
            frame = audio[start:end].astype(np.float64)

            # RMS能量
            rms[i] = np.sqrt(np.mean(frame ** 2))

            # 过零率
            zcr[i] = np.sum(np.abs(np.diff(np.sign(frame)))) / (2 * frame_size)

            # 频谱质心 (简化FFT计算)
            spectrum = np.abs(np.fft.rfft(frame * np.hanning(len(frame))))
            freqs = np.fft.rfftfreq(len(frame), 1.0 / sample_rate)
            if np.sum(spectrum) > 0:
                spectral_centroid[i] = np.sum(freqs * spectrum) / np.sum(spectrum)
            else:
                spectral_centroid[i] = 0

        # MFCC简化版 (13维)
        mfcc = self._compute_mfcc(audio, sample_rate, n_frames, frame_size, hop_size)

        return {
            "rms": rms,
            "zcr": zcr,
            "spectral_centroid": spectral_centroid,
            "mfcc": mfcc,
        }

    def _compute_mfcc(
        self,
        audio: np.ndarray,
        sample_rate: int,
        n_frames: int,
        frame_size: int,
        hop_size: int
    ) -> np.ndarray:
        """简化的MFCC计算 (13维)"""
        n_mfcc = 13
        n_mels = 40
        mfcc = np.zeros((n_frames, n_mfcc))

        # Mel滤波器组
        mel_filters = self._create_mel_filters(n_mels, frame_size, sample_rate)

        for i in range(n_frames):
            start = i * hop_size
            end = start + frame_size
            frame = audio[start:end].astype(np.float64)
            frame = frame * np.hanning(len(frame))

            # FFT
            spectrum = np.abs(np.fft.rfft(frame, frame_size))[:frame_size // 2 + 1]

            # Mel能量
            mel_energy = np.dot(mel_filters, spectrum)
            mel_energy = np.maximum(mel_energy, 1e-10)
            log_mel = np.log(mel_energy)

            # DCT → MFCC
            for k in range(n_mfcc):
                mfcc[i, k] = np.sum(
                    log_mel * np.cos(np.pi * k * (np.arange(n_mels) + 0.5) / n_mels)
                )

        return mfcc

    @staticmethod
    def _create_mel_filters(
        n_mels: int,
        fft_size: int,
        sample_rate: int
    ) -> np.ndarray:
        """创建Mel三角滤波器组"""
        mel_low = 2595 * math.log10(1 + 0 / 700)
        mel_high = 2595 * math.log10(1 + (sample_rate / 2) / 700)
        mel_points = np.linspace(mel_low, mel_high, n_mels + 2)
        hz_points = 700 * (10 ** (mel_points / 2595) - 1)
        bin_points = np.floor((fft_size + 1) * hz_points / sample_rate).astype(int)
        bin_points = np.clip(bin_points, 0, fft_size // 2)

        filters = np.zeros((n_mels, fft_size // 2 + 1))
        for m in range(1, n_mels + 1):
            f_m_minus = bin_points[m - 1]
            f_m = bin_points[m]
            f_m_plus = bin_points[m + 1]

            for k in range(f_m_minus, f_m):
                if f_m > f_m_minus:
                    filters[m - 1, k] = (k - f_m_minus) / (f_m - f_m_minus)
            for k in range(f_m, f_m_plus):
                if f_m_plus > f_m:
                    filters[m - 1, k] = (f_m_plus - k) / (f_m_plus - f_m)

        return filters

    # ─── 能量→嘴型参数映射 (无ASR模式) ──────────────────

    def energy_to_mouth_params(
        self,
        rms_energy: np.ndarray,
        audio_duration: float,
        silence_threshold: float = 0.05
    ) -> List[MouthParams]:
        """
        将RMS能量曲线映射为嘴型参数 (无ASR时使用)。

        基于音量变化驱动嘴部张合:
        - RMS高 → 嘴张大 (情绪激动/大声说话)
        - RMS低但高于静音阈值→ 嘴微张 (轻声说话)
        - RMS低于静音阈值 → 嘴闭合 (静音)
        - 频谱质心高 → 嘴角拉宽 (高音/i类音)
        """
        n_frames = int(audio_duration * self.fps)
        if n_frames == 0:
            return []

        # 重采样RMS到目标帧率
        rms_resampled = self._resample_1d(rms_energy, n_frames)

        # 归一化
        max_val = np.max(rms_resampled)
        if max_val > 0:
            rms_norm = rms_resampled / max_val
        else:
            rms_norm = np.zeros_like(rms_resampled)

        # 平滑
        rms_smooth = self._smooth_1d(rms_norm)

        params = []
        for i in range(n_frames):
            energy = rms_smooth[i]
            is_speaking = energy > silence_threshold

            if not is_speaking:
                params.append(MouthParams(
                    time=i / self.fps,
                    jaw_open=0.0, mouth_width=0.5,
                    lip_round=0.0, lip_pucker=0.0,
                    rms_energy=energy, is_speaking=False
                ))
            else:
                # jaw_open: 跟上能量非线性映射
                jaw_open = min(1.0, energy * 1.2 + 0.05)
                # mouth_width: 中等能量时最宽 (类似i音), 高能量时中等 (a音)
                mouth_width = 0.3 + energy * 0.3 + (1.0 - energy) * 0.2
                # lip_round: 与mouth_width相反
                lip_round = 0.1 + (1.0 - mouth_width) * 0.3

                params.append(MouthParams(
                    time=i / self.fps,
                    jaw_open=jaw_open,
                    mouth_width=mouth_width,
                    lip_round=lip_round,
                    lip_pucker=lip_round * 0.3,
                    rms_energy=energy,
                    is_speaking=True
                ))

        return params

    # ─── Viseme映射 (有ASR模式) ─────────────────────────

    def viseme_to_params(
        self,
        viseme_id: str,
        intensity: float = 1.0
    ) -> MouthParams:
        """将单个Viseme ID转换为MouthParams，支持强度调节"""
        config = VISEME_TABLE.get(viseme_id, VISEME_TABLE["REST"])
        return MouthParams(
            time=0.0,
            jaw_open=min(1.0, config.jaw_open * intensity),
            mouth_width=config.mouth_width,
            lip_round=config.lip_round,
            lip_pucker=config.lip_pucker,
            tongue_tip=config.tongue_tip,
            rms_energy=intensity,
            is_speaking=(viseme_id != "REST")
        )

    def phoneme_to_viseme(self, phoneme: str) -> str:
        """将音素映射到最近的Viseme ID"""
        # 直接从Viseme表反查
        for vid, config in VISEME_TABLE.items():
            if phoneme in config.example_phonemes:
                return vid

        # 拼音首字母映射
        if phoneme in _PINYIN_INITIAL_TO_VISEME:
            return _PINYIN_INITIAL_TO_VISEME[phoneme]

        # 拼音韵母映射
        if phoneme in _PINYIN_FINAL_TO_VISEME:
            return _PINYIN_FINAL_TO_VISEME[phoneme]

        # 子串匹配
        for pinyin, vid in _PINYIN_FINAL_TO_VISEME.items():
            if phoneme.endswith(pinyin):
                return vid
        for pinyin, vid in _PINYIN_INITIAL_TO_VISEME.items():
            if phoneme.startswith(pinyin):
                return vid

        return "REST"

    def asr_segments_to_params(
        self,
        segments: List[Dict],
        audio_duration: float,
        rms_energy: Optional[np.ndarray] = None
    ) -> List[MouthParams]:
        """
        将ASR时间片段转换为帧级嘴型参数。

        Args:
            segments: [{"start": 0.5, "end": 1.2, "text": "你好"}]
            audio_duration: 音频总时长
            rms_energy: 可选RMS能量曲线，用于强度调节

        Returns:
            帧级MouthParams列表
        """
        n_frames = int(audio_duration * self.fps)
        if n_frames == 0:
            return []

        params = [MouthParams(time=i / self.fps) for i in range(n_frames)]

        if not segments:
            return params

        # 重采样RMS
        rms_norm = None
        if rms_energy is not None:
            rms_resampled = self._resample_1d(rms_energy, n_frames)
            max_val = np.max(rms_resampled)
            if max_val > 0:
                rms_norm = rms_resampled / max_val

        for seg in segments:
            seg_start = seg.get("start", 0)
            seg_end = seg.get("end", audio_duration)
            text = seg.get("text", "")

            start_frame = int(seg_start * self.fps)
            end_frame = int(seg_end * self.fps)
            start_frame = max(0, min(start_frame, n_frames - 1))
            end_frame = max(start_frame + 1, min(end_frame, n_frames))

            n_seg_frames = end_frame - start_frame
            if n_seg_frames <= 0:
                continue

            # 将文本分解为拼音/音素序列
            phonemes = self._text_to_phonemes(text)
            n_phonemes = max(1, len(phonemes))

            for f_idx in range(start_frame, end_frame):
                rel_pos = (f_idx - start_frame) / n_seg_frames  # 0.0-1.0
                p_idx = min(n_phonemes - 1, int(rel_pos * n_phonemes))

                if p_idx < len(phonemes):
                    viseme = self.phoneme_to_viseme(phonemes[p_idx])
                else:
                    viseme = "REST"

                # 获取基础参数
                vp = self.viseme_to_params(viseme)

                # RMS能量调节强度
                intensity = 1.0
                if rms_norm is not None and f_idx < len(rms_norm):
                    energy = rms_norm[f_idx]
                    if energy < 0.05:
                        intensity = 0.0
                        viseme = "REST"
                    else:
                        intensity = min(1.5, energy * 2.0 + 0.3)

                vp = self.viseme_to_params(viseme, intensity)
                vp.time = f_idx / self.fps

                if rms_norm is not None and f_idx < len(rms_norm):
                    vp.rms_energy = float(rms_norm[f_idx])

                params[f_idx] = vp

        # 平滑过渡
        params = self._smooth_params(params)

        return params

    def _text_to_phonemes(self, text: str) -> List[str]:
        """将中文文本粗略分解为拼音音素列表"""
        phonemes = []
        try:
            # 2026-09-25 改走离线注音字典（app/core/ai/pinyin_dict），三个理由：
            #   ① 直接调 pypinyin 拿不到人工校订（古人名/地名/多音字），
            #      例：大宛 dà yuān、皋陶 gāo yáo、曹参 cáo shēn；
            #   ② 与 TTS 正音**同源** —— 避免「配音读 chóng、口型按 zhòng」
            #      的音画不一致（同一份词典同一次判定）；
            #   ③ 字典不可用时诚实降级到字符级兜底（行为与旧版一致）。
            from app.core.ai.pinyin_dict import annotate as _annotate

            res = _annotate(text, style="normal")
            if not res.get("ok"):
                raise RuntimeError(str(res.get("message") or "注音不可用"))
            # 只取「汉字 + 字典有读音」的项（等价旧实现 errors="ignore"）：
            # 英文/数字/标点**不进音素**，否则 'abc123' 会被当成一个音素
            # 传给下游 Viseme 查表（查不到 → 无效嘴型）。
            # 用 chars 详情过滤比「py != 原字符」可靠：lazy_pinyin 对纯英文串
            # 会整串返回，逐字比较识别不出来。
            pinyin_list = [
                str(c.get("pinyin"))
                for c in res.get("chars", [])
                if c.get("cjk") and c.get("known") and c.get("pinyin")
            ]
            for py in pinyin_list:
                # 拆分声母和韵母
                if py and len(py) >= 1:
                    if len(py) >= 2 and py[:2] in _PINYIN_INITIAL_TO_VISEME:
                        phonemes.append(py[:2])
                        phonemes.append(py[2:])
                    elif py[0] in _PINYIN_INITIAL_TO_VISEME:
                        phonemes.append(py[0])
                        phonemes.append(py[1:])
                    else:
                        phonemes.append(py)
        except Exception:
            # 注音字典 / pypinyin 不可用；或文本无有效汉字 → 字符级兜底
            for ch in text:
                if '\u4e00' <= ch <= '\u9fff' or '\u3400' <= ch <= '\u4dbf':
                    # 汉字→默认A类嘴型(张开)
                    phonemes.append("a")
                elif ch.isalpha():
                    phonemes.append(ch.lower())
                else:
                    phonemes.append("sil")

        if not phonemes:
            phonemes = ["a"]  # 兜底

        return phonemes

    # ─── 平滑处理 ──────────────────────────────────────

    def _smooth_params(self, params: List[MouthParams]) -> List[MouthParams]:
        """对嘴型参数进行时间轴平滑，消除抖动"""
        if len(params) <= self.smoothing_window:
            return params

        n = len(params)
        smoothed = []
        half_w = self.smoothing_window // 2

        fields_to_smooth = [
            "jaw_open", "mouth_width", "lip_round",
            "lip_pucker", "tongue_tip"
        ]

        for i in range(n):
            # 滑动窗口
            start = max(0, i - half_w)
            end = min(n, i + half_w + 1)
            window = params[start:end]
            w_size = len(window)

            # 检查窗口内是否有说话帧
            speaking_frames = [p for p in window if p.is_speaking]

            if not speaking_frames:
                # 全部静音 → 保持静止
                smoothed.append(MouthParams(
                    time=params[i].time,
                    jaw_open=0.0, mouth_width=0.5,
                    lip_round=0.0, lip_pucker=0.0,
                    rms_energy=params[i].rms_energy, is_speaking=False
                ))
            else:
                new_p = MouthParams(
                    time=params[i].time,
                    rms_energy=params[i].rms_energy,
                    is_speaking=params[i].is_speaking
                )
                for field in fields_to_smooth:
                    values = [getattr(p, field) for p in window]
                    setattr(new_p, field, float(np.mean(values)))

                smoothed.append(new_p)

        return smoothed

    @staticmethod
    def _smooth_1d(data: np.ndarray, window: int = 3) -> np.ndarray:
        """一维数据平滑"""
        if len(data) <= window:
            return data
        kernel = np.ones(window) / window
        return np.convolve(data, kernel, mode='same')

    @staticmethod
    def _resample_1d(data: np.ndarray, target_len: int) -> np.ndarray:
        """一维数据重采样到目标长度"""
        if len(data) == target_len:
            return data.astype(np.float64)
        x_old = np.linspace(0, 1, len(data))
        x_new = np.linspace(0, 1, target_len)
        return np.interp(x_new, x_old, data)

    # ─── 统一分析入口 ──────────────────────────────────

    def analyze_audio(
        self,
        audio_path: str,
        use_asr: bool = False,
        asr_language: str = "zh",
        asr_model_size: str = "base",
    ) -> List[MouthParams]:
        """
        分析音频文件，输出帧级嘴型参数。

        Args:
            audio_path: 音频文件路径
            use_asr: 是否使用Whisper ASR获取精确word-level时间对齐
            asr_language: ASR语言代码 ("zh" / "en" / "auto")
            asr_model_size: ASR模型大小 ("tiny"/"base"/"small"/"medium"/"large")

        Returns:
            List[MouthParams] 帧级嘴型参数
        """
        # 加载音频
        try:
            import soundfile as sf
            audio, sample_rate = sf.read(audio_path)
            if len(audio.shape) > 1:
                audio = audio.mean(axis=1)
        except (ImportError, Exception):
            logger.error(f"无法加载音频文件: {audio_path}")
            return []

        audio_duration = len(audio) / sample_rate
        logger.info(
            f"分析音频: {audio_path}, "
            f"时长={audio_duration:.1f}s, "
            f"采样率={sample_rate}Hz, "
            f"ASR={'开' if use_asr else '关'}"
        )

        # 提取音频特征
        features = self.extract_audio_features(audio, sample_rate)
        rms = features["rms"]

        if use_asr:
            # ASR模式
            segments = self._run_asr(audio_path, asr_language, asr_model_size)
            logger.info(f"ASR识别: {len(segments)} 个片段")
            return self.asr_segments_to_params(segments, audio_duration, rms)
        else:
            # 纯能量模式
            return self.energy_to_mouth_params(rms, audio_duration)

    def _run_asr(
        self,
        audio_path: str,
        language: str,
        model_size: str
    ) -> List[Dict]:
        """运行Whisper ASR，返回时间片段"""
        try:
            if self._asr_model is None:
                try:
                    from faster_whisper import WhisperModel
                    self._asr_model = WhisperModel(
                        model_size_or_path=model_size,
                        device="cpu",
                        compute_type="int8"
                    )
                except ImportError:
                    try:
                        import whisper
                        self._asr_model = whisper.load_model(model_size, device="cpu")
                        self._use_original_whisper = True
                    except ImportError:
                        logger.warning("ASR引擎不可用 (faster-whisper / whisper)")
                        return []
                else:
                    self._use_original_whisper = False

            if getattr(self, '_use_original_whisper', False):
                result = self._asr_model.transcribe(audio_path, language=language)
                return result.get("segments", [])
            else:
                segments_iter, _ = self._asr_model.transcribe(
                    audio_path, beam_size=5, language=language
                )
                return [
                    {"start": s.start, "end": s.end, "text": s.text}
                    for s in segments_iter
                ]
        except Exception as e:
            logger.warning(f"ASR失败: {e}")
            return []

    # ─── 输出导出 ──────────────────────────────────────

    def export_blendshapes(
        self,
        params: List[MouthParams],
        output_path: str,
        format: str = "json"
    ) -> bool:
        """
        导出为ARKit blendshapes JSON格式。

        输出格式:
        {
            "fps": 25,
            "duration": 10.0,
            "frames": [
                {
                    "time": 0.0,
                    "blendshapes": {
                        "jawOpen": 0.0,
                        "mouthWidth": 0.5,
                        "mouthPucker": 0.0,
                        ...
                    }
                },
                ...
            ]
        }
        """
        if not params:
            return False

        frames = []
        for p in params:
            frames.append({
                "time": round(p.time, 3),
                "blendshapes": {
                    "jawOpen": round(p.jaw_open, 3),
                    "mouthWidth": round(p.mouth_width, 3),
                    "mouthPucker": round(p.lip_pucker, 3),
                    "mouthRound": round(p.lip_round, 3),
                    "tongueTip": round(p.tongue_tip, 3),
                },
                "energy": round(p.rms_energy, 4),
                "isSpeaking": p.is_speaking,
            })

        output = {
            "fps": self.fps,
            "duration": round(params[-1].time, 3) if params else 0,
            "frame_count": len(frames),
            "frames": frames,
        }

        try:
            import json
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(output, f, ensure_ascii=False, indent=2)
            logger.info(f"Blendshapes导出成功: {output_path} ({len(frames)}帧)")
            return True
        except Exception as e:
            logger.error(f"导出失败: {e}")
            return False

    def export_keyframe_csv(
        self,
        params: List[MouthParams],
        output_path: str
    ) -> bool:
        """导出为CSV关键帧（兼容After Effects / Premiere）"""
        if not params:
            return False

        try:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write("time,jawOpen,mouthWidth,mouthPucker,mouthRound,energy\n")
                for p in params:
                    f.write(
                        f"{p.time:.3f},{p.jaw_open:.3f},{p.mouth_width:.3f},"
                        f"{p.lip_pucker:.3f},{p.lip_round:.3f},{p.rms_energy:.4f}\n"
                    )
            logger.info(f"CSV关键帧导出成功: {output_path}")
            return True
        except Exception as e:
            logger.error(f"CSV导出失败: {e}")
            return False

    @staticmethod
    def get_viseme_table_info() -> List[Dict]:
        """获取Viseme映射表信息（供UI展示）"""
        info = []
        for vid, config in VISEME_TABLE.items():
            info.append({
                "id": vid,
                "name": config.name,
                "description": config.description,
                "phonemes": config.example_phonemes,
                "params": {
                    "jaw_open": config.jaw_open,
                    "mouth_width": config.mouth_width,
                    "lip_round": config.lip_round,
                    "lip_pucker": config.lip_pucker,
                }
            })
        return info
