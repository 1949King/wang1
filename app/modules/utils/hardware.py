import platform
import subprocess
import logging

logger = logging.getLogger(__name__)

# ===================== 硬件检测与自动适配 =====================
def detect_hardware():
    """检测硬件配置并返回适配参数"""
    try:
        # 延迟导入psutil
        import psutil
        
        # 获取CPU核心数
        cpu_count = psutil.cpu_count(logical=True)
        
        # 获取可用内存（GB）
        memory = psutil.virtual_memory()
        available_memory_gb = memory.available / (1024 ** 3)
        
        # 获取系统信息
        system = platform.system()
        
        # 根据硬件配置调整参数
        if available_memory_gb < 4:
            # 低配置系统
            max_threads = max(1, cpu_count // 2)
            max_batch_size = 2
            cache_size = 512
        elif available_memory_gb < 8:
            # 中等配置系统
            max_threads = cpu_count
            max_batch_size = 5
            cache_size = 1024
        else:
            # 高配置系统
            max_threads = min(cpu_count * 2, 32)
            max_batch_size = 10
            cache_size = 2048
        
        return {
            "cpu_count": cpu_count,
            "available_memory_gb": round(available_memory_gb, 2),
            "system": system,
            "max_threads": max_threads,
            "max_batch_size": max_batch_size,
            "cache_size": cache_size
        }
    except Exception as e:
        logger.warning(f"硬件检测失败: {e}")
        # 返回默认值
        return {
            "cpu_count": 4,
            "available_memory_gb": 4,
            "system": platform.system(),
            "max_threads": 4,
            "max_batch_size": 3,
            "cache_size": 512
        }


# ===================== GPU 编码器自动检测 =====================
def _check_gpu_encoder(ffmpeg_executable, encoder_name):
    """安全检测GPU编码器（用两个进程pipe连接，避免shell=True命令注入）"""
    try:
        p1 = subprocess.Popen(
            [ffmpeg_executable, "-encoders"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        p2 = subprocess.Popen(
            ["findstr", encoder_name],
            stdin=p1.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        p1.stdout.close()
        p2.communicate()
        return p2.returncode == 0
    except Exception as e:
        logger.debug(f"检测{encoder_name}失败: {e}")
        return False


def detect_gpu_encoder(ffmpeg_executable="ffmpeg.exe"):
    """检测系统可用的GPU编码器"""
    # 验证可执行文件名安全性
    if not ffmpeg_executable or not ffmpeg_executable.replace('.', '').replace('_', '').replace('-', '').isalnum():
        ffmpeg_executable = "ffmpeg.exe"
    
    if _check_gpu_encoder(ffmpeg_executable, "h264_nvenc"):
        return "h264_nvenc"
    
    if _check_gpu_encoder(ffmpeg_executable, "h264_amf"):
        return "h264_amf"
    
    if _check_gpu_encoder(ffmpeg_executable, "h264_qsv"):
        return "h264_qsv"
    
    return "libx264"
