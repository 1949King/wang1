# -*- coding: utf-8 -*-
"""二维码（2026-11-02）：生成 → 自己解一遍 → 对得上原文。

只测闭环，不测"长得好不好看"：二维码唯一的功能判据是**扫得出来**。
解不回原文通常就两个原因 —— 少了静区，或者放大的插值方式把模块边缘糊掉了。
"""
from __future__ import annotations

import base64

import pytest

from app.core import team_qr as T


def test_qr_selfcheck_roundtrip():
    pytest.importorskip("cv2")
    assert T.qr_selfcheck() is None
    # 面板上真实会编进去的那串（带查询参数、最长 40 余字符）
    assert T.qr_selfcheck("http://192.168.1.4:18770/pair?code=229140") is None


def test_qr_data_uri_is_png():
    pytest.importorskip("cv2")
    uri = T.qr_png_data_uri("http://192.168.1.4:18770/pair?code=229140")
    assert uri.startswith("data:image/png;base64,")
    raw = base64.b64decode(uri.split(",", 1)[1])
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"


def test_qr_empty_text_returns_empty_string():
    """空串回空串：调用方据此只显示数字码，不能拿空图占位。"""
    assert T.qr_png_data_uri("") == ""
    assert T.qr_png_data_uri("   ") == ""


def test_qr_never_raises_on_garbage():
    """编码器抛什么都不能冒出来 —— 生成二维码只是锦上添花，不许拦住出码。"""
    pytest.importorskip("cv2")
    # 超长 + 控制字符：编不进去也该安静地回空串
    assert T.qr_png_data_uri("a" * 20000) == ""
