# -*- coding: utf-8 -*-
"""WebEngine 预检 + 浏览器兜底（2026-10-25）。"""
from __future__ import annotations

from pathlib import Path

import app.modules.lego.character_management_module as C

_ROOT = Path(__file__).resolve().parents[2]
_MAIN = _ROOT / "app" / "main_qt6.py"
_FROZEN_MAIN = _ROOT / "main_qt6.py"


class _FakeSelf:
    def __init__(self) -> None:
        self._web = None
        self.status = []

    def _set_status(self, text: str) -> None:
        self.status.append(text)

    def _ensure_web_view(self) -> bool:
        return False


def test_main_has_webengine_probe_and_sets_flag() -> None:
    src = _MAIN.read_text(encoding="utf-8")
    assert "def _probe_webengine()" in src
    assert "probe_webengine.py" in src
    assert 'SHIGUANG_NO_WEBENGINE"] = "1"' in src


def test_frozen_main_sets_no_sandbox_before_qt_imports() -> None:
    """冻结入口也必须保留已验证的 Chromium 启动标志及导入顺序。"""
    src = _FROZEN_MAIN.read_text(encoding="utf-8")
    flag_assignment = 'os.environ["QTWEBENGINE_CHROMIUM_FLAGS"]'
    assert flag_assignment in src
    assert 'if "--no-sandbox" not in _webengine_flags:' in src
    assert src.index(flag_assignment) < src.index("from PySide6.QtWidgets")


def test_probe_script_exists_and_exits_nonzero_on_broken_env() -> None:
    probe = _ROOT / "_verify" / "probe_webengine.py"
    assert probe.is_file()
    src = probe.read_text(encoding="utf-8")
    assert "QtWebEngineWidgets" in src
    assert "sys.exit(0 if state[\"ok\"] else 3)" in src


def test_probe_passes_non_empty_argv() -> None:
    """🔴 回归锁（2026-10-25）：探针不得给 QApplication 传空 argv。

    实测：`QApplication([])` ⇒ Chromium 打印「Argument list is empty, the program
    name is not passed to QCoreApplication. base::CommandLine cannot be properly
    initialized.」⇒ 渲染进程 fail-fast（0xC0000409 / exit 127），探针**恒失败**
    ⇒ main_qt6 置 SHIGUANG_NO_WEBENGINE=1 ⇒ 应用内画布被永久禁用（黑屏 +
    「画布页面加载失败」）。同一台机器换成非空 argv 立刻 exit 0。

    用 AST 只看**真实调用**，避免被注释/文档字符串里的示例误伤。
    """
    import ast

    src = (_ROOT / "_verify" / "probe_webengine.py").read_text(encoding="utf-8")
    calls = [
        node
        for node in ast.walk(ast.parse(src))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "QApplication"
    ]
    assert calls, "探针必须真的创建 QApplication"
    for call in calls:
        argv = call.args[0] if call.args else None
        # 空列表字面量 / 无参 ⇒ Chromium base::CommandLine 初始化失败 ⇒ fail-fast
        assert not (isinstance(argv, ast.List) and not argv.elts), (
            "QApplication 不得传空 argv（渲染进程会 fail-fast）"
        )
        assert argv is not None, "QApplication 必须显式传非空 argv"



def test_probe_failure_reason_is_observable() -> None:
    """探针诊断必须写 stderr（stdout 被调用方丢弃），否则失败原因不可查。"""
    src = (_ROOT / "_verify" / "probe_webengine.py").read_text(encoding="utf-8")
    assert "sys.stderr.write" in src or "sys.stderr" in src


def test_main_probe_helpers() -> None:
    """main_qt6 必须具备：失败原因落盘（stderr 捕获）+ 强制启用逃生开关。"""
    src = _MAIN.read_text(encoding="utf-8")
    assert "SHIGUANG_FORCE_WEBENGINE" in src
    assert "stderr=subprocess.PIPE" in src
    assert "_startup_mark" in src



def test_ensure_web_view_short_circuits_on_flag(monkeypatch) -> None:
    monkeypatch.setenv("SHIGUANG_NO_WEBENGINE", "1")
    s = _FakeSelf()
    assert C.CharacterManagementModule._ensure_web_view(s) is False
    assert s.status and "系统浏览器" in s.status[0]


def test_load_canvas_falls_back_to_system_browser(monkeypatch) -> None:
    """_ensure_web_view 为 False 时，_load_canvas 必须走 webbrowser.open。"""
    import webbrowser

    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url) or True)
    monkeypatch.setenv("SHIGUANG_NO_WEBENGINE", "1")
    s = _FakeSelf()
    s._pending_canvas_url = ""
    C.CharacterManagementModule._load_canvas(s, "http://127.0.0.1:3011/?token=t")
    assert opened and opened[0].startswith("http://127.0.0.1:3011")
