"""
视频处理模块 (VideoProcessor)
============================
提供视频处理核心功能：剪辑、合并、转码、滤镜等
"""

import os
import subprocess
import threading
import gc
import tempfile
import shutil
from typing import Dict, List, Any, Optional, Callable, Tuple
from dataclasses import dataclass
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


@dataclass
class ExportSettings:
    """导出设置"""
    resolution: str = "1920x1080"
    bitrate: str = "5M"
    encoder: str = "libx264"
    format: str = "mp4"
    fps: int = 30
    audio_codec: str = "aac"
    audio_bitrate: str = "192k"


@dataclass
class VideoInfo:
    """视频信息"""
    path: str
    duration: float
    width: int
    height: int
    fps: float
    codec: str
    bitrate: int
    size: int


def detect_gpu_encoder(ffmpeg_path: str = "ffmpeg") -> str:
    """检测 GPU 编码器"""
    encoders = [
        ("h264_nvenc", "NVIDIA NVENC"),
        ("hevc_nvenc", "NVIDIA NVENC HEVC"),
        ("h264_qsv", "Intel Quick Sync"),
        ("hevc_qsv", "Intel Quick Sync HEVC"),
        ("h264_videotoolbox", "Apple VideoToolbox"),
        ("hevc_videotoolbox", "Apple VideoToolbox HEVC"),
    ]
    
    try:
        result = subprocess.run(
            [ffmpeg_path, "-encoders"],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
        
        for encoder, name in encoders:
            if encoder in result.stdout:
                logger.info(f"检测到 GPU 编码器: {name} ({encoder})")
                return encoder
    except Exception as e:
        logger.warning(f"检测 GPU 编码器失败: {e}")
    
    return "libx264"


def get_video_info(video_path: str, ffprobe_path: str = "ffprobe") -> Optional[VideoInfo]:
    """获取视频信息"""
    try:
        cmd = [
            ffprobe_path,
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            video_path
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            creation_flags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
        
        if result.returncode != 0:
            return None
        
        import json
        data = json.loads(result.stdout)
        
        video_stream = None
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                video_stream = stream
                break
        
        if not video_stream:
            return None
        
        format_info = data.get("format", {})
        
        fps_str = video_stream.get("r_frame_rate", "30/1")
        if "/" in fps_str:
            num, den = fps_str.split("/")
            fps = float(num) / float(den) if float(den) != 0 else 30
        else:
            fps = float(fps_str)
        
        return VideoInfo(
            path=video_path,
            duration=float(format_info.get("duration", 0)),
            width=int(video_stream.get("width", 0)),
            height=int(video_stream.get("height", 0)),
            fps=fps,
            codec=video_stream.get("codec_name", "unknown"),
            bitrate=int(format_info.get("bit_rate", 0)),
            size=int(format_info.get("size", 0))
        )
    except Exception as e:
        logger.error(f"获取视频信息失败: {e}")
        return None


def extract_audio(video_path: str, output_path: str, ffmpeg_path: str = "ffmpeg") -> bool:
    """从视频中提取音频"""
    try:
        cmd = [
            ffmpeg_path,
            "-i", video_path,
            "-vn",
            "-acodec", "pcm_s16le",
            "-ar", "44100",
            "-ac", "2",
            "-y",
            output_path
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            creation_flags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
        
        return result.returncode == 0
    except Exception as e:
        logger.error(f"提取音频失败: {e}")
        return False


def merge_videos(
    video_paths: List[str],
    output_path: str,
    ffmpeg_path: str = "ffmpeg",
    settings: Optional[ExportSettings] = None
) -> bool:
    """合并多个视频"""
    if not video_paths:
        return False
    
    settings = settings or ExportSettings()
    
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            for path in video_paths:
                f.write(f"file '{path}'\n")
            list_file = f.name
        
        cmd = [
            ffmpeg_path,
            "-f", "concat",
            "-safe", "0",
            "-i", list_file,
            "-c:v", settings.encoder,
            "-b:v", settings.bitrate,
            "-c:a", settings.audio_codec,
            "-b:a", settings.audio_bitrate,
            "-y",
            output_path
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            creation_flags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
        
        os.unlink(list_file)
        
        return result.returncode == 0
    except Exception as e:
        logger.error(f"合并视频失败: {e}")
        return False


def trim_video(
    video_path: str,
    output_path: str,
    start_time: float,
    end_time: float,
    ffmpeg_path: str = "ffmpeg",
    settings: Optional[ExportSettings] = None
) -> bool:
    """裁剪视频"""
    settings = settings or ExportSettings()
    
    try:
        cmd = [
            ffmpeg_path,
            "-i", video_path,
            "-ss", str(start_time),
            "-to", str(end_time),
            "-c:v", settings.encoder,
            "-b:v", settings.bitrate,
            "-c:a", settings.audio_codec,
            "-b:a", settings.audio_bitrate,
            "-y",
            output_path
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            creation_flags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
        
        return result.returncode == 0
    except Exception as e:
        logger.error(f"裁剪视频失败: {e}")
        return False


def add_watermark(
    video_path: str,
    watermark_path: str,
    output_path: str,
    position: str = "bottom_right",
    opacity: float = 0.8,
    ffmpeg_path: str = "ffmpeg",
    settings: Optional[ExportSettings] = None
) -> bool:
    """添加水印"""
    settings = settings or ExportSettings()
    
    positions = {
        "top_left": "10:10",
        "top_right": "W-w-10:10",
        "bottom_left": "10:H-h-10",
        "bottom_right": "W-w-10:H-h-10",
        "center": "(W-w)/2:(H-h)/2"
    }
    
    overlay_pos = positions.get(position, positions["bottom_right"])
    
    try:
        cmd = [
            ffmpeg_path,
            "-i", video_path,
            "-i", watermark_path,
            "-filter_complex",
            f"[1:v]format=rgba,colorchannelmixer=aa={opacity}[wm];[0:v][wm]overlay={overlay_pos}",
            "-c:v", settings.encoder,
            "-b:v", settings.bitrate,
            "-c:a", "copy",
            "-y",
            output_path
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            creation_flags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
        
        return result.returncode == 0
    except Exception as e:
        logger.error(f"添加水印失败: {e}")
        return False


def change_speed(
    video_path: str,
    output_path: str,
    speed: float,
    ffmpeg_path: str = "ffmpeg",
    settings: Optional[ExportSettings] = None
) -> bool:
    """改变视频速度"""
    settings = settings or ExportSettings()
    
    try:
        video_filter = f"setpts={1/speed}*PTS"
        audio_filter = f"atempo={speed}" if 0.5 <= speed <= 2.0 else f"atempo=2.0,atempo={speed/2}"
        
        cmd = [
            ffmpeg_path,
            "-i", video_path,
            "-filter_complex",
            f"[0:v]{video_filter}[v];[0:a]{audio_filter}[a]",
            "-map", "[v]",
            "-map", "[a]",
            "-c:v", settings.encoder,
            "-b:v", settings.bitrate,
            "-c:a", settings.audio_codec,
            "-b:a", settings.audio_bitrate,
            "-y",
            output_path
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            creation_flags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
        
        return result.returncode == 0
    except Exception as e:
        logger.error(f"改变视频速度失败: {e}")
        return False


def resize_video(
    video_path: str,
    output_path: str,
    width: int,
    height: int,
    ffmpeg_path: str = "ffmpeg",
    settings: Optional[ExportSettings] = None
) -> bool:
    """调整视频分辨率"""
    settings = settings or ExportSettings()
    
    try:
        cmd = [
            ffmpeg_path,
            "-i", video_path,
            "-vf", f"scale={width}:{height}",
            "-c:v", settings.encoder,
            "-b:v", settings.bitrate,
            "-c:a", "copy",
            "-y",
            output_path
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            creation_flags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
        
        return result.returncode == 0
    except Exception as e:
        logger.error(f"调整分辨率失败: {e}")
        return False


def add_background_music(
    video_path: str,
    music_path: str,
    output_path: str,
    music_volume: float = 0.3,
    video_volume: float = 1.0,
    ffmpeg_path: str = "ffmpeg",
    settings: Optional[ExportSettings] = None
) -> bool:
    """添加背景音乐"""
    settings = settings or ExportSettings()
    
    try:
        cmd = [
            ffmpeg_path,
            "-i", video_path,
            "-i", music_path,
            "-filter_complex",
            f"[0:a]volume={video_volume}[a1];[1:a]volume={music_volume},aloop=0:size=2e+09[a2];[a1][a2]amix=inputs=2:duration=first[a]",
            "-map", "0:v",
            "-map", "[a]",
            "-c:v", "copy",
            "-c:a", settings.audio_codec,
            "-b:a", settings.audio_bitrate,
            "-shortest",
            "-y",
            output_path
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            creation_flags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
        
        return result.returncode == 0
    except Exception as e:
        logger.error(f"添加背景音乐失败: {e}")
        return False


def extract_frames(
    video_path: str,
    output_dir: str,
    fps: float = 1.0,
    ffmpeg_path: str = "ffmpeg"
) -> int:
    """提取视频帧"""
    os.makedirs(output_dir, exist_ok=True)
    
    try:
        output_pattern = os.path.join(output_dir, "frame_%04d.jpg")
        
        cmd = [
            ffmpeg_path,
            "-i", video_path,
            "-vf", f"fps={fps}",
            "-q:v", "2",
            "-y",
            output_pattern
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            creation_flags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
        
        frames = [f for f in os.listdir(output_dir) if f.startswith("frame_")]
        return len(frames)
    except Exception as e:
        logger.error(f"提取视频帧失败: {e}")
        return 0


def create_video_from_images(
    image_dir: str,
    output_path: str,
    fps: int = 30,
    ffmpeg_path: str = "ffmpeg",
    settings: Optional[ExportSettings] = None
) -> bool:
    """从图片创建视频"""
    settings = settings or ExportSettings()
    
    try:
        input_pattern = os.path.join(image_dir, "%04d.jpg")
        
        cmd = [
            ffmpeg_path,
            "-framerate", str(fps),
            "-i", input_pattern,
            "-c:v", settings.encoder,
            "-b:v", settings.bitrate,
            "-pix_fmt", "yuv420p",
            "-y",
            output_path
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            creation_flags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
        
        return result.returncode == 0
    except Exception as e:
        logger.error(f"从图片创建视频失败: {e}")
        return False


class VideoProcessor:
    """视频处理器"""
    
    def __init__(self, ffmpeg_path: str = "ffmpeg", ffprobe_path: str = "ffprobe"):
        self.ffmpeg_path = ffmpeg_path
        self.ffprobe_path = ffprobe_path
        self.gpu_encoder = detect_gpu_encoder(ffmpeg_path)
    
    def get_info(self, video_path: str) -> Optional[VideoInfo]:
        """获取视频信息"""
        return get_video_info(video_path, self.ffprobe_path)
    
    def process(
        self,
        video_path: str,
        output_path: str,
        operations: List[Dict[str, Any]],
        settings: Optional[ExportSettings] = None,
        progress_callback: Optional[Callable[[int], None]] = None
    ) -> bool:
        """执行视频处理操作链"""
        settings = settings or ExportSettings()
        current_path = video_path
        temp_files = []
        
        try:
            for i, op in enumerate(operations):
                op_type = op.get("type")
                temp_output = tempfile.mktemp(suffix=".mp4")
                temp_files.append(temp_output)
                
                if op_type == "trim":
                    success = trim_video(
                        current_path, temp_output,
                        op.get("start", 0), op.get("end", 10),
                        self.ffmpeg_path, settings
                    )
                elif op_type == "speed":
                    success = change_speed(
                        current_path, temp_output,
                        op.get("speed", 1.0),
                        self.ffmpeg_path, settings
                    )
                elif op_type == "resize":
                    success = resize_video(
                        current_path, temp_output,
                        op.get("width", 1920), op.get("height", 1080),
                        self.ffmpeg_path, settings
                    )
                elif op_type == "watermark":
                    success = add_watermark(
                        current_path, op.get("watermark_path", ""),
                        temp_output, op.get("position", "bottom_right"),
                        op.get("opacity", 0.8),
                        self.ffmpeg_path, settings
                    )
                else:
                    continue
                
                if not success:
                    return False
                
                current_path = temp_output
                
                if progress_callback:
                    progress_callback(int((i + 1) / len(operations) * 100))
            
            shutil.copy(current_path, output_path)
            return True
            
        finally:
            for temp_file in temp_files:
                if os.path.exists(temp_file):
                    os.unlink(temp_file)
