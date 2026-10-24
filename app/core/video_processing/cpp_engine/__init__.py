"""
Py+C++ 混合内核 - Python 封装层
================================
提供 C++ 视频引擎的 Python 接口，实现高性能视频处理
"""

import os
import sys
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from enum import Enum
import logging

logger = logging.getLogger("AI短剧编辑器.cpp_engine")


def _ensure_ffmpeg_path():
    """
    补短 P0#3：保证 system() / 子进程调用的 ffmpeg 是带 libfreetype(drawtext) 的版本。

    C++ 引擎内部通过 system("ffmpeg ...") 调用 ffmpeg，依赖 PATH 解析。
    如果 PATH 排在前面的 ffmpeg.exe 不带 libfreetype（典型：Shotcut 自带 ffmpeg），
    水印等 drawtext 类滤镜就会报 "No such filter: 'drawtext'"。

    策略（不破坏现有导入/全局状态，只在当前进程 PATH 前置项目内 ffmpeg 目录）：
      1. 优先用环境变量 AI_EDITOR_FFMPEG_DIR
      2. 退回项目内 thirdparty/ffmpeg/bin
      3. 都没有则保持原状（让系统 PATH 自行决定）
    """
    try:
        candidates = []
        env_dir = os.environ.get("AI_EDITOR_FFMPEG_DIR", "").strip()
        if env_dir and os.path.isfile(os.path.join(env_dir, "ffmpeg.exe")):
            candidates.append(env_dir)

        # 项目内置 thirdparty
        here = os.path.dirname(os.path.abspath(__file__))
        project_ffmpeg_dir = os.path.normpath(
            os.path.join(here, "..", "..", "..", "thirdparty", "ffmpeg", "bin")
        )
        if os.path.isfile(os.path.join(project_ffmpeg_dir, "ffmpeg.exe")):
            candidates.append(project_ffmpeg_dir)

        if not candidates:
            return

        ffmpeg_dir = candidates[0]

        # 关键：把项目内 ffmpeg 目录插到 PATH **绝对最前面**（不污染用户 PATH）
        #
        # 为什么不能简单依赖既有 PATH：
        #   mlt_engine_cpp._load_mlt() 会把 thirdparty/mlt/Shotcut 目录加到 PATH 最前，
        #   它的 ffmpeg.exe 没有 --enable-libfreetype，会让 system() 抓到不带 drawtext 的版本。
        # 所以我们要比它更"前"。
        current_path = os.environ.get("PATH", "")
        # 移除已存在的同目录条目，避免重复
        path_dirs = [d for d in current_path.split(os.pathsep) if d and os.path.normcase(d) != os.path.normcase(ffmpeg_dir)]
        new_path = ffmpeg_dir + os.pathsep + os.pathsep.join(path_dirs)
        os.environ["PATH"] = new_path

        def _has_drawtext(ffmpeg_path: str) -> bool:
            try:
                import subprocess
                r = subprocess.run(
                    [ffmpeg_path, "-hide_banner", "-filters"],
                    capture_output=True, text=True, timeout=5,
                )
                return "drawtext" in (r.stdout or "")
            except Exception:
                return False

        # 验证：当前 PATH 最前的 ffmpeg 是不是带 drawtext 的
        first_ffmpeg = None
        for d in new_path.split(os.pathsep):
            p = os.path.join(d, "ffmpeg.exe") if d else ""
            if p and os.path.isfile(p):
                first_ffmpeg = p
                break

        if first_ffmpeg and _has_drawtext(first_ffmpeg):
            logger.info(f"FFmpeg PATH 已前置: {ffmpeg_dir}（带 libfreetype 的版本）")
        else:
            logger.warning(f"FFmpeg PATH 前置后 drawtext 仍不可用: {first_ffmpeg}")
    except Exception as e:
        logger.debug(f"_ensure_ffmpeg_path 跳过: {e}")


# 在导入 C++ 扩展前先纠正 ffmpeg PATH，避免 system() 抓到不带 drawtext 的 ffmpeg
_ensure_ffmpeg_path()

# 尝试导入 C++ 扩展模块
try:
    from .video_engine_cpp import (
        VideoEngine,
        VideoInfo,
        ExportConfig,
        ClipSegment,
        VideoFrame,
        AudioFrame,
        PerformanceStats,
        get_video_engine
    )
    CPP_ENGINE_AVAILABLE = True
    logger.info("C++ 视频引擎加载成功")
except ImportError as e:
    logger.warning(f"C++ 视频引擎加载失败: {e}")
    CPP_ENGINE_AVAILABLE = False


class VideoCodec(Enum):
    """视频编码器"""
    H264 = "libx264"
    H265 = "libx265"
    NVENC_H264 = "h264_nvenc"
    NVENC_H265 = "hevc_nvenc"
    AMF_H264 = "h264_amf"
    QSV_H264 = "h264_qsv"


class VideoPreset(Enum):
    """编码预设"""
    ULTRAFAST = "ultrafast"
    FAST = "fast"
    MEDIUM = "medium"
    SLOW = "slow"
    VERYSLOW = "veryslow"


@dataclass
class VideoProcessingResult:
    """视频处理结果"""
    success: bool
    output_path: str
    processing_time: float
    error_message: str = ""
    stats: Optional[Dict] = None


class CppVideoEngine:
    """C++ 视频引擎 Python 封装"""
    
    def __init__(self):
        """初始化视频引擎"""
        if not CPP_ENGINE_AVAILABLE:
            raise RuntimeError("C++ 视频引擎不可用，请检查编译状态")
        
        self._engine = get_video_engine()
        self._gpu_encoder = None
        self._detect_gpu()
    
    def _detect_gpu(self):
        """检测 GPU 编码器"""
        try:
            encoder_name = ""
            if self._engine.detect_gpu_encoder(encoder_name):
                self._gpu_encoder = encoder_name
                logger.info(f"检测到 GPU 编码器: {encoder_name}")
            else:
                logger.info("未检测到 GPU 编码器，使用 CPU 编码")
        except Exception as e:
            logger.warning(f"GPU 检测失败: {e}")
    
    def analyze_video(self, filepath: str) -> Optional[VideoInfo]:
        """
        分析视频文件
        
        Args:
            filepath: 视频文件路径
            
        Returns:
            VideoInfo 对象，包含视频信息
        """
        try:
            return self._engine.analyze_video(filepath)
        except Exception as e:
            logger.error(f"视频分析失败: {e}")
            return None
    
    def extract_frame(self, filepath: str, timestamp: float,
                     output_path: str, width: int = 0, height: int = 0) -> bool:
        """
        提取视频帧
        
        Args:
            filepath: 视频文件路径
            timestamp: 时间戳（秒）
            output_path: 输出路径
            width: 输出宽度（0 表示原始宽度）
            height: 输出高度（0 表示原始高度）
            
        Returns:
            是否成功
        """
        try:
            return self._engine.extract_frame(filepath, timestamp, output_path, width, height)
        except Exception as e:
            logger.error(f"帧提取失败: {e}")
            return False
    
    def extract_thumbnails(self, filepath: str, count: int,
                          output_dir: str, width: int = 160, height: int = 90) -> List[str]:
        """
        批量提取缩略图
        
        Args:
            filepath: 视频文件路径
            count: 缩略图数量
            output_dir: 输出目录
            width: 缩略图宽度
            height: 缩略图高度
            
        Returns:
            缩略图路径列表
        """
        try:
            return self._engine.extract_thumbnails(filepath, count, output_dir, width, height)
        except Exception as e:
            logger.error(f"缩略图提取失败: {e}")
            return []
    
    def clip_video(self, input_path: str, output_path: str,
                  start_time: float, duration: float,
                  speed: float = 1.0,
                  progress_callback=None) -> VideoProcessingResult:
        """
        剪辑视频
        
        Args:
            input_path: 输入视频路径
            output_path: 输出视频路径
            start_time: 开始时间（秒）
            duration: 持续时间（秒）
            speed: 播放速度
            progress_callback: 进度回调函数
            
        Returns:
            VideoProcessingResult 处理结果
        """
        try:
            success = self._engine.clip_video(
                input_path, output_path, start_time, duration, speed, progress_callback
            )
            
            stats = self._engine.get_last_stats()
            
            return VideoProcessingResult(
                success=success,
                output_path=output_path,
                processing_time=stats.processing_time,
                stats={
                    "processing_time": stats.processing_time,
                    "fps_processed": stats.fps_processed,
                    "frames_processed": stats.frames_processed
                }
            )
        except Exception as e:
            logger.error(f"视频剪辑失败: {e}")
            return VideoProcessingResult(
                success=False,
                output_path="",
                processing_time=0,
                error_message=str(e)
            )
    
    def merge_clips(self, clips: List[ClipSegment], output_path: str,
                   config: Optional[ExportConfig] = None,
                   progress_callback=None) -> VideoProcessingResult:
        """
        合并视频片段
        
        Args:
            clips: 视频片段列表
            output_path: 输出路径
            config: 导出配置
            progress_callback: 进度回调
            
        Returns:
            VideoProcessingResult 处理结果
        """
        if config is None:
            config = ExportConfig()
            config.codec = self._gpu_encoder if self._gpu_encoder else "libx264"
            config.preset = "fast"
            config.bitrate = 5000
            config.audio_bitrate = 128
        
        try:
            success = self._engine.merge_clips(clips, output_path, config, progress_callback)
            
            return VideoProcessingResult(
                success=success,
                output_path=output_path,
                processing_time=0
            )
        except Exception as e:
            logger.error(f"视频合并失败: {e}")
            return VideoProcessingResult(
                success=False,
                output_path="",
                processing_time=0,
                error_message=str(e)
            )
    
    def add_watermark(self, input_path: str, output_path: str,
                     text: str, font_size: int = 24,
                     color: str = "white",
                     x: int = -1, y: int = -1) -> bool:
        """
        添加文字水印
        
        Args:
            input_path: 输入视频路径
            output_path: 输出视频路径
            text: 水印文字
            font_size: 字体大小
            color: 字体颜色
            x: X 坐标（-1 表示居中）
            y: Y 坐标（-1 表示居中）
            
        Returns:
            是否成功
        """
        try:
            return self._engine.add_watermark(
                input_path, output_path, text, font_size, color, x, y
            )
        except Exception as e:
            logger.error(f"水印添加失败: {e}")
            return False
    
    def add_background_music(self, video_path: str, audio_path: str,
                            output_path: str,
                            audio_volume: float = 0.3,
                            video_volume: float = 1.0) -> bool:
        """
        添加背景音乐
        
        Args:
            video_path: 视频文件路径
            audio_path: 音频文件路径
            output_path: 输出路径
            audio_volume: 音频音量
            video_volume: 视频音量
            
        Returns:
            是否成功
        """
        try:
            return self._engine.add_background_music(
                video_path, audio_path, output_path, audio_volume, video_volume
            )
        except Exception as e:
            logger.error(f"背景音乐添加失败: {e}")
            return False
    
    def convert_format(self, input_path: str, output_path: str,
                      config: Optional[ExportConfig] = None,
                      progress_callback=None) -> VideoProcessingResult:
        """
        转换视频格式
        
        Args:
            input_path: 输入路径
            output_path: 输出路径
            config: 导出配置
            progress_callback: 进度回调
            
        Returns:
            VideoProcessingResult 处理结果
        """
        if config is None:
            config = ExportConfig()
            config.codec = self._gpu_encoder if self._gpu_encoder else "libx264"
            config.preset = "fast"
            config.bitrate = 5000
            config.audio_bitrate = 128
        
        try:
            success = self._engine.convert_format(
                input_path, output_path, config, progress_callback
            )
            
            return VideoProcessingResult(
                success=success,
                output_path=output_path,
                processing_time=0
            )
        except Exception as e:
            logger.error(f"格式转换失败: {e}")
            return VideoProcessingResult(
                success=False,
                output_path="",
                processing_time=0,
                error_message=str(e)
            )
    
    def extract_audio(self, video_path: str, output_path: str,
                     sample_rate: int = 44100,
                     channels: int = 2) -> bool:
        """
        提取音频
        
        Args:
            video_path: 视频路径
            output_path: 输出音频路径
            sample_rate: 采样率
            channels: 声道数
            
        Returns:
            是否成功
        """
        try:
            return self._engine.extract_audio(
                video_path, output_path, sample_rate, channels
            )
        except Exception as e:
            logger.error(f"音频提取失败: {e}")
            return False
    
    def get_video_metadata(self, filepath: str) -> str:
        """
        获取视频元数据
        
        Args:
            filepath: 视频文件路径
            
        Returns:
            元数据字符串
        """
        try:
            return self._engine.get_video_metadata(filepath)
        except Exception as e:
            logger.error(f"元数据获取失败: {e}")
            return ""
    
    def get_gpu_encoder(self) -> Optional[str]:
        """获取 GPU 编码器名称"""
        return self._gpu_encoder
    
    def set_thread_pool_size(self, size: int):
        """设置线程池大小"""
        self._engine.set_thread_pool_size(size)
    
    def cancel(self):
        """取消当前操作"""
        self._engine.cancel()


# 全局引擎实例
_engine_instance = None


def get_engine() -> CppVideoEngine:
    """获取全局视频引擎实例"""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = CppVideoEngine()
    return _engine_instance


def is_cpp_engine_available() -> bool:
    """检查 C++ 引擎是否可用"""
    return CPP_ENGINE_AVAILABLE
