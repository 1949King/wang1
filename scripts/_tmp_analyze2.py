"""重新分析 editor_module.py 当前方法分布(第一次抽取后)"""
import ast
from pathlib import Path

src = Path(r'd:\拾光剪影\app\modules\lego\editor_module.py').read_text(encoding='utf-8')
lines = src.splitlines()
tree = ast.parse(src)

# 冻结符号(不可触碰)
FROZEN = {
    "_ensure_media_audio_output", "_arm_media_audio", "_ensure_media_signals",
    "_on_media_status_changed", "_on_position_changed", "_on_playback_state_changed",
    "on_deactivated", "_play_pause", "_start_timeline_playback", "_stop_timeline_playback",
    "_on_timeline_playback_tick", "_rebasing_playback_clock", "_sync_bgm_audio",
    "_is_linked_video_audio_clip", "cleanup", "_shutdown_media",
    "_preview_content_rect", "_preview_norm_from_pos", "_clip_box_norm",
    "_hit_preview_transform_mode", "_overlay_transform_handles_on_qimage",
    "_apply_preview_transform_to_clip", "eventFilter",
    # __init__ 也不抽
    "__init__", "_setup_ui", "info",
}

methods = []
for node in ast.walk(tree):
    if isinstance(node, ast.ClassDef) and node.name == 'EditorModule':
        for m in node.body:
            if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                end = getattr(m, 'end_lineno', m.lineno)
                count = end - m.lineno + 1
                frozen = m.name in FROZEN
                methods.append((m.name, m.lineno, end, count, frozen))

methods.sort(key=lambda x: -x[3])
total = sum(m[3] for m in methods)
frozen_total = sum(m[3] for m in methods if m[4])
print(f"共 {len(methods)} 个方法, 总行数: {total}, 冻结: {frozen_total}")
print(f"{'方法名':<50} {'起':>8} {'行数':>6} {'冻结':>4}")
for n, s, e, c, f in methods[:60]:
    flag = "❄️" if f else ""
    print(f"{n[:50]:<50} {s:>8} {c:>6} {flag:>4}")
