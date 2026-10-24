# -*- coding: utf-8 -*-
"""时间线互操作（OTIO/EDL/FCPXML）桥接守卫（§6.8.7 时间线交换 · 2026-10-18）

背景：interchange 包（timeline_dsl ↔ _clips ↔ OTIO）已落地并接了导出 UI，
但一直**没有守卫**——正是本项目反复踩过的「零件在位、无锁必漂」。
2026-10-18 用户拍板 OTIO 全量迁移（推翻 §1.4「不重写时间线」），迁移前
先把互操作现状锁成可执行断言。

断言：
  ① 桥接字段映射契约：clips_to_timeline 的显式对照
     （path→source / start_time→range.start / in·out→source_range /
      track 分组 / audio 类型判定），timeline_to_clips 往返 extras 不丢
  ② OTIO 端到端往返（真子进程路径）：clips→DSL→.otio→DSL→clips
     关键字段守恒（含 generation/semantic 血缘块）
  ③ Qt 段错误红线：otio_adapter 源码**不得**顶层 import opentimelineio
     （C 扩展在 PyQt6 之后加载会 access violation，生产路径必须走子进程）；
     is_available 只用 find_spec 探测
  ④ UI 接线在册：editor_export_panel.py 确实消费 clips_to_timeline +
     导出过滤器（防静默断线）
  ⑤ 依赖在册：requirements.txt 登记 opentimelineio（环境漂移防护——
     未登记时新机器互操作静默退化为不可用）

用法（项目根执行）：.venv312\\Scripts\\python.exe _verify/check_interchange_bridge.py
退出码 0 = 通过；1 = 有漂移。② 在 opentimelineio 缺失时如实 SKIP（不算失败，
①③④⑤ 仍全跑）。
"""
from __future__ import annotations

import os
import sys
import tempfile

try:
    _SG_TMP = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        ".workbuddy", "tmp",
    )
    os.makedirs(_SG_TMP, exist_ok=True)
    tempfile.tempdir = _SG_TMP
except OSError:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

problems = []
skips = []


def _fail(msg: str) -> None:
    problems.append(msg)


def _rich_clips():
    """覆盖契约字段的样本 clip 集（双轨 + 音频 + 血缘/语义块 + extras）。"""
    return [
        {"id": "v1", "type": "video", "path": "a.mp4", "duration": 5.0,
         "start_time": 0.0, "in_point": 1.0, "out_point": 4.0, "track": 0,
         "volume": 0.8,
         "generation": {"prompt": "p", "seed": 42},
         "semantic": {"quality": {"weighted_score": 77.0}}},
        {"id": "v2", "type": "video", "path": "b.mp4", "duration": 3.0,
         "start_time": 6.0, "in_point": 0.0, "out_point": 3.0, "track": 0,
         "custom_extra": "keep-me"},
        {"id": "a1", "type": "audio", "path": "bgm.mp3", "duration": 10.0,
         "start_time": 0.0, "in_point": 0.0, "out_point": 10.0, "track": 1},
    ]


# ── ① 桥接字段映射契约 ───────────────────────────────────────────────

def check_bridge_contract() -> None:
    from app.core.interchange.editor_timeline_bridge import (
        clips_to_timeline, timeline_to_clips)

    clips = _rich_clips()
    tl = clips_to_timeline(clips, fps=30.0)
    if len(tl.tracks) < 2:
        _fail(f"① track 分组失败：期望 ≥2 轨，实得 {len(tl.tracks)}")
    n_clips = sum(len(t.clips) for t in tl.tracks)
    if n_clips != 3:
        _fail(f"① clip 数守恒失败：{n_clips} ≠ 3")

    # 显式映射抽查：v1 的 source/range/source_range
    v1 = next((c for t in tl.tracks for c in t.clips if c.id == "v1"), None)
    if v1 is None:
        _fail("① v1 未进 DSL")
        return
    if v1.source != "a.mp4":
        _fail(f"① path→source 漂移：{v1.source!r}")
    if abs(v1.range.start - 0.0) > 1e-6 or abs(v1.range.duration - 3.0) > 1e-6:
        _fail(f"① start/duration(out-in) 映射漂移：{v1.range}")
    if abs(v1.source_range.start - 1.0) > 1e-6:
        _fail(f"① in_point→source_range.start 漂移：{v1.source_range}")

    # 往返：extras（custom_extra / generation / semantic）不丢
    back = {c["id"]: c for c in timeline_to_clips(tl)}
    if set(back) != {"v1", "v2", "a1"}:
        _fail(f"① 往返 clip 集不一致：{sorted(back)}")
        return
    if back["v2"].get("custom_extra") != "keep-me":
        _fail("① 往返丢 extras（metadata 无损承诺被破）")
    if not isinstance(back["v1"].get("generation"), dict) or \
       back["v1"]["generation"].get("seed") != 42:
        _fail("① 往返丢 generation 血缘块")
    if not isinstance(back["v1"].get("semantic"), dict):
        _fail("① 往返丢 semantic 语义块")
    if back["a1"].get("type") != "audio":
        _fail("① audio 类型往返漂移")


# ── ② OTIO 端到端往返（真子进程） ────────────────────────────────────

def check_otio_roundtrip() -> None:
    from app.core.interchange import otio_adapter
    from app.core.interchange.editor_timeline_bridge import (
        clips_to_timeline, timeline_to_clips)

    if not otio_adapter.is_available():
        skips.append("② opentimelineio 未安装，端到端往返 SKIP（①③④⑤ 不受影响）")
        return
    fd, tmp = tempfile.mkstemp(prefix="sg_interop_", suffix=".otio")
    os.close(fd)
    try:
        tl = clips_to_timeline(_rich_clips(), fps=30.0)
        otio_adapter.export_otio(tl, tmp)
        back_tl = otio_adapter.import_otio(tmp)
        back = {c["id"]: c for c in timeline_to_clips(back_tl)}
        if set(back) != {"v1", "v2", "a1"}:
            _fail(f"② OTIO 端到端 clip 集漂移：{sorted(back)}")
            return
        if abs(back["v1"]["start_time"] - 0.0) > 1e-3 or \
           abs(back["v2"]["start_time"] - 6.0) > 1e-3:
            _fail("② OTIO 端到端时间线位置漂移（RationalTime 换算）")
        if back["v1"].get("path") != "a.mp4":
            _fail("② OTIO 端到端 path 漂移")
        if not isinstance(back["v1"].get("generation"), dict):
            _fail("② OTIO 端到端丢 generation（metadata shiguang 无损承诺被破）")
        if back["v2"].get("custom_extra") != "keep-me":
            _fail("② OTIO 端到端丢 extras")
    except RuntimeError as e:
        _fail(f"② OTIO 端到端失败：{e}")
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


# ── ③ Qt 段错误红线（静态） ──────────────────────────────────────────

def check_no_top_level_import() -> None:
    for fname in ("otio_adapter.py", "editor_timeline_bridge.py",
                  "__init__.py"):
        path = os.path.join(ROOT, "app", "core", "interchange", fname)
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
        # 顶层（非函数体内）出现 import opentimelineio 即违规：
        # 简化判定——任何不以空白开头的 import opentimelineio 行
        for line in src.splitlines():
            if line.strip().startswith(("import opentimelineio",
                                        "from opentimelineio")) \
                    and not line.startswith(("    ", "\t")):
                _fail(f"③ {fname} 顶层 import opentimelineio"
                      "（Qt 进程段错误红线：必须 find_spec 探测 + 子进程读写）")
    adapter = os.path.join(ROOT, "app", "core", "interchange", "otio_adapter.py")
    with open(adapter, "r", encoding="utf-8") as f:
        src = f.read()
    if "find_spec" not in src:
        _fail("③ is_available 不再用 find_spec 探测（红线实现漂移）")


# ── ④ UI 接线在册 ────────────────────────────────────────────────────

def check_ui_wiring() -> None:
    panel = os.path.join(ROOT, "app", "modules", "lego", "editor_export_panel.py")
    with open(panel, "r", encoding="utf-8") as f:
        src = f.read()
    # 刀3（2026-10-18）：消费端改读 store.to_timeline() canonical 视图（桥接由 store 内部消费）
    for token in ("_timeline_store.to_timeline(", "timeline_export_filters",
                  "is_timeline_extension"):
        if token not in src:
            _fail(f"④ 导出 UI 断线：editor_export_panel 不再消费 {token}")
    # 导入接线（2026-10-18 e8b）：UI 入口 + 动作调度 + 桥消费三层都在册
    if "_import_timeline_document" not in src or "import_timeline_to_clips" not in src:
        _fail("④ 导入 UI 断线：editor_export_panel 不再实现 _import_timeline_document"
              "/消费 import_timeline_to_clips")
    ux = os.path.join(ROOT, "app", "modules", "lego", "editor_ux_commands.py")
    with open(ux, "r", encoding="utf-8") as f:
        src = f.read()
    if '"import_timeline"' not in src or "_import_timeline_document" not in src:
        _fail("④ 导入动作断线：editor_ux_commands 不再在册 import_timeline → "
              "_import_timeline_document")
    builder = os.path.join(ROOT, "app", "modules", "lego", "editor_ui_builder_mixin.py")
    with open(builder, "r", encoding="utf-8") as f:
        src = f.read()
    if 'bind_action(self, "import_timeline")' not in src:
        _fail("④ 导入按钮断线：编辑器工具栏不再绑定 import_timeline 动作")


# ── ⑤ 依赖在册 ───────────────────────────────────────────────────────

def check_requirements() -> None:
    # 可选依赖清单（缺失→互操作诚实降级，与 is_available 设计一致；
    # 不进 REQUIRED 是因 main_qt6 DependencyChecker 启动检查会误报缺必需包）
    req = os.path.join(ROOT, "app", "requirements-optional.txt")
    with open(req, "r", encoding="utf-8") as f:
        src = f.read().lower()
    if "opentimelineio" not in src:
        _fail("⑤ requirements-optional.txt 未登记 opentimelineio"
              "（新环境互操作会静默退化不可用）")


def main() -> int:
    check_bridge_contract()
    check_otio_roundtrip()
    check_no_top_level_import()
    check_ui_wiring()
    check_requirements()
    for s in skips:
        print(f"SKIP  {s}")
    if problems:
        for p in problems:
            print(f"FAIL  {p}")
        return 1
    print("PASS  时间线互操作：桥接契约/OTIO端到端/Qt段错误红线/UI接线/依赖在册")
    return 0


if __name__ == "__main__":
    sys.exit(main())
