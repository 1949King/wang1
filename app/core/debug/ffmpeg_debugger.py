"""
FFmpeg调试中间件
================
封装av_err错误码解析、滤镜链日志捕获、硬件编码器状态监控，
输出结构化调试信息，弥补国产AI工具无法解析程序内嵌FFmpeg异常的短板。

核心能力：
1. av_err错误码转人类可读描述
2. 滤镜链执行日志捕获与分析
3. 硬件编码器状态监控
4. 实时日志解析与问题定位
5. FFmpeg命令构建验证
"""
import os
import re
import subprocess
import threading
import queue
import logging
import json
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime

logger = logging.getLogger("AI短剧编辑器.ffmpeg_debugger")


class FFmpegErrorParser:
    """FFmpeg错误码解析器"""
    
    AV_ERROR_MAP = {
        -1: "AVERROR_UNKNOWN",
        -2: "AVERROR_INVALIDDATA",
        -3: "AVERROR_NOMEM",
        -4: "AVERROR_INVALIDARG",
        -5: "AVERROR_NOTFOUND",
        -6: "AVERROR_EXIT",
        -7: "AVERROR_EAGAIN",
        -8: "AVERROR_ENOSYS",
        -9: "AVERROR_ENOENT",
        -10: "AVERROR_ENOMEM",
        -11: "AVERROR_EINVAL",
        -12: "AVERROR_EOF",
        -13: "AVERROR_PATCHWELCOME",
        -14: "AVERROR_BSF_NOT_FOUND",
        -15: "AVERROR_DECODER_NOT_FOUND",
        -16: "AVERROR_ENCODER_NOT_FOUND",
        -17: "AVERROR_FILTER_NOT_FOUND",
        -18: "AVERROR_MUXER_NOT_FOUND",
        -19: "AVERROR_DEMUXER_NOT_FOUND",
        -20: "AVERROR_PROTOCOL_NOT_FOUND",
        -21: "AVERROR_STREAM_NOT_FOUND",
        -22: "AVERROR_CHANNEL_NOT_FOUND",
        -23: "AVERROR_SAMPLE_FMT_NOT_FOUND",
        -24: "AVERROR_BUG",
        -25: "AVERROR_BUFFER_TOO_SMALL",
        -26: "AVERROR_OPTION_NOT_FOUND",
        -27: "AVERROR_PARAM_CHANGED",
        -28: "AVERROR_INVALIDCHANNELS",
        -29: "AVERROR_INVALID_SAMPLE_RATE",
        -30: "AVERROR_INVALID_BIT_RATE",
        -31: "AVERROR_INVALID_CODEC",
        -32: "AVERROR_INVALID_PIX_FMT",
        -33: "AVERROR_INVALID_DATA",
        -34: "AVERROR_NOPROTOOPT",
        -35: "AVERROR_NOFILTER_PARAM",
        -36: "AVERROR_NOMATCH",
        -37: "AVERROR_NOTSUPP",
        -38: "AVERROR_NOCONFIG",
        -39: "AVERROR_INVALID_DEVICE",
        -40: "AVERROR_OUT_OF_RANGE",
        -100: "AVERROR_IO",
        -101: "AVERROR_NUMEXPECTED",
        -102: "AVERROR_INVALID",
        -103: "AVERROR_BUG2",
        -104: "AVERROR_MEMORY",
        -105: "AVERROR_INTERNAL",
        -106: "AVERROR_UNKNOWN",
    }
    
    FFMPEG_ERROR_PATTERNS = {
        r"Invalid argument": "参数无效",
        r"No such file or directory": "文件或目录不存在",
        r"Permission denied": "权限被拒绝",
        r"Could not find codec": "找不到编码器",
        r"Could not find decoder": "找不到解码器",
        r"Invalid codec": "无效编码器",
        r"Invalid bit rate": "无效比特率",
        r"Invalid sample rate": "无效采样率",
        r"Invalid frame rate": "无效帧率",
        r"Invalid resolution": "无效分辨率",
        r"Hardware acceleration not available": "硬件加速不可用",
        r"NVENC not available": "NVENC不可用",
        r"QSV not available": "QSV不可用",
        r"Failed to initialize": "初始化失败",
        r"Buffer too small": "缓冲区太小",
        r"Memory allocation failed": "内存分配失败",
        r"Filter not found": "滤镜未找到",
        r"Option not found": "选项未找到",
        r"Invalid filtergraph": "无效滤镜图",
        r"Invalid argument for filter": "滤镜参数无效",
        r"Overload": "过载",
        r"Timestamps are unset": "时间戳未设置",
        r"Frame rate differs": "帧率不一致",
        r"Sample format differs": "采样格式不一致",
        r"Channel layout differs": "声道布局不一致",
        r"Duration differs": "时长不一致",
        r"No such stream": "不存在该流",
        r"Cannot allocate memory": "无法分配内存",
        r"Connection refused": "连接被拒绝",
        r"Operation timed out": "操作超时",
        r"Broken pipe": "管道破裂",
        r"Resource temporarily unavailable": "资源暂时不可用",
    }
    
    @classmethod
    def parse_av_error(cls, error_code: int) -> Dict[str, Any]:
        """解析av_err错误码"""
        error_name = cls.AV_ERROR_MAP.get(error_code, f"AVERROR_UNKNOWN({error_code})")
        return {
            "code": error_code,
            "name": error_name,
            "description": cls._get_error_description(error_code),
            "severity": cls._get_error_severity(error_code),
        }
    
    @classmethod
    def _get_error_description(cls, error_code: int) -> str:
        """获取错误描述"""
        descriptions = {
            -1: "未知错误",
            -2: "无效数据",
            -3: "内存不足",
            -4: "无效参数",
            -5: "未找到",
            -6: "退出",
            -7: "资源暂时不可用",
            -8: "功能未实现",
            -9: "文件不存在",
            -10: "内存不足",
            -11: "无效参数",
            -12: "文件结束",
            -13: "补丁欢迎",
            -14: "比特流过滤器未找到",
            -15: "解码器未找到",
            -16: "编码器未找到",
            -17: "滤镜未找到",
            -18: "复用器未找到",
            -19: "解复用器未找到",
            -20: "协议未找到",
            -21: "流未找到",
            -22: "通道未找到",
            -23: "采样格式未找到",
            -24: "程序错误",
            -25: "缓冲区太小",
            -26: "选项未找到",
            -27: "参数已更改",
            -28: "无效通道数",
            -29: "无效采样率",
            -30: "无效比特率",
            -31: "无效编码器",
            -32: "无效像素格式",
            -33: "无效数据",
            -34: "协议选项不存在",
            -35: "滤镜参数不存在",
            -36: "不匹配",
            -37: "不支持",
            -38: "无配置",
            -39: "无效设备",
            -40: "超出范围",
            -100: "IO错误",
            -101: "数值异常",
            -102: "无效数据",
            -103: "程序错误",
            -104: "内存错误",
            -105: "内部错误",
            -106: "未知错误",
        }
        return descriptions.get(error_code, "未知错误")
    
    @classmethod
    def _get_error_severity(cls, error_code: int) -> str:
        """获取错误严重程度"""
        if error_code in [-3, -10, -104]:
            return "CRITICAL"
        if error_code in [-1, -2, -4, -5, -15, -16, -17, -24, -25, -31, -32, -102, -103, -105]:
            return "ERROR"
        if error_code in [-7, -8, -9, -12, -14, -18, -19, -20, -21, -22, -23, -26, -27, -28, -29, -30, -33, -34, -35, -36, -37, -38, -39, -40, -100, -101]:
            return "WARNING"
        return "INFO"
    
    @classmethod
    def parse_log_line(cls, log_line: str) -> Dict[str, Any]:
        """解析FFmpeg日志行"""
        log_line = log_line.strip()
        
        for pattern, description in cls.FFMPEG_ERROR_PATTERNS.items():
            if re.search(pattern, log_line, re.IGNORECASE):
                return {
                    "level": "ERROR",
                    "pattern": pattern,
                    "description": description,
                    "raw": log_line,
                    "suggestion": cls._get_suggestion(pattern),
                }
        
        if "warning" in log_line.lower():
            return {
                "level": "WARNING",
                "pattern": "warning",
                "description": "警告信息",
                "raw": log_line,
                "suggestion": "检查相关参数配置",
            }
        
        if "info" in log_line.lower():
            return {
                "level": "INFO",
                "pattern": "info",
                "description": "信息日志",
                "raw": log_line,
                "suggestion": None,
            }
        
        return {
            "level": "UNKNOWN",
            "pattern": None,
            "description": "未知日志",
            "raw": log_line,
            "suggestion": None,
        }
    
    @classmethod
    def _get_suggestion(cls, pattern: str) -> Optional[str]:
        """获取修复建议"""
        suggestions = {
            r"Invalid argument": "检查参数值是否在有效范围内",
            r"No such file or directory": "确认文件路径是否正确",
            r"Permission denied": "检查文件读写权限",
            r"Could not find codec": "确认编码器是否已编译进FFmpeg",
            r"Hardware acceleration not available": "检查显卡驱动是否安装正确，尝试回退到软件编码",
            r"NVENC not available": "确认NVIDIA显卡驱动版本，检查CUDA Toolkit安装",
            r"QSV not available": "确认Intel显卡驱动版本，检查Media SDK安装",
            r"Filter not found": "确认滤镜名称拼写正确，检查FFmpeg编译选项",
            r"Invalid filtergraph": "检查滤镜链语法，确保所有滤镜参数正确",
            r"Memory allocation failed": "减少同时处理的视频数量，增加系统内存",
            r"Buffer too small": "增加缓冲区大小",
            r"Timestamps are unset": "检查时间戳生成逻辑，确保正确设置PTS/DTS",
            r"Frame rate differs": "统一所有输入视频的帧率",
            r"Sample format differs": "统一所有输入音频的采样格式",
            r"Channel layout differs": "统一所有输入音频的声道数",
            r"Overload": "降低编码码率，减少并发任务数",
        }
        for pat, suggestion in suggestions.items():
            if re.search(pat, pattern):
                return suggestion
        return None


class FilterChainValidator:
    """滤镜链验证器"""
    
    FILTER_COMPATIBILITY = {
        "scale": ["crop", "pad", "transpose", "rotate", "vflip", "hflip"],
        "crop": ["scale", "pad", "overlay", "drawtext"],
        "overlay": ["drawtext", "scale", "crop", "blend"],
        "drawtext": ["overlay", "scale", "fps"],
        "blur": ["scale", "overlay", "eq"],
        "eq": ["blur", "hue", "saturation"],
        "xfade": ["scale", "fps"],
        "concat": ["xfade", "scale"],
        "amix": ["volume", "aresample"],
        "volume": ["amix", "aresample"],
        "aresample": ["amix", "volume"],
    }
    
    HARDWARE_INCOMPATIBLE_FILTERS = [
        "subtitles", "ass", "webvtt",
        "deinterlace_vaapi", "scale_vaapi",
        "hwdownload", "hwupload",
    ]
    
    @classmethod
    def validate_filter_chain(cls, filters: List[str]) -> Dict[str, Any]:
        """验证滤镜链"""
        issues = []
        warnings = []
        
        for i, filter_name in enumerate(filters):
            clean_name = cls._extract_filter_name(filter_name)
            
            if clean_name in cls.HARDWARE_INCOMPATIBLE_FILTERS:
                warnings.append({
                    "filter": filter_name,
                    "issue": f"滤镜'{clean_name}'可能与硬件加速不兼容",
                    "suggestion": "考虑使用软件编码或替代滤镜",
                })
            
            if i > 0:
                prev_filter = cls._extract_filter_name(filters[i-1])
                if prev_filter in cls.FILTER_COMPATIBILITY:
                    if clean_name not in cls.FILTER_COMPATIBILITY[prev_filter]:
                        issues.append({
                            "position": f"{i-1}→{i}",
                            "filters": f"{prev_filter} → {clean_name}",
                            "issue": "滤镜顺序可能导致性能问题或兼容性问题",
                            "suggestion": f"建议调整顺序或在中间添加兼容滤镜",
                        })
        
        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "warnings": warnings,
            "total_filters": len(filters),
            "analysis": cls._analyze_filter_chain(filters),
        }
    
    @classmethod
    def _extract_filter_name(cls, filter_str: str) -> str:
        """从滤镜字符串中提取滤镜名"""
        match = re.match(r'^([a-zA-Z_][a-zA-Z0-9_]*)', filter_str)
        return match.group(1) if match else ""
    
    @classmethod
    def _analyze_filter_chain(cls, filters: List[str]) -> Dict[str, Any]:
        """分析滤镜链"""
        video_filters = []
        audio_filters = []
        complex_filters = []
        
        for filter_str in filters:
            name = cls._extract_filter_name(filter_str)
            if name in ["scale", "crop", "pad", "overlay", "drawtext", "blur", "eq", "hue", "xfade", "transpose", "rotate", "vflip", "hflip", "fps"]:
                video_filters.append(name)
            elif name in ["amix", "volume", "aresample", "acopy", "aformat"]:
                audio_filters.append(name)
            else:
                complex_filters.append(name)
        
        return {
            "video_filters": video_filters,
            "audio_filters": audio_filters,
            "complex_filters": complex_filters,
            "has_video": len(video_filters) > 0,
            "has_audio": len(audio_filters) > 0,
            "has_complex": len(complex_filters) > 0,
        }


class HardwareEncoderMonitor:
    """硬件编码器监控器"""
    
    ENCODER_CAPABILITIES = {
        "nvidia": {
            "encoders": ["h264_nvenc", "hevc_nvenc"],
            "max_resolution": (8192, 8192),
            "max_fps": 60,
            "supported_formats": ["yuv420p", "yuv444p", "nv12"],
        },
        "intel": {
            "encoders": ["h264_qsv", "hevc_qsv", "vp9_qsv"],
            "max_resolution": (4096, 4096),
            "max_fps": 60,
            "supported_formats": ["yuv420p", "nv12", "p010le"],
        },
        "amd": {
            "encoders": ["h264_amf", "hevc_amf"],
            "max_resolution": (4096, 4096),
            "max_fps": 60,
            "supported_formats": ["yuv420p", "nv12"],
        },
    }
    
    def __init__(self):
        self.encoder_status = {}
        self.encoder_errors = []
        self._lock = threading.Lock()
    
    def monitor_encoder(self, encoder_type: str, resolution: Tuple[int, int], fps: float) -> Dict[str, Any]:
        """监控编码器状态"""
        caps = self.ENCODER_CAPABILITIES.get(encoder_type.lower())
        if not caps:
            return {
                "valid": False,
                "error": f"未知编码器类型: {encoder_type}",
            }
        
        width, height = resolution
        
        issues = []
        if width > caps["max_resolution"][0] or height > caps["max_resolution"][1]:
            issues.append({
                "type": "resolution",
                "issue": f"分辨率{width}x{height}超过{encoder_type}最大支持{caps['max_resolution'][0]}x{caps['max_resolution'][1]}",
                "suggestion": f"降低分辨率或使用{caps['max_resolution'][0]}x{caps['max_resolution'][1]}以下",
            })
        
        if fps > caps["max_fps"]:
            issues.append({
                "type": "fps",
                "issue": f"帧率{fps}超过{encoder_type}最大支持{caps['max_fps']}fps",
                "suggestion": f"降低帧率至{caps['max_fps']}fps以下",
            })
        
        with self._lock:
            self.encoder_status[encoder_type] = {
                "valid": len(issues) == 0,
                "issues": issues,
                "capabilities": caps,
                "current_config": {
                    "resolution": resolution,
                    "fps": fps,
                },
                "timestamp": datetime.now().isoformat(),
            }
        
        return self.encoder_status[encoder_type]
    
    def get_encoder_status(self, encoder_type: str = None) -> Dict[str, Any]:
        """获取编码器状态"""
        with self._lock:
            if encoder_type:
                return self.encoder_status.get(encoder_type, {})
            return dict(self.encoder_status)
    
    def add_error(self, encoder_type: str, error: str):
        """添加编码器错误"""
        with self._lock:
            self.encoder_errors.append({
                "encoder": encoder_type,
                "error": error,
                "timestamp": datetime.now().isoformat(),
            })
    
    def get_errors(self) -> List[Dict[str, Any]]:
        """获取编码器错误列表"""
        with self._lock:
            return list(self.encoder_errors)


class FFmpegCommandBuilder:
    """FFmpeg命令构建器"""
    
    VALID_CODECS = {
        "video": ["h264", "hevc", "vp9", "av1", "mpeg4", "wmv2"],
        "audio": ["aac", "mp3", "opus", "vorbis", "wavpack", "flac"],
    }
    
    VALID_CONTAINERS = ["mp4", "mov", "avi", "mkv", "webm", "flv", "mpg", "wmv"]
    
    VALID_PIX_FMTS = ["yuv420p", "yuv444p", "nv12", "p010le", "yuv422p"]
    
    def __init__(self):
        self.command = ["ffmpeg"]
        self.inputs = []
        self.outputs = []
        self.global_options = []
        self.input_options = {}
        self.output_options = {}
        self.filter_complex = None
    
    def add_input(self, file_path: str, options: Optional[Dict[str, Any]] = None):
        """添加输入文件"""
        self.inputs.append({"path": file_path, "options": options or {}})
    
    def add_output(self, file_path: str, options: Optional[Dict[str, Any]] = None):
        """添加输出文件"""
        self.outputs.append({"path": file_path, "options": options or {}})
    
    def set_filter_complex(self, filter_graph: str):
        """设置滤镜图"""
        self.filter_complex = filter_graph
    
    def add_global_option(self, key: str, value: Any = None):
        """添加全局选项"""
        if value is None:
            self.global_options.append(f"-{key}")
        else:
            self.global_options.append(f"-{key}")
            self.global_options.append(str(value))
    
    def build(self) -> Tuple[bool, str, List[str]]:
        """构建FFmpeg命令"""
        cmd = ["ffmpeg"]
        
        for opt in self.global_options:
            cmd.append(opt)
        
        for inp in self.inputs:
            if inp["options"]:
                for key, value in inp["options"].items():
                    cmd.append(f"-{key}")
                    cmd.append(str(value))
            cmd.append("-i")
            cmd.append(inp["path"])
        
        if self.filter_complex:
            cmd.append("-filter_complex")
            cmd.append(self.filter_complex)
        
        for out in self.outputs:
            if out["options"]:
                for key, value in out["options"].items():
                    cmd.append(f"-{key}")
                    cmd.append(str(value))
            cmd.append(out["path"])
        
        validation = self._validate_command()
        
        return validation["valid"], validation["message"], cmd
    
    def _validate_command(self) -> Dict[str, Any]:
        """验证命令"""
        issues = []
        
        if not self.inputs:
            issues.append("缺少输入文件")
        
        if not self.outputs:
            issues.append("缺少输出文件")
        
        for inp in self.inputs:
            if not os.path.exists(inp["path"]):
                issues.append(f"输入文件不存在: {inp['path']}")
        
        for out in self.outputs:
            dir_path = os.path.dirname(out["path"])
            if dir_path and not os.path.exists(dir_path):
                issues.append(f"输出目录不存在: {dir_path}")
            
            options = out["options"]
            if "c:v" in options:
                codec = options["c:v"]
                if codec not in self.VALID_CODECS["video"] and not codec.endswith("_nvenc") and not codec.endswith("_qsv") and not codec.endswith("_amf"):
                    issues.append(f"未知视频编码器: {codec}")
            
            if "pix_fmt" in options:
                pix_fmt = options["pix_fmt"]
                if pix_fmt not in self.VALID_PIX_FMTS:
                    issues.append(f"未知像素格式: {pix_fmt}")
        
        return {
            "valid": len(issues) == 0,
            "message": "命令有效" if len(issues) == 0 else "; ".join(issues),
            "issues": issues,
        }


class FFmpegDebugger:
    """FFmpeg调试器主类"""
    
    def __init__(self):
        self.error_parser = FFmpegErrorParser()
        self.filter_validator = FilterChainValidator()
        self.hw_monitor = HardwareEncoderMonitor()
        self.command_builder = FFmpegCommandBuilder()
        self.log_queue = queue.Queue()
        self.log_thread = None
        self._log_running = False
        self.debug_info = {}
    
    def start_log_monitoring(self):
        """开始日志监控"""
        if self._log_running:
            return
        
        self._log_running = True
        self.log_thread = threading.Thread(target=self._log_processor, daemon=True)
        self.log_thread.start()
    
    def stop_log_monitoring(self):
        """停止日志监控"""
        self._log_running = False
    
    def _log_processor(self):
        """日志处理线程"""
        while self._log_running:
            try:
                log_entry = self.log_queue.get(timeout=1)
                self._process_log_entry(log_entry)
            except queue.Empty:
                continue
    
    def _process_log_entry(self, log_entry: Dict[str, Any]):
        """处理日志条目"""
        parsed = self.error_parser.parse_log_line(log_entry.get("message", ""))
        log_entry["parsed"] = parsed
        
        if parsed["level"] == "ERROR":
            self.debug_info.setdefault("errors", []).append(log_entry)
        elif parsed["level"] == "WARNING":
            self.debug_info.setdefault("warnings", []).append(log_entry)
    
    def log(self, message: str, source: str = "unknown", level: str = "INFO"):
        """记录日志"""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "message": message,
            "source": source,
            "level": level,
        }
        self.log_queue.put(entry)
        logger.log(getattr(logging, level.upper(), logging.INFO), message)
    
    def analyze_logs(self, logs: List[str]) -> Dict[str, Any]:
        """分析日志列表"""
        results = {
            "errors": [],
            "warnings": [],
            "info": [],
            "suggestions": [],
        }
        
        for log_line in logs:
            parsed = self.error_parser.parse_log_line(log_line)
            if parsed["level"] == "ERROR":
                results["errors"].append(parsed)
                if parsed["suggestion"]:
                    results["suggestions"].append(parsed["suggestion"])
            elif parsed["level"] == "WARNING":
                results["warnings"].append(parsed)
            else:
                results["info"].append(parsed)
        
        return results
    
    def validate_filter_chain(self, filters: List[str]) -> Dict[str, Any]:
        """验证滤镜链"""
        return self.filter_validator.validate_filter_chain(filters)
    
    def validate_command(self, command: List[str]) -> Dict[str, Any]:
        """验证FFmpeg命令"""
        self.command_builder = FFmpegCommandBuilder()
        
        i = 0
        while i < len(command):
            if command[i] == "-i":
                i += 1
                if i < len(command):
                    self.command_builder.add_input(command[i])
                    i += 1
                    continue
            elif command[i].startswith("-"):
                key = command[i][1:]
                i += 1
                value = None
                if i < len(command) and not command[i].startswith("-"):
                    value = command[i]
                    i += 1
                if key in ["i", "y"]:
                    continue
                self.command_builder.add_global_option(key, value)
            else:
                self.command_builder.add_output(command[i])
                i += 1
        
        valid, message, _ = self.command_builder.build()
        return {
            "valid": valid,
            "message": message,
            "inputs": len(self.command_builder.inputs),
            "outputs": len(self.command_builder.outputs),
        }
    
    def analyze_hardware(self, gpu_info: Dict[str, Any]) -> Dict[str, Any]:
        """分析硬件编码器"""
        gpu_type = gpu_info.get("gpu_type", "").lower()
        return self.hw_monitor.monitor_encoder(
            gpu_type,
            gpu_info.get("resolution", (1920, 1080)),
            gpu_info.get("fps", 30.0),
        )
    
    def get_debug_report(self) -> Dict[str, Any]:
        """获取调试报告"""
        return {
            "timestamp": datetime.now().isoformat(),
            "encoder_status": self.hw_monitor.get_encoder_status(),
            "encoder_errors": self.hw_monitor.get_errors(),
            "debug_info": self.debug_info,
        }
    
    def save_report(self, file_path: str):
        """保存调试报告"""
        report = self.get_debug_report()
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)


ffmpeg_debugger = FFmpegDebugger()