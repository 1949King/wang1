"""
AI配音生成引擎
提供AI配音生成、声音克隆、多语言支持
"""

import numpy as np
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
from threading import RLock
from datetime import datetime
import json


import logging
logger = logging.getLogger("AI短剧编辑器.core.voice_generator")

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
    
    def to_dict(self) -> Dict:
        return {
            "request_id": self.request_id,
            "audio_path": self.audio_path,
            "duration": self.duration,
            "sample_rate": self.sample_rate,
            "success": self.success,
            "error_message": self.error_message,
            "generation_time": self.generation_time,
            "created_at": self.created_at
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
                
                if progress_callback:
                    progress_callback(80, "处理音频...")
                
                # 计算时长
                duration = len(audio_data) / voice_profile.sample_rate
                
                if progress_callback:
                    progress_callback(100, "生成完成")
                
                generation_time = time.time() - start_time
                
                result = VoiceGenerationResult(
                    request_id=str(time.time()),
                    audio_data=audio_data,
                    audio_path=None,
                    duration=duration,
                    sample_rate=voice_profile.sample_rate,
                    success=True,
                    generation_time=generation_time
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
    
    def _generate_tts_audio(self, request: VoiceGenerationRequest,
                             voice_profile: VoiceProfile) -> np.ndarray:
        """真实TTS语音生成 - 优先gTTS，回退edge-tts，最终回退正弦波"""
        text = request.text
        sample_rate = voice_profile.sample_rate
        text_length = len(text)
        duration_sec = max(1.0, text_length * 0.15)

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

        # 最终回退：正弦波合成
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
