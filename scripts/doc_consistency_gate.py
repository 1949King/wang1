#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文档一致性门禁：防止「代码改了、文档没跟着改」——文档一旦说谎，纪律就从根上松。

## 为什么需要它（实测论据，非推测）

项目把「唯一事实源 = docs/现行技术文档.md」写进了纪律，但**同步是人工动作**：
`app/version.py` / `canvasVersion.ts` / `frozen_zones.json` 一改，文档侧
（README、PROJECT_CONTEXT_PACK、CHANGELOG、现行技术文档）就得跟着改。漏一次，
下次 AI 会话加载到的上下文就是错的 —— 错一条，后面所有决策都偏。

实证漂移（当天发生，不是理论风险）：
  · PROJECT_CONTEXT_PACK 生成当天记 `editor_module.py = 9,717` 行，
    同日实测已是 **9,746**（并发会话改动）⇒ 行数锚点当天就失效。
  · `frozen_zones.json` 的 zone 清单与「现行技术文档 §5」靠人记着同步，
    没有任何机器校验。

## 判定设计（刻意分两级，避免噪声把门禁顶红、然后没人再看）

项目血泪：`stability_gate` 曾因草稿目录噪声长期红、`arch_guard` 曾无参空转
⇒ 门禁一旦常红就形同虚设。所以本门禁**只把能精确判定、不会误报的项设为 ERROR**，
其余一律 WARN 提示、不阻断，交给人工判断。

ERROR（阻断，exit=1）—— 可精确判定：
  E1 画布版本三角：`canvasVersion.ts` 的版本号 == `vendor/shiguang-canvas/package.json`
     的 version，且该版本在 `docs/CHANGELOG.md` 有记录。
  E2 冻结区清单一致：`frozen_zones.json` 里每个 zone id 必须在
     `docs/现行技术文档.md` 出现（防「加了 zone、忘了写文档」）。

WARN（提示，exit=0）—— 需人判断：
  W1 主程序版本锚点：`app/version.py` 的版本应出现在
     `docs/CHANGELOG.md` / `README.md` / `docs/PROJECT_CONTEXT_PACK.md`。
  W2 上下文包新鲜度：PROJECT_CONTEXT_PACK 的快照日期超过 30 天 ⇒ 提示重新生成。

## 用法

    python scripts/doc_consistency_gate.py            # 检查（WARN 不阻断）
    python scripts/doc_consistency_gate.py --strict   # WARN 也当 ERROR（CI 用）
    python scripts/doc_consistency_gate.py --json     # 机器可读输出
    python scripts/doc_consistency_gate.py --selfcheck  # 守卫自证（注入漂移验证能拦）

## 边界

- **不 import 项目代码**（用正则读文件）——避免触发 config_manager 的 wmic 链。
- 只读、不改任何文件；不做自动修复（自动改文档风险高于收益，人工确认）。
- 判定锚点是「字符串是否出现」，不做语义理解，故零误报。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

VERSION_PY = ROOT / "app" / "version.py"
CANVAS_VERSION_TS = ROOT / "vendor" / "shiguang-canvas" / "src" / "canvasVersion.ts"
CANVAS_PKG_JSON = ROOT / "vendor" / "shiguang-canvas" / "package.json"
FROZEN_ZONES = ROOT / "docs" / "knowledge" / "frozen_zones.json"
CURRENT_DOC = ROOT / "docs" / "现行技术文档.md"
CHANGELOG = ROOT / "docs" / "CHANGELOG.md"
README = ROOT / "README.md"
CONTEXT_PACK = ROOT / "docs" / "PROJECT_CONTEXT_PACK.md"

SNAPSHOT_MAX_AGE_DAYS = 30
# 上下文包里的快照日期锚点：优先「快照日期：2026-10-11」，兼容「快照 2026-10-11」/「2026-10-11 生成」
_SNAPSHOT_DATE_RE = re.compile(r"(?:快照日期|快照|生成)[^\d]{0,8}(\d{4}-\d{2}-\d{2})")


@dataclass
class Finding:
    """一条检查结论。level ∈ {PASS, WARN, ERROR}。"""

    code: str
    level: str
    title: str
    detail: str = ""


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)

    def add(self, code: str, level: str, title: str, detail: str = "") -> None:
        self.findings.append(Finding(code, level, title, detail))

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "ERROR"]

    @property
    def warns(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "WARN"]


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _main_version() -> str:
    m = re.search(r'__version__\s*=\s*"([^"]+)"', _read(VERSION_PY))
    return m.group(1) if m else ""


def _canvas_version() -> str:
    m = re.search(r'CANVAS_VERSION\s*=\s*"([^"]+)"', _read(CANVAS_VERSION_TS))
    return m.group(1) if m else ""


def _canvas_pkg_version() -> str:
    m = re.search(r'"version"\s*:\s*"([^"]+)"', _read(CANVAS_PKG_JSON))
    return m.group(1) if m else ""


def check_canvas_version_triangle(r: Report) -> None:
    """E1：画布版本三角（canvasVersion.ts / package.json / CHANGELOG）。"""
    ts_v, pkg_v = _canvas_version(), _canvas_pkg_version()
    if not ts_v or not pkg_v:
        r.add("E1", "ERROR", "画布版本读取失败",
              f"canvasVersion.ts={ts_v or '?'} · package.json={pkg_v or '?'}")
        return
    if ts_v != pkg_v:
        r.add("E1", "ERROR", "画布版本三角不一致",
              f"canvasVersion.ts={ts_v} ≠ package.json={pkg_v} "
              f"（改画布版三件套：canvasVersion.ts → package.json → CHANGELOG）")
        return
    if ts_v not in _read(CHANGELOG):
        r.add("E1", "ERROR", "画布版本未记入 CHANGELOG",
              f"版本 {ts_v} 在 docs/CHANGELOG.md 中找不到记录")
        return
    r.add("E1", "PASS", f"画布版本三角一致（{ts_v}）")


def check_frozen_zone_sync(r: Report) -> None:
    """E2：frozen_zones.json 的 zone 清单必须在现行技术文档中出现。"""
    raw = _read(FROZEN_ZONES)
    if not raw:
        r.add("E2", "ERROR", "冻结区清单读取失败", str(FROZEN_ZONES))
        return
    try:
        zone_ids = [z.get("id", "") for z in json.loads(raw).get("zones", [])]
    except json.JSONDecodeError as exc:
        r.add("E2", "ERROR", "frozen_zones.json 解析失败", str(exc))
        return
    doc = _read(CURRENT_DOC)
    if not doc:
        r.add("E2", "ERROR", "现行技术文档读取失败", str(CURRENT_DOC))
        return
    missing = [z for z in zone_ids if z and z not in doc]
    if missing:
        r.add("E2", "ERROR", "冻结区清单未同步到现行技术文档",
              "缺失 zone：" + " · ".join(missing))
    else:
        r.add("E2", "PASS", f"冻结区清单已同步（{len(zone_ids)} 个 zone）")


def check_main_version_anchors(r: Report) -> None:
    """W1：主程序版本号应出现在 CHANGELOG / README / 上下文包。"""
    v = _main_version()
    if not v:
        r.add("W1", "WARN", "主程序版本读取失败", str(VERSION_PY))
        return
    targets = [("docs/CHANGELOG.md", CHANGELOG), ("README.md", README),
               ("docs/PROJECT_CONTEXT_PACK.md", CONTEXT_PACK)]
    stale = [name for name, path in targets if v not in _read(path)]
    if stale:
        r.add("W1", "WARN", f"主程序版本 {v} 未同步到部分文档",
              "缺失：" + " · ".join(stale))
    else:
        r.add("W1", "PASS", f"主程序版本 {v} 已同步到 3 处文档")


def check_snapshot_freshness(r: Report, today: date | None = None) -> None:
    """W2：上下文包快照日期是否过期（> 30 天）。"""
    today = today or datetime.now().date()
    text = _read(CONTEXT_PACK)
    if not text:
        r.add("W2", "WARN", "上下文包不存在", str(CONTEXT_PACK))
        return
    m = _SNAPSHOT_DATE_RE.search(text)
    if not m:
        r.add("W2", "WARN", "上下文包未标注快照日期",
              "建议在文首写「快照 YYYY-MM-DD」，便于判断新鲜度")
        return
    try:
        snap = date.fromisoformat(m.group(1))
    except ValueError:
        r.add("W2", "WARN", "上下文包快照日期格式无法解析", m.group(1))
        return
    age = (today - snap).days
    if age > SNAPSHOT_MAX_AGE_DAYS:
        r.add("W2", "WARN", f"上下文包快照已过期（{age} 天）",
              f"快照 {snap.isoformat()} ⇒ 建议重新生成 docs/PROJECT_CONTEXT_PACK.md")
    else:
        r.add("W2", "PASS", f"上下文包快照新鲜（{age} 天前）")


def run_checks(today: date | None = None) -> Report:
    r = Report()
    check_canvas_version_triangle(r)
    check_frozen_zone_sync(r)
    check_main_version_anchors(r)
    check_snapshot_freshness(r, today)
    return r


def selfcheck() -> int:
    """守卫自证：注入已知漂移 ⇒ 必须报 ERROR；还原 ⇒ 必须放行。

    项目血泪：守卫必须**证明能拦**，否则就是「看起来有守卫、实际没守卫」
    （`arch_guard` 曾无参空转、`stability_gate` 曾因草稿噪声长期红而无人看）。
    全程在临时目录 + monkeypatch 模块常量，**不碰任何真实文件**。
    """
    import shutil
    import tempfile

    tmp_root = ROOT / ".workbuddy" / "tmp"
    tmp_root.mkdir(parents=True, exist_ok=True)
    d = Path(tempfile.mkdtemp(dir=tmp_root, prefix="docgate_"))
    watch = ("CANVAS_VERSION_TS", "CANVAS_PKG_JSON", "CHANGELOG",
             "FROZEN_ZONES", "CURRENT_DOC")
    saved = {k: globals()[k] for k in watch}
    outcomes: list[bool] = []

    def expect(name: str, want_error: bool, fn: Callable[[Report], None]) -> None:
        rep = Report()
        fn(rep)
        got = bool(rep.errors)
        ok = got == want_error
        outcomes.append(ok)
        detail = rep.errors[0].detail if rep.errors else "（无 ERROR）"
        print(f"[{'PASS' if ok else 'FAIL'}] {name} → "
              f"期望{'有' if want_error else '无'} ERROR，实际{'有' if got else '无'} · {detail}")

    try:
        ts = d / "canvasVersion.ts"
        pkg = d / "package.json"
        log = d / "CHANGELOG.md"
        ts.write_text('export const CANVAS_VERSION = "1.0.0";', encoding="utf-8")
        pkg.write_text('{"version": "9.9.9"}', encoding="utf-8")
        log.write_text("无记录", encoding="utf-8")
        g = globals()
        g["CANVAS_VERSION_TS"], g["CANVAS_PKG_JSON"], g["CHANGELOG"] = ts, pkg, log
        expect("画布版本三角不一致", True, check_canvas_version_triangle)

        ts.write_text('export const CANVAS_VERSION = "7.7.7";', encoding="utf-8")
        pkg.write_text('{"version": "7.7.7"}', encoding="utf-8")
        expect("三角一致但缺 CHANGELOG", True, check_canvas_version_triangle)

        log.write_text("## 7.7.7 画布版本", encoding="utf-8")
        expect("三角完整", False, check_canvas_version_triangle)

        fz = d / "frozen_zones.json"
        doc = d / "doc.md"
        fz.write_text('{"zones":[{"id":"zone-a"},{"id":"zone-ghost"}]}', encoding="utf-8")
        doc.write_text("只有 zone-a", encoding="utf-8")
        g["FROZEN_ZONES"], g["CURRENT_DOC"] = fz, doc
        expect("冻结区清单缺 zone-ghost", True, check_frozen_zone_sync)

        doc.write_text("zone-a 与 zone-ghost 都在", encoding="utf-8")
        expect("冻结区清单完整", False, check_frozen_zone_sync)
    finally:
        for k, v in saved.items():
            globals()[k] = v
        shutil.rmtree(d, ignore_errors=True)

    print("-" * 60)
    all_ok = all(outcomes)
    print("自证结论：" + ("全部通过（守卫确实能拦）" if all_ok else "存在 FAIL —— 守卫失效！"))
    return 0 if all_ok else 1


def _print_human(r: Report, strict: bool) -> None:
    icon = {"PASS": "[ OK ]", "WARN": "[WARN]", "ERROR": "[FAIL]"}
    for f in r.findings:
        print(f"{icon.get(f.level, '[????]')} {f.code} {f.title}")
        if f.detail:
            print(f"          {f.detail}")
    n_bad = len(r.errors) + (len(r.warns) if strict else 0)
    print("-" * 60)
    print(f"结论：{len(r.errors)} 个阻断 · {len(r.warns)} 个警告"
          f"{'（--strict：警告也算失败）' if strict else ''}")
    if n_bad:
        print("修复：改完对应文档后重跑；门禁只读、不自动改文档。")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="文档一致性门禁（只读检查）")
    ap.add_argument("--strict", action="store_true", help="警告也视为失败（CI 用）")
    ap.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    ap.add_argument("--selfcheck", action="store_true",
                    help="守卫自证：注入漂移验证「能拦」（不碰真实文件）")
    args = ap.parse_args(argv)

    if args.selfcheck:
        return selfcheck()

    report = run_checks()
    if args.json:
        print(json.dumps({
            "errors": [asdict(f) for f in report.errors],
            "warns": [asdict(f) for f in report.warns],
            "findings": [asdict(f) for f in report.findings],
        }, ensure_ascii=False, indent=2))
    else:
        _print_human(report, args.strict)

    failed = bool(report.errors) or (args.strict and bool(report.warns))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
