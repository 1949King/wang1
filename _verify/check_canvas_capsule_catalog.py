#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""画布「意图胶囊目录 + CodeVideoSpec 前端镜像」守卫（2026-10-20）

锁四件事：
  A. 能力 id 真实存在：胶囊目录里每个 capability 都在后端 agent_capability_catalog；
  B. 节点 kind 真实存在：胶囊引用的 nodeKinds 都在前端真源 ports.ts；
  C. 契约常量同源：codeVideoSpec.ts 的版本/帧率/文字层/上限与后端 spec.py 一致；
  D. 目录卫生：胶囊 id 唯一、7 阶段全覆盖。

用法（项目根执行）：
    .venv312\\Scripts\\python.exe _verify/check_canvas_capsule_catalog.py
"""
from __future__ import annotations

import io
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

CANVAS_CORE = os.path.join(ROOT, "vendor", "packages", "canvas-core", "src")
CAPSULE_TS = os.path.join(CANVAS_CORE, "intentCapsuleCatalog.ts")
SPEC_TS = os.path.join(CANVAS_CORE, "codeVideoSpec.ts")
PORTS_TS = os.path.join(CANVAS_CORE, "ports.ts")

_failures: list = []


def check(cond, msg):
    if cond:
        print(f"  ✓ {msg}")
    else:
        print(f"  ✗ {msg}")
        _failures.append(msg)


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


# ── A. 能力 id 必须真实存在 ──
print("[A] 胶囊目录 → 后端能力目录")
from app.core import agent_capability_catalog as cat

_capsule_src = _read(CAPSULE_TS)
_used_caps = set(re.findall(
    r'"((?:editor|pipeline|canvas|model|ext|workflow)\.[a-z0-9_.]+)"', _capsule_src
))
_known = set(cat.registered_capability_ids())
_missing = sorted(_used_caps - _known)
check(bool(_used_caps), f"胶囊引用了 {len(_used_caps)} 个能力 id")
check(not _missing, f"全部能力 id 在册（缺失：{_missing[:5]}）")

# ── B. 节点 kind 必须真实存在 ──
print("[B] 胶囊目录 → 前端 ports.ts 节点 kind")
_ports_src = _read(PORTS_TS)
_known_kinds = set(re.findall(r"^\s{2}([A-Za-z][A-Za-z0-9_]*)\s*:\s*\{", _ports_src, re.M))
_capsule_kinds = set()
for block in re.findall(r"nodeKinds\s*:\s*\[([^\]]*)\]", _capsule_src, re.S):
    _capsule_kinds |= set(re.findall(r'"([A-Za-z][A-Za-z0-9_]*)"', block))
_missing_kinds = sorted(_capsule_kinds - _known_kinds)
check(len(_known_kinds) >= 20, f"ports.ts 解析到 {len(_known_kinds)} 个节点 kind")
check(not _missing_kinds, f"胶囊节点 kind 全部存在（缺失：{_missing_kinds[:5]}）")

# ── C. CodeVideoSpec 常量同源 ──
print("[C] codeVideoSpec.ts 常量 ↔ 后端 spec.py")
from app.core.code_video.spec import (
    ALLOWED_FPS,
    DEFAULT_MAX_CLIPS,
    DEFAULT_MAX_DURATION,
    MAX_CANVAS_H,
    MAX_CANVAS_W,
    SPEC_VERSION,
    TEXT_KINDS,
)

_spec_ts = _read(SPEC_TS)


def _const(name: str) -> str:
    m = re.search(rf"export const {name}\s*=\s*([^;]+);", _spec_ts)
    if not m:
        return ""
    raw = m.group(1).strip()
    return re.sub(r"\s*as\s+const\s*$", "", raw).strip()


check(_const("SPEC_VERSION").strip('"') == SPEC_VERSION,
      f"SPEC_VERSION={SPEC_VERSION}")
check(_const("ALLOWED_FPS").replace(" ", "") == "[" + ",".join(str(x) for x in ALLOWED_FPS) + "]",
      f"ALLOWED_FPS={list(ALLOWED_FPS)}")
check(_const("TEXT_KINDS").replace(" ", "") == '["' + '","'.join(TEXT_KINDS) + '"]',
      f"TEXT_KINDS={list(TEXT_KINDS)}")
check(_const("MAX_DURATION") == str(int(DEFAULT_MAX_DURATION)), f"MAX_DURATION={DEFAULT_MAX_DURATION}")
check(_const("MAX_CLIPS") == str(DEFAULT_MAX_CLIPS), f"MAX_CLIPS={DEFAULT_MAX_CLIPS}")
check(_const("MAX_CANVAS_W") == str(MAX_CANVAS_W), f"MAX_CANVAS_W={MAX_CANVAS_W}")
check(_const("MAX_CANVAS_H") == str(MAX_CANVAS_H), f"MAX_CANVAS_H={MAX_CANVAS_H}")

# ── D. 目录卫生 ──
print("[D] 胶囊目录卫生")
_ids = re.findall(r'id:\s*"(capsule\.[A-Za-z0-9_]+)"', _capsule_src)
check(len(_ids) == len(set(_ids)) and bool(_ids), f"胶囊 id 唯一（{len(_ids)} 个）")
_stages = set(re.findall(r'stage:\s*"([a-z]+)"', _capsule_src))
check(_stages == {"idea", "script", "storyboard", "generate", "edit", "deliver", "govern"},
      f"7 阶段全覆盖（实际 {sorted(_stages)}）")

print()
if _failures:
    print(f"✗ 失败 {len(_failures)} 项")
    sys.exit(1)
print("OK 画布胶囊目录 + CodeVideoSpec 前端镜像守卫全绿")
