# -*- coding: utf-8 -*-
"""工程画幅 SSOT：比例 / 分辨率 / fit 纯函数（无 Qt / 无 I/O）。

EditorModule 持有 SequenceFormat；导出与预览 letterbox 均读此结构。
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from math import gcd
from typing import Any, Dict, Tuple

KNOWN_ASPECTS = ("9:16", "16:9", "1:1", "4:3", "3:4", "4:5", "21:9")


@dataclass
class SequenceFormat:
    """工程一等公民画幅。"""

    aspect: str = "9:16"
    width: int = 1080
    height: int = 1920
    fit_mode: str = "contain"  # contain=黑边 | cover=裁切铺满

    @classmethod
    def default(cls) -> "SequenceFormat":
        return cls()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "aspect": str(self.aspect),
            "width": int(self.width),
            "height": int(self.height),
            "fit_mode": str(self.fit_mode or "contain"),
        }

    @classmethod
    def from_dict(cls, data: Any) -> "SequenceFormat":
        if not isinstance(data, dict):
            return cls.default()
        aspect = str(data.get("aspect") or "9:16").strip() or "9:16"
        try:
            w = int(data.get("width") or 1080)
            h = int(data.get("height") or 1920)
        except (TypeError, ValueError):
            w, h = 1080, 1920
        fit = str(data.get("fit_mode") or "contain").strip().lower() or "contain"
        if fit not in ("contain", "cover"):
            fit = "contain"
        w, h = normalize_size(aspect, max(1, w), max(1, h))
        return cls(aspect=aspect, width=w, height=h, fit_mode=fit)

    def resolution_str(self) -> str:
        return f"{int(self.width)}x{int(self.height)}"

    def orientation(self) -> str:
        """竖屏 / 横屏 / 方形。"""
        if self.width == self.height or self.aspect in ("1:1",):
            return "方形"
        if self.height > self.width or self.aspect in ("9:16", "3:4", "4:5"):
            return "竖屏"
        return "横屏"

    def badge_text(self) -> str:
        fit_label = "裁切" if (self.fit_mode or "contain") == "cover" else "黑边"
        return f"{self.orientation()} {self.aspect} · {self.width}×{self.height} · {fit_label}"


# 常用画幅预设（须在 SequenceFormat 类定义之后）
SEQUENCE_FORMAT_PRESETS = [
    ("9:16 竖屏 · 抖音/TikTok",
        [SequenceFormat("9:16", 1080, 1920),
         SequenceFormat("9:16", 720, 1280),
         SequenceFormat("9:16", 2160, 3840)]),
    ("16:9 横屏 · 哔哩/YouTube",
        [SequenceFormat("16:9", 1920, 1080),
         SequenceFormat("16:9", 1280, 720),
         SequenceFormat("16:9", 3840, 2160)]),
    ("1:1 方形 · Instagram",
        [SequenceFormat("1:1", 1080, 1080),
         SequenceFormat("1:1", 1920, 1920)]),
    ("4:5 竖方 · Instagram Reels",
        [SequenceFormat("4:5", 1080, 1350)]),
    ("21:9 超宽 · 电影感",
        [SequenceFormat("21:9", 2560, 1080),
         SequenceFormat("21:9", 3440, 1440)]),
    ("4:3 传统方屏",
        [SequenceFormat("4:3", 1440, 1080)]),
]


def parse_aspect(s: str) -> Tuple[int, int]:
    """'9:16' / 'W:H' → (w_ratio, h_ratio)。"""
    raw = str(s or "").strip().replace("：", ":")
    if not raw or ":" not in raw:
        raise ValueError(f"invalid aspect: {s!r}")
    a, b = raw.split(":", 1)
    wr, hr = int(float(a.strip())), int(float(b.strip()))
    if wr <= 0 or hr <= 0:
        raise ValueError(f"invalid aspect: {s!r}")
    return wr, hr


def parse_resolution(s: str) -> Tuple[int, int]:
    """'1920x1080' / '1920×1080' → (w, h)。"""
    raw = str(s or "").strip().lower().replace("×", "x").replace("*", "x")
    if "x" not in raw:
        raise ValueError(f"invalid resolution: {s!r}")
    a, b = raw.split("x", 1)
    w, h = int(float(a.strip())), int(float(b.strip()))
    if w <= 0 or h <= 0:
        raise ValueError(f"invalid resolution: {s!r}")
    return w, h


def aspect_from_size(width: int, height: int) -> str:
    """像素 → 最简比，贴近已知预设则吸附。"""
    w, h = max(1, int(width)), max(1, int(height))
    g = gcd(w, h)
    simple = f"{w // g}:{h // g}"
    cur = w / h
    best = simple
    best_err = abs(cur - (w // g) / (h // g))
    for known in KNOWN_ASPECTS:
        try:
            ar_w, ar_h = parse_aspect(known)
        except ValueError:
            continue
        err = abs(cur - ar_w / ar_h)
        if err < 0.03 and err <= best_err + 1e-9:
            best, best_err = known, err
    return best


def normalize_size(aspect: str, width: int, height: int) -> Tuple[int, int]:
    """按 aspect 对齐像素；保留提示尺寸的长边，偶数边长。"""
    try:
        ar_w, ar_h = parse_aspect(aspect)
    except ValueError:
        ar_w, ar_h = 9, 16
    width = max(1, int(width or 1))
    height = max(1, int(height or 1))
    target_ar = ar_w / float(ar_h)
    if abs(width / float(height) - target_ar) < 0.02:
        nw, nh = width - (width % 2), height - (height % 2)
        return max(2, nw), max(2, nh)

    long_edge = max(width, height, 2)
    if ar_w >= ar_h:
        nw = long_edge
        nh = max(2, int(round(long_edge * ar_h / float(ar_w))))
    else:
        nh = long_edge
        nw = max(2, int(round(long_edge * ar_w / float(ar_h))))
    nw -= nw % 2
    nh -= nh % 2
    return max(2, nw), max(2, nh)


def fit_rect(
    src_w: int,
    src_h: int,
    dst_w: int,
    dst_h: int,
    mode: str = "contain",
) -> Tuple[int, int, int, int]:
    """在目标框内放置源：返回 (x, y, w, h)（目标坐标系；cover 可能越界）。"""
    src_w = max(1, int(src_w))
    src_h = max(1, int(src_h))
    dst_w = max(1, int(dst_w))
    dst_h = max(1, int(dst_h))
    mode = (mode or "contain").strip().lower()
    src_ar = src_w / float(src_h)
    dst_ar = dst_w / float(dst_h)

    if mode == "cover":
        if src_ar > dst_ar:
            h = dst_h
            w = max(1, int(round(h * src_ar)))
        else:
            w = dst_w
            h = max(1, int(round(w / src_ar)))
        x = (dst_w - w) // 2
        y = (dst_h - h) // 2
        return int(x), int(y), int(w), int(h)

    # contain（默认）
    if src_ar > dst_ar:
        w = dst_w
        h = max(1, int(round(w / src_ar)))
    else:
        h = dst_h
        w = max(1, int(round(h * src_ar)))
    x = (dst_w - w) // 2
    y = (dst_h - h) // 2
    return int(x), int(y), int(w), int(h)


def scale_fit_for_export(fit_mode: str) -> str:
    """SequenceFormat.fit_mode → apply_export_settings 的 scale_fit。"""
    m = (fit_mode or "contain").strip().lower()
    if m == "cover":
        return "crop"
    return "pad"


__all__ = [
    "SequenceFormat",
    "SEQUENCE_FORMAT_PRESETS",
    "KNOWN_ASPECTS",
    "parse_aspect",
    "parse_resolution",
    "aspect_from_size",
    "normalize_size",
    "fit_rect",
    "scale_fit_for_export",
    "asdict",
]
