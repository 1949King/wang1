"""
专业级视频剪辑引擎 - TOP 0级核心模块
=====================================
基于FFmpeg的专业级视频处理引擎
特性：无损剪辑、硬解码加速、批量渲染、智能导出

这是TOP 0级软件的核心竞争力，决定了剪辑质量和导出速度
"""

import os
import subprocess
import json
import threading
import queue
import time
from typing import Dict, List, Optional, Tuple, Callable, Any
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import tempfile
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np


class VideoCodec(Enum):
    """视频编码器"""
    H264 = "libx264"
    H264_NVENC = "h264_nvenc"  # NVIDIA硬件加速
    H264_QSV = "h264_qsv"      # Intel QuickSync
    H265 = "libx265"
    H265_NVENC = "hevc_nvenc"  # NVIDIA HEVC
    H265_QSV = "hevc_qsv"      # Intel HEVC
    VP9 = "libvpx-vp9"
    AV1 = "libaom-av1"


class AudioCodec(Enum):
    """音频编码器"""
    AAC = "aac"
    MP3 = "libmp3lame"
    OPUS = "libopus"
    FLAC = "flac"


class HardwareAccel(Enum):
    """硬件加速类型"""
    NONE = "none"
    NVIDIA = "cuda"
    INTEL = "qsv"
    AMD = "amf"
    APPLE = "videotoolbox"


@dataclass
class VideoInfo:
    """视频信息"""
    path: str
    duration: float
    width: int
    height: int
    fps: float
    bitrate: int
    codec: str
    audio_codec: str
    audio_bitrate: int
    has_audio: bool


@dataclass
class ExportSettings:
    """导出设置"""
    resolution: Tuple[int, int] = (1920, 1080)
    fps: float = 30.0
    video_codec: VideoCodec = VideoCodec.H264
    video_bitrate: str = "5M"
    audio_codec: AudioCodec = AudioCodec.AAC
    audio_bitrate: str = "128k"
    hardware_accel: HardwareAccel = HardwareAccel.NONE
    pix_fmt: str = "yuv420p"
    preset: str = "medium"  # ultrafast, superfast, veryfast, faster, fast, medium, slow, slower, veryslow
    crf: int = 23  # 0-51, 越低质量越好
    format: str = "mp4"
    extra_args: List[str] = field(default_factory=list)


@dataclass
class CutSegment:
    """剪辑片段"""
    start_time: float
    end_time: float
    video_path: str
    audio_fade_in: float = 0.0
    audio_fade_out: float = 0.0
    video_fade_in: float = 0.0
    video_fade_out: float = 0.0


@dataclass
class VideoTask:
    """视频处理任务"""
    task_id: str
    input_path: str
    output_path: str
    operation: str  # cut, merge, transcode, etc.
    params: Dict[str, Any]
    priority: int = 0
    callback: Optional[Callable] = None


@dataclass
class TaskResult:
    """任务结果"""
    task_id: str
    success: bool
    output_path: Optional[str]
    error_message: Optional[str]
    processing_time: float
    output_info: Optional[VideoInfo]


class FFmpegUtils:
    """FFmpeg工具类"""
    
    @staticmethod
    def find_ffmpeg():
        """查找FFmpeg可执行文件"""
        # 优先查找项目中的本地FFmpeg
        # 获取当前文件的绝对路径
        current_file = os.path.abspath(__file__)
        # 向上走4级目录到达项目根目录
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(current_file))))
        project_ffmpeg_path = os.path.join(base_dir, 'thirdparty', 'ffmpeg', 'bin', 'ffmpeg.exe')
        print(f"尝试使用本地FFmpeg: {project_ffmpeg_path}")
        if os.path.exists(project_ffmpeg_path):
            print(f"✓ 找到本地FFmpeg: {project_ffmpeg_path}")
            return project_ffmpeg_path
        
        # 常见路径
        possible_paths = [
            "ffmpeg",
            "ffmpeg.exe",
            r"C:\ffmpeg\bin\ffmpeg.exe",
            r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
            r"D:\ffmpeg\bin\ffmpeg.exe",
            "/usr/bin/ffmpeg",
            "/usr/local/bin/ffmpeg",
        ]
        
        for path in possible_paths:
            if shutil.which(path):
                return path
        
        raise RuntimeError("未找到FFmpeg，请安装FFmpeg并添加到系统PATH")
    
    @staticmethod
    def run_command(cmd: List[str], 
                   progress_callback: Optional[Callable] = None,
                   duration: float = 0) -> Tuple[bool, str]:
        """
        运行FFmpeg命令
        
        Args:
            cmd: 命令列表
            progress_callback: 进度回调函数(percentage)
            duration: 视频总时长（用于计算进度）
            
        Returns:
            (success, error_message)
        """
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                encoding='utf-8',
                errors='ignore'
            )
            
            stderr_output = []
            
            # 实时读取输出
            while True:
                output = process.stderr.readline()
                if output == '' and process.poll() is not None:
                    break
                    
                if output:
                    stderr_output.append(output)
                    
                    # 解析进度
                    if progress_callback and duration > 0:
                        time_match = __import__('re').search(r'time=(\d+):(\d+):(\d+\.\d+)', output)
                        if time_match:
                            hours = int(time_match.group(1))
                            minutes = int(time_match.group(2))
                            seconds = float(time_match.group(3))
                            current_time = hours * 3600 + minutes * 60 + seconds
                            progress = min(100, (current_time / duration) * 100)
                            progress_callback(progress)
            
            return_code = process.poll()
            
            if return_code != 0:
                error_msg = ''.join(stderr_output[-10:])  # 最后10行错误信息
                return False, f"FFmpeg错误 (代码 {return_code}): {error_msg}"
            
            return True, ""
            
        except Exception as e:
            return False, str(e)
    
    @staticmethod
    def get_video_info(video_path: str) -> Optional[VideoInfo]:
        """获取视频信息"""
        try:
            cmd = [
                FFmpegUtils.find_ffmpeg(),
                "-i", video_path,
                "-print_format", "json",
                "-show_streams",
                "-v", "quiet"
            ]
            
            # 使用本地ffprobe获取信息
            ffmpeg_path = FFmpegUtils.find_ffmpeg()
            ffprobe_path = os.path.join(os.path.dirname(ffmpeg_path), 'ffprobe.exe')
            if not os.path.exists(ffprobe_path):
                ffprobe_path = "ffprobe" if shutil.which("ffprobe") else ffmpeg_path
            
            ffprobe_cmd = [
                ffprobe_path,
                "-i", video_path,
                "-print_format", "json",
                "-show_streams",
                "-v", "quiet"
            ]
            
            # 如果ffprobe不可用，使用ffmpeg的替代方案
            if not shutil.which("ffprobe"):
                result = subprocess.run(
                    [FFmpegUtils.find_ffmpeg(), "-i", video_path],
                    capture_output=True,
                    text=True
                )
                
                # 解析ffmpeg输出
                output = result.stderr
                
                # 提取基本信息
                duration_match = __import__('re').search(r'Duration: (\d+):(\d+):(\d+\.\d+)', output)
                duration = 0
                if duration_match:
                    hours = int(duration_match.group(1))
                    minutes = int(duration_match.group(2))
                    seconds = float(duration_match.group(3))
                    duration = hours * 3600 + minutes * 60 + seconds
                
                video_match = __import__('re').search(r'Stream.*Video:.*?(\d+)x(\d+)', output)
                width = int(video_match.group(1)) if video_match else 1920
                height = int(video_match.group(2)) if video_match else 1080
                
                fps_match = __import__('re').search(r'(\d+(?:\.\d+)?) fps', output)
                fps = float(fps_match.group(1)) if fps_match else 30.0
                
                bitrate_match = __import__('re').search(r'bitrate: (\d+) kb/s', output)
                bitrate = int(bitrate_match.group(1)) * 1000 if bitrate_match else 5000000
                
                return VideoInfo(
                    path=video_path,
                    duration=duration,
                    width=width,
                    height=height,
                    fps=fps,
                    bitrate=bitrate,
                    codec="h264",
                    audio_codec="aac",
                    audio_bitrate=128000,
                    has_audio="Audio:" in output
                )
            
            # 使用ffprobe
            result = subprocess.run(
                ffprobe_cmd,
                capture_output=True,
                text=True
            )
            
            data = json.loads(result.stdout)
            
            # 解析视频流
            video_stream = None
            audio_stream = None
            
            for stream in data.get('streams', []):
                if stream['codec_type'] == 'video':
                    video_stream = stream
                elif stream['codec_type'] == 'audio':
                    audio_stream = stream
            
            if not video_stream:
                return None
            
            # 提取信息
            duration = float(video_stream.get('duration', 0))
            if duration == 0 and 'format' in data:
                duration = float(data['format'].get('duration', 0))
            
            width = int(video_stream.get('width', 1920))
            height = int(video_stream.get('height', 1080))
            
            fps_str = video_stream.get('r_frame_rate', '30/1')
            if '/' in fps_str:
                num, den = fps_str.split('/')
                fps = float(num) / float(den)
            else:
                fps = float(fps_str)
            
            bitrate = int(video_stream.get('bit_rate', 5000000))
            
            return VideoInfo(
                path=video_path,
                duration=duration,
                width=width,
                height=height,
                fps=fps,
                bitrate=bitrate,
                codec=video_stream.get('codec_name', 'h264'),
                audio_codec=audio_stream.get('codec_name', 'aac') if audio_stream else '',
                audio_bitrate=int(audio_stream.get('bit_rate', 128000)) if audio_stream else 0,
                has_audio=audio_stream is not None
            )
            
        except Exception as e:
            print(f"获取视频信息失败: {e}")
            return None


class ProfessionalVideoEngine:
    """
    专业级视频剪辑引擎
    
    特性：
    - 无损剪辑（不重新编码）
    - 硬解码加速（NVIDIA/Intel）
    - 批量任务处理
    - 智能导出（多平台适配）
    """
    
    def __init__(self, max_workers: int = 4):
        """
        初始化引擎
        
        Args:
            max_workers: 最大并行工作线程数
        """
        self.ffmpeg_path = FFmpegUtils.find_ffmpeg()
        self.max_workers = max_workers
        self.task_queue = queue.PriorityQueue()
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.active_tasks = {}
        self.task_history = []
        
        # 检测硬件加速支持
        self.hardware_support = self._detect_hardware_support()
        
        print(f"🎬 ProfessionalVideoEngine 初始化完成")
        print(f"   - FFmpeg: {self.ffmpeg_path}")
        print(f"   - 最大工作线程: {max_workers}")
        print(f"   - 硬件加速: {self.hardware_support}")
    
    def _detect_hardware_support(self) -> Dict[str, bool]:
        """检测硬件加速支持"""
        support = {
            "nvidia": False,
            "intel": False,
            "amd": False
        }
        
        try:
            # 检查NVIDIA
            result = subprocess.run(
                [self.ffmpeg_path, "-encoders"],
                capture_output=True,
                text=True
            )
            output = result.stdout
            
            if "h264_nvenc" in output:
                support["nvidia"] = True
            if "h264_qsv" in output:
                support["intel"] = True
            if "h264_amf" in output:
                support["amd"] = True
                
        except Exception as e:
            print(f"检测硬件加速失败: {e}")
        
        return support
    
    def get_optimal_settings(self, target_platform: str = "抖音") -> ExportSettings:
        """
        获取最优导出设置
        
        Args:
            target_platform: 目标平台
            
        Returns:
            ExportSettings: 最优设置
        """
        # 平台预设
        presets = {
            "抖音": ExportSettings(
                resolution=(1080, 1920),
                fps=30.0,
                video_codec=VideoCodec.H264_NVENC if self.hardware_support["nvidia"] else VideoCodec.H264,
                video_bitrate="4M",
                preset="fast",
                crf=23
            ),
            "快手": ExportSettings(
                resolution=(1080, 1920),
                fps=30.0,
                video_codec=VideoCodec.H264_NVENC if self.hardware_support["nvidia"] else VideoCodec.H264,
                video_bitrate="5M",
                preset="medium",
                crf=21
            ),
            "小红书": ExportSettings(
                resolution=(1080, 1440),
                fps=30.0,
                video_codec=VideoCodec.H264_NVENC if self.hardware_support["nvidia"] else VideoCodec.H264,
                video_bitrate="6M",
                preset="slow",
                crf=18
            ),
            "B站": ExportSettings(
                resolution=(1920, 1080),
                fps=60.0,
                video_codec=VideoCodec.H264_NVENC if self.hardware_support["nvidia"] else VideoCodec.H264,
                video_bitrate="8M",
                preset="slow",
                crf=18
            )
        }
        
        return presets.get(target_platform, presets["抖音"])
    
    def cut_lossless(self, 
                     video_path: str, 
                     start_time: float, 
                     end_time: float,
                     output_path: Optional[str] = None,
                     progress_callback: Optional[Callable] = None) -> TaskResult:
        """
        无损剪辑（不重新编码，速度极快）
        
        Args:
            video_path: 输入视频路径
            start_time: 开始时间（秒）
            end_time: 结束时间（秒）
            output_path: 输出路径（可选）
            progress_callback: 进度回调
            
        Returns:
            TaskResult: 任务结果
        """
        start_process = time.time()
        task_id = f"cut_lossless_{int(start_process * 1000)}"
        
        if output_path is None:
            base, ext = os.path.splitext(video_path)
            output_path = f"{base}_cut_{start_time:.0f}_{end_time:.0f}{ext}"
        
        print(f"\n✂️ 无损剪辑: {os.path.basename(video_path)}")
        print(f"   时间段: {start_time:.2f}s - {end_time:.2f}s")
        
        try:
            # 获取视频信息
            video_info = FFmpegUtils.get_video_info(video_path)
            if not video_info:
                return TaskResult(
                    task_id=task_id,
                    success=False,
                    output_path=None,
                    error_message="无法获取视频信息",
                    processing_time=0,
                    output_info=None
                )
            
            # 构建命令（无损剪辑）
            cmd = [
                self.ffmpeg_path,
                "-ss", str(start_time),
                "-i", video_path,
                "-t", str(end_time - start_time),
                "-c", "copy",  # 不重新编码
                "-avoid_negative_ts", "make_zero",
                "-y",
                output_path
            ]
            
            # 执行命令
            success, error = FFmpegUtils.run_command(
                cmd, 
                progress_callback,
                end_time - start_time
            )
            
            processing_time = time.time() - start_process
            
            if success:
                output_info = FFmpegUtils.get_video_info(output_path)
                print(f"   ✓ 剪辑完成: {processing_time:.2f}s")
                print(f"   输出: {output_path}")
                
                return TaskResult(
                    task_id=task_id,
                    success=True,
                    output_path=output_path,
                    error_message=None,
                    processing_time=processing_time,
                    output_info=output_info
                )
            else:
                print(f"   ✗ 剪辑失败: {error}")
                return TaskResult(
                    task_id=task_id,
                    success=False,
                    output_path=None,
                    error_message=error,
                    processing_time=processing_time,
                    output_info=None
                )
                
        except Exception as e:
            processing_time = time.time() - start_process
            return TaskResult(
                task_id=task_id,
                success=False,
                output_path=None,
                error_message=str(e),
                processing_time=processing_time,
                output_info=None
            )
    
    def cut_with_reencode(self,
                          video_path: str,
                          start_time: float,
                          end_time: float,
                          output_path: Optional[str] = None,
                          settings: Optional[ExportSettings] = None,
                          progress_callback: Optional[Callable] = None) -> TaskResult:
        """
        重新编码剪辑（支持滤镜、转场等）
        
        Args:
            video_path: 输入视频路径
            start_time: 开始时间（秒）
            end_time: 结束时间（秒）
            output_path: 输出路径（可选）
            settings: 导出设置（可选）
            progress_callback: 进度回调
            
        Returns:
            TaskResult: 任务结果
        """
        start_process = time.time()
        task_id = f"cut_reencode_{int(start_process * 1000)}"
        
        if output_path is None:
            base, ext = os.path.splitext(video_path)
            output_path = f"{base}_edited_{start_time:.0f}_{end_time:.0f}.mp4"
        
        if settings is None:
            settings = self.get_optimal_settings()
        
        print(f"\n🎬 重新编码剪辑: {os.path.basename(video_path)}")
        print(f"   时间段: {start_time:.2f}s - {end_time:.2f}s")
        print(f"   编码器: {settings.video_codec.value}")
        
        try:
            # 获取视频信息
            video_info = FFmpegUtils.get_video_info(video_path)
            if not video_info:
                return TaskResult(
                    task_id=task_id,
                    success=False,
                    output_path=None,
                    error_message="无法获取视频信息",
                    processing_time=0,
                    output_info=None
                )
            
            # 构建命令
            cmd = [
                self.ffmpeg_path,
                "-ss", str(start_time),
                "-i", video_path,
                "-t", str(end_time - start_time),
            ]
            
            # 视频编码设置
            cmd.extend([
                "-c:v", settings.video_codec.value,
                "-b:v", settings.video_bitrate,
                "-r", str(settings.fps),
                "-pix_fmt", settings.pix_fmt,
                "-preset", settings.preset,
            ])
            
            # CRF设置（仅软件编码）
            if settings.video_codec in [VideoCodec.H264, VideoCodec.H265]:
                cmd.extend(["-crf", str(settings.crf)])
            
            # 分辨率设置
            cmd.extend([
                "-vf", f"scale={settings.resolution[0]}:{settings.resolution[1]}:force_original_aspect_ratio=decrease,pad={settings.resolution[0]}:{settings.resolution[1]}:(ow-iw)/2:(oh-ih)/2"
            ])
            
            # 音频编码设置
            cmd.extend([
                "-c:a", settings.audio_codec.value,
                "-b:a", settings.audio_bitrate,
            ])
            
            # 额外参数
            cmd.extend(settings.extra_args)
            
            # 输出文件
            cmd.extend(["-y", output_path])
            
            # 执行命令
            success, error = FFmpegUtils.run_command(
                cmd,
                progress_callback,
                end_time - start_time
            )
            
            processing_time = time.time() - start_process
            
            if success:
                output_info = FFmpegUtils.get_video_info(output_path)
                print(f"   ✓ 剪辑完成: {processing_time:.2f}s")
                print(f"   输出: {output_path}")
                
                return TaskResult(
                    task_id=task_id,
                    success=True,
                    output_path=output_path,
                    error_message=None,
                    processing_time=processing_time,
                    output_info=output_info
                )
            else:
                print(f"   ✗ 剪辑失败: {error}")
                return TaskResult(
                    task_id=task_id,
                    success=False,
                    output_path=None,
                    error_message=error,
                    processing_time=processing_time,
                    output_info=None
                )
                
        except Exception as e:
            processing_time = time.time() - start_process
            return TaskResult(
                task_id=task_id,
                success=False,
                output_path=None,
                error_message=str(e),
                processing_time=processing_time,
                output_info=None
            )
    
    def merge_videos(self,
                     video_paths: List[str],
                     output_path: str,
                     settings: Optional[ExportSettings] = None,
                     progress_callback: Optional[Callable] = None) -> TaskResult:
        """
        合并多个视频
        
        Args:
            video_paths: 视频路径列表
            output_path: 输出路径
            settings: 导出设置（可选）
            progress_callback: 进度回调
            
        Returns:
            TaskResult: 任务结果
        """
        start_process = time.time()
        task_id = f"merge_{int(start_process * 1000)}"
        
        if settings is None:
            settings = self.get_optimal_settings()
        
        print(f"\n🔗 合并视频: {len(video_paths)}个文件")
        
        try:
            # 创建临时文件列表
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
                for path in video_paths:
                    f.write(f"file '{path}'\n")
                concat_file = f.name
            
            # 计算总时长
            total_duration = 0
            for path in video_paths:
                info = FFmpegUtils.get_video_info(path)
                if info:
                    total_duration += info.duration
            
            # 构建命令
            cmd = [
                self.ffmpeg_path,
                "-f", "concat",
                "-safe", "0",
                "-i", concat_file,
                "-c:v", settings.video_codec.value,
                "-b:v", settings.video_bitrate,
                "-c:a", settings.audio_codec.value,
                "-b:a", settings.audio_bitrate,
                "-preset", settings.preset,
                "-y",
                output_path
            ]
            
            # 执行命令
            success, error = FFmpegUtils.run_command(
                cmd,
                progress_callback,
                total_duration
            )
            
            # 删除临时文件
            os.unlink(concat_file)
            
            processing_time = time.time() - start_process
            
            if success:
                output_info = FFmpegUtils.get_video_info(output_path)
                print(f"   ✓ 合并完成: {processing_time:.2f}s")
                
                return TaskResult(
                    task_id=task_id,
                    success=True,
                    output_path=output_path,
                    error_message=None,
                    processing_time=processing_time,
                    output_info=output_info
                )
            else:
                print(f"   ✗ 合并失败: {error}")
                return TaskResult(
                    task_id=task_id,
                    success=False,
                    output_path=None,
                    error_message=error,
                    processing_time=processing_time,
                    output_info=None
                )
                
        except Exception as e:
            processing_time = time.time() - start_process
            return TaskResult(
                task_id=task_id,
                success=False,
                output_path=None,
                error_message=str(e),
                processing_time=processing_time,
                output_info=None
            )
    
    def add_subtitles(self,
                      video_path: str,
                      subtitle_path: str,
                      output_path: str,
                      style: Dict[str, Any] = None) -> TaskResult:
        """
        添加字幕
        
        Args:
            video_path: 视频路径
            subtitle_path: 字幕文件路径（SRT/ASS）
            output_path: 输出路径
            style: 字幕样式
            
        Returns:
            TaskResult: 任务结果
        """
        start_process = time.time()
        task_id = f"subtitles_{int(start_process * 1000)}"
        
        print(f"\n📝 添加字幕: {os.path.basename(video_path)}")
        
        try:
            # 默认样式
            default_style = {
                "font": "Arial",
                "size": 24,
                "color": "white",
                "outline": 2,
                "outline_color": "black",
                "position": "bottom"
            }
            
            if style:
                default_style.update(style)
            
            # 构建滤镜字符串
            vf = f"subtitles={subtitle_path}"
            
            cmd = [
                self.ffmpeg_path,
                "-i", video_path,
                "-vf", vf,
                "-c:v", "libx264",
                "-crf", "23",
                "-preset", "medium",
                "-c:a", "copy",
                "-y",
                output_path
            ]
            
            success, error = FFmpegUtils.run_command(cmd)
            
            processing_time = time.time() - start_process
            
            if success:
                print(f"   ✓ 字幕添加完成: {processing_time:.2f}s")
                return TaskResult(
                    task_id=task_id,
                    success=True,
                    output_path=output_path,
                    error_message=None,
                    processing_time=processing_time,
                    output_info=None
                )
            else:
                print(f"   ✗ 字幕添加失败: {error}")
                return TaskResult(
                    task_id=task_id,
                    success=False,
                    output_path=None,
                    error_message=error,
                    processing_time=processing_time,
                    output_info=None
                )
                
        except Exception as e:
            processing_time = time.time() - start_process
            return TaskResult(
                task_id=task_id,
                success=False,
                output_path=None,
                error_message=str(e),
                processing_time=processing_time,
                output_info=None
            )
    
    def batch_process(self,
                      tasks: List[VideoTask],
                      progress_callback: Optional[Callable] = None) -> List[TaskResult]:
        """
        批量处理任务
        
        Args:
            tasks: 任务列表
            progress_callback: 总体进度回调
            
        Returns:
            List[TaskResult]: 任务结果列表
        """
        print(f"\n🚀 开始批量处理: {len(tasks)}个任务")
        print(f"   并行工作线程: {self.max_workers}")
        
        results = []
        completed = 0
        
        def task_wrapper(task: VideoTask) -> TaskResult:
            """任务包装器"""
            if task.operation == "cut_lossless":
                return self.cut_lossless(
                    task.input_path,
                    task.params["start_time"],
                    task.params["end_time"],
                    task.output_path
                )
            elif task.operation == "cut_reencode":
                return self.cut_with_reencode(
                    task.input_path,
                    task.params["start_time"],
                    task.params["end_time"],
                    task.output_path,
                    task.params.get("settings")
                )
            elif task.operation == "merge":
                return self.merge_videos(
                    task.params["video_paths"],
                    task.output_path
                )
            else:
                return TaskResult(
                    task_id=task.task_id,
                    success=False,
                    output_path=None,
                    error_message=f"未知操作: {task.operation}",
                    processing_time=0,
                    output_info=None
                )
        
        # 提交所有任务
        future_to_task = {
            self.executor.submit(task_wrapper, task): task 
            for task in tasks
        }
        
        # 收集结果
        for future in as_completed(future_to_task):
            task = future_to_task[future]
            try:
                result = future.result()
                results.append(result)
                
                # 更新进度
                completed += 1
                if progress_callback:
                    progress = (completed / len(tasks)) * 100
                    progress_callback(progress, result)
                
                # 调用任务回调
                if task.callback:
                    task.callback(result)
                    
            except Exception as e:
                results.append(TaskResult(
                    task_id=task.task_id,
                    success=False,
                    output_path=None,
                    error_message=str(e),
                    processing_time=0,
                    output_info=None
                ))
        
        # 统计结果
        success_count = sum(1 for r in results if r.success)
        print(f"\n📊 批量处理完成:")
        print(f"   成功: {success_count}/{len(tasks)}")
        print(f"   失败: {len(tasks) - success_count}/{len(tasks)}")
        
        return results
    
    def shutdown(self):
        """关闭引擎"""
        print("\n🛑 关闭ProfessionalVideoEngine...")
        self.executor.shutdown(wait=True)
        print("   ✓ 引擎已关闭")


# 使用示例
if __name__ == "__main__":
    # 初始化引擎
    engine = ProfessionalVideoEngine(max_workers=4)
    
    # 测试视频路径
    test_video = "test_video.mp4"
    
    if os.path.exists(test_video):
        # 获取视频信息
        info = FFmpegUtils.get_video_info(test_video)
        if info:
            print(f"\n视频信息:")
            print(f"   时长: {info.duration:.2f}s")
            print(f"   分辨率: {info.width}x{info.height}")
            print(f"   帧率: {info.fps:.2f}fps")
            print(f"   码率: {info.bitrate / 1000000:.2f}Mbps")
        
        # 无损剪辑测试
        result = engine.cut_lossless(test_video, 10, 20)
        print(f"\n无损剪辑结果:")
        print(f"   成功: {result.success}")
        print(f"   输出: {result.output_path}")
        print(f"   耗时: {result.processing_time:.2f}s")
        
        # 重新编码剪辑测试
        settings = engine.get_optimal_settings("抖音")
        result2 = engine.cut_with_reencode(
            test_video, 
            30, 40, 
            settings=settings
        )
        print(f"\n重新编码剪辑结果:")
        print(f"   成功: {result2.success}")
        print(f"   输出: {result2.output_path}")
        print(f"   耗时: {result2.processing_time:.2f}s")
    else:
        print(f"测试视频不存在: {test_video}")
    
    # 关闭引擎
    engine.shutdown()
