"""
AI配音生成引擎
提供AI配音生成、声音克隆、多语言支持
"""

import numpy as np
import os
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
from threading import RLock
from datetime import datetime
import json


import logging
logger = logging.getLogger("AI短剧编辑器.core.voice_generator")

# ── 诚实失败纪律（2026-10-09 修）─────────────────────────────
# 项目铁律：**执行端不可用必须诚实失败，绝不返回假音频/静默降级**
# （同 YuE 那条，见 docs/knowledge 冻结区不变量第 35 条）。
# 本模块原实现违反该铁律：gTTS / edge-tts / Coqui 全失败时，它合成一段
# 220Hz 正弦波当"配音"返回，而 generate_voice() 无条件标 success=True。
# 下游据此会写出一个时长正确、内容完全错误的音频文件 —— 且没有任何信号
# 告诉用户"这是假的"。对配音这种要交付给观众的东西，这是最坏的一类失败。
#
# 修法：默认**诚实失败**；把正弦波降级成**显式 opt-in 的演示占位**
# （环境变量 SHIGUANG_ALLOW_PLACEHOLDER_TTS=1），并在结果里留痕
# （error_message / is_placeholder），让它永远不可能被误当成真配音。
ENV_ALLOW_PLACEHOLDER_TTS = "SHIGUANG_ALLOW_PLACEHOLDER_TTS"
_TRUTHY = {"1", "true", "yes", "on"}

# ── Piper（本地离线 TTS，2026-10-11 接入）────────────────────
# 动机：原链路 Coqui→gTTS→edge-tts 里只有 gTTS 是本机实装的，且 gTTS **要联网**；
# 对「素材库仅本机」的离线场景，需要一条**纯本地**通路。Piper 轻量、离线、快，
# 是离线 TTS 的业界首选（与 whisper 之于 ASR 对位）。
# 与 YuE 同纪律：**模型未配置必须诚实失败**，绝不因缺模型就退回假音频。
# 配置：SHIGUANG_PIPER_MODEL 指向 .onnx；或 SHIGUANG_PIPER_HOME 指向含 .onnx 的目录。
ENV_PIPER_MODEL = "SHIGUANG_PIPER_MODEL"
ENV_PIPER_HOME = "SHIGUANG_PIPER_HOME"


def allow_placeholder_tts() -> bool:
    """是否允许「真 TTS 全挂时返回正弦波占位」（默认否 —— 默认诚实失败）。"""
    return os.environ.get(ENV_ALLOW_PLACEHOLDER_TTS, "").strip().lower() in _TRUTHY


def piper_model_path() -> Optional[str]:
    """定位 Piper 语音模型（.onnx）：env 显式路径 → env 目录 → 常见约定目录。

    找不到返回 None（调用方据此诚实跳过 Piper，而非报错）。
    """
    import glob

    explicit = os.environ.get(ENV_PIPER_MODEL, "").strip()
    if explicit and os.path.isfile(explicit):
        return explicit
    home = os.environ.get(ENV_PIPER_HOME, "").strip()
    dirs = [home] if home else []
    dirs += [
        os.path.join(os.getcwd(), "models", "piper"),
        os.path.join(os.getcwd(), "data", "piper"),
    ]
    for d in dirs:
        if d and os.path.isdir(d):
            found = sorted(glob.glob(os.path.join(d, "*.onnx")))
            if found:
                return found[0]
    return None


class VoiceStyle(Enum):
    """配音风格"""
    CALM = "calm"
    ENERGETIC = "energetic"
    EMOTIONAL = "emotional"
    PROFESSIONAL = "professional"
    CASUAL = "casual"
    DRAMATIC = "dramatic"
    HUMOROUS = "humorous"


class VoiceGender(Enum):
    """配音性别"""
    MALE = "male"
    FEMALE = "female"
    CHILD = "child"
    NEUTRAL = "neutral"


class VoiceAge(Enum):
    """配音年龄"""
    YOUNG = "young"
    ADULT = "adult"
    SENIOR = "senior"


@dataclass
class VoiceProfile:
    """声线配置"""
    id: str
    name: str
    gender: VoiceGender
    age: VoiceAge
    style: VoiceStyle
    language: str = "zh"
    sample_rate: int = 22050
    description: str = ""
    preview_url: Optional[str] = None
    is_default: bool = False
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "gender": self.gender.value,
            "age": self.age.value,
            "style": self.style.value,
            "language": self.language,
            "sample_rate": self.sample_rate,
            "description": self.description,
            "preview_url": self.preview_url,
            "is_default": self.is_default
        }


@dataclass
class VoiceGenerationRequest:
    """配音生成请求"""
    text: str
    voice_profile_id: str
    speed: float = 1.0
    pitch: float = 1.0
    volume: float = 1.0
    emotion: str = "neutral"
    language: str = "zh"
    output_format: str = "mp3"
    
    def to_dict(self) -> Dict:
        return {
            "text": self.text,
            "voice_profile_id": self.voice_profile_id,
            "speed": self.speed,
            "pitch": self.pitch,
            "volume": self.volume,
            "emotion": self.emotion,
            "language": self.language,
            "output_format": self.output_format
        }


@dataclass
class VoiceGenerationResult:
    """配音生成结果"""
    request_id: str
    audio_data: Optional[np.ndarray]
    audio_path: Optional[str]
    duration: float
    sample_rate: int
    success: bool
    error_message: str = ""
    generation_time: float = 0.0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    # 2026-10-09 新增：本条音频是否为「正弦波占位」而非真实 TTS 合成产物。
    # 只在 SHIGUANG_ALLOW_PLACEHOLDER_TTS=1 时为 True；有了这个位，
    # 下游（导出/预览/审核）才能把占位音挑出来，而不是拿它当成品交付。
    # 注意：按 serialization-field-symmetry 纪律，新增字段必须同步 to_dict()，
    # 否则写日志/落盘时它会静默丢失。
    is_placeholder: bool = False
    # 2026-10-15 新增（配音一致性方案 P1②）：听写回环验证相似度。
    # None = **未做验证**（ASR 未启用或调用方未请求）——不伪造默认值，如实标注。
    # 由 dub_verify.verify_dubbing() 回填；低于阈值时调用方应红标。
    verified_similarity: Optional[float] = None
    # 字幕来源标记（P1②）："asr" = 时间轴来自**音频听写**（真相）；
    # "estimated" = 剧本文本估算。严禁在 TTS 路径用剧本回填字幕——
    # 剧本只是"意图"，音频才是"真相"。
    subtitle_source: str = "estimated"

    def to_dict(self) -> Dict:
        return {
            "request_id": self.request_id,
            "audio_path": self.audio_path,
            "duration": self.duration,
            "sample_rate": self.sample_rate,
            "success": self.success,
            "error_message": self.error_message,
            "generation_time": self.generation_time,
            "created_at": self.created_at,
            "is_placeholder": self.is_placeholder,
            "verified_similarity": self.verified_similarity,
            "subtitle_source": self.subtitle_source,
        }



class AIVoiceGenerator:
    """AI配音生成器"""
    
    def __init__(self):
        self._voice_profiles: Dict[str, VoiceProfile] = {}
        self._generation_queue: List[VoiceGenerationRequest] = []
        self._results: Dict[str, VoiceGenerationResult] = {}
        self._lock = RLock()
        self._initialize_default_profiles()
    
    def _initialize_default_profiles(self):
        """初始化默认声线配置"""
        default_profiles = [
            VoiceProfile(
                id="male_adult_calm",
                name="男声沉稳",
                gender=VoiceGender.MALE,
                age=VoiceAge.ADULT,
                style=VoiceStyle.CALM,
                description="适合正式场合的男声",
                is_default=True
            ),
            VoiceProfile(
                id="male_adult_energetic",
                name="男声活力",
                gender=VoiceGender.MALE,
                age=VoiceAge.ADULT,
                style=VoiceStyle.ENERGETIC,
                description="适合活力场景的男声",
                is_default=True
            ),
            VoiceProfile(
                id="female_adult_emotional",
                name="女声情感",
                gender=VoiceGender.FEMALE,
                age=VoiceAge.ADULT,
                style=VoiceStyle.EMOTIONAL,
                description="适合情感场景的女声",
                is_default=True
            ),
            VoiceProfile(
                id="female_young_casual",
                name="女声年轻",
                gender=VoiceGender.FEMALE,
                age=VoiceAge.YOUNG,
                style=VoiceStyle.CASUAL,
                description="适合日常场景的年轻女声",
                is_default=True
            ),
            VoiceProfile(
                id="child_cute",
                name="童声可爱",
                gender=VoiceGender.CHILD,
                age=VoiceAge.YOUNG,
                style=VoiceStyle.HUMOROUS,
                description="适合儿童内容的可爱童声",
                is_default=True
            ),
            VoiceProfile(
                id="neutral_professional",
                name="中性专业",
                gender=VoiceGender.NEUTRAL,
                age=VoiceAge.ADULT,
                style=VoiceStyle.PROFESSIONAL,
                description="适合专业内容的中性声线",
                is_default=True
            )
        ]
        
        for profile in default_profiles:
            self._voice_profiles[profile.id] = profile
    
    def generate_voice(self, request: VoiceGenerationRequest,
                    progress_callback: Optional[callable] = None) -> VoiceGenerationResult:
        """生成配音"""
        if progress_callback:
            progress_callback(0, "开始生成配音...")
        
        import time
        start_time = time.time()
        
        with self._lock:
            try:
                # 获取声线配置
                voice_profile = self._voice_profiles.get(request.voice_profile_id)
                if not voice_profile:
                    return VoiceGenerationResult(
                        request_id=str(time.time()),
                        audio_data=None,
                        audio_path=None,
                        duration=0.0,
                        sample_rate=0,
                        success=False,
                        error_message=f"声线配置不存在: {request.voice_profile_id}"
                    )
                
                if progress_callback:
                    progress_callback(20, "准备生成...")
                
                # TTS 语音生成
                audio_data = self._generate_tts_audio(request, voice_profile)

                # ── 诚实失败（2026-10-09）：不要拿 None 去算 len()，也不要把
                # 「没有音频」包装成 success=True。原实现在这里直接
                # len(audio_data) ⇒ 引擎全挂时抛 TypeError，被外层 except 吞成
                # 一句模糊的 "object of type 'NoneType' has no len()"。
                if audio_data is None:
                    logger.error("[VoiceGenerator] 未生成任何音频（所有 TTS 引擎不可用），"
                                 "按诚实失败返回：text=%r", request.text[:40])
                    return VoiceGenerationResult(
                        request_id=str(time.time()),
                        audio_data=None,
                        audio_path=None,
                        duration=0.0,
                        sample_rate=0,
                        success=False,
                        error_message=("所有 TTS 引擎不可用（Coqui/gTTS/edge-tts），未生成音频；"
                                       "未使用占位音。如需演示占位音请设置 "
                                       f"{ENV_ALLOW_PLACEHOLDER_TTS}=1"),
                    )

                if progress_callback:
                    progress_callback(80, "处理音频...")
                
                # 计算时长
                duration = len(audio_data) / voice_profile.sample_rate
                
                if progress_callback:
                    progress_callback(100, "生成完成")
                
                generation_time = time.time() - start_time

                is_placeholder = bool(getattr(self, "_last_tts_was_placeholder", False))
                self._last_tts_was_placeholder = False
                
                result = VoiceGenerationResult(
                    request_id=str(time.time()),
                    audio_data=audio_data,
                    audio_path=None,
                    duration=duration,
                    sample_rate=voice_profile.sample_rate,
                    success=True,
                    generation_time=generation_time,
                    is_placeholder=is_placeholder,
                    error_message=("占位音（正弦波），非真实配音"
                                   if is_placeholder else ""),
                )

                
                self._results[result.request_id] = result
                
                return result
                
            except Exception as e:
                logger.error(f'生成配音失败: {e}')
                return VoiceGenerationResult(
                    request_id=str(time.time()),
                    audio_data=None,
                    audio_path=None,
                    duration=0.0,
                    sample_rate=0,
                    success=False,
                    error_message=str(e)
                )
    
    def _try_breeze_tts(self, request: "VoiceGenerationRequest",
                        voice_profile: "VoiceProfile") -> Optional[np.ndarray]:
        """Breeze TTS 2（外部服务）合成；未启用 / 服务不在返回 None（诚实跳过）。

        为什么走外部服务：官方运行时是 Linux + CUDA（依赖 flash-attn，Docker 按
        sm90 编译），eager 需 ~7.7 GiB 显存、官方推荐 12GB 卡；本机 Windows + 8GB
        既装不了也跑不动。与 ComfyUI 同范式：重运行时放外部进程，这里只做客户端。

        三种模式由参数自动选（见 breeze_tts_client.synthesize）：
        - 有参考音频 + 文稿 → Voice Clone / Direction；
          项目还没有「每个声线一份参考音」的数据结构，故用环境变量配的全局参考音；
        - 否则 → Voice Design（用声线的性别/年龄/风格/情绪拼成自然语言指令造音色）。

        采样率：Breeze 固定输出 24kHz s16le，需转成声线要求的 sample_rate。
        走 ffmpeg 管道（与 Piper 那条一致），不额外引入重采样依赖。
        **重采样失败就返回 None**，不返回采样率不符的音频（那会整体变调）。
        """
        try:
            from app.core.ai import breeze_tts_client as breeze
        except Exception:
            logger.debug("[VoiceGenerator] Breeze 客户端导入失败", exc_info=True)
            return None

        if not breeze.breeze_tts_enabled():
            logger.debug("[VoiceGenerator] Breeze 未配置（%s），跳过", breeze.ENV_URL)
            return None

        instruction = breeze.build_instruction(
            gender=getattr(voice_profile.gender, "value", ""),
            age=getattr(voice_profile.age, "value", ""),
            style=getattr(voice_profile.style, "value", ""),
            description=voice_profile.description or "",
            emotion=request.emotion or "",
        )
        ref_audio = (os.environ.get("SHIGUANG_BREEZE_TTS_REF_AUDIO", "") or "").strip()
        ref_text = (os.environ.get("SHIGUANG_BREEZE_TTS_REF_TEXT", "") or "").strip()

        got = breeze.synthesize(
            request.text,
            instruction=instruction,
            ref_audio_path=ref_audio,
            ref_text=ref_text if ref_audio else "",
        )
        if not got:
            return None
        pcm, src_rate = got

        audio = breeze.pcm_to_float32(pcm)
        if audio is None:
            return None
        if src_rate == int(voice_profile.sample_rate):
            return audio

        try:
            import subprocess
            import sys

            no_window = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            proc = subprocess.run(
                ["ffmpeg", "-y",
                 "-f", "s16le", "-ar", str(src_rate), "-ac", "1", "-i", "pipe:0",
                 "-f", "f32le", "-acodec", "pcm_f32le",
                 "-ar", str(int(voice_profile.sample_rate)), "-ac", "1", "pipe:1"],
                input=pcm, capture_output=True, timeout=120, creationflags=no_window,
            )
            if proc.returncode == 0 and proc.stdout:
                return np.frombuffer(proc.stdout, dtype=np.float32)
            logger.warning("[VoiceGenerator] Breeze 重采样失败 rc=%s", proc.returncode)
        except FileNotFoundError:
            logger.warning(
                "[VoiceGenerator] ffmpeg 缺失，Breeze 音频无法重采样到 %s Hz（%d 字节已合成）",
                voice_profile.sample_rate, len(pcm))
        except Exception as e:
            logger.warning("[VoiceGenerator] Breeze 重采样异常: %s", e)
        return None

    def _try_piper_tts(self, text: str, sample_rate: int) -> Optional[np.ndarray]:
        """本地 Piper 合成；模型/引擎不可用返回 None（诚实跳过，不报错）。

        走 CLI（`piper` 或 `python -m piper`，跨版本稳定），文本经 stdin UTF-8 传入
        （中文必需）；产出 wav 再交 ffmpeg 转 f32le 单声道。
        """
        model = piper_model_path()
        if not model:
            logger.debug(
                "[VoiceGenerator] Piper 未配置模型（%s / %s），跳过",
                ENV_PIPER_MODEL, ENV_PIPER_HOME)
            return None
        import shutil
        import subprocess
        import sys
        import tempfile

        no_window = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        exe = shutil.which("piper")
        cmd = [exe] if exe else [sys.executable, "-m", "piper"]
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        try:
            proc = subprocess.run(
                cmd + ["--model", model, "--output_file", tmp.name],
                input=text.encode("utf-8"), capture_output=True, timeout=90,
                creationflags=no_window,
            )
            ok = (proc.returncode == 0 and os.path.exists(tmp.name)
                  and os.path.getsize(tmp.name) >= 128)
            if not ok:
                logger.debug(
                    "[VoiceGenerator] Piper 未产出音频：rc=%s err=%s",
                    proc.returncode, (proc.stderr or b"")[-200:])
                return None
            conv = subprocess.run(
                ["ffmpeg", "-y", "-i", tmp.name,
                 "-f", "f32le", "-acodec", "pcm_f32le",
                 "-ar", str(sample_rate), "-ac", "1", "pipe:1"],
                capture_output=True, timeout=60, creationflags=no_window,
            )
            if conv.returncode == 0 and conv.stdout:
                return np.frombuffer(conv.stdout, dtype=np.float32)
        except FileNotFoundError:
            logger.debug("[VoiceGenerator] Piper 未安装（pip install piper-tts）")
        except Exception as e:
            logger.debug(f"[VoiceGenerator] Piper 合成失败: {e}")
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                logger.debug("清理 Piper 临时音频失败: %s", tmp.name, exc_info=True)
        return None

    def _generate_tts_audio(self, request: VoiceGenerationRequest,
                             voice_profile: VoiceProfile) -> Optional[np.ndarray]:
        """真实 TTS 语音生成 - 优先 Breeze TTS 2(外部服务) → Coqui → Piper(本地) → gTTS → edge-tts。

        Returns:
            一维 float32 音频；**所有引擎都不可用时返回 None**（诚实失败）。
            仅当 `SHIGUANG_ALLOW_PLACEHOLDER_TTS=1` 时才返回正弦波占位音。
        """
        text = request.text
        sample_rate = voice_profile.sample_rate
        text_length = len(text)
        duration_sec = max(1.0, text_length * 0.15)
        # 每次调用先复位「本次是否用了占位音」，避免上一轮的状态串味
        self._last_tts_was_placeholder = False

        # 优先 Breeze TTS 2（3B、支持语音设计/克隆/导演；需外部服务，Linux + 12GB 卡）。
        # 未配置 SHIGUANG_BREEZE_TTS_URL 或服务不在 ⇒ 返回 None，静默回退下面这条本地链。
        audio = self._try_breeze_tts(request, voice_profile)
        if audio is not None:
            return audio

        # 尝试 Coqui TTS（质量最高）
        try:
            from TTS.api import TTS
            import tempfile, os, subprocess, sys
            tmp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
            tmp.close()
            tts = TTS(model_name="tts_models/zh-CN/baker/tacotron2-DDC-GST")
            tts.tts_to_file(text=text, file_path=tmp.name)
            result = subprocess.run([
                "ffmpeg", "-y", "-i", tmp.name,
                "-f", "f32le", "-acodec", "pcm_f32le",
                "-ar", str(sample_rate), "-ac", "1", "pipe:1"
            ], capture_output=True, timeout=60,
               creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
            os.unlink(tmp.name)
            if result.returncode == 0 and result.stdout:
                return np.frombuffer(result.stdout, dtype=np.float32)
        except ImportError as e:
            logger.debug(f"[VoiceGenerator] pyttsx3不可用: {e}")
        except Exception as e:
            logger.debug(f"[VoiceGenerator] pyttsx3生成音频失败: {e}")

        # 尝试 Piper（本地离线，优先于需要联网的 gTTS / edge-tts）
        audio = self._try_piper_tts(text, sample_rate)
        if audio is not None:
            return audio

        # 尝试 gTTS
        try:
            import tempfile, os, subprocess, sys
            from gtts import gTTS
            tmp = tempfile.NamedTemporaryFile(suffix='.mp3', delete=False)
            tmp.close()
            tts = gTTS(text=text, lang='zh-cn', slow=False)
            tts.save(tmp.name)
            result = subprocess.run([
                "ffmpeg", "-y", "-i", tmp.name,
                "-f", "f32le", "-acodec", "pcm_f32le",
                "-ar", str(sample_rate), "-ac", "1", "pipe:1"
            ], capture_output=True, timeout=30,
               creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
            os.unlink(tmp.name)
            if result.returncode == 0 and result.stdout:
                return np.frombuffer(result.stdout, dtype=np.float32)
        except ImportError as e:
            logger.debug(f"[VoiceGenerator] gTTS不可用: {e}")
        except Exception as e:
            logger.debug(f"[VoiceGenerator] gTTS生成音频失败: {e}")

        # 尝试 edge-tts
        try:
            import tempfile, os, subprocess, sys
            tmp = tempfile.NamedTemporaryFile(suffix='.mp3', delete=False)
            tmp.close()
            subprocess.run([
                "edge-tts", "--text", text, "--voice", "zh-CN-XiaoxiaoNeural",
                "--write-media", tmp.name
            ], capture_output=True, timeout=30,
               creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
            if os.path.getsize(tmp.name) > 100:
                result = subprocess.run([
                    "ffmpeg", "-y", "-i", tmp.name,
                    "-f", "f32le", "-acodec", "pcm_f32le",
                    "-ar", str(sample_rate), "-ac", "1", "pipe:1"
                ], capture_output=True, timeout=30,
                   creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
                os.unlink(tmp.name)
                if result.returncode == 0 and result.stdout:
                    return np.frombuffer(result.stdout, dtype=np.float32)
            else:
                os.unlink(tmp.name)
        except Exception as e:
            logger.debug(f"[VoiceGenerator] edge-tts生成音频失败: {e}")

        # ── 最终兜底（2026-10-09 改：默认诚实失败，不再默默返回假音频）──
        # 原实现无条件合成 220Hz 正弦波返回，调用方（generate_voice）还会把
        # success 标成 True ⇒ 用户拿到一个"时长对、内容全是嗡声"的配音文件
        # 却毫无察觉。现在：默认 return None（由 generate_voice 转成诚实的失败
        # 结果）；只有显式打开 SHIGUANG_ALLOW_PLACEHOLDER_TTS=1 才返回占位音，
        # 且调用链会把它标成 is_placeholder=True。
        logger.warning(
            "[VoiceGenerator] 所有真实 TTS 引擎均不可用"
            "（Breeze/Coqui/Piper/gTTS/edge-tts）text=%r", text[:40])
        logger.info(
            "[VoiceGenerator] 离线配音可配置 Piper：pip install piper-tts，"
            "并设置 %s 指向中文 .onnx 模型（如 zh_CN-huayan-medium）", ENV_PIPER_MODEL)
        logger.info(
            "[VoiceGenerator] 想要更高音质/克隆，可在 Linux + ≥12GB 显存机器上跑 Breeze TTS 2，"
            "再设 SHIGUANG_BREEZE_TTS_URL 指向它（本机 8GB 显存跑不动其 7.7GiB 本地推理）")
        if not allow_placeholder_tts():
            logger.error(
                "[VoiceGenerator] 诚实失败：不返回假音频。"
                "如需演示占位音，显式设置 %s=1", ENV_ALLOW_PLACEHOLDER_TTS)
            return None

        logger.warning("[VoiceGenerator] %s=1 ⇒ 返回正弦波占位音（明显不是配音）",
                       ENV_ALLOW_PLACEHOLDER_TTS)
        self._last_tts_was_placeholder = True
        sample_count = int(duration_sec * sample_rate)
        t = np.linspace(0, duration_sec, sample_count, endpoint=False)
        audio = np.sin(2 * np.pi * 220 * t) * 0.3
        audio = audio.astype(np.float32)
        if request.speed != 1.0:
            audio = np.interp(
                np.linspace(0, len(audio), int(len(audio) / request.speed)),
                np.arange(len(audio)), audio)
        if request.pitch != 1.0:
            audio = audio * request.pitch
        return audio
    
    def batch_generate(self, requests: List[VoiceGenerationRequest],
                     progress_callback: Optional[callable] = None) -> List[VoiceGenerationResult]:
        """批量生成配音"""
        results = []
        
        for i, request in enumerate(requests):
            if progress_callback:
                progress = int(100 * (i + 1) / len(requests))
                progress_callback(progress, f"生成 {i+1}/{len(requests)}")
            
            result = self.generate_voice(request)
            results.append(result)
        
        return results
    
    def get_voice_profiles(self) -> List[VoiceProfile]:
        """获取所有声线配置"""
        return list(self._voice_profiles.values())
    
    def get_voice_profile(self, profile_id: str) -> Optional[VoiceProfile]:
        """获取声线配置"""
        return self._voice_profiles.get(profile_id)
    
    def add_voice_profile(self, profile: VoiceProfile) -> bool:
        """添加声线配置"""
        with self._lock:
            self._voice_profiles[profile.id] = profile
            return True
    
    def remove_voice_profile(self, profile_id: str) -> bool:
        """移除声线配置"""
        with self._lock:
            if profile_id in self._voice_profiles:
                del self._voice_profiles[profile_id]
                return True
            return False
    
    def get_generation_result(self, request_id: str) -> Optional[VoiceGenerationResult]:
        """获取生成结果"""
        return self._results.get(request_id)

    def generate_audio(self, text: str, output_path: str = "",
                       voice_profile_id: str = "", **kwargs) -> Dict[str, Any]:
        """适配 AIEngine TTS：生成并可选写盘。

        传 ``guard=True`` 时启用 **TTS 正音守护**（V4.33.5）：长台词先**切段**
        （每段回到 TTS 稳定长度）再逐段合成、拼接 —— 治「长片段后面发音错 / 与字幕不符」。
        默认关（``guard`` 缺省 False），**行为与改造前逐字一致**。

        Returns:
            {"success": bool, "audio_path": str, "error": str, "guarded": bool, "segments": int}
        """
        import os
        import tempfile

        if not (text or "").strip():
            return {"success": False, "error": "文本为空"}

        profile_id = voice_profile_id or kwargs.get("voice", "")
        if not profile_id:
            for p in self._voice_profiles.values():
                if getattr(p, "is_default", False):
                    profile_id = p.id
                    break
            if not profile_id and self._voice_profiles:
                profile_id = next(iter(self._voice_profiles))

        # ── TTS 正音守护（可选）：长台词分段合成 ──
        if kwargs.get("guard"):
            guarded = self._generate_audio_guarded(
                text, output_path=output_path, voice_profile_id=profile_id, **kwargs)
            if guarded is not None:      # None = 无需分段（短句），继续走原路径
                return guarded

        request = VoiceGenerationRequest(
            text=text.strip(),
            voice_profile_id=profile_id,
            speed=float(kwargs.get("rate", kwargs.get("speed", 1.0)) or 1.0),
            volume=float(kwargs.get("volume", 1.0) or 1.0),
            language=str(kwargs.get("language", "zh") or "zh"),
        )
        result = self.generate_voice(request)
        if not result.success or result.audio_data is None:
            return {
                "success": False,
                "error": result.error_message or "TTS 生成失败",
            }

        path = (output_path or "").strip()
        if not path:
            fd, path = tempfile.mkstemp(suffix=".wav")
            os.close(fd)

        err = self._write_wav(path, result.audio_data, result.sample_rate)
        if err:
            return {"success": False, "error": f"写音频失败: {err}"}
        return {"success": True, "audio_path": path, "guarded": False}

    @staticmethod
    def _write_wav(path: str, audio_data: Any, sample_rate: int = 22050) -> Optional[str]:
        """把 float32 音频写成 16bit 单声道 wav。

        **返回 None 表示成功**，否则返回错误信息（便于调用方原样透出原因）。
        """
        import os
        import wave
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            pcm = np.asarray(audio_data, dtype=np.float32)
            pcm = np.clip(pcm, -1.0, 1.0)
            int16 = (pcm * 32767.0).astype(np.int16)
            with wave.open(path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(int(sample_rate or 22050))
                wf.writeframes(int16.tobytes())
            return None
        except Exception as e:
            return str(e)

    def _generate_audio_guarded(self, text: str, *, output_path: str = "",
                                voice_profile_id: str = "",
                                **kwargs) -> Optional[Dict[str, Any]]:
        """**TTS 正音守护**：长台词分段合成再拼接（V4.33.5）。

        为什么分段：AI 配音在**长片段**里会「前面正常、后面发音错 / 与字幕不符」——
        根因是长文本 TTS 注意力漂移（见 `app/core/ai/tts_guard.py` docstring）。
        每段回到「一句话」的长度即可消除，而**不必换 TTS 引擎**。

        ⚠️ **只切段、不喂 SSML 注音**：现有本地 TTS（gTTS / Coqui）不支持 SSML，
        喂进去会把 ``<phoneme>`` 标签当文字念出来。注音要等接入支持 SSML 的后端
        （如 edge-tts 的 SSML 模式）再启用 —— 宁可不注音，也不要念出标签。

        Returns:
            ``None`` → 无需分段（短句），调用方走原路径；
            ``dict`` → 分段结果（成功含 ``audio_path`` / ``segments``；失败含 ``error``）。
        """
        import os
        import tempfile

        from app.core.ai.tts_guard import plan_tts

        try:
            max_chars = int(kwargs.get("guard_max_chars") or 40)
        except (TypeError, ValueError):
            max_chars = 40
        # llm=None：此处不做多音字注音（见上方 SSML 说明），只借 TTS 守护的**切段**能力
        plan = plan_tts(text, max_chars=max_chars, llm=None)
        segs = [s for s in (plan.get("segments") or []) if str(s.get("text") or "").strip()]
        if len(segs) <= 1:
            return None

        parts: List[Any] = []
        for s in segs:
            req = VoiceGenerationRequest(
                text=str(s["text"]),
                voice_profile_id=voice_profile_id,
                speed=float(kwargs.get("rate", kwargs.get("speed", 1.0)) or 1.0),
                volume=float(kwargs.get("volume", 1.0) or 1.0),
                language=str(kwargs.get("language", "zh") or "zh"),
            )
            r = self.generate_voice(req)
            if not r.success or r.audio_data is None:
                idx = int(s.get("index", 0)) + 1
                return {"success": False, "guarded": True, "segments": len(segs),
                        "error": f"第 {idx}/{len(segs)} 段合成失败：{r.error_message or '未知原因'}"}
            parts.append(np.asarray(r.audio_data, dtype=np.float32))

        if not parts:
            return {"success": False, "guarded": True, "segments": 0, "error": "分段合成结果为空"}
        merged = np.concatenate(parts)

        path = (output_path or "").strip()
        if not path:
            fd, path = tempfile.mkstemp(suffix=".wav")
            os.close(fd)
        prof = self._voice_profiles.get(voice_profile_id)
        err = self._write_wav(path, merged, getattr(prof, "sample_rate", 22050) or 22050)
        if err:
            return {"success": False, "guarded": True, "segments": len(segs),
                    "error": f"写音频失败: {err}"}
        return {"success": True, "audio_path": path, "guarded": True, "segments": len(segs)}
    
    def clear_results(self):
        """清除生成结果"""
        with self._lock:
            self._results.clear()
    
    def export_profiles(self, file_path: str) -> bool:
        """导出声线配置"""
        try:
            data = {
                "profiles": [profile.to_dict() for profile in self._voice_profiles.values()],
                "total_profiles": len(self._voice_profiles),
                "exported_at": datetime.now().isoformat()
            }
            
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            return True
        except Exception as e:
            logger.error(f'导出声线配置失败: {e}')
            return False


# AIEngineEnhanced 等调用方使用 VoiceGenerator 名；保持兼容别名
VoiceGenerator = AIVoiceGenerator


class EffectRecommendationEngine:
    """特效推荐引擎"""
    
    def __init__(self):
        self._recommendations: Dict[str, Any] = {}
        self._lock = RLock()
        self._initialize_recommendations()
    
    def _initialize_recommendations(self):
        """初始化推荐规则"""
        self._recommendations = {
            "scene_to_effect": {
                "intro": ["fade_in", "brightness_increase"],
                "emotion": ["soft_light", "warm_filter"],
                "suspense": ["dark_tone", "glitch_effect"],
                "action": ["motion_blur", "speed_lines"],
                "climax": ["gold_rush", "energy_burst"],
                "outro": ["fade_out", "slow_motion"]
            },
            "emotion_to_effect": {
                "happy": ["bright", "saturated", "warm"],
                "sad": ["desaturated", "cool", "soft"],
                "angry": ["high_contrast", "red_tint", "sharp"],
                "surprised": ["flash", "zoom_in"],
                "neutral": ["no_effect", "subtle_enhancement"]
            },
            "genre_to_effect": {
                "counterattack": ["gold_rush", "energy_burst", "power_lines"],
                "emotion": ["soft_light", "dream_filter", "romantic_glow"],
                "suspense": ["dark_tone", "fog_effect", "mystery_overlay"],
                "selling": ["highlight", "focus_effect", "product_frame"],
                "comedy": ["cartoon_effect", "bounce", "color_pop"],
                "romance": ["soft_glow", "heart_overlay", "romantic_filter"],
                "action": ["motion_trail", "speed_lines", "impact_frame"]
            }
        }
    
    def recommend_effects(self, scene_type: str, emotion: str,
                       genre: str, confidence: float = 0.8) -> List[Dict[str, Any]]:
        """推荐特效"""
        with self._lock:
            try:
                recommendations = []
                
                # 基于场景类型推荐
                scene_effects = self._recommendations["scene_to_effect"].get(scene_type, [])
                for effect_id in scene_effects:
                    recommendations.append({
                        "effect_id": effect_id,
                        "source": "scene_type",
                        "confidence": confidence * 0.9,
                        "reason": f"场景类型为{scene_type}"
                    })
                
                # 基于情感推荐
                emotion_effects = self._recommendations["emotion_to_effect"].get(emotion, [])
                for effect_id in emotion_effects:
                    recommendations.append({
                        "effect_id": effect_id,
                        "source": "emotion",
                        "confidence": confidence * 0.85,
                        "reason": f"情感为{emotion}"
                    })
                
                # 基于类型推荐
                genre_effects = self._recommendations["genre_to_effect"].get(genre, [])
                for effect_id in genre_effects:
                    recommendations.append({
                        "effect_id": effect_id,
                        "source": "genre",
                        "confidence": confidence * 0.8,
                        "reason": f"类型为{genre}"
                    })
                
                # 去重并排序
                unique_recommendations = {}
                for rec in recommendations:
                    effect_id = rec["effect_id"]
                    if effect_id not in unique_recommendations:
                        unique_recommendations[effect_id] = rec
                    else:
                        if rec["confidence"] > unique_recommendations[effect_id]["confidence"]:
                            unique_recommendations[effect_id] = rec
                
                sorted_recommendations = sorted(
                    unique_recommendations.values(),
                    key=lambda x: (-x["confidence"], x["effect_id"])
                )
                
                return sorted_recommendations[:10]
                
            except Exception as e:
                logger.error(f'推荐特效失败: {e}')
                return []
    
    def get_effect_recommendations(self, **kwargs) -> List[Dict[str, Any]]:
        """获取特效推荐"""
        return self.recommend_effects(**kwargs)
    
    def add_custom_rule(self, rule_type: str, rule_name: str, effects: List[str]):
        """添加自定义推荐规则"""
        with self._lock:
            if rule_type not in self._recommendations:
                self._recommendations[rule_type] = {}
            
            self._recommendations[rule_type][rule_name] = effects
    
    def remove_custom_rule(self, rule_type: str, rule_name: str):
        """移除自定义推荐规则"""
        with self._lock:
            if rule_type in self._recommendations and rule_name in self._recommendations[rule_type]:
                del self._recommendations[rule_type][rule_name]
