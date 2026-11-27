# -*- coding: utf-8 -*-
"""QtWebEngine 可用性预检（2026-10-25，2026-10-25 二次修正）。

背景：PyQt6 时代本机 Qt 6.10.2 + WebEngine 6.10.0 混装后，
WebEngine 渲染进程 **fail-fast（0xC0000409）**，连 data: URL 都加载不了。
PySide6 迁移后四包统一 6.10.2，仍保留子进程实载探针。
这种崩溃无法 try/except，只能子进程试跑。

🔴 2026-10-25 定案（本文件的**致命误判**，务必别改回去）：
``QApplication([])`` 传**空 argv** 时，Qt 6.11 的 Chromium 会打印
``Argument list is empty, the program name is not passed to QCoreApplication.
base::CommandLine cannot be properly initialized.`` 然后**必然** fail-fast
（退出码 -1073740791 = 0xC0000409）。实测对照：

    空 argv     → exit 127(0xC0000409)，画布永远判「不可用」
    ["probe"]   → loadFinished=True，exit 0

即真正炸的不是 WebEngine，是探针自己。误判后果极重：main_qt6 据此置
``SHIGUANG_NO_WEBENGINE=1`` ⇒ 应用内画布被**永久**禁用，用户只看到一块黑屏 +
「画布页面加载失败（请点刷新或启动画布）」，点多少次都没用。
故 QApplication 的 argv 一律用**非空**列表（sys.argv 至少含脚本名，
为空时兜底给一个显式程序名）。

退出码：0 = 能真正加载页面；非 0 = 不可用（调用方据此走系统浏览器兜底）。
诊断信息一律走 stderr（stdout 会被调用方丢弃）。
"""
import os
import sys

os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox")

# 必须在 QApplication 之前导入（QtWebEngineWidgets 的硬要求）
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer, QUrl


def _diag(msg: str) -> None:
    try:
        sys.stderr.write("[probe_webengine] " + msg + "\n")
        sys.stderr.flush()
    except Exception:  # stability-gate: allow-swallow（诊断输出失败不得影响探针结论）
        pass


# 🔴 argv 必须非空：空列表会让 Chromium 的 base::CommandLine 初始化失败 ⇒ 渲染进程 fail-fast
_argv = [a for a in (sys.argv or []) if isinstance(a, str)]
if not _argv:
    _argv = ["probe_webengine"]
elif not _argv[0]:
    _argv[0] = "probe_webengine"

app = QApplication(_argv)
view = QWebEngineView()
state = {"ok": None}


def _done(finished: bool) -> None:
    state["ok"] = bool(finished)
    app.quit()


view.loadFinished.connect(_done)
view.load(QUrl("data:text/html,<h1>probe</h1>"))
QTimer.singleShot(12000, app.quit)
app.exec()

if state["ok"]:
    _diag("OK: data: URL 渲染成功")
else:
    _diag(
        "FAIL: data: URL 未能渲染（loadFinished=False 或超时）。"
        "常见原因：PySide6 / Essentials / Addons / shiboken6 四者版本不齐，"
        "或 Chromium 沙箱起不来（需 QTWEBENGINE_CHROMIUM_FLAGS=--no-sandbox）"
    )
sys.exit(0 if state["ok"] else 3)
