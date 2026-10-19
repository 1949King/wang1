# -*- coding: utf-8 -*-
"""CodeVideoSpec 契约测试（V4.44 · 2026-10-19）

覆盖铁律（改 spec.py 前先跑本文件）：
    1. round-trip：to_dict → from_dict → to_dict 恒等
    2. 文字层铁律：kind∈TEXT_KINDS ⇒ source 必须 html://
    3. limits 硬钳：60s / 12clip / 1080×1920 / fps∈{24,30}
    4. params 白名单：嵌套对象显式进 errors（不静默修正）
    5. source 前缀与目录逃逸防护
    6. from_storyboard：混合 source / 缺 duration 不猜 / 空输入诚实失败
    7. handler：计划态成功 / 无输入失败 / 编译不过失败
"""
from app.core.capability_dispatcher import CapabilityRequest
from app.core.capability_handlers_code_video import CodeVideoCapabilityHandlers
from app.core.code_video.spec import (
    ALLOWED_FPS,
    DEFAULT_MAX_CLIPS,
    DEFAULT_MAX_DURATION,
    SOURCE_PREFIXES,
    SPEC_VERSION,
    TEXT_KINDS,
    AssetEntry,
    CanvasSettings,
    CodeVideoSpec,
    SpecClip,
    SpecLineage,
    SpecTrack,
    compile_spec,
    from_storyboard,
    validate_spec,
)

_STORYBOARD = [
    {"shot": 1, "description": "雨夜霓虹街头，少女回头", "duration": 6.0},
    {"shot": 2, "description": "特写：眼中倒影", "duration": 4.5},
]


def _video_spec(duration: float = 13.5, clips: int = 2) -> CodeVideoSpec:
    """构造一个最小合法 spec（v1 视频轨 + s1 字幕轨）。"""
    clips_list = []
    for i in range(clips):
        start = 3.0 + i * 1.0
        clips_list.append(
            SpecClip(
                id=f"c{i}",
                source=f"asset://shot_{i + 1}.mp4",
                range=[start, start + 1.0],
                kind="video",
            )
        )
    return CodeVideoSpec(
        canvas=CanvasSettings(duration=duration),
        tracks=[
            SpecTrack(id="v1", kind="video", clips=clips_list),
            SpecTrack(
                id="s1",
                kind="subtitle",
                clips=[
                    SpecClip(
                        id="c_sub",
                        source="html://subtitle.html",
                        range=[0.0, duration],
                        kind="subtitle",
                        params={"text": []},
                    )
                ],
            ),
        ],
        assets={f"shot_{i + 1}.mp4": AssetEntry(duration=1.0) for i in range(clips)},
        lineage=SpecLineage(route="hybrid", spec_id="t1", created_by="test"),
    )


# ---------- 1. round-trip ----------

def test_round_trip_to_dict_from_dict():
    spec, errors = from_storyboard(_STORYBOARD, spec_id="rt1")
    assert errors == []
    d1 = spec.to_dict()
    d2 = CodeVideoSpec.from_dict(d1).to_dict()
    assert d1 == d2


# ---------- 2. 文字层铁律 ----------

def test_text_kind_requires_html_source():
    spec = _video_spec()
    spec.tracks[0].clips[0].kind = "subtitle"  # 文字层 kind 却指向 asset://
    compiled, errors = compile_spec(spec)
    assert compiled is None
    assert any("文字层铁律" in e for e in errors)


def test_text_kind_html_source_ok():
    spec = _video_spec()
    spec.tracks[0].clips[0].source = "html://title.html"
    spec.tracks[0].clips[0].kind = "text"
    compiled, errors = compile_spec(spec)
    assert compiled is not None, errors


# ---------- 3. limits 硬钳 ----------

def test_limits_duration_60s():
    spec = _video_spec(duration=90.0)
    spec.tracks[0].clips[0].range = [3.0, 90.0]
    compiled, errors = compile_spec(spec)
    assert compiled is None
    assert any("总时长" in e and "60" in e for e in errors)


def test_limits_clip_count_12():
    spec = _video_spec(duration=30.0, clips=13)
    for i, c in enumerate(spec.tracks[0].clips):
        c.range = [3.0 + i, 4.0 + i]
    spec.tracks[1].clips[0].range = [0.0, 30.0]
    spec.assets = {f"shot_{i + 1}.mp4": AssetEntry(duration=1.0) for i in range(13)}
    compiled, errors = compile_spec(spec)
    assert compiled is None
    assert any("clip 总数" in e for e in errors)


def test_limits_fps_only_24_30():
    spec = _video_spec()
    spec.canvas.fps = 60
    compiled, errors = compile_spec(spec)
    assert compiled is None
    assert any("fps" in e for e in errors)


def test_limits_canvas_1080x1920():
    spec = _video_spec()
    spec.canvas.width = 2160
    spec.canvas.height = 3840
    compiled, errors = compile_spec(spec)
    assert compiled is None
    assert any("分辨率" in e for e in errors)


def test_limits_defaults_constants():
    assert ALLOWED_FPS == (24, 30)
    assert DEFAULT_MAX_DURATION == 60.0
    assert DEFAULT_MAX_CLIPS == 12
    assert SOURCE_PREFIXES == ("asset://", "html://")
    assert TEXT_KINDS == ("text", "subtitle")
    assert SPEC_VERSION == "1.0"


# ---------- 4. params 白名单 ----------

def test_params_whitelist_drops_nested():
    spec = _video_spec()
    spec.tracks[1].clips[0].params = {"text": ["ok"], "evil": {"nested": 1}}
    compiled, errors = compile_spec(spec)
    assert compiled is None
    assert any("params.evil" in e for e in errors)


def test_params_whitelist_keeps_scalars():
    spec = _video_spec()
    spec.tracks[1].clips[0].params = {"text": ["a", "b"], "size": 42, "on": True}
    compiled, errors = compile_spec(spec)
    assert compiled is not None, errors
    sub = [e["clip"] for e in compiled["tracks"] if e["clip"]["id"] == "c_sub"][0]
    assert sub["params"] == {"text": ["a", "b"], "size": 42, "on": True}


# ---------- 5. source 前缀与逃逸防护 ----------

def test_source_prefix_required():
    spec = _video_spec()
    spec.tracks[0].clips[0].source = "file:///etc/passwd"
    compiled, errors = compile_spec(spec)
    assert compiled is None
    assert any("asset://" in e or "html://" in e for e in errors)


def test_asset_path_traversal_blocked():
    for bad in ("asset://../secret.mp4", "asset:///abs/shot.mp4", "asset://C:/x.mp4"):
        spec = _video_spec()
        spec.tracks[0].clips[0].source = bad
        compiled, errors = compile_spec(spec)
        assert compiled is None, bad
        assert errors, bad


def test_html_name_regex_enforced():
    for bad in ("html://Shot.html", "html://../x.html", "html://a b.html"):
        spec = _video_spec()
        spec.tracks[1].clips[0].source = bad
        compiled, errors = compile_spec(spec)
        assert compiled is None, bad
        assert errors, bad


# ---------- 6. from_storyboard ----------

def test_from_storyboard_hybrid_sources():
    spec, errors = from_storyboard(_STORYBOARD, spec_id="cv1")
    assert errors == []
    sources = [c.source for t in spec.tracks for c in t.clips]
    assert "html://title.html" in sources          # 片头（文字层 ⇒ html）
    assert "html://subtitle.html" in sources       # 字幕轨（文字层 ⇒ html）
    assert "asset://shot_1.mp4" in sources   # 镜头（扩散产物位；基准 = canvas_inbox_dir 根）
    assert spec.lineage.route == "hybrid"
    assert spec.lineage.created_by == "pipeline.code_video_plan"
    assert spec.total_clips() == 4


def test_from_storyboard_missing_duration_warns_not_guesses():
    shots = [{"shot": 1, "description": "只有描述没有时长"}]
    spec, errors = from_storyboard(shots)
    assert any("duration" in e for e in errors)
    assert spec is not None                       # 其余部分仍可成草案
    assert spec.total_clips() == 2                # 片头 + 字幕，镜头被跳过
    assert "asset://" not in str(spec.assets)     # 没有猜时长的素材登记


def test_from_storyboard_empty_fails_honestly():
    spec, errors = from_storyboard([])
    assert spec is None
    assert errors


# ---------- 7. validate_spec ----------

def test_validate_spec_version_mismatch():
    d = _video_spec().to_dict()
    d["version"] = "0.9"
    assert any("version" in e for e in validate_spec(d))


def test_validate_spec_track_id_dup():
    spec = _video_spec()
    spec.tracks[1].id = "v1"
    d = spec.to_dict()
    assert any("id 重复" in e for e in validate_spec(d))


def test_validate_spec_canvas_missing_field():
    d = _video_spec().to_dict()
    del d["canvas"]["fps"]
    assert any("fps" in e for e in validate_spec(d))


# ---------- 8. handler 计划态 ----------

def test_handler_plan_success():
    h = CodeVideoCapabilityHandlers()
    res = h.code_video_plan(
        CapabilityRequest(capability_id="pipeline.code_video_plan",
                          params={"storyboard": _STORYBOARD})
    )
    assert res.success
    assert res.output["clip_count"] == 4
    assert res.output["warnings"] == []
    assert res.output["compiled"] is not None
    assert "计划态" in res.output["note"]


def test_handler_plan_no_input_fails():
    h = CodeVideoCapabilityHandlers()
    res = h.code_video_plan(CapabilityRequest(capability_id="pipeline.code_video_plan", params={}))
    assert not res.success
    assert "storyboard" in res.error


def test_handler_plan_compile_fail_fails():
    h = CodeVideoCapabilityHandlers()
    # 10 镜头 × 10s = 100s > 60s limits ⇒ 编译不过 ⇒ 诚实失败
    shots = [{"shot": i, "description": f"镜头{i}", "duration": 10.0} for i in range(1, 11)]
    res = h.code_video_plan(
        CapabilityRequest(capability_id="pipeline.code_video_plan",
                          params={"storyboard": shots})
    )
    assert not res.success
    assert "契约编译" in res.error


def test_handler_plan_warnings_surface():
    h = CodeVideoCapabilityHandlers()
    shots = [{"shot": 1, "description": "缺时长"}, {"shot": 2, "description": "正常", "duration": 5.0}]
    res = h.code_video_plan(
        CapabilityRequest(capability_id="pipeline.code_video_plan",
                          params={"storyboard": shots})
    )
    assert res.success
    assert any("duration" in w for w in res.output["warnings"])
