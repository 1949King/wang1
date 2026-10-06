# -*- coding: utf-8 -*-
"""LUT（3D 查找表）滤镜映射 —— 导出侧。

为什么单独成模块（2026-10-05，刀 A3 第三项）
============================================
`video_processor.py` 在单文件规模守卫的基线内（2732 行，容差 ±30），
LUT 映射带来 40+ 行会直接破门禁 —— 按项目规矩**拆模块**而不是放宽基线。
LUT 的解析/转义/混合本来就是一类独立关注点，抽出来也更好单测。

背景：修的是什么 bug
====================
`map_filter_to_vf` 此前**完全不处理 `lut` 键** ⇒ LUT 只在**预览**生效、
**导出静默丢失**（用户看到调色后的画面，拿到的成片却是原色 ——
「预览≠导出」是最难查的一类不一致）。

与预览的等价性依据（`app/core/gl_filter_widget.py` 片元着色器）
==============================================================
着色器最后一步是::

    col = clamp(col, 0, 1) * u_opacity;
    if (u_lut_intensity > 0.001 && u_lut_size > 1.5) {
        col = mix(col, applyLut2D(col), clamp(u_lut_intensity, 0, 1));
    }

⇒ 两条硬约束：
  ① LUT 必须在**滤镜链尾**（后于 eq/色温/锐度/滤镜分类）；
  ② 强度是「原图与 LUT 结果的**线性混合**」，对应 ffmpeg `split + lut3d + blend`
     （`lut3d` 本身没有强度参数）。
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict

logger = logging.getLogger(__name__)


def escape_lut_path(path: str) -> str:
    """转义 ffmpeg 滤镜参数里的文件路径（**2026-10-05 真机实测校准，勿凭直觉改**）。

    filtergraph 的解析规则（用本机 ffmpeg 逐个变体试出来的，不是猜的）：

    | 写法 | 结果 |
    |---|---|
    | `lut3d=file=D:/a.cube` | ❌ 解析失败 —— `:` 被当作选项分隔符，值只剩 `/a.cube` |
    | `lut3d=file=D\\:/a.cube` | ❌ 仍失败 —— 转义了冒号但**没有引号保护** |
    | `lut3d=file='D\\:/a.cube'` | ✅ **可用** —— 转义冒号 **+ 单引号包裹**（实测 OK） |

    ⇒ 两件都要做：先把 `\\`→`/`，再把路径用单引号包起来并对 `:` 转义；
    路径里原本的 `'` 按 ffmpeg 规则写成 `'\\''`（结束引号 + 转义 + 重开引号）。
    """
    p = str(path).replace("\\", "/")
    p = p.replace("'", "'\\''")
    p = p.replace(":", "\\:")
    return f"'{p}'"


def build_lut_vf(color_params: Dict[str, Any]) -> str:
    """把 `color_params` 里的 LUT 设置映射成 vf 片段（空串 = 无 LUT）。

    键约定（前端调色页写入 `clip["effects"]["color_params"]`）：
      - `lut`：**cube/3dl 绝对路径**
      - `lut_intensity`：0~1，缺省按 1.0；非法值按 1.0 兜底

    诚实失败：文件不存在时打 WARNING 并**不加**该滤镜（静默跳过会让
    「预览≠导出」这条最难查的 bug 复活）。
    """
    cp = color_params or {}
    lut_path = str(cp.get("lut") or "").strip()
    if not lut_path:
        return ""
    if not os.path.isfile(lut_path):
        logger.warning("LUT 文件不存在，导出将不带该 LUT（与预览也不一致）: %s", lut_path)
        return ""
    esc = escape_lut_path(lut_path)
    raw_i = cp.get("lut_intensity")
    try:
        lut_i = 1.0 if raw_i is None else max(0.0, min(1.0, float(raw_i)))
    except (TypeError, ValueError):
        lut_i = 1.0
    if lut_i >= 0.999:
        return f"lut3d=file={esc}"
    if lut_i > 0.001:
        # 复刻着色器 `mix(col, mapped, i)`：先 split 出原图，再让 LUT 结果与原图按 i 混合
        return (f"split[lutbase][lutin];[lutin]lut3d=file={esc}[lutout];"
                f"[lutbase][lutout]blend=all_mode=normal:all_opacity={lut_i:.3f}")
    return ""   # 强度 0 ⇒ 等价原图（与预览 mix 0% 一致）
