class PresetManager:
    def __init__(self):
        self.presets = {
            "effect": [],
            "transition": [],
            "export": [],
            "audio": [],
            "subtitle": []
        }
        self._initialize_default_presets()
    
    def _initialize_default_presets(self):
        """初始化默认预设"""
        # 特效预设
        self.presets["effect"].extend([
            {
                "id": "effect_preset_1",
                "name": "电影风格",
                "type": "effect",
                "category": "color",
                "parameters": {
                    "brightness": 0.9,
                    "contrast": 1.2,
                    "saturation": 1.1,
                    "hue": 0.0,
                    "gamma": 1.0
                },
                "effects": ["brightness", "contrast", "saturation"]
            },
            {
                "id": "effect_preset_2",
                "name": "复古风格",
                "type": "effect",
                "category": "color",
                "parameters": {
                    "brightness": 0.8,
                    "contrast": 1.0,
                    "saturation": 0.7,
                    "sepia": 0.6
                },
                "effects": ["brightness", "contrast", "saturation", "sepia"]
            },
            {
                "id": "effect_preset_3",
                "name": "黑白风格",
                "type": "effect",
                "category": "color",
                "parameters": {
                    "saturation": 0.0,
                    "contrast": 1.3
                },
                "effects": ["saturation", "contrast"]
            }
        ])
        
        # 转场预设
        self.presets["transition"].extend([
            {
                "id": "transition_preset_1",
                "name": "平滑淡入淡出",
                "type": "transition",
                "category": "fade",
                "parameters": {
                    "duration": 1.0,
                    "ease_in": 0.5,
                    "ease_out": 0.5
                },
                "transition_type": "fade"
            },
            {
                "id": "transition_preset_2",
                "name": "快速滑动",
                "type": "transition",
                "category": "slide",
                "parameters": {
                    "duration": 0.5,
                    "direction": "left",
                    "ease": "ease_out"
                },
                "transition_type": "slide"
            }
        ])
        
        # 导出预设
        self.presets["export"].extend([
            {
                "id": "export_preset_1",
                "name": "HD 1080p",
                "type": "export",
                "category": "video",
                "parameters": {
                    "resolution": "1920x1080",
                    "frame_rate": 30,
                    "bitrate": "10M",
                    "codec": "h264",
                    "audio_codec": "aac",
                    "audio_bitrate": "128k"
                }
            },
            {
                "id": "export_preset_2",
                "name": "4K Ultra HD",
                "type": "export",
                "category": "video",
                "parameters": {
                    "resolution": "3840x2160",
                    "frame_rate": 60,
                    "bitrate": "30M",
                    "codec": "h265",
                    "audio_codec": "aac",
                    "audio_bitrate": "256k"
                }
            },
            {
                "id": "export_preset_3",
                "name": "社交媒体",
                "type": "export",
                "category": "video",
                "parameters": {
                    "resolution": "1080x1080",
                    "frame_rate": 30,
                    "bitrate": "5M",
                    "codec": "h264",
                    "audio_codec": "aac",
                    "audio_bitrate": "128k"
                }
            }
        ])
        
        # 音频预设
        self.presets["audio"].extend([
            {
                "id": "audio_preset_1",
                "name": "电影音频",
                "type": "audio",
                "category": "mix",
                "parameters": {
                    "volume": 1.0,
                    "bass": 1.2,
                    "mid": 1.0,
                    "treble": 1.1,
                    "compression": 0.5
                }
            },
            {
                "id": "audio_preset_2",
                "name": "语音优化",
                "type": "audio",
                "category": "voice",
                "parameters": {
                    "volume": 1.2,
                    "bass": 0.8,
                    "mid": 1.3,
                    "treble": 1.1,
                    "noise_reduction": 0.6
                }
            }
        ])
        
        # 字幕预设
        self.presets["subtitle"].extend([
            {
                "id": "subtitle_preset_1",
                "name": "电影字幕",
                "type": "subtitle",
                "category": "display",
                "parameters": {
                    "font": "Arial",
                    "font_size": 24,
                    "color": "#FFFFFF",
                    "background": "#000000",
                    "opacity": 0.8,
                    "alignment": "bottom",
                    "margin": 30
                }
            },
            {
                "id": "subtitle_preset_2",
                "name": "标题字幕",
                "type": "subtitle",
                "category": "display",
                "parameters": {
                    "font": "Arial Bold",
                    "font_size": 36,
                    "color": "#FFFFFF",
                    "background": "transparent",
                    "opacity": 1.0,
                    "alignment": "center",
                    "margin": 50
                }
            }
        ])
    
    def create_preset(self, name, preset_type, parameters, category="default"):
        """创建预设"""
        if preset_type not in self.presets:
            return None
        
        preset = {
            "id": f"{preset_type}_preset_{len(self.presets[preset_type]) + 1}",
            "name": name,
            "type": preset_type,
            "category": category,
            "parameters": parameters,
            "created_at": "2024-01-01T00:00:00"
        }
        
        self.presets[preset_type].append(preset)
        return preset
    
    def get_preset(self, preset_id):
        """获取预设"""
        for preset_type, presets in self.presets.items():
            for preset in presets:
                if preset["id"] == preset_id:
                    return preset
        return None
    
    def list_presets(self, preset_type=None, category=None):
        """列出预设"""
        if preset_type:
            if preset_type not in self.presets:
                return []
            presets = self.presets[preset_type]
        else:
            presets = [p for ps in self.presets.values() for p in ps]
        
        if category:
            presets = [p for p in presets if p.get("category") == category]
        
        return presets
    
    def update_preset(self, preset_id, **kwargs):
        """更新预设"""
        preset = self.get_preset(preset_id)
        if preset:
            preset.update(kwargs)
            return True
        return False
    
    def delete_preset(self, preset_id):
        """删除预设"""
        for preset_type, presets in self.presets.items():
            for i, preset in enumerate(presets):
                if preset["id"] == preset_id:
                    self.presets[preset_type].pop(i)
                    return True
        return False
    
    def search_presets(self, query, preset_type=None):
        """搜索预设"""
        if preset_type:
            if preset_type not in self.presets:
                return []
            presets = self.presets[preset_type]
        else:
            presets = [p for ps in self.presets.values() for p in ps]
        
        return [p for p in presets if query.lower() in p["name"].lower() or 
                query.lower() in p.get("category", "").lower()]
    
    def import_preset(self, file_path):
        """导入预设"""
        # 这里应该实现实际的预设导入逻辑
        # 暂时返回模拟数据
        imported_presets = []
        return imported_presets
    
    def export_preset(self, preset_id, file_path):
        """导出预设"""
        preset = self.get_preset(preset_id)
        if preset:
            # 这里应该实现实际的预设导出逻辑
            return True
        return False
    
    def apply_preset(self, preset_id, target):
        """应用预设到目标"""
        preset = self.get_preset(preset_id)
        if preset:
            # 这里应该实现实际的预设应用逻辑
            # 暂时返回成功
            return True
        return False
    
    def duplicate_preset(self, preset_id, new_name):
        """复制预设"""
        preset = self.get_preset(preset_id)
        if preset:
            new_preset = preset.copy()
            new_preset["id"] = f"{preset['type']}_preset_{len(self.presets[preset['type']]) + 1}"
            new_preset["name"] = new_name
            new_preset["created_at"] = "2024-01-01T00:00:00"
            
            self.presets[preset['type']].append(new_preset)
            return new_preset
        return None
    
    def get_preset_categories(self, preset_type=None):
        """获取预设分类"""
        categories = set()
        if preset_type:
            if preset_type in self.presets:
                for preset in self.presets[preset_type]:
                    categories.add(preset.get("category", "default"))
        else:
            for presets in self.presets.values():
                for preset in presets:
                    categories.add(preset.get("category", "default"))
        
        return list(categories)
    
    def reset_to_defaults(self, preset_type=None):
        """重置为默认预设"""
        if preset_type:
            if preset_type in self.presets:
                self.presets[preset_type] = []
        else:
            self.presets = {
                "effect": [],
                "transition": [],
                "export": [],
                "audio": [],
                "subtitle": []
            }
        
        self._initialize_default_presets()
        return True