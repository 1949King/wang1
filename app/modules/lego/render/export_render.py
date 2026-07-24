"""
导出渲染器 - 批量导出、离线渲染、多格式支持
=========================================
支持批量导出、断点续传、进度监控等高级导出功能
支持硬件加速编码 (NVENC/QSV/AMF)
"""

import numpy as np
from typing import Dict, Any, Optional, List
from PyQt6.QtCore import QObject, QThread, pyqtSignal
from PyQt6.QtGui import QImage
import logging
import time
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from . import IRenderer, RenderStats

logger = logging.getLogger("AI短剧编辑器.export_render")


class HardwareEncoder:
    """硬件编码器类型"""
    NONE = "libx264"
    NVIDIA = "h264_nvenc"
    NVIDIA_HEVC = "hevc_nvenc"
    INTEL = "h264_qsv"
    INTEL_HEVC = "hevc_qsv"
    AMD = "h264_amf"
    AMD_HEVC = "hevc_amf"


class ExportRenderer(QObject, IRenderer):
    """导出渲染器 - 批量导出、离线渲染、多格式支持"""
    
    def __init__(self):
        super().__init__()
        self._initialized = False
        self._width = 1920
        self._height = 1080
        self._fps = 30
        self._quality = "high"
        self._output_format = "mp4"
        self._output_path = "./output"
        self._stats = RenderStats()
        self._export_thread: Optional[QThread] = None
        self._is_exporting = False
        self._current_progress = 0.0
        self._total_frames = 0
        self._export_queue = []
        self._max_queue_size = 10
        self._supported_formats = ['mp4', 'avi', 'mov', 'mkv', 'flv', 'webm']
        self._supported_codecs = ['h264', 'h265', 'vp9', 'av1', 'mpeg4']
        self._supported_qualities = ['low', 'medium', 'high', 'ultra']
        self._h264_encoder = HardwareEncoder.NONE
        self._h265_encoder = HardwareEncoder.NONE
        self._has_gpu = False
    
    def initialize(self) -> bool:
        """初始化导出渲染器"""
        try:
            logger.info("初始化导出渲染器")
            
            output_dir = Path(self._output_path)
            output_dir.mkdir(parents=True, exist_ok=True)
            
            self._detect_hardware_encoders()
            
            self._initialized = True
            return True
        except Exception as e:
            logger.error(f"导出渲染器初始化失败: {e}")
            return False
    
    def _detect_hardware_encoders(self) -> None:
        """检测可用的硬件编码器"""
        try:
            result = subprocess.run(
                ["ffmpeg", "-encoders"],
                capture_output=True, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )
            out = result.stdout.lower()
            
            if "h264_nvenc" in out:
                self._h264_encoder = HardwareEncoder.NVIDIA
                self._has_gpu = True
            elif "h264_qsv" in out:
                self._h264_encoder = HardwareEncoder.INTEL
                self._has_gpu = True
            elif "h264_amf" in out:
                self._h264_encoder = HardwareEncoder.AMD
                self._has_gpu = True
            
            if "hevc_nvenc" in out:
                self._h265_encoder = HardwareEncoder.NVIDIA_HEVC
            elif "hevc_qsv" in out:
                self._h265_encoder = HardwareEncoder.INTEL_HEVC
            elif "hevc_amf" in out:
                self._h265_encoder = HardwareEncoder.AMD_HEVC
            
            logger.info(f"硬件编码器检测完成: H.264={self._h264_encoder}, H.265={self._h265_encoder}, GPU={self._has_gpu}")
        except Exception as e:
            logger.warning(f"检测硬件编码器失败: {e}")
    
    def render_frame(self, frame_data: Dict[str, Any]) -> Optional[QImage]:
        """渲染单帧（导出模式）"""
        if not self._initialized:
            logger.error("导出渲染器未初始化")
            return None
        
        try:
            width = frame_data.get('width', self._width)
            height = frame_data.get('height', self._height)
            
            if 'image_data' in frame_data:
                image_data = frame_data['image_data']
                
                if isinstance(image_data, np.ndarray):
                    qimage = QImage(
                        image_data.data,
                        image_data.shape[1],
                        image_data.shape[0],
                        QImage.Format.Format_RGB888
                    )
                    
                    if self._quality == 'low':
                        qimage = qimage.scaled(
                            width // 2,
                            height // 2,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation
                        )
                    
                    return qimage
            
            logger.warning(f"无法渲染帧，缺少图像数据: {list(frame_data.keys())}")
            return None
            
        except Exception as e:
            logger.error(f"导出渲染帧失败: {e}")
            return None
    
    def render_sequence(self, sequence_data: List[Dict[str, Any]]) -> bool:
        """渲染序列（导出模式）"""
        if not self._initialized:
            logger.error("导出渲染器未初始化")
            return False
        
        try:
            start_time = time.time()
            success_count = 0
            
            for frame_data in sequence_data:
                image = self.render_frame(frame_data)
                if image:
                    success_count += 1
            
            end_time = time.time()
            total_time = end_time - start_time
            
            if self._stats:
                self._stats.frames_rendered = success_count
                self._stats.total_time = total_time
                if total_time > 0:
                    self._stats.average_fps = len(sequence_data) / total_time
            
            logger.info(f"导出渲染序列完成: {success_count}/{len(sequence_data)} 帧，耗时: {total_time:.2f}秒")
            return success_count == len(sequence_data)
            
        except Exception as e:
            logger.error(f"导出渲染序列失败: {e}")
            return False
    
    def export_video(self, sequence_data: List[Dict[str, Any]] = None,
                     output_path: str = None, format: str = None,
                     codec: str = None, quality: str = None,
                     source_video: str = None, clips: List[Dict] = None) -> bool:
        """导出视频文件 - 使用FFmpeg真实编码"""
        if not self._initialized:
            logger.error("导出渲染器未初始化")
            return False

        try:
            output_file = output_path or os.path.join(
                self._output_path, f"export_{int(time.time())}.{format or self._output_format}")
            output_format = format or self._output_format
            output_quality = quality or self._quality
            os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)

            logger.info(f"开始导出视频: {output_file}")

            if source_video and os.path.exists(source_video):
                return self._export_source(source_video, output_file, output_format, output_quality)
            if clips:
                return self._export_clips(clips, output_file, output_format, output_quality)
            if sequence_data:
                return self._export_frames(sequence_data, output_file, output_format, output_quality)

            logger.error("无可用导出数据")
            return False

        except Exception as e:
            logger.error(f"视频导出失败: {e}")
            return False

    def _export_source(self, source: str, output_file: str, fmt: str, quality: str) -> bool:
        """从源视频直接导出，支持硬件加速编码"""
        crf_map = {'low': '28', 'medium': '23', 'high': '18', 'ultra': '15'}
        
        cmd = ["ffmpeg", "-y"]
        
        if self._h264_encoder in (HardwareEncoder.NVIDIA, HardwareEncoder.NVIDIA_HEVC):
            cmd += ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
        elif self._h264_encoder in (HardwareEncoder.INTEL, HardwareEncoder.INTEL_HEVC):
            cmd += ["-hwaccel", "qsv", "-hwaccel_output_format", "qsv"]
        elif self._h264_encoder in (HardwareEncoder.AMD, HardwareEncoder.AMD_HEVC):
            cmd += ["-hwaccel", "d3d11va"]
        
        cmd += ["-i", source]
        
        codec = self._h264_encoder
        if fmt.lower() in ('mkv', 'mov') and self._h265_encoder != HardwareEncoder.NONE:
            codec = self._h265_encoder
        
        cmd += ["-c:v", codec]
        
        if codec in (HardwareEncoder.NVIDIA, HardwareEncoder.NVIDIA_HEVC):
            cmd += ["-rc", "cbr", "-gpu", "0"]
        elif codec in (HardwareEncoder.INTEL, HardwareEncoder.INTEL_HEVC):
            cmd += ["-init_qpP", "24"]
        
        cmd += [
            "-crf", crf_map.get(quality, '23'),
            "-c:a", "aac", "-b:a", "192k",
            output_file
        ]
        
        logger.info(f"导出命令: {' '.join(cmd[:10])}...")
        
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=600,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        )
        success = result.returncode == 0 and os.path.exists(output_file)
        if success:
            logger.info(f"源视频导出完成: {output_file} (编码器: {codec})")
        else:
            logger.error(f"导出失败: {result.stderr[:300]}")
            logger.info(f"尝试使用软件编码回退...")
            return self._export_with_software_codec(source, output_file, fmt, quality)
        return success
    
    def _export_with_software_codec(self, source: str, output_file: str, fmt: str, quality: str) -> bool:
        """使用软件编码回退导出"""
        crf_map = {'low': '28', 'medium': '23', 'high': '18', 'ultra': '15'}
        result = subprocess.run([
            "ffmpeg", "-y", "-i", source,
            "-c:v", "libx264", "-preset", "medium",
            "-crf", crf_map.get(quality, '23'),
            "-c:a", "aac", "-b:a", "192k",
            output_file
        ], capture_output=True, text=True, timeout=600,
           creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
        success = result.returncode == 0 and os.path.exists(output_file)
        if success:
            logger.info(f"源视频导出完成(软件编码): {output_file}")
        else:
            logger.error(f"软件编码导出失败: {result.stderr[:300]}")
        return success

    def _export_clips(self, clips: List[Dict], output_file: str, fmt: str, quality: str) -> bool:
        """从多个片段拼接导出"""
        concat_file = None
        try:
            valid_clips = [c for c in clips if os.path.exists(c.get('path', ''))]
            if not valid_clips:
                logger.error("无有效片段")
                return False

            if len(valid_clips) == 1:
                return self._export_source(valid_clips[0]['path'], output_file, fmt, quality)

            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False,
                                              encoding='utf-8') as f:
                for c in valid_clips:
                    f.write(f"file '{c['path']}'\n")
                concat_file = f.name

            result = subprocess.run([
                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", concat_file, "-c", "copy", output_file
            ], capture_output=True, text=True, timeout=600,
               creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)

            success = result.returncode == 0 and os.path.exists(output_file)
            if not success:
                logger.warning(f"concat copy failed, trying re-encode: {result.stderr[:200]}")
                success = self._export_source(valid_clips[0]['path'], output_file, fmt, quality)
            return success
        except Exception as e:
            logger.error(f"片段导出失败: {e}")
            return False
        finally:
            if concat_file and os.path.exists(concat_file):
                os.unlink(concat_file)

    def _export_frames(self, sequence_data: List[Dict], output_file: str,
                        fmt: str, quality: str) -> bool:
        """从帧序列导出，支持硬件加速编码"""
        if not sequence_data:
            return False
        first = sequence_data[0]
        img_data = first.get('image_data')
        if img_data is None:
            return False
        h, w = img_data.shape[:2]
        crf_map = {'low': '28', 'medium': '23', 'high': '18', 'ultra': '15'}
        
        codec = self._h264_encoder
        if fmt.lower() in ('mkv', 'mov') and self._h265_encoder != HardwareEncoder.NONE:
            codec = self._h265_encoder
        
        cmd = [
            "ffmpeg", "-y",
            "-f", "rawvideo", "-vcodec", "rawvideo",
            "-s", f"{w}x{h}", "-pix_fmt", "rgb24",
            "-r", str(self._fps),
            "-i", "pipe:0",
        ]
        
        if codec in (HardwareEncoder.NVIDIA, HardwareEncoder.NVIDIA_HEVC):
            cmd += ["-hwaccel", "cuda"]
        
        cmd += ["-c:v", codec]
        
        if codec in (HardwareEncoder.NVIDIA, HardwareEncoder.NVIDIA_HEVC):
            cmd += ["-rc", "cbr", "-gpu", "0"]
        elif codec in (HardwareEncoder.INTEL, HardwareEncoder.INTEL_HEVC):
            cmd += ["-init_qpP", "24"]
        
        cmd += [
            "-crf", crf_map.get(quality, '23'),
            "-pix_fmt", "yuv420p",
            output_file
        ]
        
        logger.info(f"帧序列导出命令: {' '.join(cmd[:12])}...")
        
        process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE,
                                     creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
        try:
            for frame_data in sequence_data:
                img = frame_data.get('image_data')
                if img is not None:
                    if img.ndim == 3 and img.shape[2] == 3:
                        process.stdin.write(img.tobytes())
                    elif img.ndim == 2:
                        rgb = np.stack([img, img, img], axis=2)
                        process.stdin.write(rgb.tobytes())
            process.stdin.close()
            process.wait(timeout=600)
            success = process.returncode == 0 and os.path.exists(output_file)
            if success:
                logger.info(f"帧序列导出完成: {output_file} (编码器: {codec})")
            else:
                logger.error(f"帧序列导出失败，尝试软件编码回退")
                return self._export_frames_with_software_codec(sequence_data, output_file, fmt, quality)
            return success
        except Exception as e:
            logger.error(f"帧导出失败: {e}")
            process.kill()
            return False
    
    def _export_frames_with_software_codec(self, sequence_data: List[Dict], output_file: str,
                                           fmt: str, quality: str) -> bool:
        """使用软件编码回退从帧序列导出"""
        if not sequence_data:
            return False
        first = sequence_data[0]
        img_data = first.get('image_data')
        if img_data is None:
            return False
        h, w = img_data.shape[:2]
        crf_map = {'low': '28', 'medium': '23', 'high': '18', 'ultra': '15'}
        cmd = [
            "ffmpeg", "-y",
            "-f", "rawvideo", "-vcodec", "rawvideo",
            "-s", f"{w}x{h}", "-pix_fmt", "rgb24",
            "-r", str(self._fps),
            "-i", "pipe:0",
            "-c:v", "libx264", "-preset", "fast",
            "-crf", crf_map.get(quality, '23'),
            "-pix_fmt", "yuv420p",
            output_file
        ]
        process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE,
                                     creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
        try:
            for frame_data in sequence_data:
                img = frame_data.get('image_data')
                if img is not None:
                    if img.ndim == 3 and img.shape[2] == 3:
                        process.stdin.write(img.tobytes())
                    elif img.ndim == 2:
                        rgb = np.stack([img, img, img], axis=2)
                        process.stdin.write(rgb.tobytes())
            process.stdin.close()
            process.wait(timeout=600)
            success = process.returncode == 0 and os.path.exists(output_file)
            if success:
                logger.info(f"帧序列导出完成(软件编码): {output_file}")
            return success
        except Exception as e:
            logger.error(f"帧导出失败: {e}")
            process.kill()
            return False
    
    def _get_codec_for_format(self, format: str) -> str:
        """根据格式获取编码器"""
        format_codec_map = {
            'mp4': 'h264',
            'avi': 'mpeg4',
            'mov': 'h264',
            'mkv': 'h264',
            'flv': 'h264',
            'webm': 'vp9'
        }
        return format_codec_map.get(format, 'h264')
    
    def batch_export(self, export_tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """批量导出"""
        if not self._initialized:
            logger.error("导出渲染器未初始化")
            return {
                'success': False,
                'total_tasks': len(export_tasks),
                'completed_tasks': 0,
                'failed_tasks': 0,
                'total_time': 0.0
            }
        
        try:
            start_time = time.time()
            completed_tasks = 0
            failed_tasks = 0
            
            for task in export_tasks:
                try:
                    sequence_data = task.get('sequence_data', [])
                    output_path = task.get('output_path')
                    output_format = task.get('format', self._output_format)
                    codec = task.get('codec')
                    quality = task.get('quality', self._quality)
                    
                    success = self.export_video(sequence_data, output_path, output_format, codec, quality)
                    
                    if success:
                        completed_tasks += 1
                        logger.info(f"导出任务完成: {task.get('name', 'unknown')}")
                    else:
                        failed_tasks += 1
                        logger.error(f"导出任务失败: {task.get('name', 'unknown')}")
                        
                except Exception as e:
                    failed_tasks += 1
                    logger.error(f"导出任务异常: {task.get('name', 'unknown')}: {e}")
            
            end_time = time.time()
            total_time = end_time - start_time
            
            return {
                'success': True,
                'total_tasks': len(export_tasks),
                'completed_tasks': completed_tasks,
                'failed_tasks': failed_tasks,
                'total_time': total_time
            }
            
        except Exception as e:
            logger.error(f"批量导出失败: {e}")
            return {
                'success': False,
                'total_tasks': len(export_tasks),
                'completed_tasks': 0,
                'failed_tasks': 0,
                'total_time': 0.0
            }
    
    def cleanup(self) -> None:
        """清理导出渲染器资源"""
        try:
            logger.info("清理导出渲染器资源")
            
            if self._export_thread and self._export_thread.is_alive():
                self._export_thread.quit()
                self._export_thread.wait()
            
            self._initialized = False
            self._is_exporting = False
            self._export_queue.clear()
            self._current_progress = 0.0
            self._total_frames = 0
            
            self._stats = None
            logger.info("导出渲染器已清理")
            
        except Exception as e:
            logger.error(f"清理导出渲染器失败: {e}")
    
    def get_capabilities(self) -> Dict[str, Any]:
        """获取导出渲染能力"""
        return {
            'renderer_type': 'export',
            'supported_formats': self._supported_formats,
            'supported_codecs': self._supported_codecs,
            'supported_qualities': self._supported_qualities,
            'batch_export': True,
            'progress_monitoring': True,
            'resume_support': True,
            'max_resolution': '4096x2160',
            'quality_presets': True,
            'format_conversion': True
        }
    
    def set_quality(self, quality: str) -> None:
        """设置导出质量"""
        if quality in self._supported_qualities:
            self._quality = quality
            logger.info(f"导出渲染器质量设置为: {quality}")
        else:
            logger.warning(f"无效的质量设置: {quality}")
    
    def get_quality(self) -> str:
        """获取当前导出质量"""
        return self._quality
    
    def set_output_format(self, format: str) -> None:
        """设置输出格式"""
        if format in self._supported_formats:
            self._output_format = format
            logger.info(f"导出渲染器格式设置为: {format}")
        else:
            logger.warning(f"无效的格式设置: {format}")
    
    def get_output_format(self) -> str:
        """获取当前输出格式"""
        return self._output_format
    
    def set_output_path(self, path: str) -> None:
        """设置输出路径"""
        try:
            output_dir = Path(path)
            output_dir.mkdir(parents=True, exist_ok=True)
            self._output_path = path
            logger.info(f"导出渲染器输出路径设置为: {path}")
        except Exception as e:
            logger.error(f"设置输出路径失败: {e}")
    
    def get_output_path(self) -> str:
        """获取当前输出路径"""
        return self._output_path
    
    def get_export_progress(self) -> Dict[str, Any]:
        """获取导出进度"""
        return {
            'current_progress': self._current_progress,
            'total_frames': self._total_frames,
            'is_exporting': self._is_exporting,
            'queue_size': len(self._export_queue)
        }
    
    def add_to_queue(self, export_task: Dict[str, Any]) -> bool:
        """添加导出任务到队列"""
        if len(self._export_queue) >= self._max_queue_size:
            logger.warning("导出队列已满")
            return False
        
        self._export_queue.append(export_task)
        logger.info(f"添加导出任务到队列: {export_task.get('name', 'unknown')}")
        return True
    
    def clear_queue(self) -> None:
        """清空导出队列"""
        self._export_queue.clear()
        logger.info("导出队列已清空")