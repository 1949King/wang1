# -*- coding: utf-8 -*-
"""场景/高光切点：顺序 grab + 静音边界合并。不写 `_clips`。"""
from __future__ import annotations

import os
import re
import subprocess
from typing import List, Optional, Sequence, Tuple

import numpy as np

from app.core.ffmpeg_utils import find_ffmpeg

_WIN = os.name == "nt"
SilenceSpan = Tuple[float, float]
Segment = Tuple[float, float, str]


def gray_diff_scene_times(
    samples: Sequence[Tuple[float, np.ndarray]],
    thresh: float = 15.0,
) -> List[float]:
    """samples: (t, gray uint8)。返回场景切换时间。"""
    times: List[float] = []
    prev = None
    for t, gray in samples:
        if prev is not None:
            diff = float(np.mean(np.abs(gray.astype(np.float32) - prev.astype(np.float32))))
            if diff > thresh:
                times.append(float(t))
        prev = gray
    return times


def motion_highlight_windows(
    samples: Sequence[Tuple[float, np.ndarray]],
    *,
    window_sec: float = 2.0,
    top_n: int = 8,
) -> List[Tuple[float, float, float]]:
    """返回 (start, end, score) 按时间排序的高运动窗。"""
    if len(samples) < 2:
        return []
    scores: List[Tuple[float, float]] = []
    prev = None
    for t, gray in samples:
        if prev is not None:
            diff = float(np.mean(np.abs(gray.astype(np.float32) - prev.astype(np.float32))))
            scores.append((float(t), diff))
        prev = gray
    if not scores:
        return []
    t0 = samples[0][0]
    t1 = samples[-1][0]
    duration = max(t1 - t0, window_sec)
    step = max(window_sec * 0.5, 0.25)
    windows: List[Tuple[float, float, float]] = []
    t = t0
    while t + 0.2 < t0 + duration:
        end = min(t + window_sec, t0 + duration)
        chunk = [s for ts, s in scores if t - 1e-6 <= ts <= end + 1e-6]
        if chunk:
            windows.append((t, end, float(sum(chunk) / len(chunk))))
        t += step
    windows.sort(key=lambda x: x[2], reverse=True)
    best = windows[: max(1, int(top_n))]
    best.sort(key=lambda x: x[0])
    return best


def parse_silencedetect(stderr: str) -> List[SilenceSpan]:
    starts: List[float] = []
    spans: List[SilenceSpan] = []
    for line in (stderr or "").splitlines():
        m = re.search(r"silence_start:\s*([0-9.]+)", line)
        if m:
            starts.append(float(m.group(1)))
            continue
        m = re.search(r"silence_end:\s*([0-9.]+)", line)
        if m and starts:
            spans.append((starts.pop(0), float(m.group(1))))
    return spans


def merge_silence_into_segments(
    segments: Sequence[Segment],
    silences: Sequence[SilenceSpan],
    *,
    min_len: float = 1.0,
) -> List[Segment]:
    """用静音区间把过长场景切开；短于 min_len 的半段丢弃。"""
    out: List[Segment] = []
    for s, e, label in segments:
        cuts = [s]
        for a, b in silences:
            cut = float(a)
            if s + min_len < cut < e - min_len:
                cuts.append(cut)
        cuts.append(e)
        cuts = sorted(set(round(c, 4) for c in cuts))
        for i in range(len(cuts) - 1):
            a, b = cuts[i], cuts[i + 1]
            if b - a >= min_len:
                extra = label
                if i or len(cuts) > 2:
                    extra = (label + " · 静音切开").strip(" ·")
                out.append((a, b, extra))
    return out or list(segments)


def _sample_grays_sequential(
    path: str,
    *,
    sample_hz: float = 1.0,
    max_width: int = 320,
) -> List[Tuple[float, np.ndarray]]:
    import cv2

    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        return []
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0) or 30.0
    step = max(1, int(round(fps / max(sample_hz, 0.1))))
    samples: List[Tuple[float, np.ndarray]] = []
    idx = 0
    while True:
        ok = cap.grab()
        if not ok:
            break
        if idx % step == 0:
            ret, frame = cap.retrieve()
            if not ret:
                break
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            h, w = gray.shape[:2]
            if w > max_width:
                nh = max(1, int(h * max_width / w))
                gray = cv2.resize(gray, (max_width, nh))
            samples.append((idx / fps, gray))
        idx += 1
    cap.release()
    return samples


def detect_scene_segments(
    path: str,
    *,
    min_len: float = 2.0,
    max_scenes: int = 10,
    thresh: float = 15.0,
) -> List[Segment]:
    if not path or not os.path.isfile(path):
        return []
    samples = _sample_grays_sequential(path, sample_hz=1.0)
    if not samples:
        return []
    duration = samples[-1][0]
    cuts = [0.0] + gray_diff_scene_times(samples, thresh=thresh) + [duration]
    segs: List[Segment] = []
    for i in range(len(cuts) - 1):
        s, e = cuts[i], cuts[i + 1]
        if e - s >= min_len:
            segs.append((s, e, "场景"))
    return segs[:max_scenes]


def detect_motion_segments(
    path: str,
    *,
    top_n: int = 8,
    window_sec: float = 2.0,
) -> List[Segment]:
    if not path or not os.path.isfile(path):
        return []
    samples = _sample_grays_sequential(path, sample_hz=2.0, max_width=160)
    wins = motion_highlight_windows(samples, window_sec=window_sec, top_n=top_n)
    return [(s, e, f"运动分 {sc:.1f}") for s, e, sc in wins]


def detect_silences_ffmpeg(
    path: str,
    *,
    ffmpeg: Optional[str] = None,
    noise_db: float = -30.0,
    min_silence: float = 0.4,
    timeout: float = 120.0,
) -> List[SilenceSpan]:
    if not path or not os.path.isfile(path):
        return []
    ff = ffmpeg or find_ffmpeg() or "ffmpeg"
    cmd = [
        ff, "-i", path,
        "-af", f"silencedetect=noise={noise_db}dB:d={min_silence}",
        "-f", "null", "-",
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if _WIN else 0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    return parse_silencedetect((proc.stderr or "") + (proc.stdout or ""))


def grab_mid_jpeg(path: str, t: float, dst: str, *, ffmpeg: Optional[str] = None) -> bool:
    if not path or not os.path.isfile(path):
        return False
    ff = ffmpeg or find_ffmpeg() or "ffmpeg"
    os.makedirs(os.path.dirname(os.path.abspath(dst)) or ".", exist_ok=True)
    cmd = [ff, "-y", "-ss", f"{max(0.0, t):.3f}", "-i", path, "-vframes", "1", "-q:v", "3", dst]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW if _WIN else 0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0 and os.path.isfile(dst) and os.path.getsize(dst) > 0
