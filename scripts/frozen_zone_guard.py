#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""冻结区守护：校验已锁定功能的源码哈希是否被改动。

清单: docs/knowledge/frozen_zones.json
基线: docs/knowledge/frozen_zones.hashes.json

用法:
  python scripts/frozen_zone_guard.py              # 检查，有变更则 exit 1
  python scripts/frozen_zone_guard.py --update     # 重写基线（仅解冻后）
  python scripts/frozen_zone_guard.py --list       # 列出保护区
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs" / "knowledge" / "frozen_zones.json"
HASHES = ROOT / "docs" / "knowledge" / "frozen_zones.hashes.json"

MARKER_BEGIN = re.compile(r"#\s*>>>\s*FROZEN:(?P<id>[^\s]+)\s+BEGIN\s*$", re.M)
MARKER_END = re.compile(r"#\s*<<<\s*FROZEN:(?P<id>[^\s]+)\s+END\s*$", re.M)


def _sha(text: str) -> str:
    norm = text.replace("\r\n", "\n").strip() + "\n"
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _find_symbol_source(tree: ast.AST, source: str, name: str) -> Optional[str]:
    lines = source.splitlines(keepends=True)

    def slice_node(node: ast.AST) -> str:
        # lineno/end_lineno 1-based inclusive
        start = node.lineno - 1
        end = getattr(node, "end_lineno", node.lineno) or node.lineno
        return "".join(lines[start:end])

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name:
            return slice_node(node)
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == name:
                    return slice_node(child)
    return None


def _extract_marker_block(source: str, marker_id: str) -> Optional[str]:
    begin = None
    for m in MARKER_BEGIN.finditer(source):
        if m.group("id") == marker_id:
            begin = m.end()
            break
    if begin is None:
        return None
    for m in MARKER_END.finditer(source):
        if m.group("id") == marker_id and m.start() > begin:
            return source[begin:m.start()]
    return None


def collect_hashes(manifest: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    file_cache: Dict[str, Tuple[str, ast.AST]] = {}

    def load(rel: str) -> Tuple[str, ast.AST]:
        if rel not in file_cache:
            text = _read(ROOT / rel)
            file_cache[rel] = (text, ast.parse(text))
        return file_cache[rel]

    for zone in manifest.get("zones", []):
        zid = zone["id"]
        for sym in zone.get("symbols") or []:
            rel, name = sym["file"], sym["name"]
            text, tree = load(rel)
            body = _find_symbol_source(tree, text, name)
            if body is None:
                raise SystemExit(f"[frozen] missing symbol {name} in {rel} (zone {zid})")
            out[f"symbol:{rel}:{name}"] = _sha(body)
        for rel in zone.get("files") or []:
            text = _read(ROOT / rel)
            out[f"file:{rel}"] = _sha(text)
        for mk in zone.get("markers") or []:
            rel, mid = mk["file"], mk["id"]
            text, _ = load(rel)
            block = _extract_marker_block(text, mid)
            if block is None:
                raise SystemExit(f"[frozen] missing marker FROZEN:{mid} in {rel} (zone {zid})")
            out[f"marker:{rel}:{mid}"] = _sha(block)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="冻结区守护")
    ap.add_argument("--update", action="store_true", help="用当前源码重写哈希基线")
    ap.add_argument("--list", action="store_true", help="列出保护区")
    args = ap.parse_args()

    if not MANIFEST.is_file():
        print(f"缺少清单: {MANIFEST}")
        return 2
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    if args.list:
        for z in manifest.get("zones", []):
            n = len(z.get("symbols") or []) + len(z.get("files") or []) + len(z.get("markers") or [])
            print(f"- {z['id']}: {z['title']} ({n} 锁点)")
            for inv in z.get("invariants") or []:
                print(f"    · {inv}")
        return 0

    current = collect_hashes(manifest)

    if args.update:
        payload = {
            "version": manifest.get("version", 1),
            "updated_note": "由 frozen_zone_guard.py --update 生成；勿手改",
            "hashes": current,
        }
        HASHES.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"已更新基线 {HASHES} （{len(current)} 项）")
        return 0

    if not HASHES.is_file():
        print(f"缺少基线，请先: python scripts/frozen_zone_guard.py --update")
        return 2

    baseline = json.loads(HASHES.read_text(encoding="utf-8")).get("hashes") or {}
    drifted: List[str] = []
    missing: List[str] = []
    for key, hv in current.items():
        if key not in baseline:
            missing.append(key)
        elif baseline[key] != hv:
            drifted.append(key)
    extra = [k for k in baseline if k not in current]

    if not drifted and not missing and not extra:
        print(f"OK frozen zones intact ({len(current)} locks)")
        return 0

    print("FROZEN ZONE DRIFT — 禁止在未解冻时改这些代码")
    for k in drifted:
        print(f"  changed: {k}")
    for k in missing:
        print(f"  new/missing-in-baseline: {k}")
    for k in extra:
        print(f"  removed: {k}")
    print("若用户已明确解冻，运行: python scripts/frozen_zone_guard.py --update")
    return 1


if __name__ == "__main__":
    sys.exit(main())
