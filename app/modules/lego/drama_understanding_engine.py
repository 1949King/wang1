"""
AI剧情理解引擎 - TOP 0级核心模块
===============================
实现4层理解：语音层、文本层、视觉层、决策层

这是整个软件的核心灵魂，决定了AI能否真正"看懂短剧"
"""

import os
import json
import asyncio
import logging
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import numpy as np

logger = logging.getLogger(__name__)

# 语音分析
WHISPER_AVAILABLE = False
_whisper_model_type = None

def _detect_whisper():
    """检测Whisper可用性，优先使用faster-whisper"""
    global WHISPER_AVAILABLE, _whisper_model_type
    try:
        import faster_whisper
        _whisper_model_type = "faster_whisper"
        WHISPER_AVAILABLE = True
        return True
    except ImportError:
        try:
            import whisper
            _whisper_model_type = "openai_whisper"
            WHISPER_AVAILABLE = True
            return True
        except (ImportError, OSError) as e:
            try:
                print(f"[warn] Whisper not loaded: {e}")
            except Exception as e:
                logger.debug("Whisper print fallback failed: %s", e)
            return False

_detect_whisper()

# 视觉分析
try:
    import cv2
    from PIL import Image
    VISION_AVAILABLE = True
except ImportError as e:
    print(f"⚠️ 视觉分析未加载: {e}")
    VISION_AVAILABLE = False

# 本地LLM
OLLAMA_AVAILABLE = False

def _check_ollama():
    """检测Ollama可用性，同时检查import和服务运行状态"""
    global OLLAMA_AVAILABLE
    try:
        import ollama
        client = ollama.Client()
        models = client.list()
        if models and models.get('models'):
            OLLAMA_AVAILABLE = True
            return True
        print("⚠️ Ollama服务已安装但未运行，请执行: ollama serve")
        return False
    except ImportError:
        print("⚠️ Ollama未安装: pip install ollama")
        return False
    except Exception as e:
        print(f"⚠️ Ollama连接失败: {e}")
        return False

_check_ollama()


class SceneType(Enum):
    """场景类型"""
    DIALOGUE = "对话"           # 对话场景
    ACTION = "动作"             # 动作场景
    EMOTIONAL = "情绪"          # 情绪场景
    CONFLICT = "冲突"           # 冲突场景
    TRANSITION = "转场"         # 转场场景
    FLASHBACK = "回忆"          # 回忆场景
    DREAM = "梦境"              # 梦境场景


class EmotionalTone(Enum):
    """情绪基调"""
    HAPPY = "开心"
    SAD = "悲伤"
    ANGRY = "愤怒"
    TENSE = "紧张"
    ROMANTIC = "浪漫"
    SUSPENSE = "悬疑"
    EXCITING = "激动"
    WARM = "温馨"


class PlotPointType(Enum):
    """情节点类型"""
    HOOK = "钩子"               # 吸引注意力的开场
    SETUP = "铺垫"              # 背景设定
    INCITING_INCIDENT = "触发事件"  # 触发事件
    RISING_ACTION = "上升动作"  # 情节升级
    CLIMAX = "高潮"             # 高潮
    FALLING_ACTION = "下降动作" # 情节回落
    RESOLUTION = "结局"         # 结局
    TWIST = "反转"              # 剧情反转
    CALLBACK = "callback"       # 呼应


@dataclass
class DialogueSegment:
    """对话片段"""
    start_time: float
    end_time: float
    speaker: str
    text: str
    emotion: EmotionalTone
    volume: float  # 音量级别
    speed: float   # 语速


@dataclass
class SceneSegment:
    """场景片段"""
    start_time: float
    end_time: float
    scene_type: SceneType
    characters: List[str]
    location: str
    emotional_tone: EmotionalTone
    key_moments: List[Dict] = field(default_factory=list)


@dataclass
class PlotPoint:
    """情节点"""
    timestamp: float
    plot_type: PlotPointType
    description: str
    importance: float  # 0-1，重要性评分
    characters_involved: List[str]
    emotional_impact: float  # 情绪冲击力


@dataclass
class Character:
    """角色信息"""
    name: str
    role_type: str  # protagonist, antagonist, supporting
    personality_traits: List[str]
    relationships: Dict[str, str]  # 与其他角色的关系
    appearance_times: List[Tuple[float, float]]
    key_lines: List[str]


@dataclass
class DramaStructure:
    """剧情结构分析"""
    title: str
    genre: str  # 类型：甜宠、虐恋、逆袭等
    total_duration: float
    characters: List[Character]
    plot_points: List[PlotPoint]
    scenes: List[SceneSegment]
    dialogues: List[DialogueSegment]
    emotional_curve: List[Tuple[float, float]]  # 情绪曲线 (时间, 复合情绪值 [-1,1])
    pacing_analysis: Dict[str, Any]  # 节奏分析
    themes: List[str]  # 主题标签
    # v2.0 新增：8维情绪向量 + LLM全局分析
    _emotion_vectors: Any = field(default_factory=list)    # List[np.ndarray] 8维融合向量
    emotional_arc_analysis: Dict = field(default_factory=dict)  # LLM全局情绪走势
    # v3.0 新增：情绪状态链
    emotion_journey: list = field(default_factory=list)  # List[Dict] 情绪旅程分析


@dataclass
class HighlightClip:
    """高光片段"""
    start_time: float
    end_time: float
    duration: float
    clip_type: str  # highlight, hook, cliffhanger, etc.
    score: float  # 质量评分 0-100
    reasons: List[str]  # 推荐理由
    suggested_title: str
    suggested_tags: List[str]
    emotional_highlights: List[str]
    key_characters: List[str]


@dataclass
class EditingStrategy:
    """剪辑策略"""
    target_platform: str  # 抖音、快手、小红书等
    video_style: str  # 高光剪辑、剧情解说、CP向等
    pacing: str  # fast, normal, slow
    bgm_style: str
    subtitle_style: str
    transition_style: str
    effects: List[str]
    highlights: List[HighlightClip]
    structure_template: str  # 结构模板


class DramaUnderstandingEngine:
    """
    TOP 0级AI剧情理解引擎
    
    实现4层理解：
    1. 语音层 - 提取台词、情绪、停顿
    2. 文本层 - 理解剧情结构、人物关系
    3. 视觉层 - 识别镜头、表情、场景
    4. 决策层 - 生成剪辑策略
    """
    
    def __init__(self, 
                 whisper_model: str = "base",
                 ollama_model: str = "qwen2.5",
                 use_local_ai: bool = True):
        """
        初始化引擎
        
        Args:
            whisper_model: Whisper模型大小 (tiny, base, small, medium, large)
            ollama_model: Ollama本地模型名称
            use_local_ai: 是否优先使用本地AI
        """
        self.whisper_model_name = whisper_model
        self.ollama_model = ollama_model
        self.use_local_ai = use_local_ai
        
        # 延迟加载模型
        self._whisper_model = None
        self._ollama_client = None
        self._yolo_model = None
        self._yolo_available = False

        print(f"🎭 DramaUnderstandingEngine 初始化完成")
        print(f"   - Whisper模型: {whisper_model} {'(可用)' if WHISPER_AVAILABLE else '(不可用)'}")
        print(f"   - Ollama模型: {ollama_model} {'(可用)' if OLLAMA_AVAILABLE else '(不可用)'}")
        print(f"   - 视觉分析: {'(可用)' if VISION_AVAILABLE else '(不可用)'}")
        print(f"   - 本地AI优先: {use_local_ai}")
    
    def _load_whisper(self):
        """加载Whisper模型，支持faster-whisper和openai-whisper"""
        if self._whisper_model is None:
            print(f"🎤 加载Whisper模型: {self.whisper_model_name} (类型: {_whisper_model_type})")
            if _whisper_model_type == "faster_whisper":
                import faster_whisper
                compute_type = "int8" if self.whisper_model_name in ("tiny", "base") else "float16"
                self._whisper_model = faster_whisper.WhisperModel(
                    self.whisper_model_name,
                    device="cpu",
                    compute_type=compute_type
                )
            elif _whisper_model_type == "openai_whisper":
                import whisper
                self._whisper_model = whisper.load_model(self.whisper_model_name)
        return self._whisper_model
    
    def analyze_video(self, video_path: str) -> DramaStructure:
        """
        完整分析视频 - 4层理解流程
        （带视频级缓存：同一文件重复导入时直接秒回）
        
        Args:
            video_path: 视频文件路径
            
        Returns:
            DramaStructure: 完整的剧情结构分析
        """
        print(f"\n{'='*60}")
        print(f"🎬 开始分析视频: {os.path.basename(video_path)}")
        print(f"{'='*60}\n")

        # 1) 尝试命中缓存 — 如果文件未被修改则直接复用
        try:
            from .character_cache import AnalysisCache
            cache = AnalysisCache()
            cached = cache.get_drama(video_path)
            if cached is not None:
                print(f"⚡ 命中缓存：跳过 Whisper + LLM，直接复用上次分析结果")
                print(f"   角色数: {len(cached.characters)}, 场景数: {len(cached.scenes)}")
                print(f"{'='*60}")
                return cached
        except Exception as cache_err:
            print(f"   ⚠️ 缓存读取异常（忽略）: {cache_err}")

        # 第1层：语音层分析
        print("🔊 第1层：语音分析...")
        dialogues = self._analyze_audio_layer(video_path)
        print(f"   ✓ 提取了 {len(dialogues)} 段对话")
        
        # 第2层：文本层分析
        print("\n📝 第2层：文本剧情分析...")
        drama_structure = self._analyze_text_layer(dialogues)
        print(f"   ✓ 识别了 {len(drama_structure.characters)} 个角色")
        print(f"   ✓ 分析了 {len(drama_structure.plot_points)} 个情节点")
        
        # 第3层：视觉层分析
        print("\n👁️ 第3层：视觉内容分析...")
        scenes = self._analyze_visual_layer(video_path, dialogues)
        print(f"   ✓ 识别了 {len(scenes)} 个场景")

        # 跨模态对齐：将 LLM 情节点时间戳修正到视觉场景边界
        if scenes and drama_structure.plot_points:
            aligned_count = self._align_plot_to_scenes(drama_structure.plot_points, scenes)
            if aligned_count > 0:
                print(f"   ✓ 跨模态对齐: {aligned_count} 个情节点已修正到场景边界")
        
        # 第4层：决策层分析
        print("\n🧠 第4层：决策分析...")
        drama_structure.scenes = scenes
        drama_structure = self._analyze_decision_layer(drama_structure, video_path)
        print(f"   ✓ 生成了多模态情绪曲线")
        print(f"   ✓ 完成了节奏分析")
        
        print(f"\n{'='*60}")
        print(f"✅ 视频分析完成!")
        print(f"{'='*60}\n")

        # 写入缓存（文件未变动时下次直接命中）
        try:
            from .character_cache import AnalysisCache
            cache = AnalysisCache()
            cache.put_drama(video_path, drama_structure)
            print(f"💾 分析结果已缓存（下次导入同一视频可秒回）")
        except Exception as cache_err:
            print(f"   ⚠️ 缓存写入异常（忽略）: {cache_err}")

        return drama_structure
    
    def _analyze_audio_layer(self, video_path: str) -> List[DialogueSegment]:
        """
        第1层：语音层分析
        提取台词、情绪、停顿、语速

        委托给统一的 whisper_asr 共享模块处理 Whisper 后端差异。
        """
        try:
            from app.core.ai.whisper_asr import transcribe, is_available
        except ImportError:
            try:
                from core.ai.whisper_asr import transcribe, is_available
            except ImportError:
                # 回退：内置 whisper 加载（保留旧逻辑作为 fallback）
                return self._analyze_audio_layer_fallback(video_path)

        if not is_available():
            return self._analyze_audio_layer_fallback(video_path)

        raw_segments = transcribe(
            video_path,
            model_size=self.whisper_model_name,
            language="zh",
        )

        dialogues = []
        for seg in raw_segments:
            start_t = seg.get("start", 0)
            end_t = seg.get("end", 0)
            text = seg.get("text", "").strip()
            if not text:
                continue
            dialogue = DialogueSegment(
                start_time=start_t,
                end_time=end_t,
                speaker="未知",
                text=text,
                emotion=self._detect_emotion_from_text(text),
                volume=seg.get("avg_logprob", 0.0),
                speed=self._calc_speech_speed(start_t, end_t, text)
            )
            dialogues.append(dialogue)

        return dialogues

    def _analyze_audio_layer_fallback(self, video_path: str) -> List[DialogueSegment]:
        """Whisper ASR 回退方案（内置模型加载，兼容旧环境）"""
        model = self._load_whisper()
        if model is None:
            return []

        if _whisper_model_type == "faster_whisper":
            segments_iter, _info = model.transcribe(
                video_path,
                language="zh",
                task="transcribe",
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=500),
            )
            raw_segments = list(segments_iter)
        else:
            result = model.transcribe(
                video_path,
                language="zh",
                task="transcribe",
                verbose=False
            )
            raw_segments = result.get("segments", [])

        dialogues = []
        for seg in raw_segments:
            if _whisper_model_type == "faster_whisper":
                start_t, end_t = seg.start, seg.end
                text = seg.text.strip() if seg.text else ""
                avg_logprob = getattr(seg, 'avg_logprob', 0.0)
            else:
                start_t = seg.get("start", 0)
                end_t = seg.get("end", 0)
                text = seg.get("text", "").strip()
                avg_logprob = seg.get("avg_logprob", 0.0)

            dialogue = DialogueSegment(
                start_time=start_t,
                end_time=end_t,
                speaker="未知",
                text=text,
                emotion=self._detect_emotion_from_text(text),
                volume=avg_logprob,
                speed=self._calc_speech_speed(start_t, end_t, text)
            )
            dialogues.append(dialogue)

        return dialogues

    # ═══════════════════════════════════════════════════════════════
    # 连续情绪向量 (v2.0)：取代离散 8 类枚举
    # 每个维度 0-1 连续值，表示该情绪的强度
    # 顺序: [开心, 悲伤, 愤怒, 紧张, 浪漫, 悬疑, 激动, 温馨]
    # ═══════════════════════════════════════════════════════════════
    EMOTION_DIMS = ["开心", "悲伤", "愤怒", "紧张", "浪漫", "悬疑", "激动", "温馨"]
    EMOTION_TO_INDEX = {e: i for i, e in enumerate(EMOTION_DIMS)}
    TONE_TO_DIM = {
        EmotionalTone.HAPPY: "开心", EmotionalTone.SAD: "悲伤",
        EmotionalTone.ANGRY: "愤怒", EmotionalTone.TENSE: "紧张",
        EmotionalTone.ROMANTIC: "浪漫", EmotionalTone.SUSPENSE: "悬疑",
        EmotionalTone.EXCITING: "激动", EmotionalTone.WARM: "温馨",
    }

    # 轻量 fallback 词表（仅 LLM 不可用时使用）
    _FALLBACK_EMOTION_WORDS = {
        "开心": ["开心", "高兴", "笑", "哈哈", "太好了", "棒", "好开心", "真开心",
                 "快乐", "欢喜", "兴奋", "喜悦", "欣慰", "满足", "幸福"],
        "悲伤": ["难过", "伤心", "哭", "泪", "痛苦", "难受", "悲伤", "绝望",
                 "心碎", "崩溃", "痛哭", "哀伤", "凄惨", "委屈", "心疼"],
        "愤怒": ["生气", "愤怒", "混蛋", "可恶", "恨", "该死", "滚", "闭嘴",
                 "怒", "气死", "暴怒", "恼火", "愤恨", "发火", "怒吼"],
        "紧张": ["紧张", "危险", "小心", "快跑", "救命", "完了", "糟糕",
                 "急", "来不及", "撑住", "别怕", "当心", "恐惧", "不安"],
        "浪漫": ["喜欢", "爱", "心动", "甜蜜", "亲爱的", "想你", "思念",
                 "温柔", "深情", "浪漫", "吻", "抱", "宠", "疼", "依偎"],
        "悬疑": ["秘密", "真相", "到底", "为什么", "阴谋", "居然", "原来",
                 "发现", "隐藏", "调查", "跟踪", "试探", "猜疑", "谜"],
        "激动": ["太棒了", "成功了", "赢了", "厉害", "牛逼", "终于", "太好了",
                 "激动", "热血", "燃", "痛快", "震撼", "震惊", "不可思议"],
        "温馨": ["温暖", "感动", "谢谢", "真好", "温馨", "安慰", "陪伴",
                 "照顾", "体贴", "理解", "原谅", "和解", "团", "家"],
    }

    # LLM 情绪分析 prompt 缓存
    _emotion_prompt_template = """分析以下短剧对白，输出每条对白的情绪向量。

情绪维度: {dims}
每条对白输出 JSON 格式，各维度 0.0-1.0 连续值，表示该情绪的强度。

对白列表:
{lines}

返回纯 JSON 数组，每个元素为 {{"index": 序号, "emotion_vector": [开心值, 悲伤值, 愤怒值, 紧张值, 浪漫值, 悬疑值, 激动值, 温馨值]}}"""

    def _detect_emotion_from_text(self, text: str) -> EmotionalTone:
        """
        从文本检测情绪（v2.0：LLM 优先 + 连续向量）。

        当 LLM 可用时返回连续向量中最强维度对应的情绪；
        LLM 不可用时降级为轻量关键词匹配。
        """
        vector = self._get_emotion_vector(text)
        if vector is None:
            return EmotionalTone.HAPPY
        idx = int(np.argmax(vector))
        dim_name = self.EMOTION_DIMS[idx]
        # 反向查找 dim_name 对应的 EmotionalTone 枚举值
        matched_tone = None
        for tone, dim in self.TONE_TO_DIM.items():
            if dim == dim_name:
                matched_tone = tone
                break
        return matched_tone if matched_tone else EmotionalTone.HAPPY

    def _get_emotion_vector(self, text: str) -> Optional[np.ndarray]:
        """
        获取文本的连续情绪向量 [8维, 0-1]。

        优先 LLM 语义分析，降级为关键词密度向量。
        """
        if not text or not text.strip():
            return None
        # 尝试 LLM
        if OLLAMA_AVAILABLE:
            try:
                return self._llm_emotion_vector(text)
            except Exception as e:
                logger.debug("LLM emotion vector failed, fallback to keyword: %s", e)
        # fallback
        return self._keyword_emotion_vector(text)

    def _keyword_emotion_vector(self, text: str) -> np.ndarray:
        """
        关键词密度向量 (fallback)：基于词频归一化生成 8 维向量。
        不再是"命中就定死一个情绪"，而是计算所有维度的密度分布。
        """
        vec = np.zeros(len(self.EMOTION_DIMS), dtype=np.float32)
        for dim_idx, dim_name in enumerate(self.EMOTION_DIMS):
            words = self._FALLBACK_EMOTION_WORDS.get(dim_name, [])
            count = sum(text.count(w) for w in words)
            vec[dim_idx] = float(count)
        # 归一化：除以总命中数，避免长文本天然高分
        total = vec.sum()
        if total > 0:
            vec = vec / total
        else:
            # 无任何命中时返回均匀小值，避免下游除以零
            vec[:] = 0.125
        return vec

    def _llm_emotion_vector(self, text: str) -> np.ndarray:
        """LLM 语义级情绪分析 → 连续向量"""
        try:
            from .ollama_client import OllamaClient
            client = OllamaClient()
            prompt = f"""分析这句短剧对白的情绪，返回 JSON。

情绪维度: {', '.join(self.EMOTION_DIMS)}
每个维度给 0.0-1.0 的强度值，总和为 1.0。

对白: {text[:200]}

只返回纯 JSON: {{"emotion_vector": [开心值, 悲伤值, 愤怒值, 紧张值, 浪漫值, 悬疑值, 激动值, 温馨值]}}"""
            response_parts = []
            for chunk in client.generate(
                model=self.ollama_model, prompt=prompt, format="json",
            ):
                response_parts.append(chunk)
            raw = "".join(response_parts).strip()
            if not raw:
                raise ValueError("LLM 空响应")
            result = json.loads(raw)
            vec = np.array(result.get("emotion_vector", []), dtype=np.float32)
            if len(vec) != len(self.EMOTION_DIMS):
                raise ValueError(f"向量维度错误: {len(vec)}")
            # 归一化
            total = vec.sum()
            if total > 0:
                vec = vec / total
            return vec
        except Exception:
            raise  # 让调用方 catch 后走 fallback

    def _batch_llm_emotion_vectors(self, texts: List[str],
                                    batch_size: int = 20) -> List[np.ndarray]:
        """
        批量 LLM 情绪分析：一次请求分析多句对白，大幅减少 API 调用次数。
        """
        if not OLLAMA_AVAILABLE or not texts:
            return [self._keyword_emotion_vector(t) for t in texts]

        results = [self._keyword_emotion_vector(t) for t in texts]  # 默认 fallback
        try:
            from .ollama_client import OllamaClient
            client = OllamaClient()

            for batch_start in range(0, len(texts), batch_size):
                batch_texts = texts[batch_start:batch_start + batch_size]
                lines_block = "\n".join(
                    f"[{i}] {t[:100]}" for i, t in enumerate(batch_texts, start=batch_start)
                )
                prompt = self._emotion_prompt_template.format(
                    dims=", ".join(self.EMOTION_DIMS),
                    lines=lines_block,
                )
                response_parts = []
                for chunk in client.generate(
                    model=self.ollama_model, prompt=prompt, format="json",
                ):
                    response_parts.append(chunk)
                raw = "".join(response_parts).strip()
                if not raw:
                    continue
                parsed = json.loads(raw)
                items = parsed if isinstance(parsed, list) else parsed.get("results", [])
                for item in items:
                    idx = int(item.get("index", -1))
                    vec = np.array(item.get("emotion_vector", []), dtype=np.float32)
                    if idx < 0 or idx >= len(results) or len(vec) != len(self.EMOTION_DIMS):
                        continue
                    total = vec.sum()
                    if total > 0:
                        vec = vec / total
                    results[idx] = vec
        except Exception as e:
            print(f"   ⚠️ 批量LLM情绪分析失败，使用关键词fallback: {e}")
        return results
    
    def _calc_speech_speed(self, start: float, end: float, text: str) -> float:
        """计算语速（字符/秒），接受显式参数以兼容两种 Whisper 后端"""
        duration = end - start
        word_count = len(text) if text else 0
        if duration > 0:
            return word_count / duration
        return 0.0
    
    def _analyze_text_layer(self, dialogues: List[DialogueSegment]) -> DramaStructure:
        """
        第2层：文本层分析
        理解剧情结构、人物关系、情节点
        """
        # 构建完整剧本文本
        full_script = "\n".join([d.text for d in dialogues])
        
        # 使用LLM分析剧情结构
        analysis_prompt = f"""
你是一位专业的短剧编剧和剧情分析师。请分析以下短剧剧本，提取关键信息：

【剧本内容】
{full_script[:4000]}  # 限制长度，避免超出模型上下文

请按以下JSON格式输出分析结果：
{{
    "title": "短剧标题",
    "genre": "类型（如：甜宠、虐恋、逆袭、悬疑等）",
    "characters": [
        {{
            "name": "角色名",
            "role_type": "角色类型（protagonist/antagonist/supporting）",
            "personality_traits": ["性格特点1", "性格特点2"],
            "relationships": {{"其他角色名": "关系描述"}}
        }}
    ],
    "plot_points": [
        {{
            "timestamp": "大致时间点（秒）",
            "plot_type": "情节点类型（HOOK/SETUP/INCITING_INCIDENT/RISING_ACTION/CLIMAX/FALLING_ACTION/RESOLUTION/TWIST）",
            "description": "描述",
            "importance": "重要性评分0-1",
            "characters_involved": ["涉及角色"],
            "emotional_impact": "情绪冲击力0-1"
        }}
    ],
    "themes": ["主题标签1", "主题标签2", "主题标签3"],
    "emotional_curve": "整体情绪走向描述"
}}

注意：
1. 角色分析要准确，识别主角、反派、配角
2. 情节点要完整，覆盖开端、发展、高潮、结局
3. 识别爽点、虐点、反转等关键剧情
"""
        
        # 调用本地LLM（通过项目 OllamaClient，兼容端口/代理配置）
        try:
            from .ollama_client import OllamaClient
            client = OllamaClient()
            # generate 返回 generator，收集完整响应
            response_parts = []
            for chunk in client.generate(
                model=self.ollama_model,
                prompt=analysis_prompt,
                format="json",
            ):
                response_parts.append(chunk)
            raw_response = "".join(response_parts)
            if not raw_response.strip():
                raise ValueError("Ollama 返回空响应")
            analysis_result = json.loads(raw_response)
        except Exception as e:
            print(f"   ⚠️ LLM分析失败，使用基础分析: {e}")
            analysis_result = self._basic_text_analysis(dialogues)
        
        # 构建DramaStructure
        characters = [
            Character(
                name=c["name"],
                role_type=c["role_type"],
                personality_traits=c.get("personality_traits", []),
                relationships=c.get("relationships", {}),
                appearance_times=[],
                key_lines=[]
            )
            for c in analysis_result.get("characters", [])
        ]
        
        plot_points = [
            PlotPoint(
                timestamp=float(p.get("timestamp", 0)),
                plot_type=PlotPointType(p.get("plot_type", "SETUP")),
                description=p.get("description", ""),
                importance=float(p.get("importance", 0.5)),
                characters_involved=p.get("characters_involved", []),
                emotional_impact=float(p.get("emotional_impact", 0.5))
            )
            for p in analysis_result.get("plot_points", [])
        ]
        
        return DramaStructure(
            title=analysis_result.get("title", "未知短剧"),
            genre=analysis_result.get("genre", "未知类型"),
            total_duration=dialogues[-1].end_time if dialogues else 0,
            characters=characters,
            plot_points=plot_points,
            scenes=[],
            dialogues=dialogues,
            emotional_curve=[],
            pacing_analysis={},
            themes=analysis_result.get("themes", [])
        )
    
    def _basic_text_analysis(self, dialogues: List[DialogueSegment]) -> Dict:
        """基础文本分析（LLM失败时的备用方案）"""
        # 提取角色名（简单的命名实体识别）
        characters = set()
        for d in dialogues:
            # 简单的角色名提取逻辑
            words = d.text.split()
            for word in words[:3]:  # 通常角色名在句子开头
                if len(word) >= 2 and len(word) <= 4:
                    characters.add(word)
        
        return {
            "title": "未知短剧",
            "genre": "未知类型",
            "characters": [{"name": name, "role_type": "supporting"} for name in list(characters)[:5]],
            "plot_points": [],
            "themes": []
        }
    
    def _analyze_visual_layer(self, video_path: str, 
                             dialogues: List[DialogueSegment]) -> List[SceneSegment]:
        """
        第3层：视觉层分析
        识别镜头类型、人物出现、场景切换
        """
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        scenes = []
        current_scene_start = 0
        last_frame = None
        scene_change_threshold = 30  # 场景变化阈值
        
        sample_interval = int(fps * 2)  # 每2秒采样一帧
        frame_count = 0
        
        print(f"   📊 视频信息: {total_frames}帧, {fps}fps, 采样间隔: {sample_interval}")
        
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            # 每隔一定帧数采样
            if frame_count % sample_interval == 0:
                current_time = frame_count / fps
                
                # 检测场景变化
                if last_frame is not None:
                    diff = self._calculate_frame_difference(frame, last_frame)
                    
                    if diff > scene_change_threshold:
                        # 场景变化，保存当前场景
                        scene = self._create_scene_segment(
                            current_scene_start, current_time, 
                            dialogues, frame
                        )
                        scenes.append(scene)
                        current_scene_start = current_time
                
                last_frame = frame.copy()
                if frame_count % (sample_interval * 3) == 0 and self._yolo_model is not None:
                    persons = self._detect_persons(frame)
                    if persons:
                        scene_persons[current_scene_start] = scene_persons.get(
                            current_scene_start, 0) + len(persons)
            
            frame_count += 1
            
            # 显示进度
            if frame_count % (sample_interval * 10) == 0:
                progress = (frame_count / total_frames) * 100
                print(f"   ⏳ 视觉分析进度: {progress:.1f}%")
        
        # 添加最后一个场景
        if current_scene_start < (frame_count / fps):
            final_scene = self._create_scene_segment(
                current_scene_start, frame_count / fps,
                dialogues, last_frame
            )
            scenes.append(final_scene)
        
        cap.release()
        return scenes

    def _load_yolo(self):
        """延迟加载YOLOv8模型"""
        if self._yolo_model is None and not self._yolo_available:
            try:
                from ultralytics import YOLO
                self._yolo_model = YOLO("yolov8n.pt")
                self._yolo_available = True
                print("   - YOLOv8人物检测: (可用)")
            except ImportError:
                print("   - YOLOv8人物检测: (未安装)")
            except Exception as e:
                print(f"   - YOLOv8加载失败: {e}")
        return self._yolo_model

    def _detect_persons(self, frame: np.ndarray) -> list:
        """YOLOv8人物检测"""
        model = self._load_yolo()
        if model is None:
            return []
        try:
            results = model(frame, classes=[0], verbose=False)
            if len(results) > 0 and results[0].boxes is not None:
                boxes = results[0].boxes.xyxy.tolist()
                result_list = []
                for i, box in enumerate(boxes):
                    confidence = float(results[0].boxes.conf[i]) if hasattr(results[0].boxes, 'conf') else 0.0
                    result_list.append({
                        'bbox': box,
                        'confidence': confidence,
                        'center': [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2]
                    })
                return result_list
            return []
        except Exception:
            return []
    
    def _calculate_frame_difference(self, frame1: np.ndarray, 
                                   frame2: np.ndarray) -> float:
        """计算两帧之间的差异"""
        # 转换为灰度图
        gray1 = cv2.cvtColor(frame1, cv2.COLOR_BGR2GRAY)
        gray2 = cv2.cvtColor(frame2, cv2.COLOR_BGR2GRAY)
        
        # 计算绝对差异
        diff = cv2.absdiff(gray1, gray2)
        
        # 返回平均差异值
        return np.mean(diff)
    
    def _create_scene_segment(self, start_time: float, end_time: float,
                             dialogues: List[DialogueSegment],
                             frame: np.ndarray) -> SceneSegment:
        """创建场景片段"""
        # 获取该时间段的对话
        scene_dialogues = [
            d for d in dialogues 
            if start_time <= d.start_time <= end_time
        ]
        
        # 分析场景类型
        scene_type = self._classify_scene_type(scene_dialogues, frame)
        
        # 提取角色
        characters = list(set([d.speaker for d in scene_dialogues]))
        
        # 分析情绪基调
        emotions = [d.emotion for d in scene_dialogues]
        emotional_tone = max(set(emotions), key=emotions.count) if emotions else EmotionalTone.HAPPY
        
        return SceneSegment(
            start_time=start_time,
            end_time=end_time,
            scene_type=scene_type,
            characters=characters,
            location="未知地点",  # 可以通过图像识别进一步分析
            emotional_tone=emotional_tone,
            key_moments=[{"time": d.start_time, "text": d.text} for d in scene_dialogues[:3]]
        )
    
    def _classify_scene_type(self, dialogues: List[DialogueSegment],
                            frame: np.ndarray) -> SceneType:
        """
        分类场景类型 (v2.0: LLM 语义分析 + 关键词 fallback)。

        不再仅靠几个关键词字典，而是：
        1. LLM 优先：理解对白语义后判断场景类型
        2. 关键词 fallback：LLM 不可用时使用扩展词表
        """
        if not dialogues:
            return SceneType.TRANSITION

        text = " ".join([d.text for d in dialogues])

        # LLM 优先
        if OLLAMA_AVAILABLE:
            try:
                return self._llm_classify_scene(text)
            except Exception as e:
                logger.debug("LLM scene classification failed, fallback to keyword: %s", e)

        # Fallback: 扩展关键词表（仍比原来好，但只做兜底）
        scene_keywords = {
            SceneType.ACTION: ["打", "杀", "冲", "跑", "追", "撞", "摔", "跳",
                              "抓", "推", "拉", "逃", "闯", "砍", "刺", "飞"],
            SceneType.EMOTIONAL: ["爱", "喜欢", "吻", "抱", "亲爱的", "想",
                                   "思念", "温柔", "浪漫", "心动", "深情", "宠"],
            SceneType.CONFLICT: ["混蛋", "该死", "恨", "滚", "闭嘴", "凭什么",
                                  "你以为", "不配", "报复", "算账", "走着瞧", "敢"],
            SceneType.DIALOGUE: ["说", "问", "告诉", "知道", "明白", "觉得",
                                  "认为", "听说", "讲", "聊"],
        }
        for stype, keywords in scene_keywords.items():
            if any(kw in text for kw in keywords):
                return stype

        return SceneType.DIALOGUE if dialogues else SceneType.TRANSITION

    def _llm_classify_scene(self, text: str) -> SceneType:
        """LLM 语义分析场景类型"""
        prompt = f"""分析以下短剧对白的场景类型，只返回一个分类词。

对白: {text[:300]}

可选分类: 对话, 动作, 情绪, 冲突, 转场, 回忆, 梦境
只返回分类词，不要其他内容。"""
        try:
            from .ollama_client import OllamaClient
            client = OllamaClient()
            response_parts = []
            for chunk in client.generate(model=self.ollama_model, prompt=prompt):
                response_parts.append(chunk)
            result = "".join(response_parts).strip()
            type_map = {
                "对话": SceneType.DIALOGUE, "动作": SceneType.ACTION,
                "情绪": SceneType.EMOTIONAL, "冲突": SceneType.CONFLICT,
                "转场": SceneType.TRANSITION, "回忆": SceneType.FLASHBACK,
                "梦境": SceneType.DREAM,
            }
            return type_map.get(result, SceneType.DIALOGUE)
        except Exception:
            raise
    
    def _align_plot_to_scenes(self, plot_points: List[PlotPoint],
                              scenes: List[SceneSegment]) -> int:
        """
        跨模态对齐：将 LLM 分析的情节点时间戳修正到视觉场景边界。

        LLM 给出的时间戳是估算的，可能落在场景中间。
        视觉层检测到的场景边界更精确。
        此方法将每个情节点的 timestamp 吸附到最近的场景 start_time，
        确保后续剪辑时不会切在场景中间。
        """
        aligned = 0
        snap_threshold = 2.0  # 2秒内才吸附，超过则保留原始值

        for pp in plot_points:
            best_scene = None
            best_dist = float("inf")
            for scene in scenes:
                dist_start = abs(pp.timestamp - scene.start_time)
                dist_end = abs(pp.timestamp - scene.end_time)
                if dist_start < best_dist:
                    best_dist = dist_start
                    best_scene = scene
                if dist_end < best_dist:
                    best_dist = dist_end
                    best_scene = scene

            if best_scene and best_dist <= snap_threshold:
                # 吸附到最近的场景边界
                if abs(pp.timestamp - best_scene.start_time) < abs(pp.timestamp - best_scene.end_time):
                    new_ts = best_scene.start_time
                else:
                    new_ts = best_scene.end_time

                if abs(pp.timestamp - new_ts) > 0.1:  # 有实际偏移才计数
                    pp.timestamp = new_ts
                    aligned += 1

        return aligned

    def _analyze_decision_layer(self, drama: DramaStructure,
                                video_path: Optional[str] = None) -> DramaStructure:
        """
        第4层：决策层分析 (v3.0 多模态融合)

        升级要点：
        1. 文本 LLM 情绪向量 + 音频声学情绪向量 → 双模态融合
        2. emotional_curve 从单标量升级为多维向量曲线
        3. 新增情绪状态链分析（替代简单反差峰检测）
        """
        texts = [d.text for d in drama.dialogues]

        # ── 1) 文本情绪：批量 LLM ──
        text_vectors = self._batch_llm_emotion_vectors(texts) if texts else []

        # ── 2) 音频情绪：librosa 声学分析 ──
        audio_vectors = []
        if video_path and drama.dialogues:
            try:
                from app.core.ai.audio_emotion_analyzer import AudioEmotionAnalyzer
                audio_analyzer = AudioEmotionAnalyzer()
                segments = [(d.start_time, d.end_time) for d in drama.dialogues]
                audio_vectors = audio_analyzer.analyze_segments(video_path, segments)
                if audio_vectors and len(audio_vectors) == len(drama.dialogues):
                    print(f"   🎵 音频情绪分析完成 ({len(audio_vectors)} 段)")
                else:
                    audio_vectors = []
            except Exception as e:
                print(f"   ⚠️ 音频情绪分析跳过: {e}")
                audio_vectors = []

        # ── 3) 多模态融合 + 构建多维情绪曲线 ──
        emotional_curve = []
        drama._emotion_vectors = []

        for i, dialogue in enumerate(drama.dialogues):
            # 文本向量
            if i < len(text_vectors) and text_vectors[i] is not None:
                tv = text_vectors[i]
            else:
                tv = self._keyword_emotion_vector(dialogue.text)

            # 音频向量
            if i < len(audio_vectors) and audio_vectors[i] is not None:
                av = audio_vectors[i]
            else:
                av = None

            # 融合：文本主导语义，音频补充表达强度
            if av is not None:
                # 加权融合：文本占 0.55，音频占 0.45
                fused_vec = tv * 0.55 + av * 0.45
                # 归一化
                total = fused_vec.sum()
                if total > 0:
                    fused_vec = fused_vec / total
            else:
                fused_vec = tv

            drama._emotion_vectors.append(fused_vec)

            # 保留向后兼容的标量情绪值（正负极性合成）
            pos_val = float(np.sum(fused_vec[[0, 4, 6, 7]]))   # 正极性
            neg_val = float(np.sum(fused_vec[[1, 2, 3, 5]]))   # 负极性
            composite = pos_val - neg_val

            emotional_curve.append((dialogue.start_time, composite))

        drama.emotional_curve = emotional_curve

        # ── 4) 情绪状态链分析 ──
        if len(drama._emotion_vectors) >= 5:
            drama.emotion_journey = self._analyze_emotion_journey(drama._emotion_vectors,
                                                                   drama.dialogues)
        else:
            drama.emotion_journey = []

        # ── 5) LLM 全局情绪走势分析 ──
        if OLLAMA_AVAILABLE and len(drama.dialogues) >= 10:
            try:
                drama.emotional_arc_analysis = self._llm_emotional_arc(drama)
            except Exception:
                drama.emotional_arc_analysis = {}

        # 节奏分析
        drama.pacing_analysis = self._analyze_pacing(drama)

        return drama

    def _analyze_emotion_journey(self, vectors: List[np.ndarray],
                                  dialogues: List) -> List[Dict]:
        """
        情绪状态链分析 (v3.0 新增)。

        不止检测"反差峰"，而是识别完整的情绪旅程结构：
        - calm → build → peak → plateau → release → reversal
        每种状态转换有不同的剪辑价值。

        Returns:
            List[{
                "type": "phase" | "transition",
                "start_idx": int, "end_idx": int,
                "start_sec": float, "end_sec": float,
                "dominant_emotion": str,
                "arousal": float,  # 唤醒度 0-1
                "valence": float,  # 效价 [-1, 1]
                "editing_value": float,  # 剪辑价值 0-1
            }]
        """
        if not vectors:
            return []

        n = len(vectors)
        # 计算每个时间点的 arousal 和 valence
        arousal = []
        valence = []
        for v in vectors:
            a = float(np.sum(v[[2, 3, 6]]))     # 愤怒+紧张+激动
            pos = float(np.sum(v[[0, 4, 6, 7]])) # 正极性
            neg = float(np.sum(v[[1, 2, 3, 5]])) # 负极性
            val = pos - neg
            arousal.append(a)
            valence.append(val)

        # 用 arousal 变化率检测阶段边界
        if n < 5:
            return []

        # 计算 arousal 的一阶差分
        arousal_arr = np.array(arousal)
        delta = np.diff(arousal_arr, prepend=arousal_arr[0])

        # 阶段分割：找出 arousal 的局部极值和拐点
        phases = []
        phase_start = 0
        current_trend = "stable"  # rising, falling, stable

        for i in range(1, n):
            if delta[i] > 0.05:
                trend = "rising"
            elif delta[i] < -0.05:
                trend = "falling"
            else:
                trend = "stable"

            if trend != current_trend and i - phase_start >= 2:
                # 阶段结束
                phases.append({
                    "type": "phase",
                    "start_idx": phase_start,
                    "end_idx": i - 1,
                    "start_sec": float(dialogues[phase_start].start_time),
                    "end_sec": float(dialogues[i - 1].end_time),
                    "trend": current_trend,
                    "avg_arousal": float(np.mean(arousal_arr[phase_start:i])),
                    "avg_valence": float(np.mean(valence[phase_start:i])),
                })
                phase_start = i
            current_trend = trend

        # 添加最后一个阶段
        if phase_start < n:
            phases.append({
                "type": "phase",
                "start_idx": phase_start,
                "end_idx": n - 1,
                "start_sec": float(dialogues[phase_start].start_time),
                "end_sec": float(dialogues[n - 1].end_time),
                "trend": current_trend,
                "avg_arousal": float(np.mean(arousal_arr[phase_start:])),
                "avg_valence": float(np.mean(valence[phase_start:])),
            })

        # 标注阶段间转换 + 计算剪辑价值
        journey = []
        for i, p in enumerate(phases):
            # 阶段类型标签
            a = p["avg_arousal"]
            v = p["avg_valence"]
            trend = p["trend"]

            if trend == "rising" and a > 0.6:
                label = "peak"       # 情绪高峰
                editing_value = 0.95
            elif trend == "rising":
                label = "build"      # 情绪攀升
                editing_value = 0.70
            elif trend == "falling" and a < 0.3:
                label = "release"    # 情绪释放
                editing_value = 0.40
            elif trend == "falling":
                label = "plateau"    # 情绪回落
                editing_value = 0.35
            else:
                label = "calm"       # 平稳
                editing_value = 0.20

            p["phase_label"] = label
            p["editing_value"] = editing_value

            # 检测阶段间转换类型
            if i > 0:
                prev = phases[i - 1]
                v_delta = v - prev["avg_valence"]
                a_delta = a - prev["avg_arousal"]

                if abs(v_delta) > 0.3 and prev["avg_valence"] * v < 0:
                    transition_type = "reversal"  # 情绪反转（正→负 或 负→正）
                    trans_value = 0.90
                elif a_delta > 0.2:
                    transition_type = "escalation"  # 升级
                    trans_value = 0.75
                elif a_delta < -0.2:
                    transition_type = "deescalation"  # 降级
                    trans_value = 0.30
                else:
                    transition_type = "continuation"
                    trans_value = 0.15

                journey.append({
                    "type": "transition",
                    "from_phase": prev["phase_label"],
                    "to_phase": label,
                    "transition_type": transition_type,
                    "at_sec": p["start_sec"],
                    "valence_delta": round(v_delta, 3),
                    "arousal_delta": round(a_delta, 3),
                    "editing_value": trans_value,
                })

            journey.append(p)

        return journey

    def _llm_emotional_arc(self, drama: DramaStructure) -> Dict:
        """
        LLM 分析全局情绪走势：识别情绪段落、转折点、高潮位置。

        这不是逐句分析，而是让 LLM 从宏观视角理解整部剧的情绪结构。
        """
        # 采样关键节点（开头/转折/结尾各取代表性对白）
        dialogues = drama.dialogues
        n = len(dialogues)
        sample_indices = [0, n // 4, n // 2, 3 * n // 4, n - 1] if n >= 5 else list(range(n))
        sample_indices = [i for i in sample_indices if i < n]

        sample_lines = "\n".join(
            f"[{dialogues[i].start_time:.0f}s] {dialogues[i].text[:80]}"
            for i in sample_indices
        )

        prompt = f"""分析以下短剧的情绪走势，输出 JSON。

对白采样（时间+内容）:
{sample_lines}

总时长: {drama.total_duration:.0f}秒
总对白数: {n}句

返回 JSON:
{{
    "emotion_phases": [
        {{"start_sec": 开始秒, "end_sec": 结束秒, "dominant_emotion": "主导情绪", "intensity": 0-1}}
    ],
    "turning_points": [
        {{"sec": 时间秒, "description": "情绪转折描述", "from_emotion": "从", "to_emotion": "到"}}
    ],
    "climax_zone": {{"start_sec": 开始, "end_sec": 结束, "description": "高潮区域描述"}},
    "overall_arc": "整体情绪弧线描述（一句话）"
}}"""
        try:
            from .ollama_client import OllamaClient
            client = OllamaClient()
            response_parts = []
            for chunk in client.generate(
                model=self.ollama_model, prompt=prompt, format="json",
            ):
                response_parts.append(chunk)
            raw = "".join(response_parts).strip()
            if raw:
                return json.loads(raw)
        except Exception as e:
            logger.debug("LLM JSON parse failed, return empty dict: %s", e)
        return {}
    
    def _analyze_pacing(self, drama: DramaStructure) -> Dict:
        """分析剧情节奏"""
        if not drama.dialogues:
            return {}
        
        # 计算平均场景时长
        scene_durations = [s.end_time - s.start_time for s in drama.scenes]
        avg_scene_duration = np.mean(scene_durations) if scene_durations else 0
        
        # 计算对话密度
        total_dialogue_time = sum([d.end_time - d.start_time for d in drama.dialogues])
        dialogue_density = total_dialogue_time / drama.total_duration if drama.total_duration > 0 else 0
        
        # 判断节奏类型
        if avg_scene_duration < 5:
            pacing_type = "fast"
            pacing_desc = "快节奏，适合短视频平台"
        elif avg_scene_duration < 15:
            pacing_type = "normal"
            pacing_desc = "中等节奏，适合剧情解说"
        else:
            pacing_type = "slow"
            pacing_desc = "慢节奏，适合深度剪辑"
        
        return {
            "pacing_type": pacing_type,
            "pacing_description": pacing_desc,
            "average_scene_duration": avg_scene_duration,
            "dialogue_density": dialogue_density,
            "scene_count": len(drama.scenes),
            "dialogue_count": len(drama.dialogues)
        }
    
    # ═══════════════════════════════════════════════════════════════
    # 内容类型 → ABCD 融合权重矩阵
    # A=剧情(Plot), B=情绪(Emotion), C=视觉(Scene Visual), D=爆款(Viral)
    # 不同剧种的高光判定维度权重不同
    # ═══════════════════════════════════════════════════════════════
    GENRE_WEIGHTS = {
        "甜宠":    {"A": 0.20, "B": 0.45, "C": 0.20, "D": 0.15},
        "逆袭":    {"A": 0.35, "B": 0.25, "C": 0.15, "D": 0.25},
        "虐恋":    {"A": 0.25, "B": 0.40, "C": 0.25, "D": 0.10},
        "悬疑":    {"A": 0.30, "B": 0.15, "C": 0.35, "D": 0.20},
        "爽文":    {"A": 0.25, "B": 0.30, "C": 0.15, "D": 0.30},
        "家庭伦理": {"A": 0.30, "B": 0.35, "C": 0.15, "D": 0.20},
        "古装":    {"A": 0.25, "B": 0.25, "C": 0.30, "D": 0.20},
        "都市":    {"A": 0.25, "B": 0.30, "C": 0.20, "D": 0.25},
    }
    DEFAULT_WEIGHTS = {"A": 0.25, "B": 0.30, "C": 0.25, "D": 0.20}

    def _get_genre_weights(self, genre: str) -> Dict[str, float]:
        """根据剧种获取 ABCD 融合权重"""
        genre_lower = genre.lower()
        for key, weights in self.GENRE_WEIGHTS.items():
            if key in genre_lower or genre_lower in key:
                return weights
        return dict(self.DEFAULT_WEIGHTS)

    def _build_timeline_score_map(self, drama: DramaStructure,
                                   weights: Dict[str, float]) -> Dict[float, Dict[str, float]]:
        """
        构建时间轴上的 ABCD 四维评分地图。
        返回：{timestamp: {"A": score, "B": score, "C": score, "D": score}}
        """
        timeline = {}
        # 以 0.5 秒为粒度构建时间网格
        grid_step = 0.5
        max_t = drama.total_duration
        grid_times = np.arange(0, max_t, grid_step)

        # 初始化
        for t in grid_times:
            timeline[round(t, 1)] = {"A": 0.0, "B": 0.0, "C": 0.0, "D": 0.0}

        # A 轴：剧情重要性 → 所在场景的时间段
        for pp in drama.plot_points:
            score = pp.importance * pp.emotional_impact  # 0-1 综合
            for scene in drama.scenes:
                if scene.start_time <= pp.timestamp <= scene.end_time:
                    for t in grid_times:
                        if scene.start_time <= t <= scene.end_time:
                            key = round(t, 1)
                            if key in timeline:
                                timeline[key]["A"] = max(timeline[key]["A"], score)

        # B 轴：多模态情绪评分（v3.0：用 8 维向量替代标量 abs()）
        emotion_vectors = getattr(drama, '_emotion_vectors', [])
        if emotion_vectors and drama.dialogues:
            dia_times = np.array([d.start_time for d in drama.dialogues])
            for t in grid_times:
                key = round(t, 1)
                if key not in timeline:
                    continue
                # 找到当前位置最近的情绪向量
                idx = np.argmin(np.abs(dia_times - t)) if len(dia_times) > 0 else 0
                if idx >= len(emotion_vectors):
                    continue
                vec = emotion_vectors[idx]

                # 多维情绪指标
                # B_arousal: 高唤醒情绪强度（愤怒+紧张+激动）
                arousal = float(np.sum(vec[[2, 3, 6]]))
                # B_intensity: 主导情绪的强度（峰值越高 = 情绪越浓烈）
                intensity = float(np.max(vec))
                # B_volatility: 情绪复杂度（多情绪并存 = 不确定性高 = 好看的反转点）
                sorted_vec = np.sort(vec)[::-1]
                if sorted_vec[0] > 0:
                    volatility = 1.0 - (sorted_vec[0] - sorted_vec[1]) / sorted_vec[0]
                else:
                    volatility = 0.0

                # 融合：高唤醒 + 高强度 + 适度复杂度
                b_score = 0.40 * arousal + 0.40 * intensity + 0.20 * volatility
                # 如果情绪极性正在转变（局部前后窗口的情绪反差大），加分
                local_contrast = 0.0
                pre_idx = max(0, idx - 2)
                post_idx = min(len(emotion_vectors) - 1, idx + 2)
                if pre_idx < post_idx and pre_idx < len(emotion_vectors) and post_idx < len(emotion_vectors):
                    # 向量余弦距离衡量情绪变化幅度
                    pre_vec = emotion_vectors[pre_idx]
                    post_vec = emotion_vectors[post_idx]
                    dot = max(0.0, float(np.dot(pre_vec, post_vec)))
                    cosine_dist = 1.0 - dot
                    local_contrast = cosine_dist * 0.3

                timeline[key]["B"] = min(1.0, b_score + local_contrast)

            # 增强：情绪旅程中的 reversal/escalation 点直接加分
            journey = getattr(drama, 'emotion_journey', [])
            for event in journey:
                if event.get("type") == "transition":
                    t_type = event.get("transition_type", "")
                    if t_type in ("reversal", "escalation"):
                        at_sec = event.get("at_sec", 0)
                        ev = event.get("editing_value", 0.5)
                        for t in grid_times:
                            if abs(t - at_sec) < 3.0:  # 转折点前后 3 秒
                                key = round(t, 1)
                                if key in timeline:
                                    timeline[key]["B"] = max(timeline[key]["B"], ev)
        elif drama.emotional_curve:
            # fallback：无多模态向量时回退到旧标量方式
            curve_times = np.array([t for t, _ in drama.emotional_curve])
            curve_vals = np.array([v for _, v in drama.emotional_curve])
            for t in grid_times:
                key = round(t, 1)
                if key in timeline:
                    idx = np.argmin(np.abs(curve_times - t)) if len(curve_times) > 0 else 0
                    raw_val = abs(curve_vals[idx]) if idx < len(curve_vals) else 0
                    timeline[key]["B"] = raw_val

        # C 轴：场景类型优先级
        scene_priority = {
            SceneType.CONFLICT: 0.9, SceneType.ACTION: 0.85,
            SceneType.EMOTIONAL: 0.8, SceneType.DIALOGUE: 0.5,
            SceneType.TRANSITION: 0.2, SceneType.FLASHBACK: 0.7,
            SceneType.DREAM: 0.6,
        }
        for scene in drama.scenes:
            c_score = scene_priority.get(scene.scene_type, 0.3)
            for t in grid_times:
                if scene.start_time <= t <= scene.end_time:
                    key = round(t, 1)
                    if key in timeline:
                        timeline[key]["C"] = max(timeline[key]["C"], c_score)

        # D 轴：ViralDetector 爆款基因（延迟导入）
        try:
            srt_lines = []
            for i, d in enumerate(drama.dialogues):
                h, m = int(d.start_time // 3600), int((d.start_time % 3600) // 60)
                s, ms = int(d.start_time % 60), int((d.start_time % 1) * 1000)
                eh, em = int(d.end_time // 3600), int((d.end_time % 3600) // 60)
                es, ems = int(d.end_time % 60), int((d.end_time % 1) * 1000)
                srt_lines.append(f"{i + 1}")
                srt_lines.append(
                    f"{h:02d}:{m:02d}:{s:02d},{ms:03d} --> "
                    f"{eh:02d}:{em:02d}:{es:02d},{ems:03d}"
                )
                srt_lines.append(d.text)
                srt_lines.append("")
            srt_text = "\n".join(srt_lines)
            from app.core.ai.viral_detector import quick_detect
            viral_segs = quick_detect(srt_text, drama.total_duration, top_k=10)
            for vs in viral_segs:
                vs_score = vs.get("total_score", 0) / 100.0
                vs_start = vs.get("start", 0)
                vs_end = vs.get("end", 0)
                for t in grid_times:
                    if vs_start <= t <= vs_end:
                        key = round(t, 1)
                        if key in timeline:
                            timeline[key]["D"] = max(timeline[key]["D"], vs_score)
        except Exception as e:
            logger.debug("D axis computation failed: %s", e)

        return timeline

    def _compute_fused_score(self, timeline: Dict, weights: Dict[str, float]) -> List[Tuple[float, float]]:
        """
        计算时间轴上每点的融合得分。
        返回：[(timestamp, fused_score), ...]
        """
        scores = []
        for t, dims in sorted(timeline.items()):
            fused = (
                weights.get("A", 0) * dims.get("A", 0) +
                weights.get("B", 0) * dims.get("B", 0) +
                weights.get("C", 0) * dims.get("C", 0) +
                weights.get("D", 0) * dims.get("D", 0)
            )
            scores.append((t, fused))
        return scores

    def _find_continuous_regions(self, scores: List[Tuple[float, float]],
                                  threshold: float = 0.35,
                                  min_duration: float = 3.0,
                                  max_duration: float = 30.0) -> List[Tuple[float, float, float]]:
        """
        在融合得分曲线上找到连续高分区域。
        返回：[(start, end, avg_score), ...]
        """
        if not scores:
            return []
        regions = []
        in_region = False
        region_start = None
        region_scores = []

        for t, score in scores:
            if score >= threshold:
                if not in_region:
                    in_region = True
                    region_start = t
                    region_scores = [score]
                else:
                    region_scores.append(score)
            else:
                if in_region:
                    in_region = False
                    dur = t - region_start
                    if min_duration <= dur <= max_duration:
                        avg = np.mean(region_scores)
                        regions.append((region_start, t, round(float(avg), 3)))
                    region_start = None
                    region_scores = []

        # 处理末尾区域
        if in_region and region_start is not None:
            last_t = scores[-1][0]
            dur = last_t - region_start
            if min_duration <= dur <= max_duration and region_scores:
                avg = np.mean(region_scores)
                regions.append((region_start, last_t, round(float(avg), 3)))

        return regions

    def _temporal_orchestrate(self, regions: List[Tuple[float, float, float]],
                               target_duration: float,
                               drama: DramaStructure) -> List[Tuple[float, float, float]]:
        """
        时序编排算法：避免片段碎片化，保证叙事连贯性。

        规则：
        1. 合并间隔 < 3s 且同场景的相邻区域
        2. 确保覆盖不同类型（钩子、高潮、反转）
        3. 按时间顺序输出（不是按分数排序）
        4. 总时长不超过目标
        """
        if not regions:
            return []

        # 规则1：合并过近的区域
        merged = [list(regions[0])]
        for r in regions[1:]:
            prev = merged[-1]
            gap = r[0] - prev[1]
            if gap < 3.0 and ((prev[1] - prev[0]) + (r[1] - r[0]) + gap) <= 40.0:
                # 合并：延长时间，取加权平均分
                total_dur = (prev[1] - prev[0]) + (r[1] - r[0])
                prev[2] = (prev[2] * (prev[1]-prev[0]) + r[2] * (r[1]-r[0])) / (total_dur + 1e-8)
                prev[1] = r[1]
            else:
                merged.append(list(r))

        # 规则2：限制总时长贪心选择
        merged.sort(key=lambda x: x[2], reverse=True)
        selected = []
        total = 0
        for s, e, score in merged:
            dur = e - s
            if total + dur <= target_duration:
                selected.append((s, e, score))
                total += dur

        # 规则3：按时间顺序排列
        selected.sort(key=lambda x: x[0])
        return selected

    def _detect_contrast_peaks(self, emotional_curve: List[Tuple[float, float]],
                                window_before: float = 4.0,
                                window_after: float = 2.0,
                                threshold: float = 0.35,
                                vectors: List[np.ndarray] = None,
                                journey: List[Dict] = None) -> List[Tuple[float, float]]:
        """
        检测情绪反差峰 (v3.0：向量距离 + 标量双重检测)。

        当 8 维向量可用时，用余弦距离衡量情绪变化幅度；
        向量不可用时回退到标量差。

        同时从 emotion_journey 中补充 LLM 识别的反转/升级点。
        """
        results = []
        use_vector = vectors is not None and len(vectors) >= 20

        # ── 方法1：向量余弦距离（更准确） ──
        if use_vector:
            samples_before = max(2, int(window_before / 2.0))
            samples_after = max(1, int(window_after / 2.0))
            for i in range(samples_before, len(vectors) - samples_after):
                before_vecs = vectors[i - samples_before:i]
                after_vecs = vectors[i:i + samples_after]
                before_avg = np.mean(before_vecs, axis=0)
                after_avg = np.mean(after_vecs, axis=0)
                # 余弦相似度 → 距离
                dot = max(0.0, float(np.dot(before_avg, after_avg)))
                cosine_dist = 1.0 - dot
                if cosine_dist > threshold:
                    t = float(emotional_curve[i][0]) if i < len(emotional_curve) else float(i)
                    results.append((t, round(cosine_dist, 3)))

        # ── 方法2：标量差（fallback / 补充） ──
        if not use_vector and len(emotional_curve) >= 20:
            times = np.array([t for t, _ in emotional_curve])
            values = np.array([v for _, v in emotional_curve])
            dt = times[1] - times[0] if len(times) > 1 else 0.5
            samples_before = max(1, int(window_before / dt))
            samples_after = max(1, int(window_after / dt))
            for i in range(samples_before, len(values) - samples_after):
                before = np.mean(values[i - samples_before:i])
                after = np.mean(values[i:i + samples_after])
                delta = after - before
                if abs(delta) > threshold:
                    results.append((float(times[i]), float(delta)))

        # ── 方法3：情绪旅程中的 reversal/escalation 点 ──
        if journey:
            for event in journey:
                if event.get("type") == "transition":
                    t_type = event.get("transition_type", "")
                    if t_type in ("reversal", "escalation"):
                        at_sec = event.get("at_sec", 0)
                        v_delta = abs(event.get("valence_delta", 0.5))
                        results.append((float(at_sec), min(1.0, v_delta * 1.5)))

        # 去重：相近时间点合并
        if len(results) > 1:
            results.sort(key=lambda x: x[0])
            deduped = [results[0]]
            for r in results[1:]:
                if r[0] - deduped[-1][0] > 2.0:
                    deduped.append(r)
                elif abs(r[1]) > abs(deduped[-1][1]):
                    deduped[-1] = r
            results = deduped

        results.sort(key=lambda x: abs(x[1]), reverse=True)
        return results

    def extract_highlights(self, drama: DramaStructure,
                          target_duration: float = 60.0,
                          genre: Optional[str] = None) -> List[HighlightClip]:
        """
        ABCD 融合矩阵：高光片段提取（v2.0 多模态融合版）。

        Args:
            drama: 剧情结构分析结果
            target_duration: 目标片段总时长（秒）
            genre: 覆盖剧种（None 则取 drama.genre）

        Returns:
            List[HighlightClip]: 质量排序的高光片段列表
        """
        effective_genre = genre or drama.genre or "未知"
        print(f"\n✨ ABCD融合矩阵高光提取（目标: {target_duration}s，剧种: {effective_genre}）...")

        # Step 0: 获取该剧种的融合权重
        weights = self._get_genre_weights(effective_genre)
        print(f"   📊 融合权重: A(剧情)={weights['A']:.2f} B(情绪)={weights['B']:.2f} "
              f"C(视觉)={weights['C']:.2f} D(爆款)={weights['D']:.2f}")

        # Step 1: 构建 ABCD 四维时间轴评分地图
        timeline = self._build_timeline_score_map(drama, weights)

        # Step 2: 计算融合得分曲线
        score_curve = self._compute_fused_score(timeline, weights)

        # Step 3: 找融合曲线上的连续高分区域
        regions = self._find_continuous_regions(score_curve, threshold=0.35,
                                                 min_duration=3.0, max_duration=30.0)
        print(f"   🔍 融合曲线检测到 {len(regions)} 个高分区域")

        # Step 4: 补充情绪反差峰（反转式高潮 · v3.0 向量距离版）
        if drama.emotional_curve:
            vectors = getattr(drama, '_emotion_vectors', None)
            journey = getattr(drama, 'emotion_journey', None)
            contrast_peaks = self._detect_contrast_peaks(
                drama.emotional_curve,
                vectors=vectors,
                journey=journey,
            )
            for cp_t, cp_delta in contrast_peaks[:5]:
                # 在反差峰附近追加窗口
                cp_start = max(0, cp_t - 2)
                cp_end = min(drama.total_duration, cp_t + 3)
                cp_score = min(1.0, abs(cp_delta) * 1.5)
                regions.append((cp_start, cp_end, cp_score))
            print(f"   ⚡ 向量反差峰 + 情绪旅程补充 {min(5, len(contrast_peaks))} 个片段")

        # Step 5: 时序编排（合并碎片 + 保证叙事连贯 + 控制总时长）
        orchestrated = self._temporal_orchestrate(regions, target_duration, drama)
        print(f"   🎬 时序编排后保留 {len(orchestrated)} 个片段")

        # Step 6: 构建 HighlightClip
        highlights = []
        for s, e, fused_score in orchestrated:
            # 找到该时间段覆盖的场景信息
            scene_types = []
            emotions = []
            chars = set()
            for scene in drama.scenes:
                if not (scene.end_time < s or scene.start_time > e):
                    scene_types.append(scene.scene_type.value)
                    emotions.append(scene.emotional_tone.value)
                    for c in scene.characters:
                        chars.add(c)

            # 找到该时间段包含的 plot_points 用于生成标题/标签
            relevant_pp = [
                pp for pp in drama.plot_points
                if s <= pp.timestamp <= e
            ]

            clip_type = "融合高光"
            reasons = [f"ABCD融合评分: {fused_score:.2f}"]
            if scene_types:
                reasons.append(f"场景: {', '.join(set(scene_types))}")
            if relevant_pp:
                reasons.append(f"剧情: {relevant_pp[0].description[:40]}")

            clip = HighlightClip(
                start_time=s,
                end_time=e,
                duration=e - s,
                clip_type=clip_type,
                score=min(100, fused_score * 100),
                reasons=reasons,
                suggested_title=self._generate_clip_title(
                    relevant_pp[0], drama
                ) if relevant_pp else f"高光片段 {s:.0f}s",
                suggested_tags=(self._generate_tags(relevant_pp[0], drama)
                                if relevant_pp else scene_types[:3]),
                emotional_highlights=emotions[:3],
                key_characters=list(chars)[:5],
            )
            highlights.append(clip)

        # Step 7: 按分数降序（保留时间顺序的可用性由上层控制）
        highlights.sort(key=lambda x: x.score, reverse=True)

        total = sum(h.duration for h in highlights)
        print(f"   ✅ 提取 {len(highlights)} 个高光片段，总时长 {total:.1f}s")
        return highlights
    
    def _find_emotion_peaks(self, emotional_curve: List[Tuple[float, float]], 
                           window_size: int = 5) -> List[Tuple[float, float]]:
        """找到情绪曲线的峰值点"""
        peaks = []
        values = [v for _, v in emotional_curve]
        
        for i in range(window_size, len(values) - window_size):
            window = values[i - window_size:i + window_size + 1]
            if values[i] == max(window) and values[i] > 0.5:  # 正向峰值
                peaks.append((emotional_curve[i][0], values[i]))
            elif values[i] == min(window) and values[i] < -0.5:  # 负向峰值
                peaks.append((emotional_curve[i][0], values[i]))
        
        # 按绝对值排序
        peaks.sort(key=lambda x: abs(x[1]), reverse=True)
        return peaks
    
    def _generate_clip_title(self, plot_point: PlotPoint, 
                            drama: DramaStructure) -> str:
        """生成片段标题"""
        titles = {
            PlotPointType.HOOK: "开场钩子",
            PlotPointType.CLIMAX: "剧情高潮",
            PlotPointType.TWIST: "神级反转",
            PlotPointType.CONFLICT: "激烈冲突",
            PlotPointType.RESOLUTION: "完美结局"
        }
        
        base_title = titles.get(plot_point.plot_type, "精彩片段")
        
        # 添加角色信息
        if plot_point.characters_involved:
            chars = ",".join(plot_point.characters_involved[:2])
            return f"{base_title} | {chars}"
        
        return base_title
    
    def _generate_tags(self, plot_point: PlotPoint, 
                      drama: DramaStructure) -> List[str]:
        """生成标签"""
        tags = [plot_point.plot_type.value, drama.genre]
        
        # 添加情绪标签
        if plot_point.emotional_impact > 0.7:
            tags.append("高情绪")
        
        # 添加角色标签
        tags.extend(plot_point.characters_involved[:2])
        
        return tags
    
    def _deduplicate_highlights(self, highlights: List[HighlightClip]) -> List[HighlightClip]:
        """去重高光片段"""
        unique_highlights = []
        
        for clip in highlights:
            # 检查是否与已选片段重叠
            is_duplicate = False
            for existing in unique_highlights:
                # 如果重叠超过50%，认为是重复
                overlap_start = max(clip.start_time, existing.start_time)
                overlap_end = min(clip.end_time, existing.end_time)
                overlap_duration = max(0, overlap_end - overlap_start)
                
                if overlap_duration > clip.duration * 0.5:
                    is_duplicate = True
                    # 保留得分更高的
                    if clip.score > existing.score:
                        unique_highlights.remove(existing)
                        unique_highlights.append(clip)
                    break
            
            if not is_duplicate:
                unique_highlights.append(clip)
        
        return unique_highlights
    
    def _llm_refine_highlights(self, drama: DramaStructure,
                               highlights: List[HighlightClip],
                               platform: str, style: str,
                               max_duration: float) -> List[HighlightClip]:
        """
        LLM 精修高光片段：用剧情理解重新评估每个片段的价值。

        这是决策层的核心——让 LLM 根据完整的剧情分析来决定
        哪些片段真正适合目标平台和风格，而不是仅靠硬编码规则。
        """
        # 构建片段摘要
        clips_desc = []
        for i, h in enumerate(highlights):
            clips_desc.append(
                f"[{i}] {h.start_time:.0f}s-{h.end_time:.0f}s "
                f"({h.duration:.0f}s) 类型:{h.clip_type} "
                f"原因:{'; '.join(h.reasons[:2])}"
            )
        clips_block = "\n".join(clips_desc)

        # 剧情摘要
        drama_summary = (
            f"剧名:{drama.title}, 类型:{drama.genre}, "
            f"总时长:{drama.total_duration:.0f}s, "
            f"场景数:{len(drama.scenes)}, 情节点:{len(drama.plot_points)}, "
            f"主题:{', '.join(drama.themes)}"
        )

        prompt = f"""你是{platform}{style}的专业剪辑师。以下是短剧分析结果和候选高光片段：

【剧情摘要】
{drama_summary}

【候选片段】（共{len(highlights)}个，总时长上限{max_duration}秒）
{clips_block}

【任务】
1. 根据{platform}平台特性和"{style}"风格，重新评估每个片段的重要性
2. 给每个片段一个 0-100 的最终分数（考虑：钩子强度、情绪冲击、叙事连贯性、平台适配）
3. 如果某片段不适合目标平台/风格，降低其分数
4. 确保选中片段的总时长不超过{max_duration}秒

只返回 JSON 数组，每个元素包含 index 和 score：
[{{"index": 0, "score": 85, "reason": "强钩子适合抖音开头"}}, ...]
不要返回其他文本。"""

        try:
            from .ollama_client import OllamaClient
            client = OllamaClient()
            parts = []
            for chunk in client.generate(
                model=self.ollama_model,
                prompt=prompt,
                format="json",
            ):
                parts.append(chunk)
            raw = "".join(parts).strip()
            if not raw:
                return highlights

            scores = json.loads(raw)
            if not isinstance(scores, list):
                return highlights

            # 应用 LLM 分数
            score_map = {}
            for item in scores:
                idx = int(item.get("index", -1))
                if 0 <= idx < len(highlights):
                    score_map[idx] = float(item.get("score", highlights[idx].score))
                    # 附加理由
                    reason = item.get("reason", "")
                    if reason and reason not in [r for r in highlights[idx].reasons]:
                        highlights[idx].reasons.append(f"[LLM] {reason}")

            for i, h in enumerate(highlights):
                if i in score_map:
                    h.score = score_map[i]

            # 重新按分数排序
            highlights.sort(key=lambda x: x.score, reverse=True)
            print(f"   ✓ LLM精修完成: {len(score_map)} 个片段重新评分")

        except Exception as e:
            print(f"   ⚠️ LLM精修异常（保留原始评分）: {e}")

        return highlights

    def generate_editing_strategy(self, drama: DramaStructure,
                                 target_platform: str = "抖音",
                                 video_style: str = "高光剪辑") -> EditingStrategy:
        """
        生成剪辑策略
        
        Args:
            drama: 剧情结构分析
            target_platform: 目标平台
            video_style: 视频风格
            
        Returns:
            EditingStrategy: 剪辑策略
        """
        print(f"\n🎯 生成剪辑策略（平台: {target_platform}, 风格: {video_style}）...")
        
        # 根据平台确定参数
        platform_configs = {
            "抖音": {
                "duration": 15,
                "pacing": "fast",
                "bgm_style": "高能电音",
                "subtitle_style": "大字紧凑",
                "transition": "闪切"
            },
            "快手": {
                "duration": 30,
                "pacing": "normal",
                "bgm_style": "节奏感强",
                "subtitle_style": "醒目",
                "transition": "淡入淡出"
            },
            "小红书": {
                "duration": 60,
                "pacing": "normal",
                "bgm_style": "温馨/治愈",
                "subtitle_style": "文艺",
                "transition": "柔和"
            }
        }
        
        config = platform_configs.get(target_platform, platform_configs["抖音"])
        
        # 根据视频风格调整
        style_configs = {
            "高光剪辑": {
                "structure": "钩子 → 爽点 → 反转 → 悬念",
                "effects": ["快速剪辑", "强调音效", "大字幕"]
            },
            "剧情解说": {
                "structure": "背景 → 冲突 → 高潮 → 结局",
                "effects": ["旁白", "转场", "背景音乐"]
            },
            "CP向混剪": {
                "structure": "相遇 → 甜蜜 → 虐心 → 重逢",
                "effects": ["慢动作", "柔光", "浪漫音乐"]
            }
        }
        
        style_config = style_configs.get(video_style, style_configs["高光剪辑"])
        
        # 提取高光片段（传入剧种以自适应权重）
        highlights = self.extract_highlights(drama, config["duration"],
                                             genre=drama.genre)

        # LLM 精修：用剧情理解重新评估每个片段的价值
        if OLLAMA_AVAILABLE and len(highlights) > 1:
            try:
                highlights = self._llm_refine_highlights(
                    drama, highlights, target_platform, video_style,
                    max_duration=config["duration"]
                )
            except Exception as e:
                print(f"   ⚠️ LLM精修失败（使用原始结果）: {e}")
        
        strategy = EditingStrategy(
            target_platform=target_platform,
            video_style=video_style,
            pacing=config["pacing"],
            bgm_style=config["bgm_style"],
            subtitle_style=config["subtitle_style"],
            transition_style=config["transition"],
            effects=style_config["effects"],
            highlights=highlights,
            structure_template=style_config["structure"]
        )
        
        print(f"   ✓ 策略生成完成")
        print(f"   - 结构模板: {strategy.structure_template}")
        print(f"   - 节奏: {strategy.pacing}")
        print(f"   - BGM风格: {strategy.bgm_style}")
        print(f"   - 高光片段: {len(strategy.highlights)}个")
        
        return strategy


# 使用示例
if __name__ == "__main__":
    # 初始化引擎
    engine = DramaUnderstandingEngine(
        whisper_model="base",
        ollama_model="qwen2.5",
        use_local_ai=True
    )
    
    # 分析视频
    video_path = "test_video.mp4"  # 替换为实际视频路径
    if os.path.exists(video_path):
        drama = engine.analyze_video(video_path)
        
        # 生成剪辑策略
        strategy = engine.generate_editing_strategy(
            drama,
            target_platform="抖音",
            video_style="高光剪辑"
        )
        
        # 打印结果
        print("\n" + "="*60)
        print("分析结果:")
        print(f"标题: {drama.title}")
        print(f"类型: {drama.genre}")
        print(f"角色: {[c.name for c in drama.characters]}")
        print(f"高光片段: {len(strategy.highlights)}个")
        for i, clip in enumerate(strategy.highlights[:3], 1):
            print(f"  {i}. {clip.suggested_title} ({clip.duration:.1f}s) - 评分: {clip.score:.1f}")
    else:
        print(f"视频文件不存在: {video_path}")
