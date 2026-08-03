#!/usr/bin/env python3
"""
同步拾光剪影项目知识库目录。

扫描仓库内 Markdown，刷新：
  - docs/knowledge/sources/MANIFEST.md
  - docs/knowledge/catalog.json

不复制巨型方案全文进知识库（避免漂移）；只编目 + 链接。
知识库正文（00–07）由人工/Agent 维护，本脚本不覆盖。

用法（项目根）：
  python scripts/sync_knowledge.py
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KB = ROOT / "docs" / "knowledge"
MANIFEST = KB / "sources" / "MANIFEST.md"
CATALOG = KB / "catalog.json"

SKIP_DIR_PARTS = {
    ".git",
    ".venv",
    ".venv312",
    "venv",
    "bmf_env",
    "packaging_env",
    "node_modules",
    "thirdparty",
    "__pycache__",
    ".pytest_cache",
    "libopenshot",
    "openshot-qt",
    "site-packages",
}


def should_skip(path: Path) -> bool:
    parts = set(path.parts)
    if parts & SKIP_DIR_PARTS:
        return True
    # skip nested venv-like
    for p in path.parts:
        if p.startswith(".venv") or p.endswith("_env"):
            return True
    return False


def first_heading(text: str) -> str:
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#"):
            return re.sub(r"^#+\s*", "", s).strip()[:120]
    return "(无标题)"


def categorize(rel: str) -> str:
    rel_posix = rel.replace("\\", "/")
    if rel_posix.startswith("docs/knowledge/"):
        return "knowledge"
    if rel_posix.startswith("docs/"):
        return "docs"
    if rel_posix.startswith(".workbuddy/"):
        return "workbuddy"
    if rel_posix.startswith(".claude/"):
        return "claude"
    if rel_posix.startswith(".trae/"):
        return "trae"
    if rel_posix.startswith("app/"):
        return "app"
    if "/" not in rel_posix and rel_posix.endswith(".md"):
        return "root"
    return "other"


def scan() -> list[dict]:
    items: list[dict] = []
    for path in ROOT.rglob("*.md"):
        if should_skip(path):
            continue
        try:
            rel = path.relative_to(ROOT).as_posix()
            raw = path.read_text(encoding="utf-8", errors="replace")
            size_kb = round(path.stat().st_size / 1024, 1)
            items.append(
                {
                    "path": rel,
                    "size_kb": size_kb,
                    "title": first_heading(raw),
                    "category": categorize(rel),
                    "lines": raw.count("\n") + 1,
                }
            )
        except OSError as e:
            print(f"skip {path}: {e}", file=sys.stderr)
    items.sort(key=lambda x: (x["category"], x["path"]))
    return items


def write_manifest(items: list[dict], generated_at: str) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    order = ["knowledge", "root", "docs", "workbuddy", "app", "claude", "trae", "other"]
    labels = {
        "knowledge": "知识库正文",
        "root": "根目录方案/报告",
        "docs": "docs/",
        "workbuddy": ".workbuddy 记忆",
        "app": "app/ 内文档",
        "claude": ".claude skills",
        "trae": ".trae",
        "other": "其他",
    }
    lines = [
        "# 源文档清单（MANIFEST）",
        "",
        "> 由 `scripts/sync_knowledge.py` 自动生成。勿手改表格（会被覆盖）。",
        f">",
        f"> 上次同步：`{generated_at}` · 共 **{len(items)}** 个 Markdown",
        "",
        "知识库入口：[INDEX.md](../INDEX.md)",
        "",
    ]
    by_cat: dict[str, list[dict]] = {}
    for it in items:
        by_cat.setdefault(it["category"], []).append(it)

    for cat in order:
        group = by_cat.get(cat) or []
        if not group:
            continue
        lines.append(f"## {labels.get(cat, cat)}（{len(group)}）")
        lines.append("")
        lines.append("| 路径 | KB | 标题 |")
        lines.append("|------|-----:|------|")
        for it in group:
            # link relative from sources/
            link = f"../../{it['path']}" if not it["path"].startswith("docs/knowledge/") else f"../{Path(it['path']).name}"
            if it["path"].startswith("docs/knowledge/"):
                # deeper paths
                rel_from_sources = Path("..") / Path(it["path"]).relative_to("docs/knowledge")
                link = rel_from_sources.as_posix()
            else:
                link = ("../../" + it["path"]).replace("\\", "/")
            title = it["title"].replace("|", "\\|")
            lines.append(f"| [{it['path']}]({link}) | {it['size_kb']} | {title} |")
        lines.append("")

    MANIFEST.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_catalog(items: list[dict], generated_at: str) -> None:
    KB.mkdir(parents=True, exist_ok=True)
    payload = {
        "project": "拾光剪影",
        "generated_at": generated_at,
        "knowledge_index": "docs/knowledge/INDEX.md",
        "core_docs": [
            "docs/knowledge/00-overview.md",
            "docs/knowledge/01-glossary.md",
            "docs/knowledge/02-architecture.md",
            "docs/knowledge/03-editor-pipeline.md",
            "docs/knowledge/04-module-map.md",
            "docs/knowledge/05-known-issues.md",
            "docs/knowledge/06-roadmap.md",
            "docs/knowledge/07-coding-rules.md",
        ],
        "live_paths": [
            "app/main_qt6.py",
            "app/modules/lego/editor_module.py",
            "app/modules/lego/timeline_widget.py",
            "app/core/preview_manager.py",
            "app/core/waveform_generator.py",
            "app/core/editor_scheduler.py",
        ],
        "documents": items,
        "counts": {},
    }
    counts: dict[str, int] = {}
    for it in items:
        counts[it["category"]] = counts.get(it["category"], 0) + 1
    payload["counts"] = counts
    CATALOG.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    generated_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    items = scan()
    write_manifest(items, generated_at)
    write_catalog(items, generated_at)
    print(f"[sync_knowledge] synced {len(items)} markdown files")
    print(f"  -> {MANIFEST.relative_to(ROOT)}")
    print(f"  -> {CATALOG.relative_to(ROOT)}")
    for k, v in sorted(CATALOG and json.loads(CATALOG.read_text(encoding='utf-8'))["counts"].items()):
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
