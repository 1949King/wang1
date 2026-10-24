# -*- coding: utf-8 -*-
"""本地模型统一视图（2026-10-25）。

为什么需要
==========
模型管理页此前只有「模型广场」（云端 provider + Ollama 对话）和「网关统计」，
**没有本地扩散引擎的入口** ⇒ 磁盘上已下载的 SD1.5/SDXL/SVD/Wan 在 UI 上完全不可见，
`modelscope_client.list_local_models()` 更是零调用者。

本模块把「本地模型」收成一张表（纯数据，无 Qt）：
  · 图像：diffusers_image 注册表（sd15-t2i / sdxl-t2i），is_downloaded 严格校验；
  · 视频：video_gen 注册表（svd-xt-i2v / wan21 / wan22），is_downloaded 认 unet|transformer；
  · 其余族（cogvideox/hunyuan/ltx/mochi/minimax_h3）：只有登记无权重 → downloaded=False，
    验证态取自 model_family（诚实标注 unverified）。

口径
====
· 每行一个「可下载/可用的模型条目」，与注册表一一对应，不虚构；
· verification 与 weights 分列：**权重在盘 ≠ 验证过**（三态：verified/unverified/blocked）；
· 目录一律给绝对路径，UI 可直接「打开所在文件夹」。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger("AI短剧编辑器.core.neural.local_models_view")

#: 只有登记、没有权重探测的族（视频）——如实列出，不假装可用
_VIDEO_FAMILY_EXTRA = ("cogvideox", "hunyuan", "ltx", "mochi", "minimax_h3")


def _verification_map() -> Dict[str, str]:
    """族 → 验证态（model_family 不可用则空表，UI 显示「未登记」）。"""
    try:
        from app.core.neural import model_family as MF

        return {s.family: s.verification for s in MF.families()}
    except Exception:
        logger.debug("[local_models_view] 模型族注册表不可用", exc_info=True)
        return {}


def _image_rows(vmap: Dict[str, str]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    try:
        from app.core.neural import diffusers_image as DI

        for m in DI.available_models():
            mid = str(m.get("id") or "")
            fam = "sdxl" if "sdxl" in mid else "sd15"
            try:
                downloaded = bool(DI.DiffusersImageEngine.is_downloaded(mid))
                folder = DI.DiffusersImageEngine.local_dir(mid)
            except Exception:
                downloaded, folder = False, ""
            rows.append({
                "id": mid, "label": m.get("label") or mid, "capability": "image",
                "family": fam, "verification": vmap.get(fam, ""),
                "downloaded": downloaded, "size_gb": m.get("size_gb"),
                "vram_gb": m.get("vram_gb"), "ram_gb": m.get("ram_gb"),
                "native_fps": 0, "modes": list(m.get("modes") or []),
                "dir": folder, "note": m.get("note") or "",
            })
    except Exception:
        logger.debug("[local_models_view] 图像注册表不可用", exc_info=True)
    return rows


def _video_rows(vmap: Dict[str, str]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    try:
        from app.core.neural import video_gen as VG

        for m in VG.available_models():
            mid = str(m.get("id") or "")
            fam = "svd" if mid.startswith("svd") else ("wan" if "wan" in mid else "")
            try:
                downloaded = bool(VG.VideoGenEngine.is_downloaded(mid))
                folder = VG.VideoGenEngine.local_dir(mid)
            except Exception:
                downloaded, folder = False, ""
            rows.append({
                "id": mid, "label": m.get("label") or mid, "capability": "video",
                "family": fam, "verification": vmap.get(fam, ""),
                "downloaded": downloaded, "size_gb": m.get("subset_gb"),
                "vram_gb": m.get("vram_gb"), "ram_gb": m.get("ram_gb"),
                "native_fps": m.get("native_fps") or 0,
                "modes": list(m.get("modes") or []),
                "dir": folder, "note": m.get("note") or "",
            })
    except Exception:
        logger.debug("[local_models_view] 视频注册表不可用", exc_info=True)
    return rows


def _extra_family_rows(vmap: Dict[str, str]) -> List[Dict[str, Any]]:
    """只有登记、无视频注册表条目的族：如实列出「未下载 / 未验证」。"""
    rows: List[Dict[str, Any]] = []
    try:
        from app.core.neural import model_family as MF
    except Exception:
        return rows
    for fam in _VIDEO_FAMILY_EXTRA:
        s = MF.spec_of(fam)
        if s is None:
            continue
        rows.append({
            "id": "%s（未接入下载器）" % fam, "label": "%s 族" % fam,
            "capability": "video", "family": fam,
            "verification": vmap.get(fam, ""), "downloaded": False,
            "size_gb": None, "vram_gb": s.min_vram_gb, "ram_gb": None,
            "native_fps": s.native_fps, "modes": [], "dir": "",
            "note": s.note or "已登记、无权重",
        })
    return rows


def list_local_models() -> List[Dict[str, Any]]:
    """统一本地模型清单：图像 + 视频注册表 + 仅登记族。异常一律返回已收集部分。"""
    vmap = _verification_map()
    return _image_rows(vmap) + _video_rows(vmap) + _extra_family_rows(vmap)


def summary(rows: List[Dict[str, Any]] | None = None) -> Dict[str, Any]:
    """计数摘要（UI 标题/胶囊用）：总数 / 已下载 / 已验证 / 分能力。"""
    rs = rows if rows is not None else list_local_models()
    by_cap: Dict[str, int] = {}
    for r in rs:
        c = str(r.get("capability") or "other")
        by_cap[c] = by_cap.get(c, 0) + 1
    return {
        "total": len(rs),
        "downloaded": sum(1 for r in rs if r.get("downloaded")),
        "verified": sum(1 for r in rs if r.get("verification") == "verified"),
        "by_capability": by_cap,
    }
