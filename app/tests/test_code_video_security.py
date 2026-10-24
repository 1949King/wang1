# -*- coding: utf-8 -*-
"""code_video 渲染安检测试（V4.45 · 2026-10-19）

覆盖：HTML 自包含铁律 / 路径 jail / 资源限额 / 渲染边界铁律再确认。
全部纯函数 + tmp_path，不启动 Chromium、不依赖 Qt。
"""
import os

import pytest

from app.core.code_video import security as sec
from app.core.code_video.spec import compile_spec, from_storyboard

VALID_HTML = """<!doctype html><html><head><style>body{margin:0}</style></head><body>
<div id="t" data-sg-text>\u6807\u9898</div>
<script>
  window.frame = function (t) { document.getElementById('t').textContent = 'T' + t; };
</script></body></html>"""


def _compiled(sources, assets=None, canvas=None, kinds=None):
    kinds = kinds or ["video"] * len(sources)
    return {
        "canvas": canvas or {"width": 1080, "height": 1920, "fps": 30, "duration": 10.0},
        "tracks": [
            {
                "track_id": "v1",
                "track_kind": "video",
                "clip": {
                    "id": f"c{i}",
                    "source": src,
                    "kind": kinds[i],
                    "range": [0.0, 1.0],
                },
            }
            for i, src in enumerate(sources)
        ],
        "assets": assets or {},
    }


# ---------- HTML 静态安检 ----------

def test_valid_self_contained_html_passes():
    assert sec.check_html("title.html", VALID_HTML) == []


def test_w3_org_xmlns_is_not_external_fetch():
    html = '<svg xmlns="http://www.w3.org/2000/svg"><rect width="1" height="1"/></svg>'
    assert sec.check_html("art.html", html) == []


@pytest.mark.parametrize("name", ["Title.html", "a b.html", "../x.html", "x.htm", ""])
def test_bad_html_name_rejected(name):
    assert sec.check_html(name, VALID_HTML)


def test_empty_html_rejected():
    assert sec.check_html("empty.html", "   ")


def test_oversize_html_rejected():
    big = "x" * (sec.MAX_HTML_BYTES + 1)
    errors = sec.check_html("big.html", big)
    assert any("体积" in e for e in errors)


FORBIDDEN_SAMPLES = [
    ("S1-external-http", '<img src="https://evil.example/x.png">'),
    ("S1-script-src", '<script src="x.js"></script>'),
    ("S1-link-href", '<link rel="stylesheet" href="x.css">'),
    ("S1-css-import", "<style>@import url(x.css);</style>"),
    ("S1-protocol-relative", '<img src="//evil.example/x.png">'),
    ("S1-fetch", "<script>fetch('/x')</script>"),
    ("S1-xhr", "<script>new XMLHttpRequest()</script>"),
    ("S1-websocket", "<script>new WebSocket('ws://x')</script>"),
    ("S1-eventsource", "<script>new EventSource('/x')</script>"),
    ("S1-beacon", "<script>navigator.sendBeacon('/x')</script>"),
    ("S1-dynamic-import", "<script>import('./x.js')</script>"),
    ("S1-eval", "<script>eval('1')</script>"),
    ("S1-new-function", "<script>new Function('return 1')</script>"),
    ("S1-window-open", "<script>window.open('/x')</script>"),
    ("S1-navigation", "<script>location.href = '/x'</script>"),
    ("S1-parent-escape", "<script>parent.document.body.remove()</script>"),
    ("S1-base-tag", '<base href="/x/">'),
    ("S1-meta-refresh", '<meta http-equiv="refresh" content="0;url=/x">'),
    ("S1-storage", "<script>localStorage.setItem('a', 'b')</script>"),
]


@pytest.mark.parametrize("rule_id,snippet", FORBIDDEN_SAMPLES)
def test_forbidden_rule_rejected(rule_id, snippet):
    errors = sec.check_html("bad.html", snippet)
    assert any(rule_id in e for e in errors), (rule_id, errors)


def test_rule_table_is_single_source():
    ids = [r[0] for r in sec.FORBIDDEN_RULES]
    assert len(ids) == len(set(ids))
    assert ids == [s[0] for s in FORBIDDEN_SAMPLES]


# ---------- html 路径解析 ----------

def test_resolve_html_reads_file(tmp_path):
    (tmp_path / "title.html").write_text(VALID_HTML, encoding="utf-8")
    contents, errors = sec.resolve_html(_compiled(["html://title.html"]), str(tmp_path))
    assert errors == []
    assert contents["html://title.html"] == VALID_HTML


def test_resolve_html_missing_file(tmp_path):
    _, errors = sec.resolve_html(_compiled(["html://nope.html"]), str(tmp_path))
    assert any("不存在" in e for e in errors)


def test_resolve_html_root_missing(tmp_path):
    _, errors = sec.resolve_html(
        _compiled(["html://a.html"]), str(tmp_path / "missing")
    )
    assert any("根目录不存在" in e for e in errors)


def test_resolve_html_no_sources_needs_no_root(tmp_path):
    contents, errors = sec.resolve_html({}, str(tmp_path / "missing"))
    assert contents == {} and errors == []


def test_resolve_html_rejects_traversal(tmp_path):
    (tmp_path / "x.html").write_text(VALID_HTML, encoding="utf-8")
    _, errors = sec.resolve_html(_compiled(["html://../x.html"]), str(tmp_path))
    assert errors


def test_resolve_html_too_many_files(tmp_path):
    sources = []
    for i in range(sec.MAX_HTML_FILES + 1):
        name = f"a{i}.html"
        (tmp_path / name).write_text(VALID_HTML, encoding="utf-8")
        sources.append(f"html://{name}")
    _, errors = sec.resolve_html(_compiled(sources), str(tmp_path))
    assert any("文件数" in e for e in errors)


def test_resolve_html_total_bytes_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(sec, "MAX_TOTAL_HTML_BYTES", 10)
    (tmp_path / "a.html").write_text(VALID_HTML, encoding="utf-8")
    _, errors = sec.resolve_html(_compiled(["html://a.html"]), str(tmp_path))
    assert any("总字节" in e for e in errors)


# ---------- asset 路径解析 ----------

def test_resolve_assets_ok(tmp_path):
    (tmp_path / "shot_1.mp4").write_bytes(b"0")
    resolved, errors = sec.resolve_assets(_compiled([], {"shot_1.mp4": {}}), str(tmp_path))
    assert errors == []
    assert os.path.isfile(resolved["shot_1.mp4"])


def test_resolve_assets_missing(tmp_path):
    _, errors = sec.resolve_assets(_compiled([], {"shot_9.mp4": {}}), str(tmp_path))
    assert any("不存在" in e for e in errors)


def test_resolve_assets_traversal(tmp_path):
    outside = tmp_path.parent / "evil.mp4"
    outside.write_bytes(b"0")
    _, errors = sec.resolve_assets(_compiled([], {"../evil.mp4": {}}), str(tmp_path))
    assert any("越出 inbox" in e for e in errors)


def test_resolve_assets_inbox_missing(tmp_path):
    _, errors = sec.resolve_assets({}, str(tmp_path / "nope"))
    assert any("inbox 目录不存在" in e for e in errors)


def test_symlink_escape_rejected(tmp_path):
    root = tmp_path / "html"
    root.mkdir()
    outside = tmp_path / "outside.html"
    outside.write_text(VALID_HTML, encoding="utf-8")
    try:
        (root / "link.html").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("本机无权限创建符号链接")
    _, errors = sec.resolve_html(_compiled(["html://link.html"]), str(root))
    assert any("越出" in e for e in errors)


# ---------- 渲染边界限额 ----------

def _compiled_from_storyboard():
    spec, errors = from_storyboard(
        [
            {"shot": 1, "description": "a", "duration": 2.0},
            {"shot": 2, "description": "b", "duration": 2.0},
        ]
    )
    assert errors == []
    compiled, cerrs = compile_spec(spec)
    assert compiled is not None and cerrs == []
    return compiled


def test_check_limits_ok():
    assert sec.check_limits(_compiled_from_storyboard()) == []


def test_check_limits_frames_over_budget():
    errors = sec.check_limits(
        _compiled([], canvas={"width": 1080, "height": 1920, "fps": 30, "duration": 61.0})
    )
    assert any("帧数" in e for e in errors)


def test_check_limits_bad_fps():
    errors = sec.check_limits(
        _compiled([], canvas={"width": 1080, "height": 1920, "fps": 60, "duration": 10.0})
    )
    assert any("fps" in e for e in errors)


def test_check_limits_canvas_too_large():
    errors = sec.check_limits(
        _compiled([], canvas={"width": 2160, "height": 3840, "fps": 30, "duration": 10.0})
    )
    assert any("超上限" in e for e in errors)


def test_check_limits_no_clips():
    errors = sec.check_limits(_compiled([]))
    assert any("没有任何 clip" in e for e in errors)


def test_check_limits_text_law_at_render_boundary():
    errors = sec.check_limits(
        _compiled(["asset://x.mp4"], kinds=["subtitle"])
    )
    assert any("文字层铁律" in e for e in errors)


def test_check_limits_malformed_canvas():
    errors = sec.check_limits({"canvas": {}, "tracks": []})
    assert errors
