import subprocess
import os
from config import OUTPUT_PATH
from modules.utils.logger import logger
from typing import Optional, List, Dict, Any
from pathlib import Path
import platform
import re

class VideoProcessor:
    def __init__(self):
        # 尝试获取FFmpeg路径，默认使用系统PATH中的ffmpeg
        self.ffmpeg_path = "ffmpeg"
        self.hardware_acceleration = "none"
        self.available_gpus = []
        self.cuda_available = False
        self.opencl_available = False
        
        self._detect_hardware_capabilities()
    
    def _detect_hardware_capabilities(self):
        """检测硬件加速能力"""
        try:
            import subprocess
            
            # 检测CUDA可用性
            try:
                result = subprocess.run(
                    ["python", "-c", "import torch; print(torch.cuda.is_available())"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                self.cuda_available = "True" in result.stdout
                logger.info(f"CUDA可用性: {self.cuda_available}")
            except Exception as e:
                logger.warning(f"CUDA检测失败: {e}")
                self.cuda_available = False
            
            # 检测OpenCL可用性
            try:
                result = subprocess.run(
                    ["python", "-c", "import pyopencl; print('OpenCL available' if any(opencl.get_platforms()) else 'OpenCL not available')"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                self.opencl_available = "available" in result.stdout
                logger.info(f"OpenCL可用性: {self.opencl_available}")
            except Exception as e:
                logger.warning(f"OpenCL检测失败: {e}")
                self.opencl_available = False
            
            # 检测可用GPU
            if platform.system() == "Windows":
                try:
                    result = subprocess.run(
                        ["wmic", "path", "win32_VideoController", "get", "name", "/format:list"],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    gpu_info = result.stdout
                    self.available_gpus = self._parse_gpu_info(gpu_info)
                    logger.info(f"检测到GPU: {len(self.available_gpus)} 个")
                except Exception as e:
                    logger.warning(f"GPU检测失败: {e}")
                    self.available_gpus = []
            else:
                logger.info("非Windows系统，跳过GPU检测")
                self.available_gpus = []
            
            logger.info(f"硬件加速能力检测完成: CUDA={self.cuda_available}, OpenCL={self.opencl_available}, GPU数量={len(self.available_gpus)}")
        except Exception as e:
            logger.error(f"硬件检测过程出错: {e}")
    
    def _parse_gpu_info(self, gpu_info: str) -> List[Dict[str, Any]]:
        """解析GPU信息"""
        gpus = []
        lines = gpu_info.split('\n')
        
        for line in lines:
            if 'Name' in line and 'AdapterString' in line:
                try:
                    name_match = re.search(r'Name:\s*(.+?)\s*AdapterString:\s*(.+)', line)
                    if name_match:
                        gpu_name = name_match.group(1).strip()
                        adapter_match = re.search(r'AdapterString:\s*(.+)', line)
                        if adapter_match:
                            adapter = adapter_match.group(1).strip()
                            
                            gpu_info = {
                                'name': gpu_name,
                                'adapter': adapter,
                                'type': self._get_gpu_type(gpu_name)
                            }
                            gpus.append(gpu_info)
                except Exception as e:
                    logger.warning(f"解析GPU信息失败: {e}")
        
        return gpus
    
    def _get_gpu_type(self, gpu_name: str) -> str:
        """获取GPU类型"""
        gpu_name_lower = gpu_name.lower()
        
        if 'nvidia' in gpu_name_lower or 'geforce' in gpu_name_lower or 'quadro' in gpu_name_lower:
            return 'nvidia'
        elif 'amd' in gpu_name_lower or 'radeon' in gpu_name_lower:
            return 'amd'
        elif 'intel' in gpu_name_lower:
            return 'intel'
        else:
            return 'unknown'
    
    def get_hardware_info(self) -> Dict[str, Any]:
        """获取硬件信息"""
        return {
            'cuda_available': self.cuda_available,
            'opencl_available': self.opencl_available,
            'available_gpus': self.available_gpus,
            'hardware_acceleration': self.hardware_acceleration,
            'recommended_acceleration': self._get_recommended_acceleration()
        }
    
    def _get_recommended_acceleration(self) -> str:
        """获取推荐的硬件加速方式"""
        if self.cuda_available:
            return 'nvidia'
        elif self.opencl_available and self.available_gpus:
            return 'opencl'
        else:
            return 'none'
        
    def denoise_audio(self, video_path, output_path):
        """音频降噪"""
        if not os.path.exists(video_path):
            logger.error(f"视频文件不存在: {video_path}")
            return False
        
        cmd = [
            self.ffmpeg_path,
            "-i", video_path,
            "-af", "arnndn=m=rnnoise-models/denoise.rnnn",
            "-c:v", "copy",
            "-y",
            output_path
        ]
        
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            logger.info(f"音频降噪成功: {output_path}")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"音频降噪失败: {e.stderr}")
            return False
        except FileNotFoundError:
            logger.error(f"FFmpeg未找到，请确保已安装并添加到PATH中")
            return False
    
    def separate_audio(self, video_path, vocal_output_path, bgm_output_path):
        """分离人声和背景音乐"""
        if not os.path.exists(video_path):
            logger.error(f"视频文件不存在: {video_path}")
            return False
        
        # 使用FFmpeg的afftdn滤镜分离音频
        cmd = [
            self.ffmpeg_path,
            "-i", video_path,
            "-filter_complex",
            "[0:a]afftdn=nf=-20:tnf=-20[bgm];[0:a]afftdn=nf=-20:tnf=-20:dn=1[vocal]",
            "-map", "[vocal]",
            "-c:a", "aac",
            "-b:a", "128k",
            vocal_output_path,
            "-map", "[bgm]",
            "-c:a", "aac",
            "-b:a", "128k",
            bgm_output_path,
            "-y"
        ]
        
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            logger.info(f"音频分离成功: {vocal_output_path}, {bgm_output_path}")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"音频分离失败: {e.stderr}")
            return False
        except FileNotFoundError:
            logger.error(f"FFmpeg未找到，请确保已安装并添加到PATH中")
            return False
    
    def import_image_sequence(self, image_pattern, output_path, fps=30):
        """导入图片序列为视频
        
        Args:
            image_pattern: 图片序列的路径模式，例如 "images/frame_%04d.jpg"
            output_path: 输出视频路径
            fps: 帧率，默认为30
        """
        cmd = [
            self.ffmpeg_path,
            "-framerate", str(fps),
            "-i", image_pattern,
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-y",
            output_path
        ]
        
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            logger.info(f"图片序列导入成功: {output_path}")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"图片序列导入失败: {e.stderr}")
            return False
        except FileNotFoundError:
            logger.error(f"FFmpeg未找到，请确保已安装并添加到PATH中")
            return False
    
    def export_video(self, input_path, output_path, format=None, codec="libx264", bitrate="5M", fps=None, threads=None, hardware_acceleration=None, quality=None):
        """导出视频为不同格式
        
        Args:
            input_path: 输入视频路径
            output_path: 输出视频路径
            format: 输出格式，例如 "mp4", "mov", "avi", "wmv", "flv" 等
            codec: 编码器，默认为 "libx264"
            bitrate: 比特率，默认为 "5M"
            fps: 帧率，可选
            threads: 线程数，可选
            hardware_acceleration: 硬件加速方式，可选值："nvidia"（NVENC）, "amd"（AMF）
            quality: 编码质量，可选值："ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"
        """
        if not os.path.exists(input_path):
            logger.error(f"输入文件不存在: {input_path}")
            return False
        
        cmd = [
            self.ffmpeg_path,
            "-i", input_path
        ]
        
        # 添加硬件加速
        if hardware_acceleration == "nvidia":
            # 使用NVIDIA NVENC
            cmd.extend(["-hwaccel", "cuda", "-c:v", "h264_nvenc"])
        elif hardware_acceleration == "amd":
            # 使用AMD AMF
            cmd.extend(["-hwaccel", "d3d11va", "-c:v", "h264_amf"])
        else:
            # 使用软件编码
            cmd.extend(["-c:v", codec])
        
        # 添加帧率设置
        if fps:
            cmd.extend(["-r", str(fps)])
        
        # 添加比特率设置
        cmd.extend(["-b:v", bitrate])
        
        # 添加音频设置
        cmd.extend(["-c:a", "aac", "-b:a", "128k"])
        
        # 添加线程设置
        if threads:
            cmd.extend(["-threads", str(threads)])
        
        # 添加编码质量设置
        if quality:
            cmd.extend(["-preset", quality])
        
        # 添加格式设置
        if format:
            cmd.extend(["-f", format])
        
        cmd.extend(["-y", output_path])
        
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            logger.info(f"视频导出成功: {output_path}")
            logger.info(f"导出设置: 编码器={codec}, 比特率={bitrate}, 线程={threads}, 硬件加速={hardware_acceleration}, 质量={quality}")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"视频导出失败: {e.stderr}")
            return False
        except FileNotFoundError:
            logger.error(f"FFmpeg未找到，请确保已安装并添加到PATH中")
            return False
    
    def get_hardware_acceleration_options(self):
        """获取可用的硬件加速选项"""
        return [
            {"id": "none", "name": "无硬件加速", "description": "使用CPU软件编码"},
            {"id": "nvidia", "name": "NVIDIA NVENC", "description": "使用NVIDIA显卡硬件编码"},
            {"id": "amd", "name": "AMD AMF", "description": "使用AMD显卡硬件编码"}
        ]
    
    def get_quality_options(self):
        """获取可用的编码质量选项"""
        return [
            {"id": "ultrafast", "name": "超快", "description": "最快的编码速度，文件较大"},
            {"id": "superfast", "name": "超快速", "description": "非常快的编码速度"},
            {"id": "veryfast", "name": "很快", "description": "很快的编码速度"},
            {"id": "faster", "name": "较快", "description": "较快的编码速度"},
            {"id": "fast", "name": "快", "description": "快速的编码速度"},
            {"id": "medium", "name": "中等", "description": "平衡的速度和质量"},
            {"id": "slow", "name": "慢", "description": "较慢的编码速度，更好的质量"},
            {"id": "slower", "name": "很慢", "description": "很慢的编码速度，更好的质量"},
            {"id": "veryslow", "name": "极慢", "description": "最慢的编码速度，最佳质量"}
        ]
    
    def get_supported_formats(self):
        """获取支持的视频格式"""
        return ["mp4", "mov", "avi", "wmv", "flv", "mkv", "webm"]