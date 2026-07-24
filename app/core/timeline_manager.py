import os
import json
import time
from datetime import datetime
from typing import Dict, List, Optional, Any
from collections import OrderedDict
import threading


class TimelineManager:
    """
    时间线管理系统
    负责时间线的多轨道管理、片段编辑、关键帧动画等功能
    """
    
    def __init__(self):
        """初始化时间线管理器"""
        self.timelines = {}
        self.current_timeline_id = None
        
        self.virtual_timeline = OrderedDict()
        self.virtual_window_start = 0.0
        self.virtual_window_end = 0.0
        self.virtual_scale = 1.0
        self.virtual_offset = 0.0
        
        self.timeline_cache = {}
        self.max_cache_size = 100
        self._lock = threading.RLock()
    
    def create_timeline(self, name: str, resolution: str = "1920x1080", fps: int = 30) -> Dict[str, Any]:
        """
        创建时间线
        
        Args:
            name: 时间线名称
            resolution: 分辨率
            fps: 帧率
            
        Returns:
            时间线信息字典
        """
        timeline_id = f"timeline_{int(time.time())}"
        
        timeline = {
            "id": timeline_id,
            "name": name,
            "created_at": datetime.now().isoformat(),
            "last_modified": datetime.now().isoformat(),
            "settings": {
                "resolution": resolution,
                "fps": fps,
                "duration": 0
            },
            "tracks": [
                # 视频轨道
                {
                    "id": "video_1",
                    "name": "视频轨道 1",
                    "type": "video",
                    "clips": []
                },
                # 音频轨道
                {
                    "id": "audio_1",
                    "name": "音频轨道 1",
                    "type": "audio",
                    "clips": []
                }
            ],
            "markers": [],
            "keyframes": []
        }
        
        self.timelines[timeline_id] = timeline
        self.current_timeline_id = timeline_id
        
        return timeline
    
    def get_timeline(self, timeline_id: str) -> Optional[Dict[str, Any]]:
        """
        获取时间线
        
        Args:
            timeline_id: 时间线ID
            
        Returns:
            时间线信息字典，如果时间线不存在则返回None
        """
        return self.timelines.get(timeline_id)
    
    def add_track(self, timeline_id: str, track_type: str = "video", name: str = None) -> Dict[str, Any]:
        """
        添加轨道
        
        Args:
            timeline_id: 时间线ID
            track_type: 轨道类型 (video, audio)
            name: 轨道名称
            
        Returns:
            轨道信息字典
        """
        timeline = self.get_timeline(timeline_id)
        if not timeline:
            raise ValueError(f"时间线不存在: {timeline_id}")
        
        track_id = f"{track_type}_{len(timeline['tracks']) + 1}"
        track_name = name or f"{track_type} 轨道 {len(timeline['tracks']) + 1}"
        
        new_track = {
            "id": track_id,
            "name": track_name,
            "type": track_type,
            "clips": []
        }
        
        timeline["tracks"].append(new_track)
        timeline["last_modified"] = datetime.now().isoformat()
        
        return new_track
    
    def add_clip(self, timeline_id: str, track_id: str, clip_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        添加片段到轨道
        
        Args:
            timeline_id: 时间线ID
            track_id: 轨道ID
            clip_info: 片段信息
            
        Returns:
            片段信息字典
        """
        timeline = self.get_timeline(timeline_id)
        if not timeline:
            raise ValueError(f"时间线不存在: {timeline_id}")
        
        # 找到轨道
        track = None
        for t in timeline["tracks"]:
            if t["id"] == track_id:
                track = t
                break
        
        if not track:
            raise ValueError(f"轨道不存在: {track_id}")
        
        # 生成片段ID
        clip_id = f"clip_{int(time.time())}"
        import os as _os
        clip_name = clip_info.get("name") or _os.path.basename(clip_info.get("path", ""))
        
        # 片段信息
        new_clip = {
            "id": clip_id,
            "name": clip_name,
            "path": clip_info.get("path"),
            "start_time": clip_info.get("start_time", 0),
            "duration": clip_info.get("duration", 10),
            "in_point": clip_info.get("in_point", 0),
            "out_point": clip_info.get("out_point", clip_info.get("duration", 10)),
            "volume": clip_info.get("volume", 1.0),
            "opacity": clip_info.get("opacity", 1.0),
            "effects": clip_info.get("effects", []),
            "transitions": clip_info.get("transitions", []),
            "created_at": datetime.now().isoformat()
        }
        
        # 添加到轨道
        track["clips"].append(new_clip)
        
        # 更新时间线时长
        timeline_end = max(new_clip["start_time"] + new_clip["duration"], timeline["settings"]["duration"])
        timeline["settings"]["duration"] = timeline_end
        timeline["last_modified"] = datetime.now().isoformat()
        
        return new_clip
    
    def move_clip(self, timeline_id: str, track_id: str, clip_id: str, new_start_time: float, new_track_id: str = None) -> bool:
        """
        移动片段
        
        Args:
            timeline_id: 时间线ID
            track_id: 当前轨道ID
            clip_id: 片段ID
            new_start_time: 新的开始时间
            new_track_id: 新的轨道ID，如果为None则保持原轨道
            
        Returns:
            是否移动成功
        """
        timeline = self.get_timeline(timeline_id)
        if not timeline:
            return False
        
        # 找到当前轨道和片段
        current_track = None
        clip = None
        for t in timeline["tracks"]:
            if t["id"] == track_id:
                current_track = t
                for c in t["clips"]:
                    if c["id"] == clip_id:
                        clip = c
                        break
                break
        
        if not clip:
            return False
        
        # 如果要移动到新轨道
        if new_track_id and new_track_id != track_id:
            # 找到新轨道
            new_track = None
            for t in timeline["tracks"]:
                if t["id"] == new_track_id:
                    new_track = t
                    break
            
            if not new_track:
                return False
            
            # 从原轨道移除
            current_track["clips"] = [c for c in current_track["clips"] if c["id"] != clip_id]
            
            # 添加到新轨道
            clip["start_time"] = new_start_time
            new_track["clips"].append(clip)
        else:
            # 同一轨道内移动
            clip["start_time"] = new_start_time
        
        # 更新时间线时长
        max_end = 0
        for track in timeline["tracks"]:
            for c in track["clips"]:
                max_end = max(max_end, c["start_time"] + c["duration"])
        timeline["settings"]["duration"] = max_end
        timeline["last_modified"] = datetime.now().isoformat()
        
        return True
    
    def resize_clip(self, timeline_id: str, track_id: str, clip_id: str, new_duration: float, adjust_in_point: bool = False) -> bool:
        """
        调整片段长度
        
        Args:
            timeline_id: 时间线ID
            track_id: 轨道ID
            clip_id: 片段ID
            new_duration: 新的时长
            adjust_in_point: 是否调整入点（否则调整出点）
            
        Returns:
            是否调整成功
        """
        timeline = self.get_timeline(timeline_id)
        if not timeline:
            return False
        
        # 找到轨道和片段
        track = None
        clip = None
        for t in timeline["tracks"]:
            if t["id"] == track_id:
                track = t
                for c in t["clips"]:
                    if c["id"] == clip_id:
                        clip = c
                        break
                break
        
        if not clip:
            return False
        
        # 调整片段
        if adjust_in_point:
            # 调整入点，保持出点不变
            clip["in_point"] += clip["duration"] - new_duration
            clip["start_time"] += clip["duration"] - new_duration
        else:
            # 调整出点，保持入点不变
            clip["out_point"] = clip["in_point"] + new_duration
        
        clip["duration"] = new_duration
        
        # 更新时间线时长
        max_end = 0
        for track in timeline["tracks"]:
            for c in track["clips"]:
                max_end = max(max_end, c["start_time"] + c["duration"])
        timeline["settings"]["duration"] = max_end
        timeline["last_modified"] = datetime.now().isoformat()
        
        return True
    
    def delete_clip(self, timeline_id: str, track_id: str, clip_id: str) -> bool:
        """
        删除片段
        
        Args:
            timeline_id: 时间线ID
            track_id: 轨道ID
            clip_id: 片段ID
            
        Returns:
            是否删除成功
        """
        timeline = self.get_timeline(timeline_id)
        if not timeline:
            return False
        
        # 找到轨道
        track = None
        for t in timeline["tracks"]:
            if t["id"] == track_id:
                track = t
                break
        
        if not track:
            return False
        
        # 删除片段
        original_length = len(track["clips"])
        track["clips"] = [c for c in track["clips"] if c["id"] != clip_id]
        
        if len(track["clips"]) == original_length:
            return False
        
        # 更新时间线时长
        max_end = 0
        for track in timeline["tracks"]:
            for c in track["clips"]:
                max_end = max(max_end, c["start_time"] + c["duration"])
        timeline["settings"]["duration"] = max_end
        timeline["last_modified"] = datetime.now().isoformat()
        
        return True
    
    def add_marker(self, timeline_id: str, time: float, name: str = None, color: str = "red") -> Dict[str, Any]:
        """
        添加时间线标记
        
        Args:
            timeline_id: 时间线ID
            time: 标记时间
            name: 标记名称
            color: 标记颜色
            
        Returns:
            标记信息字典
        """
        timeline = self.get_timeline(timeline_id)
        if not timeline:
            raise ValueError(f"时间线不存在: {timeline_id}")
        
        marker_id = f"marker_{int(time.time())}"
        marker = {
            "id": marker_id,
            "time": time,
            "name": name or f"标记 {len(timeline['markers']) + 1}",
            "color": color,
            "created_at": datetime.now().isoformat()
        }
        
        timeline["markers"].append(marker)
        timeline["last_modified"] = datetime.now().isoformat()
        
        return marker
    
    def add_keyframe(self, timeline_id: str, clip_id: str, time: float, property_name: str, value: Any) -> Dict[str, Any]:
        """
        添加关键帧
        
        Args:
            timeline_id: 时间线ID
            clip_id: 片段ID
            time: 关键帧时间
            property_name: 属性名称
            value: 属性值
            
        Returns:
            关键帧信息字典
        """
        timeline = self.get_timeline(timeline_id)
        if not timeline:
            raise ValueError(f"时间线不存在: {timeline_id}")
        
        keyframe_id = f"keyframe_{int(time.time())}"
        keyframe = {
            "id": keyframe_id,
            "clip_id": clip_id,
            "time": time,
            "property": property_name,
            "value": value,
            "created_at": datetime.now().isoformat()
        }
        
        timeline["keyframes"].append(keyframe)
        timeline["last_modified"] = datetime.now().isoformat()
        
        return keyframe
    
    def get_clips_at_time(self, timeline_id: str, time: float) -> List[Dict[str, Any]]:
        """
        获取指定时间点的所有片段
        
        Args:
            timeline_id: 时间线ID
            time: 时间点
            
        Returns:
            片段列表
        """
        timeline = self.get_timeline(timeline_id)
        if not timeline:
            return []
        
        clips = []
        for track in timeline["tracks"]:
            for clip in track["clips"]:
                if clip["start_time"] <= time < clip["start_time"] + clip["duration"]:
                    clips.append(clip)
        
        return clips
    
    def get_clip(self, timeline_id: str, clip_id: str) -> Optional[Dict[str, Any]]:
        """
        获取片段
        
        Args:
            timeline_id: 时间线ID
            clip_id: 片段ID
            
        Returns:
            片段信息字典，如果片段不存在则返回None
        """
        timeline = self.get_timeline(timeline_id)
        if not timeline:
            return None
        
        for track in timeline["tracks"]:
            for clip in track["clips"]:
                if clip["id"] == clip_id:
                    return clip
        
        return None
    
    def update_clip(self, timeline_id: str, clip_id: str, **kwargs) -> bool:
        """
        更新片段信息
        
        Args:
            timeline_id: 时间线ID
            clip_id: 片段ID
            **kwargs: 要更新的字段
            
        Returns:
            是否更新成功
        """
        clip = self.get_clip(timeline_id, clip_id)
        if not clip:
            return False
        
        clip.update(kwargs)
        
        timeline = self.get_timeline(timeline_id)
        timeline["last_modified"] = datetime.now().isoformat()
        
        return True
    
    def set_current_timeline(self, timeline_id: str) -> bool:
        """
        设置当前时间线
        
        Args:
            timeline_id: 时间线ID
            
        Returns:
            是否设置成功
        """
        if timeline_id in self.timelines:
            self.current_timeline_id = timeline_id
            return True
        return False
    
    def get_current_timeline(self) -> Optional[Dict[str, Any]]:
        """
        获取当前时间线
        
        Returns:
            当前时间线信息字典，如果没有设置则返回None
        """
        if self.current_timeline_id:
            return self.get_timeline(self.current_timeline_id)
        return None
    
    def delete_timeline(self, timeline_id: str) -> bool:
        """
        删除时间线
        
        Args:
            timeline_id: 时间线ID
            
        Returns:
            是否删除成功
        """
        if timeline_id in self.timelines:
            del self.timelines[timeline_id]
            if self.current_timeline_id == timeline_id:
                self.current_timeline_id = None
            return True
        return False
    
    def set_virtual_window(self, start_time: float, end_time: float) -> None:
        """设置虚拟时间窗口"""
        with self._lock:
            self.virtual_window_start = start_time
            self.virtual_window_end = end_time
            self._update_virtual_timeline()
    
    def set_virtual_scale(self, scale: float) -> None:
        """设置虚拟时间轴缩放比例"""
        with self._lock:
            self.virtual_scale = max(0.1, min(10.0, scale))
            self._update_virtual_timeline()
    
    def set_virtual_offset(self, offset: float) -> None:
        """设置虚拟时间轴偏移量"""
        with self._lock:
            self.virtual_offset = offset
            self._update_virtual_timeline()
    
    def get_virtual_window(self) -> Dict[str, float]:
        """获取虚拟时间窗口"""
        with self._lock:
            return {
                'start': self.virtual_window_start,
                'end': self.virtual_window_end,
                'duration': self.virtual_window_end - self.virtual_window_start,
                'scale': self.virtual_scale,
                'offset': self.virtual_offset
            }
    
    def get_virtual_clips(self) -> List[Dict[str, Any]]:
        """获取虚拟时间窗口内的所有片段"""
        with self._lock:
            virtual_clips = []
            
            if not self.current_timeline_id:
                return virtual_clips
            
            timeline = self.timelines.get(self.current_timeline_id)
            if not timeline:
                return virtual_clips
            
            for track in timeline['tracks']:
                for clip in track['clips']:
                    clip_start = clip['start_time']
                    clip_end = clip['start_time'] + clip['duration']
                    
                    virtual_start = self.virtual_window_start + self.virtual_offset
                    virtual_end = self.virtual_window_end + self.virtual_offset
                    
                    if clip_start < virtual_end and clip_end > virtual_start:
                        virtual_clips.append(clip)
            
            return virtual_clips
    
    def _update_virtual_timeline(self):
        """更新虚拟时间轴"""
        if not self.current_timeline_id:
            return
            
        cache_key = f"virtual_{self.current_timeline_id}_{self.virtual_window_start}_{self.virtual_window_end}_{self.virtual_scale}_{self.virtual_offset}"
        
        if cache_key in self.timeline_cache:
            self.virtual_timeline = self.timeline_cache[cache_key]
            return
        
        virtual_clips = self.get_virtual_clips()
        self.virtual_timeline = OrderedDict()
        
        for clip in virtual_clips:
            virtual_start = (clip['start_time'] - self.virtual_offset) / self.virtual_scale
            virtual_end = (clip['start_time'] + clip['duration'] - self.virtual_offset) / self.virtual_scale
            
            self.virtual_timeline[clip['id']] = {
                'id': clip['id'],
                'virtual_start': virtual_start,
                'virtual_end': virtual_end,
                'virtual_duration': virtual_end - virtual_start,
                'original_clip': clip
            }
        
        if len(self.timeline_cache) >= self.max_cache_size:
            self.timeline_cache.popitem(last=False)
        
        self.timeline_cache[cache_key] = self.virtual_timeline.copy()
    
    def clear_timeline_cache(self) -> None:
        """清理时间轴缓存"""
        with self._lock:
            self.timeline_cache.clear()
            self.virtual_timeline.clear()
    
    def get_timeline_stats(self, timeline_id: str = None) -> Dict[str, Any]:
        """获取时间轴统计信息"""
        target_timeline_id = timeline_id or self.current_timeline_id
        if not target_timeline_id:
            return {}
        
        timeline = self.timelines.get(target_timeline_id)
        if not timeline:
            return {}
        
        total_clips = sum(len(track['clips']) for track in timeline['tracks'])
        total_duration = max(
            (track['clips'][-1]['start_time'] + track['clips'][-1]['duration'] if track['clips'] else 0)
            for track in timeline['tracks']
        ) if timeline['tracks'] else 0
        
        return {
            'timeline_id': target_timeline_id,
            'total_clips': total_clips,
            'total_tracks': len(timeline['tracks']),
            'total_duration': total_duration,
            'video_tracks': len([t for t in timeline['tracks'] if t['type'] == 'video']),
            'audio_tracks': len([t for t in timeline['tracks'] if t['type'] == 'audio']),
            'cache_size': len(self.timeline_cache)
        }

    # --- Ripple 编辑系统 (对标 Shotcut/OpenShot) ---

    def ripple_delete_clip(self, timeline_id: str, track_id: str, clip_id: str) -> bool:
        """
        Ripple 删除：删除片段后，后续片段自动向前移动填补空隙

        Args:
            timeline_id: 时间线ID
            track_id: 轨道ID
            clip_id: 片段ID

        Returns:
            是否删除成功
        """
        timeline = self.get_timeline(timeline_id)
        if not timeline:
            return False

        track = None
        for t in timeline["tracks"]:
            if t["id"] == track_id:
                track = t
                break
        if not track:
            return False

        clip_to_delete = None
        for c in track["clips"]:
            if c["id"] == clip_id:
                clip_to_delete = c
                break
        if not clip_to_delete:
            return False

        clip_duration = clip_to_delete["duration"]
        clip_start = clip_to_delete["start_time"]

        # 删除片段
        track["clips"] = [c for c in track["clips"] if c["id"] != clip_id]

        # Ripple 推移：将后续片段向前移动
        for c in track["clips"]:
            if c["start_time"] > clip_start:
                c["start_time"] -= clip_duration
                c["start_time"] = max(0, c["start_time"])

        self._recalculate_duration(timeline)
        timeline["last_modified"] = datetime.now().isoformat()
        return True

    def insert_clip(self, timeline_id: str, track_id: str, clip_info: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        插入剪辑：在指定位置插入片段，后续片段自动后移

        Args:
            timeline_id: 时间线ID
            track_id: 轨道ID
            clip_info: 片段信息 (必须包含 start_time 和 duration)

        Returns:
            新片段信息，失败返回 None
        """
        timeline = self.get_timeline(timeline_id)
        if not timeline:
            return None

        track = None
        for t in timeline["tracks"]:
            if t["id"] == track_id:
                track = t
                break
        if not track:
            return None

        insert_time = clip_info.get("start_time", 0)
        clip_duration = clip_info.get("duration", 10)

        # Ripple 推移：将插入点之后的片段后移
        for c in track["clips"]:
            if c["start_time"] >= insert_time:
                c["start_time"] += clip_duration

        # 添加新片段
        return self.add_clip(timeline_id, track_id, clip_info)

    def overwrite_clip(self, timeline_id: str, track_id: str, clip_info: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        覆盖剪辑：在指定位置放置片段，覆盖重叠部分

        Args:
            timeline_id: 时间线ID
            track_id: 轨道ID
            clip_info: 片段信息 (必须包含 start_time 和 duration)

        Returns:
            新片段信息，失败返回 None
        """
        timeline = self.get_timeline(timeline_id)
        if not timeline:
            return None

        track = None
        for t in timeline["tracks"]:
            if t["id"] == track_id:
                track = t
                break
        if not track:
            return None

        new_start = clip_info.get("start_time", 0)
        new_duration = clip_info.get("duration", 10)
        new_end = new_start + new_duration

        # 移除与新片段重叠的片段
        track["clips"] = [
            c for c in track["clips"]
            if c["start_time"] + c["duration"] <= new_start or c["start_time"] >= new_end
        ]

        # 添加新片段
        return self.add_clip(timeline_id, track_id, clip_info)

    def lift_clip(self, timeline_id: str, track_id: str, clip_id: str) -> bool:
        """
        提升剪辑：删除片段，但保留空隙 (与 ripple_delete 相反)

        Args:
            timeline_id: 时间线ID
            track_id: 轨道ID
            clip_id: 片段ID

        Returns:
            是否删除成功
        """
        return self.delete_clip(timeline_id, track_id, clip_id)

    def ripple_move_clip(self, timeline_id: str, track_id: str, clip_id: str, new_start_time: float) -> bool:
        """
        Ripple 移动：移动片段，后续片段自动跟随

        Args:
            timeline_id: 时间线ID
            track_id: 轨道ID
            clip_id: 片段ID
            new_start_time: 新的开始时间

        Returns:
            是否移动成功
        """
        timeline = self.get_timeline(timeline_id)
        if not timeline:
            return False

        track = None
        clip = None
        for t in timeline["tracks"]:
            if t["id"] == track_id:
                track = t
                for c in t["clips"]:
                    if c["id"] == clip_id:
                        clip = c
                        break
                break
        if not clip:
            return False

        old_start = clip["start_time"]
        clip_duration = clip["duration"]
        delta = new_start_time - old_start

        # 如果向左移动，防止与左侧片段重叠
        if delta < 0:
            max_left_end = 0
            for c in track["clips"]:
                if c["id"] != clip_id and c["start_time"] + c["duration"] <= old_start:
                    max_left_end = max(max_left_end, c["start_time"] + c["duration"])
            if new_start_time < max_left_end:
                new_start_time = max_left_end
                delta = new_start_time - old_start

        # 移动片段
        clip["start_time"] = new_start_time

        # Ripple 推移后续片段
        for c in track["clips"]:
            if c["id"] != clip_id:
                if delta > 0 and c["start_time"] > old_start:
                    c["start_time"] += delta
                elif delta < 0 and c["start_time"] > new_start_time + clip_duration:
                    c["start_time"] += delta
                c["start_time"] = max(0, c["start_time"])

        self._recalculate_duration(timeline)
        timeline["last_modified"] = datetime.now().isoformat()
        return True

    def slip_clip(self, timeline_id: str, track_id: str, clip_id: str, slip_delta: float) -> bool:
        """
        Slip 编辑：保持片段时间位置不变，调整素材的入点/出点

        Args:
            timeline_id: 时间线ID
            track_id: 轨道ID
            clip_id: 片段ID
            slip_delta: 滑移量 (正=向右滑，负=向左滑)

        Returns:
            是否成功
        """
        clip = self.get_clip(timeline_id, clip_id)
        if not clip:
            return False

        new_in = clip["in_point"] + slip_delta
        if new_in < 0:
            return False

        clip["in_point"] = new_in
        clip["out_point"] = clip["in_point"] + clip["duration"]

        timeline = self.get_timeline(timeline_id)
        if timeline:
            timeline["last_modified"] = datetime.now().isoformat()
        return True

    def slide_clip(self, timeline_id: str, track_id: str, clip_id: str, slide_delta: float) -> bool:
        """
        Slide 编辑：保持素材入点/出点不变，移动片段在时间轴上的位置

        Args:
            timeline_id: 时间线ID
            track_id: 轨道ID
            clip_id: 片段ID
            slide_delta: 滑动量

        Returns:
            是否成功
        """
        clip = self.get_clip(timeline_id, clip_id)
        if not clip:
            return False
        return self.move_clip(timeline_id, track_id, clip_id,
                              clip["start_time"] + slide_delta)

    def _recalculate_duration(self, timeline: Dict[str, Any]) -> None:
        """重新计算时间线总时长"""
        max_end = 0
        for track in timeline["tracks"]:
            for c in track["clips"]:
                max_end = max(max_end, c["start_time"] + c["duration"])
        timeline["settings"]["duration"] = max_end

    # --- 结束 Ripple 编辑系统 ---


# 全局时间线管理器实例
timeline_manager = TimelineManager()
