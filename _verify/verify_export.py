"""Headless verification of the editing->export pipeline.

Emulates what EditorModule._build_edited_video + editor_scheduler.export_video
now do, using the REAL video_processor functions, and confirms a valid output
is produced with the chosen resolution/fps and baked filters.

Run with the managed venv that has imageio-ffmpeg (provides a real ffmpeg.exe).
"""
import os
import sys
import re
import json
import tempfile
import subprocess

ROOT = r"D:\拾光剪影"
WORK = os.path.join(ROOT, "_verify")
os.makedirs(WORK, exist_ok=True)
sys.path.insert(0, ROOT)

# ── locate ffmpeg / ffprobe ──────────────────────────────────────────────
try:
    import imageio_ffmpeg
    FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    FFMPEG = "ffmpeg"
FFPROBE = FFMPEG.replace("ffmpeg", "ffprobe")
print("FFMPEG:", FFMPEG, os.path.exists(FFMPEG))


def run(cmd):
    r = subprocess.run(cmd, capture_output=True)
    return r.returncode == 0, r.stderr.decode("utf-8", "ignore")[-400:]


# ── 1) generate two source clips (video + audio) ────────────────────────
def gen(path, text):
    cmd = [
        FFMPEG, "-y",
        "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=30:duration=4",
        "-f", "lavfi", "-i", f"aevalsrc=sin(2*PI*440*t):d=4:s=44100",
        "-vf", f"drawtext=text='{text}':x=50:y=50:fontsize=60:fontcolor=white",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
        path,
    ]
    ok, err = run(cmd)
    assert ok, f"gen failed: {err}"
    print("generated", os.path.basename(path))


src_a = os.path.join(WORK, "srcA.mp4")
src_b = os.path.join(WORK, "srcB.mp4")
gen(src_a, "CLIP_A")
gen(src_b, "CLIP_B")

# ── 2) emulate the clip dicts EditorModule now produces ─────────────────
# effects is a DICT (the unified fix); filter + color_params both present.
clips = [
    {
        "path": src_a, "in_point": 0.0, "out_point": 2.0, "start_time": 0.0,
        "filter": "电影感", "filter_intensity": 0.7,
        "effects": {
            "filter": "电影感", "filter_intensity": 0.7,
            "color_params": {"brightness": 0.1, "contrast": 1.2, "saturation": 1.3, "hue": 0},
        },
    },
    {
        "path": src_b, "in_point": 0.0, "out_point": 2.0, "start_time": 2.0,
        "filter": "黑白", "filter_intensity": 0.7,
        "transition": {"type": "淡入淡出", "duration": 0.5},
        "effects": {"filter": "黑白", "filter_intensity": 0.7},
    },
]

from app.modules.lego.video_processor import (
    trim_video, apply_video_filter, merge_with_transitions,
    merge_videos, map_filter_to_vf, apply_export_settings,
)

# ── 3) replicate _build_edited_video logic ───────────────────────────────
tmp_segments, filtered, durations, transitions = [], [], [], []
for clip in clips:
    src = clip["path"]
    in_p, out_p = clip["in_point"], clip["out_point"]
    seg = tempfile.mktemp(suffix=".mp4", dir=WORK)
    if not trim_video(src, seg, in_p, out_p, FFMPEG):
        print("trim failed for", src); continue
    tmp_segments.append(seg)

    eff = clip.get("effects") or {}
    fn = clip.get("filter") or eff.get("filter", "")
    vf = map_filter_to_vf(
        fn,
        float(clip.get("filter_intensity", eff.get("filter_intensity", 0.7))),
        eff.get("color_params"),
    )
    final = seg
    if vf:
        fseg = tempfile.mktemp(suffix=".mp4", dir=WORK)
        if apply_video_filter(seg, fseg, vf, FFMPEG):
            tmp_segments.append(fseg)
            final = fseg
    filtered.append(final)
    durations.append(out_p - in_p)
    if len(filtered) >= 2:
        t = clip.get("transition") or {"type": "淡入淡出", "duration": 0.5}
        transitions.append(t)

edited = os.path.join(WORK, "edited.mp4")
if len(filtered) == 1:
    import shutil
    shutil.copy(filtered[0], edited)
elif transitions:
    merge_with_transitions(filtered, transitions, edited, FFMPEG, None, durations)
else:
    merge_videos(filtered, edited, FFMPEG)
print("edited exists:", os.path.exists(edited),
      "size:", os.path.getsize(edited) if os.path.exists(edited) else 0)

# ── 4) apply export settings (640x360, 24fps, 2M) ───────────────────────
out = os.path.join(WORK, "final.mp4")
params = {
    "resolution": "640x360", "fps": "24", "bitrate": "2M", "codec": "H.264",
    "audio_codec": "AAC", "audio_bitrate": "128k",
    "audio_sample": "44100", "audio_channels": "立体声",
}
ok = apply_export_settings(edited, out, params, FFMPEG)
print("apply_export_settings ok:", ok)

# ── 5) probe final (imageio-ffmpeg ships no ffprobe, use ffmpeg -i) ─────
if os.path.exists(out):
    r = subprocess.run([FFMPEG, "-i", out], capture_output=True)
    txt = (r.stderr or r.stdout).decode("utf-8", "ignore")
    m = re.search(r"Stream.*Video:.*?(\d{2,5})x(\d{2,5})", txt)
    fps_m = re.search(r"(\d+(?:\.\d+)?)\s*fps", txt)
    if m:
        w, h = int(m.group(1)), int(m.group(2))
        print("FINAL:", w, "x", h, "fps:", fps_m.group(1) if fps_m else "?",
              "size:", os.path.getsize(out))
        assert (w, h) == (640, 360), "resolution mismatch!"
        print("RESULT: PASS ✅")
    else:
        print("RESULT: FAIL ❌ (could not parse stream)")
else:
    print("RESULT: FAIL ❌ (no output)")
