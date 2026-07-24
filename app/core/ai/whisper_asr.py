"""
统一的 Whisper ASR 模块
======================
所有 AI 层组件共享此模块进行语音识别，
消除 4 套独立实现的冗余。

特性：
- 自动选择后端：faster-whisper（优先，速度快5x）→ openai-whisper（回退）
- 统一返回格式：List[{"start": float, "end": float, "text": str, ...}]
- 单例模型缓存：避免重复加载模型
- 支持 hotwords 注入（通过 initial_prompt）

用法:
    from app.core.ai.whisper_asr import transcribe, is_available

    if is_available():
        segments = transcribe("video.mp4", language="zh", hotwords="短剧,反转")
        for seg in segments:
            print(f"{seg['start']:.1f}s - {seg['end']:.1f}s: {seg['text']}")
"""

import os
import logging
import threading
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# ── 全局状态 ──────────────────────────────────────────────────

_WHISPER_TYPE: Optional[str] = None  # "faster_whisper" | "openai_whisper" | None
_MODEL_CACHE: Dict[str, object] = {}  # keyed by model_size
_MODEL_LOCK = threading.Lock()


def _detect_backend() -> Optional[str]:
    """检测可用的 Whisper 后端，优先 faster-whisper"""
    global _WHISPER_TYPE
    if _WHISPER_TYPE is not None:
        return _WHISPER_TYPE

    try:
        import faster_whisper  # noqa: F401
        _WHISPER_TYPE = "faster_whisper"
        logger.info("Whisper 后端: faster-whisper")
        return _WHISPER_TYPE
    except ImportError:
        pass

    try:
        import whisper  # noqa: F401
        _WHISPER_TYPE = "openai_whisper"
        logger.info("Whisper 后端: openai-whisper")
        return _WHISPER_TYPE
    except ImportError:
        logger.warning("Whisper 未安装，语音识别不可用")
        return None


def is_available() -> bool:
    """Whisper 是否可用"""
    return _detect_backend() is not None


def get_backend() -> Optional[str]:
    """获取当前后端名称"""
    return _detect_backend()


# ── 模型加载 ──────────────────────────────────────────────────

def _load_model(model_size: str = "base") -> Optional[object]:
    """加载 Whisper 模型（线程安全 + 缓存）"""
    backend = _detect_backend()
    if not backend:
        return None

    cache_key = f"{backend}:{model_size}"
    with _MODEL_LOCK:
        if cache_key in _MODEL_CACHE:
            return _MODEL_CACHE[cache_key]

        try:
            if backend == "faster_whisper":
                import faster_whisper
                compute_type = (
                    "int8" if model_size in ("tiny", "base", "small") else "float16"
                )
                model = faster_whisper.WhisperModel(
                    model_size, device="cpu", compute_type=compute_type
                )
            else:
                import whisper
                model = whisper.load_model(model_size)
            _MODEL_CACHE[cache_key] = model
            logger.info(f"Whisper 模型已加载: {model_size} ({backend})")
            return model
        except Exception as e:
            logger.warning(f"加载 Whisper 模型失败 [{model_size}]: {e}")
            return None


# ── 核心 API ──────────────────────────────────────────────────

def transcribe(
    video_path: str,
    model_size: str = "base",
    language: str = "zh",
    hotwords: str = "",
) -> List[Dict]:
    """
    Whisper 语音识别，返回统一格式的 segment 列表。

    Args:
        video_path: 视频/音频文件路径
        model_size: 模型大小 (tiny/base/small/medium/large)
        language:   识别语言
        hotwords:   热词提示（逗号分隔），帮助模型偏向特定词汇

    Returns:
        [{"start": 0.0, "end": 2.5, "text": "你好世界"}, ...]
        失败时返回空列表
    """
    backend = _detect_backend()
    if not backend:
        return []

    model = _load_model(model_size)
    if model is None:
        return []

    try:
        if backend == "faster_whisper":
            kwargs = {"language": language} if language else {}
            if hotwords:
                kwargs["initial_prompt"] = f"以下词汇可能出现: {hotwords}"
            kwargs["vad_filter"] = True
            kwargs["vad_parameters"] = dict(min_silence_duration_ms=500)
            segments_iter, _info = model.transcribe(video_path, **kwargs)
            return [
                {
                    "start": seg.start,
                    "end": seg.end,
                    "text": seg.text.strip() if seg.text else "",
                    "avg_logprob": getattr(seg, "avg_logprob", 0.0),
                }
                for seg in segments_iter
            ]
        else:
            # openai-whisper
            kwargs = {"language": language} if language else {}
            if hotwords:
                kwargs["initial_prompt"] = f"以下词汇可能出现: {hotwords}"
            result = model.transcribe(video_path, **kwargs)
            return [
                {
                    "start": seg.get("start", 0),
                    "end": seg.get("end", 0),
                    "text": seg.get("text", "").strip(),
                    "avg_logprob": seg.get("avg_logprob", 0.0),
                }
                for seg in result.get("segments", [])
            ]
    except Exception as e:
        logger.warning(f"Whisper 转录失败 [{video_path}]: {e}")
        return []


def segments_to_srt_text(segments: List[Dict]) -> str:
    """将 segment 列表转为供 LLM 阅读的文本"""
    lines = []
    for i, seg in enumerate(segments, 1):
        start = _fmt_time(seg.get("start", 0))
        end = _fmt_time(seg.get("end", 0))
        text = seg.get("text", "").strip()
        if not text:
            continue
        lines.append(f"[{i}] {start} → {end}: {text}")
    return "\n".join(lines)


def segments_to_srt_file(segments: List[Dict], output_path: str):
    """将 segment 列表写入 SRT 文件"""
    with open(output_path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, 1):
            start = _fmt_time_srt(seg.get("start", 0))
            end = _fmt_time_srt(seg.get("end", 0))
            text = seg.get("text", "").strip()
            f.write(f"{i}\n{start} --> {end}\n{text}\n\n")


# ── 时间格式化工具 ─────────────────────────────────────────────

def _fmt_time(sec: float) -> str:
    """秒 → HH:MM:SS.mmm"""
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def _fmt_time_srt(sec: float) -> str:
    """秒 → HH:MM:SS,mmm (SRT 格式)"""
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    ms = int((sec % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
