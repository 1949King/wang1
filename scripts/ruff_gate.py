#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RUFF 存量棘轮门禁：新增文件必须 0 违规，已有文件按文件记基线、只减不增。

## 为什么不是「直接 ruff check 暂存文件」

2026-10-07 定案。原 hook ① 是对暂存文件直接 `ruff check --no-fix`，其**意图**
（见 hook 注释）是「只拦本次改动的文件」＝增量严格；但**实现**是整文件判定，
于是踩到一个结构性缺陷：

  `app/modules/lego/editor_module.py` 有 52 处**历史**违规，而该文件在冻结区、
  是剪辑核心（9479 行）。任何对它的正当改动，都会被这 52 处与本次毫无关系的
  存量债拦死 ⇒ **等于冻结核心文件永远无法提交**。

实测确认这不是个别现象：白名单范围（app/modules/lego · app/core · ai_tools）
下约 250 个文件带存量违规，其中大文件动辄 40~80 处。这些文件最后一次提交多在
2026-09-21/22，**早于 hook 诞生（2026-09-26）**，因此从未被门禁扫过。

⇒ 按项目既有范式（`scripts/stability_gate.py` + `docs/knowledge/stability_gate_baseline.json`）
改成**增量棘轮**：存量登记为基线，只许减少；不在基线里的文件（＝新文件）必须 0 违规。

## 语义

- 门禁**没有放松**：任何「新增」违规（新文件 >0、或已有文件超过其基线）仍然拦截。
- 与 stability_gate 的区别：后者是全局计数基线，本门禁是**逐文件**基线——
  防止「A 文件修 3 处、B 文件加 3 处」这种此消彼长的钻空子。

## 用法

    python scripts/ruff_gate.py              # 检查**暂存**的受控 .py（pre-commit 调用）
    python scripts/ruff_gate.py --all        # 检查白名单全部目录（全量体检）
    python scripts/ruff_gate.py --report     # 打印当前存量（含与基线差异）
    python scripts/ruff_gate.py --update     # 用当前存量重写基线
    python scripts/ruff_gate.py --update --force   # 允许抬高既有权/为新文件建基线

`--update` 的自我约束（防把棘轮当后门）：
  · 抬高**已有**文件的基线 → 必须显式 `--force`；
  · 为 **HEAD 里不存在的新文件**建基线 → 必须显式 `--force`（新文件本该干净）；
  · 降低基线 / 新增「HEAD 里已存在的」文件条目 → 直接允许（属清理与补登记）。

ruff 可执行体来源：环境变量 `SHIGUANG_RUFF`（如 `"C:/Python314/python.exe -m ruff"`），
否则自动探测（`sys.executable -m ruff` → `C:/Python314/python.exe -m ruff` → `ruff`）。
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "docs" / "knowledge" / "ruff_gate_baseline.json"

# 受控范围：与原 hook ① 的 grep 白名单严格一致（勿擅自扩大，否则基线要重做）
WHITELIST_PREFIXES: Tuple[str, ...] = ("app/modules/lego/", "app/core/", "ai_tools/")

# --all 模式的扫描根
SCAN_DIRS: Tuple[str, ...] = ("app/core", "app/modules/lego", "ai_tools")


# ────────────────────────────── ruff 调用 ──────────────────────────────

def _ruff_cmd() -> List[str]:
    """定位可用的 ruff 调用方式。"""
    env = os.environ.get("SHIGUANG_RUFF")
    candidates: List[List[str]] = []
    if env:
        candidates.append(shlex.split(env, posix=False))
    candidates.append([sys.executable, "-m", "ruff"])
    candidates.append(["C:/Python314/python.exe", "-m", "ruff"])
    candidates.append(["ruff"])
    for cand in candidates:
        if not cand:
            continue
        if len(cand) == 1 and shutil.which(cand[0]) is None:
            continue
        try:
            p = subprocess.run(cand + ["--version"], capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            continue
        if p.returncode == 0 and "ruff" in (p.stdout or "").lower():
            return cand
    raise SystemExit(
        "✗ 找不到可用的 ruff。请设置环境变量 SHIGUANG_RUFF，例如\n"
        '    export SHIGUANG_RUFF="C:/Python314/python.exe -m ruff"'
    )


def _rel_posix(p: str) -> str:
    """绝对/相对路径 → 仓库内 POSIX 相对路径。"""
    f = Path(p)
    try:
        f = f.resolve()
    except OSError:
        pass
    try:
        return f.relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return Path(p).as_posix()


def _run_ruff(cmd: List[str], targets: List[str]) -> Dict[str, int]:
    """跑一次 ruff，返回 {仓库内相对路径: 违规数}。"""
    if not targets:
        return {}
    argv = cmd + ["check", "--no-fix", "--force-exclude", "--output-format=json"] + targets
    p = subprocess.run(argv, cwd=str(ROOT), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if p.returncode not in (0, 1):  # 1 = 有违规，属正常返回
        raise SystemExit(f"✗ ruff 执行失败（rc={p.returncode}）：\n{(p.stderr or '')[-1500:]}")
    raw = (p.stdout or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise SystemExit(f"✗ ruff 输出不是 JSON：\n{raw[:800]}")
    out: Dict[str, int] = {}
    for item in data:
        rel = _rel_posix(item.get("filename", ""))
        out[rel] = out.get(rel, 0) + 1
    return out


# ────────────────────────────── 目标集合 ──────────────────────────────

def _is_controlled(rel: str) -> bool:
    return rel.endswith(".py") and any(rel.startswith(p) for p in WHITELIST_PREFIXES)


def _staged_files() -> List[str]:
    """--default 模式：本次暂存的受控 .py（新增/修改，不含删除）。"""
    p = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if p.returncode != 0:
        raise SystemExit("✗ 读取暂存区失败（git diff --cached）")
    return [ln.strip() for ln in (p.stdout or "").splitlines() if ln.strip() and _is_controlled(ln.strip())]


def _all_files() -> List[str]:
    targets = [d for d in SCAN_DIRS if (ROOT / d).is_dir()]
    return targets


# ────────────────────────────── 基线 ──────────────────────────────

def _load_baseline() -> Dict[str, int]:
    if not BASELINE.exists():
        return {}
    try:
        data = json.loads(BASELINE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"✗ 基线文件损坏（{BASELINE}）：{exc}")
    files = data.get("files", {})
    return {k: int(v) for k, v in files.items()}


def _write_baseline(files: Dict[str, int]) -> None:
    BASELINE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated": _today(),
        "note": (
            "RUFF 存量棘轮基线（scripts/ruff_gate.py）。语义：逐文件只减不增；"
            "不在此表中的文件＝新文件，必须 0 违规。抬高既有值或为新文件建条目需 --force。"
        ),
        "scope": list(WHITELIST_PREFIXES),
        "files": dict(sorted(files.items())),
    }
    BASELINE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _today() -> str:
    import datetime
    return datetime.date.today().isoformat()


def _exists_at_head(rel: str) -> bool:
    p = subprocess.run(["git", "cat-file", "-e", f"HEAD:{rel}"],
                       cwd=str(ROOT), capture_output=True, text=True)
    return p.returncode == 0


# ────────────────────────────── 主流程 ──────────────────────────────

def _do_update(cmd: List[str], force: bool) -> int:
    counts = _run_ruff(cmd, _all_files())
    base = _load_baseline()
    new_files: Dict[str, int] = {}
    refused: List[str] = []
    raised: List[str] = []

    for rel, n in counts.items():
        if n <= 0:
            continue
        old = base.get(rel)
        if old is None:
            if _exists_at_head(rel) or force:
                new_files[rel] = n
                if not _exists_at_head(rel):
                    raised.append(f"{rel}（新文件建基线 {n}，已 --force 放行）")
            else:
                refused.append(f"{rel}:{n}（HEAD 中不存在＝新文件，必须 0 违规）")
        elif n > old:
            if force:
                new_files[rel] = n
                raised.append(f"{rel}:{old} → {n}")
            else:
                refused.append(f"{rel}:{old} → {n}（抬高基线）")
        else:
            new_files[rel] = n

    # 基线里已归零/已消失的条目：保留归零（不删），便于审计
    for rel, old in base.items():
        new_files.setdefault(rel, counts.get(rel, 0))

    if refused:
        print("✗ 拒绝写入，以下项需要显式 --force：")
        for r in refused:
            print("   ", r)
        return 1

    _write_baseline(new_files)
    total = sum(new_files.values())
    print(f"OK 基线已更新：{len(new_files)} 个文件 / {total} 项存量违规 → {BASELINE}")
    if raised:
        print("   本次抬高：")
        for r in raised:
            print("     ·", r)
    return 0


def _report(cmd: List[str]) -> int:
    counts = _run_ruff(cmd, _all_files())
    base = _load_baseline()
    rows = []
    for rel in set(counts) | set(base):
        n, b = counts.get(rel, 0), base.get(rel, 0)
        flag = ""
        if rel not in base and n > 0:
            flag = " ← 新文件违规（应 0）"
        elif n > b:
            flag = f" ← 超基线（+{n - b}）"
        elif n < b:
            flag = f" ← 已收敛（-{b - n}）"
        rows.append((n, rel, b, flag))
    rows.sort(key=lambda t: (-t[0], t[1]))
    print(f"当前违规总数 {sum(counts.values())} 项 / 基线 {sum(base.values())} 项")
    for n, rel, b, flag in rows:
        if n or b:
            print(f"  {n:>4} (基线 {b:>4})  {rel}{flag}")
    return 0


def _check(cmd: List[str], staged_mode: bool) -> int:
    targets = _staged_files() if staged_mode else _all_files()
    if not targets:
        print("OK 无受控 .py 需要检查（ruff 存量棘轮）")
        return 0
    counts = _run_ruff(cmd, targets)
    base = _load_baseline()

    # staged 模式下 targets 是具体文件；--all 模式下 targets 是目录，需用 counts 的键域
    checked = set(counts) if not staged_mode else set(targets)

    new_file_bad: List[Tuple[str, int]] = []
    over: List[Tuple[str, int, int]] = []
    shrunk: List[Tuple[str, int, int]] = []

    for rel in sorted(checked):
        n = counts.get(rel, 0)
        b = base.get(rel, 0)
        if rel not in base:
            if n > 0:
                new_file_bad.append((rel, n))
        elif n > b:
            over.append((rel, n, b))
        elif n < b:
            shrunk.append((rel, n, b))

    if new_file_bad or over:
        print(f"RUFF GATE FAIL — 发现 {len(new_file_bad) + len(over)} 个文件超出存量基线")
        if over:
            print("\n[超出既有基线]")
            for rel, n, b in over:
                print(f"  - {rel}  {b} → {n}（+{n - b}）")
        if new_file_bad:
            print("\n[新增文件必须 0 违规]")
            for rel, n in new_file_bad:
                print(f"  - {rel}  {n} 项")
        print("\n修复后如需重设基线：python scripts/ruff_gate.py --update --force")
        return 1

    extra = f"（另有 {len(shrunk)} 个文件已收敛）" if shrunk else ""
    print(f"OK ruff 存量棘轮通过：检查 {len(checked)} 个文件，零新增违规{extra}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(add_help=True, description="RUFF 存量棘轮门禁")
    ap.add_argument("--all", action="store_true", help="检查白名单全部目录（默认只查暂存文件）")
    ap.add_argument("--report", action="store_true", help="打印当前存量与基线差异")
    ap.add_argument("--update", action="store_true", help="用当前存量重写基线")
    ap.add_argument("--force", action="store_true", help="配合 --update：允许抬高基线/为新文件建条目")
    args = ap.parse_args()

    cmd = _ruff_cmd()
    if args.update:
        return _do_update(cmd, args.force)
    if args.report:
        return _report(cmd)
    return _check(cmd, staged_mode=not args.all)


if __name__ == "__main__":
    sys.exit(main())
