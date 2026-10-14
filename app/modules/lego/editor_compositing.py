# -*- coding: utf-8 -*-
"""剪辑合成像素运算 —— 混合模式 / 裁剪 / 叠层混合（2026-10-11 从 editor_module.py 抽出，拆分刀 1）。

## 为什么抽

`editor_module.py`（9,746 行 / 365 方法）是单文件规模守卫的存量最大项，也是「AI 改错概率随
文件大小上升」的典型。按「门面 + 分族抽出」策略做**第一刀**：只抽**与本类状态无关的模块级纯函数**：

  · `_blend_pixels_bgr`            —— W3C 混合模式公式（纯 numpy）
  · `apply_clip_crop_bgr`          —— 按 ``clip["crop"]`` 裁掉四边（纯数组切片）
  · `composite_overlay_bgr_blend`  —— 几何定位 + 像素混合（numpy + cv2）

三者都是纯函数（无 ``self``、无 Qt、无项目内依赖），且实测 grep 确认**引用点全部在
`editor_module.py` 内部**（无任何其他模块 import），因此抽出对调用方零影响。

## 为什么不触碰冻结区（这刀无需解冻）

`scripts/frozen_zone_guard.py::collect_hashes()` 对 zone 的 **symbol** 是按「AST 提取该符号源码
文本」再算 sha256 —— 只锁 zone 里登记的那 23 个符号（均为播放/音频、预览变换、退出清理族）。
本文件抽走的 3 个函数**不在任何 zone 的符号表**，且 `editor_module.py` 本身也不是任何 zone 的
``files`` 锁目标 ⇒ 抽出后守卫哈希不变。
"""

from __future__ import annotations


def _blend_pixels_bgr(base01, over01, mode: str):
    """按混合模式计算 base/overlay 混合结果（BGR，float，0~1）。非独立分离模式（色相/饱和度/颜色/明度）用 W3C 公式。"""
    import numpy as np

    if mode in (None, "", "normal", "正常"):
        return over01

    if mode in ("darken", "变暗"):
        return np.minimum(base01, over01)
    if mode in ("multiply", "正片叠底"):
        return base01 * over01
    if mode in ("color_burn", "颜色加深"):
        return np.where(over01 <= 1e-6, 0.0, 1.0 - np.minimum(1.0, (1.0 - base01) / np.maximum(over01, 1e-6)))
    if mode in ("lighten", "变亮"):
        return np.maximum(base01, over01)
    if mode in ("screen", "滤色"):
        return base01 + over01 - base01 * over01
    if mode in ("hard_light", "强光"):
        lo = 2.0 * base01 * over01
        hi = 1.0 - 2.0 * (1.0 - base01) * (1.0 - over01)
        return np.where(over01 <= 0.5, lo, hi)
    if mode in ("overlay", "叠加"):
        lo = 2.0 * base01 * over01
        hi = 1.0 - 2.0 * (1.0 - base01) * (1.0 - over01)
        return np.where(base01 <= 0.5, lo, hi)
    if mode in ("soft_light", "柔光"):
        d = np.where(base01 <= 0.25, ((16 * base01 - 12) * base01 + 4) * base01, np.sqrt(np.maximum(base01, 0.0)))
        lo = base01 - (1.0 - 2.0 * over01) * base01 * (1.0 - base01)
        hi = base01 + (2.0 * over01 - 1.0) * (d - base01)
        return np.where(over01 <= 0.5, lo, hi)
    if mode in ("difference", "差值"):
        return np.abs(base01 - over01)
    if mode in ("exclusion", "排除"):
        return base01 + over01 - 2.0 * base01 * over01
    if mode in ("hue", "saturation", "color", "luminosity", "色相", "饱和度", "颜色", "明度"):

        def lum(c):
            return c[..., 2] * 0.3 + c[..., 1] * 0.59 + c[..., 0] * 0.11

        def clip_lum(c):
            return np.clip(c, 0.0, 1.0)

        def set_lum(c, l):
            d = l - lum(c)
            return clip_lum(c + d[..., None])

        def sat(c):
            return c.max(axis=-1) - c.min(axis=-1)

        def set_sat(c, s):
            order = np.argsort(c, axis=-1)  # 从小到大：min, mid, max 的下标
            cmin = np.take_along_axis(c, order[..., 0:1], axis=-1)
            cmid = np.take_along_axis(c, order[..., 1:2], axis=-1)
            cmax = np.take_along_axis(c, order[..., 2:3], axis=-1)
            rng = np.maximum(cmax - cmin, 1e-6)
            new_mid = np.where(cmax > cmin, (cmid - cmin) * s[..., None] / rng, 0.0)
            new_max = np.where(cmax > cmin, s[..., None], 0.0)
            new_min = np.zeros_like(cmin)
            out = np.zeros_like(c)
            np.put_along_axis(out, order[..., 0:1], new_min, axis=-1)
            np.put_along_axis(out, order[..., 1:2], new_mid, axis=-1)
            np.put_along_axis(out, order[..., 2:3], new_max, axis=-1)
            return out

        if mode in ("hue", "色相"):
            return set_lum(set_sat(over01, sat(base01)), lum(base01))
        if mode in ("saturation", "饱和度"):
            return set_lum(set_sat(base01, sat(over01)), lum(base01))
        if mode in ("color", "颜色"):
            return set_lum(over01, lum(base01))
        return set_lum(base01, lum(over01))  # luminosity/明度

    return over01


def apply_clip_crop_bgr(arr, clip: dict):
    """按 clip["crop"]（上/下/左/右，源帧像素）裁掉四边，返回裁剪后的数组（无裁剪时原样返回）。"""
    if arr is None or not isinstance(clip, dict):
        return arr
    crop = clip.get("crop")
    if not isinstance(crop, dict):
        return arr
    try:
        top = max(0, int(crop.get("top", 0) or 0))
        bottom = max(0, int(crop.get("bottom", 0) or 0))
        left = max(0, int(crop.get("left", 0) or 0))
        right = max(0, int(crop.get("right", 0) or 0))
    except (TypeError, ValueError):
        return arr
    if top == 0 and bottom == 0 and left == 0 and right == 0:
        return arr
    h, w = arr.shape[:2]
    y0, y1 = min(top, h - 1), max(top + 1, h - bottom)
    x0, x1 = min(left, w - 1), max(left + 1, w - right)
    if y1 <= y0 or x1 <= x0:
        return arr
    return arr[y0:y1, x0:x1]


def composite_overlay_bgr_blend(base_bgr, overlay_bgr, tf: dict, opacity: float = 1.0, blend_mode: str = "normal"):
    """在 composite_overlay_bgr 的定位/缩放/旋转几何基础上，额外支持像素混合模式。

    与冻结区 clip_transform.composite_overlay_bgr 的放置几何保持一致（新写函数，
    不改动冻结文件），仅当 blend_mode 非「正常」时按混合公式计算叠层结果。
    """
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

    x0 = int((bw - ow) * float(tf.get("x", 0.5)))
    y0 = int((bh - oh) * float(tf.get("y", 0.5)))
    x0 = max(-ow + 1, min(bw - 1, x0))
    y0 = max(-oh + 1, min(bh - 1, y0))

    sx0 = max(0, -x0)
    sy0 = max(0, -y0)
    dx0 = max(0, x0)
    dy0 = max(0, y0)
    dx1 = min(bw, x0 + ow)
    dy1 = min(bh, y0 + oh)

    result = base.copy()
    if dx1 > dx0 and dy1 > dy0:
        sw = dx1 - dx0
        sh = dy1 - dy0
        over_region01 = np.clip(scaled[sy0:sy0 + sh, sx0:sx0 + sw] / 255.0, 0.0, 1.0)
        base_region01 = np.clip(result[dy0:dy1, dx0:dx1] / 255.0, 0.0, 1.0)
        blended01 = _blend_pixels_bgr(base_region01, over_region01, blend_mode)
        blended = np.clip(blended01, 0.0, 1.0) * 255.0
        op = max(0.0, min(1.0, float(opacity)))
        result[dy0:dy1, dx0:dx1] = base_region01 * 255.0 * (1.0 - op) + blended * op
    return result
