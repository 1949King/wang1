# -*- coding: utf-8 -*-
"""画布桥文件流式服务 + CORS 收紧（V4.46.1 安全刀）单测。

serve_file 用假 handler（不真起 HTTP），Range 语义逐条锁；
_is_local_bridge_origin 直接测纯函数。
"""
import io

import pytest

from app.core.canvas_http_file import parse_range, serve_file


class FakeHandler:
    """最小 BaseHTTPRequestHandler 替身：记录状态/头，body 写进 BytesIO。"""

    def __init__(self, headers=None, command="GET"):
        self.headers = dict(headers or {})
        self.command = command
        self.status = None
        self.sent = []          # [(k, v)]
        self.wfile = io.BytesIO()
        self.json_calls = []

    def send_response(self, code):
        self.status = code

    def send_header(self, k, v):
        self.sent.append((k, v))

    def end_headers(self):
        pass

    def _cors(self):
        self.sent.append(("X-Cors", "1"))

    def _json(self, code, payload):
        self.json_calls.append((code, payload))


def _header_map(h):
    return dict(h.sent)


@pytest.fixture()
def sample(tmp_path):
    p = tmp_path / "big.png"
    p.write_bytes(b"A" * 100 + b"B" * 150)  # 250 字节
    return str(p)


# ── parse_range 纯函数 ──────────────────────────────────────────

def test_parse_range_forms():
    assert parse_range("bytes=10-19", 250) == (10, 19)
    assert parse_range("bytes=200-", 250) == (200, 249)
    assert parse_range("bytes=-50", 250) == (200, 249)
    assert parse_range("bytes=0-999999", 250) == (0, 249)   # 越界截到文件尾
    assert parse_range("", 250) is None
    assert parse_range("bytes=abc", 250) is None            # 语法不熟 ⇒ 忽略（整发）
    assert parse_range("bytes=0-1,5-6", 250) is None        # 多段不支持 ⇒ 整发（诚实）
    assert parse_range("bytes=5-1", 250) is None            # end<start ⇒ 整发
    assert parse_range("bytes=-0", 250) is None


# ── serve_file 分支 ────────────────────────────────────────────

def test_serve_full_200(sample):
    h = FakeHandler()
    serve_file(h, sample)
    assert h.status == 200
    hm = _header_map(h)
    assert hm["Content-Length"] == "250"
    assert hm["Accept-Ranges"] == "bytes"
    assert hm["Content-Type"] == "image/png"
    assert h.wfile.getvalue() == b"A" * 100 + b"B" * 150


def test_serve_206_slice(sample):
    h = FakeHandler({"Range": "bytes=100-149"})
    serve_file(h, sample)
    assert h.status == 206
    hm = _header_map(h)
    assert hm["Content-Range"] == "bytes 100-149/250"
    assert hm["Content-Length"] == "50"
    assert h.wfile.getvalue() == b"B" * 50


def test_serve_suffix_range(sample):
    h = FakeHandler({"Range": "bytes=-10"})
    serve_file(h, sample)
    assert h.status == 206
    assert h.wfile.getvalue() == b"B" * 10


def test_serve_416_start_beyond_size(sample):
    h = FakeHandler({"Range": "bytes=999-1200"})
    serve_file(h, sample)
    assert h.status == 416
    assert _header_map(h)["Content-Range"] == "bytes */250"
    assert h.wfile.getvalue() == b""


def test_serve_unknown_range_ignored_full(sample):
    h = FakeHandler({"Range": "bytes=0-1,5-6"})
    serve_file(h, sample)
    assert h.status == 200  # 多段不支持：降级整发而不是报错
    assert len(h.wfile.getvalue()) == 250


def test_serve_head_no_body(sample):
    h = FakeHandler(command="HEAD")
    serve_file(h, sample, inline=False)
    assert h.status == 200
    assert h.wfile.getvalue() == b""
    assert _header_map(h)["Content-Length"] == "250"
    assert "attachment" in _header_map(h)["Content-Disposition"]


def test_serve_empty_file(tmp_path):
    p = tmp_path / "e.mp4"
    p.write_bytes(b"")
    h = FakeHandler()
    serve_file(h, str(p))
    assert h.status == 200
    assert _header_map(h)["Content-Length"] == "0"


# ── CORS 收紧 ──────────────────────────────────────────────────

def test_local_origin_allowlist():
    from app.core.canvas_server import _is_local_bridge_origin

    ok = [
        "http://127.0.0.1:3010", "http://localhost:3011", "http://127.0.0.1:18765",
        "http://[::1]:3010", "http://tauri.localhost", "tauri://localhost",
        "http://127.0.0.5:8080",
    ]
    bad = [
        "http://evil.example.com", "https://attacker.io", "file:///C:/x",
        "http://192.168.1.10:3010", "http://localhost.evil.com", "javascript:alert(1)",
        "http://127.0.0.999:1",
    ]
    for u in ok:
        assert _is_local_bridge_origin(u), u
    for u in bad:
        assert not _is_local_bridge_origin(u), u


def test_cors_allow_origin_pure_function():
    """_cors 的真实逻辑走 cors_allow_origin ⇒ 直接测它（不留复刻假实现）。"""
    from app.core.canvas_server import cors_allow_origin

    # 无 Origin（curl/原生）→ "*" 保持既有行为
    assert cors_allow_origin("") == "*"
    assert cors_allow_origin("   ") == "*"
    # 本机 Origin → 回显自身
    assert cors_allow_origin("http://127.0.0.1:3010") == "http://127.0.0.1:3010"
    assert cors_allow_origin("http://tauri.localhost") == "http://tauri.localhost"
    # 陌生 Origin → None（不写 ACAO 头 ⇒ 浏览器拦截跨站读取）
    assert cors_allow_origin("http://evil.example.com") is None
    assert cors_allow_origin("https://attacker.io") is None
