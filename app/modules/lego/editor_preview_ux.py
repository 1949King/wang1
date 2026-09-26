"""
预览体验 UX（分级画质 / 代理路径解析）
====================================
从 editor_module 抽出的轻量逻辑，避免宿主继续膨胀。

约定：
  - 用户档位：quarter(1/4) / half(1/2) / full(100%)
  - PreviewManager 内部：low / medium / high
  - 导出永远用 clip["path"] 原片；预览可走 clip["proxy_path"]
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Mapping, Optional, Tuple

logger = logging.getLogger(__name__)

# UI 标签 → PreviewManager.preview_quality
QUALITY_LABEL_TO_PM = {
    "1/4": "low",
    "1/2": "medium",
    "100%": "high",
    "quarter": "low",
    "half": "medium",
    "full": "high",
    "low": "low",
    "medium": "medium",
    "high": "high",
}

PM_TO_QUALITY_LABEL = {
    "low": "1/4",
    "medium": "1/2",
    "high": "100%",
}

DEFAULT_USER_PREVIEW_QUALITY = "high"  # 100% 精剪，预览保持原片分辨率；拖动/播放时自动降至 1/4 保流畅


def normalize_preview_quality(quality: Optional[str]) -> str:
    """归一到 low/medium/high；非法值回落 medium。"""
    if not quality:
        return DEFAULT_USER_PREVIEW_QUALITY
    key = str(quality).strip()
    return QUALITY_LABEL_TO_PM.get(key, QUALITY_LABEL_TO_PM.get(key.lower(), DEFAULT_USER_PREVIEW_QUALITY))


def quality_label(quality: Optional[str]) -> str:
    return PM_TO_QUALITY_LABEL.get(normalize_preview_quality(quality), "1/2")


def quality_combo_items() -> Tuple[Tuple[str, str], ...]:
    """(显示文本, pm_quality) 列表。"""
    return (
        ("1/4 粗剪", "low"),
        ("1/2 常规", "medium"),
        ("100% 精剪", "high"),
    )


def resolve_preview_media_path(
    clip: Optional[Mapping[str, Any]],
    *,
    prefer_proxy: bool = True,
    resolve_abs=None,
) -> str:
    """
    预览用媒体路径：代理就绪则用代理，否则原片。
    resolve_abs: 可选 callable(path)->path，用于相对路径展开。
    """
    if not isinstance(clip, dict):
        return ""
    original = str(clip.get("path") or "")
    proxy = str(clip.get("proxy_path") or "")
    if resolve_abs is not None:
        try:
            original = resolve_abs(original) or original
        except Exception:
            logger.debug("resolve_abs 展开原始路径失败，保留原值", exc_info=True)
        try:
            if proxy:
                proxy = resolve_abs(proxy) or proxy
        except Exception:
            logger.debug("resolve_abs 展开代理路径失败，保留原值", exc_info=True)
    if prefer_proxy and proxy and os.path.isfile(proxy):
        return os.path.normpath(proxy)
    if original and os.path.isfile(original):
        return os.path.normpath(original)
    return original or proxy


def attach_proxy_path(clip: Dict[str, Any], proxy_path: str) -> bool:
    """写回 clip.proxy_path；不改 path（导出真相源）。"""
    if not isinstance(clip, dict) or not proxy_path:
        return False
    if not os.path.isfile(proxy_path):
        return False
    clip["proxy_path"] = os.path.normpath(os.path.abspath(proxy_path))
    return True


def is_proxy_path(path: str, cache_dir: Optional[str] = None) -> bool:
    if not path:
        return False
    try:
        ap = os.path.normcase(os.path.abspath(path))
    except Exception:
        return False
    if cache_dir:
        try:
            root = os.path.normcase(os.path.abspath(cache_dir))
            return ap.startswith((root + os.sep, root + "/"))
        except Exception:
            logger.debug("cache_dir 绝对化失败，按 proxies 关键字判定", exc_info=True)
    return "proxies" in ap.replace("\\", "/").lower()
