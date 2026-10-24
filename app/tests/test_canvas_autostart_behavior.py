# -*- coding: utf-8 -*-
"""画布自动拉起的行为级测试（2026-10-25）：真调 _on_web_load_finished，不靠读源码。"""
from __future__ import annotations

import app.core.canvas_runtime as CR
import app.modules.lego.character_management_module as C


class _FakeSelf:
    def __init__(self) -> None:
        self._pending_canvas_url = "http://127.0.0.1:3011/?token=x"
        self._web = object()
        self._canvas_load_retries = 0
        self._manual_canvas_start = True
        self.status = []
        self.started = 0
        self.retried = []

    def _set_status(self, text: str) -> None:
        self.status.append(text)

    def _on_start_canvas(self) -> None:
        self.started += 1

    def _retry_load_canvas(self, url: str) -> None:
        self.retried.append(url)


def test_autostart_when_canvas_service_down(monkeypatch) -> None:
    class RT:
        url = "http://127.0.0.1:3011"

        def is_ready(self) -> bool:
            return False

    monkeypatch.setattr(CR, "get_canvas_runtime", lambda: RT())
    s = _FakeSelf()
    C.CharacterManagementModule._on_web_load_finished(s, False)
    assert s.started == 1, "服务没起时必须自动调用 _on_start_canvas"
    assert s._manual_canvas_start is False, "自动路径不得弹模态框"
    assert any("自动启动" in x for x in s.status)


def test_retry_when_service_ready_but_page_failed(monkeypatch) -> None:
    class RT:
        def is_ready(self) -> bool:
            return True

    monkeypatch.setattr(CR, "get_canvas_runtime", lambda: RT())
    calls = []
    monkeypatch.setattr(
        C, "QTimer", type("Q", (), {"singleShot": staticmethod(lambda ms, fn: calls.append(ms))}))
    s = _FakeSelf()
    C.CharacterManagementModule._on_web_load_finished(s, False)
    assert s.started == 0 and s._canvas_load_retries == 1 and calls


def test_retries_are_bounded(monkeypatch) -> None:
    class RT:
        def is_ready(self) -> bool:
            return True

    monkeypatch.setattr(CR, "get_canvas_runtime", lambda: RT())
    monkeypatch.setattr(
        C, "QTimer", type("Q", (), {"singleShot": staticmethod(lambda ms, fn: None)}))
    s = _FakeSelf()
    s._canvas_load_retries = 3
    C.CharacterManagementModule._on_web_load_finished(s, False)
    assert s._canvas_load_retries == 3, "超过 3 次不再无限重试"
    assert any("加载失败" in x for x in s.status)
