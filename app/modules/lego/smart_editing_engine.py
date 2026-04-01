"""
智能剪辑引擎 - 高级功能模块
============================
包含：
1. 智能分镜重组 - 基于剧情理解重新排列镜头
2. 自动卡点剪辑 - 根据音乐节奏自动剪辑
3. 情绪匹配转场 - 根据情绪变化选择转场效果
4. 智能字幕样式 - 根据内容自动选择字幕样式
"""

import os
import json
import numpy as np
from typing import Dict, List, Tuple, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
import tempfile
import shutil

from .professional_video_engine import ProfessionalVideoEngine, VideoTask
from .drama_understanding_engine import DramaStructure, EmotionalTone, SceneType


class TransitionType(Enum):
    """转场类型"""
    CUT = "硬切"                    # 快速切换，适合紧张场景
    FADE = "淡入淡出"               # 柔和过渡，适合情感场景
    DISSOLVE = "溶解"               # 渐变过渡，适合时间流逝
    WIPE = "擦除"                   # 方向性过渡，适合动作场景
    ZOOM = "缩放"                   # 放大/缩小，适合强调
    SLIDE = "滑动"                  # 滑动过渡，适合连续动作
    GLITCH = "故障"                 # 故障效果，适合冲突/反转
    FLASH = "闪白"                  # 闪白效果，适合高潮/冲击


class BeatPattern(Enum):
    """卡点模式"""
    EVERY_BEAT = "每拍"             # 每个节拍都切
    EVERY_2_BEATS = "每2拍"         # 每2拍切一次
    EVERY_4_BEATS = "每4拍"         # 每4拍切一次（常见）
    ACCENT_ONLY = "重音点"          # 只在重音点切
    BUILD_UP = "渐强"               # 渐强时加快切换
    DROP = "Drop点"                 # 在Drop点切换


@dataclass
class Shot:
    """镜头/分镜"""
    start_time: float
    end_time: float
    shot_type: str                  # 特写、中景、全景等
    characters: List[str]
    emotional_tone: EmotionalTone
    importance: float               # 重要性评分
    visual_features: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EditingSequence:
    """剪辑序列"""
    shots: List[Shot]
    transitions: List[TransitionType]
    music_beats: List[float]        # 音乐节拍点
    total_duration: float
    pacing: str                     # fast, normal, slow


@dataclass
class SubtitleStyle:
    """字幕样式"""
    name: str
    font_family: str
    font_size: int
    font_color: str
    outline_color: str
    outline_width: int
    background_color: Optional[str]
    position: str                   # top, middle, bottom
    animation: Optional[str]        # 动画效果


class SmartEditingEngine:
    """
    智能剪辑引擎
    
    高级功能：
    1. 智能分镜重组 - 基于剧情理解优化镜头顺序
    2. 自动卡点剪辑 - 根据音乐节奏自动剪辑
    3. 情绪匹配转场 - 智能选择转场效果
    4. 智能字幕样式 - 根据内容自动选择字幕样式
    """
    
    # 转场效果与情绪的匹配规则
    EMOTION_TRANSITION_MAP = {
        EmotionalTone.HAPPY: [TransitionType.FADE, TransitionType.ZOOM],
        EmotionalTone.SAD: [TransitionType.FADE, TransitionType.DISSOLVE],
        EmotionalTone.ANGRY: [TransitionType.CUT, TransitionType.GLITCH],
        EmotionalTone.TENSE: [TransitionType.CUT, TransitionType.FLASH],
        EmotionalTone.ROMANTIC: [TransitionType.FADE, TransitionType.DISSOLVE],
        EmotionalTone.SUSPENSE: [TransitionType.CUT, TransitionType.WIPE],
        EmotionalTone.EXCITING: [TransitionType.CUT, TransitionType.FLASH, TransitionType.ZOOM],
        EmotionalTone.WARM: [TransitionType.FADE, TransitionType.DISSOLVE],
    }
    
    # 字幕样式库
    SUBTITLE_STYLES = {
        "默认": SubtitleStyle(
            name="默认",
            font_family="Arial",
            font_size=24,
            font_color="white",
            outline_color="black",
            outline_width=2,
            background_color=None,
            position="bottom",
            animation=None
        ),
        "抖音爆款": SubtitleStyle(
            name="抖音爆款",
            font_family="PingFang SC",
            font_size=32,
            font_color="yellow",
            outline_color="red",
            outline_width=3,
            background_color=None,
            position="bottom",
            animation="pop"
        ),
        "情绪强调": SubtitleStyle(
            name="情绪强调",
            font_family="Arial Black",
            font_size=36,
            font_color="white",
            outline_color="black",
            outline_width=4,
            background_color="rgba(0,0,0,0.5)",
            position="middle",
            animation="shake"
        ),
        "文艺清新": SubtitleStyle(
            name="文艺清新",
            font_family="STKaiti",
            font_size=28,
            font_color="white",
            outline_color="none",
            outline_width=0,
            background_color=None,
            position="bottom",
            animation="fade"
        ),
        "高能预警": SubtitleStyle(
            name="高能预警",
            font_family="Impact",
            font_size=40,
            font_color="red",
            outline_color="yellow",
            outline_width=3,
            background_color="black",
            position="middle",
            animation="flash"
        )
    }
    
    def __init__(self):
        """初始化引擎"""
        self.video_engine = ProfessionalVideoEngine()
        print("🎬 智能剪辑引擎初始化完成")
        print(f"   已加载 {len(self.SUBTITLE_STYLES)} 种字幕样式")
        print(f"   已加载 {len(self.EMOTION_TRANSITION_MAP)} 种情绪转场规则")
    
    def smart_shot_reordering(self, drama: DramaStructure, 
                             target_duration: float = 60.0) -> EditingSequence:
        """
        智能分镜重组
        
        基于剧情理解优化镜头顺序，提升完播率和吸引力
        
        Args:
            drama: 剧情结构分析
            target_duration: 目标时长
            
        Returns:
            EditingSequence: 优化后的剪辑序列
        """
        print("\n🎬 开始智能分镜重组...")
        
        # Step 1: 提取所有镜头
        shots = self._extract_shots(drama)
        print(f"   提取了 {len(shots)} 个镜头")
        
        # Step 2: 根据剧情重要性排序
        shots = self._sort_by_importance(shots)
        
        # Step 3: 应用剪辑策略
        shots = self._apply_editing_strategy(shots, target_duration)
        
        # Step 4: 选择转场效果
        transitions = self._select_transitions(shots)
        
        # Step 5: 计算总时长和节奏
        total_duration = sum([s.end_time - s.start_time for s in shots])
        pacing = self._analyze_pacing(shots)
        
        sequence = EditingSequence(
            shots=shots,
            transitions=transitions,
            music_beats=[],
            total_duration=total_duration,
            pacing=pacing
        )
        
        print(f"   ✓ 重组完成: {len(shots)} 个镜头, 总时长 {total_duration:.1f}s")
        print(f"   节奏: {pacing}")
        
        return sequence
    
    def _extract_shots(self, drama: DramaStructure) -> List[Shot]:
        """从剧情结构中提取镜头"""
        shots = []
        
        for scene in drama.scenes:
            shot = Shot(
                start_time=scene.start_time,
                end_time=scene.end_time,
                shot_type=self._classify_shot_type(scene),
                characters=scene.characters,
                emotional_tone=scene.emotional_tone,
                importance=self._calculate_importance(scene, drama.plot_points),
                visual_features={}
            )
            shots.append(shot)
        
        return shots
    
    def _classify_shot_type(self, scene) -> str:
        """分类镜头类型"""
        duration = scene.end_time - scene.start_time
        
        if duration < 2:
            return "特写"
        elif duration < 5:
            return "近景"
        elif duration < 10:
            return "中景"
        else:
            return "全景"
    
    def _calculate_importance(self, scene, plot_points) -> float:
        """计算镜头重要性"""
        importance = 0.5  # 基础重要性
        
        # 检查是否包含情节点
        for point in plot_points:
            if scene.start_time <= point.timestamp <= scene.end_time:
                importance += point.importance * 0.3
        
        # 根据场景类型调整
        if scene.scene_type in [SceneType.CONFLICT, SceneType.ACTION]:
            importance += 0.2
        elif scene.scene_type == SceneType.EMOTIONAL:
            importance += 0.15
        
        return min(1.0, importance)
    
    def _sort_by_importance(self, shots: List[Shot]) -> List[Shot]:
        """按重要性排序"""
        # 使用黄金3秒法则：最重要的镜头放在开头
        sorted_shots = sorted(shots, key=lambda s: s.importance, reverse=True)
        
        # 重新排列：最高重要性放第1位，第2高的放最后（悬念）
        if len(sorted_shots) >= 3:
            first = sorted_shots[0]
            last = sorted_shots[1]
            middle = sorted_shots[2:]
            sorted_shots = [first] + middle + [last]
        
        return sorted_shots
    
    def _apply_editing_strategy(self, shots: List[Shot], 
                               target_duration: float) -> List[Shot]:
        """应用剪辑策略"""
        # 根据目标时长筛选镜头
        selected_shots = []
        current_duration = 0
        
        for shot in shots:
            shot_duration = shot.end_time - shot.start_time
            
            if current_duration + shot_duration <= target_duration:
                selected_shots.append(shot)
                current_duration += shot_duration
            else:
                # 如果接近目标时长，可以稍微超出一点
                if current_duration < target_duration * 0.9:
                    selected_shots.append(shot)
                break
        
        return selected_shots
    
    def _select_transitions(self, shots: List[Shot]) -> List[TransitionType]:
        """为镜头选择转场效果"""
        transitions = []
        
        for i in range(len(shots) - 1):
            current_shot = shots[i]
            next_shot = shots[i + 1]
            
            # 根据情绪变化选择转场
            if current_shot.emotional_tone != next_shot.emotional_tone:
                # 情绪变化时使用柔和转场
                transition = TransitionType.FADE
            else:
                # 根据情绪类型选择
                emotion_transitions = self.EMOTION_TRANSITION_MAP.get(
                    current_shot.emotional_tone, 
                    [TransitionType.CUT]
                )
                transition = emotion_transitions[0]  # 选择第一个匹配的
            
            transitions.append(transition)
        
        # 最后一个镜头不需要转场
        if shots:
            transitions.append(TransitionType.CUT)
        
        return transitions
    
    def _analyze_pacing(self, shots: List[Shot]) -> str:
        """分析剪辑节奏"""
        if not shots:
            return "normal"
        
        avg_duration = np.mean([s.end_time - s.start_time for s in shots])
        
        if avg_duration < 3:
            return "fast"
        elif avg_duration < 6:
            return "normal"
        else:
            return "slow"
    
    def auto_beat_editing(self, video_path: str, 
                         audio_path: str,
                         pattern: BeatPattern = BeatPattern.EVERY_4_BEATS,
                         output_path: Optional[str] = None) -> str:
        """
        自动卡点剪辑
        
        根据音乐节奏自动剪辑视频
        
        Args:
            video_path: 视频路径
            audio_path: 音频路径（用于分析节拍）
            pattern: 卡点模式
            output_path: 输出路径
            
        Returns:
            str: 输出视频路径
        """
        print("\n🎵 开始自动卡点剪辑...")
        
        # 分析音乐节拍
        beats = self._analyze_music_beats(audio_path)
        print(f"   检测到 {len(beats)} 个节拍点")
        
        # 根据模式选择节拍点
        selected_beats = self._select_beats_by_pattern(beats, pattern)
        print(f"   选择 {len(selected_beats)} 个剪辑点")
        
        # 根据节拍点剪辑视频
        if output_path is None:
            base, ext = os.path.splitext(video_path)
            output_path = f"{base}_beat_edit{ext}"
        
        # 执行剪辑
        result = self._cut_by_beats(video_path, selected_beats, output_path)
        
        print(f"   ✓ 卡点剪辑完成: {output_path}")
        return output_path
    
    def _analyze_music_beats(self, audio_path: str) -> List[float]:
        """分析音乐节拍"""
        # 这里简化处理，实际应该使用librosa等库分析
        # 返回模拟的节拍点
        return [i * 0.5 for i in range(120)]  # 每0.5秒一个节拍
    
    def _select_beats_by_pattern(self, beats: List[float], 
                                pattern: BeatPattern) -> List[float]:
        """根据模式选择节拍点"""
        if pattern == BeatPattern.EVERY_BEAT:
            return beats
        elif pattern == BeatPattern.EVERY_2_BEATS:
            return beats[::2]
        elif pattern == BeatPattern.EVERY_4_BEATS:
            return beats[::4]
        elif pattern == BeatPattern.ACCENT_ONLY:
            # 选择重音点（简化：每8拍一个）
            return beats[::8]
        else:
            return beats[::4]  # 默认每4拍
    
    def _cut_by_beats(self, video_path: str, beats: List[float], 
                     output_path: str) -> str:
        """根据节拍点剪辑视频"""
        # 使用专业剪辑引擎
        # 这里简化处理，实际应该根据节拍点精确剪辑
        
        # 创建剪辑任务
        tasks = []
        for i in range(len(beats) - 1):
            task = VideoTask(
                task_id=f"beat_{i}",
                input_path=video_path,
                output_path=tempfile.mktemp(suffix=".mp4"),
                operation="cut_lossless",
                params={
                    "start_time": beats[i],
                    "end_time": beats[i + 1]
                }
            )
            tasks.append(task)
        
        # 批量处理
        results = self.video_engine.batch_process(tasks)
        
        # 合并剪辑好的片段
        successful_clips = [r.output_path for r in results if r.success]
        if successful_clips:
            self.video_engine.merge_videos(successful_clips, output_path)
        
        # 清理临时文件
        for clip in successful_clips:
            if os.path.exists(clip):
                os.unlink(clip)
        
        return output_path
    
    def emotion_matched_transition(self, from_emotion: EmotionalTone,
                                   to_emotion: EmotionalTone) -> TransitionType:
        """
        情绪匹配转场
        
        根据情绪变化选择最佳转场效果
        """
        # 如果情绪相同，使用简单转场
        if from_emotion == to_emotion:
            return TransitionType.CUT
        
        # 如果情绪变化剧烈，使用强调转场
        emotion_intensity = {
            EmotionalTone.HAPPY: 1,
            EmotionalTone.SAD: 2,
            EmotionalTone.ANGRY: 3,
            EmotionalTone.TENSE: 3,
            EmotionalTone.ROMANTIC: 2,
            EmotionalTone.SUSPENSE: 2,
            EmotionalTone.EXCITING: 3,
            EmotionalTone.WARM: 1,
        }
        
        from_intensity = emotion_intensity.get(from_emotion, 1)
        to_intensity = emotion_intensity.get(to_emotion, 1)
        
        if abs(from_intensity - to_intensity) >= 2:
            # 情绪变化剧烈，使用强调转场
            return TransitionType.FLASH
        elif from_intensity > to_intensity:
            # 从强烈到平静，使用柔和转场
            return TransitionType.FADE
        else:
            # 从平静到强烈，使用快速转场
            return TransitionType.CUT
    
    def auto_subtitle_style(self, text: str, 
                           emotion: EmotionalTone,
                           scene_type: SceneType) -> SubtitleStyle:
        """
        自动选择字幕样式
        
        根据内容、情绪和场景类型自动选择最佳字幕样式
        """
        # 根据场景类型选择
        if scene_type == SceneType.CONFLICT:
            return self.SUBTITLE_STYLES["高能预警"]
        elif scene_type == SceneType.EMOTIONAL:
            if emotion == EmotionalTone.ROMANTIC:
                return self.SUBTITLE_STYLES["文艺清新"]
            else:
                return self.SUBTITLE_STYLES["情绪强调"]
        elif scene_type == SceneType.ACTION:
            return self.SUBTITLE_STYLES["抖音爆款"]
        
        # 根据情绪选择
        if emotion in [EmotionalTone.EXCITING, EmotionalTone.ANGRY]:
            return self.SUBTITLE_STYLES["高能预警"]
        elif emotion in [EmotionalTone.ROMANTIC, EmotionalTone.WARM]:
            return self.SUBTITLE_STYLES["文艺清新"]
        
        # 默认样式
        return self.SUBTITLE_STYLES["默认"]
    
    def generate_editing_report(self, sequence: EditingSequence) -> Dict[str, Any]:
        """
        生成剪辑报告
        
        分析剪辑序列的质量和特点
        """
        report = {
            "total_shots": len(sequence.shots),
            "total_duration": sequence.total_duration,
            "pacing": sequence.pacing,
            "avg_shot_duration": sequence.total_duration / len(sequence.shots) if sequence.shots else 0,
            "transition_distribution": {},
            "emotion_flow": [],
            "suggestions": []
        }
        
        # 统计转场分布
        for transition in sequence.transitions:
            name = transition.value
            report["transition_distribution"][name] = report["transition_distribution"].get(name, 0) + 1
        
        # 记录情绪流
        for shot in sequence.shots:
            report["emotion_flow"].append({
                "time": shot.start_time,
                "emotion": shot.emotional_tone.value
            })
        
        # 生成建议
        if report["avg_shot_duration"] > 8:
            report["suggestions"].append("镜头平均时长较长，建议加快节奏")
        
        if len(sequence.shots) < 5:
            report["suggestions"].append("镜头数量较少，建议增加场景切换")
        
        return report


# 使用示例
if __name__ == "__main__":
    engine = SmartEditingEngine()
    
    # 示例：智能分镜重组
    print("\n" + "="*70)
    print("智能分镜重组示例")
    print("="*70)
    
    # 这里应该传入实际的DramaStructure
    # sequence = engine.smart_shot_reordering(drama, target_duration=60.0)
    
    # 示例：情绪匹配转场
    print("\n情绪匹配转场示例:")
    transition = engine.emotion_matched_transition(
        EmotionalTone.HAPPY, 
        EmotionalTone.ANGRY
    )
    print(f"从开心到愤怒: {transition.value}")
    
    # 示例：自动字幕样式
    print("\n自动字幕样式示例:")
    style = engine.auto_subtitle_style(
        "我爱你",
        EmotionalTone.ROMANTIC,
        SceneType.EMOTIONAL
    )
    print(f"选择的样式: {style.name}")
    print(f"字体: {style.font_family}, 大小: {style.font_size}")
