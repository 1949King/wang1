"""画布神经补帧任务体（T4 项二，2026-11-20）。

POST /host/interpolate 的实际后端：把视频抽帧 → RIFE v4.9 逐对插帧 →
重编码（fps×multiplier）→ mux 源音轨 → 落 inbox 返回可播放 URL。

诚实纪律
========
- **模型缺失**（find_rife_model()==""）⇒ ok:false + RIFE_MODEL_GUIDANCE，
  绝不触网下载、也不静默降级冒充神经补帧。
- **RIFE 运行时异常**（权重损坏 / torch 缺失 / 显存不足）⇒ 降级光流
  （ai_interpolation._flow_interpolate），degraded=True + reason，engine="flow"。
- 外链视频（_normalize_reference_video 返回 path=""）⇒ 诚实失败（本地补帧需本地文件）。
- 进度为真值（按已处理帧对百分比）；取消经 canvas_gen_jobs 令牌协作式跳出。

分层：本模块属 core 层任务体，由 canvas_routes_post 经 canvas_gen_jobs.submit
调度（worker 线程执行，不卡 HTTP/主界面）。重依赖（torch/cv2/canvas_aigc）懒 import，
使 parse_interpolate_request 纯函数可在无 torch 环境单测。
"""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
import time
from typing import Any, Dict

logger = logging.getLogger("AI短剧编辑器.video_interpolate")

# 补帧倍数钳制区间（×2/×3/×4）；默认 ×2
MULTIPLIER_MIN = 2
MULTIPLIER_MAX = 4
MULTIPLIER_DEFAULT = 2


def parse_interpolate_request(body: Any) -> Dict[str, Any]:
    """解析 /host/interpolate 请求体（纯函数，不触网/不读视频）。

    返回 {ok, video_url, video_path, multiplier, mode, target_fps, title}
    或 {ok:False, error}。multiplier 钳制 [2,4]；legacy mode/target_fps/title 透传。
    """
    if not isinstance(body, dict):
        return {"ok": False, "error": "请求体无效"}
    video_url = str(body.get("video_url") or body.get("videoUrl") or "").strip()
    video_path = str(body.get("video_path") or body.get("videoPath") or "").strip()
    if not video_url and not video_path:
        return {"ok": False, "error": "缺少视频源（video_url / video_path）"}

    raw_m = body.get("multiplier", MULTIPLIER_DEFAULT)
    try:
        multiplier = int(float(raw_m))
    except (TypeError, ValueError):
        multiplier = MULTIPLIER_DEFAULT
    multiplier = max(MULTIPLIER_MIN, min(MULTIPLIER_MAX, multiplier))

    mode = str(body.get("mode") or "smart")
    try:
        target_fps = int(body.get("target_fps") or 24)
    except (TypeError, ValueError):
        target_fps = 24
    title = str(body.get("title") or "")

    return {
        "ok": True,
        "video_url": video_url,
        "video_path": video_path,
        "multiplier": multiplier,
        "mode": mode,
        "target_fps": target_fps,
        "title": title,
    }


def _imread_unicode(path: str):
    """Unicode 安全读图（cv2.imread 中文路径静默失败 ⇒ np.fromfile+imdecode）。"""
    import cv2
    import numpy as np
    try:
        data = np.fromfile(path, dtype=np.uint8)
        if data.size == 0:
            return None
        return cv2.imdecode(data, cv2.IMREAD_COLOR)
    except Exception as e:
        logger.debug("[interpolate] 读帧失败 %s: %s", path, e)
        return None


def _imwrite_unicode(path: str, img_bgr) -> bool:
    """Unicode 安全写图（cv2.imwrite 中文路径静默失败 ⇒ imencode+tofile）。"""
    import cv2
    try:
        ok, buf = cv2.imencode(".png", img_bgr)
        if not ok:
            return False
        buf.tofile(path)
        return True
    except Exception as e:
        logger.debug("[interpolate] 写帧失败 %s: %s", path, e)
        return False


def run_interpolate(req: Dict[str, Any], report: Any) -> Dict[str, Any]:
    """任务体：抽帧 → 插帧 → 编码 → mux 音轨 → 落 inbox。

    report 为 canvas_gen_jobs.StageReporter（stage/progress/note）。
    返回 {ok, video_path, video_url, fps, multiplier, frames_added, engine,
    degraded, reason?} 或 {ok:False, error, guidance?}。
    """
    import cv2

    from app.core import canvas_gen_jobs
    from app.core.ai_interpolation import ContextAwareInterpolator
    from app.core.canvas_aigc import _normalize_reference_video
    from app.core.ffmpeg_utils import get_ffmpeg, mux_source_audio
    from app.core.generation_postprocess import (
        _encode_frames, _extract_frames, _read_video_fps,
    )
    from app.core.neural.rife_engine import (
        RIFE_MODEL_GUIDANCE, RifeEngine, find_rife_model,
    )
    from app.core.neural.rife_net import RifeError, RifeOOMError, RifeUnavailableError

    # ── 1. 视频源归一化为本地 inbox 文件（外链诚实失败）──
    source = req.get("video_path") or req.get("video_url") or ""
    norm = _normalize_reference_video(source)
    if not norm.get("ok"):
        return {"ok": False, "error": norm.get("message", "视频源无效")}
    src_path = norm.get("path") or ""
    if not src_path or not os.path.isfile(src_path):
        return {"ok": False, "error": "视频源不在本地收件箱，无法本地补帧（外链不支持）"}

    multiplier = int(req.get("multiplier") or MULTIPLIER_DEFAULT)

    # ── 2. 模型缺失：诚实报错 + 引导（绝不触网、不冒充）──
    model_path = find_rife_model()
    if not model_path:
        return {"ok": False, "error": "未部署 RIFE 神经补帧模型", "guidance": RIFE_MODEL_GUIDANCE}

    # ── 3. 抽帧 ──
    report.stage("extract", "抽帧")
    report.progress(None)
    ffmpeg = get_ffmpeg()
    workdir = tempfile.mkdtemp(prefix="rife_")
    frames_dir = os.path.join(workdir, "frames")
    out_dir = os.path.join(workdir, "out")
    os.makedirs(frames_dir, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)
    try:
        frame_count = _extract_frames(ffmpeg, src_path, frames_dir)
        if frame_count < 2:
            return {"ok": False, "error": "视频帧数不足（<2），无法补帧"}
        src_fps = _read_video_fps(src_path) or float(req.get("target_fps") or 24)
        out_fps = src_fps * multiplier

        # ── 4. 选引擎：RIFE 加载失败 ⇒ 降级光流（degraded=True）──
        engine = RifeEngine()
        degraded = False
        reason = ""
        engine_name = "rife"
        flow = None
        try:
            loaded = engine.load(model_path)
        except RifeUnavailableError as e:
            loaded, reason = False, f"PyTorch 不可用：{e}"
        except RifeError as e:
            loaded, reason = False, str(e)
        if not loaded:
            degraded, engine_name = True, "flow"
            reason = reason or "RIFE 权重加载失败，降级光流"
            flow = ContextAwareInterpolator()
            report.note(reason)

        def _flow_pair(prev_rgb, cur_rgb, alpha):
            """光流降级（失败再回退线性混合），返回 RGB uint8。"""
            nonlocal flow
            if flow is None:
                flow = ContextAwareInterpolator()
            mid = flow._flow_interpolate(prev_rgb, cur_rgb, alpha)
            if mid is None:
                mid = flow._linear_interpolate(prev_rgb, cur_rgb, alpha)
            return mid

        # ── 5. 逐对插帧（每对插 multiplier-1 帧，真进度）──
        report.stage("interpolate", "神经补帧" if engine_name == "rife" else "光流补帧（降级）")
        out_idx = 1
        frames_added = 0
        total_pairs = frame_count - 1
        prev_bgr = _imread_unicode(os.path.join(frames_dir, "f_000001.png"))
        if prev_bgr is None:
            return {"ok": False, "error": "首帧读取失败"}
        _imwrite_unicode(os.path.join(out_dir, f"f_{out_idx:06d}.png"), prev_bgr)
        out_idx += 1

        for i in range(1, frame_count):
            tok = canvas_gen_jobs.current_token()
            if tok is not None and tok.cancelled:
                raise canvas_gen_jobs.GenCancelled()
            cur_bgr = _imread_unicode(os.path.join(frames_dir, f"f_{i + 1:06d}.png"))
            if cur_bgr is None:
                return {"ok": False, "error": f"第 {i + 1} 帧读取失败"}
            prev_rgb = cv2.cvtColor(prev_bgr, cv2.COLOR_BGR2RGB)
            cur_rgb = cv2.cvtColor(cur_bgr, cv2.COLOR_BGR2RGB)
            for k in range(multiplier - 1):
                alpha = (k + 1) / multiplier
                if engine_name == "rife" and not degraded:
                    try:
                        mid_rgb = engine.interpolate_pair(prev_rgb, cur_rgb, alpha)
                    except RifeOOMError as e:
                        degraded, engine_name = True, "flow"
                        reason = f"显存不足，降级光流：{e}"
                        report.note(reason)
                        mid_rgb = _flow_pair(prev_rgb, cur_rgb, alpha)
                    except RifeError as e:
                        degraded, engine_name = True, "flow"
                        reason = f"RIFE 推理失败，降级光流：{e}"
                        report.note(reason)
                        mid_rgb = _flow_pair(prev_rgb, cur_rgb, alpha)
                else:
                    mid_rgb = _flow_pair(prev_rgb, cur_rgb, alpha)
                mid_bgr = cv2.cvtColor(mid_rgb, cv2.COLOR_RGB2BGR)
                _imwrite_unicode(os.path.join(out_dir, f"f_{out_idx:06d}.png"), mid_bgr)
                out_idx += 1
                frames_added += 1
            _imwrite_unicode(os.path.join(out_dir, f"f_{out_idx:06d}.png"), cur_bgr)
            out_idx += 1
            prev_bgr = cur_bgr
            report.progress(int(i * 100 / total_pairs))

        # ── 6. 重编码（fps×multiplier）──
        report.stage("encode", "编码")
        report.progress(None)
        silent_out = os.path.join(workdir, "silent.mp4")
        if not _encode_frames(ffmpeg, out_dir, silent_out, out_fps):
            return {"ok": False, "error": "FFmpeg 编码失败，请检查 ffmpeg 安装"}

        # ── 7. mux 源音轨 → 落 inbox（无音轨/mux 失败保留无声产物）──
        report.stage("mux", "合入音轨")
        from app.core.canvas_bridge import canvas_inbox_dir
        final_name = f"rife_{int(time.time())}_{multiplier}x.mp4"
        final_path = os.path.join(canvas_inbox_dir(), final_name)
        os.makedirs(os.path.dirname(final_path), exist_ok=True)
        if not mux_source_audio(silent_out, src_path, final_path):
            shutil.copyfile(silent_out, final_path)

        result: Dict[str, Any] = {
            "ok": True,
            "video_path": final_path,
            "video_url": f"/inbox_file/{final_name}",
            "fps": out_fps,
            "multiplier": multiplier,
            "frames_added": frames_added,
            "engine": engine_name,
            "degraded": degraded,
        }
        if reason:
            result["reason"] = reason
        return result
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
