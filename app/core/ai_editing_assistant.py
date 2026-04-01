"""
AI智能剪辑建议系统
提供智能剪辑建议、特效推荐、转场推荐等功能
"""

import numpy as np
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
from threading import RLock
from datetime import datetime
import json


class SuggestionType(Enum):
    """建议类型"""
    CUT = "cut"
    TRANSITION = "transition"
    EFFECT = "effect"
    MUSIC = "music"
    SUBTITLE = "subtitle"
    TIMELINE = "timeline"


class SceneType(Enum):
    """场景类型"""
    INTRO = "intro"
    DIALOGUE = "dialogue"
    ACTION = "action"
    EMOTION = "emotion"
    SUSPENSE = "suspense"
    CLIMAX = "climax"
    OUTRO = "outro"


class EmotionType(Enum):
    """情感类型"""
    HAPPY = "happy"
    SAD = "sad"
    ANGRY = "angry"
    SURPRISED = "surprised"
    NEUTRAL = "neutral"


@dataclass
class SceneAnalysis:
    """场景分析结果"""
    start_time: float
    end_time: float
    scene_type: SceneType
    emotion: EmotionType
    confidence: float
    description: str = ""
    suggested_actions: List[str] = field(default_factory=list)
    
    @property
    def duration(self) -> float:
        """场景时长"""
        return self.end_time - self.start_time


@dataclass
class EditSuggestion:
    """剪辑建议"""
    id: str
    suggestion_type: SuggestionType
    priority: int
    description: str
    confidence: float
    start_time: float
    end_time: float
    suggested_params: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "suggestion_type": self.suggestion_type.value,
            "priority": self.priority,
            "description": self.description,
            "confidence": self.confidence,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "suggested_params": self.suggested_params,
            "reason": self.reason,
            "created_at": self.created_at
        }


@dataclass
class EffectRecommendation:
    """特效推荐"""
    effect_id: str
    effect_name: str
    category: str
    confidence: float
    reason: str
    suggested_params: Dict[str, Any] = field(default_factory=dict)
    preview_url: Optional[str] = None


@dataclass
class TransitionRecommendation:
    """转场推荐"""
    transition_id: str
    transition_name: str
    confidence: float
    reason: str
    suggested_params: Dict[str, Any] = field(default_factory=dict)
    preview_url: Optional[str] = None


class SceneAnalyzer:
    """场景分析器"""
    
    def __init__(self):
        self._scenes: List[SceneAnalysis] = []
        self._lock = RLock()
    
    def analyze_scenes(self, video_frames: List[np.ndarray],
                     progress_callback: Optional[callable] = None) -> List[SceneAnalysis]:
        """分析视频场景"""
        if progress_callback:
            progress_callback(0, "开始分析场景...")
        
        with self._lock:
            try:
                self._scenes = []
                total_frames = len(video_frames)
                
                # 简化的场景检测算法
                # 实际应用中应使用更专业的视频分析库
                
                if progress_callback:
                    progress_callback(20, "计算帧差异...")
                
                # 计算帧间差异
                frame_diffs = []
                for i in range(1, len(video_frames)):
                    diff = np.abs(video_frames[i] - video_frames[i-1]).mean()
                    frame_diffs.append(diff)
                
                if progress_callback:
                    progress_callback(40, "检测场景边界...")
                
                # 检测场景边界
                threshold = np.mean(frame_diffs) + np.std(frame_diffs)
                scene_boundaries = [0]
                
                for i, diff in enumerate(frame_diffs):
                    if diff > threshold:
                        scene_boundaries.append(i + 1)
                
                scene_boundaries.append(len(video_frames))
                
                if progress_callback:
                    progress_callback(60, "分析场景内容...")
                
                # 分析每个场景
                for i in range(len(scene_boundaries) - 1):
                    start = scene_boundaries[i]
                    end = scene_boundaries[i + 1]
                    scene_frames = video_frames[start:end]
                    
                    # 分析场景特征
                    scene_type = self._classify_scene_type(scene_frames)
                    emotion = self._classify_emotion(scene_frames)
                    confidence = self._calculate_confidence(scene_frames)
                    
                    # 生成建议动作
                    suggested_actions = self._generate_suggested_actions(scene_type, emotion)
                    
                    scene = SceneAnalysis(
                        start_time=start / 30.0,  # 假设30fps
                        end_time=end / 30.0,
                        scene_type=scene_type,
                        emotion=emotion,
                        confidence=confidence,
                        description=self._generate_scene_description(scene_type, emotion),
                        suggested_actions=suggested_actions
                    )
                    
                    self._scenes.append(scene)
                    
                    if progress_callback:
                        progress = 60 + int(40 * (i + 1) / (len(scene_boundaries) - 1))
                        progress_callback(progress, f"分析场景 {i+1}/{len(scene_boundaries)-1}")
                
                if progress_callback:
                    progress_callback(100, "场景分析完成")
                
                return self._scenes
                
            except Exception as e:
                print(f"场景分析失败: {e}")
                return []
    
    def _classify_scene_type(self, frames: List[np.ndarray]) -> SceneType:
        """分类场景类型"""
        # 简化的场景分类
        # 实际应用中应使用机器学习模型
        
        avg_brightness = np.mean([np.mean(frame) for frame in frames])
        motion = np.mean([np.std(frame) for frame in frames])
        
        if motion > 50:
            return SceneType.ACTION
        elif avg_brightness > 180:
            return SceneType.INTRO
        elif avg_brightness < 80:
            return SceneType.SUSPENSE
        else:
            return SceneType.DIALOGUE
    
    def _classify_emotion(self, frames: List[np.ndarray]) -> EmotionType:
        """分类情感"""
        # 简化的情感分类
        # 实际应用中应使用更专业的情感分析
        
        avg_saturation = np.mean([np.std(frame, axis=2).mean() for frame in frames])
        avg_brightness = np.mean([np.mean(frame) for frame in frames])
        
        if avg_brightness > 200 and avg_saturation > 30:
            return EmotionType.HAPPY
        elif avg_brightness < 100:
            return EmotionType.SAD
        elif avg_saturation > 40:
            return EmotionType.ANGRY
        else:
            return EmotionType.NEUTRAL
    
    def _calculate_confidence(self, frames: List[np.ndarray]) -> float:
        """计算置信度"""
        # 简化的置信度计算
        motion_variance = np.var([np.std(frame) for frame in frames])
        confidence = min(1.0, motion_variance / 100.0)
        return confidence
    
    def _generate_suggested_actions(self, scene_type: SceneType, 
                                  emotion: EmotionType) -> List[str]:
        """生成建议动作"""
        actions = []
        
        if scene_type == SceneType.ACTION:
            actions.append("添加动态特效")
            actions.append("使用快速转场")
        elif scene_type == SceneType.EMOTION:
            actions.append("添加柔光特效")
            actions.append("使用淡入淡出转场")
        elif scene_type == SceneType.SUSPENSE:
            actions.append("添加暗调特效")
            actions.append("使用缓慢转场")
        elif scene_type == SceneType.DIALOGUE:
            actions.append("确保字幕清晰")
            actions.append("调整音量平衡")
        
        if emotion == EmotionType.HAPPY:
            actions.append("增加饱和度")
        elif emotion == EmotionType.SAD:
            actions.append("降低饱和度")
            actions.append("添加柔光")
        
        return actions
    
    def _generate_scene_description(self, scene_type: SceneType, 
                                emotion: EmotionType) -> str:
        """生成场景描述"""
        type_desc = {
            SceneType.INTRO: "开场场景",
            SceneType.DIALOGUE: "对话场景",
            SceneType.ACTION: "动作场景",
            SceneType.EMOTION: "情感场景",
            SceneType.SUSPENSE: "悬疑场景",
            SceneType.CLIMAX: "高潮场景",
            SceneType.OUTRO: "结尾场景"
        }.get(scene_type, "未知场景")
        
        emotion_desc = {
            EmotionType.HAPPY: "愉快",
            EmotionType.SAD: "悲伤",
            EmotionType.ANGRY: "愤怒",
            EmotionType.SURPRISED: "惊讶",
            EmotionType.NEUTRAL: "中性"
        }.get(emotion, "")
        
        if emotion_desc:
            return f"{type_desc}，情感{emotion_desc}"
        return type_desc
    
    def get_scenes(self) -> List[SceneAnalysis]:
        """获取分析的场景"""
        return self._scenes.copy()
    
    def clear_scenes(self):
        """清除场景"""
        with self._lock:
            self._scenes.clear()


class EditSuggestionEngine:
    """剪辑建议引擎"""
    
    def __init__(self):
        self._scene_analyzer = SceneAnalyzer()
        self._suggestions: List[EditSuggestion] = []
        self._effect_recommendations: List[EffectRecommendation] = []
        self._transition_recommendations: List[TransitionRecommendation] = []
        self._lock = RLock()
    
    def generate_suggestions(self, video_frames: List[np.ndarray],
                          progress_callback: Optional[callable] = None) -> List[EditSuggestion]:
        """生成剪辑建议"""
        if progress_callback:
            progress_callback(0, "开始生成建议...")
        
        with self._lock:
            try:
                # 分析场景
                scenes = self._scene_analyzer.analyze_scenes(video_frames, progress_callback)
                
                if progress_callback:
                    progress_callback(50, "生成剪辑建议...")
                
                # 基于场景生成建议
                self._suggestions = []
                
                for scene in scenes:
                    # 生成转场建议
                    if scene.scene_type in [SceneType.DIALOGUE, SceneType.EMOTION]:
                        suggestion = self._create_transition_suggestion(scene)
                        if suggestion:
                            self._suggestions.append(suggestion)
                    
                    # 生成特效建议
                    if scene.scene_type == SceneType.CLIMAX:
                        suggestion = self._create_effect_suggestion(scene)
                        if suggestion:
                            self._suggestions.append(suggestion)
                    
                    # 生成剪辑建议
                    if scene.duration > 10.0:
                        suggestion = self._create_cut_suggestion(scene)
                        if suggestion:
                            self._suggestions.append(suggestion)
                
                if progress_callback:
                    progress_callback(100, "建议生成完成")
                
                return self._suggestions
                
            except Exception as e:
                print(f"生成建议失败: {e}")
                return []
    
    def _create_transition_suggestion(self, scene: SceneAnalysis) -> Optional[EditSuggestion]:
        """创建转场建议"""
        import uuid
        suggestion = EditSuggestion(
            id=str(uuid.uuid4()),
            suggestion_type=SuggestionType.TRANSITION,
            priority=2,
            description=f"在{scene.start_time:.2f}s处添加转场",
            confidence=scene.confidence * 0.8,
            start_time=scene.end_time - 0.5,
            end_time=scene.end_time + 0.5,
            suggested_params={
                "transition_type": "fade",
                "duration": 1.0,
                "easing": "ease-in-out"
            },
            reason=f"场景类型为{scene.scene_type.value}，建议使用平滑转场"
        )
        return suggestion
    
    def _create_effect_suggestion(self, scene: SceneAnalysis) -> Optional[EditSuggestion]:
        """创建特效建议"""
        import uuid
        effect_types = {
            SceneType.CLIMAX: "counterattack_gold_rush",
            SceneType.EMOTION: "emotion_soft_light",
            SceneType.SUSPENSE: "suspense_dark_tone"
        }
        
        effect_id = effect_types.get(scene.scene_type)
        if not effect_id:
            return None
        
        suggestion = EditSuggestion(
            id=str(uuid.uuid4()),
            suggestion_type=SuggestionType.EFFECT,
            priority=1,
            description=f"在{scene.start_time:.2f}s处添加特效",
            confidence=scene.confidence * 0.9,
            start_time=scene.start_time,
            end_time=scene.end_time,
            suggested_params={
                "effect_id": effect_id,
                "intensity": 0.8,
                "duration": scene.duration
            },
            reason=f"场景类型为{scene.scene_type.value}，建议添加对应特效"
        )
        return suggestion
    
    def _create_cut_suggestion(self, scene: SceneAnalysis) -> Optional[EditSuggestion]:
        """创建剪辑建议"""
        import uuid
        suggestion = EditSuggestion(
            id=str(uuid.uuid4()),
            suggestion_type=SuggestionType.CUT,
            priority=3,
            description=f"场景时长{scene.duration:.2f}s过长，建议分割",
            confidence=scene.confidence * 0.7,
            start_time=scene.start_time + scene.duration / 2,
            end_time=scene.end_time,
            suggested_params={
                "cut_position": scene.start_time + scene.duration / 2,
                "preserve_audio": True
            },
            reason=f"场景时长超过10秒，建议分割以提高节奏"
        )
        return suggestion
    
    def get_suggestions(self, suggestion_type: Optional[SuggestionType] = None,
                       min_priority: Optional[int] = None) -> List[EditSuggestion]:
        """获取建议"""
        suggestions = self._suggestions.copy()
        
        if suggestion_type:
            suggestions = [s for s in suggestions if s.suggestion_type == suggestion_type]
        
        if min_priority:
            suggestions = [s for s in suggestions if s.priority <= min_priority]
        
        return sorted(suggestions, key=lambda x: (-x.priority, -x.confidence))
    
    def clear_suggestions(self):
        """清除建议"""
        with self._lock:
            self._suggestions.clear()
            self._effect_recommendations.clear()
            self._transition_recommendations.clear()
    
    def export_suggestions(self, file_path: str) -> bool:
        """导出建议"""
        try:
            data = {
                "suggestions": [s.to_dict() for s in self._suggestions],
                "scenes": [
                    {
                        "start_time": s.start_time,
                        "end_time": s.end_time,
                        "scene_type": s.scene_type.value,
                        "emotion": s.emotion.value,
                        "confidence": s.confidence,
                        "description": s.description,
                        "suggested_actions": s.suggested_actions
                    }
                    for s in self._scene_analyzer.get_scenes()
                ]
            }
            
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            return True
        except Exception as e:
            print(f"导出建议失败: {e}")
            return False


class AIEditingAssistant:
    """AI剪辑助手（整合所有AI功能）"""
    
    def __init__(self):
        self._suggestion_engine = EditSuggestionEngine()
        self._scene_analyzer = SceneAnalyzer()
        self._lock = RLock()
    
    def analyze_video(self, video_frames: List[np.ndarray],
                   progress_callback: Optional[callable] = None) -> Dict[str, Any]:
        """分析视频"""
        if progress_callback:
            progress_callback(0, "开始AI分析...")
        
        with self._lock:
            try:
                # 分析场景
                if progress_callback:
                    progress_callback(20, "分析场景...")
                scenes = self._scene_analyzer.analyze_scenes(video_frames, progress_callback)
                
                # 生成建议
                if progress_callback:
                    progress_callback(60, "生成建议...")
                suggestions = self._suggestion_engine.generate_suggestions(video_frames, progress_callback)
                
                # 生成统计信息
                if progress_callback:
                    progress_callback(80, "生成统计...")
                
                stats = {
                    "total_scenes": len(scenes),
                    "total_suggestions": len(suggestions),
                    "scene_types": {
                        "intro": sum(1 for s in scenes if s.scene_type == SceneType.INTRO),
                        "dialogue": sum(1 for s in scenes if s.scene_type == SceneType.DIALOGUE),
                        "action": sum(1 for s in scenes if s.scene_type == SceneType.ACTION),
                        "emotion": sum(1 for s in scenes if s.scene_type == SceneType.EMOTION),
                        "suspense": sum(1 for s in scenes if s.scene_type == SceneType.SUSPENSE),
                        "climax": sum(1 for s in scenes if s.scene_type == SceneType.CLIMAX),
                        "outro": sum(1 for s in scenes if s.scene_type == SceneType.OUTRO)
                    },
                    "suggestion_types": {
                        "cut": sum(1 for s in suggestions if s.suggestion_type == SuggestionType.CUT),
                        "transition": sum(1 for s in suggestions if s.suggestion_type == SuggestionType.TRANSITION),
                        "effect": sum(1 for s in suggestions if s.suggestion_type == SuggestionType.EFFECT)
                    },
                    "average_confidence": np.mean([s.confidence for s in suggestions]) if suggestions else 0.0
                }
                
                if progress_callback:
                    progress_callback(100, "AI分析完成")
                
                return {
                    "scenes": scenes,
                    "suggestions": suggestions,
                    "statistics": stats
                }
                
            except Exception as e:
                print(f"AI分析失败: {e}")
                return {
                    "scenes": [],
                    "suggestions": [],
                    "statistics": {}
                }
    
    def get_scenes(self) -> List[SceneAnalysis]:
        """获取场景"""
        return self._scene_analyzer.get_scenes()
    
    def get_suggestions(self, **kwargs) -> List[EditSuggestion]:
        """获取建议"""
        return self._suggestion_engine.get_suggestions(**kwargs)
    
    def clear_analysis(self):
        """清除分析结果"""
        self._scene_analyzer.clear_scenes()
        self._suggestion_engine.clear_suggestions()
