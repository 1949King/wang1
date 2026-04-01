# FunClip 集成模块

class FunClipIntegration:
    """FunClip集成类，提供自动剪辑和字幕生成功能"""
    
    def __init__(self):
        """初始化FunClip集成"""
        self.initialized = False
        self.initialize()
    
    def initialize(self):
        """初始化FunClip"""
        try:
            # 导入必要的库
            import whisper
            import moviepy.editor as mp
            import os
            import tempfile
            
            # 加载Whisper模型用于语音识别
            self.whisper_model = whisper.load_model("base")
            self.initialized = True
            print("FunClip初始化成功")
        except Exception as e:
            print(f"FunClip初始化失败: {e}")
            self.initialized = False
    
    def auto_edit(self, video_path, **kwargs):
        """自动剪辑视频
        
        Args:
            video_path: 视频文件路径
            **kwargs: 额外参数
                highlight_detection: 是否启用高光检测
                subtitle_generation: 是否生成字幕
                output_format: 输出格式
                output_path: 输出路径
        """
        if not self.initialized:
            raise Exception("FunClip未初始化")
        
        try:
            import moviepy.editor as mp
            import os
            import tempfile
            
            # 提取参数
            highlight_detection = kwargs.get("highlight_detection", True)
            subtitle_generation = kwargs.get("subtitle_generation", True)
            output_format = kwargs.get("output_format", "mp4")
            output_path = kwargs.get("output_path", None)
            
            # 如果没有指定输出路径，生成默认路径
            if not output_path:
                base_name = os.path.basename(video_path)
                name_without_ext = os.path.splitext(base_name)[0]
                output_path = os.path.join("短剧AI剪辑输出", f"{name_without_ext}_edited.{output_format}")
            
            # 确保输出目录存在
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            # 加载视频
            video = mp.VideoFileClip(video_path)
            
            # 提取音频
            audio_path = tempfile.mktemp(suffix=".wav")
            video.audio.write_audiofile(audio_path)
            
            # 语音识别
            result = self.whisper_model.transcribe(audio_path)
            
            # 分析文本，提取高光片段
            highlights = []
            if highlight_detection:
                highlights = self._detect_highlights(result["segments"])
            
            # 生成字幕
            subtitles = []
            if subtitle_generation:
                subtitles = self._generate_subtitles(result["segments"])
            
            # 剪辑视频
            edited_video = self._edit_video(video, highlights)
            
            # 添加字幕
            if subtitle_generation:
                edited_video = self._add_subtitles(edited_video, subtitles)
            
            # 导出视频
            edited_video.write_videofile(output_path, codec="libx264", audio_codec="aac")
            
            # 清理临时文件
            os.unlink(audio_path)
            
            return {
                "success": True,
                "output_path": output_path,
                "highlights": highlights,
                "subtitles": subtitles
            }
        except Exception as e:
            print(f"自动剪辑失败: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def _detect_highlights(self, segments):
        """检测高光片段
        
        Args:
            segments: Whisper识别的语音片段
        
        Returns:
            高光片段列表，每个片段包含start和end时间
        """
        highlights = []
        
        # 简单的高光检测逻辑：长度适中且包含关键词的片段
        keywords = ["精彩", "重要", "注意", "关键", "高潮", "感动", "惊喜", "震撼", "厉害", "牛"]
        
        for segment in segments:
            text = segment["text"]
            start = segment["start"]
            end = segment["end"]
            
            # 检查片段长度（2-10秒）
            duration = end - start
            if duration < 2 or duration > 10:
                continue
            
            # 检查是否包含关键词
            if any(keyword in text for keyword in keywords):
                highlights.append({
                    "start": start,
                    "end": end,
                    "text": text
                })
        
        # 如果没有检测到高光片段，返回前3个片段
        if not highlights and segments:
            for segment in segments[:3]:
                highlights.append({
                    "start": segment["start"],
                    "end": segment["end"],
                    "text": segment["text"]
                })
        
        return highlights
    
    def _generate_subtitles(self, segments):
        """生成字幕
        
        Args:
            segments: Whisper识别的语音片段
        
        Returns:
            字幕列表，每个字幕包含start、end时间和text
        """
        subtitles = []
        
        for segment in segments:
            subtitles.append({
                "start": segment["start"],
                "end": segment["end"],
                "text": segment["text"]
            })
        
        return subtitles
    
    def _edit_video(self, video, highlights):
        """剪辑视频
        
        Args:
            video: 原始视频
            highlights: 高光片段列表
        
        Returns:
            剪辑后的视频
        """
        import moviepy.editor as mp
        
        if not highlights:
            return video
        
        # 提取高光片段
        clips = []
        for highlight in highlights:
            start = highlight["start"]
            end = highlight["end"]
            clip = video.subclip(start, end)
            clips.append(clip)
        
        # 合并片段
        if clips:
            edited_video = mp.concatenate_videoclips(clips)
            return edited_video
        else:
            return video
    
    def _add_subtitles(self, video, subtitles):
        """添加字幕
        
        Args:
            video: 视频
            subtitles: 字幕列表
        
        Returns:
            添加了字幕的视频
        """
        import moviepy.editor as mp
        from moviepy.video.tools.subtitles import SubtitlesClip
        from moviepy.video.VideoClip import TextClip
        
        if not subtitles:
            return video
        
        # 创建字幕函数
        def make_text_clip(txt, duration):
            return TextClip(txt, fontsize=24, color='white', bg_color='black', 
                           font='Microsoft-YaHei', size=(video.w - 40, None), 
                           method='caption').set_duration(duration)
        
        # 准备字幕数据
        subtitle_tuples = []
        for subtitle in subtitles:
            start = subtitle["start"]
            end = subtitle["end"]
            text = subtitle["text"]
            subtitle_tuples.append(((start, end), text))
        
        # 创建字幕剪辑
        subtitles_clip = SubtitlesClip(subtitle_tuples, make_text_clip)
        
        # 叠加字幕
        final_video = mp.CompositeVideoClip([video, subtitles_clip.set_position(('center', 'bottom'))])
        
        return final_video

# 创建FunClip实例
funclip_integration = FunClipIntegration()