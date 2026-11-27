#!/usr/bin/env python3
"""优化视频播放器及其 Windows 依赖的导入回归测试。"""


def test_video_player_module_imports():
    """播放器模块必须可导入，不能在 pytest 收集阶段退出进程。"""
    from app.modules.video_player.optimized_video_player import OptimizedVideoPlayer

    assert OptimizedVideoPlayer is not None


def test_qt_dependency_imports():
    """播放器使用的 Qt 绑定必须可导入。"""
    from PySide6.QtWidgets import QApplication

    assert QApplication is not None


def test_win32_dependency_imports():
    """Windows 窗口捕获测试所需的 pywin32 模块必须可导入。"""
    import win32con
    import win32gui

    assert win32gui is not None
    assert win32con is not None
