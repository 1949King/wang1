# -*- coding: utf-8 -*-
"""画布浮层簇守卫（输出历史 / 灯位 / 导演指导 / 上游引用开关）。

为什么这些检查放在 Python 而不是 vitest
======================================
它们要读**文件系统**（源码文本、资源体积）。画布 tsconfig **没有 `@types/node`**，
在 vitest 里 `import fs from "node:fs"` 会产生 8 个 `error TS2307/2304` —— 直接污染
tsc 棘轮基线（37）。故：**纯逻辑留在 vitest，源码/资源检查放这里**，两边都不引新依赖。

钉三件事
========
  ① **接线**：`App.tsx` 挂 `<CanvasOverlays />`（不直接挂面板 —— App 顶到规模上限），
     `CanvasOverlays` 挂 `<OutputHistoryPanel` 与工具条（Ctrl+H/Ctrl+L/Ctrl+D）；
  ② **连线上游引用**：必须存在真实引用通道 + 默认关（不在用户没同意时改节点）；
  ③ **浮层入口保留**：输出历史、灯位、导演指导、上游引用开关四颗入口。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join("vendor", "shiguang-canvas", "src", "App.tsx")
OVERLAYS = os.path.join("vendor", "shiguang-canvas", "src", "CanvasOverlays.tsx")

_fails = []


def _fail(msg: str) -> None:
    _fails.append(msg)


def _read(rel: str) -> str:
    p = os.path.join(ROOT, rel)
    if not os.path.isfile(p):
        _fail(f"文件缺失：{rel}")
        return ""
    return open(p, encoding="utf-8", errors="ignore").read()


def check_wiring() -> None:
    app = _read(APP)
    if "<CanvasOverlays />" not in app:
        _fail("① App.tsx 未挂载 <CanvasOverlays />（浮层簇入口）")
    if "<OutputHistoryPanel" in app or "<AgentPet" in app or "<DirectorPanel" in app or "<LightingPanel" in app:
        _fail("① App.tsx 直接挂了浮层子组件 —— App 顶到规模上限（2000），应只挂浮层簇入口")
    ov = _read(OVERLAYS)
    for probe in ("<OutputHistoryPanel", "Ctrl+H",
                  "useUpstreamRefsSync", "<LightingPanel", "灯位",
                  "<DirectorPanel", "导演指导", "useToolboxStore"):
        if probe not in ov:
            _fail(f"① CanvasOverlays 缺 {probe}")
    # V4.41.15 起浮层入口收进底部「⚡工具」横向工具板（旧 ov-bar 四胶囊退役）
    dock = _read(os.path.join("vendor", "shiguang-canvas", "src", "LibTvChrome.tsx"))
    for probe in ("输出历史", "灯位", "导演指导", "上游引用", "useToolboxStore"):
        if probe not in dock:
            _fail(f"① LibTvChrome 工具板缺入口：{probe}")
    store = _read(os.path.join("vendor", "shiguang-canvas", "src", "toolboxStore.ts"))
    for probe in ("historyOpen", "lightingOpen", "directorOpen", "upstreamRefs", "zustand"):
        if probe not in store:
            _fail(f"① toolboxStore 缺 {probe}")


def check_upstream_refs_module() -> None:
    """连线上游引用：必须存在真实引用通道 + 默认关（不在用户没同意时改节点）。"""
    src = _read(os.path.join("vendor", "shiguang-canvas", "src", "upstreamRefs.ts"))
    if not src:
        return
    for probe in ("firstFrameUrl", "REF_MARK", "enabled: false"):
        if probe not in src:
            _fail(f"⑤ upstreamRefs 缺 {probe}")
    # 默认必须是关：读法不能变成"没存过就算开"
    if 'localStorage.getItem(ENABLED_KEY) === "1"' not in src:
        _fail("⑤ 开关默认值被改（必须『没存过 = 关』，否则会偷偷改用户节点）")


def main() -> int:
    print("=" * 62)
    print("画布浮层簇守卫（输出历史 / 灯位 / 导演指导 / 上游引用）")
    print("=" * 62)
    for fn in (check_wiring, check_upstream_refs_module):
        try:
            fn()
        except Exception as e:
            _fail(f"{fn.__name__} 抛异常: {type(e).__name__}: {e}")
    if _fails:
        print("✗ 失败项：")
        for p in _fails:
            print(f"  - {p}")
        return 1
    print("OK 接线齐备 · 浮层入口保留 · 上游引用默认关")
    return 0


if __name__ == "__main__":
    sys.exit(main())
