class SubtitleManager:
    def __init__(self):
        self.subtitles = []
        self.subtitle_styles = {
            "default": {
                "name": "默认样式",
                "font": "Arial",
                "font_size": 24,
                "color": "#FFFFFF",
                "background": "#000000",
                "opacity": 0.8,
                "alignment": "center",
                "margin": 30
            },
            "title": {
                "name": "标题样式",
                "font": "Arial Bold",
                "font_size": 32,
                "color": "#FFFFFF",
                "background": "#000000",
                "opacity": 0.9,
                "alignment": "center",
                "margin": 40
            },
            "dialogue": {
                "name": "对话样式",
                "font": "Arial",
                "font_size": 20,
                "color": "#FFFFFF",
                "background": "#000000",
                "opacity": 0.7,
                "alignment": "bottom",
                "margin": 20
            },
            "credits": {
                "name": " credits样式",
                "font": "Arial",
                "font_size": 18,
                "color": "#FFFFFF",
                "background": "transparent",
                "opacity": 1.0,
                "alignment": "center",
                "margin": 50
            }
        }
    
    def create_subtitle(self, text, start_time, end_time, style="default"):
        """创建字幕"""
        subtitle = {
            "id": f"subtitle_{len(self.subtitles) + 1}",
            "text": text,
            "start_time": start_time,
            "end_time": end_time,
            "style": style,
            "position": {"x": 0.5, "y": 0.8},
            "visible": True
        }
        self.subtitles.append(subtitle)
        return subtitle
    
    def update_subtitle(self, subtitle_id, **kwargs):
        """更新字幕"""
        for subtitle in self.subtitles:
            if subtitle["id"] == subtitle_id:
                subtitle.update(kwargs)
                return True
        return False
    
    def delete_subtitle(self, subtitle_id):
        """删除字幕"""
        self.subtitles = [s for s in self.subtitles if s["id"] != subtitle_id]
        return True
    
    def list_subtitles(self):
        """列出所有字幕"""
        return self.subtitles
    
    def get_subtitle(self, subtitle_id):
        """获取字幕"""
        for subtitle in self.subtitles:
            if subtitle["id"] == subtitle_id:
                return subtitle
        return None
    
    def search_subtitles(self, text):
        """搜索字幕"""
        return [s for s in self.subtitles if text.lower() in s["text"].lower()]
    
    def sort_subtitles(self, by="start_time"):
        """排序字幕"""
        if by == "start_time":
            self.subtitles.sort(key=lambda x: x["start_time"])
        elif by == "end_time":
            self.subtitles.sort(key=lambda x: x["end_time"])
        elif by == "text":
            self.subtitles.sort(key=lambda x: x["text"])
        return self.subtitles
    
    def create_subtitle_style(self, name, **style_properties):
        """创建字幕样式"""
        style = self.subtitle_styles["default"].copy()
        style.update(style_properties)
        style["name"] = name
        self.subtitle_styles[name] = style
        return style
    
    def update_subtitle_style(self, style_name, **properties):
        """更新字幕样式"""
        if style_name in self.subtitle_styles:
            self.subtitle_styles[style_name].update(properties)
            return True
        return False
    
    def delete_subtitle_style(self, style_name):
        """删除字幕样式"""
        if style_name in self.subtitle_styles and style_name != "default":
            del self.subtitle_styles[style_name]
            return True
        return False
    
    def list_subtitle_styles(self):
        """列出所有字幕样式"""
        return list(self.subtitle_styles.values())
    
    def get_subtitle_style(self, style_name):
        """获取字幕样式"""
        return self.subtitle_styles.get(style_name, self.subtitle_styles["default"])
    
    def apply_style_to_subtitle(self, subtitle_id, style_name):
        """应用样式到字幕"""
        if style_name in self.subtitle_styles:
            for subtitle in self.subtitles:
                if subtitle["id"] == subtitle_id:
                    subtitle["style"] = style_name
                    return True
        return False
    
    def batch_create_subtitles(self, subtitles_data):
        """批量创建字幕"""
        created_subtitles = []
        for data in subtitles_data:
            subtitle = self.create_subtitle(
                data.get("text"),
                data.get("start_time"),
                data.get("end_time"),
                data.get("style", "default")
            )
            created_subtitles.append(subtitle)
        return created_subtitles
    
    def import_subtitles(self, file_path, format="srt"):
        """导入字幕文件"""
        # 这里应该实现实际的字幕文件导入逻辑
        # 暂时返回模拟数据
        imported_subtitles = []
        # 模拟导入SRT格式字幕
        if format == "srt":
            # 示例SRT格式解析
            pass
        return imported_subtitles
    
    def export_subtitles(self, file_path, format="srt"):
        """导出字幕文件"""
        # 这里应该实现实际的字幕文件导出逻辑
        # 暂时返回成功
        return True
    
    def sync_subtitles(self, time_offset):
        """同步字幕时间"""
        for subtitle in self.subtitles:
            subtitle["start_time"] += time_offset
            subtitle["end_time"] += time_offset
        return True
    
    def adjust_subtitle_duration(self, subtitle_id, duration_change):
        """调整字幕持续时间"""
        for subtitle in self.subtitles:
            if subtitle["id"] == subtitle_id:
                subtitle["end_time"] += duration_change
                return True
        return False
    
    def set_subtitle_position(self, subtitle_id, x, y):
        """设置字幕位置"""
        for subtitle in self.subtitles:
            if subtitle["id"] == subtitle_id:
                subtitle["position"] = {"x": x, "y": y}
                return True
        return False
    
    def toggle_subtitle_visibility(self, subtitle_id, visible=None):
        """切换字幕可见性"""
        for subtitle in self.subtitles:
            if subtitle["id"] == subtitle_id:
                if visible is None:
                    subtitle["visible"] = not subtitle["visible"]
                else:
                    subtitle["visible"] = visible
                return True
        return False
    
    def duplicate_subtitle(self, subtitle_id):
        """复制字幕"""
        subtitle = self.get_subtitle(subtitle_id)
        if subtitle:
            new_subtitle = subtitle.copy()
            new_subtitle["id"] = f"subtitle_{len(self.subtitles) + 1}"
            new_subtitle["start_time"] += 1.0  # 偏移1秒
            new_subtitle["end_time"] += 1.0
            self.subtitles.append(new_subtitle)
            return new_subtitle
        return None
    
    def split_subtitle(self, subtitle_id, split_time):
        """分割字幕"""
        subtitle = self.get_subtitle(subtitle_id)
        if subtitle:
            if subtitle["start_time"] < split_time < subtitle["end_time"]:
                # 创建第二个字幕
                new_subtitle = subtitle.copy()
                new_subtitle["id"] = f"subtitle_{len(self.subtitles) + 1}"
                new_subtitle["start_time"] = split_time
                
                # 更新第一个字幕
                subtitle["end_time"] = split_time
                
                self.subtitles.append(new_subtitle)
                return [subtitle, new_subtitle]
        return None
    
    def merge_subtitles(self, subtitle_id1, subtitle_id2):
        """合并字幕"""
        subtitle1 = self.get_subtitle(subtitle_id1)
        subtitle2 = self.get_subtitle(subtitle_id2)
        
        if subtitle1 and subtitle2:
            # 确保subtitle1在subtitle2之前
            if subtitle1["start_time"] > subtitle2["start_time"]:
                subtitle1, subtitle2 = subtitle2, subtitle1
            
            # 合并文本
            merged_text = subtitle1["text"] + " " + subtitle2["text"]
            
            # 更新第一个字幕
            subtitle1["end_time"] = subtitle2["end_time"]
            subtitle1["text"] = merged_text
            
            # 删除第二个字幕
            self.delete_subtitle(subtitle_id2)
            
            return subtitle1
        return None
    
    def preview_subtitle(self, subtitle_id):
        """预览字幕"""
        subtitle = self.get_subtitle(subtitle_id)
        if subtitle:
            style = self.get_subtitle_style(subtitle["style"])
            return {
                "subtitle": subtitle,
                "style": style,
                "preview_html": f"<div style='font-family:{style['font']}; font-size:{style['font_size']}px; color:{style['color']}; background:{style['background']}; opacity:{style['opacity']}; text-align:{style['alignment']}; margin:{style['margin']}px;'>{subtitle['text']}</div>"
            }
        return None