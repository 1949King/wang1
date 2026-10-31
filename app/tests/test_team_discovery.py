# -*- coding: utf-8 -*-
"""局域网发现（2026-10-31）：报文编解码 + 真实 UDP 一轮扫到自己。"""
from __future__ import annotations

import time

from app.core import team_discovery as D


def test_encode_decode_roundtrip():
    raw = D.encode_payload("拾光剪影团队", 18770, "192.168.1.5")
    info = D.decode_payload(raw)
    assert info == {"name": "拾光剪影团队", "port": 18770, "host": "192.168.1.5", "ver": "1"}


def test_decode_rejects_foreign_and_broken():
    assert D.decode_payload(b"not json") is None
    assert D.decode_payload(b'{"app":"other","port":1}') is None
    assert D.decode_payload(b'{"app":"shiguang-team","port":"abc"}') is None
    assert D.decode_payload(b'{"app":"shiguang-team","port":99999}') is None


def test_scan_finds_local_beacon():
    """起一个 beacon，再用 scan 扫回来（同机回环不算严格网络测试，但覆盖了收发链路）。"""
    b = D.Beacon("测试团队", 18771, "127.0.0.1", interval=0.2)
    b.start()
    try:
        deadline = time.time() + 6
        hit = []
        while time.time() < deadline and not hit:
            hit = [x for x in D.scan(timeout=1.5) if x["port"] == 18771]
        assert hit, "同一台机器上都扫不到自己的 beacon"
        assert hit[0]["name"] == "测试团队"
    finally:
        b.stop()
