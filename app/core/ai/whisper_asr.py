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


def _ensure_hf_mirror():
    """国内网络拉模型易超时：未设置时默认走 hf-mirror。"""
    if os.environ.get("HF_ENDPOINT") or os.environ.get("HUGGINGFACE_HUB_CACHE_DISABLE_MIRROR"):
        return
    # 用户已显式设置则尊重；否则用镜像降低 ConnectTimeout
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")


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
    except ImportError as e:
        logger.debug(f"[WhisperASR] faster_whisper 不可用: {e}")

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


def unavailable_reason() -> str:
    """不可用时的安装说明（给 UI 弹窗用）"""
    if is_available():
        return ""
    return (
        "未安装语音识别组件（faster-whisper 或 openai-whisper）。\n\n"
        "请在项目虚拟环境执行其一：\n"
        "  .\\.venv312\\Scripts\\python.exe -m pip install faster-whisper\n"
        "  或运行 .\\scripts\\setup_deps.ps1\n\n"
        "模型下载默认走 hf-mirror；装好后重新点击「AI字幕」。\n"
        "假字幕占位已禁用，不会生成「字幕片段 N」无关文本。"
    )


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

        _ensure_hf_mirror()
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
            # 镜像失败时再试官方源一次
            if os.environ.get("HF_ENDPOINT") == "https://hf-mirror.com":
                try:
                    os.environ.pop("HF_ENDPOINT", None)
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
                    logger.info(f"Whisper 模型已加载(官方源): {model_size}")
                    return model
                except Exception as e2:
                    logger.warning(f"官方源加载也失败 [{model_size}]: {e2}")
            return None


# ── 核心 API ──────────────────────────────────────────────────

def transcribe(
    video_path: str,
    model_size: str = "base",
    language: str = "zh",
    hotwords: str = "",
    word_timestamps: bool = False,
) -> List[Dict]:
    """
    Whisper 语音识别，返回统一格式的 segment 列表。

    Args:
        video_path: 视频/音频文件路径
        model_size: 模型大小 (tiny/base/small/medium/large)
        language:   识别语言
        hotwords:   热词提示（逗号分隔），帮助模型偏向特定词汇
        word_timestamps: 是否返回**词级**时间戳。
            段落级时间戳只够"定位到这句话"，做不了「词锚定」——
            改一句台词就落点全废。开启后每段附带 `words` 列表，
            元素为 `{"text", "start", "end"}`，是目前唯一能支撑
            「改文案只需重排、不必重分析」的原料。
            代价：转写略慢（多一次词级对齐）。

    Returns:
        [{"start": 0.0, "end": 2.5, "text": "你好世界", "words": [...]}, ...]
        `words` 仅在 word_timestamps=True 时出现；失败时返回空列表
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
            if word_timestamps:
                kwargs["word_timestamps"] = True
            segments_iter, _info = model.transcribe(video_path, **kwargs)
            out = []
            for seg in segments_iter:
                item = {
                    "start": seg.start,
                    "end": seg.end,
                    "text": seg.text.strip() if seg.text else "",
                    "avg_logprob": getattr(seg, "avg_logprob", 0.0),
                }
                if word_timestamps:
                    item["words"] = _extract_words(getattr(seg, "words", None), "attr")
                out.append(item)
            return out
        else:
            # openai-whisper
            kwargs = {"language": language} if language else {}
            if hotwords:
                kwargs["initial_prompt"] = f"以下词汇可能出现: {hotwords}"
            if word_timestamps:
                kwargs["word_timestamps"] = True
            result = model.transcribe(video_path, **kwargs)
            out = []
            for seg in result.get("segments", []):
                item = {
                    "start": seg.get("start", 0),
                    "end": seg.get("end", 0),
                    "text": seg.get("text", "").strip(),
                    "avg_logprob": seg.get("avg_logprob", 0.0),
                }
                if word_timestamps:
                    item["words"] = _extract_words(seg.get("words"), "dict")
                out.append(item)
            return out
    except Exception as e:
        logger.warning(f"Whisper 转录失败 [{video_path}]: {e}")
        return []


def _extract_words(raw_words, shape: str) -> List[Dict]:
    """把两种后端的词级结果归一成 `[{"text", "start", "end"}]`。

    faster-whisper 的词是对象（属性访问），openai-whisper 是 dict。
    空文本的词（纯空白）丢弃 —— 它们没有锚定价值，留着只会抬高 from_word/to_word
    的序号，让锚点在两版之间对不齐。
    """
    out: List[Dict] = []
    if not raw_words:
        return out
    for w in raw_words:
        try:
            if shape == "attr":
                text = (getattr(w, "word", "") or "").strip()
                start = float(getattr(w, "start", 0.0) or 0.0)
                end = float(getattr(w, "end", 0.0) or 0.0)
            else:
                text = (w.get("word", "") or "").strip()
                start = float(w.get("start", 0.0) or 0.0)
                end = float(w.get("end", 0.0) or 0.0)
        except Exception:
            continue
        if not text:
            continue
        out.append({"text": text, "start": start, "end": end})
    return out


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
