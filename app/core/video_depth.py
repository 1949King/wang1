# -*- coding: utf-8 -*-
"""深度视频/图像提取（刀 A6-深度，2026-10-06）。

对标 LibTV 的「深度视频提取」：把参考视频转成**灰度深度**再喂下游模型，
从而**只搬运运动 / 运镜 / 空间关系，不把原片的人脸与风格带过去**。

⚠️ 诚实性纪律（本模块的红线）
============================
深度**必须来自真正的深度模型**（Depth-Anything-V2-Small ONNX）。
**绝不允许**在模型缺失时"退回灰度/边缘/模糊"来冒充深度 —— 那是「回退冒充 AI」，
是本项目明令禁止的。所以：
  · `available()` 如实报告模型在不在、找不到时给出**确切的获取方式**；
  · 任一提取函数在模型缺失时返回 `{ok: False, available: False, reason, hint}`，
    并把失败原因写进返回值里给用户看，**不产出任何"看起来像深度"的假产物**。

模型与放置
==========
默认搜索 `models/depth/*.onnx`；可用环境变量 `SHIGUANG_DEPTH_MODEL` 指定单文件。
推荐（实测可下，**26MB** quantized）：
  https://hf-mirror.com/onnx-community/depth-anything-v2-small/resolve/main/onnx/model_quantized.onnx
（`huggingface.co` 在国内常被拦，`hf-mirror.com` 可用；下载时需带浏览器 UA。）

性能诚实说明
============
CPU 逐帧推理**不便宜**。本模块不猜、不吹：`extract_depth_video()` 的返回值里带
`frames` / `seconds` / `fps`（**实测值**），由调用方决定要不要降 `max_side` 或改走 GPU。
"""
from __future__ import annotations

import logging
import os
import subprocess
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

ENV_MODEL = "SHIGUANG_DEPTH_MODEL"
DEFAULT_DIR = os.path.join("models", "depth")
MODEL_URL = ("https://hf-mirror.com/onnx-community/depth-anything-v2-small/"
             "resolve/main/onnx/model_quantized.onnx")

# Depth-Anything-V2 用 patch=14 的 ViT，输入边长需为 14 的倍数
_PATCH = 14
_DEFAULT_SIDE = 518          # 官方推荐的长边
_SESSION_CACHE: Dict[str, Any] = {}


def repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def find_model() -> str:
    """返回可用的深度模型路径；没有则空串（**绝不返回占位路径**）。"""
    env = os.environ.get(ENV_MODEL, "").strip()
    if env and os.path.isfile(env):
        return env
    d = os.path.join(repo_root(), DEFAULT_DIR)
    if os.path.isdir(d):
        cands: List[str] = []
        for fn in sorted(os.listdir(d)):
            if fn.lower().endswith(".onnx"):
                p = os.path.join(d, fn)
                if os.path.isfile(p) and os.path.getsize(p) > 1_000_000:
                    cands.append(p)
        if cands:
            return cands[0]
    return ""


def available() -> Dict[str, Any]:
    """深度能力是否可用（**如实报告**，含获取方式）。"""
    p = find_model()
    if p:
        return {"ok": True, "available": True, "model": os.path.basename(p),
                "path": p, "size_mb": round(os.path.getsize(p) / 1024 / 1024, 1)}
    return {
        "ok": False, "available": False, "reason": "未找到深度模型（.onnx）",
        "hint": (f"请下载 Depth-Anything-V2-Small 到 {DEFAULT_DIR}/（约 26MB）：\n"
                 f"  {MODEL_URL}\n"
                 f"或用环境变量 {ENV_MODEL} 指向已有的 .onnx 文件。\n"
                 f"⚠️ 本功能**不会**用灰度/边缘冒充深度。"),
    }


def _session(path: str):
    """按路径缓存 onnxruntime 会话（加载一次即可）。"""
    if path in _SESSION_CACHE:
        return _SESSION_CACHE[path]
    import onnxruntime as ort  # 延迟导入：没有 onnxruntime 时也不该让 import 本模块失败

    opts = ort.SessionOptions()
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    sess = ort.InferenceSession(path, sess_options=opts, providers=["CPUExecutionProvider"])
    _SESSION_CACHE[path] = sess
    return sess


def _input_name(sess) -> str:
    return sess.get_inputs()[0].name


def _output_name(sess) -> str:
    return sess.get_outputs()[0].name


def estimate_depth_bgr(img_bgr) -> Optional[Any]:
    """单帧相对深度（**越大 = 越近**，DPT 系输出的是逆深度，非米制）。

    模型缺失/推理异常 ⇒ 返回 None（调用方据 `available()` 的 reason 向用户解释）。
    """
    path = find_model()
    if not path:
        return None
    try:
        import cv2
        import numpy as np

        sess = _session(path)
        h0, w0 = img_bgr.shape[:2]
        # 缩放到 14 的倍数，且长边不超过 _DEFAULT_SIDE（CPU 上越小越快）
        scale = min(1.0, float(_DEFAULT_SIDE) / max(h0, w0))
        nh = max(_PATCH, int(round(h0 * scale / _PATCH)) * _PATCH)
        nw = max(_PATCH, int(round(w0 * scale / _PATCH)) * _PATCH)
        rgb = cv2.cvtColor(cv2.resize(img_bgr, (nw, nh), interpolation=cv2.INTER_AREA),
                           cv2.COLOR_BGR2RGB).astype("float32") / 255.0
        mean = np.array([0.485, 0.456, 0.406], dtype="float32")
        std = np.array([0.229, 0.224, 0.225], dtype="float32")
        rgb = (rgb - mean) / std
        inp = np.transpose(rgb, (2, 0, 1))[None, ...].astype("float32")
        out = sess.run([_output_name(sess)], {_input_name(sess): inp})[0]
        depth = np.asarray(out, dtype="float32")
        while depth.ndim > 2:
            depth = depth[0]
        # 回到原分辨率，便于逐帧对齐下游
        depth = cv2.resize(depth, (w0, h0), interpolation=cv2.INTER_LINEAR)
        return depth
    except Exception as e:
        logger.warning("[video_depth] 单帧深度推理失败: %s", e)
        return None


def to_gray_u8(depth) -> Any:
    """把相对深度线性映射到 0..255（**逐帧归一化**；这是相对深度，不是米制距离）。"""
    import numpy as np

    d = np.asarray(depth, dtype="float32")
    lo, hi = float(np.min(d)), float(np.max(d))
    if not np.isfinite(lo) or not np.isfinite(hi) or hi - lo < 1e-6:
        return np.zeros(d.shape, dtype="uint8")   # 全平（理论上不会出现在真实画面）
    return np.clip((d - lo) / (hi - lo) * 255.0, 0, 255).astype("uint8")


def extract_depth_image(src_path: str, dst_path: str) -> Dict[str, Any]:
    """单图 → 灰度深度图（PNG）。模型缺失时**如实失败**。"""
    av = available()
    if not av.get("available"):
        return {"ok": False, **av}
    try:
        import cv2

        img = cv2.imread(src_path)
        if img is None:
            return {"ok": False, "reason": f"读不到图片: {src_path}"}
        d = estimate_depth_bgr(img)
        if d is None:
            return {"ok": False, "reason": "深度推理失败（模型加载/推理异常，详见日志）"}
        os.makedirs(os.path.dirname(os.path.abspath(dst_path)), exist_ok=True)
        ok = cv2.imwrite(dst_path, to_gray_u8(d))
        return {"ok": bool(ok), "dst": dst_path, "model": av.get("model"),
                "note": "相对深度（越大越近），逐帧归一化到 0..255"}
    except Exception as e:
        logger.exception("[video_depth] extract_depth_image 失败")
        return {"ok": False, "reason": str(e)}


def extract_depth_video(src_path: str, dst_path: str, *,
                        max_side: int = 384, limit_frames: int = 0) -> Dict[str, Any]:
    """视频 → 灰度深度视频（H.264，走 ffmpeg 管道）。

    · `max_side`：推理分辨率上限（CPU 上建议 320~384，越小越快）
    · `limit_frames`：>0 时只处理前 N 帧（调试/预览用）
    返回**实测**帧数与耗时 —— 不吹性能。
    """
    av = available()
    if not av.get("available"):
        return {"ok": False, **av}
    try:
        import cv2
        import numpy as np

        cap = cv2.VideoCapture(src_path)
        if not cap.isOpened():
            return {"ok": False, "reason": f"读不到视频: {src_path}"}
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        if w <= 0 or h <= 0:
            cap.release()
            return {"ok": False, "reason": "视频尺寸读不到"}

        from app.core.ffmpeg_utils import find_ffmpeg  # 复用项目既有 ffmpeg 定位
        ff = find_ffmpeg()
        if not ff:
            cap.release()
            return {"ok": False, "reason": "ffmpeg 不可用（深度视频需要它来编码）"}

        os.makedirs(os.path.dirname(os.path.abspath(dst_path)), exist_ok=True)
        cmd = [ff, "-y", "-hide_banner", "-loglevel", "error",
               "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{w}x{h}", "-r", f"{fps:.6f}",
               "-i", "-", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
               dst_path]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

        t0 = time.time()
        n = 0
        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                # 推理用缩放帧（速度），输出回原尺寸灰度
                small = frame
                if max_side and max(frame.shape[:2]) > max_side:
                    sc = max_side / max(frame.shape[:2])
                    small = cv2.resize(frame, (max(14, int(frame.shape[1] * sc)),
                                               max(14, int(frame.shape[0] * sc))),
                                       interpolation=cv2.INTER_AREA)
                d = estimate_depth_bgr(small)
                if d is None:
                    raise RuntimeError("深度推理失败（逐帧中断，如实失败，不产出半成品）")
                gray = to_gray_u8(d)
                if gray.shape[:2] != (h, w):
                    gray = cv2.resize(gray, (w, h), interpolation=cv2.INTER_LINEAR)
                proc.stdin.write(np.ascontiguousarray(gray).tobytes())  # type: ignore[union-attr]
                n += 1
                if limit_frames and n >= limit_frames:
                    break
        finally:
            cap.release()
            try:
                proc.stdin.close()          # type: ignore[union-attr]
            except Exception:  # stability-gate: allow-swallow（finally 里关 ffmpeg stdin；管道可能已被子进程关闭，关闭异常无意义）
                pass
            proc.wait(timeout=120)

        secs = max(1e-6, time.time() - t0)
        if proc.returncode != 0:
            err = (proc.stderr.read() or b"").decode("utf-8", "ignore")[-300:]
            return {"ok": False, "reason": f"ffmpeg 编码失败(code={proc.returncode}): {err}"}
        return {"ok": True, "dst": dst_path, "frames": n, "seconds": round(secs, 2),
                "fps": round(n / secs, 2), "model": av.get("model"),
                "note": "灰度**相对**深度（越大越近）；用于搬运运动/运镜，不保留人脸与风格"}
    except Exception as e:
        logger.exception("[video_depth] extract_depth_video 失败")
        return {"ok": False, "reason": str(e)}
