# -*- coding: utf-8 -*-
"""免责声明文本（2026-11-12）：Qt 帮助与画布首屏共用同一份内容约定。"""
from app.core.compliance_text import SECTIONS, VERSION, as_html


def test_sections_complete():
    assert len(SECTIONS) == 7
    titles = [t for t, _ in SECTIONS]
    assert titles[0].startswith("1.")
    assert any("标识" in t for t in titles)
    assert len({t for t, _ in SECTIONS}) == 7


def test_bodies_non_empty_and_no_ascii_quotes():
    for _, body in SECTIONS:
        assert len(body) > 20
        assert '"' not in body  # 避免与 JSON/TS 版本混用时引号风格不一致


def test_version_and_html():
    assert len(VERSION.split(".")) >= 2  # 形如 2026-11-12.1
    html = as_html()
    assert "<h3>" in html and "AI" in html