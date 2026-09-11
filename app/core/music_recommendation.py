"""
智能配乐推荐系统
提供基于场景情感、节奏、风格的智能配乐推荐
"""

import numpy as np
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
from threading import RLock
from datetime import datetime
import json


import logging
logger = logging.getLogger("AI短剧编辑器.core.music_recommendation")

class MusicGenre(Enum):
    """音乐类型"""
    POP = "pop"
    ROCK = "rock"
    ELECTRONIC = "electronic"
    CLASSICAL = "classical"
    JAZZ = "jazz"
    FOLK = "folk"
    HIPHOP = "hiphop"
    RNB = "rnb"
    AMBIENT = "ambient"
    CINEMATIC = "cinematic"
    DRAMA = "drama"
    COMEDY = "comedy"
    SUSPENSE = "suspense"
    ROMANTIC = "romantic"
    EPIC = "epic"


class MusicMood(Enum):
    """音乐情绪"""
    HAPPY = "happy"
    SAD = "sad"
    ENERGETIC = "energetic"
    CALM = "calm"
    TENSE = "tense"
    ROMANTIC = "romantic"
    MYSTERIOUS = "mysterious"
    HOPEFUL = "hopeful"
    MELANCHOLY = "melancholy"
    POWERFUL = "powerful"


class MusicTempo(Enum):
    """音乐节奏"""
    SLOW = "slow"
    MEDIUM = "medium"
    FAST = "fast"
    VARIABLE = "variable"


@dataclass
class MusicTrack:
    """音乐曲目"""
    id: str
    title: str
    artist: str
    genre: MusicGenre
    mood: MusicMood
    tempo: MusicTempo
    duration: float
    file_path: str
    bpm: Optional[int] = None
    key: Optional[str] = None
    preview_url: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    confidence: float = 0.0
    match_reason: str = ""
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "title": self.title,
            "artist": self.artist,
            "genre": self.genre.value,
            "mood": self.mood.value,
            "tempo": self.tempo.value,
            "duration": self.duration,
            "file_path": self.file_path,
            "bpm": self.bpm,
            "key": self.key,
            "preview_url": self.preview_url,
            "tags": self.tags,
            "confidence": self.confidence,
            "match_reason": self.match_reason
        }


@dataclass
class SceneMusicRequirement:
    """场景音乐需求"""
    scene_type: str
    emotion: str
    duration: float
    preferred_genres: List[str] = field(default_factory=list)
    excluded_genres: List[str] = field(default_factory=list)
    min_bpm: Optional[int] = None
    max_bpm: Optional[int] = None
    vocal_preference: str = "any"  # any, instrumental, vocal


class MusicRecommendationEngine:
    """音乐推荐引擎"""
    
    def __init__(self):
        self._music_library: Dict[str, MusicTrack] = {}
        self._recommendations: List[MusicTrack] = []
        self._lock = RLock()
        self._initialize_library()
    
    def _initialize_library(self):
        """初始化音乐库"""
        # 创建模拟音乐库
        sample_tracks = [
            {
                "id": "music_001",
                "title": "阳光明媚",
                "artist": "AI音乐库",
                "genre": MusicGenre.POP,
                "mood": MusicMood.HAPPY,
                "tempo": MusicTempo.MEDIUM,
                "duration": 180.0,
                "file_path": "music/sunny.mp3",
                "bpm": 120,
                "key": "C Major",
                "tags": ["happy", "upbeat", "energetic"]
            },
            {
                "id": "music_002",
                "title": "深情告白",
                "artist": "AI音乐库",
                "genre": MusicGenre.ROMANTIC,
                "mood": MusicMood.ROMANTIC,
                "tempo": MusicTempo.SLOW,
                "duration": 240.0,
                "file_path": "music/romantic.mp3",
                "bpm": 70,
                "key": "G Major",
                "tags": ["romantic", "emotional", "slow"]
            },
            {
                "id": "music_003",
                "title": "悬疑时刻",
                "artist": "AI音乐库",
                "genre": MusicGenre.SUSPENSE,
                "mood": MusicMood.TENSE,
                "tempo": MusicTempo.SLOW,
                "duration": 200.0,
                "file_path": "music/suspense.mp3",
                "bpm": 80,
                "key": "D Minor",
                "tags": ["suspense", "dark", "tense"]
            },
            {
                "id": "music_004",
                "title": "逆袭时刻",
                "artist": "AI音乐库",
                "genre": MusicGenre.EPIC,
                "mood": MusicMood.POWERFUL,
                "tempo": MusicTempo.FAST,
                "duration": 150.0,
                "file_path": "music/epic.mp3",
                "bpm": 140,
                "key": "E Minor",
                "tags": ["epic", "powerful", "energetic", "counterattack"]
            },
            {
                "id": "music_005",
                "title": "温馨日常",
                "artist": "AI音乐库",
                "genre": MusicGenre.FOLK,
                "mood": MusicMood.CALM,
                "tempo": MusicTempo.MEDIUM,
                "duration": 210.0,
                "file_path": "music/calm.mp3",
                "bpm": 90,
                "key": "F Major",
                "tags": ["calm", "peaceful", "folk"]
            },
            {
                "id": "music_006",
                "title": "情感波动",
                "artist": "AI音乐库",
                "genre": MusicGenre.DRAMA,
                "mood": MusicMood.MELANCHOLY,
                "tempo": MusicTempo.SLOW,
                "duration": 220.0,
                "file_path": "music/drama.mp3",
                "bpm": 75,
                "key": "A Minor",
                "tags": ["emotional", "drama", "sad"]
            },
            {
                "id": "music_007",
                "title": "动感节拍",
                "artist": "AI音乐库",
                "genre": MusicGenre.ELECTRONIC,
                "mood": MusicMood.ENERGETIC,
                "tempo": MusicTempo.FAST,
                "duration": 160.0,
                "file_path": "music/electronic.mp3",
                "bpm": 128,
                "key": "C Minor",
                "tags": ["energetic", "electronic", "fast", "rhythmic"]
            },
            {
                "id": "music_008",
                "title": "希望之光",
                "artist": "AI音乐库",
                "genre": MusicGenre.CINEMATIC,
                "mood": MusicMood.HOPEFUL,
                "tempo": MusicTempo.MEDIUM,
                "duration": 190.0,
                "file_path": "music/hopeful.mp3",
                "bpm": 95,
                "key": "G Major",
                "tags": ["hopeful", "cinematic", "uplifting"]
            },
            {
                "id": "music_009",
                "title": "神秘探索",
                "artist": "AI音乐库",
                "genre": MusicGenre.AMBIENT,
                "mood": MusicMood.MYSTERIOUS,
                "tempo": MusicTempo.SLOW,
                "duration": 230.0,
                "file_path": "music/ambient.mp3",
                "bpm": 65,
                "key": "D Minor",
                "tags": ["mysterious", "ambient", "dark"]
            },
            {
                "id": "music_010",
                "title": "喜剧时刻",
                "artist": "AI音乐库",
                "genre": MusicGenre.COMEDY,
                "mood": MusicMood.HAPPY,
                "tempo": MusicTempo.MEDIUM,
                "duration": 170.0,
                "file_path": "music/comedy.mp3",
                "bpm": 110,
                "key": "F Major",
                "tags": ["comedy", "happy", "lighthearted"]
            }
        ]
        
        for track_data in sample_tracks:
            track = MusicTrack(**track_data)
            self._music_library[track.id] = track
    
    def recommend_music(self, requirement: SceneMusicRequirement,
                     progress_callback: Optional[callable] = None) -> List[MusicTrack]:
        """推荐音乐"""
        if progress_callback:
            progress_callback(0, "开始推荐音乐...")
        
        with self._lock:
            try:
                # 步骤1: 筛选符合类型的音乐
                if progress_callback:
                    progress_callback(20, "筛选音乐库...")
                
                candidates = list(self._music_library.values())
                
                # 排除不需要的类型
                if requirement.excluded_genres:
                    candidates = [
                        m for m in candidates
                        if m.genre.value not in requirement.excluded_genres
                    ]
                
                # 优先考虑偏好的类型
                if requirement.preferred_genres:
                    preferred = [
                        m for m in candidates
                        if m.genre.value in requirement.preferred_genres
                    ]
                    if preferred:
                        candidates = preferred + [m for m in candidates if m not in preferred]
                
                # 步骤2: 匹配情绪
                if progress_callback:
                    progress_callback(40, "匹配情绪...")
                
                mood_matches = self._match_mood(candidates, requirement.emotion)
                
                # 步骤3: 匹配节奏
                if progress_callback:
                    progress_callback(60, "匹配节奏...")
                
                tempo_matches = self._match_tempo(mood_matches, requirement)
                
                # 步骤4: 计算匹配分数
                if progress_callback:
                    progress_callback(80, "计算匹配分数...")
                
                scored_tracks = []
                for track in tempo_matches:
                    score = self._calculate_match_score(track, requirement)
                    track.confidence = score
                    track.match_reason = self._generate_match_reason(track, requirement)
                    scored_tracks.append(track)
                
                # 步骤5: 排序和返回
                if progress_callback:
                    progress_callback(90, "生成推荐列表...")
                
                scored_tracks.sort(key=lambda x: (-x.confidence, -x.duration))
                
                # 限制返回数量
                max_recommendations = 10
                recommendations = scored_tracks[:max_recommendations]
                
                self._recommendations = recommendations
                
                if progress_callback:
                    progress_callback(100, "推荐完成")
                
                return recommendations
                
            except Exception as e:
                logger.error(f'推荐音乐失败: {e}')
                return []
    
    def _match_mood(self, tracks: List[MusicTrack], emotion: str) -> List[MusicTrack]:
        """匹配情绪"""
        emotion_mapping = {
            "happy": [MusicMood.HAPPY, MusicMood.HOPEFUL],
            "sad": [MusicMood.SAD, MusicMood.MELANCHOLY],
            "angry": [MusicMood.POWERFUL, MusicMood.TENSE],
            "surprised": [MusicMood.MYSTERIOUS],
            "neutral": [MusicMood.CALM],
            "fear": [MusicMood.TENSE, MusicMood.MYSTERIOUS],
            "disgust": [MusicMood.CALM],
            "joy": [MusicMood.HAPPY, MusicMood.ENERGETIC],
            "trust": [MusicMood.CALM, MusicMood.HOPEFUL],
            "anticipation": [MusicMood.TENSE, MusicMood.MYSTERIOUS]
        }
        
        target_moods = emotion_mapping.get(emotion, [MusicMood.CALM])
        matched = [t for t in tracks if t.mood in target_moods]
        
        if not matched:
            return tracks
        
        return matched
    
    def _match_tempo(self, tracks: List[MusicTrack], 
                   requirement: SceneMusicRequirement) -> List[MusicTrack]:
        """匹配节奏"""
        matched = tracks.copy()
        
        # BPM筛选
        if requirement.min_bpm:
            matched = [t for t in matched if t.bpm and t.bpm >= requirement.min_bpm]
        
        if requirement.max_bpm:
            matched = [t for t in matched if t.bpm and t.bpm <= requirement.max_bpm]
        
        # 节奏类型筛选
        if requirement.duration > 0:
            # 根据时长推断合适的节奏
            if requirement.duration < 30.0:
                target_tempo = MusicTempo.FAST
            elif requirement.duration < 120.0:
                target_tempo = MusicTempo.MEDIUM
            else:
                target_tempo = MusicTempo.SLOW
            
            matched = [t for t in matched if t.tempo == target_tempo]
        
        return matched
    
    def _calculate_match_score(self, track: MusicTrack, 
                          requirement: SceneMusicRequirement) -> float:
        """计算匹配分数"""
        score = 0.0
        
        # 情绪匹配分数 (40%)
        emotion_score = 0.4
        if track.mood.value == requirement.emotion:
            emotion_score = 0.4
        elif track.mood.value in self._get_related_emotions(requirement.emotion):
            emotion_score = 0.3
        else:
            emotion_score = 0.1
        score += emotion_score
        
        # 类型偏好分数 (30%)
        genre_score = 0.0
        if requirement.preferred_genres:
            if track.genre.value in requirement.preferred_genres:
                genre_score = 0.3
            elif track.genre.value in self._get_related_genres(requirement.preferred_genres):
                genre_score = 0.15
        score += genre_score
        
        # 节奏匹配分数 (20%)
        tempo_score = 0.2
        if track.tempo.value in self._get_related_tempos(requirement):
            tempo_score = 0.2
        score += tempo_score
        
        # 时长匹配分数 (10%)
        duration_diff = abs(track.duration - requirement.duration)
        duration_score = max(0.0, 1.0 - duration_diff / requirement.duration) * 0.1
        score += duration_score
        
        return score
    
    def _get_related_emotions(self, emotion: str) -> List[str]:
        """获取相关情绪"""
        emotion_relations = {
            "happy": ["hopeful", "energetic"],
            "sad": ["melancholy", "calm"],
            "angry": ["powerful", "tense"],
            "surprised": ["mysterious", "tense"],
            "neutral": ["calm", "hopeful"],
            "fear": ["tense", "mysterious"],
            "disgust": ["calm", "melancholy"],
            "joy": ["happy", "energetic", "hopeful"],
            "trust": ["calm", "hopeful"],
            "anticipation": ["tense", "mysterious"]
        }
        return emotion_relations.get(emotion, [])
    
    def _get_related_genres(self, genres: List[str]) -> List[str]:
        """获取相关类型"""
        genre_relations = {
            "pop": ["electronic", "rnb"],
            "rock": ["electronic", "hiphop"],
            "electronic": ["pop", "hiphop"],
            "classical": ["cinematic", "drama"],
            "jazz": ["rnb", "folk"],
            "folk": ["classical", "calm"],
            "hiphop": ["electronic", "rnb"],
            "rnb": ["jazz", "hiphop"],
            "ambient": ["cinematic", "classical"],
            "cinematic": ["epic", "drama"],
            "drama": ["cinematic", "romantic"],
            "comedy": ["pop", "folk"],
            "suspense": ["ambient", "drama"],
            "romantic": ["drama", "folk"],
            "epic": ["cinematic", "rock"]
        }
        
        related = []
        for genre in genres:
            related = genre_relations.get(genre, [])
            related.extend(related)
        
        return list(set(related))
    
    def _get_related_tempos(self, requirement: SceneMusicRequirement) -> List[str]:
        """获取相关节奏"""
        if requirement.duration < 30.0:
            return [MusicTempo.FAST.value, MusicTempo.MEDIUM.value]
        elif requirement.duration < 120.0:
            return [MusicTempo.MEDIUM.value, MusicTempo.SLOW.value]
        else:
            return [MusicTempo.SLOW.value]
    
    def _generate_match_reason(self, track: MusicTrack, 
                           requirement: SceneMusicRequirement) -> str:
        """生成匹配原因"""
        reasons = []
        
        if track.mood.value == requirement.emotion:
            reasons.append(f"情绪匹配({track.mood.value})")
        
        if track.genre.value in requirement.preferred_genres:
            reasons.append(f"类型偏好({track.genre.value})")
        
        if abs(track.duration - requirement.duration) < 10.0:
            reasons.append(f"时长接近({track.duration:.1f}s)")
        
        if track.bpm:
            if requirement.min_bpm and track.bpm >= requirement.min_bpm:
                reasons.append(f"节奏符合({track.bpm} BPM)")
            elif requirement.max_bpm and track.bpm <= requirement.max_bpm:
                reasons.append(f"节奏符合({track.bpm} BPM)")
        
        return "，".join(reasons) if reasons else "综合推荐"
    
    def get_recommendations(self) -> List[MusicTrack]:
        """获取推荐列表"""
        return self._recommendations.copy()
    
    def get_music_library(self) -> Dict[str, MusicTrack]:
        """获取音乐库"""
        return self._music_library.copy()
    
    def add_music(self, track: MusicTrack) -> bool:
        """添加音乐到库"""
        with self._lock:
            self._music_library[track.id] = track
            return True
    
    def remove_music(self, track_id: str) -> bool:
        """从库中移除音乐"""
        with self._lock:
            if track_id in self._music_library:
                del self._music_library[track_id]
                return True
            return False
    
    def search_music(self, query: str, 
                  genre: Optional[MusicGenre] = None,
                  mood: Optional[MusicMood] = None) -> List[MusicTrack]:
        """搜索音乐"""
        query = query.lower()
        results = []
        
        for track in self._music_library.values():
            # 标题匹配
            if query in track.title.lower():
                results.append(track)
                continue
            
            # 艺术家匹配
            if query in track.artist.lower():
                results.append(track)
                continue
            
            # 标签匹配
            if any(query in tag.lower() for tag in track.tags):
                results.append(track)
                continue
            
            # 类型匹配
            if genre and track.genre == genre:
                results.append(track)
                continue
            
            # 情绪匹配
            if mood and track.mood == mood:
                results.append(track)
                continue
        
        return results
    
    def clear_recommendations(self):
        """清除推荐"""
        with self._lock:
            self._recommendations.clear()
    
    def export_library(self, file_path: str) -> bool:
        """导出音乐库"""
        try:
            data = {
                "tracks": [track.to_dict() for track in self._music_library.values()],
                "total_tracks": len(self._music_library),
                "exported_at": datetime.now().isoformat()
            }
            
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            return True
        except Exception as e:
            logger.error(f'导出音乐库失败: {e}')
            return False


class MusicAutoSync:
    """音乐自动同步"""
    
    def __init__(self, engine: MusicRecommendationEngine):
        self._engine = engine
        self._lock = RLock()
    
    def auto_sync_music_to_timeline(self, video_scenes: List[Dict[str, Any]],
                                 progress_callback: Optional[callable] = None) -> Dict[str, Any]:
        """自动同步音乐到时间轴"""
        if progress_callback:
            progress_callback(0, "开始自动同步音乐...")
        
        with self._lock:
            try:
                sync_results = []
                
                for i, scene in enumerate(video_scenes):
                    if progress_callback:
                        progress = int(20 + 80 * (i + 1) / len(video_scenes))
                        progress_callback(progress, f"同步场景 {i+1}/{len(video_scenes)}")
                    
                    # 创建音乐需求
                    requirement = SceneMusicRequirement(
                        scene_type=scene.get("type", "unknown"),
                        emotion=scene.get("emotion", "neutral"),
                        duration=scene.get("duration", 0.0),
                        preferred_genres=scene.get("preferred_genres", []),
                        excluded_genres=scene.get("excluded_genres", [])
                    )
                    
                    # 获取推荐
                    recommendations = self._engine.recommend_music(requirement)
                    
                    if recommendations:
                        best_match = recommendations[0]
                        
                        sync_result = {
                            "scene_index": i,
                            "scene_start": scene.get("start_time", 0.0),
                            "scene_end": scene.get("end_time", 0.0),
                            "recommended_music": best_match.to_dict(),
                            "sync_confidence": best_match.confidence
                        }
                        
                        sync_results.append(sync_result)
                
                if progress_callback:
                    progress_callback(100, "同步完成")
                
                return {
                    "total_scenes": len(video_scenes),
                    "synced_scenes": len(sync_results),
                    "sync_results": sync_results,
                    "average_confidence": np.mean([r["sync_confidence"] for r in sync_results]) if sync_results else 0.0
                }
                
            except Exception as e:
                logger.error(f'自动同步失败: {e}')
                return {
                    "total_scenes": len(video_scenes),
                    "synced_scenes": 0,
                    "sync_results": [],
                    "average_confidence": 0.0
                }
