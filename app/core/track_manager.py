from modules.utils.logger import logger

class TrackManager:
    def __init__(self):
        self.tracks = []
        self.copied_clip_properties = None
    
    def get_track_by_id(self, track_id):
        """根据ID获取轨道"""
        return next((track for track in self.tracks if track.get("id") == track_id), None)
    
    def copy_clip_properties(self, track_id, clip_id):
        """复制剪辑片段的属性"""
        track = self.get_track_by_id(track_id)
        if not track:
            return False
        
        clip = next((c for c in track["clips"] if c["id"] == clip_id), None)
        if not clip:
            return False
        
        # 复制需要的属性
        self.copied_clip_properties = {
            "filters": clip.get("filters", []),
            "color_correction": clip.get("color_correction", {}),
            "speed": clip.get("speed", 1.0),
            "volume": clip.get("volume", 1.0),
            "effects": clip.get("effects", [])
        }
        
        logger.info(f"剪辑片段 {clip_id} 的属性已复制")
        return True
    
    def paste_clip_properties(self, track_id, clip_ids):
        """粘贴属性到多个剪辑片段"""
        if not self.copied_clip_properties:
            return False
        
        track = self.get_track_by_id(track_id)
        if not track:
            return False
        
        for clip_id in clip_ids:
            clip = next((c for c in track["clips"] if c["id"] == clip_id), None)
            if clip:
                # 粘贴属性
                clip["filters"] = self.copied_clip_properties["filters"].copy()
                clip["color_correction"] = self.copied_clip_properties["color_correction"].copy()
                clip["speed"] = self.copied_clip_properties["speed"]
                clip["volume"] = self.copied_clip_properties["volume"]
                clip["effects"] = self.copied_clip_properties["effects"].copy()
        
        logger.info(f"属性已粘贴到 {len(clip_ids)} 个剪辑片段")
        return True