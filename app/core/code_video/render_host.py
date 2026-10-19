# -*- coding: utf-8 -*-
"""渲染编排（V4.45 · 2026-10-19）

一条权威路径：compile → security → resolve → page_builder → render_worker(Chromium)
→ audio_graph(ffmpeg) → encode → ffprobe 校验 → publish_to_inbox → QC 报告。

纪律：
* **顶层零 Qt**：本模块可被能力层/守卫独立导入；Chromium 在子进程（render_worker）。
* **诚实失败**：任何一步失败返回 `{ok:False, stage, error}`，**不产出半成品冒充成功**；
  失败保留工作目录路径供排查，成功才清理。
* **单一实现**：不做第二条「纯素材 ffmpeg 快速路径」（先对后快，见 V4.45 规划 §D1）。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional, Tuple

from app.core.code_video import security, video_critic
from app.core.code_video.audio_graph import build_audio_graph, iter_audio_clips
from app.core.code_video.page_builder import build_timeline_page
from app.core.code_video.spec import CodeVideoSpec, compile_spec

_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,120}$")


# ============================================================
# 工具
# ============================================================

def _fail(stage: str, error: str, work_dir: str = "") -> Dict[str, Any]:
    out: Dict[str, Any] = {"ok": False, "stage": stage, "error": error}
    if work_dir:
        out["work_dir"] = work_dir
    return out


def _ffmpeg_bin() -> str:
    try:
        from app.core.ffmpeg_utils import find_ffmpeg
        found = find_ffmpeg()
    except Exception:  # 找不到就诚实失败
        found = None
    return found or "ffmpeg"


def _ffprobe_bin() -> str:
    try:
        from app.core.ffmpeg_utils import find_ffprobe
        found = find_ffprobe()
    except Exception:
        found = None
    return found or "ffprobe"


def _inbox_dir() -> str:
    from app.core.canvas_bridge import canvas_inbox_dir  # 只 import，不改冻结文件
    return canvas_inbox_dir()


def _probe(path: str) -> Dict[str, Any]:
    cmd = [
        _ffprobe_bin(), "-v", "error",
        "-show_entries", "format=duration:stream=codec_type,width,height,r_frame_rate",
        "-of", "json", path,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30,
                              encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "error": f"ffprobe 不可用：{exc}"}
    if proc.returncode != 0:
        return {"ok": False, "error": (proc.stderr or "").strip()[-500:]}
    try:
        data = json.loads(proc.stdout or "{}")
        data["ok"] = True
        return data
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": f"ffprobe 输出无法解析：{exc}"}


def _has_audio_streams(paths: List[str]) -> Tuple[Dict[str, bool], List[str]]:
    """探测每个素材是否有音轨（ffprobe 缺失 ⇒ 全部视为无音轨并如实 warning）。"""
    result: Dict[str, bool] = {}
    warnings: List[str] = []
    for path in paths:
        if path in result:
            continue
        cmd = [_ffprobe_bin(), "-v", "error", "-select_streams", "a",
               "-show_entries", "stream=index", "-of", "csv=p=0", path]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20,
                                  encoding="utf-8", errors="replace")
        except (OSError, subprocess.SubprocessError):
            result[path] = False
            continue
        result[path] = proc.returncode == 0 and bool((proc.stdout or "").strip())
    if not result:
        warnings.append("没有可探测音轨的素材")
    return result, warnings


def _run_worker(
    page_path: str,
    out_dir: str,
    *,
    fps: int,
    width: int,
    height: int,
    start_frame: int,
    end_frame: int,
    work_dir: str,
    sample_ts: Optional[List[float]] = None,
    timeout_s: float = 300.0,
) -> Dict[str, Any]:
    """启动渲染子进程；失败时读 worker_error.json / stderr，绝不静默。"""
    os.makedirs(out_dir, exist_ok=True)
    tmp_dir = os.path.join(work_dir, "tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    job = {
        "page_path": page_path,
        "out_dir": out_dir,
        "fps": fps,
        "width": width,
        "height": height,
        "start_frame": start_frame,
        "end_frame": end_frame,
        "sample_ts": list(sample_ts) if sample_ts else None,
        "tmp_dir": tmp_dir,
        "progress_path": os.path.join(work_dir, "progress.json"),
    }
    job_path = os.path.join(work_dir, "worker_job.json")
    with open(job_path, "w", encoding="utf-8") as fh:
        json.dump(job, fh, ensure_ascii=False)

    env = dict(os.environ)
    for key in ("TEMP", "TMP", "TMPDIR"):
        env[key] = tmp_dir
    cmd = [sys.executable, "-m", "app.core.code_video.render_worker", "--job", job_path]
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))))
    if os.environ.get("SHIGUANG_RENDER_INPROCESS") == "1":
        # 仅供测试/受限环境：生产必须走子进程（Qt 冲突与 Playwright sync API 线程约束）
        from app.core.code_video import render_worker
        if render_worker.main(["--job", job_path]) != 0:
            raise RuntimeError("worker 失败（in-process 模式，详见 worker_error.json）")
    else:
        try:
            proc = subprocess.run(cmd, cwd=project_root, env=env, capture_output=True,
                                  text=True, timeout=timeout_s, encoding="utf-8",
                                  errors="replace")
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"渲染超时（>{timeout_s}s）") from None
        if proc.returncode != 0:
            detail = ""
            err_file = os.path.join(out_dir, "worker_error.json")
            if os.path.isfile(err_file):
                try:
                    with open(err_file, "r", encoding="utf-8") as fh:
                        detail = str(json.load(fh).get("error") or "")
                except (OSError, json.JSONDecodeError):
                    detail = ""
            raise RuntimeError(detail or (proc.stderr or proc.stdout or "").strip()[-800:])
    manifest_path = os.path.join(out_dir, "worker_manifest.json")
    if not os.path.isfile(manifest_path):
        raise RuntimeError("worker 未产出 manifest（拒绝把「没截图」当成功）")
    with open(manifest_path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _build_encode_cmd(
    frames_dir: str,
    out_path: str,
    *,
    fps: int,
    duration: float,
    audio_inputs: List[str],
    filter_complex: str,
    has_audio: bool,
) -> List[str]:
    cmd = [
        _ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error",
        "-framerate", str(fps), "-i", os.path.join(frames_dir, "frame_%06d.png"),
    ]
    if has_audio:
        for path in audio_inputs:
            cmd += ["-i", path]
        cmd += ["-filter_complex", filter_complex, "-map", "0:v", "-map", "[aout]"]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
        cmd += ["-map", "0:v", "-map", "1:a"]
    cmd += [
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-r", str(fps),
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-t", f"{duration:.6f}", "-movflags", "+faststart", out_path,
    ]
    return cmd


def _validate_output(probe: Dict[str, Any], compiled: Dict[str, Any]) -> List[str]:
    """校验 ffprobe；不一致即视为失败（不交付错片）。"""
    errors: List[str] = []
    canvas = compiled.get("canvas") or {}
    if not probe.get("ok"):
        return [f"ffprobe 校验失败：{probe.get('error', '未知')}"]
    fmt = probe.get("format") or {}
    try:
        actual = float(fmt.get("duration") or 0.0)
        expected = float(canvas.get("duration") or 0.0)
    except (TypeError, ValueError):
        return ["ffprobe 时长无法解析"]
    fps = int(canvas.get("fps") or 0)
    tolerance = (1.5 / fps) if fps else 0.1
    if abs(actual - expected) > tolerance:
        errors.append(f"成片时长 {actual:.3f}s 与预期 {expected:.3f}s 偏差超 1.5 帧")
    for stream in probe.get("streams") or []:
        if stream.get("codec_type") != "video":
            continue
        if int(stream.get("width") or 0) != int(canvas.get("width") or 0):
            errors.append(f"宽 {stream.get('width')} ≠ {canvas.get('width')}")
        if int(stream.get("height") or 0) != int(canvas.get("height") or 0):
            errors.append(f"高 {stream.get('height')} ≠ {canvas.get('height')}")
        rate = str(stream.get("r_frame_rate") or "")
        if rate and rate != f"{fps}/1":
            errors.append(f"帧率 {rate} ≠ {fps}/1")
        break
    return errors


def _publish(mp4_path: str, output_name: str, inbox_dir: str = "") -> Dict[str, str]:
    """发布到画布 inbox。

    显式给 inbox_dir 时直接落该目录（测试/自定义部署），否则复用全局
    `video_gen.publish_to_inbox`（单一实现，不另造一套 URL 规则）。
    """
    name = output_name if _SAFE_NAME_RE.match(output_name or "") else ""
    if not name:
        name = f"code_video_{time.strftime('%Y%m%d_%H%M%S')}.mp4"
    if not inbox_dir:
        from app.core.neural.video_gen import publish_to_inbox
        return publish_to_inbox(mp4_path, name=name)
    from urllib.parse import quote
    from app.core.canvas_bridge import DEFAULT_PORT
    os.makedirs(inbox_dir, exist_ok=True)
    dest = os.path.join(inbox_dir, name)
    if os.path.abspath(dest) != os.path.abspath(mp4_path):
        shutil.copy2(mp4_path, dest)
    return {
        "inbox_name": name,
        "inbox_path": dest,
        "url": f"http://127.0.0.1:{int(DEFAULT_PORT)}/inbox_file/{quote(name)}",
    }


# ============================================================
# 主入口
# ============================================================

def render(
    *,
    spec: Optional[CodeVideoSpec] = None,
    compiled: Optional[Dict[str, Any]] = None,
    html_root: Optional[str] = None,
    inbox_dir: Optional[str] = None,
    output_name: str = "",
    qc: bool = True,
    timeout_s: float = 360.0,
    work_root: Optional[str] = None,
) -> Dict[str, Any]:
    """渲染一份 compiled spec；返回统一结果字典（ok/stage/error 或产物信息）。"""
    work_dir = ""
    started = time.time()
    try:
        # 1. 契约编译（若给的是 spec）
        if compiled is None:
            if spec is None:
                return _fail("compile", "缺少 spec/compiled")
            compiled, compile_errors = compile_spec(spec)
            if compiled is None:
                return _fail("compile", "; ".join(compile_errors))

        # 2. 渲染边界限额 + HTML/素材解析
        errors = security.check_limits(compiled)
        if errors:
            return _fail("security", "; ".join(errors))
        html_contents, errors = security.resolve_html(compiled, html_root)
        if errors:
            return _fail("security", "; ".join(errors))
        inbox = inbox_dir or _inbox_dir()
        asset_paths, errors = security.resolve_assets(compiled, inbox)
        if errors:
            return _fail("resolve_assets", "; ".join(errors))

        canvas = compiled.get("canvas") or {}
        width, height = int(canvas.get("width")), int(canvas.get("height"))
        fps = int(canvas.get("fps"))
        duration = float(canvas.get("duration"))

        # 3. 工作目录 + 合成页
        work_dir = tempfile.mkdtemp(prefix="sg_code_video_", dir=work_root or None)
        page_path = os.path.join(work_dir, "timeline.html")
        with open(page_path, "w", encoding="utf-8") as fh:
            fh.write(build_timeline_page(compiled, html_contents, asset_paths))

        warnings: List[str] = []
        checks: List[Dict[str, str]] = []

        # 4. QC：同 t 双乱序（失败即不渲染整片，避免交付不可复现的片子）
        if qc:
            ts = video_critic.choose_sample_ts(compiled, 5)
            if ts:
                m_a = _run_worker(
                    page_path, os.path.join(work_dir, "qc_a"),
                    fps=fps, width=width, height=height, start_frame=0, end_frame=0,
                    work_dir=work_dir, sample_ts=ts, timeout_s=min(timeout_s, 120.0),
                )
                m_b = _run_worker(
                    page_path, os.path.join(work_dir, "qc_b"),
                    fps=fps, width=width, height=height, start_frame=0, end_frame=0,
                    work_dir=work_dir, sample_ts=list(reversed(ts)),
                    timeout_s=min(timeout_s, 120.0),
                )
                checks.append(video_critic.compare_dual_shuffle(m_a, m_b))
                qc_images = [
                    os.path.join(work_dir, "qc_a", str(f.get("file")))
                    for f in m_a.get("frames") or []
                ]
                checks.append(video_critic.flat_frame_check(qc_images))
                checks.append(video_critic.text_safe_area_check(
                    m_a, width, height, (compiled.get("qc") or {}).get("text_safe_area")
                ))
                if checks[0]["status"] != "pass":
                    return _fail("qc", checks[0]["detail"], work_dir)

        # 5. 整片帧序列
        frames_manifest = _run_worker(
            page_path, os.path.join(work_dir, "frames"),
            fps=fps, width=width, height=height,
            start_frame=0, end_frame=int(round(duration * fps)),
            work_dir=work_dir, timeout_s=timeout_s,
        )
        frame_count = len(frames_manifest.get("frames") or [])
        if frame_count == 0:
            return _fail("render", "worker 输出 0 帧", work_dir)
        if frames_manifest.get("blocked_requests"):
            return _fail(
                "security",
                "运行时拦截到外联请求（静态闸应已拒绝）："
                + ", ".join(frames_manifest["blocked_requests"][:3]),
                work_dir,
            )

        # 6. 音频 + 编码
        clips = iter_audio_clips(compiled)
        keys = [str(c.get("source", ""))[len("asset://"):] for c in clips]
        path_audio, audio_warnings = _has_audio_streams(
            [asset_paths[k] for k in keys if k in asset_paths]
        )
        keys_with_audio = {
            k: bool(path_audio.get(asset_paths.get(k, ""))) for k in keys
        }
        warnings.extend(audio_warnings)
        audio_inputs, filter_complex, has_audio = build_audio_graph(
            clips, keys_with_audio, asset_paths
        )
        out_path = os.path.join(work_dir, "output.mp4")
        cmd = _build_encode_cmd(
            os.path.join(work_dir, "frames"), out_path,
            fps=fps, duration=duration, audio_inputs=audio_inputs,
            filter_complex=filter_complex, has_audio=has_audio,
        )
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s,
                                  encoding="utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            return _fail("encode", f"ffmpeg 编码超时（>{timeout_s}s）", work_dir)
        if proc.returncode != 0 or not os.path.isfile(out_path):
            return _fail("encode", (proc.stderr or "").strip()[-800:], work_dir)
        probe = _probe(out_path)
        probe_errors = _validate_output(probe, compiled)
        if probe_errors:
            return _fail("encode", "; ".join(probe_errors), work_dir)

        # 7. 发布到画布 inbox
        published = _publish(out_path, output_name, inbox)
        if not published:
            return _fail("publish", "落画布 inbox 失败", work_dir)

        # 8. QC 汇总
        if qc:
            if not any(c["name"] == "flat_frame" for c in checks):
                qc_images = [
                    os.path.join(work_dir, "qc_a", str(f.get("file")))
                    for f in frames_manifest.get("frames") or []
                ]
                checks.append(video_critic.flat_frame_check(qc_images))
            if not any(c["name"] == "text_safe_area" for c in checks):
                checks.append(video_critic.text_safe_area_check(
                    frames_manifest, width, height,
                    (compiled.get("qc") or {}).get("text_safe_area"),
                ))
            checks.append({
                "name": "loudness", "status": "not_wired",
                "detail": "V4.45 未接 EBU R128 响度检测，不假装测过",
            })
        qc_report, qc_warnings = video_critic.build_report(
            checks or [{"name": "qc", "status": "not_wired", "detail": "未开启 QC"}]
        )
        warnings.extend(qc_warnings)
        if not qc_report.get("ok"):
            return _fail("qc", "质检未通过", work_dir)

        elapsed = round(time.time() - started, 2)
        result = {
            "ok": True,
            "video_path": published.get("inbox_path") or out_path,
            "url": published.get("url") or "",
            "duration": round(float((probe.get("format") or {}).get("duration") or duration), 3),
            "fps": fps,
            "render": {
                "frames": frame_count,
                "elapsed_s": elapsed,
                "path": "chromium",
            },
            "qc": qc_report,
            "warnings": warnings,
        }
        shutil.rmtree(work_dir, ignore_errors=True)
        return result
    except Exception as exc:  # 编排层必须把失败如实交回
        return _fail("render", f"{type(exc).__name__}: {exc}", work_dir)
