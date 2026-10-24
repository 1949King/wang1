#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""形象素材守卫：清单与磁盘双向一致 / 同画布 / 质心对齐（2026-10-20 扩展）。

为什么需要
==========
表情帧是「可选素材」：`mascotFrames.ts` 声明 ready=true 但文件缺失 → 运行时 404；
文件存在但没登记 → 死资源，永远没人用。两个方向都是静默失败，必须机器守。

另外两条是**渲染前提**（不是审美）：
1. 所有帧必须 316×480 同画布 —— 否则叠放会位移；
2. alpha 质心与 neutral 偏差 ≤ 2px（实测现有三帧偏差 ≤ 0.2px）——
   否则换表情时整个人会「跳一下」。

跑法: python _verify/check_mascot_assets.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRAMES_DIR = ROOT / "vendor" / "shiguang-canvas" / "public" / "mascot"
MANIFEST = ROOT / "vendor" / "packages" / "libtv" / "src" / "mascot" / "mascotFrames.ts"
CARD = ROOT / "assets" / "mascot" / "shilan-主形象卡-v3-成年比例.png"

CANVAS = (316, 480)
CENTROID_TOLERANCE = 2.0
MANDATORY = ("pet_neutral.png", "pet_blink.png", "pet_cheer.png")


def _parse_manifest(text: str) -> dict[str, bool]:
    """从 mascotFrames.ts 抓 {file: ready}（正则跨行匹配，容忍对象换行）。"""
    entries = re.findall(r'file:\s*"([^"]+)"\s*,\s*ready:\s*(true|false)', text)
    return {name: (flag == "true") for name, flag in entries}


def _centroid(image) -> tuple[float, float] | None:
    rgba = image.convert("RGBA")
    width, height = rgba.size
    alpha = rgba.getchannel("A").load()
    sx = sy = count = 0
    for y in range(0, height, 2):
        for x in range(0, width, 2):
            if alpha[x, y] > 16:
                sx += x
                sy += y
                count += 1
    if count == 0:
        return None
    return (sx / count, sy / count)


def main() -> int:
    fails: list[str] = []

    try:
        from PIL import Image
    except ImportError:
        print("SKIP: Pillow 未安装，无法校验尺寸/质心（不误报为失败）")
        return 0

    if not MANIFEST.is_file():
        print("MASCOT ASSETS FAIL")
        print("  - 缺失清单 mascotFrames.ts")
        return 1

    declared = _parse_manifest(MANIFEST.read_text(encoding="utf-8"))
    if not declared:
        fails.append("mascotFrames.ts 未解析到任何帧声明（正则口径可能变了）")

    # ① 必备帧存在且在册
    for name in MANDATORY:
        if not (FRAMES_DIR / name).is_file():
            fails.append(f"缺失必备帧 {name}")
        if name not in declared:
            fails.append(f"必备帧 {name} 未在 mascotFrames.ts 登记")

    # ② 声明 → 磁盘（ready 必须真有文件；未 ready 不该有文件）
    for name, ready in declared.items():
        path = FRAMES_DIR / name
        if ready and not path.is_file():
            fails.append(f"{name} 声明 ready=true 但文件缺失（运行时 404）")
        if not ready and path.is_file():
            fails.append(f"{name} 文件已存在但仍标 ready=false（改回 true，或删掉文件）")

    # ③ 磁盘 → 声明（防死资源）
    for path in sorted(FRAMES_DIR.glob("pet_*.png")):
        if path.name not in declared:
            fails.append(f"{path.name} 在磁盘上但未在 mascotFrames.ts 登记")

    # ④ 尺寸 + 质心对齐（仅校验存在的帧）
    base_centroid = None
    neutral = FRAMES_DIR / "pet_neutral.png"
    if neutral.is_file():
        with Image.open(neutral) as image:
            if image.size != CANVAS:
                fails.append(f"pet_neutral.png 尺寸 {image.size} != {CANVAS}")
            else:
                base_centroid = _centroid(image)

    for name in declared:
        path = FRAMES_DIR / name
        if not path.is_file():
            continue
        with Image.open(path) as image:
            if image.size != CANVAS:
                fails.append(f"{name} 尺寸 {image.size} != {CANVAS}")
                continue
            if name == "pet_neutral.png" or base_centroid is None:
                continue
            centroid = _centroid(image)
            if centroid is None:
                fails.append(f"{name} 全透明（alpha 质心不存在）")
                continue
            distance = (
                (centroid[0] - base_centroid[0]) ** 2 + (centroid[1] - base_centroid[1]) ** 2
            ) ** 0.5
            if distance > CENTROID_TOLERANCE:
                fails.append(
                    f"{name} 质心偏差 {distance:.1f}px > {CENTROID_TOLERANCE}px（换表情会位移）"
                )

    # ⑤ 主形象卡
    if not CARD.is_file():
        fails.append(f"缺失主形象卡 {CARD.name}")

    if fails:
        print("MASCOT ASSETS FAIL")
        for item in fails:
            print("  -", item)
        print(
            "\n修复：帧放 public/mascot/pet_<id>.png（316x480 透明底、质心对齐），"
            "并在 mascotFrames.ts 把对应 ready 改 true"
        )
        return 1

    ready_count = sum(1 for ready in declared.values() if ready)
    print(
        f"OK 形象素材完整（{len(declared)} 帧登记 / {ready_count} 帧就绪 / "
        f"同画布 {CANVAS[0]}x{CANVAS[1]} / 质心 ≤{CENTROID_TOLERANCE}px）"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
