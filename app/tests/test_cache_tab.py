# -*- coding: utf-8 -*-
"""缓存管理页（2026-11-13 重做）：可展开 + 按项删除。"""
import app.modules.lego.settings_cache_tab as C


def test_fmt_size():
    assert C.fmt_size(0) == "0.0 B"
    assert C.fmt_size(1024) == "1.0 KB"
    assert C.fmt_size(5 * 1024 * 1024) == "5.0 MB"


def test_path_size_counts_recursively(tmp_path):
    d = tmp_path / "d"
    d.mkdir()
    (d / "a").write_bytes(b"x" * 100)
    sub = d / "sub"
    sub.mkdir()
    (sub / "b").write_bytes(b"y" * 50)
    assert C.path_size(d) == 150
    assert C.path_size(d / "a") == 100


def test_entries_lists_items_and_deletes_single(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "_app_root", lambda: tmp_path)
    monkeypatch.setitem(C.DIRS, "render_cache", ["render_cache"])
    rc = tmp_path / "render_cache"
    rc.mkdir()
    (rc / "a.tmp").write_bytes(b"x" * 100)
    sub = rc / "sub"
    sub.mkdir()
    (sub / "b").write_bytes(b"y" * 50)

    entries = C.list_entries("render_cache")
    assert {p.name for p, _s, _d in entries} == {"a.tmp", "sub"}

    target = [p for p, _s, _d in entries if p.name == "sub"][0]
    assert C.delete_entry(target) is True
    assert not target.exists()


def test_clear_category_keeps_dir_and_counts(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "_app_root", lambda: tmp_path)
    monkeypatch.setitem(C.DIRS, "render_cache", ["render_cache"])
    rc = tmp_path / "render_cache"
    rc.mkdir()
    (rc / "a.tmp").write_bytes(b"x" * 100)
    removed, freed = C.clear_category("render_cache")
    assert removed == 1
    assert freed == 100
    assert rc.exists()  # 目录保留


def test_model_cache_lists_individual_models(tmp_path, monkeypatch):
    """AI 模型缓存要能列出单个模型（models/cache 容器下的每一项）。"""
    monkeypatch.setattr(C, "_app_root", lambda: tmp_path)
    monkeypatch.setitem(C.DIRS, "model_cache", ["models"])
    (tmp_path / "models" / "cache").mkdir(parents=True)
    for name in ("stable-diffusion-v1-5", "lcm-lora-sdxl"):
        d = tmp_path / "models" / "cache" / name
        d.mkdir()
        (d / "w.bin").write_bytes(b"z" * 10)
    names = {p.name for p, _s, _d in C.list_entries("model_cache")}
    assert names == {"stable-diffusion-v1-5", "lcm-lora-sdxl"}
