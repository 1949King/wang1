# -*- coding: utf-8 -*-
"""QtWebEngine 可用性预检（2026-10-25）。

背景：本机 PyQt6 6.10.2 + Qt 6.10.2，但 PyQt6-WebEngine 6.10.0 ⇒ 混装后
WebEngine 渲染进程 **fail-fast（0xC0000409）**，连 data: URL 都加载不了。
这种崩溃无法 try/except，只能子进程试跑。

退出码：0 = 能真正加载页面；非 0 = 不可用（调用方据此走系统浏览器兜底）。
"""
import os
import sys

os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox")

# 必须在 QApplication 之前导入（QtWebEngineWidgets 的硬要求）
from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402
from PyQt6.QtCore import QTimer, QUrl  # noqa: E402

app = QApplication([])
view = QWebEngineView()
state = {"ok": None}


def _done(finished: bool) -> None:
    state["ok"] = bool(finished)
    app.quit()


view.loadFinished.connect(_done)
view.load(QUrl("data:text/html,<h1>probe</h1>"))
QTimer.singleShot(12000, app.quit)
app.exec()
sys.exit(0 if state["ok"] else 3)
