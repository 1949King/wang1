#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""捏脸模板缩略图守卫（2026-10-21）。

语义
====
- **没有缩略图**：属正常（未配置生图后端时脚本会诚实退出 2） -> SKIP，exit 0；
- **有缩略图**：清单必须存在、id 必须在册、sha256/尺寸必须对得上，
  且磁盘上不得出现清单外的孤儿 png -> 否则 exit 1。

为什么只守「有」的那一侧
========================
不强制要求 8 张齐全：生图后端是用户环境依赖，缺图时前端会回落到「色点 + 名称」卡片。
但**一旦生成了图，就不能与清单/产物脱节**（否则换图不更新、孤儿文件永久残留）。
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "vendor" / "shiguang-canvas" / "public" / "face-templates"
MANIFEST = OUT_DIR / "manifest.json"
TS_PATH = ROOT / "vendor" / "packages" / "libtv" / "src" / "faceTemplates.ts"
W, H = 128, 160


def template_ids() -> set[str]:
    src = TS_PATH.read_text(encoding="utf-8")
    return set(re.findall(r'id:\s*"([a-z0-9-]+)"', src))


def main() -> int:
    pngs = sorted(OUT_DIR.glob("*.png")) if OUT_DIR.is_dir() else []
    if not pngs:
        print("SKIP 未生成模板缩略图（无生图后端时属正常；前端回落色点卡片）")
        return 0

    fails: list[str] = []
    if not MANIFEST.is_file():
        print("MASCOT THUMBS FAIL")
        print("  - 存在 " + str(len(pngs)) + " 张缩略图但缺 manifest.json")
        return 1

    try:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print("MASCOT THUMBS FAIL")
        print("  - manifest.json 不是合法 JSON：" + str(exc))
        return 1

    ids = template_ids()
    items = manifest.get("items") or {}
    if not isinstance(items, dict):
        fails.append("manifest.items 不是对象")

    for tid, meta in items.items():
        if tid not in ids:
            fails.append(tid + " 不在 faceTemplates.ts 的模板 id 中（清单越权）")
            continue
        path = OUT_DIR / str((meta or {}).get("file") or (tid + ".png"))
        if not path.is_file():
            fails.append(tid + " 清单有记录但文件缺失")
            continue
        raw = path.read_bytes()
        expect_sha = (meta or {}).get("sha256") or ""
        actual_sha = hashlib.sha256(raw).hexdigest()
        if expect_sha and expect_sha != actual_sha:
            fails.append(tid + " sha256 与清单不符（图被替换但未重跑清单）")

    for path in pngs:
        if path.stem not in items:
            fails.append(path.name + " 是清单外的孤儿缩略图")

    try:
        from PIL import Image

        for path in pngs:
            with Image.open(path) as img:
                if img.size != (W, H):
                    fails.append(path.name + " 尺寸 " + str(img.size) + " != " + str((W, H)))
    except ImportError:
        print("（Pillow 未安装：跳过尺寸校验，sha256 已校验）")

    if fails:
        print("MASCOT THUMBS FAIL")
        for item in fails:
            print("  -", item)
        print("\n修复：重跑 python scripts/render_face_template_thumbs.py --force")
        return 1

    print(
        "OK 模板缩略图一致（" + str(len(items)) + " 张 / " + str(len(ids)) + " 套模板 / "
        "后端 " + str(manifest.get("backend") or "?") + "）"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
