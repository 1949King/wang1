# -*- coding: utf-8 -*-
"""画布模块入口（本地模型）+ 面板下载按钮（2026-10-25）。"""
from __future__ import annotations

from pathlib import Path

_LEGO = Path(__file__).resolve().parents[1] / "modules" / "lego"


def _src(name: str) -> str:
    return (_LEGO / name).read_text(encoding="utf-8")


def test_canvas_menu_has_local_models_entry() -> None:
    src = _src("character_management_module.py")
    assert 'menu.addAction("本地模型（已下载 / 下载）")' in src
    assert "def _on_open_local_models" in src
    assert "LocalModelsPanel" in src
    # 与主模块同源：弹窗里用的是同一份面板，不是另写一份
    assert "from .local_models_panel import LocalModelsPanel" in src


def test_panel_has_pull_button_and_thread() -> None:
    src = _src("local_models_panel.py")
    assert 'QPushButton("下载选中")' in src
    assert "def _pull_selected" in src
    assert "get_video_engine().pull(" in src
    assert "get_diffusers_image_engine().pull(" in src
    assert "threading.Thread(" in src, "下载不得阻塞 GUI 线程"
