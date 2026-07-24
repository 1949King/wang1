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
        # 角色偏好缓存：{角色名: {"keep": bool, "weight": float, "note": str}}
        # 通过 self.load_character_prefs(video_path) 从缓存读取
        self._character_prefs: Dict[str, Dict] = {}
        print("🎬 智能剪辑引擎初始化完成")
        print(f"   已加载 {len(SmartEditingEngine.SUBTITLE_STYLES)} 种字幕样式")
        print(f"   已加载 {len(SmartEditingEngine.EMOTION_TRANSITION_MAP)} 种情绪转场规则")
    
    def load_character_prefs(self, video_path: str) -> Dict[str, Dict]:
        """
        从视频级缓存读取角色偏好。
        
        返回：{角色名: {"keep": bool, "weight": float, "note": str}}
        如果该视频没有缓存或未设置偏好，返回空 dict。
        """
        if not video_path:
            self._character_prefs = {}
            return {}
        try:
            from .character_cache import AnalysisCache
            cache = AnalysisCache()
            prefs_objs = cache.get_character_prefs(video_path)
            # 转换为 plain dict
            prefs = {}
            for name, p in prefs_objs.items():
                prefs[name] = {
                    "keep": bool(getattr(p, "keep", True)),
                    "weight": float(getattr(p, "weight", 1.0)),
                    "note": str(getattr(p, "note", "")),
                }
            self._character_prefs = prefs
            if prefs:
                print(f"   📋 已加载 {len(prefs)} 个角色偏好")
            return prefs
        except Exception as e:
            print(f"   ⚠️ 读取角色偏好失败: {e}")
            self._character_prefs = {}
            return {}
    
    def set_character_pref(self, video_path: str, name: str,
                           keep: bool = True, weight: float = 1.0) -> bool:
        """设置单个角色偏好并写回缓存"""
        try:
            from .character_cache import AnalysisCache
            cache = AnalysisCache()
            ok = cache.set_character_pref(video_path, name, keep=keep, weight=weight)
            if ok:
                self.load_character_prefs(video_path)
            return ok
        except Exception as e:
            print(f"   ⚠️ 设置角色偏好失败: {e}")
            return False
    
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
        """从剧情结构中提取镜头（带角色偏好权重调整）"""
        shots = []
        for scene in drama.scenes:
            base_importance = self._calculate_importance(scene, drama.plot_points)
            # 角色偏好调整：用户标记的角色会影响该镜头的重要性
            adjustment = self._score_from_character_prefs(scene.characters)
            shot = Shot(
                start_time=scene.start_time,
                end_time=scene.end_time,
                shot_type=self._classify_shot_type(scene),
                characters=list(scene.characters) if scene.characters else [],
                emotional_tone=scene.emotional_tone,
                importance=max(0.0, min(1.0, base_importance + adjustment)),
                visual_features={}
            )
            shots.append(shot)
        return shots

    def _score_from_character_prefs(self, scene_characters) -> float:
        """
        根据角色偏好计算镜头重要性调整值。
        - 被标记「忽略」的角色出现 → 下调 importance 0.25
        - 被标记「优先保留」（weight > 1） → 上调 importance (weight-1)*0.2
        返回值在 [-0.5, +0.5] 之间
        """
        if not self._character_prefs or not scene_characters:
            return 0.0
        adjustment = 0.0
        for name in scene_characters:
            pref = self._character_prefs.get(str(name))
            if pref is None:
                continue
            if not pref.get("keep", True):
                # 忽略角色：大幅下调
                adjustment -= 0.25
            else:
                w = float(pref.get("weight", 1.0))
                if w > 1.0:
                    adjustment += (w - 1.0) * 0.2
                elif w < 1.0:
                    adjustment -= (1.0 - w) * 0.15
        return max(-0.5, min(0.5, adjustment))
    
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
        """为镜头选择转场效果 (v1.0 backup, see v2.0 vector methods)"""
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

    def _select_transitions_v2(
        self,
        shots: List[Shot],
        emotion_vectors: Optional[List[np.ndarray]] = None,
        emotion_journey: Optional[List[Dict]] = None,
    ) -> List[TransitionType]:
        """
        为镜头选择转场效果 (v2.0: 向量+情绪历程驱动)

        优先使用8维情绪向量和历程信息，回退到旧枚举方式。
        """
        transitions = []
        shot_count = len(shots)

        for i in range(shot_count - 1):
            # 尝试获取当前镜头对应的情绪向量
            from_vec = None
            to_vec = None
            if emotion_vectors and len(emotion_vectors) > i:
                from_vec = emotion_vectors[i]
            if emotion_vectors and len(emotion_vectors) > i + 1:
                to_vec = emotion_vectors[i + 1]

            # 查找情绪历程中的对应转折点
            journey_point = None
            if emotion_journey and from_vec is not None and to_vec is not None:
                # 按时间近似匹配历程转折点
                from_time = shots[i].start_time
                for jp in emotion_journey:
                    jp_time = jp.get("time", 0)
                    if abs(jp_time - from_time) < 3.0:
                        journey_point = jp
                        break

            if from_vec is not None and to_vec is not None:
                # v2.0: 向量+历程自适应选择
                transition = self._select_transition_adaptive(
                    from_vec, to_vec, journey_point
                )
            else:
                # 回退到旧枚举方式
                current = shots[i]
                nxt = shots[i + 1]
                if current.emotional_tone != nxt.emotional_tone:
                    transition = TransitionType.FADE
                else:
                    emotion_transitions = self.EMOTION_TRANSITION_MAP.get(
                        current.emotional_tone, [TransitionType.CUT]
                    )
                    transition = emotion_transitions[0]

            transitions.append(transition)

        if shots:
            transitions.append(TransitionType.CUT)

        return transitions
    
    def _select_transition_by_vector(
        self, from_vec: np.ndarray, to_vec: np.ndarray
    ) -> TransitionType:
        """
        基于8维情绪向量余弦距离选择转场 (v2.0)

        替代旧的 EmotionalTone 枚举硬编码映射，
        通过向量空间中的情绪变化幅度决定转场类型。
        """
        # 计算余弦距离 (0=完全相同, 2=完全相反)
        dot = np.dot(from_vec, to_vec)
        norm = np.linalg.norm(from_vec) * np.linalg.norm(to_vec) + 1e-8
        cos_dist = 1.0 - (dot / norm)

        if cos_dist > 0.8:
            # 情绪剧变 → 闪白强调
            return TransitionType.FLASH
        elif cos_dist > 0.5:
            # 情绪较大变化 → 故障/擦除
            return TransitionType.GLITCH
        elif cos_dist > 0.3:
            # 情绪中等变化 → 淡入淡出
            return TransitionType.FADE
        elif cos_dist > 0.15:
            # 情绪轻微变化 → 溶解
            return TransitionType.DISSOLVE
        else:
            # 情绪平滑 → 硬切
            return TransitionType.CUT

    def _select_transition_adaptive(
        self,
        from_vec: np.ndarray,
        to_vec: np.ndarray,
        journey_point: Optional[Dict] = None,
    ) -> TransitionType:
        """
        综合情绪向量+情绪历程转折点的自适应转场选择 (v2.0)

        Args:
            from_vec: 前一镜头的8维情绪向量
            to_vec: 后一镜头的8维情绪向量
            journey_point: 情绪历程中的对应点 (含 phase, transition_type, editing_value)

        Returns:
            最佳转场类型
        """
        # 基础：向量余弦距离
        base_transition = self._select_transition_by_vector(from_vec, to_vec)

        if journey_point is None:
            return base_transition

        # 情绪历程增强
        transition_type = journey_point.get("transition_type", "")
        editing_value = journey_point.get("editing_value", 0.5)
        phase = journey_point.get("phase", "")

        # 根据历程转折类型调整
        if transition_type == "reversal":
            # 情绪反转 → 强制使用强调转场
            return TransitionType.FLASH
        elif transition_type == "escalation":
            # 情绪升级 → 加速转场
            if editing_value > 0.7:
                return TransitionType.FLASH
            return TransitionType.CUT
        elif phase == "peak":
            # 情绪高潮 → 放大效果
            if editing_value > 0.6:
                return TransitionType.ZOOM
            return TransitionType.FLASH
        elif phase == "release":
            # 情绪释放 → 柔和转场
            return TransitionType.DISSOLVE

        return base_transition

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
        """分析音乐节拍（v2.0: librosa真实分析）"""
        try:
            import librosa
            y, sr = librosa.load(audio_path, sr=22050, duration=120)
            if len(y) == 0:
                return [i * 0.5 for i in range(120)]
            tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
            if beat_frames is None or len(beat_frames) == 0:
                tempo = tempo if isinstance(tempo, (int, float)) else 120.0
                beat_frames = librosa.onset.onset_detect(
                    y=y, sr=sr, units='frames'
                )
            beat_times = librosa.frames_to_time(beat_frames, sr=sr)
            return beat_times.tolist()
        except ImportError:
            # librosa 不可用时回退到默认节拍
            return [i * 0.5 for i in range(120)]
        except Exception as e:
            print(f"[SmartEditing] 节拍分析异常: {e}")
            return [i * 0.5 for i in range(120)]
    
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
        生成剪辑报告 (v2.0: 含情绪旅程分析)

        分析剪辑序列的质量和特点
        """
        report = {
            "total_shots": len(sequence.shots),
            "total_duration": sequence.total_duration,
            "pacing": sequence.pacing,
            "avg_shot_duration": (
                sequence.total_duration / len(sequence.shots)
                if sequence.shots else 0
            ),
            "transition_distribution": {},
            "emotion_flow": [],
            "suggestions": []
        }

        # 统计转场分布
        for transition in sequence.transitions:
            name = transition.value
            report["transition_distribution"][name] = (
                report["transition_distribution"].get(name, 0) + 1
            )

        # 记录情绪流（v2.0: 含情绪向量维度）
        for shot in sequence.shots:
            entry = {
                "time": shot.start_time,
                "emotion": shot.emotional_tone.value
            }
            # 如果有视觉特征中的向量信息
            if "emotion_vector" in shot.visual_features:
                vec = shot.visual_features["emotion_vector"]
                if isinstance(vec, np.ndarray):
                    # 找出最强的两个情绪维度
                    top_indices = np.argsort(vec)[-2:][::-1]
                    EMOTION_DIMS = ["开心", "悲伤", "愤怒", "紧张", "浪漫", "悬疑", "激动", "温馨"]
                    entry["dominant_emotions"] = [
                        EMOTION_DIMS[i] for i in top_indices
                        if i < len(EMOTION_DIMS)
                    ]
            report["emotion_flow"].append(entry)

        # 生成建议
        if report["avg_shot_duration"] > 8:
            report["suggestions"].append("镜头平均时长较长，建议加快节奏")

        if len(sequence.shots) < 5:
            report["suggestions"].append("镜头数量较少，建议增加场景切换")

        # v2.0: 转场多样性建议
        unique_transitions = len(report["transition_distribution"])
        if unique_transitions < 3 and len(sequence.shots) > 5:
            report["suggestions"].append(
                f"转场种类单一（仅{unique_transitions}种），建议增加转场多样性"
            )

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
