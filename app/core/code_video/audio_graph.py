# -*- coding: utf-8 -*-
"""音频 filter graph 纯函数（V4.45 · 2026-10-19）

Chromium 只负责画面帧；音频由 ffmpeg 按 compiled 时间线精确拼：
每个有声 clip → `atrim`（源区间）→ `atempo`（变速，0.25~4 链式）→ `volume` →
`adelay`（时间线起点）→ `amix`。

**纯函数**：不探测文件、不跑 ffmpeg —— 是否有音轨由 render_host 用 ffprobe 判定后传入。
变速片段不静默丢声（`atempo` 链式），无音源由 host 用 `anullsrc` 补静音轨。
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple


def iter_audio_clips(compiled: Dict[str, Any]) -> List[Dict[str, Any]]:
    """收集需要混音的有声 clip（video/audio 且有 volume>0）。"""
    out: List[Dict[str, Any]] = []
    for item in compiled.get("tracks") or []:
        clip = (item or {}).get("clip") or {}
        if not clip:
            continue
        if clip.get("kind") not in ("video", "audio"):
            continue
        if float(clip.get("volume") or 0.0) <= 0.0:
            continue
        if not str(clip.get("source", "")).startswith("asset://"):
            continue
        out.append(clip)
    return out


def atempo_chain(speed: float) -> List[str]:
    """把任意 0.25~4 的倍速拆成 atempo 支持的 [0.5, 2.0] 链。"""
    try:
        s = float(speed)
    except (TypeError, ValueError):
        s = 1.0
    if s <= 0:
        s = 1.0
    parts: List[str] = []
    while s > 2.0:
        parts.append("atempo=2.0")
        s /= 2.0
    while s < 0.5:
        parts.append("atempo=0.5")
        s /= 0.5
    if abs(s - 1.0) > 1e-6:
        parts.append(f"atempo={s:.6f}")
    return parts


def _clip_window(clip: Dict[str, Any]) -> Tuple[float, float, float]:
    rng = clip.get("range") or [0.0, 0.0]
    start, end = float(rng[0]), float(rng[1])
    speed = float(clip.get("speed") or 1.0)
    src = clip.get("source_range")
    src_start = float(src[0]) if src else 0.0
    return max(end - start, 0.0), src_start, speed


def build_audio_graph(
    clips: List[Dict[str, Any]],
    keys_with_audio: Dict[str, bool],
    asset_paths: Dict[str, str],
    *,
    sample_rate: int = 48000,
) -> Tuple[List[str], str, bool]:
    """生成 (音频输入路径列表, filter_complex, 是否有音源)。

    输入路径顺序对应 ffmpeg 的 `-i` 顺序（帧输入是 0 号，音频从 1 号开始）。
    """
    inputs: List[str] = []
    chains: List[str] = []
    labels: List[str] = []
    for clip in clips:
        key = str(clip.get("source", ""))[len("asset://"):]
        if not keys_with_audio.get(key):
            continue
        duration, src_start, speed = _clip_window(clip)
        if duration <= 0:
            continue
        path = asset_paths.get(key)
        if not path:
            continue
        idx = len(inputs) + 1  # 0 号是帧序列
        inputs.append(path)
        label = f"a{idx}"
        src_duration = duration * max(speed, 1e-6)
        parts = [
            f"[{idx}:a]atrim=start={src_start:.6f}:duration={src_duration:.6f}",
            "asetpts=PTS-STARTPTS",
            *atempo_chain(speed),
            f"volume={float(clip.get('volume') or 1.0):.6f}",
            f"adelay={int(round(float(clip.get('range', [0])[0]) * 1000))}|" 
            f"{int(round(float(clip.get('range', [0])[0]) * 1000))}",
        ]
        chains.append(",".join(parts) + f"[{label}]")
        labels.append(f"[{label}]")
    if not labels:
        return [], "", False
    mix = (
        "".join(labels)
        + f"amix=inputs={len(labels)}:duration=longest:normalize=0,"
        + f"apad,aresample={int(sample_rate)}[aout]"
    )
    return inputs, ";".join(chains + [mix]), True
