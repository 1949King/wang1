"""
时间线核心模块
==================
整合原有timeline_manager.py功能，提供专业级时间线管理能力
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
from collections import OrderedDict
import threading
import logging

logger = logging.getLogger("AI短剧编辑器.timeline_core")


class TimelineCore:
    """时间线核心管理器"""
    
    def __init__(self):
        self.timelines = {}
        self.current_timeline_id = None
        self._lock = threading.RLock()
        
        self.virtual_timeline = OrderedDict()
        self.virtual_window_start = 0.0
        self.virtual_window_end = 0.0
        self.virtual_scale = 1.0
        self.virtual_offset = 0.0
        
        self.timeline_cache = {}
        self.max_cache_size = 100
    
    def create_timeline(self, name: str, resolution: str = "1920x1080", fps: int = 30) -> Dict[str, Any]:
        """创建时间线"""
        timeline_id = f"timeline_{int(datetime.now().timestamp())}"
        
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
                {
                    "id": "video_1",
                    "name": "视频轨道 1",
                    "type": "video",
                    "clips": []
                },
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
        
        with self._lock:
            self.timelines[timeline_id] = timeline
            self.current_timeline_id = timeline_id
        
        return timeline
    
    def get_timeline(self, timeline_id: str) -> Optional[Dict[str, Any]]:
        """获取时间线"""
        with self._lock:
            return self.timelines.get(timeline_id)
    
    def set_current_timeline(self, timeline_id: str) -> bool:
        """设置当前时间线"""
        with self._lock:
            if timeline_id in self.timelines:
                self.current_timeline_id = timeline_id
                return True
        return False
    
    def get_current_timeline(self) -> Optional[Dict[str, Any]]:
        """获取当前时间线"""
        with self._lock:
            if self.current_timeline_id:
                return self.timelines.get(self.current_timeline_id)
        return None
    
    def delete_timeline(self, timeline_id: str) -> bool:
        """删除时间线"""
        with self._lock:
            if timeline_id in self.timelines:
                del self.timelines[timeline_id]
                if self.current_timeline_id == timeline_id:
                    self.current_timeline_id = None
                return True
        return False
    
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


# 全局时间线核心管理器实例
timeline_core = TimelineCore()