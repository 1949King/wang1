# -*- coding: utf-8 -*-
"""捏脸 AI 生成的纯函数测试（不联网）。"""
from __future__ import annotations

from app.core.face_template_ai import ENUM_FIELDS, extract_json, merge_and_validate


def test_enum_fields_come_from_single_source() -> None:
    # 白名单必须与 canvas_bridge 镜像表同源（8 个 A 类扩展都在）
    assert "cat" in ENUM_FIELDS["eyeStyle"]
    assert "sleepy" in ENUM_FIELDS["eyeStyle"]
    assert "glasses" in ENUM_FIELDS["hairAccessory"]
    assert "flower_crown" in ENUM_FIELDS["hairAccessory"]
    assert "pouty" in ENUM_FIELDS["lipStyle"]
    assert "round" in ENUM_FIELDS["browStyle"]


def test_merge_filters_and_clamps() -> None:
    params, dropped = merge_and_validate(
        {
            "browStyle": "cat",          # 不在眉形白名单 ⇒ 丢
            "eyeStyle": "cat",           # 合法
            "hairAccessory": "glasses",  # 合法
            "headWidth": 9,              # 越界 ⇒ 夹到 1
            "mouthCurve": "-0.5",        # 字符串数字 ⇒ 接受
            "evil_key": 1,               # 未知键 ⇒ 丢
        }
    )
    assert params["eyeStyle"] == "cat"
    assert params["hairAccessory"] == "glasses"
    assert params["headWidth"] == 1.0
    assert params["mouthCurve"] == -0.5
    assert "browStyle" in dropped
    assert "evil_key" in dropped


def test_base_is_validated_too() -> None:
    params, dropped = merge_and_validate(
        {"eyeStyle": "big"}, {"eyeStyle": "cat", "skinTone": "#zzz"}
    )
    assert params["eyeStyle"] == "big"  # AI 覆盖 base
    assert "skinTone" in dropped  # 非法 hex 被丢


def test_extract_json_handles_fence_and_noise() -> None:
    assert extract_json('prefix {"eyeStyle":"cat"} suffix') == {"eyeStyle": "cat"}
    fence = chr(96) * 3
    fenced = fence + 'json' + chr(10) + '{"eyeStyle": "cat"}' + chr(10) + fence
    assert extract_json(fenced) == {"eyeStyle": "cat"}
    assert extract_json("not json at all") is None
    assert extract_json("") is None
