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


# ── 配对码查找（2026-11-02）────────────────────────────────
#
# 「码替地址」的关键不是广播本身，而是**没人应答就等于没有**：
# 只有真持有这张有效码的机器出声，无效码一律沉默 ⇒ 穷举拿不到任何反馈。

def test_decode_pair_request_only_accepts_our_digits():
    raw = (D.PAIR_MAGIC_PREFIX + "229140").encode()
    assert D.decode_pair_request(raw) == "229140"
    # 别的软件的包、空包、非数字、超长码一律不认
    assert D.decode_pair_request(b"SHIGUANG_DISCOVER") is None
    assert D.decode_pair_request(b"") is None
    assert D.decode_pair_request((D.PAIR_MAGIC_PREFIX + "12ab").encode()) is None
    assert D.decode_pair_request((D.PAIR_MAGIC_PREFIX + "12345678901").encode()) is None


def test_find_by_code_silent_on_wrong_code():
    """码不对 ⇒ beacon 不出声（这是限速之外的第二道防线）。"""
    b = D.Beacon("测试团队", 18772, "127.0.0.1", interval=0.2,
                 pair_alive=lambda c: c == "229140")
    b.start()
    try:
        # 同一台机上：「正确码」必须问得到自己
        hit = None
        deadline = time.time() + 6
        while time.time() < deadline and hit is None:
            hit = D.find_by_code("229140", timeout=1.5)
        assert hit, "连自己的 beacon 都问不到，配对码这条路根本没通"
        assert hit["port"] == 18772 and hit["address"].startswith("http://")

        # 错误码：等一轮完整超时也不该有任何应答
        assert D.find_by_code("999999", timeout=1.5) is None
    finally:
        b.stop()


def test_find_by_code_rejects_bad_format_without_sending():
    # 格式不对直接回 None，连广播都不发（省得被当成探测流量）
    assert D.find_by_code("abc", timeout=0.1) is None
    assert D.find_by_code("", timeout=0.1) is None
