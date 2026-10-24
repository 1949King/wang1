"""画幅（aspect）常量与「画质档 × 画幅」目标尺寸表 —— 单一事实来源。

2026-09-27（V4.40.10）从 `canvas_aigc.py` 外置而来。产品是**竖屏短剧**，而此前整条
链路默认 16:9 横版 `1024x576`，与真实素材（`assets/avatar/*.png` 全为 1024x1536 竖版）
相悖。引入 aspect 维度后尺寸表变成 3 画幅 × 4 档 × 2 介质，内联会撑破
`canvas_aigc.py` 的规模守卫容差（存量文件只许减不许增），故独立成模块。

缺省 `portrait`（竖屏）= 「自动」；前端下拉让用户自选 = 「可选」。
旧调用（只传 quality）自动得到竖版尺寸，无需改动。
"""

from typing import Dict, Tuple

ASPECT_PORTRAIT = "portrait"
ASPECT_LANDSCAPE = "landscape"
ASPECT_SQUARE = "square"
DEFAULT_ASPECT = ASPECT_PORTRAIT
ASPECTS: Tuple[str, ...] = (ASPECT_PORTRAIT, ASPECT_LANDSCAPE, ASPECT_SQUARE)

# 画质档顺序：(draft, standard, fine, cinema)
_TIERS: Tuple[str, ...] = ("draft", "standard", "fine", "cinema")

# 画幅 → 四档尺寸（顺序同 _TIERS）。行内紧凑写法，把行数压到最低。
_IMAGE: Dict[str, Tuple[str, ...]] = {
    ASPECT_PORTRAIT: ("576x1024", "768x1344", "864x1536", "1080x1920"),
    ASPECT_LANDSCAPE: ("1024x576", "1024x576", "1280x720", "1920x1080"),
    ASPECT_SQUARE: ("768x768", "1024x1024", "1024x1024", "1440x1440"),
}
_VIDEO: Dict[str, Tuple[str, ...]] = {
    ASPECT_PORTRAIT: ("540x960", "720x1280", "720x1280", "1080x1920"),
    ASPECT_LANDSCAPE: ("960x540", "1280x720", "1280x720", "1920x1080"),
    ASPECT_SQUARE: ("640x640", "720x720", "720x720", "1080x1080"),
}


def resolve(quality_tier: str, is_video: bool, aspect: str) -> Tuple[str, str]:
    """按画质档 + 介质 + 画幅给出 (尺寸, 归一化画幅)。

    未知档位回退 standard、未知画幅回退 DEFAULT_ASPECT（竖屏），保证不抛错。
    """
    table = _VIDEO if is_video else _IMAGE
    a = aspect if aspect in table else DEFAULT_ASPECT
    try:
        idx = _TIERS.index(quality_tier)
    except ValueError:
        idx = _TIERS.index("standard")
    return table[a][idx], a
