# -*- coding: utf-8 -*-
"""本地模型视图：结构 / 计数 / 不虚构 / 异常不崩。"""
from __future__ import annotations

from app.core.neural import local_models_view as LV


def test_list_local_models_shape_and_honesty() -> None:
    rows = LV.list_local_models()
    assert rows, "至少要列出注册过的本地模型"
    ids = {r["id"] for r in rows}
    for mid in ("sd15-t2i", "sdxl-t2i", "svd-xt-i2v"):
        assert mid in ids
    for r in rows:
        assert r["capability"] in ("image", "video")
        assert isinstance(r["downloaded"], bool)
        assert r["verification"] in ("verified", "unverified", "blocked", "")
        assert set(r) >= {"id", "label", "family", "downloaded", "dir"}


def test_summary_counts_are_consistent() -> None:
    rows = LV.list_local_models()
    s = LV.summary(rows)
    assert s["total"] == len(rows)
    assert s["downloaded"] == sum(1 for r in rows if r["downloaded"])
    assert s["verified"] <= s["total"]
    assert s["by_capability"].get("image", 0) >= 2
    assert s["by_capability"].get("video", 0) >= 3


def test_extra_families_are_honestly_not_downloaded() -> None:
    """只登记没权重的族必须 downloaded=False（不装可用）。"""
    rows = LV.list_local_models()
    for r in rows:
        if r["family"] in ("cogvideox", "hunyuan", "ltx", "mochi", "minimax_h3"):
            assert r["downloaded"] is False
            assert r["verification"] == "unverified"


def test_registry_failure_does_not_raise(monkeypatch) -> None:
    """注册表爆掉时只少列，不许崩。"""
    import app.core.neural.diffusers_image as DI

    monkeypatch.setattr(DI, "available_models", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    rows = LV.list_local_models()
    assert isinstance(rows, list)


def test_panel_renders_rows_offscreen():
    """Qt 页签冒烟：能实例化、有数据、摘要正常（offscreen，不弹窗）。"""
    import os

    import pytest

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PyQt6")
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from app.modules.lego.local_models_panel import LocalModelsPanel

    p = LocalModelsPanel()
    assert p._table.rowCount() >= 3
    assert "已下载" in p._summary.text()
    del app
