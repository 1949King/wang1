"""
滤镜链验证流水线
==================
支持单条滤镜参数测试→执行FFmpeg命令→对比输出帧→迭代参数的闭环调试流程。

核心能力：
1. 滤镜参数生成与验证
2. FFmpeg命令执行与日志捕获
3. 输出帧对比与质量评估
4. 参数迭代优化
5. 批量滤镜测试
"""
import os
import re
import subprocess
import json
import time
import threading
from typing import Dict, List, Optional, Any, Tuple, Callable

from .ffmpeg_debugger import FFmpegDebugger


class FilterParameterGenerator:
    """滤镜参数生成器"""
    
    FILTER_TEMPLATES = {
        "scale": {
            "description": "缩放滤镜",
            "parameters": [
                {"name": "width", "type": "int", "default": 1920, "min": 16, "max": 8192},
                {"name": "height", "type": "int", "default": 1080, "min": 16, "max": 8192},
                {"name": "flags", "type": "enum", "default": "lanczos", "options": ["lanczos", "bilinear", "bicubic", "area"]},
                {"name": "force_original_aspect_ratio", "type": "enum", "default": "decrease", "options": ["decrease", "increase", "disable"]},
            ],
        },
        "crop": {
            "description": "裁剪滤镜",
            "parameters": [
                {"name": "w", "type": "int", "default": 1920, "min": 1, "max": 8192},
                {"name": "h", "type": "int", "default": 1080, "min": 1, "max": 8192},
                {"name": "x", "type": "int", "default": 0, "min": 0, "max": 8192},
                {"name": "y", "type": "int", "default": 0, "min": 0, "max": 8192},
            ],
        },
        "overlay": {
            "description": "叠加滤镜",
            "parameters": [
                {"name": "x", "type": "int", "default": 0, "min": -8192, "max": 8192},
                {"name": "y", "type": "int", "default": 0, "min": -8192, "max": 8192},
                {"name": "shortest", "type": "bool", "default": False},
                {"name": "repeatlast", "type": "bool", "default": True},
            ],
        },
        "drawtext": {
            "description": "绘制文字",
            "parameters": [
                {"name": "text", "type": "str", "default": "Hello"},
                {"name": "fontfile", "type": "str", "default": ""},
                {"name": "fontsize", "type": "int", "default": 24, "min": 8, "max": 512},
                {"name": "fontcolor", "type": "str", "default": "white"},
                {"name": "x", "type": "str", "default": "(w-text_w)/2"},
                {"name": "y", "type": "str", "default": "(h-text_h)/2"},
                {"name": "shadowcolor", "type": "str", "default": "black"},
                {"name": "shadowx", "type": "int", "default": 2},
                {"name": "shadowy", "type": "int", "default": 2},
            ],
        },
        "blur": {
            "description": "模糊滤镜",
            "parameters": [
                {"name": "luma_radius", "type": "float", "default": 2.0, "min": 0.1, "max": 100.0},
                {"name": "luma_strength", "type": "float", "default": 2.0, "min": 0.1, "max": 100.0},
                {"name": "chroma_radius", "type": "float", "default": 2.0, "min": 0.1, "max": 100.0},
                {"name": "chroma_strength", "type": "float", "default": 2.0, "min": 0.1, "max": 100.0},
            ],
        },
        "eq": {
            "description": "亮度对比度滤镜",
            "parameters": [
                {"name": "contrast", "type": "float", "default": 1.0, "min": -2.0, "max": 2.0},
                {"name": "brightness", "type": "float", "default": 0.0, "min": -1.0, "max": 1.0},
                {"name": "gamma", "type": "float", "default": 1.0, "min": 0.1, "max": 3.0},
                {"name": "gamma_r", "type": "float", "default": 1.0, "min": 0.1, "max": 3.0},
                {"name": "gamma_g", "type": "float", "default": 1.0, "min": 0.1, "max": 3.0},
                {"name": "gamma_b", "type": "float", "default": 1.0, "min": 0.1, "max": 3.0},
            ],
        },
        "xfade": {
            "description": "转场滤镜",
            "parameters": [
                {"name": "transition", "type": "enum", "default": "fade", "options": ["fade", "slide", "dissolve", "wipeleft", "wiperight", "wipeup", "wipedown"]},
                {"name": "duration", "type": "float", "default": 1.0, "min": 0.1, "max": 10.0},
                {"name": "offset", "type": "float", "default": 0.0, "min": -10.0, "max": 10.0},
            ],
        },
        "fps": {
            "description": "帧率转换",
            "parameters": [
                {"name": "fps", "type": "float", "default": 30.0, "min": 1.0, "max": 120.0},
                {"name": "round", "type": "enum", "default": "near", "options": ["near", "zero", "inf", "down", "up"]},
            ],
        },
        "hue": {
            "description": "色相调整",
            "parameters": [
                {"name": "h", "type": "float", "default": 0.0, "min": -180.0, "max": 180.0},
                {"name": "s", "type": "float", "default": 1.0, "min": 0.0, "max": 3.0},
            ],
        },
        "volume": {
            "description": "音量调整",
            "parameters": [
                {"name": "volume", "type": "float", "default": 1.0, "min": 0.0, "max": 10.0},
                {"name": "precision", "type": "enum", "default": "fixed", "options": ["fixed", "float"]},
            ],
        },
        "amix": {
            "description": "音频混合",
            "parameters": [
                {"name": "inputs", "type": "int", "default": 2, "min": 2, "max": 16},
                {"name": "duration", "type": "enum", "default": "first", "options": ["first", "longest", "shortest", "max"]},
                {"name": "dropout_transition", "type": "float", "default": 3.0, "min": 0.0, "max": 10.0},
            ],
        },
    }
    
    @classmethod
    def generate_filter(cls, filter_name: str, **kwargs) -> str:
        """生成滤镜字符串"""
        template = cls.FILTER_TEMPLATES.get(filter_name)
        if not template:
            return filter_name
        
        params = []
        for param_info in template["parameters"]:
            name = param_info["name"]
            value = kwargs.get(name, param_info["default"])
            
            if param_info["type"] == "bool":
                params.append(f"{name}={1 if value else 0}")
            elif param_info["type"] == "enum":
                if value in param_info["options"]:
                    params.append(f"{name}={value}")
            else:
                params.append(f"{name}={value}")
        
        return f"{filter_name}={':'.join(params)}" if params else filter_name
    
    @classmethod
    def get_filter_info(cls, filter_name: str) -> Optional[Dict[str, Any]]:
        """获取滤镜信息"""
        return cls.FILTER_TEMPLATES.get(filter_name)
    
    @classmethod
    def list_filters(cls) -> List[str]:
        """列出所有支持的滤镜"""
        return list(cls.FILTER_TEMPLATES.keys())


class FFmpegCommandExecutor:
    """FFmpeg命令执行器"""
    
    def __init__(self, ffmpeg_path: str = None):
        self.ffmpeg_path = ffmpeg_path or self._find_ffmpeg()
        self.debugger = FFmpegDebugger()
        self._lock = threading.Lock()
    
    def _find_ffmpeg(self) -> str:
        """查找FFmpeg可执行文件"""
        candidates = [
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "thirdparty", "ffmpeg", "bin", "ffmpeg.exe"),
            "ffmpeg",
        ]
        
        for candidate in candidates:
            if os.path.exists(candidate):
                return candidate
        
        return "ffmpeg"
    
    def execute(self, command: List[str], capture_output: bool = True) -> Dict[str, Any]:
        """执行FFmpeg命令"""
        result = {
            "success": False,
            "command": command,
            "stdout": "",
            "stderr": "",
            "return_code": None,
            "duration": 0,
            "error_analysis": None,
        }
        
        start_time = time.time()
        
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE if capture_output else None,
                stderr=subprocess.PIPE if capture_output else None,
                text=True,
                encoding="utf-8",
                errors="ignore",
            )
            
            stdout, stderr = process.communicate(timeout=300)
            result["return_code"] = process.returncode
            result["stdout"] = stdout
            result["stderr"] = stderr
            
            if process.returncode == 0:
                result["success"] = True
            else:
                result["error_analysis"] = self.debugger.analyze_logs(
                    stderr.split("\n") if stderr else []
                )
            
        except subprocess.TimeoutExpired:
            result["stderr"] = "Command timed out"
            result["return_code"] = -1
        except Exception as e:
            result["stderr"] = str(e)
            result["return_code"] = -1
        
        result["duration"] = time.time() - start_time
        
        return result
    
    def test_filter(self, input_file: str, output_file: str, filters: List[str]) -> Dict[str, Any]:
        """测试滤镜链"""
        filter_str = ",".join(filters)
        command = [
            self.ffmpeg_path,
            "-y",
            "-i", input_file,
            "-vf", filter_str,
            "-c:a", "copy",
            output_file,
        ]
        
        result = self.execute(command)
        result["filters"] = filters
        result["filter_str"] = filter_str
        
        return result
    
    def extract_frame(self, input_file: str, output_file: str, time: str = "00:00:01") -> Dict[str, Any]:
        """提取帧"""
        command = [
            self.ffmpeg_path,
            "-y",
            "-i", input_file,
            "-ss", time,
            "-vframes", "1",
            "-q:v", "2",
            output_file,
        ]
        
        return self.execute(command)


class FilterQualityAnalyzer:
    """滤镜质量分析器"""
    
    def __init__(self):
        self.executor = FFmpegCommandExecutor()
    
    def compare_frames(self, frame1: str, frame2: str) -> Dict[str, Any]:
        """对比两帧"""
        command = [
            self.executor.ffmpeg_path,
            "-y",
            "-i", frame1,
            "-i", frame2,
            "-filter_complex", "[0:v][1:v]blend=difference",
            "-f", "null",
            "-",
        ]
        
        result = self.executor.execute(command)
        
        return {
            "success": result["success"],
            "method": "blend_difference",
            "command": result["command"],
        }
    
    def analyze_filter_impact(self, input_file: str, filters: List[str], reference_file: str = None) -> Dict[str, Any]:
        """分析滤镜对画质的影响"""
        temp_output = f"temp_filter_test_{int(time.time())}.mp4"
        temp_frame = f"temp_filter_test_{int(time.time())}.png"
        
        try:
            test_result = self.executor.test_filter(input_file, temp_output, filters)
            
            if not test_result["success"]:
                return {
                    "success": False,
                    "error": test_result.get("error_analysis"),
                }
            
            extract_result = self.executor.extract_frame(temp_output, temp_frame)
            
            if not extract_result["success"]:
                return {
                    "success": False,
                    "error": "Failed to extract frame",
                }
            
            return {
                "success": True,
                "filters": filters,
                "duration": test_result["duration"],
                "output_file": temp_output,
                "frame_file": temp_frame,
                "analysis": "Frame extracted successfully",
            }
        
        finally:
            if os.path.exists(temp_output):
                os.remove(temp_output)
            if os.path.exists(temp_frame):
                os.remove(temp_frame)


class FilterValidationPipeline:
    """滤镜验证流水线"""
    
    def __init__(self, ffmpeg_path: str = None):
        self.generator = FilterParameterGenerator()
        self.executor = FFmpegCommandExecutor(ffmpeg_path)
        self.analyzer = FilterQualityAnalyzer()
        self.debugger = FFmpegDebugger()
        self.results = []
    
    def validate_single_filter(self, input_file: str, filter_name: str, **kwargs) -> Dict[str, Any]:
        """验证单个滤镜"""
        filter_str = self.generator.generate_filter(filter_name, **kwargs)
        
        temp_output = f"temp_{filter_name}_{int(time.time())}.mp4"
        
        try:
            result = self.executor.test_filter(input_file, temp_output, [filter_str])
            
            validation = {
                "filter": filter_name,
                "parameters": kwargs,
                "filter_str": filter_str,
                "success": result["success"],
                "duration": result["duration"],
                "error_analysis": result.get("error_analysis"),
            }
            
            self.results.append(validation)
            
            return validation
        
        finally:
            if os.path.exists(temp_output):
                os.remove(temp_output)
    
    def validate_filter_chain(self, input_file: str, filters: List[str], params_list: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """验证滤镜链"""
        generated_filters = []
        
        for i, filter_name in enumerate(filters):
            if params_list and i < len(params_list):
                generated = self.generator.generate_filter(filter_name, **params_list[i])
            else:
                generated = self.generator.generate_filter(filter_name)
            generated_filters.append(generated)
        
        temp_output = f"temp_filter_chain_{int(time.time())}.mp4"
        
        try:
            result = self.executor.test_filter(input_file, temp_output, generated_filters)
            
            validation = {
                "filters": filters,
                "generated_filters": generated_filters,
                "params_list": params_list,
                "success": result["success"],
                "duration": result["duration"],
                "error_analysis": result.get("error_analysis"),
                "filter_validation": self.debugger.validate_filter_chain(generated_filters),
            }
            
            self.results.append(validation)
            
            return validation
        
        finally:
            if os.path.exists(temp_output):
                os.remove(temp_output)
    
    def iterate_parameters(self, input_file: str, filter_name: str, param_name: str, values: List[Any]) -> List[Dict[str, Any]]:
        """迭代参数测试"""
        results = []
        
        for value in values:
            result = self.validate_single_filter(input_file, filter_name, **{param_name: value})
            result["param_name"] = param_name
            result["param_value"] = value
            results.append(result)
        
        return results
    
    def batch_test_filters(self, input_file: str, filter_names: List[str]) -> List[Dict[str, Any]]:
        """批量测试滤镜"""
        results = []
        
        for filter_name in filter_names:
            result = self.validate_single_filter(input_file, filter_name)
            results.append(result)
        
        return results
    
    def get_results_summary(self) -> Dict[str, Any]:
        """获取结果摘要"""
        successes = [r for r in self.results if r.get("success")]
        failures = [r for r in self.results if not r.get("success")]
        
        return {
            "total_tests": len(self.results),
            "success_rate": len(successes) / len(self.results) if self.results else 0,
            "successes": len(successes),
            "failures": len(failures),
            "results": self.results,
        }


filter_pipeline = FilterValidationPipeline()