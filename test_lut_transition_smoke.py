"""Smoke: .cube 注册解析 + 转场插件枚举/双帧混合。"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def test_lut_register_cube():
    from app.core.lut_loader import lut_loader
    import numpy as np

    size = 2
    # 最小合法 .cube
    lines = ["TITLE \"Smoke\"", f"LUT_3D_SIZE {size}"]
    for r in range(size):
        for g in range(size):
            for b in range(size):
                lines.append(f"{r/(size-1):.6f} {g/(size-1):.6f} {b/(size-1):.6f}")
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "smoke.cube")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        lut = lut_loader.register_file(path)
        assert lut is not None and lut.data is not None
        got = lut_loader.get_preset(os.path.abspath(path))
        assert got is not None
        rgb = np.zeros((4, 4, 3), dtype=np.float32)
        rgb[..., 0] = 0.5
        out = got.apply(rgb, intensity=1.0)
        assert out.shape == rgb.shape


def test_transition_plugins_list_and_fade():
    from app.core.transition_plugin_registry import (
        display_entries, apply_frames, resolve_plugin_id, xfade_name_for_transition,
    )
    import numpy as np

    entries = display_entries()
    assert entries, "应扫到 transition_*.py"
    ids = {pid for _, pid in entries}
    # fade/slide 依赖 ITransitionPlugin，部分环境可能扫不到；至少应有简易插件
    assert ids & {
        "transition_fade", "transition_dissolve", "transition_wipe",
        "transition_flip", "transition_zoom",
    }, f"转场插件过少: {ids}"
    # 优先用已成功加载的插件做双帧混合（fade/slide 依赖 ITransitionPlugin，可能扫不到）
    pid = next(
        (p for p in (
            "transition_dissolve", "transition_wipe", "transition_zoom",
            "transition_fade", "transition_flip",
        ) if p in ids),
        None,
    ) or resolve_plugin_id("溶解") or resolve_plugin_id("淡入淡出")
    assert pid
    a = np.zeros((8, 8, 3), dtype=np.uint8)
    b = np.full((8, 8, 3), 255, dtype=np.uint8)
    mixed = apply_frames(pid, a, b, 0.5, {"easing": "linear"})
    assert mixed is not None
    assert mixed.shape[:2] == (8, 8)
    assert xfade_name_for_transition({"plugin_id": "transition_slide", "direction": "left"}) == "slideleft"
    assert xfade_name_for_transition({"plugin_id": "transition_wipe", "direction": "up"}) == "wipeup"
    assert xfade_name_for_transition({"type": "滑动转场"}) in ("slideright", "slideleft")


def test_transition_export_fidelity_and_mapping():
    """非 xfade 精确转场：映射扩展 + 诚实降级文案 + bake 标记。"""
    from app.core.transition_plugin_registry import (
        xfade_name_for_transition,
        export_fidelity_for_transition,
        export_degradation_note,
        collect_transition_export_notes,
        is_bakeable_transition,
        apply_frames,
    )
    import numpy as np

    assert xfade_name_for_transition({"plugin_id": "transition_zoom"}) == "zoomin"
    assert xfade_name_for_transition({"plugin_id": "transition_glitch"}) == "pixelize"
    assert xfade_name_for_transition({"plugin_id": "transition_flip"}) == "squeezeh"
    assert xfade_name_for_transition({"plugin_id": "transition_spin"}) == "radial"
    assert xfade_name_for_transition({"plugin_id": "transition_dissolve"}) == "dissolve"

    fade = export_fidelity_for_transition({"plugin_id": "transition_fade"})
    assert fade["mode"] == "exact"
    assert not export_degradation_note({"plugin_id": "transition_fade"})

    glitch = export_fidelity_for_transition({"plugin_id": "transition_glitch", "type": "故障"})
    assert glitch["mode"] == "approx"
    assert "pixelize" in (glitch.get("note") or "")
    assert "近似" in export_degradation_note({"plugin_id": "transition_glitch"})

    zoom = export_fidelity_for_transition({"plugin_id": "transition_zoom"})
    assert zoom["mode"] == "approx"
    assert "zoomin" in (zoom.get("note") or "")

    assert is_bakeable_transition({"plugin_id": "transition_flip"})
    assert is_bakeable_transition({"plugin_id": "transition_spin"})
    assert not is_bakeable_transition({"plugin_id": "transition_glitch"})
    flip_note = export_degradation_note({"plugin_id": "transition_flip"})
    assert "烘焙" in flip_note or "squeezeh" in flip_note

    notes = collect_transition_export_notes([
        {"plugin_id": "transition_fade"},
        {"plugin_id": "transition_glitch"},
        {"plugin_id": "transition_glitch"},
        {"plugin_id": "transition_spin"},
    ])
    assert len(notes) == 2
    assert any("pixelize" in n for n in notes)

    # bake 插件仍可双帧混合（供 bake 路径调用）
    a = np.zeros((16, 16, 3), dtype=np.uint8)
    b = np.full((16, 16, 3), 200, dtype=np.uint8)
    mixed = apply_frames("transition_flip", a, b, 0.4, {"direction": "horizontal"})
    assert mixed is not None and mixed.shape[:2] == (16, 16)
    mixed2 = apply_frames("transition_spin", a, b, 0.6, {})
    assert mixed2 is not None and mixed2.shape[:2] == (16, 16)


def test_build_xfade_uses_extended_mapping():
    from app.modules.lego.video_processor import build_xfade_filtergraph

    fc, v_label, _a = build_xfade_filtergraph(
        [2.0, 2.0],
        [{"plugin_id": "transition_glitch", "duration": 0.5}],
    )
    assert "pixelize" in fc
    assert v_label
    fc2, _, _ = build_xfade_filtergraph(
        [2.0, 2.0],
        [{"plugin_id": "transition_zoom", "duration": 0.4}],
    )
    assert "zoomin" in fc2


if __name__ == "__main__":
    test_lut_register_cube()
    test_transition_plugins_list_and_fade()
    test_transition_export_fidelity_and_mapping()
    test_build_xfade_uses_extended_mapping()
    print("OK")
