"""
LLM 智能裁剪引擎
================
整合 FunClip + videocut-skills + 黄金3秒 思路，
对接项目已有 Ollama 客户端 + Whisper 字幕 + ffmpeg 切片。

核心流程:
    视频 → Whisper ASR → SRT 字幕
         → Prompt 模板 + 用户提示 → Ollama LLM 推理
         → 解析时间段 → ffmpeg 切片 → concat 输出

参考:
    - FunClip (modelscope/FunClip) videoclipper.py clip() 方法
    - videocut-skills 5-skill 拆解模式
    - 黄金3秒公式: 悬念前置80% + 身份代入15% + 锚点5%
"""

import os
import re
import json
import time
import logging
import subprocess
import tempfile
from datetime import datetime
from typing import Optional, List, Dict, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 辅助：时间格式转换
# ---------------------------------------------------------------------------

def _parse_time_srt(t: str) -> float:
    """
    将 SRT/FFmpeg 时间字符串转为秒数。
    支持: "HH:MM:SS,mmm" / "HH:MM:SS.mmm" / "HH:MM:SS" / 纯秒数
    """
    t = t.strip()
    # 纯数字（秒）
    if re.match(r"^\d+(\.\d+)?$", t):
        return float(t)
    # HH:MM:SS,mmm 或 HH:MM:SS.mmm
    m = re.match(r"(\d+):(\d+):(\d+)[,.](\d+)", t)
    if m:
        h, mi, s, ms = int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)
        return h * 3600 + mi * 60 + s + int(ms.ljust(3, "0")[:3]) / 1000.0
    # HH:MM:SS
    m = re.match(r"(\d+):(\d+):(\d+)", t)
    if m:
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
    raise ValueError(f"无法解析时间: {t}")


def _fmt_time_ffmpeg(sec: float) -> str:
    """秒数 → ffmpeg 格式 HH:MM:SS.mmm"""
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def _extract_json(text: str) -> Optional[list]:
    """
    从 LLM 返回的文本中提取 JSON 数组。
    容错：LLM 经常在 JSON 外面包 markdown 代码块或说明文字。
    """
    if not text:
        return None
    # 优先匹配 ```json ... ``` 或 ``` ... ```
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        text = m.group(1).strip()
    # 尝试直接解析
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass
    # 尝试找 [...]
    m = re.search(r"\[[\s\S]*?\]", text)
    if m:
        try:
            data = json.loads(m.group())
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass
    return None


# ---------------------------------------------------------------------------
# SRT 生成（剥离自 modules.py EditorModule._generate_ai_subtitles）
# ---------------------------------------------------------------------------

def _get_ffmpeg_exe() -> str:
    """获取项目内 ffmpeg 路径"""
    candidates = [
        os.environ.get("AI_EDITOR_FFMPEG_DIR", ""),
    ]
    # 项目内置 thirdparty
    here = os.path.dirname(os.path.abspath(__file__))
    project_ffmpeg = os.path.normpath(
        os.path.join(here, "..", "..", "..", "thirdparty", "ffmpeg", "bin", "ffmpeg.exe")
    )
    if os.path.isfile(project_ffmpeg):
        candidates.append(os.path.dirname(project_ffmpeg))
    for d in candidates:
        d = d.strip()
        if d and os.path.isfile(os.path.join(d, "ffmpeg.exe")):
            return os.path.join(d, "ffmpeg.exe")
    return "ffmpeg"  # fallback to PATH


def transcribe_whisper(video_path: str, hotwords: str = "") -> Optional[List[Dict]]:
    """
    用 Whisper 生成 SRT 片段（委托给共享模块）。

    Returns:
        [{"start": 0.0, "end": 2.5, "text": "你好世界"}, ...] 或 None
    """
    try:
        from app.core.ai.whisper_asr import transcribe
    except ImportError:
        try:
            from core.ai.whisper_asr import transcribe
        except ImportError:
            logger.warning("whisper_asr 共享模块不可用")
            return None

    result = transcribe(video_path, model_size="base", language="zh", hotwords=hotwords)
    return result if result else None


def segments_to_srt_text(segments: List[Dict]) -> str:
    """将 Whisper segments 转为 SRT 文本（供 LLM 阅读），委托给共享模块"""
    try:
        from app.core.ai.whisper_asr import segments_to_srt_text as _srt_text
    except ImportError:
        try:
            from core.ai.whisper_asr import segments_to_srt_text as _srt_text
        except ImportError:
            # 回退内联实现
            lines = []
            for i, seg in enumerate(segments, 1):
                start = seg.get("start", 0)
                end = seg.get("end", 0)
                text = seg.get("text", "").strip()
                if not text:
                    continue
                lines.append(
                    f"[{i}] {_fmt_time_ffmpeg(start)} → {_fmt_time_ffmpeg(end)}: {text}"
                )
            return "\n".join(lines)
    return _srt_text(segments)


# ---------------------------------------------------------------------------
# LLM 智能裁剪引擎
# ---------------------------------------------------------------------------

class LLMClipper:
    """
    LLM 智能裁剪引擎

    用法:
        clipper = LLMClipper()
        if clipper.is_available():
            output = clipper.smart_clip("video.mp4", prompt="提取反转片段")
            print(f"输出: {output}")
        else:
            # fallback to AIClipAlgorithm
            ...
    """

    def __init__(self, ollama_model: str = ""):
        self._ollama_model = ollama_model  # 空=自动选择第一个已安装模型

    # ---- Ollama 检测 ----

    @staticmethod
    def is_ollama_available() -> bool:
        """检测 Ollama 服务是否可用"""
        try:
            from app.modules.lego.ollama_client import OllamaClient
            return OllamaClient().is_available(force_check=True)
        except Exception:
            return False

    @staticmethod
    def list_ollama_models() -> List[str]:
        """列出已安装的 Ollama 模型名"""
        try:
            from app.modules.lego.ollama_client import OllamaClient
            models = OllamaClient().list_models()
            return [m.name for m in models]
        except Exception:
            return []

    def is_available(self) -> bool:
        """LLM 裁剪是否可用（需要 Ollama 运行且有模型）"""
        return self.is_ollama_available() and len(self.list_ollama_models()) > 0

    # ---- 核心流程 ----

    def smart_clip(
        self,
        video_path: str,
        prompt: str = "提取精彩片段",
        template_key: str = "ai_clip_algorithm",
        max_duration: int = 60,
        output_dir: str = "AI剪辑输出",
        hotwords: str = "",
        drama_structure=None,  # Optional[DramaStructure]: 复用已有分析结果
    ) -> Optional[str]:
        """
        智能裁剪主入口。

        Args:
            video_path:      源视频路径
            prompt:          用户提示词（自然语言，"提取反转片段"）
            template_key:    prompt 模板键名
            max_duration:    最大输出时长（秒）
            output_dir:      输出目录
            hotwords:        ASR 热词（逗号分隔，如 "短剧,AI,爆款"）
            drama_structure: 可选，已有的 DramaStructure 分析结果，
                             传入后可跳过 Whisper ASR 并注入剧情上下文

        Returns:
            输出视频路径 或 None
        """
        t0 = time.time()

        # 1. 验证视频文件
        if not os.path.isfile(video_path):
            logger.error(f"视频文件不存在: {video_path}")
            return None

        # 2. 获取字幕/对话文本
        srt_text = ""
        analysis_context = ""
        if drama_structure is not None and hasattr(drama_structure, 'dialogues'):
            # 复用已有分析：直接从对话片段构建 SRT 文本，跳过 Whisper ASR
            logger.info("[LLM] 复用已有剧情分析，跳过 Whisper ASR")
            srt_lines = []
            for i, d in enumerate(drama_structure.dialogues):
                srt_lines.append(
                    f"[{i}] {_fmt_time_ffmpeg(d.start_time)} → "
                    f"{_fmt_time_ffmpeg(d.end_time)}: {d.text}"
                )
            srt_text = "\n".join(srt_lines)

            # 注入剧情上下文，让 LLM 做更精确的裁剪决策
            ctx_parts = []
            if hasattr(drama_structure, 'title') and drama_structure.title:
                ctx_parts.append(f"剧名: {drama_structure.title}")
            if hasattr(drama_structure, 'genre') and drama_structure.genre:
                ctx_parts.append(f"类型: {drama_structure.genre}")
            if hasattr(drama_structure, 'themes') and drama_structure.themes:
                ctx_parts.append(f"主题: {', '.join(drama_structure.themes)}")
            if hasattr(drama_structure, 'characters'):
                chars = [c.name for c in drama_structure.characters]
                if chars:
                    ctx_parts.append(f"主要角色: {', '.join(chars)}")
            if hasattr(drama_structure, 'plot_points'):
                key_plots = [p for p in drama_structure.plot_points if p.importance > 0.6]
                if key_plots:
                    plot_descs = [f"{p.timestamp:.0f}s {p.description}" for p in key_plots[:5]]
                    ctx_parts.append(f"关键情节点: {'; '.join(plot_descs)}")
            analysis_context = "\n".join(ctx_parts)
            logger.info(f"[LLM] 注入剧情上下文 ({len(ctx_parts)} 项)，"
                        f"耗时 {time.time() - t0:.1f}s")
        else:
            # 标准流程：Whisper ASR
            segments = transcribe_whisper(video_path, hotwords=hotwords)
            srt_text = segments_to_srt_text(segments) if segments else ""
            logger.info(f"[LLM] 字幕生成完成，{len(segments or [])} 条，"
                        f"耗时 {time.time() - t0:.1f}s")

        if not srt_text:
            logger.warning("[LLM] 无字幕文本，回退到原视频前15秒")
            return self._fallback_clip(video_path, output_dir)

        # 3. 构建 prompt
        from app.core.ai.prompt_templates import build_prompt as _build_prompt
        msgs = _build_prompt(
            template_key, srt_text=srt_text,
            user_hint=prompt, max_duration=max_duration,
        )
        if not msgs:
            logger.error(f"模板不存在: {template_key}")
            return None

        # 注入剧情上下文到 user prompt（如果有）
        if analysis_context and msgs.get("user"):
            msgs["user"] = (
                f"【剧情分析上下文】\n{analysis_context}\n\n"
                f"{msgs['user']}"
            )

        # 4. 调用 Ollama
        segments_to_keep = self._call_ollama(msgs)
        if not segments_to_keep:
            logger.warning("[LLM] LLM 没有返回有效时间段，回退到原视频前15秒")
            return self._fallback_clip(video_path, output_dir)

        logger.info(f"[LLM] Ollama 推理完成，返回 {len(segments_to_keep)} 段，"
                    f"耗时 {time.time() - t0:.1f}s")

        # 5. MLT/FFmpeg 切片 + 拼接
        output_path = self._ffmpeg_clip(video_path, segments_to_keep, output_dir)
        logger.info(f"[LLM] 智能剪辑完成: {output_path}，总耗时 {time.time() - t0:.1f}s")
        return output_path

    def _call_ollama(self, msgs: Dict) -> Optional[List[Dict]]:
        """
        调用 Ollama 获取时间段列表。

        Args:
            msgs: {"system": ..., "user": ...}

        Returns:
            [{"start": 12.0, "end": 25.0}, ...] 或 None
        """
        try:
            from app.modules.lego.ollama_client import OllamaClient
        except ImportError:
            logger.warning("无法导入 OllamaClient")
            return None

        client = OllamaClient()

        # 自动选模型
        model = self._ollama_model
        if not model:
            available = self.list_ollama_models()
            if not available:
                return None
            model = available[0]

        # 构建消息
        messages = [
            {"role": "system", "content": msgs["system"]},
            {"role": "user", "content": msgs["user"]},
        ]

        try:
            # chat 返回 generator，取第一个（非 stream 模式）
            response_gen = client.chat(model, messages, stream=False)
            full = ""
            for chunk in response_gen:
                full += chunk

            logger.debug(f"[LLM] Ollama 原始响应 ({len(full)} 字符):\n{full[:500]}")

            # 解析 JSON
            segments = _extract_json(full)
            if not segments:
                logger.warning("[LLM] 无法解析 LLM 响应中的 JSON")
                return None

            # 标准化时间段
            result = []
            for item in segments:
                if not isinstance(item, dict):
                    continue
                start_str = item.get("start", "")
                end_str = item.get("end", "")
                if not start_str or not end_str:
                    continue
                try:
                    result.append({
                        "start": _parse_time_srt(start_str),
                        "end": _parse_time_srt(end_str),
                    })
                except ValueError:
                    continue
            return result if result else None

        except Exception as e:
            logger.warning(f"[LLM] Ollama 调用失败: {e}")
            return None

    def _ffmpeg_clip(
        self, video_path: str, segments: List[Dict], output_dir: str
    ) -> Optional[str]:
        """
        智能剪辑输出：优先 MLT 引擎，回退到 FFmpeg。

        Args:
            video_path: 源视频
            segments:   [{"start": 1.0, "end": 3.0}, ...]
            output_dir: 输出目录

        Returns:
            输出路径 或 None
        """
        os.makedirs(output_dir, exist_ok=True)

        # 去重 + 合并重叠段
        merged = self._merge_segments(segments)
        if not merged:
            return None

        out_path = os.path.join(
            output_dir,
            f"ai_clip_llm_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
        )

        # 优先尝试 MLT DramaEditor（原生多轨+滤镜+关键帧）
        if self._try_mlt_clip(video_path, merged, out_path):
            return out_path

        # 回退：FFmpeg 切片 + concat
        logger.info("[LLM] MLT 不可用，回退到 FFmpeg 切片")
        return self._fallback_ffmpeg_clip(video_path, merged, output_dir, out_path)

    def _try_mlt_clip(
        self, video_path: str, segments: List[Dict], out_path: str
    ) -> bool:
        """尝试使用 MLT DramaEditor 进行智能剪辑"""
        try:
            from app.core.video_processing.drama_mlt import get_drama_editor, DramaEditor
        except ImportError:
            try:
                from core.video_processing.drama_mlt import get_drama_editor, DramaEditor
            except ImportError:
                return False

        try:
            editor = get_drama_editor()
            editor.new_drama(
                os.path.basename(video_path),
                episode=1,
                preset="AI智能剪辑",
            )
            # 将 segments 转为 DramaEditor 的 highlights 格式
            highlights = [
                {
                    "source": video_path,
                    "start_time": seg["start"],
                    "duration": seg["end"] - seg["start"],
                    "score": 0.8,
                }
                for seg in segments
            ]
            editor.load_highlights(highlights)
            result = editor.auto_assemble(keep_top_pct=1.0)
            if not result.get("success", False):
                logger.warning(f"[LLM] MLT auto_assemble 失败: {result}")
                return False

            # 导出到指定路径（覆盖默认导出路径）
            default_out = editor.export(
                platform="通用HD",
                output_dir=os.path.dirname(out_path),
            )
            if default_out and os.path.isfile(default_out):
                # 如果导出的文件名与预期不同，重命名
                if os.path.normpath(default_out) != os.path.normpath(out_path):
                    try:
                        os.replace(default_out, out_path)
                    except OSError:
                        out_path = default_out
                logger.info(f"[LLM] MLT 剪辑成功: {out_path}")
                return True

            logger.warning(f"[LLM] MLT export 返回空: {default_out}")
            return False
        except Exception as e:
            logger.warning(f"[LLM] MLT 剪辑异常，回退 FFmpeg: {e}")
            return False

    def _fallback_ffmpeg_clip(
        self, video_path: str, merged: List[Dict],
        output_dir: str, out_path: str,
    ) -> Optional[str]:
        """FFmpeg 切片 + concat（原有逻辑）"""
        ffmpeg = _get_ffmpeg_exe()

        # 生成临时切片
        temp_files = []
        for i, seg in enumerate(merged):
            start, end = seg["start"], seg["end"]
            dur = end - start
            if dur <= 0:
                continue
            out = os.path.join(
                output_dir,
                f"_temp_seg_{i:03d}.mp4"
            )
            cmd = [
                ffmpeg, "-y",
                "-ss", _fmt_time_ffmpeg(start),
                "-i", video_path,
                "-t", _fmt_time_ffmpeg(dur),
                "-c", "copy",
                "-avoid_negative_ts", "make_zero",
                out,
            ]
            try:
                subprocess.run(cmd, capture_output=True, timeout=60)
                if os.path.isfile(out) and os.path.getsize(out) > 0:
                    temp_files.append(out)
            except Exception as e:
                logger.warning(f"[LLM] 切片失败 seg {i}: {e}")

        if not temp_files:
            return None

        if len(temp_files) == 1:
            try:
                os.replace(temp_files[0], out_path)
            except OSError:
                os.rename(temp_files[0], out_path)
            return out_path

        # 多段：concat
        concat_file = os.path.join(output_dir, "_temp_concat.txt")
        with open(concat_file, "w", encoding="utf-8") as f:
            for tf in temp_files:
                f.write(f"file '{tf.replace(chr(92), '/')}'\n")

        try:
            subprocess.run([
                ffmpeg, "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_file),
                "-c", "copy",
                out_path,
            ], capture_output=True, timeout=120)
        finally:
            for tf in temp_files:
                try:
                    os.remove(tf)
                except Exception:
                    pass
            try:
                os.remove(concat_file)
            except Exception:
                pass

        if os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
            return out_path
        return None

    def _merge_segments(self, segments: List[Dict]) -> List[Dict]:
        """排序 + 合并重叠时间段"""
        if not segments:
            return []
        segs = sorted(segments, key=lambda s: s["start"])
        merged = [segs[0].copy()]
        for seg in segs[1:]:
            last = merged[-1]
            if seg["start"] <= last["end"]:
                last["end"] = max(last["end"], seg["end"])
            else:
                merged.append(seg.copy())
        return merged

    def _fallback_clip(self, video_path: str, output_dir: str) -> Optional[str]:
        """LLM 失败时取视频前 15 秒作为兜底"""
        ffmpeg = _get_ffmpeg_exe()
        os.makedirs(output_dir, exist_ok=True)
        out_path = os.path.join(
            output_dir,
            f"ai_clip_fallback_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
        )
        try:
            subprocess.run([
                ffmpeg, "-y",
                "-i", video_path,
                "-t", "15",
                "-c", "copy",
                out_path,
            ], capture_output=True, timeout=60)
            return out_path if os.path.isfile(out_path) else None
        except Exception:
            return None


# ---------------------------------------------------------------------------
# 便捷函数
# ---------------------------------------------------------------------------

_llm_clipper: Optional[LLMClipper] = None


def get_llm_clipper() -> LLMClipper:
    """获取 LLMClipper 单例"""
    global _llm_clipper
    if _llm_clipper is None:
        _llm_clipper = LLMClipper()
    return _llm_clipper


def is_llm_clip_available() -> bool:
    """LLM 智能裁剪是否可用"""
    return get_llm_clipper().is_available()
