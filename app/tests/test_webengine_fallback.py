# -*- coding: utf-8 -*-
"""WebEngine 预检 + 浏览器兜底（2026-10-25）。"""
from __future__ import annotations

from pathlib import Path

import app.modules.lego.character_management_module as C

_ROOT = Path(__file__).resolve().parents[2]
_MAIN = _ROOT / "app" / "main_qt6.py"


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


def test_probe_script_exists_and_exits_nonzero_on_broken_env() -> None:
    probe = _ROOT / "_verify" / "probe_webengine.py"
    assert probe.is_file()
    src = probe.read_text(encoding="utf-8")
    assert "QtWebEngineWidgets" in src
    assert "sys.exit(0 if state[\"ok\"] else 3)" in src


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
