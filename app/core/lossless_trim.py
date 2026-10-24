# -*- coding: utf-8 -*-
"""LosslessCut 思路：关键帧对齐 trim。纯函数，不碰 Qt / `_clips`。"""
from __future__ import annotations

import os
import subprocess
from typing import Dict, List, Optional, Sequence

from app.core.ffmpeg_utils import find_ffmpeg, find_ffprobe

_WIN = os.name == "nt"


def parse_ffprobe_keyframes(stdout: str) -> List[float]:
    times: List[float] = []
    for raw in (stdout or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            times.append(float(line))
        except ValueError:
            continue
    times.sort()
    return times


def snap_to_keyframe(
    t: float,
    keyframes: Sequence[float],
    *,
    mode: str = "before",
) -> float:
    if not keyframes:
        return float(t)
    t = float(t)
    if mode == "after":
        for k in keyframes:
            if k + 1e-6 >= t:
                return float(k)
        return float(keyframes[-1])
    chosen = float(keyframes[0])
    for k in keyframes:
        if k - 1e-6 <= t:
            chosen = float(k)
        else:
            break
    return chosen


def probe_keyframes(
    src: str,
    *,
    ffprobe: Optional[str] = None,
    timeout: float = 60.0,
) -> List[float]:
    probe = ffprobe or find_ffprobe() or "ffprobe"
    cmd = [
        probe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "packet=pts_time,flags",
        "-of",
        "csv=print_section=0",
        src,
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if _WIN else 0,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return []
    times: List[float] = []
    for line in (proc.stdout or "").splitlines():
        parts = line.strip().split(",")
        if len(parts) < 2:
            continue
        flags = parts[1]
        if "K" not in flags:
            continue
        try:
            times.append(float(parts[0]))
        except ValueError:
            continue
    times.sort()
    return times


def lossless_trim(
    src: str,
    t0: float,
    t1: float,
    dst: str,
    *,
    ffmpeg: Optional[str] = None,
    ffprobe: Optional[str] = None,
    max_snap_skew: float = 0.5,
    timeout: float = 300.0,
) -> Dict[str, object]:
    """优先 -c copy；切点偏离关键帧过大或 copy 失败则重编码并标明 reencoded。"""
    if not src or not os.path.isfile(src):
        return {
            "success": False,
            "reencoded": False,
            "error": f"源文件不存在：{src}",
            "dst": dst,
        }
    t0 = float(t0)
    t1 = float(t1)
    if t1 <= t0 + 1e-3:
        return {
            "success": False,
            "reencoded": False,
            "error": "出点必须大于入点",
            "dst": dst,
        }
    ff = ffmpeg or find_ffmpeg() or "ffmpeg"
    kfs = probe_keyframes(src, ffprobe=ffprobe)
    snap0 = snap_to_keyframe(t0, kfs, mode="before") if kfs else t0
    skew = abs(snap0 - t0)
    duration = t1 - t0
    os.makedirs(os.path.dirname(os.path.abspath(dst)) or ".", exist_ok=True)

    copy_ok = kfs and skew <= max_snap_skew
    if copy_ok:
        copy_cmd = [
            ff, "-y", "-ss", f"{snap0:.6f}", "-i", src,
            "-t", f"{duration:.6f}", "-c", "copy", "-avoid_negative_ts", "1", dst,
        ]
        try:
            proc = subprocess.run(
                copy_cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                creationflags=subprocess.CREATE_NO_WINDOW if _WIN else 0,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            proc = None
            copy_err = str(e)
        else:
            copy_err = (proc.stderr or "")[-400:]
        if proc is not None and proc.returncode == 0 and os.path.isfile(dst) and os.path.getsize(dst) > 0:
            return {
                "success": True,
                "reencoded": False,
                "error": "",
                "dst": dst,
                "t0": snap0,
                "t1": snap0 + duration,
                "snap_skew": skew,
            }

    re_cmd = [
        ff, "-y", "-ss", f"{t0:.6f}", "-i", src,
        "-t", f"{duration:.6f}",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "aac", dst,
    ]
    try:
        proc2 = subprocess.run(
            re_cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if _WIN else 0,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return {
            "success": False,
            "reencoded": False,
            "error": f"FFmpeg 无法运行：{e}",
            "dst": dst,
        }
    if proc2.returncode != 0 or not os.path.isfile(dst) or os.path.getsize(dst) == 0:
        return {
            "success": False,
            "reencoded": True,
            "error": (proc2.stderr or "")[-500:] or "重编码失败，未写出文件",
            "dst": dst,
        }
    return {
        "success": True,
        "reencoded": True,
        "error": "",
        "dst": dst,
        "t0": t0,
        "t1": t1,
        "snap_skew": skew if kfs else None,
        "message": "切点未对齐关键帧或 copy 失败，已重编码",
    }
