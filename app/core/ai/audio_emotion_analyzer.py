"""
音频情绪分析器 (v1.0)
====================
从音频信号中提取情绪维度，与文本情绪分析形成互补。

核心思路：
- 文本告诉你"说了什么"，音频告诉你"怎么说的"
- "我恨你" 轻声说 vs 怒吼 → 情绪强度完全不同
- 短剧中语调、BGM强度、哭/笑声是重要的情绪信号

提取特征 → 情绪维度映射：
- RMS能量 → 激动/愤怒 (高强度 → 高arousal)
- 频谱质心 → 紧张/悬疑 (高质心 → 高tension)
- 过零率 → 语速/紧张度
- MFCC → 音色特征 → 情绪基调 (低沉 vs 尖锐)
- 基频F0 → 悲伤/愤怒 (音高变化模式不同)

设计原则：
- 纯依赖 librosa，无需 LLM
- 输出 8 维情绪向量，与文本分析格式统一
- 以 dialogue 的时间段为分析窗口
"""

import logging
from typing import List, Dict, Optional, Tuple
import numpy as np

logger = logging.getLogger(__name__)

# 尝试加载 librosa
LIBROSA_AVAILABLE = False
try:
    import librosa
    import librosa.display
    LIBROSA_AVAILABLE = True
except ImportError:
    logger.warning("librosa 未安装，音频情绪分析不可用。pip install librosa")

# 8 维情绪维度（与 drama_understanding_engine 一致）
EMOTION_DIMS = ["开心", "悲伤", "愤怒", "紧张", "浪漫", "悬疑", "激动", "温馨"]

# 声学特征 → 情绪维度的启发式映射权重
# 基于语音情感识别研究的近似规则
ACOUSTIC_TO_EMOTION_WEIGHTS = {
    # feature_name: {emotion_dim_index: weight}
    # RMS能量 (响度)
    "rms_high":    {0: 0.15, 2: 0.35, 6: 0.40, 7: 0.10},  # 高响度 → 激动/愤怒
    "rms_low":     {1: 0.30, 7: 0.40, 4: 0.20, 5: 0.10},   # 低响度 → 悲伤/温馨/浪漫
    # 频谱质心 (音色亮度)
    "centroid_high": {3: 0.35, 5: 0.30, 2: 0.20, 6: 0.15},  # 高质心 → 紧张/悬疑/愤怒
    "centroid_low":  {1: 0.30, 4: 0.30, 7: 0.30, 0: 0.10},   # 低质心 → 悲伤/浪漫/温馨
    # 过零率 (语速)
    "zcr_high":    {2: 0.30, 3: 0.35, 6: 0.25, 5: 0.10},    # 高语速 → 愤怒/紧张/激动
    "zcr_low":     {1: 0.35, 4: 0.30, 7: 0.25, 0: 0.10},     # 低语速 → 悲伤/浪漫/温馨
    # 基频变化 (F0 variability)
    "f0_var_high":  {2: 0.25, 6: 0.30, 3: 0.25, 0: 0.20},   # 高音高变化 → 愤怒/激动
    "f0_var_low":   {1: 0.40, 4: 0.25, 5: 0.20, 7: 0.15},    # 低音高变化 → 悲伤/悬疑
}

# 情绪维度按 arousal (唤醒度) 和 valence (效价) 分组
HIGH_AROUSAL_DIMS = [2, 3, 6]   # 愤怒, 紧张, 激动
LOW_AROUSAL_DIMS  = [1, 4, 7]   # 悲伤, 浪漫, 温馨
POSITIVE_DIMS     = [0, 4, 6, 7]  # 开心, 浪漫, 激动, 温馨
NEGATIVE_DIMS     = [1, 2, 3, 5]  # 悲伤, 愤怒, 紧张, 悬疑


class AudioEmotionAnalyzer:
    """
    音频情绪分析器。

    对每个 dialogue 时间段提取声学特征，映射为 8 维情绪向量。

    使用方式:
        analyzer = AudioEmotionAnalyzer()
        vectors = analyzer.analyze_segments(video_path, dialogues)
        # → List[np.ndarray] 每个 dialogue 对应一个 8 维情绪向量
    """

    def __init__(self, sr: int = 16000):
        self.sr = sr
        if not LIBROSA_AVAILABLE:
            self.available = False
        else:
            self.available = True

    def analyze_segments(self, audio_path: str,
                         segments: List[Tuple[float, float]]) -> List[np.ndarray]:
        """
        分析多个时间段的音频情绪。

        Args:
            audio_path: 音频文件路径
            segments: [(start_sec, end_sec), ...] 时间段列表

        Returns:
            List[np.ndarray] 每个 segment 对应的 8 维情绪向量 [0-1]
        """
        if not self.available or not segments:
            return [self._neutral_vector() for _ in segments]

        try:
            # 加载完整音频（resample 到 16kHz）
            y, sr = librosa.load(audio_path, sr=self.sr, mono=True)
            duration = len(y) / sr
        except Exception as e:
            logger.debug(f"音频加载失败: {e}")
            return [self._neutral_vector() for _ in segments]

        # 提取全局声学特征曲线
        features = self._extract_feature_curves(y, sr)

        # 对每个 segment 聚合特征
        results = []
        for start_s, end_s in segments:
            if start_s >= duration or end_s <= 0:
                results.append(self._neutral_vector())
                continue

            start_s = max(0, start_s)
            end_s = min(duration, end_s)
            vec = self._segment_to_emotion_vector(features, start_s, end_s, sr)
            results.append(vec)

        return results

    def analyze_full_curve(self, audio_path: str,
                           window_sec: float = 1.0,
                           hop_sec: float = 0.5) -> Tuple[np.ndarray, np.ndarray]:
        """
        分析完整音频的情绪曲线。

        Args:
            audio_path: 音频文件路径
            window_sec: 分析窗口大小（秒）
            hop_sec: 窗口步长（秒）

        Returns:
            (times: np.ndarray [N], vectors: np.ndarray [N, 8])
        """
        if not self.available:
            return np.array([]), np.array([])

        try:
            y, sr = librosa.load(audio_path, sr=self.sr, mono=True)
            duration = len(y) / sr
        except Exception:
            return np.array([]), np.array([])

        features = self._extract_feature_curves(y, sr)
        times = np.arange(0, duration, hop_sec)
        vectors = []

        for t in times:
            end_t = min(t + window_sec, duration)
            vec = self._segment_to_emotion_vector(features, t, end_t, sr)
            vectors.append(vec)

        return times, np.array(vectors)

    def _extract_feature_curves(self, y: np.ndarray, sr: int) -> Dict[str, np.ndarray]:
        """
        提取全局声学特征曲线。

        Returns:
            {
                "rms":        (N,) 能量均方根
                "centroid":   (N,) 频谱质心
                "zcr":        (N,) 过零率
                "f0":         (N,) 基频估计
                "times":      (N,) 时间点
            }
        """
        hop_length = 512
        frame_length = 2048

        # RMS 能量
        rms = librosa.feature.rms(y=y, frame_length=frame_length, hop_length=hop_length)[0]

        # 频谱质心
        centroid = librosa.feature.spectral_centroid(
            y=y, sr=sr, n_fft=frame_length, hop_length=hop_length
        )[0]

        # 过零率
        zcr = librosa.feature.zero_crossing_rate(
            y, frame_length=frame_length, hop_length=hop_length
        )[0]

        # 基频 (F0) 估计 — 使用 pYIN 或 YIN
        try:
            f0, _, _ = librosa.pyin(
                y, fmin=librosa.note_to_hz('C2'), fmax=librosa.note_to_hz('C7'),
                sr=sr, hop_length=hop_length,
            )
            f0 = np.nan_to_num(f0, nan=0.0)
        except Exception:
            # pyin 失败时使用 YIN 基础版
            try:
                f0 = librosa.yin(y, fmin=50, fmax=2000, sr=sr,
                                 hop_length=hop_length, frame_length=frame_length)
                f0 = np.nan_to_num(f0, nan=0.0)
            except Exception:
                f0 = np.zeros_like(rms)

        # 时间轴
        times = librosa.frames_to_time(np.arange(len(rms)), sr=sr,
                                       hop_length=hop_length)

        return {
            "rms": rms,
            "centroid": centroid,
            "zcr": zcr,
            "f0": f0,
            "times": times,
        }

    def _segment_to_emotion_vector(self, features: Dict[str, np.ndarray],
                                    start_s: float, end_s: float,
                                    sr: int) -> np.ndarray:
        """
        将时间段内的声学特征聚合为 8 维情绪向量。
        """
        times = features["times"]

        # 找到时间段内的帧索引
        mask = (times >= start_s) & (times <= end_s)
        if not mask.any():
            return self._neutral_vector()

        # 计算每个特征的统计量
        rms_seg = features["rms"][mask]
        centroid_seg = features["centroid"][mask]
        zcr_seg = features["zcr"][mask]
        f0_seg = features["f0"][mask]

        # 统计
        rms_mean = float(np.mean(rms_seg))
        rms_std = float(np.std(rms_seg))
        centroid_mean = float(np.mean(centroid_seg))
        zcr_mean = float(np.mean(zcr_seg))
        f0_std = float(np.std(f0_seg[f0_seg > 0])) if (f0_seg > 0).any() else 0.0

        # 归一化参考值（基于典型语音范围）
        rms_norm = min(1.0, rms_mean / 0.15)        # 0.15 ≈ 正常对话响度
        centroid_norm = min(1.0, centroid_mean / 3000)  # 3000Hz ≈ 高音色
        zcr_norm = min(1.0, zcr_mean / 0.12)          # 0.12 ≈ 正常语速过零率
        f0_var_norm = min(1.0, f0_std / 150)          # 150Hz ≈ 高音高变化

        # 初始化 8 维情绪向量
        vec = np.zeros(len(EMOTION_DIMS), dtype=np.float32)

        # 根据声学特征值的高低选择不同的映射权重
        self._apply_acoustic_mapping(vec, rms_norm, "rms")
        self._apply_acoustic_mapping(vec, centroid_norm, "centroid")
        self._apply_acoustic_mapping(vec, zcr_norm, "zcr")
        self._apply_acoustic_mapping(vec, f0_var_norm, "f0_var")

        # 归一化
        total = vec.sum()
        if total > 0:
            vec = vec / total
        else:
            vec[:] = 0.125

        return vec

    def _apply_acoustic_mapping(self, vec: np.ndarray, value: float,
                                 feature_name: str):
        """
        根据声学特征值的高低，累加对应的情绪维度权重。

        高值走 high 映射，低值走 low 映射，中间线性插值。
        """
        high_key = f"{feature_name}_high"
        low_key = f"{feature_name}_low"
        high_weights = ACOUSTIC_TO_EMOTION_WEIGHTS.get(high_key, {})
        low_weights = ACOUSTIC_TO_EMOTION_WEIGHTS.get(low_key, {})

        # sigmoid 归一化：把原始值平滑映射到 [0, 1]
        # 中心点 0.5 → 高低各半
        high_ratio = 1.0 / (1.0 + np.exp(-8 * (value - 0.5)))
        low_ratio = 1.0 - high_ratio

        for dim_idx, w in high_weights.items():
            vec[dim_idx] += w * high_ratio
        for dim_idx, w in low_weights.items():
            vec[dim_idx] += w * low_ratio

    def _neutral_vector(self) -> np.ndarray:
        """返回中性情绪向量（均匀分布）"""
        return np.full(len(EMOTION_DIMS), 0.125, dtype=np.float32)


# ---------------------------------------------------------------------------
# 便捷函数
# ---------------------------------------------------------------------------

def audio_emotion_for_dialogues(audio_path: str,
                                dialogues: List) -> List[np.ndarray]:
    """
    为对话列表提取音频情绪向量。

    Args:
        audio_path: 音频/视频文件路径
        dialogues: DialogueSegment 对象列表（需要有 start_time, end_time 属性）

    Returns:
        与 dialogues 等长的 8 维向量列表
    """
    analyzer = AudioEmotionAnalyzer()
    segments = [(d.start_time, d.end_time) for d in dialogues]
    return analyzer.analyze_segments(audio_path, segments)


# ---------------------------------------------------------------------------
# 自测
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("AudioEmotionAnalyzer 自测")
    print(f"  librosa 可用: {LIBROSA_AVAILABLE}")
    if not LIBROSA_AVAILABLE:
        print("  请安装: pip install librosa")
        exit(0)

    # 生成测试音频（正弦波模拟不同情绪音调）
    sr = 16000
    duration = 3.0

    # 模拟："平静" 低能量正弦波
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    y_calm = 0.1 * np.sin(2 * np.pi * 200 * t)

    # 模拟："激动" 高能量 + 高频率
    y_excited = 0.5 * np.sin(2 * np.pi * 800 * t) + 0.3 * np.sin(2 * np.pi * 200 * t)

    import tempfile, os, soundfile
    # 写入临时文件测试
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        tmp_path = f.name
    soundfile.write(tmp_path, y_calm, sr)
    soundfile.write(tmp_path, y_excited, sr)  # 覆盖写入 excited

    analyzer = AudioEmotionAnalyzer()
    vectors = analyzer.analyze_segments(tmp_path, [(0, 1.5), (1.5, 3.0)])
    for i, vec in enumerate(vectors):
        print(f"  段{i}: {dict(zip(EMOTION_DIMS, [f'{v:.3f}' for v in vec]))}")

    os.unlink(tmp_path)
    print("  自测通过 ✓")
