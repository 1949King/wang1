# -*- coding: utf-8 -*-
"""回归：画布双库漂移 —— 主库 shiguang-canvas ↔ 副库 AI-Canvas-tauri/src/libtv

背景：
  两个画布包目前靠**手工同步**（外加 5 个数据契约文件的 Windows 硬链接）维持一致。
  2026-09-13 实测：84 vs 77 文件 / 62 一致 / **15 分叉** / **7 缺失**（含整个 novice/ 小白模式）。
  抽包成 `@shiguang/libtv` 的大改造（P0-1）还没开始，但**漂移必须立刻止血**。

策略（基线制，避免存量问题淹没新信号）：
  - 5 个数据契约文件**必须字节一致**（硬链接断了就算 FAIL）
  - 基线之外的**新分叉 / 新缺失** → FAIL（这才是要抓的东西）
  - 基线内的文件**恢复一致** → 报「已收敛」，提示从基线移除（不失败，鼓励收敛）

用法：
    python _verify/check_canvas_dual_repo.py
    python _verify/check_canvas_dual_repo.py --update   # 把当前状态写回基线（谨慎！）
"""
from __future__ import annotations

import argparse
import hashlib
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MAIN_REL = os.path.join("vendor", "shiguang-canvas", "src")
SUB_REL = os.path.join("vendor", "AI-Canvas-tauri", "src", "libtv")

# 5 个数据契约文件：靠 Windows 硬链接共享 inode，必须字节一致
MUST_SYNC = [
    "stores/templates.ts",
    "stores/schema-migrations.ts",
    "stores/history-store.ts",
    "stores/project-storage.ts",
    "stores/migrations.ts",
]

# ── 基线（2026-09-13 实测，勿凭印象改）──
BASELINE_DIVERGED = {
}
# 副库尚未同步（主库独有）：咬合缝/槽位高亮 + 整个小白模式
BASELINE_MISSING = {
    "comfyToCanvas.test.ts",
    "magnetic/MagneticEngine.test.ts",
    "magnetic/bonds.test.ts",
    "magnetic/reflow.test.ts",
    "stage3dScene.test.ts",
    "tauri-api-shim.d.ts",
}


def _walk(root: str) -> dict:
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ("node_modules", "dist")]
        for f in filenames:
            if f.endswith((".ts", ".tsx")):
                p = os.path.join(dirpath, f)
                out[os.path.relpath(p, root).replace("\\", "/")] = p
    return out


def _md5(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.md5(fh.read()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--update", action="store_true",
                    help="把当前实测状态写回本脚本的基线（仅在确认漂移是有意的时候用）")
    args = ap.parse_args()

    main_root = os.path.join(ROOT, MAIN_REL)
    sub_root = os.path.join(ROOT, SUB_REL)
    if not os.path.isdir(main_root) or not os.path.isdir(sub_root):
        print(f"✗ 找不到画布目录：{MAIN_REL} / {SUB_REL}")
        return 1

    mains = _walk(main_root)
    subs = _walk(sub_root)

    same, diverged, missing = [], [], []
    for rel in sorted(mains):
        sub_path = os.path.join(sub_root, rel.replace("/", os.sep))
        if not os.path.exists(sub_path):
            missing.append(rel)
        elif _md5(mains[rel]) == _md5(sub_path):
            same.append(rel)
        else:
            diverged.append(rel)
    only_sub = sorted(set(subs) - set(mains))

    print(f"主库 {len(mains)} 文件 · 副库 {len(subs)} 文件")
    print(f"一致 {len(same)} · 分叉 {len(diverged)} · 副库缺失 {len(missing)}")

    if args.update:
        _write_baseline(diverged, missing)
        print("✓ 基线已更新（--update）")
        return 0

    failures = []

    print("\n[1] 数据契约文件必须字节一致（硬链接是否还在）")
    for rel in MUST_SYNC:
        sub_path = os.path.join(sub_root, rel.replace("/", os.sep))
        ok = os.path.exists(sub_path) and _md5(mains[rel]) == _md5(sub_path)
        print(f"  {'✓' if ok else '✗'} {rel}")
        if not ok:
            failures.append(f"数据契约文件分叉（硬链接可能断了）: {rel}")

    print("\n[2] 新分叉（基线之外）")
    new_diverged = [r for r in diverged if r not in BASELINE_DIVERGED]
    if new_diverged:
        for r in new_diverged:
            print(f"  ✗ 新分叉: {r}")
            failures.append(f"新分叉: {r}")
    else:
        print(f"  ✓ 无新分叉（基线内 {len(diverged)} 个已知分叉保持观察）")

    print("\n[3] 新缺失（基线之外）")
    new_missing = [r for r in missing if r not in BASELINE_MISSING]
    if new_missing:
        for r in new_missing:
            print(f"  ✗ 副库新增缺失: {r}")
            failures.append(f"副库新增缺失: {r}")
    else:
        print(f"  ✓ 无新缺失（基线内 {len(missing)} 个已知缺失保持观察）")

    print("\n[4] 收敛提示")
    converged = [r for r in BASELINE_DIVERGED if r in same]
    if converged:
        for r in converged:
            print(f"  · 已收敛（可从 BASELINE_DIVERGED 移除）: {r}")
    else:
        print("  · 暂无")

    if only_sub:
        print("\n[5] 副库独有文件（主库没有）")
        for r in only_sub:
            print(f"  · {r}")

    print()
    if failures:
        print(f"✗ 失败 {len(failures)} 项：")
        for f in failures:
            print("   -", f)
        print("  提示：确认是有意同步后再跑 `--update` 刷新基线，别拿它当消警告按钮。")
        return 1
    print("OK 双库无新增漂移")
    return 0


def _write_baseline(diverged, missing) -> None:
    path = os.path.abspath(__file__)
    src = open(path, encoding="utf-8").read()
    new_div = "BASELINE_DIVERGED = {\n" + "".join(f'    "{r}",\n' for r in sorted(diverged)) + "}"
    new_mis = "BASELINE_MISSING = {\n" + "".join(f'    "{r}",\n' for r in sorted(missing)) + "}"
    import re
    src = re.sub(r"BASELINE_DIVERGED = \{[^}]*\}", new_div, src, count=1)
    src = re.sub(r"BASELINE_MISSING = \{[^}]*\}", new_mis, src, count=1)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(src)


if __name__ == "__main__":
    sys.exit(main())
