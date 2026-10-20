#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""形象素材守卫：三帧同画布 / 尺寸一致 / 文件存在（2026-10-20）。

为什么需要：桌宠的 blink / cheer 帧必须与 neutral **同画布同尺寸**，
否则叠放会出现位移（用户会看到「眨眼时整个人跳一下」）。
这条不是审美约束，是渲染前提 —— 所以用机器守，不靠人眼。

跑法: python _verify/check_mascot_assets.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRAMES_DIR = ROOT / "vendor" / "shiguang-canvas" / "public" / "mascot"
CARD = ROOT / "assets" / "mascot" / "shilan-主形象卡-v3-成年比例.png"

EXPECTED = {
    "pet_neutral.png": (316, 480),
    "pet_blink.png": (316, 480),
    "pet_cheer.png": (316, 480),
}


def main() -> int:
    fails: list[str] = []

    try:
        from PIL import Image
    except ImportError:
        print("SKIP: Pillow 未安装，无法校验尺寸（不误报为失败）")
        return 0

    for name, expected in EXPECTED.items():
        path = FRAMES_DIR / name
        if not path.is_file():
            fails.append(f"缺失 {name}")
            continue
        try:
            with Image.open(path) as image:
                actual = image.size
            if actual != expected:
                fails.append(f"{name} 尺寸 {actual} != {expected}")
        except Exception as exc:  # noqa: BLE001 - 守卫要如实报出读图失败
            fails.append(f"{name} 无法读取: {exc}")

    if not CARD.is_file():
        fails.append(f"缺失主形象卡 {CARD.name}")

    if fails:
        print("MASCOT ASSETS FAIL")
        for item in fails:
            print("  -", item)
        print("\n修复：三帧必须是 316x480 同画布（质心对齐 IoU>=0.985）；主形象卡放 assets/mascot/")
        return 1

    print("OK 形象素材完整（3 帧同画布 316x480 + 主形象卡在位）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
