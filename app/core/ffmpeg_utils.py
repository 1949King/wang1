"""
FFmpeg 路径检测工具模块
=====================
集中管理 FFmpeg 可执行文件的查找与验证，供所有模块统一使用。

能力：
  - 多级路径查找（环境变量 → 项目内置 → 系统 PATH）
  - drawtext/libfreetype 能力验证
  - 硬件编码器检测（NVENC/QSV/AMF）
  - ffprobe 同步检测
"""

import os
import sys
import subprocess
import logging
from typing import Optional, List, Dict, Tuple

logger = logging.getLogger("AI短剧编辑器.ffmpeg_utils")

_ffmpeg_cache: Optional[str] = None
_ffprobe_cache: Optional[str] = None
_hw_encoder_cache: Dict[str, str] = {}
_cache_initialized = False


def find_ffmpeg() -> Optional[str]:
    """
    查找可用的 ffmpeg.exe，返回绝对路径。

    查找优先级：
      1. 环境变量 AI_EDITOR_FFMPEG_DIR / FFMPEG_PATH
      2. 项目内置 thirdparty/ffmpeg/bin/
      3. 系统 PATH
    """
    global _ffmpeg_cache
    if _ffmpeg_cache and os.path.isfile(_ffmpeg_cache):
        return _ffmpeg_cache

    candidates: List[str] = []

    # 1. 环境变量
    for env_var in ("AI_EDITOR_FFMPEG_DIR", "FFMPEG_PATH"):
        env_val = os.environ.get(env_var, "").strip()
        if env_val:
            if os.path.isfile(env_val) and "ffmpeg" in os.path.basename(env_val).lower():
                candidates.append(env_val)
            elif os.path.isdir(env_val):
                exe = os.path.join(env_val, "ffmpeg.exe")
                if os.path.isfile(exe):
                    candidates.append(exe)

    # 2. 项目内置（支持从 app/core/ 和 app/ 目录调用）
    # PyInstaller 打包后，资源解压在 sys._MEIPASS 下，优先从这里找
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        for relative in (
            "thirdparty/ffmpeg/bin/ffmpeg.exe",
            "thirdparty/ffmpeg/ffmpeg.exe",
        ):
            builtin = os.path.normpath(os.path.join(meipass, relative))
            if os.path.isfile(builtin):
                candidates.append(builtin)

    here = os.path.dirname(os.path.abspath(__file__))
    # 尝试从 app/core/ 向上两层到项目根目录
    project_root = os.path.normpath(os.path.join(here, "..", ".."))
    for relative in (
        "thirdparty/ffmpeg/bin/ffmpeg.exe",
        "thirdparty/ffmpeg/ffmpeg.exe",
    ):
        builtin = os.path.normpath(os.path.join(project_root, relative))
        if os.path.isfile(builtin):
            candidates.append(builtin)
    
    # 如果没找到，尝试向上一层（从 app/ 目录）
    if not any(os.path.isfile(c) for c in candidates):
        project_root = os.path.normpath(os.path.join(here, ".."))
        for relative in (
            "thirdparty/ffmpeg/bin/ffmpeg.exe",
            "thirdparty/ffmpeg/ffmpeg.exe",
        ):
            builtin = os.path.normpath(os.path.join(project_root, relative))
            if os.path.isfile(builtin):
                candidates.append(builtin)

    # 3. 系统 PATH
    for d in os.environ.get("PATH", "").split(os.pathsep):
        exe = os.path.join(d.strip(), "ffmpeg.exe")
        if os.path.isfile(exe):
            candidates.append(exe)

    # 选第一个存在的
    seen = set()
    for p in candidates:
        p_abs = os.path.abspath(p)
        if p_abs in seen:
            continue
        seen.add(p_abs)
        if os.path.isfile(p_abs):
            _ffmpeg_cache = p_abs
            logger.info(f"FFmpeg 路径: {p_abs}")
            return p_abs

    return None


def find_ffprobe() -> Optional[str]:
    """查找 ffprobe.exe"""
    global _ffprobe_cache
    if _ffprobe_cache and os.path.isfile(_ffprobe_cache):
        return _ffprobe_cache

    ffmpeg_path = find_ffmpeg()
    if ffmpeg_path:
        ffmpeg_dir = os.path.dirname(ffmpeg_path)
        probe = os.path.join(ffmpeg_dir, "ffprobe.exe")
        if os.path.isfile(probe):
            _ffprobe_cache = probe
            return probe

    # PATH 回退
    for d in os.environ.get("PATH", "").split(os.pathsep):
        exe = os.path.join(d.strip(), "ffprobe.exe")
        if os.path.isfile(exe):
            _ffprobe_cache = os.path.abspath(exe)
            return _ffprobe_cache

    return None


def has_drawtext_support(ffmpeg_path: str = None) -> bool:
    """检查 FFmpeg 是否支持 drawtext 滤镜（需要 libfreetype）"""
    path = ffmpeg_path or find_ffmpeg()
    if not path:
        return False
    try:
        r = subprocess.run(
            [path, "-hide_banner", "-filters"],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        return "drawtext" in (r.stdout or "")
    except Exception:
        return False


def detect_hardware_encoders(ffmpeg_path: str = None) -> Dict[str, str]:
    """
    检测可用的硬件编码器。

    Returns:
        {"h264": "h264_nvenc", "h265": "hevc_nvenc"} 或空
    """
    global _hw_encoder_cache
    if _hw_encoder_cache:
        return _hw_encoder_cache.copy()

    path = ffmpeg_path or find_ffmpeg()
    if not path:
        return {}

    try:
        r = subprocess.run(
            [path, "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        out = (r.stdout + r.stderr).lower()

        result: Dict[str, str] = {}

        # H.264
        if "h264_nvenc" in out:
            result["h264"] = "h264_nvenc"
            result["vendor"] = "nvidia"
        elif "h264_qsv" in out:
            result["h264"] = "h264_qsv"
            result["vendor"] = "intel"
        elif "h264_amf" in out:
            result["h264"] = "h264_amf"
            result["vendor"] = "amd"

        # H.265
        if "hevc_nvenc" in out:
            result["h265"] = "hevc_nvenc"
        elif "hevc_qsv" in out:
            result["h265"] = "hevc_qsv"
        elif "hevc_amf" in out:
            result["h265"] = "hevc_amf"

        _hw_encoder_cache = result.copy()
        logger.info(f"硬件编码器检测: {result}")
        return result
    except Exception as e:
        logger.debug(f"硬件编码器检测失败: {e}")
        return {}


def ensure_ffmpeg_path() -> str:
    """
    保证 PATH 中最前的 ffmpeg 是项目内置的（带 libfreetype）。

    当 MLT Shotcut 目录被提前插入 PATH 后，系统可能拿到不带 drawtext
    的 ffmpeg.exe。本方法把项目内置 ffmpeg 目录重新置顶。
    """
    ffmpeg_exe = find_ffmpeg()
    if not ffmpeg_exe:
        return "ffmpeg"

    ffmpeg_dir = os.path.dirname(os.path.abspath(ffmpeg_exe))
    current_path = os.environ.get("PATH", "")

    # 移除已有的同目录条目，避免重复
    path_dirs = [
        d for d in current_path.split(os.pathsep)
        if d and os.path.normcase(os.path.abspath(d)) != os.path.normcase(os.path.abspath(ffmpeg_dir))
    ]
    new_path = ffmpeg_dir + os.pathsep + os.pathsep.join(path_dirs)
    os.environ["PATH"] = new_path

    return ffmpeg_exe


def get_ffmpeg() -> str:
    """获取 ffmpeg 可执行文件路径（有兜底）"""
    return find_ffmpeg() or "ffmpeg"


def get_ffprobe() -> str:
    """获取 ffprobe 可执行文件路径（有兜底）"""
    return find_ffprobe() or "ffprobe"


def probe_video_duration(filepath: str) -> float:
    """
    获取视频时长（秒），失败返回 0。

    优先用 ffprobe，失败时用 ffmpeg。
    """
    if not os.path.isfile(filepath):
        return 0.0

    probe = find_ffprobe()
    if probe:
        try:
            r = subprocess.run(
                [probe, "-v", "quiet", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", filepath],
                capture_output=True, text=True, timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            if r.returncode == 0 and r.stdout.strip():
                return float(r.stdout.strip())
        except Exception as e:
            logger.debug(f"[FFmpegUtils] ffprobe获取时长失败: {e}")

    # ffmpeg 兜底
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        try:
            r = subprocess.run(
                [ffmpeg, "-i", filepath, "-f", "null", "-"],
                capture_output=True, text=True, timeout=120,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            import re
            m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", r.stderr)
            if m:
                h, mi, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
                return h * 3600 + mi * 60 + s
        except Exception as e:
            logger.debug(f"[FFmpegUtils] ffmpeg获取时长兜底失败: {e}")

    return 0.0
