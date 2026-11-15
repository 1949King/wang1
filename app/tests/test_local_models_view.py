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


def test_size_column_is_never_all_empty() -> None:
    """「体积 GB」整列不许全空 —— 这是字段名写错时的唯一表征。

    2026-11-15 踩过：两个注册表都叫 `download_gb`，视图却分别读 `size_gb` / `subset_gb`，
    两个都取不到 ⇒ UI 十行全是「—」，而实际有 3.97~26.9GB。这类错**不会报异常**。
    """
    rows = LV.list_local_models()
    with_size = [r for r in rows if r.get("size_gb")]
    assert len(with_size) >= 5, [r["id"] for r in rows if not r.get("size_gb")]
    for r in rows:
        if r["id"] in ("sd15-t2i", "sdxl-t2i", "svd-xt-i2v", "wan21-t2v-1.3b", "wan22-ti2v-5b"):
            assert r.get("size_gb"), "%s 应有下载体积" % r["id"]


def test_every_row_carries_sources_without_faking() -> None:
    """每行带 `sources`；有开放权重的族必须给链接，没有的**不许**编一个。"""
    rows = LV.list_local_models()
    for r in rows:
        assert isinstance(r.get("sources"), list)
        for s in r["sources"]:
            assert s["url"].startswith("https://"), s
            assert s["name"] and s["note"]
        if r["family"] == "minimax_h3":
            assert r["sources"] == [], "没有开放权重就不该给链接"
        else:
            assert r["sources"], "%s 应给出社区入口" % r["id"]


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

    # 未选中时给提示，选中后必须长出「魔搭 / GitHub」按钮
    assert "选中一行" in p._src_label.text()
    idx = next(i for i, r in enumerate(p._rows) if r["family"] == "sd15")
    p._table.selectRow(idx)
    assert p._src_box.count() >= 1, "选中行后应有社区入口按钮"
    names = [p._src_box.itemAt(i).widget().text() for i in range(p._src_box.count())]
    assert any("魔搭" in n for n in names), names

    # 换到没有开放权重的那行 ⇒ 按钮必须清空，且说明原因
    idx2 = next(i for i, r in enumerate(p._rows) if r["family"] == "minimax_h3")
    p._table.selectRow(idx2)
    assert p._src_box.count() == 0, "没有权重的族不该留旧按钮"
    assert "没有开放权重" in p._src_label.text()
    del app
