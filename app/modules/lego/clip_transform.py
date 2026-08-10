# -*- coding: utf-8 -*-
"""片段变换模型（从 editor_module / video_processor 抽出）。

统一归一化坐标，供预览叠层与导出叠轨共用：
- x/y: 0~1 → overlay=(W-w)*x:(H-h)*y（0.5=居中）
- scale: 相对画幅 0.05~2.0
- rotation: 度
- anchor: 中心/左上/右上/左下/右下（影响旋转枢轴与放置）
"""
# >>> FROZEN:clip-transform:module BEGIN
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

ANCHOR_NAMES = ("中心", "左上", "右上", "左下", "右下")
# 锚点相对叠层窗的归一化枢轴 (ax, ay)，0=左/上，1=右/下
ANCHOR_PIVOTS = {
    "中心": (0.5, 0.5),
    "center": (0.5, 0.5),
    "左上": (0.0, 0.0),
    "top_left": (0.0, 0.0),
    "右上": (1.0, 0.0),
    "top_right": (1.0, 0.0),
    "左下": (0.0, 1.0),
    "bottom_left": (0.0, 1.0),
    "右下": (1.0, 1.0),
    "bottom_right": (1.0, 1.0),
}


def _as_unit01(val: Any, default: float) -> float:
    try:
        v = float(val)
    except (TypeError, ValueError):
        return float(default)
    if v > 1.0 + 1e-6:
        v = v / 100.0
    return max(0.0, min(1.0, v))


def resolve_anchor(name: Any) -> Tuple[float, float]:
    """返回锚点枢轴 (ax, ay) ∈ [0,1]。"""
    if isinstance(name, (tuple, list)) and len(name) >= 2:
        try:
            return (
                max(0.0, min(1.0, float(name[0]))),
                max(0.0, min(1.0, float(name[1]))),
            )
        except (TypeError, ValueError):
            return (0.5, 0.5)
    key = str(name or "中心").strip()
    return ANCHOR_PIVOTS.get(key, (0.5, 0.5))


def normalize_clip_transform(
    clip: Optional[Dict[str, Any]],
    frame_w: int = 1920,
    frame_h: int = 1080,
    defaults: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """统一片段变换为归一化坐标。

    返回 ``{x, y, scale, opacity, rotation, anchor, anchor_x, anchor_y}``。
    """
    d = defaults or {}
    def_x = float(d.get("x", 0.75))
    def_y = float(d.get("y", 0.80))
    def_s = float(d.get("scale", 0.35))
    def_op = float(d.get("opacity", 1.0))
    def_rot = float(d.get("rotation", 0.0))
    def_anchor = str(d.get("anchor", "中心") or "中心")
    clip = clip if isinstance(clip, dict) else {}
    fw = max(1, int(frame_w or 1920))
    fh = max(1, int(frame_h or 1080))

    x = y = None
    scale = None
    opacity = None
    rotation = None
    anchor = None

    tf = clip.get("transform") if isinstance(clip.get("transform"), dict) else {}
    if tf:
        if tf.get("x") is not None:
            x = _as_unit01(tf.get("x"), def_x)
        if tf.get("y") is not None:
            y = _as_unit01(tf.get("y"), def_y)
        if tf.get("scale") is not None:
            try:
                scale = float(tf.get("scale"))
            except (TypeError, ValueError):
                pass
        if tf.get("opacity") is not None:
            try:
                opacity = float(tf.get("opacity"))
            except (TypeError, ValueError):
                pass
        if tf.get("rotation") is not None:
            try:
                rotation = float(tf.get("rotation"))
            except (TypeError, ValueError):
                pass
        if tf.get("anchor") is not None:
            anchor = str(tf.get("anchor"))

    if x is None and clip.get("pip_x") is not None:
        x = _as_unit01(clip.get("pip_x"), def_x)
    if y is None and clip.get("pip_y") is not None:
        y = _as_unit01(clip.get("pip_y"), def_y)
    if scale is None and clip.get("pip_scale") is not None:
        try:
            scale = float(clip.get("pip_scale"))
        except (TypeError, ValueError):
            pass

    pos = clip.get("position") if isinstance(clip.get("position"), dict) else None
    if x is None and pos is not None:
        try:
            x = max(0.0, min(1.0, float(pos.get("x", 0) or 0) / float(fw) + 0.5))
        except (TypeError, ValueError):
            x = def_x
    if y is None and pos is not None:
        try:
            y = max(0.0, min(1.0, float(pos.get("y", 0) or 0) / float(fh) + 0.5))
        except (TypeError, ValueError):
            y = def_y

    if scale is None:
        try:
            if clip.get("scale") is not None:
                scale = float(clip.get("scale"))
            elif isinstance(clip.get("effects"), dict) and clip["effects"].get("scale") is not None:
                scale = float(clip["effects"]["scale"])
        except (TypeError, ValueError):
            scale = None

    if opacity is None:
        try:
            eff = clip.get("effects") if isinstance(clip.get("effects"), dict) else {}
            if clip.get("opacity") is not None:
                opacity = float(clip.get("opacity"))
            elif eff.get("opacity") is not None:
                opacity = float(eff.get("opacity"))
        except (TypeError, ValueError):
            opacity = None

    if rotation is None:
        try:
            if clip.get("rotation") is not None:
                rotation = float(clip.get("rotation"))
            elif tf.get("rotation") is not None:
                rotation = float(tf.get("rotation"))
        except (TypeError, ValueError):
            rotation = None

    if anchor is None:
        anchor = str(clip.get("anchor") or def_anchor)

    if x is None:
        x = def_x
    if y is None:
        y = def_y
    if scale is None:
        scale = def_s
    if opacity is None:
        opacity = def_op
    if rotation is None:
        rotation = def_rot

    # 关键帧/预览可覆盖的临时字段
    for k_src, k_dst, clamp in (
        ("_tf_x", "x", True),
        ("_tf_y", "y", True),
        ("_tf_rot", "rotation", False),
    ):
        if isinstance(clip.get("effects"), dict) and clip["effects"].get(k_src) is not None:
            try:
                v = float(clip["effects"][k_src])
                if clamp:
                    v = max(0.0, min(1.0, v))
                if k_dst == "x":
                    x = v
                elif k_dst == "y":
                    y = v
                else:
                    rotation = v
            except (TypeError, ValueError):
                pass

    scale = max(0.05, min(2.0, float(scale)))
    opacity = max(0.0, min(1.0, float(opacity)))
    rotation = float(rotation or 0.0)
    while rotation > 180:
        rotation -= 360
    while rotation < -180:
        rotation += 360
    ax, ay = resolve_anchor(anchor)
    return {
        "x": float(x),
        "y": float(y),
        "scale": scale,
        "opacity": opacity,
        "rotation": rotation,
        "anchor": str(anchor or "中心"),
        "anchor_x": ax,
        "anchor_y": ay,
    }


def apply_normalized_transform(
    clip: Dict[str, Any],
    *,
    x: Optional[float] = None,
    y: Optional[float] = None,
    scale: Optional[float] = None,
    opacity: Optional[float] = None,
    rotation: Optional[float] = None,
    anchor: Optional[str] = None,
    frame_w: int = 1920,
    frame_h: int = 1080,
) -> Dict[str, Any]:
    """把归一化变换写回 clip（transform + pip_* + position/scale/effects）。"""
    if not isinstance(clip, dict):
        return clip
    cur = normalize_clip_transform(clip, frame_w, frame_h)
    nx = cur["x"] if x is None else _as_unit01(x, cur["x"])
    ny = cur["y"] if y is None else _as_unit01(y, cur["y"])
    try:
        ns = cur["scale"] if scale is None else max(0.05, min(2.0, float(scale)))
    except (TypeError, ValueError):
        ns = cur["scale"]
    try:
        nop = cur["opacity"] if opacity is None else max(0.0, min(1.0, float(opacity)))
    except (TypeError, ValueError):
        nop = cur["opacity"]
    try:
        nrot = cur["rotation"] if rotation is None else float(rotation)
    except (TypeError, ValueError):
        nrot = cur["rotation"]
    nanchor = str(anchor if anchor is not None else cur.get("anchor") or "中心")

    fw = max(1, int(frame_w or 1920))
    fh = max(1, int(frame_h or 1080))
    ax, ay = resolve_anchor(nanchor)
    clip["transform"] = {
        "x": nx, "y": ny, "scale": ns, "opacity": nop,
        "rotation": nrot, "anchor": nanchor,
        "anchor_x": ax, "anchor_y": ay,
    }
    clip["pip_x"] = nx
    clip["pip_y"] = ny
    clip["pip_scale"] = ns
    clip["scale"] = ns
    clip["opacity"] = nop
    clip["rotation"] = nrot
    clip["anchor"] = nanchor
    clip["position"] = {
        "x": int(round((nx - 0.5) * fw)),
        "y": int(round((ny - 0.5) * fh)),
    }
    effects = clip.get("effects") if isinstance(clip.get("effects"), dict) else {}
    effects = dict(effects)
    effects["scale"] = ns
    effects["opacity"] = nop
    effects["rotation"] = nrot
    clip["effects"] = effects
    return clip


def composite_overlay_bgr(
    base_bgr,
    overlay_bgr,
    tf: Dict[str, Any],
    opacity: float = 1.0,
):
    """将 overlay 按 tf 缩放/旋转/定位合成到 base（float32 BGR）。返回新 base。"""
    import numpy as np
    import cv2

    base = base_bgr.astype(np.float32)
    overlay = overlay_bgr.astype(np.float32)
    bh, bw = base.shape[:2]
    if overlay.shape[:2] != (bh, bw):
        overlay = cv2.resize(overlay, (bw, bh)).astype(np.float32)

    scale = float(tf.get("scale", 1.0) or 1.0)
    ow = max(1, int(bw * scale))
    oh = max(1, int(bh * scale))
    scaled = cv2.resize(overlay, (ow, oh))
    rot = float(tf.get("rotation", 0) or 0)
    ax = float(tf.get("anchor_x", 0.5))
    ay = float(tf.get("anchor_y", 0.5))

    if abs(rot) > 0.05:
        # 绕锚点旋转：扩展画布避免裁切
        cx, cy = ow * ax, oh * ay
        M = cv2.getRotationMatrix2D((cx, cy), rot, 1.0)
        cos = abs(M[0, 0])
        sin = abs(M[0, 1])
        nw = int(oh * sin + ow * cos)
        nh = int(oh * cos + ow * sin)
        M[0, 2] += (nw / 2) - cx
        M[1, 2] += (nh / 2) - cy
        scaled = cv2.warpAffine(
            scaled, M, (nw, nh),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(0, 0, 0),
        )
        ow, oh = nw, nh
        # 旋转后枢轴近似画布中心
        ax, ay = 0.5, 0.5

    # 目标：锚点落在 (tf.x * W, tf.y * H) 附近，兼容 (W-w)*x 语义：
    # 左上角 = (W-w)*x  ⇔  窗中心落点随尺寸变化；锚点偏移：
    x0 = int((bw - ow) * float(tf.get("x", 0.5)) - (ax - 0.5) * ow * 0)
    y0 = int((bh - oh) * float(tf.get("y", 0.5)) - (ay - 0.5) * oh * 0)
    # 简化：仍用 (W-w)*x 放置左上；旋转后尺寸已含边距
    x0 = int((bw - ow) * float(tf.get("x", 0.5)))
    y0 = int((bh - oh) * float(tf.get("y", 0.5)))
    x0 = max(-ow + 1, min(bw - 1, x0))
    y0 = max(-oh + 1, min(bh - 1, y0))

    canvas = np.zeros_like(base)
    sx0 = max(0, -x0)
    sy0 = max(0, -y0)
    dx0 = max(0, x0)
    dy0 = max(0, y0)
    dx1 = min(bw, x0 + ow)
    dy1 = min(bh, y0 + oh)
    if dx1 > dx0 and dy1 > dy0:
        sw = dx1 - dx0
        sh = dy1 - dy0
        canvas[dy0:dy1, dx0:dx1] = scaled[sy0:sy0 + sh, sx0:sx0 + sw]

    op = max(0.0, min(1.0, float(opacity)))
    return base * (1.0 - op) + canvas * op


def lut_to_2d_atlas(lut_data, size: int):
    """把 (S,S,S,3) float LUT 展成 2D 图集：宽 S*S，高 S。行=G，列=B*S+R。"""
    import numpy as np
    s = int(size)
    atlas = np.zeros((s, s * s, 3), dtype=np.float32)
    for b in range(s):
        for g in range(s):
            for r in range(s):
                atlas[g, b * s + r] = lut_data[r, g, b]
    return atlas
# <<< FROZEN:clip-transform:module END
