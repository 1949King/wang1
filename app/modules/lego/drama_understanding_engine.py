"""
AI剧情理解引擎 - TOP 0级核心模块
===============================
实现4层理解：语音层、文本层、视觉层、决策层

这是整个软件的核心灵魂，决定了AI能否真正"看懂短剧"
"""

import os
import json
import asyncio
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import numpy as np

# 语音分析
try:
    import whisper
    WHISPER_AVAILABLE = True
except (ImportError, OSError) as e:
    print(f"⚠️ Whisper未加载: {e}")
    WHISPER_AVAILABLE = False

# 视觉分析
try:
    import cv2
    from PIL import Image
    VISION_AVAILABLE = True
except ImportError as e:
    print(f"⚠️ 视觉分析未加载: {e}")
    VISION_AVAILABLE = False

# 本地LLM
try:
    import ollama
    OLLAMA_AVAILABLE = True
except (ImportError, OSError) as e:
    print(f"⚠️ Ollama未加载: {e}")
    OLLAMA_AVAILABLE = False


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
    emotional_curve: List[Tuple[float, float]]  # 情绪曲线 (时间, 情绪值)
    pacing_analysis: Dict[str, Any]  # 节奏分析
    themes: List[str]  # 主题标签


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
        
        print(f"🎭 DramaUnderstandingEngine 初始化完成")
        print(f"   - Whisper模型: {whisper_model} {'(可用)' if WHISPER_AVAILABLE else '(不可用)'}")
        print(f"   - Ollama模型: {ollama_model} {'(可用)' if OLLAMA_AVAILABLE else '(不可用)'}")
        print(f"   - 视觉分析: {'(可用)' if VISION_AVAILABLE else '(不可用)'}")
        print(f"   - 本地AI优先: {use_local_ai}")
    
    def _load_whisper(self):
        """加载Whisper模型"""
        if self._whisper_model is None:
            print(f"🎤 加载Whisper模型: {self.whisper_model_name}")
            self._whisper_model = whisper.load_model(self.whisper_model_name)
        return self._whisper_model
    
    def analyze_video(self, video_path: str) -> DramaStructure:
        """
        完整分析视频 - 4层理解流程
        
        Args:
            video_path: 视频文件路径
            
        Returns:
            DramaStructure: 完整的剧情结构分析
        """
        print(f"\n{'='*60}")
        print(f"🎬 开始分析视频: {os.path.basename(video_path)}")
        print(f"{'='*60}\n")
        
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
        
        # 第4层：决策层分析
        print("\n🧠 第4层：决策分析...")
        drama_structure.scenes = scenes
        drama_structure = self._analyze_decision_layer(drama_structure)
        print(f"   ✓ 生成了情绪曲线")
        print(f"   ✓ 完成了节奏分析")
        
        print(f"\n{'='*60}")
        print(f"✅ 视频分析完成!")
        print(f"{'='*60}\n")
        
        return drama_structure
    
    def _analyze_audio_layer(self, video_path: str) -> List[DialogueSegment]:
        """
        第1层：语音层分析
        提取台词、情绪、停顿、语速
        """
        model = self._load_whisper()
        
        # 转录音频
        result = model.transcribe(
            video_path,
            language="zh",
            task="transcribe",
            verbose=False
        )
        
        dialogues = []
        for segment in result["segments"]:
            dialogue = DialogueSegment(
                start_time=segment["start"],
                end_time=segment["end"],
                speaker=segment.get("speaker", "未知"),
                text=segment["text"].strip(),
                emotion=self._detect_emotion_from_text(segment["text"]),
                volume=segment.get("avg_logprob", 0.0),
                speed=self._calculate_speech_speed(segment)
            )
            dialogues.append(dialogue)
        
        return dialogues
    
    def _detect_emotion_from_text(self, text: str) -> EmotionalTone:
        """从文本检测情绪"""
        # 简单的关键词匹配，实际应该使用情感分析模型
        emotion_keywords = {
            EmotionalTone.HAPPY: ["开心", "高兴", "笑", "哈哈", "太好了"],
            EmotionalTone.SAD: ["难过", "伤心", "哭", "泪", "痛苦"],
            EmotionalTone.ANGRY: ["生气", "愤怒", "混蛋", "可恶", "恨"],
            EmotionalTone.TENSE: ["紧张", "危险", "小心", "快跑", "救命"],
            EmotionalTone.ROMANTIC: ["喜欢", "爱", "心动", "甜蜜", "亲爱的"],
            EmotionalTone.SUSPENSE: ["秘密", "真相", "到底是谁", "为什么", "阴谋"],
            EmotionalTone.EXCITING: ["太棒了", "成功了", "赢了", "厉害", "牛逼"],
            EmotionalTone.WARM: ["温暖", "感动", "谢谢", "真好", "温馨"],
        }
        
        for emotion, keywords in emotion_keywords.items():
            if any(keyword in text for keyword in keywords):
                return emotion
        
        return EmotionalTone.HAPPY  # 默认
    
    def _calculate_speech_speed(self, segment: Dict) -> float:
        """计算语速"""
        duration = segment["end"] - segment["start"]
        word_count = len(segment["text"])
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
        
        # 调用本地LLM
        try:
            response = ollama.generate(
                model=self.ollama_model,
                prompt=analysis_prompt,
                format="json"
            )
            analysis_result = json.loads(response['response'])
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
        """分类场景类型"""
        if not dialogues:
            return SceneType.TRANSITION
        
        # 基于对话内容分类
        text = " ".join([d.text for d in dialogues])
        
        # 简单的关键词匹配
        if any(word in text for word in ["打", "杀", "冲", "跑", "追"]):
            return SceneType.ACTION
        elif any(word in text for word in ["爱", "喜欢", "吻", "抱", "亲爱的"]):
            return SceneType.EMOTIONAL
        elif any(word in text for word in ["混蛋", "该死", "恨", "滚", "闭嘴"]):
            return SceneType.CONFLICT
        elif len(dialogues) > 0:
            return SceneType.DIALOGUE
        
        return SceneType.TRANSITION
    
    def _analyze_decision_layer(self, drama: DramaStructure) -> DramaStructure:
        """
        第4层：决策层分析
        生成情绪曲线、节奏分析、主题提炼
        """
        # 生成情绪曲线
        emotional_curve = []
        for i, dialogue in enumerate(drama.dialogues):
            # 将情绪转换为数值
            emotion_values = {
                EmotionalTone.HAPPY: 0.8,
                EmotionalTone.SAD: -0.8,
                EmotionalTone.ANGRY: -0.6,
                EmotionalTone.TENSE: -0.4,
                EmotionalTone.ROMANTIC: 0.9,
                EmotionalTone.SUSPENSE: -0.3,
                EmotionalTone.EXCITING: 1.0,
                EmotionalTone.WARM: 0.7
            }
            value = emotion_values.get(dialogue.emotion, 0.0)
            emotional_curve.append((dialogue.start_time, value))
        
        drama.emotional_curve = emotional_curve
        
        # 节奏分析
        drama.pacing_analysis = self._analyze_pacing(drama)
        
        return drama
    
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
    
    def extract_highlights(self, drama: DramaStructure, 
                          target_duration: float = 60.0) -> List[HighlightClip]:
        """
        基于分析结果提取高光片段
        
        Args:
            drama: 剧情结构分析结果
            target_duration: 目标片段总时长（秒）
            
        Returns:
            List[HighlightClip]: 高光片段列表
        """
        print(f"\n✨ 开始提取高光片段（目标时长: {target_duration}秒）...")
        
        highlights = []
        
        # 策略1：基于情节点提取
        for plot_point in drama.plot_points:
            if plot_point.importance > 0.7:  # 只选重要情节点
                # 找到对应的场景
                for scene in drama.scenes:
                    if scene.start_time <= plot_point.timestamp <= scene.end_time:
                        clip = HighlightClip(
                            start_time=max(0, scene.start_time - 2),
                            end_time=min(drama.total_duration, scene.end_time + 2),
                            duration=scene.end_time - scene.start_time + 4,
                            clip_type=plot_point.plot_type.value,
                            score=plot_point.importance * 100,
                            reasons=[
                                f"重要情节点: {plot_point.description}",
                                f"情绪冲击力: {plot_point.emotional_impact:.2f}",
                                f"涉及角色: {', '.join(plot_point.characters_involved)}"
                            ],
                            suggested_title=self._generate_clip_title(plot_point, drama),
                            suggested_tags=self._generate_tags(plot_point, drama),
                            emotional_highlights=[scene.emotional_tone.value],
                            key_characters=plot_point.characters_involved
                        )
                        highlights.append(clip)
                        break
        
        # 策略2：基于情绪峰值提取
        if drama.emotional_curve:
            peaks = self._find_emotion_peaks(drama.emotional_curve)
            for peak_time, peak_value in peaks[:3]:  # 取前3个峰值
                # 找到对应的场景
                for scene in drama.scenes:
                    if scene.start_time <= peak_time <= scene.end_time:
                        clip = HighlightClip(
                            start_time=scene.start_time,
                            end_time=scene.end_time,
                            duration=scene.end_time - scene.start_time,
                            clip_type="情绪高潮",
                            score=abs(peak_value) * 100,
                            reasons=[
                                f"情绪峰值: {peak_value:.2f}",
                                f"场景类型: {scene.scene_type.value}",
                                "高情绪感染力"
                            ],
                            suggested_title=f"{scene.emotional_tone.value}片段",
                            suggested_tags=[scene.emotional_tone.value, "情绪", "高潮"],
                            emotional_highlights=[scene.emotional_tone.value],
                            key_characters=scene.characters
                        )
                        highlights.append(clip)
                        break
        
        # 策略3：基于场景类型提取
        priority_scenes = [SceneType.CONFLICT, SceneType.ACTION, SceneType.EMOTIONAL]
        for scene in drama.scenes:
            if scene.scene_type in priority_scenes:
                clip = HighlightClip(
                    start_time=scene.start_time,
                    end_time=scene.end_time,
                    duration=scene.end_time - scene.start_time,
                    clip_type=f"{scene.scene_type.value}场景",
                    score=75.0,
                    reasons=[
                        f"场景类型: {scene.scene_type.value}",
                        f"情绪基调: {scene.emotional_tone.value}",
                        "适合作为高光片段"
                    ],
                    suggested_title=f"精彩{scene.scene_type.value}",
                    suggested_tags=[scene.scene_type.value, scene.emotional_tone.value],
                    emotional_highlights=[scene.emotional_tone.value],
                    key_characters=scene.characters
                )
                highlights.append(clip)
        
        # 去重并排序
        highlights = self._deduplicate_highlights(highlights)
        highlights.sort(key=lambda x: x.score, reverse=True)
        
        # 根据目标时长筛选
        selected_highlights = []
        total_duration = 0
        for clip in highlights:
            if total_duration + clip.duration <= target_duration:
                selected_highlights.append(clip)
                total_duration += clip.duration
        
        print(f"   ✓ 提取了 {len(selected_highlights)} 个高光片段")
        print(f"   ✓ 总时长: {total_duration:.1f}秒")
        
        return selected_highlights
    
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
        
        # 提取高光片段
        highlights = self.extract_highlights(drama, config["duration"])
        
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
