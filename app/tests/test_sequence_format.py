# -*- coding: utf-8 -*-
"""工程画幅 SequenceFormat 纯函数测例。"""

from __future__ import annotations

import pytest

from app.core.sequence_format import (
    SequenceFormat,
    parse_aspect,
    parse_resolution,
    normalize_size,
    fit_rect,
    aspect_from_size,
    scale_fit_for_export,
)


@pytest.mark.unit
class TestParse:
    def test_parse_aspect(self):
        assert parse_aspect("9:16") == (9, 16)
        assert parse_aspect("16:9") == (16, 9)
        assert parse_aspect("1:1") == (1, 1)
        assert parse_aspect("4:3") == (4, 3)

    def test_parse_aspect_invalid(self):
        with pytest.raises(ValueError):
            parse_aspect("bad")
        with pytest.raises(ValueError):
            parse_aspect("0:9")

    def test_parse_resolution(self):
        assert parse_resolution("1920x1080") == (1920, 1080)
        assert parse_resolution("1080×1920") == (1080, 1920)
        assert parse_resolution("1080X1080") == (1080, 1080)


@pytest.mark.unit
class TestNormalize:
    def test_portrait_keeps_long_edge(self):
        w, h = normalize_size("9:16", 1920, 1080)
        assert w == 1080 and h == 1920

    def test_landscape_from_portrait_hint(self):
        w, h = normalize_size("16:9", 1080, 1920)
        assert w == 1920 and h == 1080

    def test_square(self):
        w, h = normalize_size("1:1", 1080, 1920)
        assert w == h == 1920

    def test_already_aligned(self):
        w, h = normalize_size("9:16", 1080, 1920)
        assert w == 1080 and h == 1920

    def test_aspect_from_size(self):
        assert aspect_from_size(1080, 1920) == "9:16"
        assert aspect_from_size(1920, 1080) == "16:9"
        assert aspect_from_size(1080, 1080) == "1:1"


@pytest.mark.unit
class TestFitRect:
    def test_contain_letterbox_landscape_in_portrait(self):
        # 16:9 source into 9:16 dest → width fills, height smaller, centered Y
        x, y, w, h = fit_rect(1920, 1080, 1080, 1920, "contain")
        assert w == 1080
        assert h == 608  # 1080 / (16/9) = 607.5 → 608
        assert x == 0
        assert y == (1920 - h) // 2
        assert w <= 1080 and h <= 1920

    def test_contain_pillarbox_portrait_in_landscape(self):
        x, y, w, h = fit_rect(1080, 1920, 1920, 1080, "contain")
        assert h == 1080
        assert w == 608
        assert y == 0
        assert x == (1920 - w) // 2

    def test_cover_fills_dest(self):
        x, y, w, h = fit_rect(1920, 1080, 1080, 1920, "cover")
        # height fills 1920, width overflows
        assert h == 1920
        assert w >= 1080
        assert x <= 0
        assert y == 0

    def test_cover_landscape_dest(self):
        x, y, w, h = fit_rect(1080, 1920, 1920, 1080, "cover")
        assert w == 1920
        assert h >= 1080
        assert y <= 0


@pytest.mark.unit
class TestSequenceFormat:
    def test_default_manju(self):
        sf = SequenceFormat.default()
        assert sf.aspect == "9:16"
        assert sf.width == 1080 and sf.height == 1920
        assert sf.fit_mode == "contain"
        assert "竖屏" in sf.badge_text()
        assert "黑边" in sf.badge_text()

    def test_badge_cover(self):
        sf = SequenceFormat(aspect="16:9", width=1920, height=1080, fit_mode="cover")
        assert "裁切" in sf.badge_text()
        assert "横屏" in sf.badge_text()

    def test_roundtrip_dict(self):
        sf = SequenceFormat(aspect="16:9", width=1920, height=1080, fit_mode="cover")
        back = SequenceFormat.from_dict(sf.to_dict())
        assert back.aspect == "16:9"
        assert back.width == 1920 and back.height == 1080
        assert back.fit_mode == "cover"

    def test_scale_fit_export(self):
        assert scale_fit_for_export("contain") == "pad"
        assert scale_fit_for_export("cover") == "crop"
