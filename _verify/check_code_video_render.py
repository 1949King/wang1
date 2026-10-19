#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""渲染引擎门禁（V4.45 · 2026-10-19）

锁四件事：
  A. 安检规则表在册且无重复（security.FORBIDDEN_RULES）
  B. Playwright/Chromium 可用（不可用 ⇒ **显式 SKIP**，不假绿）
  C. 真实渲染冒烟：360×640 / 24fps / 0.5s 的 HTML 镜头 → mp4（含 QC 双乱序）
  D. 产物真实：ffprobe 时长/宽高/帧率一致；文字安全区 pass；失败不交半成品

用法（项目根执行）：
    .venv312\\Scripts\\python.exe _verify/check_code_video_render.py
"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_TMP_BASE = os.path.join(ROOT, ".workbuddy", "tmp")
os.makedirs(_TMP_BASE, exist_ok=True)
os.environ["TEMP"] = os.environ["TMP"] = os.environ["TMPDIR"] = _TMP_BASE

_failures: list = []


def check(cond, msg):
    if cond:
        print(f"  ✓ {msg}")
    else:
        print(f"  ✗ {msg}")
        _failures.append(msg)


HTML = """<!doctype html><html><head><meta charset="utf-8">
<style>html,body{margin:0;background:#0b0f1a;color:#fff;font:24px sans-serif}
#t{position:absolute;top:45%;left:10%;width:80%;text-align:center}
</style></head><body>
<div id="t" data-sg-text>GUARD</div>
<script>window.__sgFrame=function(t){document.getElementById('t').textContent='GUARD '+t.toFixed(2);};</script>
</body></html>"""


# ── A. 安检规则表 ──
print("[A] 安检规则表在册")
from app.core.code_video import security as sec

_ids = [r[0] for r in sec.FORBIDDEN_RULES]
check(len(_ids) >= 15, f"禁用规则 {len(_ids)} 条（≥15）")
check(len(_ids) == len(set(_ids)), "规则 id 无重复")
check(sec.check_html("ok.html", HTML) == [], "守卫自带 HTML 通过静态安检")

# ── B. Chromium 可用性（不可用 ⇒ 显式 SKIP）──
print("[B] Playwright/Chromium 可用性")
_probe = subprocess.run(
    [sys.executable, "-m", "app.core.code_video.render_worker", "--check"],
    cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
)
available = _probe.returncode == 0 and '"ok": true' in (_probe.stdout or "").replace("'", '"')
if not available:
    print(f"  SKIP Chromium 不可用：{(_probe.stdout or _probe.stderr or '').strip()[:200]}")
    print("  （显式跳过，不判失败；请在真机跑一次渲染验收）")
    print()
    print("OK 渲染引擎门禁：静态部分通过（动态冒烟 SKIP）")
    sys.exit(0)
check(True, "Chromium 可用")

# ── C. 真实渲染冒烟 ──
print("[C] 真实渲染冒烟（360×640 / 24fps / 0.5s HTML 镜头）")
from app.core.code_video.render_host import render
from app.core.code_video.spec import (
    CanvasSettings,
    CodeVideoSpec,
    SpecClip,
    SpecTrack,
    compile_spec,
)

work = tempfile.mkdtemp(prefix="sg_guard_render_", dir=_TMP_BASE)
try:
    html_dir = os.path.join(work, "html")
    os.makedirs(html_dir, exist_ok=True)
    with open(os.path.join(html_dir, "title.html"), "w", encoding="utf-8") as fh:
        fh.write(HTML)
    inbox = os.path.join(work, "inbox")
    os.makedirs(inbox, exist_ok=True)

    spec = CodeVideoSpec(
        canvas=CanvasSettings(width=360, height=640, fps=24, duration=0.5),
        tracks=[SpecTrack(id="v1", kind="video", clips=[
            SpecClip(id="c1", source="html://title.html", range=[0.0, 0.5], kind="video"),
        ])],
    )
    compiled, errors = compile_spec(spec)
    check(compiled is not None, f"compile_spec 通过（{errors[:2]}）")
    if compiled is None:
        raise SystemExit(1)

    result = render(
        compiled=compiled,
        html_root=html_dir,
        inbox_dir=inbox,
        output_name="guard_render.mp4",
        qc=True,
        timeout_s=180,
        work_root=work,
    )
    check(result.get("ok") is True, f"render ok（stage={result.get('stage')} err={result.get('error')}）")
    check(os.path.isfile(result.get("video_path") or ""), "产物 mp4 存在")
    qc = {c["name"]: c["status"] for c in (result.get("qc") or {}).get("checks") or []}
    check(qc.get("dual_shuffle") == "pass", f"QC 同 t 双乱序 pass（{qc}）")
    check(qc.get("text_safe_area") == "pass", "QC 文字安全区 pass（data-sg-text 在安全区内）")
    check(qc.get("loudness") == "not_wired", "响度显式 not_wired（不假装测过）")

    # ── D. 产物真实（ffprobe）──
    print("[D] ffprobe 产物校验")
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration:stream=codec_type,width,height,r_frame_rate",
         "-of", "json", result["video_path"]],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    check(probe.returncode == 0, "ffprobe 可读产物")
    data = json.loads(probe.stdout or "{}")
    video = next((s for s in data.get("streams") or [] if s.get("codec_type") == "video"), {})
    check(video.get("width") == 360 and video.get("height") == 640,
          f"宽高 360×640（{video.get('width')}×{video.get('height')}）")
    check(video.get("r_frame_rate") == "24/1", f"帧率 24/1（{video.get('r_frame_rate')}）")
    check(abs(float(data.get("format", {}).get("duration", 0)) - 0.5) <= 0.0625,
          f"时长 ≈0.5s（{data.get('format', {}).get('duration')}）")
finally:
    shutil.rmtree(work, ignore_errors=True)

print()
if _failures:
    print(f"✗ 失败 {len(_failures)} 项")
    sys.exit(1)
print("OK 渲染引擎门禁全绿（真渲染 + QC + ffprobe）")
