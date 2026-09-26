#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""单文件规模守卫（2026-09-25 V4.39.4 新增）—— 阻止技术债「继续增长」。

为什么需要（实测结论）：
    `editor_module.py` 已 **9,717 行**（09-19 时 9,479 → 仍在涨）；
    app/ 有 8 个、画布 src/ 有 4 个 >2000 行文件。**没有任何机制阻止它继续变大**
    ⇒ 每加一个功能，认知负荷就再涨一截。

本守卫**不要求立刻拆分**（那是大工程、高风险），而是把现状冻结为基线：
    · 基线内文件：允许波动 ≤ _TOLERANCE 行；**持续增长即失败**
    · 基线外新超标：失败（新文件不许一上来就 >2000 行）
    · 基线内文件**变小**：PASS，并提示「已收敛，可从基线移除」

跑法: python _verify/check_file_size.py

修复指引：
    1. 新超标 → 按职责拆模块（项目已有 mixin 拆分先例：
       `editor_agent_runtime_mixin.py` / `editor_agent_panel_mixin.py`）
    2. 存量膨胀 → 拆分后**同时下调本文件基线**（基线下调 = 债务收敛的正反馈）
    3. 千万别把基线往上调 —— 那等于宣布「债务可以继续涨」
"""
from __future__ import annotations

import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 行数阈值：超过即「需要拆分」
_LIMIT = 2000
# 允许波动（正常增删代码的噪声）；超过即视为「债务增长」
_TOLERANCE = 30

_SKIP_DIRS = {"__pycache__", "node_modules", "dist", ".git", "build",
              "_archive", ".venv312", "temp"}

_TARGETS = [
    ("app", (".py",)),
    ("vendor/shiguang-canvas/src", (".ts", ".tsx")),
]

# ── 基线（2026-09-25 实测）──────────────────────────────────────────
# 格式: 相对路径 → 行数。**只减不增**：拆分后请下调这里的数字。
BASELINE: dict = {
    # app/（8 个）
    "app/modules/lego/editor_module.py": 9717,
    # A4 批次 1+2/3（2026-09-27）：GET 25 端点迁到 canvas_routes_get.py（650 行）、
    # POST 29 端点迁到 canvas_routes_post.py（1,183 行）
    # → 3,273 → **1,740**，两次下调基线（债务收敛，守卫指引的正反馈）
    "app/core/canvas_server.py": 1740,
    "app/core/canvas_aigc.py": 2905,
    "app/modules/lego/settings_module.py": 2823,
    "app/modules/lego/video_processor.py": 2732,
    "app/modules/lego/editor_agent_panel_mixin.py": 2330,
    "app/modules/lego/extensions_module.py": 2198,
    "app/modules/lego/drama_understanding_engine.py": 2160,
    # vendor/shiguang-canvas/src（4 个）
    "vendor/shiguang-canvas/src/Stage3D.tsx": 4660,
    "vendor/shiguang-canvas/src/riggedHumanoid.ts": 3707,
    "vendor/shiguang-canvas/src/CanvasShell.tsx": 3199,
    "vendor/shiguang-canvas/src/store.ts": 2452,
    # V4.39.8 异步接线（generateForNode→runGeneration）后越线 2000；
    # 存量文件冻结入基线，⚠️ 待拆分（异步编排宜独立成模块），拆分后请下调。
    "vendor/shiguang-canvas/src/bridge.ts": 2016,
}


def _count_lines(path: str) -> int:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return sum(1 for _ in f)
    except OSError:
        return -1


def _scan() -> dict:
    """扫描目标目录，返回 {rel_path: lines}（只收 >_LIMIT 的）。"""
    found: dict = {}
    for rel_root, exts in _TARGETS:
        base = os.path.join(ROOT, rel_root)
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for fn in filenames:
                if not fn.endswith(exts):
                    continue
                full = os.path.join(dirpath, fn)
                n = _count_lines(full)
                if n > _LIMIT:
                    rel = os.path.relpath(full, ROOT).replace("\\", "/")
                    found[rel] = n
    return found


def main() -> int:
    current = _scan()
    fails: list = []
    grown: list = []
    shrunk: list = []
    new_over: list = []
    gone: list = []

    for rel, n in sorted(current.items(), key=lambda kv: -kv[1]):
        base = BASELINE.get(rel)
        if base is None:
            new_over.append((rel, n))
            fails.append(f"新增超标文件 {rel}（{n} 行 > {_LIMIT}）")
        elif n > base + _TOLERANCE:
            grown.append((rel, base, n))
            fails.append(f"存量债务增长 {rel}：{base} → {n} 行"
                         f"（+{n - base}，容差 {_TOLERANCE}）")
        elif n < base - _TOLERANCE:
            shrunk.append((rel, base, n))

    for rel, base in BASELINE.items():
        if rel not in current:
            gone.append((rel, base))

    print("=" * 62)
    print(f"单文件规模守卫（阈值 {_LIMIT} 行）")
    print("=" * 62)
    print(f"当前超标文件：{len(current)} 个（基线 {len(BASELINE)} 个）")

    if grown:
        print("\n✗ 存量债务增长（必须拆分或下调基线）：")
        for rel, base, n in grown:
            print(f"    {rel}  {base} → {n}（+{n - base}）")
    if new_over:
        print("\n✗ 新增超标文件：")
        for rel, n in new_over:
            print(f"    {rel}  {n} 行")

    if shrunk:
        print("\n✓ 已收敛（可从 BASELINE 下调/移除）：")
        for rel, base, n in shrunk:
            print(f"    {rel}  {base} → {n}（-{base - n}）")

    if gone:
        print("\n· 已消失（拆分/删除/改名？确认后从 BASELINE 移除）：")
        for rel, base in gone:
            print(f"    {rel}（基线 {base}）")

    if not (grown or new_over):
        print("\n✓ 无新增债务（存量 12 个已冻结为基线，只许减不许增）")
        if not shrunk and not gone:
            print("  · 提示：拆掉一个就能在这里看到「已收敛」正反馈")
        print("\nOK 单文件规模守卫通过")
        return 0

    print(f"\n{'=' * 62}")
    print(f"✗ 失败 {len(fails)} 项：")
    for f in fails:
        print(f"  - {f}")
    print("\n修复指引：拆模块（可参考 editor_agent_*_mixin 的拆分先例），"
          "拆完下调本文件 BASELINE。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
