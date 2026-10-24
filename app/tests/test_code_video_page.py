# -*- coding: utf-8 -*-
"""合成时间线页面生成器测试（V4.45 · 2026-10-19）

纯字符串断言：不启动 Chromium、不依赖 Qt/ffmpeg。
"""
import json

from app.core.code_video.page_builder import build_timeline_page, inject_clock
from app.core.code_video.spec import compile_spec, from_storyboard

_HTML = "<!doctype html><html><head><style>b{}</style></head><body><div data-sg-text>字幕</div></body></html>"


def _compiled():
    spec, errors = from_storyboard(
        [
            {"shot": 1, "description": "雨夜", "duration": 2.0},
            {"shot": 2, "description": "特写", "duration": 2.0},
        ]
    )
    assert errors == []
    compiled, cerrs = compile_spec(spec)
    assert compiled is not None and cerrs == []
    return compiled, spec


def _paths(tmp_path):
    paths = {}
    for name in ("shot_1.mp4", "shot_2.mp4"):
        p = tmp_path / name
        p.write_bytes(b"0")
        paths[name] = str(p)
    return paths


def test_page_contains_runtime_and_layers(tmp_path):
    compiled, spec = _compiled()
    htmls = {"html://title.html": _HTML, "html://subtitle.html": _HTML}
    page = build_timeline_page(compiled, htmls, _paths(tmp_path))
    assert "window.__sgSeek" in page
    assert "window.__sgReady" in page
    assert "window.__SG_SPEC__" in page
    assert "window.__SG_CLOCK__" in page
    assert 'data-clip="clip_title"' in page
    assert 'data-clip="clip_shot_1"' in page
    assert 'data-source="html://subtitle.html"' in page
    assert "file:///" in page.replace("\\\\", "/")


def test_clock_is_injected_into_html_head():
    out = inject_clock(_HTML)
    assert out.index("<head>") < out.index("__sgSetT") < out.index("</head>")
    out2 = inject_clock("<div>x</div>")
    assert "__sgSetT" in out2


def test_html_content_cannot_break_out_of_script():
    compiled, _ = _compiled()
    evil = '<script>alert("</script><img src=x onerror=alert(1)>")</script>'
    page = build_timeline_page(
        compiled, {"html://title.html": evil, "html://subtitle.html": _HTML}, {}
    )
    # JSON 里 </ 被转义，页面不会出现由内容制造的真实闭合标签
    assert "</script><img" not in page
    assert "<\\/script>" in page


def test_blur_fill_has_background_copy(tmp_path):
    compiled, _ = _compiled()
    for item in compiled["tracks"]:
        if item["clip"]["id"] == "clip_shot_1":
            item["clip"]["fit"] = "blur-fill"
    page = build_timeline_page(compiled, {}, _paths(tmp_path))
    assert "sg-fit-blur" in page
    assert "sg-bg" in page


def test_image_asset_uses_img(tmp_path):
    compiled, _ = _compiled()
    key = "shot_1.mp4"
    compiled["assets"][key]["kind"] = "image"
    page = build_timeline_page(compiled, {}, _paths(tmp_path))
    assert '<img class="sg-media sg-fg"' in page


def test_clip_id_is_escaped(tmp_path):
    compiled, _ = _compiled()
    compiled["tracks"][0]["clip"]["id"] = 'a"b'
    page = build_timeline_page(compiled, {}, _paths(tmp_path))
    assert 'data-clip="a&quot;b"' in page


def test_unknown_asset_path_skipped_not_faked(tmp_path):
    compiled, _ = _compiled()
    page = build_timeline_page(compiled, {}, {})  # 路径没解析出来
    assert 'data-clip="clip_shot_1"' not in page
    assert 'data-clip="clip_title"' in page  # HTML 层不受影响


def test_spec_json_is_parseable():
    compiled, _ = _compiled()
    page = build_timeline_page(compiled, {}, {})
    marker = "window.__SG_SPEC__ = "
    start = page.index(marker) + len(marker)
    end = page.index(";\n", start)
    assert json.loads(page[start:end].replace("<\\/", "</"))["canvas"]["fps"] == 30
