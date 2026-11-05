#!/usr/bin/env python3
"""
Qt6 主应用入口
集成授权管理系统和登录窗口
"""

import sys
import os

# ===========================================================================
# 启动序（顺序不能改）
# ===========================================================================
# ① AI 内核装载：把随包分发的 runtime/ 接进 sys.path。必须早于任何可能 import
#    torch 的代码；原因见 app/core/runtime_pack.py（torch 进不了 PyInstaller）。
from app.core.runtime_pack import ensure_runtime_path

ensure_runtime_path()

# ② 原生库导入顺序（历史坑，别踩回去）
#    实测（2026-11-05 本机，可复现）：
#        import PyQt6.QtWidgets; import sentencepiece   → 原生访问违例，exit 139
#        import sentencepiece;   import PyQt6.QtWidgets  → 正常
#    sentencepiece 的 C 扩展在 Qt 已加载时创建模块就崩，Python 层没有栈。
#    受影响路径是 gguf/vocab.py:12 → import sentencepiece，也就是「加载 GGUF
#    量化模型」在 Qt 进程里必崩。
#    ⇒ 处理方式：**AI 内核里不带 sentencepiece**（scripts/make_runtime_pack.py
#      的 SKIP_TOPLEVEL_DISTS）。它对 gguf 是 try/except 可选依赖，对
#      transformers 是 is_sentencepiece_available() 门控的可选功能，缺了只是
#      少数旧式分词器模型的退化，不会崩。相比之下「带了就崩进程」不可接受。
#    所以这里**不做**预热导入 —— 曾经加过，在冻结版里反而让每次启动都崩。

# ③ 自检分流：必须在 import PyQt6 **之前**。
#    实测：PyQt6 先加载、再 import torch 系原生库，同进程会触发原生段错误
#    （exit 139，无 Python 栈）。与本项目 app/core/interchange/_otio_worker.py
#    拆子进程是同一类问题。自检不需要 GUI，绕开 Qt 即可。
if "--selftest" in sys.argv:
    from app.core import ai_runtime_selftest as _st

    _out = ""
    if "--selftest-out" in sys.argv:
        _i = sys.argv.index("--selftest-out")
        if _i + 1 < len(sys.argv):
            _out = sys.argv[_i + 1]
    # --only <名字>：只跑一项。用于排除「同进程互相干扰」造成的假失败
    # （全项自检把几十个原生库塞一个进程，比产品实际条件更苛刻）。
    _only = ""
    if "--only" in sys.argv:
        _i = sys.argv.index("--only")
        if _i + 1 < len(sys.argv):
            _only = sys.argv[_i + 1]
    sys.exit(_st.emit(as_json="--json" in sys.argv, out_path=_out, only=_only))

# ③b OTIO 转换子进程入口（冻结版专用，也必须在 import PyQt6 之前）。
#    背景：主进程绝不能 import opentimelineio —— 它的 C 扩展在 Qt 之后加载必
#    段错误（见 app/core/interchange/_otio_worker.py 顶部实测记录）。开发态由
#    `python -m app.core.interchange._otio_worker` 起子进程；冻结后 sys.executable
#    是这个 exe，`-m` 参数没人认，会直接把 GUI 拉起来 ⇒ OTIO 导入导出在发布版
#    静默失效。这里给冻结态一个等价入口，保证子进程里没有任何 Qt。
if "--otio-worker" in sys.argv:
    from app.core.interchange import _otio_worker as _otio_w

    _i = sys.argv.index("--otio-worker")
    # _otio_worker.main 期望 argv[0] 是脚本名、argv[1] 是子命令
    sys.exit(_otio_w.main(["_otio_worker", *sys.argv[_i + 1:]]))

# ④ 之后才是 GUI 依赖。这里之所以可以安全地在 import 块之前插代码：
#    历史上 spec 把 torch 全排除、进程里一个 torch 都没有也能正常启动，说明
#    这些模块级 import 从不触达 torch（重型依赖全是函数内懒加载）。
from PyQt6.QtWidgets import QApplication, QMainWindow, QMessageBox, QVBoxLayout, QHBoxLayout, QWidget, QLabel, QPushButton, QGridLayout
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QIcon

# 导入独立授权管理模块
from license.license_manager import LicenseManager, LicenseDialog, get_license_manager, check_permission

# 导入主窗口
from app.modules.lego.main_window import MainWindow

# 导入登录窗口
from app.modules.lego.login_window import LoginWindow, ActivationWindow


class AppStartupThread(QThread):
    """应用启动线程"""
    startup_finished = pyqtSignal()
    
    def run(self):
        # 模拟启动过程
        import time
        time.sleep(1)  # 模拟初始化时间
        self.startup_finished.emit()


class AIShortDramaEditorApp:
    """AI短剧编辑器主应用"""
    
    def __init__(self, app):
        print("AIShortDramaEditorApp初始化开始...")
        self.app = app
        # 初始化授权管理器
        self.license_manager = get_license_manager()
        print(f"授权管理器初始化完成: {self.license_manager}")
        
        # 初始化窗口
        self.login_window = None
        self.activation_window = None
        self.main_window = None
        
        # 直接显示主窗口
        self._show_main_window()

    def _show_login_window(self):
        """显示登录窗口"""
        print("创建LoginWindow...")
        self.login_window = LoginWindow()
        self.login_window.login_success.connect(self._on_login_success)
        self.login_window.show()
        print("LoginWindow已显示")

    def _on_login_success(self):
        """登录成功处理"""
        print("登录成功，显示主窗口")
        # 关闭登录窗口
        if self.login_window:
            self.login_window.close()
            self.login_window = None
        
        # 显示主窗口
        self._show_main_window()

    def _show_main_window(self):
        """显示主窗口"""
        print("创建MainWindow...")
        self.main_window = MainWindow()
        # 修复：register_skills 之前从未被调用，导致 Skill 工坊列表为空
        try:
            from app.modules.lego.video_editing_skill import register_skills
            register_skills()
        except Exception as e:
            print(f"Skill 注册失败（不影响启动）: {e}")

        # 统一调用层 & 长期记忆 & 反馈桥 eager init（best-effort）
        try:
            import logging as _logging
            _log = _logging.getLogger("startup")
            from app.core.memory_store import MemoryStore
            from app.core.agent_feedback_bridge import AgentFeedbackBridge
            from app.core.capability_dispatcher import CapabilityDispatcher
            MemoryStore.get_instance()
            AgentFeedbackBridge.get_instance().event_bus  # 触发订阅
            CapabilityDispatcher.get_instance()  # 首次 invoke 时注册内置 handler
            _log.info("[startup] 调用层 & 记忆 & 反馈桥 已就绪")
        except Exception as e:
            print(f"[startup] 调用层初始化失败（不影响主流程）: {e}")

        # 连接主窗口的关闭信号
        self.main_window.destroyed.connect(self._on_main_window_closed)
        self.main_window.show()
        print("MainWindow已显示")

    def _on_main_window_closed(self):
        """主窗口关闭处理"""
        print("主窗口已关闭，退出应用")
        # 关闭所有窗口
        if self.login_window:
            self.login_window.close()
        if self.activation_window:
            self.activation_window.close()
        # 退出应用
        self.app.quit()


def main():
    """主函数"""
    # 自检入口已在模块顶部（import PyQt6 之前）分流，这里不会走到 --selftest。
    # WebEngine 必须在 QApplication 创建前设置此属性，否则报:
    # QtWebEngineWidgets must be imported or Qt.AA_ShareOpenGLContexts
    # must be set before a QCoreApplication instance is created
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    # 提前 import WebEngineWidgets，让 Qt 在创建 QApplication 前完成 OpenGL 上下文共享
    try:
        from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
    except ImportError:
        pass

    app = QApplication(sys.argv)
    
    # 设置应用图标
    icon_path = "icon.png"
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    
    # 启动应用
    editor_app = AIShortDramaEditorApp(app)
    
    # 将editor_app保存到app的属性中，防止被垃圾回收
    app.editor_app = editor_app
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
