"""
软渲染器 - 第二阶段核心组件
=======================================
提供基于CPU的软件渲染，支持多种视频格式和特效
目标：支持低配设备流畅运行，提供基础渲染能力
"""

import os
import subprocess
import tempfile
import threading
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field
from enum import Enum
import time

from app.modules.utils.logger import logger

class RenderFormat(Enum):
    """渲染格式"""
    MP4 = "mp4"
    WEBM = "webm"
    MOV = "mov"
    AVI = "avi"

class RenderQuality(Enum):
    """渲染质量"""
    LOW = "low"      # 预览质量
    MEDIUM = "medium"  # 编辑质量
    HIGH = "high"      # 最终导出质量

class RenderCodec(Enum):
    """编码器"""
    H264 = "libx264"
    H265 = "libx265"
    VP9 = "libvpx-vp9"
    PRORES = "prores_ks"

@dataclass
class RenderConfig:
    """渲染配置"""
    width: int = 1920
    height: int = 1080
    fps: float = 30.0
    format: RenderFormat = RenderFormat.MP4
    codec: RenderCodec = RenderCodec.H264
    quality: RenderQuality = RenderQuality.MEDIUM
    bitrate: str = "auto"
    preset: str = "medium"
    threads: int = 4

@dataclass
class FrameData:
    """帧数据"""
    video_path: str
    frame_index: int
    timestamp: float
    effects: List[str] = field(default_factory=list)
    filters: List[str] = field(default_factory=list)

@dataclass
class RenderResult:
    """渲染结果"""
    success: bool
    output_path: Optional[str] = None
    frame_count: int = 0
    duration: float = 0.0
    error_message: Optional[str] = None
    render_time: float = 0.0

class SoftwareRenderer:
    """增强软渲染器"""
    
    def __init__(self, config: Optional[RenderConfig] = None):
        self.config = config or RenderConfig()
        self._initialized = False
        self._rendering = False
        self._current_frame = 0
        self._total_frames = 0
        self._lock = threading.Lock()
        self._temp_dir = tempfile.mkdtemp(prefix="soft_render_")
        
        logger.info(f"软渲染器初始化: {self.config.width}x{self.config.height}@{self.config.fps}FPS")
    
    def initialize(self) -> bool:
        """初始化渲染器"""
        if self._initialized:
            logger.warning("软渲染器已初始化")
            return False
        
        try:
            # 检查FFmpeg是否可用
            result = subprocess.run(
                ['ffmpeg', '-version'],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode != 0:
                logger.error("FFmpeg未找到或不可用")
                return False
            
            self._initialized = True
            logger.info("软渲染器初始化成功")
            return True
            
        except Exception as e:
            logger.error(f"软渲染器初始化失败: {e}")
            return False
    
    def render_frame(self, frame_data: FrameData) -> Optional[RenderResult]:
        """渲染单帧"""
        if not self._initialized:
            return RenderResult(
                success=False,
                error_message="渲染器未初始化"
            )
        
        with self._lock:
            try:
                start_time = time.time()
                
                # 构建FFmpeg命令
                cmd = self._build_ffmpeg_command(frame_data, single_frame=True)
                
                # 执行渲染
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                
                render_time = time.time() - start_time
                
                if result.returncode == 0:
                    return RenderResult(
                        success=True,
                        frame_count=1,
                        render_time=render_time
                    )
                else:
                    error_msg = result.stderr if result.stderr else "未知错误"
                    return RenderResult(
                        success=False,
                        error_message=f"渲染失败: {error_msg}"
                    )
                    
            except Exception as e:
                logger.error(f"帧渲染异常: {e}")
                return RenderResult(
                    success=False,
                    error_message=str(e)
                )
    
    def render_sequence(self, frame_data_list: List[FrameData], 
                   output_path: str) -> RenderResult:
        """渲染视频序列"""
        if not self._initialized:
            return RenderResult(
                success=False,
                error_message="渲染器未初始化"
            )
        
        if not frame_data_list:
            return RenderResult(
                success=False,
                error_message="帧数据列表为空"
            )
        
        with self._lock:
            if self._rendering:
                logger.warning("渲染器正在渲染中")
                return RenderResult(
                    success=False,
                    error_message="渲染器忙碌"
                )
            
            self._rendering = True
            start_time = time.time()
            
            try:
                # 创建临时文件列表
                temp_files = []
                for i, frame_data in enumerate(frame_data_list):
                    temp_file = os.path.join(
                        self._temp_dir,
                        f"frame_{i:06d}.png"
                    )
                    temp_files.append(temp_file)
                
                # 渲染所有帧
                success_count = 0
                for i, frame_data in enumerate(frame_data_list):
                    result = self.render_frame(frame_data)
                    if result.success:
                        success_count += 1
                    else:
                        logger.warning(f"帧{i}渲染失败: {result.error_message}")
                
                # 合成视频
                if success_count > 0:
                    video_result = self._combine_frames_to_video(
                        temp_files, output_path
                    )
                else:
                    video_result = RenderResult(
                        success=False,
                        error_message="所有帧渲染失败"
                    )
                
                # 清理临时文件
                for temp_file in temp_files:
                    try:
                        if os.path.exists(temp_file):
                            os.remove(temp_file)
                    except Exception as e:
                        logger.warning(f"清理临时文件失败: {e}")
                
                self._rendering = False
                render_time = time.time() - start_time
                
                return video_result
                
            except Exception as e:
                self._rendering = False
                logger.error(f"序列渲染异常: {e}")
                return RenderResult(
                    success=False,
                    error_message=str(e)
                )
    
    def _build_ffmpeg_command(self, frame_data: FrameData, 
                            single_frame: bool = False) -> List[str]:
        """构建FFmpeg命令"""
        cmd = ['ffmpeg']
        
        # 输入
        if single_frame:
            cmd.extend([
                '-i', frame_data.video_path,
                '-vf', f'select=eq(n\,{frame_data.frame_index})',
                '-vframes', '1',
                '-f', 'image2pipe'
            ])
        else:
            cmd.extend(['-f', 'image2pipe'])
        
        # 特效和滤镜
        all_filters = []
        if frame_data.effects:
            all_filters.extend(frame_data.effects)
        if frame_data.filters:
            all_filters.extend(frame_data.filters)
        if all_filters:
            filters_str = ','.join(all_filters)
            cmd.extend(['-vf', filters_str])
        
        # 输出格式
        cmd.extend([
            '-s', f'{self.config.width}x{self.config.height}',
            '-r', f'{self.config.fps}',
            '-c:v', self.config.codec.value,
            '-preset', self.config.preset
        ])
        
        # 质量设置
        if self.config.quality == RenderQuality.HIGH:
            cmd.extend(['-crf', '18'])
        elif self.config.quality == RenderQuality.MEDIUM:
            cmd.extend(['-crf', '23'])
        else:
            cmd.extend(['-crf', '28'])
        
        # 输出
        if single_frame:
            cmd.extend(['-pix_fmt', 'rgba', '-'])
        else:
            cmd.extend([
                '-c:a', 'aac',
                '-b:a', '128k',
                '-f', self.config.format.value
            ])
        
        return cmd
    
    def _combine_frames_to_video(self, frame_files: List[str], 
                             output_path: str) -> RenderResult:
        """合成视频"""
        try:
            # 构建合成命令
            cmd = [
                'ffmpeg',
                '-y',
                '-framerate', str(self.config.fps),
                '-i', f"concat:{'|'.join(frame_files)}"
            ]
            
            # 输出配置
            cmd.extend([
                '-c:v', self.config.codec.value,
                '-preset', self.config.preset,
                '-s', f'{self.config.width}x{self.config.height}',
                '-pix_fmt', 'yuv420p',
                '-movflags', '+faststart'
            ])
            
            # 音频
            cmd.extend([
                '-c:a', 'aac',
                '-b:a', '128k',
                '-shortest'
            ])
            
            # 输出文件
            cmd.extend(['-f', self.config.format.value, output_path])
            
            # 执行合成
            start_time = time.time()
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300
            )
            
            render_time = time.time() - start_time
            
            if result.returncode == 0:
                return RenderResult(
                    success=True,
                    output_path=output_path,
                    frame_count=len(frame_files),
                    duration=0.0,
                    render_time=render_time
                )
            else:
                error_msg = result.stderr if result.stderr else "未知错误"
                return RenderResult(
                    success=False,
                    error_message=f"视频合成失败: {error_msg}"
                )
                
        except Exception as e:
            logger.error(f"视频合成异常: {e}")
            return RenderResult(
                success=False,
                error_message=str(e)
            )
    
    def apply_effect(self, effect_name: str, params: Dict[str, Any]) -> bool:
        """应用特效"""
        effect_presets = {
            'brightness': f'brightness={params.get("value", 0)}',
            'contrast': f'contrast={params.get("value", 1.0)}',
            'saturation': f'saturation={params.get("value", 1.0)}',
            'blur': f'gblur={params.get("radius", 5)}',
            'sharpen': f'unsharp=5:5:0.5:0'
        }
        
        if effect_name in effect_presets:
            return True
        
        logger.warning(f"未知特效: {effect_name}")
        return False
    
    def get_render_stats(self) -> Dict[str, Any]:
        """获取渲染统计"""
        with self._lock:
            return {
                'initialized': self._initialized,
                'rendering': self._rendering,
                'current_frame': self._current_frame,
                'total_frames': self._total_frames,
                'config': {
                    'width': self.config.width,
                    'height': self.config.height,
                    'fps': self.config.fps,
                    'format': self.config.format.value,
                    'codec': self.config.codec.value,
                    'quality': self.config.quality.value
                }
            }
    
    def set_quality(self, quality: RenderQuality):
        """设置渲染质量"""
        self.config.quality = quality
        logger.info(f"渲染质量设置为: {quality.value}")
    
    def set_format(self, format: RenderFormat):
        """设置输出格式"""
        self.config.format = format
        logger.info(f"输出格式设置为: {format.value}")
    
    def set_resolution(self, width: int, height: int):
        """设置分辨率"""
        self.config.width = width
        self.config.height = height
        logger.info(f"分辨率设置为: {width}x{height}")
    
    def shutdown(self) -> bool:
        """关闭渲染器"""
        with self._lock:
            self._rendering = False
            self._initialized = False
            
            # 清理临时目录
            try:
                import shutil
                if os.path.exists(self._temp_dir):
                    shutil.rmtree(self._temp_dir)
                    logger.info("清理软渲染器临时目录")
            except Exception as e:
                logger.error(f"清理临时目录失败: {e}")
        
        return True

# 全局软渲染器实例
software_renderer = None

def get_software_renderer(config: Optional[RenderConfig] = None) -> SoftwareRenderer:
    """获取软渲染器实例（单例模式）"""
    global software_renderer
    if software_renderer is None:
        software_renderer = SoftwareRenderer(config)
    return software_renderer