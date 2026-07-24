"""
示例积木集合
===========
包含：自动剪辑、字幕生成、去重优化等积木
"""

from typing import Dict, Any, List
import os
import subprocess
import random

from .base_block import (
    LegoBlock, BlockInput, BlockOutput, BlockMeta, 
    BlockResult, InputType, OutputType
)


class AutoClipBlock(LegoBlock):
    """
    自动剪辑积木
    功能：自动识别精彩片段并剪辑
    """
    
    def info(self) -> BlockMeta:
        return BlockMeta(
            name="自动剪辑",
            version="1.0.0",
            author="AI短剧编辑器",
            description="自动识别视频中的精彩片段并进行剪辑",
            category="视频处理",
            tags=["剪辑", "自动化", "AI"],
            icon="✂️"
        )
    
    def inputs(self) -> List[BlockInput]:
        return [
            BlockInput(
                name="video_path",
                type=InputType.FILE,
                description="输入视频文件路径",
                required=True
            ),
            BlockInput(
                name="mode",
                type=InputType.CONFIG,
                description="剪辑模式",
                required=False,
                default="30s爆款引流",
                options=["30s爆款引流", "90s剧情解说", "8分钟挂车长视频"]
            ),
            BlockInput(
                name="output_dir",
                type=InputType.DIRECTORY,
                description="输出目录",
                required=False,
                default="输出"
            ),
            BlockInput(
                name="gpu_encoder",
                type=InputType.CONFIG,
                description="GPU编码器",
                required=False,
                default="libx264",
                options=["libx264", "h264_nvenc", "h264_amf"]
            )
        ]
    
    def outputs(self) -> List[BlockOutput]:
        return [
            BlockOutput(
                name="output_videos",
                type=OutputType.FILE,
                description="输出的剪辑视频列表"
            ),
            BlockOutput(
                name="clip_count",
                type=OutputType.JSON,
                description="剪辑片段数量"
            ),
            BlockOutput(
                name="highlights",
                type=OutputType.JSON,
                description="识别到的精彩片段信息"
            )
        ]
    
    def process(self, inputs: Dict[str, Any]) -> BlockResult:
        video_path = inputs.get("video_path")
        mode = inputs.get("mode", "30s爆款引流")
        output_dir = inputs.get("output_dir", "输出")
        gpu_encoder = inputs.get("gpu_encoder", "libx264")
        
        if not os.path.exists(video_path):
            return BlockResult(success=False, error=f"视频文件不存在: {video_path}")
        
        self._report_progress(0.1, "分析视频中...")
        
        try:
            highlights = self._detect_highlights(video_path, mode)
            
            self._report_progress(0.3, f"发现 {len(highlights)} 个精彩片段")
            
            os.makedirs(output_dir, exist_ok=True)
            output_videos = []
            
            for i, (start, end) in enumerate(highlights):
                self._report_progress(
                    0.3 + 0.6 * (i + 1) / len(highlights),
                    f"剪辑片段 {i + 1}/{len(highlights)}"
                )
                
                output_path = os.path.join(output_dir, f"clip_{i+1}.mp4")
                success = self._clip_video(
                    video_path, output_path, start, end - start, gpu_encoder
                )
                if success:
                    output_videos.append(output_path)
            
            self._report_progress(1.0, "剪辑完成")
            
            return BlockResult(
                success=True,
                outputs={
                    "output_videos": output_videos,
                    "clip_count": len(output_videos),
                    "highlights": highlights
                }
            )
            
        except Exception as e:
            return BlockResult(success=False, error=str(e))
    
    def _detect_highlights(self, video_path: str, mode: str) -> List[tuple]:
        """检测精彩片段 - 帧差法运动分析 + 固定时长回退"""
        duration = self._get_video_duration(video_path)
        if mode == "30s爆款引流":
            clip_duration = 30
        elif mode == "90s剧情解说":
            clip_duration = 90
        else:
            clip_duration = 480

        try:
            import cv2
            import numpy as np
            cap = cv2.VideoCapture(video_path)
            if cap.isOpened():
                fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
                frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                seg_len = int(fps * 2)
                scores = []
                prev = None
                for i in range(0, frame_count, seg_len):
                    cap.set(cv2.CAP_PROP_POS_FRAMES, i)
                    motion = 0
                    cnt = 0
                    for _ in range(0, seg_len, 5):
                        ret, frm = cap.read()
                        if not ret:
                            break
                        g = cv2.cvtColor(frm, cv2.COLOR_BGR2GRAY)
                        g = cv2.resize(g, (120, 68))
                        if prev is not None:
                            motion += np.mean(np.abs(g.astype(float) - prev.astype(float)))
                            cnt += 1
                        prev = g
                    if cnt > 0:
                        scores.append((i / fps, min((i + seg_len) / fps, duration), motion / cnt))
                cap.release()
                if scores:
                    scores.sort(key=lambda x: x[2], reverse=True)
                    top = scores[:max(3, int(duration / clip_duration))]
                    top.sort(key=lambda x: x[0])
                    highlights = [(max(0, s - clip_duration / 4), min(s + clip_duration, duration))
                                  for s, _, _ in top]
                    return highlights
        except Exception:
            pass

        highlights = []
        start = 0
        while start < duration:
            end = min(start + clip_duration, duration)
            if end - start >= 10:
                highlights.append((start, end))
            start = end
        return highlights
    
    def _get_video_duration(self, video_path: str) -> float:
        """获取视频时长"""
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", 
                 "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", 
                 video_path],
                capture_output=True, text=True
            )
            return float(result.stdout.strip())
        except Exception:
            pass
            return 60.0
    
    def _clip_video(self, input_path: str, output_path: str, 
                    start: float, duration: float, encoder: str) -> bool:
        """剪辑视频"""
        try:
            cmd = [
                "ffmpeg", "-y",
                "-ss", str(start),
                "-i", input_path,
                "-t", str(duration),
                "-c:v", encoder,
                "-c:a", "aac",
                output_path
            ]
            subprocess.run(cmd, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            return os.path.exists(output_path)
        except Exception:
            pass
            return False


class SubtitleGenerateBlock(LegoBlock):
    """
    字幕生成积木
    功能：自动提取视频字幕
    """
    
    def info(self) -> BlockMeta:
        return BlockMeta(
            name="字幕生成",
            version="1.0.0",
            author="AI短剧编辑器",
            description="使用AI自动识别视频中的语音并生成字幕",
            category="字幕处理",
            tags=["字幕", "AI", "语音识别"],
            icon="📝"
        )
    
    def inputs(self) -> List[BlockInput]:
        return [
            BlockInput(
                name="video_path",
                type=InputType.FILE,
                description="输入视频文件路径",
                required=True
            ),
            BlockInput(
                name="language",
                type=InputType.CONFIG,
                description="语言",
                required=False,
                default="zh",
                options=["zh", "en", "ja", "ko"]
            ),
            BlockInput(
                name="output_format",
                type=InputType.CONFIG,
                description="输出格式",
                required=False,
                default="srt",
                options=["srt", "vtt", "ass", "txt"]
            )
        ]
    
    def outputs(self) -> List[BlockOutput]:
        return [
            BlockOutput(
                name="subtitle_path",
                type=OutputType.FILE,
                description="字幕文件路径"
            ),
            BlockOutput(
                name="segments",
                type=OutputType.JSON,
                description="字幕片段列表"
            ),
            BlockOutput(
                name="text",
                type=OutputType.TEXT,
                description="完整文本"
            )
        ]
    
    def process(self, inputs: Dict[str, Any]) -> BlockResult:
        video_path = inputs.get("video_path")
        language = inputs.get("language", "zh")
        output_format = inputs.get("output_format", "srt")
        
        if not os.path.exists(video_path):
            return BlockResult(success=False, error=f"视频文件不存在: {video_path}")
        
        self._report_progress(0.1, "加载语音识别模型...")
        
        try:
            self._report_progress(0.3, "识别语音中...")
            
            segments = self._transcribe(video_path, language)
            
            self._report_progress(0.7, "生成字幕文件...")
            
            base_name = os.path.splitext(video_path)[0]
            subtitle_path = f"{base_name}.{output_format}"
            
            self._save_subtitle(segments, subtitle_path, output_format)
            
            full_text = " ".join([seg["text"] for seg in segments])
            
            self._report_progress(1.0, "字幕生成完成")
            
            return BlockResult(
                success=True,
                outputs={
                    "subtitle_path": subtitle_path,
                    "segments": segments,
                    "text": full_text
                }
            )
            
        except Exception as e:
            return BlockResult(success=False, error=str(e))
    
    def _transcribe(self, video_path: str, language: str) -> List[Dict]:
        """语音识别 - 委托给统一的 whisper_asr 共享模块"""
        try:
            from app.core.ai.whisper_asr import transcribe
        except ImportError:
            try:
                from core.ai.whisper_asr import transcribe
            except ImportError:
                # 回退示例数据
                return [
                    {"start": 0.0, "end": 5.0, "text": "[示例字幕] 请安装 faster-whisper"},
                    {"start": 5.0, "end": 10.0, "text": "[示例字幕] 以启用真实语音识别"}
                ]
        result = transcribe(video_path, model_size="small", language=language)
        return result if result else [{"start": 0.0, "end": 3.0, "text": "[识别结果为空]"}]
    
    def _save_subtitle(self, segments: List[Dict], path: str, fmt: str):
        """保存字幕文件"""
        with open(path, "w", encoding="utf-8") as f:
            if fmt == "srt":
                for i, seg in enumerate(segments, 1):
                    f.write(f"{i}\n")
                    f.write(f"{self._format_time(seg['start'])} --> {self._format_time(seg['end'])}\n")
                    f.write(f"{seg['text']}\n\n")
            elif fmt == "txt":
                for seg in segments:
                    f.write(f"{seg['text']}\n")
            else:
                for seg in segments:
                    f.write(f"{seg['start']}\t{seg['end']}\t{seg['text']}\n")
    
    def _format_time(self, seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds % 1) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


class DeduplicateBlock(LegoBlock):
    """
    去重优化积木
    功能：随机调整视频参数减少重复检测
    """
    
    def info(self) -> BlockMeta:
        return BlockMeta(
            name="去重优化",
            version="1.0.0",
            author="AI短剧编辑器",
            description="随机调整视频偏移和色调，减少平台重复检测",
            category="视频处理",
            tags=["去重", "优化", "发布"],
            icon="🔄"
        )
    
    def inputs(self) -> List[BlockInput]:
        return [
            BlockInput(
                name="video_path",
                type=InputType.FILE,
                description="输入视频文件路径",
                required=True
            ),
            BlockInput(
                name="output_path",
                type=InputType.FILE,
                description="输出视频文件路径",
                required=False
            ),
            BlockInput(
                name="offset_range",
                type=InputType.CONFIG,
                description="偏移范围",
                required=False,
                default=6,
                min_value=0,
                max_value=20
            ),
            BlockInput(
                name="hue_range",
                type=InputType.CONFIG,
                description="色调调整范围",
                required=False,
                default=4,
                min_value=0,
                max_value=10
            )
        ]
    
    def outputs(self) -> List[BlockOutput]:
        return [
            BlockOutput(
                name="output_path",
                type=OutputType.FILE,
                description="输出视频路径"
            ),
            BlockOutput(
                name="offset_x",
                type=OutputType.JSON,
                description="X轴偏移值"
            ),
            BlockOutput(
                name="offset_y",
                type=OutputType.JSON,
                description="Y轴偏移值"
            ),
            BlockOutput(
                name="hue_shift",
                type=OutputType.JSON,
                description="色调偏移值"
            )
        ]
    
    def process(self, inputs: Dict[str, Any]) -> BlockResult:
        video_path = inputs.get("video_path")
        output_path = inputs.get("output_path")
        offset_range = inputs.get("offset_range", 6)
        hue_range = inputs.get("hue_range", 4)
        
        if not os.path.exists(video_path):
            return BlockResult(success=False, error=f"视频文件不存在: {video_path}")
        
        if not output_path:
            base, ext = os.path.splitext(video_path)
            output_path = f"{base}_dedup{ext}"
        
        self._report_progress(0.1, "计算随机参数...")
        
        offset_x = random.randint(-offset_range, offset_range)
        offset_y = random.randint(-offset_range, offset_range)
        hue_shift = random.randint(-hue_range, hue_range)
        
        self._report_progress(0.3, f"应用参数: offset=({offset_x}, {offset_y}), hue={hue_shift}")
        
        try:
            self._report_progress(0.5, "处理视频中...")
            
            success = self._apply_dedup(
                video_path, output_path, offset_x, offset_y, hue_shift
            )
            
            self._report_progress(1.0, "去重处理完成")
            
            if success:
                return BlockResult(
                    success=True,
                    outputs={
                        "output_path": output_path,
                        "offset_x": offset_x,
                        "offset_y": offset_y,
                        "hue_shift": hue_shift
                    }
                )
            else:
                return BlockResult(success=False, error="视频处理失败")
                
        except Exception as e:
            return BlockResult(success=False, error=str(e))
    
    def _apply_dedup(self, input_path: str, output_path: str,
                     offset_x: int, offset_y: int, hue: int) -> bool:
        """应用去重滤镜"""
        try:
            filter_str = f"crop=iw-{abs(offset_x)*2}:ih-{abs(offset_y)*2},pad=iw:ih:{offset_x}:{offset_y},hue=h={hue/100}"
            
            cmd = [
                "ffmpeg", "-y",
                "-i", input_path,
                "-vf", filter_str,
                "-c:a", "copy",
                output_path
            ]
            
            subprocess.run(cmd, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            return os.path.exists(output_path)
        except Exception:
            pass
            return False


class VideoInfoBlock(LegoBlock):
    """
    视频信息积木
    功能：读取视频基本信息
    """
    
    def info(self) -> BlockMeta:
        return BlockMeta(
            name="视频信息",
            version="1.0.0",
            author="AI短剧编辑器",
            description="读取视频的时长、分辨率、编码等基本信息",
            category="视频处理",
            tags=["信息", "分析"],
            icon="ℹ️"
        )
    
    def inputs(self) -> List[BlockInput]:
        return [
            BlockInput(
                name="video_path",
                type=InputType.FILE,
                description="视频文件路径",
                required=True
            )
        ]
    
    def outputs(self) -> List[BlockOutput]:
        return [
            BlockOutput(name="duration", type=OutputType.JSON, description="时长（秒）"),
            BlockOutput(name="width", type=OutputType.JSON, description="宽度"),
            BlockOutput(name="height", type=OutputType.JSON, description="高度"),
            BlockOutput(name="fps", type=OutputType.JSON, description="帧率"),
            BlockOutput(name="codec", type=OutputType.JSON, description="编码格式"),
            BlockOutput(name="file_size", type=OutputType.JSON, description="文件大小（MB）")
        ]
    
    def process(self, inputs: Dict[str, Any]) -> BlockResult:
        video_path = inputs.get("video_path")
        
        if not os.path.exists(video_path):
            return BlockResult(success=False, error=f"视频文件不存在: {video_path}")
        
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json",
                 "-show_format", "-show_streams", video_path],
                capture_output=True, text=True
            )
            
            import json
            data = json.loads(result.stdout)
            
            video_stream = None
            for stream in data.get("streams", []):
                if stream.get("codec_type") == "video":
                    video_stream = stream
                    break
            
            if not video_stream:
                return BlockResult(success=False, error="未找到视频流")
            
            duration = float(data.get("format", {}).get("duration", 0))
            width = int(video_stream.get("width", 0))
            height = int(video_stream.get("height", 0))
            
            fps_str = video_stream.get("r_frame_rate", "30/1")
            if "/" in fps_str:
                num, den = map(int, fps_str.split("/"))
                fps = num / den if den > 0 else 30
            else:
                fps = float(fps_str)
            
            codec = video_stream.get("codec_name", "unknown")
            file_size = os.path.getsize(video_path) / (1024 * 1024)
            
            return BlockResult(
                success=True,
                outputs={
                    "duration": duration,
                    "width": width,
                    "height": height,
                    "fps": fps,
                    "codec": codec,
                    "file_size": round(file_size, 2)
                }
            )
            
        except Exception as e:
            return BlockResult(success=False, error=str(e))


class CopyGenerateBlock(LegoBlock):
    """
    文案生成积木
    功能：AI生成视频文案
    """
    
    def info(self) -> BlockMeta:
        return BlockMeta(
            name="文案生成",
            version="1.0.0",
            author="AI短剧编辑器",
            description="使用AI生成视频标题、描述、标签等文案",
            category="AI功能",
            tags=["文案", "AI", "标题"],
            icon="✍️"
        )
    
    def inputs(self) -> List[BlockInput]:
        return [
            BlockInput(
                name="content",
                type=InputType.TEXT,
                description="视频内容描述",
                required=True
            ),
            BlockInput(
                name="platform",
                type=InputType.CONFIG,
                description="目标平台",
                required=False,
                default="抖音",
                options=["抖音", "快手", "视频号", "小红书"]
            ),
            BlockInput(
                name="style",
                type=InputType.CONFIG,
                description="文案风格",
                required=False,
                default="爆款",
                options=["爆款", "剧情", "解说", "情感"]
            )
        ]
    
    def outputs(self) -> List[BlockOutput]:
        return [
            BlockOutput(name="title", type=OutputType.TEXT, description="标题"),
            BlockOutput(name="description", type=OutputType.TEXT, description="描述"),
            BlockOutput(name="tags", type=OutputType.JSON, description="标签列表"),
            BlockOutput(name="hashtags", type=OutputType.TEXT, description="话题标签")
        ]
    
    def process(self, inputs: Dict[str, Any]) -> BlockResult:
        content = inputs.get("content", "")
        platform = inputs.get("platform", "抖音")
        style = inputs.get("style", "爆款")
        
        self._report_progress(0.3, "分析内容...")
        
        try:
            self._report_progress(0.5, "生成文案...")
            
            title = self._generate_title(content, platform, style)
            description = self._generate_description(content, platform, style)
            tags = self._generate_tags(content, platform)
            hashtags = " ".join([f"#{tag}" for tag in tags])
            
            self._report_progress(1.0, "文案生成完成")
            
            return BlockResult(
                success=True,
                outputs={
                    "title": title,
                    "description": description,
                    "tags": tags,
                    "hashtags": hashtags
                }
            )
            
        except Exception as e:
            return BlockResult(success=False, error=str(e))
    
    def _generate_title(self, content: str, platform: str, style: str) -> str:
        """智能标题生成 - 模板匹配"""
        templates = {
            "爆款": ["🔥{}，看完直呼过瘾！", "太绝了！{}，必看！", "震惊！{}"],
            "剧情": ["【剧情】{}", "深度解析：{}", "精彩剧情：{}"],
            "解说": ["【解说】{}", "一文看懂：{}", "深度解读：{}"],
            "情感": ["感动！{}", "泪目...{}", "破防了！{}"]
        }
        template = random.choice(templates.get(style, templates["爆款"]))
        return template.format(content[:20] if len(content) > 20 else content)
    
    def _generate_description(self, content: str, platform: str, style: str) -> str:
        """生成描述"""
        return f"这是一段关于{content[:30]}的精彩内容，快来看看吧！"
    
    def _generate_tags(self, content: str, platform: str) -> List[str]:
        """生成标签"""
        base_tags = ["短剧", "热门", "推荐", "追剧"]
        return base_tags[:3]


BUILTIN_BLOCKS = [
    AutoClipBlock,
    SubtitleGenerateBlock,
    DeduplicateBlock,
    VideoInfoBlock,
    CopyGenerateBlock
]
