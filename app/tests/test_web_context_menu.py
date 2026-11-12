# -*- coding: utf-8 -*-
"""中文右键菜单（2026-11-12）：菜单项按上下文裁剪，不出现无关项。"""
from app.core.web_context_menu import build_menu_items


def _keys(groups):
    return [k for g in groups for k, _ in g]


def test_plain_area_has_navigation_only():
    keys = _keys(build_menu_items({}))
    assert "back" in keys and "reload" in keys
    assert "copy_image" not in keys and "paste" not in keys


def test_image_context_has_media_items():
    keys = _keys(build_menu_items({"media": "image"}))
    assert {"save_image", "copy_image", "copy_image_url"} <= set(keys)
    assert "copy_media_url" not in keys


def test_video_context_has_media_url_and_play():
    keys = _keys(build_menu_items({"media": "video"}))
    assert {"copy_media_url", "toggle_play"} <= set(keys)
    assert "save_image" not in keys


def test_link_context_has_open_and_copy_link():
    keys = _keys(build_menu_items({"has_link": True}))
    assert {"open_link", "copy_link"} <= set(keys)


def test_editable_context_has_edit_items():
    keys = _keys(build_menu_items({"editable": True}))
    assert {"cut", "paste", "select_all", "copy"} <= set(keys)


def test_labels_are_chinese():
    groups = build_menu_items({"media": "image", "has_link": True, "editable": True})
    labels = [lab for g in groups for _, lab in g]
    assert all(not any(ch.isascii() and ch.isalpha() for ch in lab) for lab in labels), labels
