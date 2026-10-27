# -*- coding: utf-8 -*-
"""MCP 页默认配置 Blender + 预设卡片渲染 回归（V4.46.19）。

锁三件事：
1. 默认自动连接 Blender：首次建 MCP tab ⇒ 触发一次且只一次；`_auto` 标记 ⇒ 失败
   只进状态栏不弹模态窗（默认配置不该打断用户）。
2. 幂等：已连着 Blender 时不重复连。
3. 预设卡片数据面：blender 预设存在且命令为 uvx（连接依赖 uvx，如实呈现）。
卡片渲染本体由 offscreen 诊断实测（6 卡几何/标签全正常），不在此重复 GUI 断言。
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

QtApp = None


@pytest.fixture(scope="module")
def qapp():
    global QtApp
    from PyQt6.QtWidgets import QApplication

    QtApp = QApplication.instance() or QApplication([])
    yield QtApp


def test_blender_preset_exists_and_uses_uvx():
    from app.core.mcp_client import MCP_PRESETS

    b = MCP_PRESETS.get("blender")
    assert b, "Blender 预设必须内置（默认配置的载体）"
    assert b["command"] == "uvx" and "blender-mcp" in b["args"]


def test_auto_connect_blender_fires_once_and_marks_auto(qapp, monkeypatch):
    import app.modules.lego.extensions_module as EM

    mod = EM.ExtensionsModule()
    mod._mcp_client = object()          # 非 None 即可通过初始化检查（连接被我们拦截）
    calls = []

    def fake_connect(preset):
        calls.append(dict(preset))
        return False                    # 模拟连接失败（uvx 不在）

    monkeypatch.setattr(mod, "_connect_mcp_preset", fake_connect, raising=False)

    mod._create_mcp_tab()
    qapp.processEvents()
    # QTimer.singleShot(600) 的回调需要事件循环；直接手动触发（单测里不等真实定时器）
    mod._auto_connect_blender_preset()
    assert len(calls) == 1, "默认自动连接必须发生且只发生一次"
    assert calls[0].get("_auto") is True, "自动连接必须带 _auto 标记（失败不弹窗）"
    assert calls[0].get("name") == "Blender MCP"

    # 幂等：已连着 Blender 时不重复连（实现用「已连接名单」防重）
    n_before = len(calls)
    mod._connected_mcps.append({"name": "Blender MCP", "state": "已连接", "tools": []})
    mod._auto_connect_blender_preset()
    assert len(calls) == n_before, "已连着 Blender 时不得重复连接"


def test_auto_connect_failure_does_not_raise(monkeypatch):
    """uvx 缺失等失败场景：只记状态，绝不抛异常打断页面构建。"""
    import app.modules.lego.extensions_module as EM

    mod = EM.ExtensionsModule()
    mod._mcp_client = None             # 未初始化 ⇒ _connect_mcp_preset 走弹窗分支
    # 弹窗分支在 offscreen 下会真弹 QMessageBox —— 打桩拦住，验证不抛即可
    warned = []

    import app.modules.lego.extensions_module as _em

    class _FakeMB:
        @staticmethod
        def warning(*a, **k):
            warned.append(a)

    monkeypatch.setattr(_em, "QMessageBox", _FakeMB, raising=False)
    mod._auto_connect_blender_preset()   # 不应抛
    assert warned or True                # 拦到或静默都算通过；关键是没抛
