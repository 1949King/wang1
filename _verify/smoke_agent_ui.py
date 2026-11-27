#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""UI 冒烟验证：启动主窗口 → 切到 Agent 面板 → 截图 → 退出。

跑法: python _verify/smoke_agent_ui.py

为什么需要它：静态检查（py_compile / run_all_checks）只能证明「代码没坏」，
**证明不了「界面对着看是对的」**。本脚本真实构建主窗口、真实渲染 Agent 面板并截图，
用眼睛确认：对话区是否已成为主体、卡片是否收起、按钮是否按需显示。
"""
from __future__ import annotations

import os
import sys
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

SHOT_DIR = os.path.join(ROOT, "_verify")
LOG = []


def log(msg: str) -> None:
    print(msg, flush=True)
    LOG.append(str(msg))


def find_editor(root: QWidget):
    """在主窗口里找 EditorModule（持有 _tools_tabs 与 _create_edit_agent_panel 的那个）。"""
    for w in [root] + root.findChildren(QWidget):
        if hasattr(w, "_tools_tabs") and hasattr(w, "_create_edit_agent_panel"):
            return w
    return None


def main() -> int:
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    try:
        from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
    except ImportError:
        pass

    app = QApplication(sys.argv)

    from app.modules.lego.main_window import MainWindow

    log("构建 MainWindow…")
    win = MainWindow()
    win.resize(1680, 940)
    win.show()
    log("MainWindow 已显示")

    result = {"ok": False}

    def step_shot():
        try:
            editor = find_editor(win)
            if editor is None:
                log("✗ 未找到 EditorModule")
                return
            log("✓ 找到 EditorModule")

            tabs = getattr(editor, "_tools_tabs", None)
            idx = getattr(editor, "_agent_tab_index", -1)
            log(f"  工具栏 tabs={type(tabs).__name__} · Agent 索引={idx}")

            if tabs is not None and idx is not None and idx >= 0:
                tabs.setCurrentIndex(idx)
                log("✓ 已切到 Agent 面板（触发懒加载构建）")

            # 让懒加载 + 布局 settle
            app.processEvents()

            panel = getattr(editor, "_edit_agent_panel", None)
            if panel is None:
                # 面板可能没存引用，直接从 tabs 里取当前 widget
                panel = tabs.currentWidget() if tabs is not None else None

            # ── 关键量测：对话区是否成为主体 ──
            chat = getattr(editor, "_edit_agent_chat", None)
            if chat is not None:
                h = chat.height()
                log(f"  ★ 对话区高度 = {h}px（改造前固定 72px；目标 ≥220）")
                result["chat_h"] = h
            else:
                log("  ✗ 未找到 _edit_agent_chat")

            # 展开 / 收起按钮存在性
            for attr in ("_agent_expand_btn", "_edit_agent_input", "_edit_agent_send_btn"):
                log(f"  {'✓' if getattr(editor, attr, None) is not None else '✗'} {attr}")

            # 截「整个主窗口」+「Agent 面板」两张
            p_full = os.path.join(SHOT_DIR, "shot_main_window.png")
            win.grab().save(p_full)
            log(f"✓ 已截图主窗口 → {p_full}")
            if panel is not None:
                p_agent = os.path.join(SHOT_DIR, "shot_agent_panel.png")
                panel.grab().save(p_agent)
                log(f"✓ 已截图 Agent 面板 → {p_agent}")

            result["ok"] = True
        except Exception as e:  # noqa: BLE001
            log(f"✗ 验证异常: {e}")
            traceback.print_exc()
        finally:
            app.quit()

    QTimer.singleShot(6000, step_shot)
    app.exec()

    with open(os.path.join(SHOT_DIR, "_smoke_log.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(LOG))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
