# -*- coding: utf-8 -*-
"""画布加载失败自动拉起 + settings 导航修复（2026-10-25，授权解冻 stage3d-core）。"""
from __future__ import annotations

from pathlib import Path

_LEGO = Path(__file__).resolve().parents[1] / "modules" / "lego"
_CANVAS = _LEGO / "character_management_module.py"
_MAIN = _LEGO / "main_window.py"


def _block(path: Path, func: str, size: int = 2600) -> str:
    src = path.read_text(encoding="utf-8")
    start = src.index("def " + func)
    return src[start:start + size]


def test_load_failure_auto_starts_canvas_service() -> None:
    block = _block(_CANVAS, "_on_web_load_finished")
    assert "is_ready()" in block, "失败路径必须先探测画布服务是否就绪"
    assert "auto start then reload" in block, "未就绪时必须自动启动再加载"
    assert "_on_start_canvas()" in block
    assert "_manual_canvas_start = False" in block, "自动路径不应弹模态框"


def test_load_failure_has_bounded_retries() -> None:
    block = _block(_CANVAS, "_on_web_load_finished")
    assert "retries < 3" in block, "服务就绪但页面仍失败 ⇒ 有限次退避重试"


def test_settings_target_never_hits_nav_missing_toast() -> None:
    """settings 是 nav_hidden：必须先委托 _show_settings，不能走导航栏检查。"""
    block = _block(_MAIN, "_on_module_activated", 12000)
    assert 'target == "settings"' in block
    assert "_show_settings()" in block
    assert block.index('target == "settings"') < block.index("has_module(target)")
