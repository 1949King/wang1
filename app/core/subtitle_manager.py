import os
import re
import numpy as np

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
            "position": {"x": 0.5, "y": 0.85},
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
    
    def add_subtitle(self, text, start_time, end_time, style="default"):
        """添加字幕（EditorModule使用的别名）"""
        return self.create_subtitle(text, start_time, end_time, style)

    def import_subtitles(self, file_path, format="srt"):
        """导入字幕文件 - 支持SRT/VTT格式"""
        imported = []
        if not os.path.exists(file_path):
            return imported
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            if format == "srt":
                imported = self._parse_srt(content)
            elif format == "vtt":
                imported = self._parse_vtt(content)
            for sub in imported:
                self.subtitles.append(sub)
        except Exception as e:
            print(f"导入字幕失败: {e}")
        return imported

    def _parse_srt(self, content):
        subs = []
        blocks = re.split(r'\n\s*\n', content.strip())
        for block in blocks:
            lines = block.strip().split('\n')
            if len(lines) < 2:
                continue
            idx = lines[0].strip()
            times = lines[1].strip()
            text = '\n'.join(lines[2:])
            match = re.match(r'(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)', times)
            if match:
                sh, sm, ss, sms = map(int, match.groups()[:4])
                eh, em, es, ems = map(int, match.groups()[4:])
                start = sh * 3600 + sm * 60 + ss + sms / 1000.0
                end = eh * 3600 + em * 60 + es + ems / 1000.0
                sub = self.create_subtitle(text, start, end)
                subs.append(sub)
        return subs

    def _parse_vtt(self, content):
        content = re.sub(r'^\s*WEBVTT.*?\n\n', '', content, flags=re.S)
        return self._parse_srt(content)

    def export_subtitles(self, file_path, format="srt"):
        """导出字幕为 SRT / ASS 文件。"""
        fmt = (format or "srt").lower().lstrip(".")
        if fmt == "ass":
            return self.export_subtitles_ass(file_path)
        try:
            sorted_subs = sorted(self.subtitles, key=lambda s: s["start_time"])
            with open(file_path, "w", encoding="utf-8") as f:
                for i, sub in enumerate(sorted_subs, 1):
                    if not sub.get("visible", True):
                        continue
                    st = self._sec_to_srt(sub["start_time"])
                    et = self._sec_to_srt(sub["end_time"])
                    f.write(f"{i}\n{st} --> {et}\n{sub['text']}\n\n")
            return True
        except Exception as e:
            print(f"导出字幕失败: {e}")
            return False

    def _sec_to_ass(self, sec: float) -> str:
        """ASS 时间码 H:MM:SS.cc（厘秒）。"""
        sec = max(0.0, float(sec or 0))
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = int(sec % 60)
        cs = int(round((sec % 1) * 100))
        if cs >= 100:
            cs = 0
            s += 1
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

    @staticmethod
    def _hex_to_ass_color(hex_color, alpha: int = 0) -> str:
        """#RRGGBB → ASS &HAABBGGRR（alpha: 00 不透明, FF 全透）。"""
        named = {
            "白": "#FFFFFF", "白色": "#FFFFFF", "white": "#FFFFFF",
            "黑": "#000000", "黑色": "#000000", "black": "#000000",
            "红": "#FF0000", "红色": "#FF0000",
            "黄": "#FFFF00", "黄色": "#FFFF00",
            "蓝": "#0000FF", "蓝色": "#0000FF",
            "绿": "#00FF00", "绿色": "#00FF00",
        }
        c = str(hex_color or "#FFFFFF").strip()
        if c.lower() in ("transparent", "none", ""):
            return f"&H{max(0, min(255, int(alpha))):02X}000000"
        c = named.get(c, named.get(c.lower(), c))
        if c.startswith("#"):
            c = c[1:]
        if len(c) >= 8:  # AARRGGBB
            try:
                a = int(c[0:2], 16)
                r, g, b = int(c[2:4], 16), int(c[4:6], 16), int(c[6:8], 16)
                # CSS alpha 0=透 → ASS FF=透
                ass_a = 255 - a
                return f"&H{ass_a:02X}{b:02X}{g:02X}{r:02X}"
            except ValueError as e:
                logger.debug(f"[SubtitleManager] 转换颜色值失败: {e}")
        if len(c) < 6:
            c = (c + "FFFFFF")[:6]
        try:
            r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
        except ValueError as e:
            r, g, b = 255, 255, 255
        a = max(0, min(255, int(alpha)))
        return f"&H{a:02X}{b:02X}{g:02X}{r:02X}"

    @staticmethod
    def _ass_escape_text(text: str) -> str:
        t = str(text or "")
        t = t.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
        t = t.replace("\r\n", "\\N").replace("\n", "\\N").replace("\r", "\\N")
        return t

    def export_subtitles_ass(self, file_path, play_res=(1920, 1080)) -> bool:
        """导出带样式/位置的 ASS，供 FFmpeg libass 烧录（与预览对齐）。"""
        try:
            res_x, res_y = int(play_res[0]), int(play_res[1])
            lines = [
                "[Script Info]",
                "ScriptType: v4.00+",
                f"PlayResX: {res_x}",
                f"PlayResY: {res_y}",
                "WrapStyle: 0",
                "ScaledBorderAndShadow: yes",
                "",
                "[V4+ Styles]",
                "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
                "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
                "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            ]
            # 为每个已用样式生成 Style 行；未用的也带上 default
            used = {"default"}
            for sub in self.subtitles:
                used.add(str(sub.get("style") or "default"))
            for style_name in sorted(used):
                style = self.get_subtitle_style(style_name) or {}
                font = str(style.get("font") or "Microsoft YaHei").replace("Arial Bold", "Arial")
                if "Bold" in font and font != "Arial":
                    font = font.replace(" Bold", "").replace("Bold", "").strip() or "Microsoft YaHei"
                fontsize = int(style.get("font_size", 28) or 28)
                primary = self._hex_to_ass_color(style.get("color") or "#FFFFFF", 0)
                outline_c = self._hex_to_ass_color(
                    style.get("border_color") or style.get("outline_color") or "#000000", 0
                )
                if str(style.get("border_color") or "").lower() in ("transparent", "none"):
                    outline_c = self._hex_to_ass_color("#000000", 0)
                bg = str(style.get("background") or "transparent")
                if bg.lower() in ("transparent", "none", ""):
                    back = self._hex_to_ass_color("#000000", 128)
                    border_style = 1  # outline
                else:
                    # opacity 0.8 → ASS alpha ~51
                    op = float(style.get("opacity", 0.8) or 0.8)
                    ass_a = int(round((1.0 - max(0.0, min(1.0, op))) * 255))
                    back = self._hex_to_ass_color(bg, ass_a)
                    border_style = 3  # opaque box
                outline_w = float(
                    style.get("border_width", style.get("outline", style.get("stroke", 2))) or 2
                )
                shadow_depth = {"无": 0, "柔和": 1, "硬边": 2, "投影": 3, "发光": 2}.get(
                    str(style.get("shadow") or "无"), 0
                )
                if str(style.get("shadow") or "无") == "发光":
                    outline_w = max(outline_w, 3.0)  # 无原生 glow，加粗描边近似发光
                bold = 1 if "bold" in str(style.get("font") or "").lower() else 0
                safe_name = re.sub(r"[^A-Za-z0-9_]", "_", style_name) or "Default"
                lines.append(
                    f"Style: {safe_name},{font},{fontsize},{primary},&H000000FF,{outline_c},{back},"
                    f"{bold},0,0,0,100,100,0,0,{border_style},{outline_w:.1f},{shadow_depth},5,40,40,40,1"
                )
            lines.extend([
                "",
                "[Events]",
                "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
            ])
            sorted_subs = sorted(self.subtitles, key=lambda s: float(s.get("start_time", 0) or 0))
            for sub in sorted_subs:
                if not sub.get("visible", True):
                    continue
                style_name = str(sub.get("style") or "default")
                safe_name = re.sub(r"[^A-Za-z0-9_]", "_", style_name) or "Default"
                pos = sub.get("position") or {}
                try:
                    xr = float(pos.get("x", 0.5))
                    yr = float(pos.get("y", 0.85))
                except (TypeError, ValueError):
                    xr, yr = 0.5, 0.85
                xr = min(0.98, max(0.02, xr))
                yr = min(0.95, max(0.05, yr))
                px = int(round(res_x * xr)) + int(sub.get("offset_x", 0) or 0)
                py = int(round(res_y * yr)) + int(sub.get("offset_y", 0) or 0)
                text = self._ass_escape_text(sub.get("text", ""))
                if not text:
                    continue
                start_sec = float(sub.get("start_time", 0) or 0)
                end_sec = float(sub.get("end_time", 0) or 0)
                st = self._sec_to_ass(start_sec)
                et = self._sec_to_ass(end_sec)
                dur_ms = max(0.0, (end_sec - start_sec) * 1000.0)
                anim_tag = self._build_ass_anim_tag(
                    sub.get("anim_in"), sub.get("anim_out"),
                    sub.get("anim_duration_ms", 500), px, py, dur_ms,
                )
                # \an5 = 中心锚点，与预览按 (x,y) 比率定位一致
                lines.append(
                    f"Dialogue: 0,{st},{et},{safe_name},,0,0,0,,{{\\an5{anim_tag}}}{text}"
                )
            with open(file_path, "w", encoding="utf-8-sig") as f:
                f.write("\n".join(lines) + "\n")
            return True
        except Exception as e:
            print(f"导出 ASS 字幕失败: {e}")
            return False

    def _build_ass_anim_tag(self, anim_in, anim_out, dur_ms, px, py, total_dur_ms) -> str:
        """把「入场/出场」动画映射为 ASS override 标签（\\pos/\\move + \\fad + \\t 缩放旋转）。

        位置类（滑入/滑出）用 \\move 实现，ASS 只支持单个 \\move，二者都存在时优先入场，
        出场退化为淡出（仍有动效，非零效果）；缩放/淡入淡出可与位置动画独立叠加。
        """
        anim_in = str(anim_in or "无")
        anim_out = str(anim_out or "无")
        d = max(50.0, float(dur_ms or 500))
        total = max(d, float(total_dur_ms or 0))
        slide_off = {
            "滑入上": (0, -80), "滑入下": (0, 80), "滑入左": (-120, 0), "滑入右": (120, 0),
            "滑出上": (0, -80), "滑出下": (0, 80), "滑出左": (-120, 0), "滑出右": (120, 0),
        }
        tags = []
        fade_in = int(d) if anim_in == "淡入" else 0
        fade_out = int(d) if anim_out == "淡出" else 0
        pos_tag = f"\\pos({px},{py})"
        if anim_in in slide_off:
            dx, dy = slide_off[anim_in]
            pos_tag = f"\\move({px + dx},{py + dy},{px},{py},0,{int(d)})"
        elif anim_out in slide_off:
            dx, dy = slide_off[anim_out]
            t1 = max(0, int(total - d))
            pos_tag = f"\\move({px},{py},{px + dx},{py + dy},{t1},{int(total)})"
        tags.append(pos_tag)
        if fade_in or fade_out:
            tags.append(f"\\fad({fade_in},{fade_out})")
        if anim_in == "缩放进入":
            tags.append(f"\\fscx20\\fscy20\\t(0,{int(d)},\\fscx100\\fscy100)")
        if anim_in == "旋转进入":
            tags.append(f"\\frz-30\\t(0,{int(d)},\\frz0)")
        if anim_out == "缩放退出":
            t1 = max(0, int(total - d))
            tags.append(f"\\t({t1},{int(total)},\\fscx20\\fscy20)")
        return "".join(tags)

    def _sec_to_srt(self, sec):
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = int(sec % 60)
        ms = int((sec % 1) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    def render_to_frame(self, frame: np.ndarray, time_sec: float) -> np.ndarray:
        """将当前时间的字幕渲染叠加到帧上"""
        result = frame.copy()
        try:
            import cv2
            CV2_AVAILABLE = True
        except ImportError:
            CV2_AVAILABLE = False
        active = [s for s in self.subtitles
                  if s.get("visible", True) and s["start_time"] <= time_sec <= s["end_time"]]
        for sub in active:
            style = self.get_subtitle_style(sub.get("style", "default"))
            text = sub["text"]
            h, w = result.shape[:2]
            font = cv2.FONT_HERSHEY_SIMPLEX if CV2_AVAILABLE else None
            font_scale = style["font_size"] / 30.0 if CV2_AVAILABLE else 1.0
            thickness = max(1, int(style["font_size"] / 15))
            if CV2_AVAILABLE:
                (tw, th), baseline = cv2.getTextSize(text, font, font_scale, thickness)
                x = int((w - tw) / 2)
                y = int(h * sub["position"]["y"])
                overlay = result.copy()
                cv2.rectangle(overlay, (x - 10, y - th - 10), (x + tw + 10, y + 10),
                              (0, 0, 0), -1)
                result = cv2.addWeighted(overlay, 0.6, result, 0.4, 0)
                cv2.putText(result, text, (x, y), font, font_scale,
                            (255, 255, 255), thickness, cv2.LINE_AA)
        return result
    
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

    def compute_frame_bindings(self, clip, fps=30.0):
        """
        B0：为当前字幕列表计算 timeline/source 帧级绑定（不写 _clips）。

        clip: EditorModule._clips 条目 dict
        fps:  项目或片源帧率；B1 Ripple Delete 读 binding.timeline_frame_in/out

        返回 List[TextFrameBinding]；可用 enrich_subtitle_dicts_with_bindings 挂到条目。
        """
        try:
            from app.core.text_frame_map import bind_subtitle_items_to_clip
        except ImportError:
            from core.text_frame_map import bind_subtitle_items_to_clip
        return bind_subtitle_items_to_clip(self.subtitles, clip, fps=fps)