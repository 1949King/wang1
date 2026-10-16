#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""全模块 UI 遍历截图（模拟手动点击）。

设计边界（零污染原则）：
- 不启动登录流程、不写 QSettings、不改注册表开关；
- 点击导航按钮 = 用户真实点击路径（NavigationButton.click() → _on_button_clicked）；
- 导航里没有的模块（用户关闭了开关）：不强行打开开关，改为独立实例化 + 顶层 show 截图，
  截完后 deleteLater，不触碰 module_switches.json；
- 截图目录 _verify/ui_walk/<ts>/，附 manifest.json。
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PyQt6.QtCore import Qt, QTimer  # noqa: E402
from PyQt6.QtWidgets import QApplication, QTabWidget  # noqa: E402

TS = time.strftime("%Y%m%d_%H%M%S")
SHOT_DIR = os.path.join(ROOT, "_verify", "ui_walk", TS)
os.makedirs(SHOT_DIR, exist_ok=True)

MANIFEST: dict = {"shots_dir": SHOT_DIR, "modules": {}, "errors": []}


def pump(app: QApplication, seconds: float) -> None:
    """真实事件循环推进（等价于人的等待），不阻塞 Qt 定时器。"""
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.02)


def shot(widget, name: str) -> str:
    path = os.path.join(SHOT_DIR, name + ".png")
    pm = widget.grab()
    pm.save(path, "PNG")
    return path


def walk_tabs(win, widget, prefix: str, app: QApplication, max_tw: int = 2, max_tabs: int = 5):
    """遍历模块内部 QTabWidget 的每个页签：切换（等价点击）→ settle → 截图。"""
    out = []
    try:
        tabs_list = widget.findChildren(QTabWidget)
    except Exception:
        return out
    for ti, tw in enumerate(tabs_list[:max_tw]):
        n = tw.count()
        for i in range(min(n, max_tabs)):
            try:
                tw.setCurrentIndex(i)
                label = tw.tabText(i) or f"tab{i}"
                pump(app, 0.5)
                p = shot(win, f"{prefix}__tab{ti}_{label}")
                out.append({"tab": label, "file": os.path.basename(p)})
            except Exception:
                MANIFEST["errors"].append(f"tab {prefix}/{ti}/{i}: " + traceback.format_exc(limit=2))
    return out


def main() -> int:
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    from app.modules.lego.main_window import MainWindow
    win = MainWindow()
    win.resize(1600, 940)
    win.show()
    pump(app, 3.0)

    # 1) 首屏（home 默认选中）
    p = shot(win, "00_home")
    MANIFEST["modules"]["home"] = {"nav": True, "shot": os.path.basename(p), "tabs": walk_tabs(win, win._modules["home"].instance if "home" in win._modules and win._modules["home"].instance else win, "00_home", app)}
    print("[done] home", flush=True)

    # 2) 有导航按钮的模块：真实点击路径
    order = ["editor", "characters", "copywriting", "tasks", "materials", "models", "extensions", "performance", "help", "settings"]
    for mid in order:
        if win._nav_bar.has_module(mid):
            try:
                btn = win._nav_bar._buttons[mid]
                btn.click()  # 与鼠标点击同信号
                is_canvas = (mid == "characters")
                pump(app, 14.0 if is_canvas else 5.0)
                info = win._modules.get(mid)
                inst = getattr(info, "instance", None)
                name = f"010_{mid}"
                p = shot(win, name)
                rec = {"nav": True, "shot": os.path.basename(p)}
                if inst is not None:
                    rec["tabs"] = walk_tabs(win, inst, name, app)
                if is_canvas:
                    pump(app, 10.0)  # 再等画布渲染，补拍第二张
                    p2 = shot(win, name + "_late")
                    rec["shot_late"] = os.path.basename(p2)
                MANIFEST["modules"][mid] = rec
                print(f"[done] {mid} (nav)", flush=True)
            except Exception:
                MANIFEST["errors"].append(f"{mid}: " + traceback.format_exc(limit=3))
                print(f"[FAIL] {mid}", flush=True)
        else:
            # 用户关掉了开关 ⇒ 不碰开关；独立实例化该模块顶层截图（等价"手动开启后"的样子）
            try:
                import importlib
                from app.modules.lego.module_registry import get_registry
                d = get_registry().get_definition(mid)
                if d:
                    mod = importlib.import_module("app.modules.lego." + d["import_module"].lstrip("."))
                    cls = getattr(mod, d["import_class"])
                    w = cls()
                    w.resize(1600, 900)
                    w.setWindowTitle(mid)
                    w.show()
                    is_canvas = (mid == "characters")
                    pump(app, 12.0 if is_canvas else 5.0)
                    name = f"015_{mid}_standalone"
                    p = shot(w, name)
                    rec = {"nav": False, "standalone": True, "shot": os.path.basename(p)}
                    rec["tabs"] = walk_tabs(w, w, name, app)
                    MANIFEST["modules"][mid] = rec
                    w.close(); w.deleteLater(); pump(app, 0.3)
                    print(f"[done] {mid} (standalone)", flush=True)
            except Exception:
                MANIFEST["errors"].append(f"standalone-{mid}: " + traceback.format_exc(limit=3))
                MANIFEST["modules"][mid] = {"nav": False, "error": True}
                print(f"[FAIL-standalone] {mid}", flush=True)

    # 3) editor 的工具区页签若在第 2 步没截全（tabs 上限 5），单独补一轮
    try:
        info = win._modules.get("editor")
        ed = getattr(info, "instance", None) if info else None
        tools = getattr(ed, "_tools_tabs", None) if ed else None
        if tools is not None:
            extra = []
            for i in range(tools.count()):
                tools.setCurrentIndex(i)
                pump(app, 0.5)
                label = tools.tabText(i) or f"t{i}"
                p = shot(win, f"020_editor_tools_{i}_{label}")
                extra.append({"tab": label, "file": os.path.basename(p)})
            MANIFEST["modules"]["editor"]["tools_tabs"] = extra
            print(f"[done] editor tools x{len(extra)}", flush=True)
    except Exception:
        MANIFEST["errors"].append("editor-tools: " + traceback.format_exc(limit=3))

    with open(os.path.join(SHOT_DIR, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(MANIFEST, f, ensure_ascii=False, indent=2)
    print("MANIFEST_DIR=" + SHOT_DIR, flush=True)
    win.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
