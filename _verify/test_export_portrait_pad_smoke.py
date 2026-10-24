"""M2 冒烟：竖屏导出 scale+pad，默认分辨率 1080x1920。"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def test_apply_export_settings_uses_pad_not_stretch():
    from app.modules.lego import video_processor as vp

    src = inspect.getsource(vp.apply_export_settings)
    assert "force_original_aspect_ratio=decrease" in src
    assert "pad=" in src
    assert 'or "1080x1920"' in src or "1080, 1920" in src


def test_export_panel_defaults_portrait():
    path = Path(__file__).resolve().parents[1] / "app/modules/lego/editor_export_panel.py"
    text = path.read_text(encoding="utf-8")
    assert '_ct("_resolution_var", "1080x1920")' in text
    assert '_ct("_aspect_var", "9:16")' in text


def test_export_preset_helpers_exist():
    from app.modules.lego import editor_module as em

    assert hasattr(em.EditorModule, "_apply_manju_portrait_preset")
    assert hasattr(em.EditorModule, "_on_export_platform_changed")
    text = Path(em.__file__).read_text(encoding="utf-8", errors="ignore")
    assert "漫剧竖屏快切" in text
    assert "_apply_manju_portrait_preset" in text


if __name__ == "__main__":
    test_apply_export_settings_uses_pad_not_stretch()
    test_export_panel_defaults_portrait()
    test_export_preset_helpers_exist()
    print("ok")
