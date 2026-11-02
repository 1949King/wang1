# -*- coding: utf-8 -*-
"""本地一键拉片 · 视觉解析（I1）。

把参考视频的**代表帧**交给**本机视觉模型**（Ollama），解析景别 / 运镜 / 画面描述，
回填到分镜表 —— 全程 localhost，**素材不出机**（规避参考片 IP 风险）。

为什么单独成模块
----------------
`canvas_aigc.py` 已顶到单文件规模基线（仅 1 行余量），新逻辑不得塞进去；
本模块只**复用**其既有 helper（`_extract_shot_frame` / `_analyze_frame_tone`），
不修改它的任何一行。

诚实降级
--------
本机无视觉模型 / 模型不可用 / 单镜解析失败 → **保留像素启发式**结果，
并如实回填 `vision_fallback=True`，绝不伪装成真实视觉解析。

入口
----
`enrich_shot_table(res, video_path, model="")`：被 canvas_server 的
`/host/video-storyboard` 在 `use_llm=True` 时调用。
`list_local_vision_models()`：被 GET `/host/local-vision-models` 调用（设置页下拉）。
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── 词表（与前端分镜表列候选保持一致）──────────────────────────────
_SHOT_SIZES = ("特写", "近景", "中景", "全景", "远景")
_CAMERAS = ("固定", "推", "拉", "摇", "移", "跟", "升", "降", "手持", "环绕")
_TONES = ("暖", "冷", "中性")

_PROMPT = (
    "你是影视分镜助理。给你同一镜头的起始帧与结束帧（也可能只有 1 帧）。"
    "只输出一个 JSON 对象，不要任何多余文字，字段如下：\n"
    '{"shot_size":"特写|近景|中景|全景|远景",'
    '"camera":"固定|推|拉|摇|移|跟|升|降|手持|环绕",'
    '"tone":"暖|冷|中性",'
    '"description":"不超过30字，概括画面内容与镜头语言"}\n'
    "若画面无明显位移或缩放、无法判断运镜，camera 填「固定」。"
)


def _ollama_client():
    """延迟取 Ollama 客户端（避免顶层导入顺序问题）。"""
    try:
        from app.modules.lego.ollama_client import ollama_client
    except ImportError:
        from modules.lego.ollama_client import ollama_client  # type: ignore

    return ollama_client


def list_local_vision_models() -> List[Dict[str, Any]]:
    """列举本机具备视觉能力的模型（查 Ollama `/api/show` 的 capabilities）。

    返回 [{"name", "size", "vision": True}]，按名称排序；服务不可用时返回 []。
    """
    client = _ollama_client()
    try:
        models = client.list_models() or []
    except Exception as e:
        logger.warning("列举本机模型失败: %s", e)
        return []

    out: List[Dict[str, Any]] = []
    for m in models:
        name = getattr(m, "name", "") or ""
        if not name:
            continue
        try:
            info = client.get_model_info(name) or {}
        except Exception:
            continue
        if "vision" in (info.get("capabilities") or []):
            out.append({"name": name, "size": getattr(m, "size", "") or "", "vision": True})
    out.sort(key=lambda x: x["name"])
    return out


def _resolve_vision_model(model: str = "") -> str:
    """选模型：显式指定且具视觉能力则用之，否则自动挑第一个可用视觉模型；无则空串。"""
    names = [m["name"] for m in list_local_vision_models()]
    if not names:
        return ""
    if model and model in names:
        return model
    return names[0]


def _norm(value: Any, allowed: tuple, default: str) -> str:
    """把模型输出规整到词表内：含关键词即命中，否则回退 default（诚实降级）。"""
    text = str(value or "").strip()
    for a in allowed:
        if a and a in text:
            return a
    return default


def _grab_frame(path: str, t: float, width: int = 256, timeout: float = 60.0) -> Optional[bytes]:
    """在 t 秒抽 1 帧 JPEG bytes（缩到 width 宽），失败返回 None。

    `timeout` 可调：画布桥的请求有 30 秒硬上限（`canvas_server`），从那条路径进来
    必须给更小的值，否则 ffmpeg 还没返回、连接已经被对端放弃了。

    ⚠️ **不复用** `canvas_aigc._extract_shot_frame`：它把临时帧写到 `%TEMP%`，
    本机 AV 锁 `%TEMP%` → ffmpeg 报「Permission denied」抽帧失败（实测踩过）。
    这里写项目自带 `.workbuddy/tmp`（与 `reference_breakdown` 同款，绝不落项目根），
    并缩放以省算力 / base64 体积。
    """
    import subprocess
    import sys as _sys

    try:
        from app.core.ffmpeg_utils import find_ffmpeg
    except ImportError:
        from core.ffmpeg_utils import find_ffmpeg  # type: ignore
    try:
        from app.core.reference_breakdown import _tmp_dir
    except ImportError:
        from core.reference_breakdown import _tmp_dir  # type: ignore

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return None

    out = os.path.join(_tmp_dir(), f"sg_vision_{os.getpid()}_{uuid.uuid4().hex[:8]}.jpg")
    try:
        cmd = [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-ss", f"{max(0.0, t):.3f}", "-i", path,
            "-frames:v", "1", "-vf", f"scale={int(width)}:-2", "-q:v", "4", out,
        ]
        r = subprocess.run(
            cmd, capture_output=True, timeout=max(5.0, float(timeout)),
            creationflags=subprocess.CREATE_NO_WINDOW if _sys.platform == "win32" else 0,
        )
        if r.returncode != 0 or not os.path.isfile(out) or os.path.getsize(out) == 0:
            return None
        with open(out, "rb") as f:
            return f.read()
    except Exception as e:
        logger.debug("抽帧失败 t=%.2f: %s", t, e)
        return None
    finally:
        try:
            os.remove(out)
        except OSError:
            # 临时抽帧文件删除失败（Windows 文件锁 / 已被清理）不影响主流程，
            # 但必须留痕：否则磁盘上会积累无人知晓的残留帧文件。
            logger.debug("临时帧文件清理失败 path=%s", out, exc_info=True)


def _extract_vision_frames(path: str, start: float, end: float) -> List[bytes]:
    """抽该镜头的代表帧：>0.6s 取首尾两帧（供模型判运镜），否则只取中点帧。"""
    mid = (start + end) / 2.0
    if end - start <= 0.6:
        b = _grab_frame(path, mid)
        return [b] if b else []
    ts = [min(max(start + 0.15, start), end), max(min(end - 0.15, end), start)]
    return [b for b in (_grab_frame(path, t) for t in ts) if b]


def _parse_json_obj(text: str) -> Optional[Dict[str, Any]]:
    """容错解析模型输出：先直取 JSON，再退而截取首个 {...} 片段。"""
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except Exception:
        # 直取失败属正常路径（模型常在JSON 前后带话）——走片段兜底，但留痕便于排查。
        logger.debug("模型输出非直取 JSON，转片段兜底", exc_info=True)
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            data = json.loads(m.group(0))
            if isinstance(data, dict):
                return data
        except Exception:
            logger.debug("片段兜底解析也失败，判定为非 JSON 输出", exc_info=True)
    return None


def _ask_vision(model: str, frames: List[bytes]) -> Optional[Dict[str, Any]]:
    """把帧发给本机视觉模型，返回解析后的 dict；失败返回 None。"""
    if not frames:
        return None
    images = [base64.b64encode(b).decode("ascii") for b in frames]
    client = _ollama_client()
    try:
        parts = list(
            client.chat(
                model,
                [{"role": "user", "content": _PROMPT}],
                stream=False,
                think=False,
                images=images,
                format="json",
            )
        )
        text = "".join(parts).strip()
    except Exception as e:
        logger.warning("视觉解析调用失败: %s", e)
        return None
    if not text or text.startswith("错误"):
        logger.debug("视觉解析返回异常: %s", text[:120])
        return None
    return _parse_json_obj(text)


def enrich_shot_table(res: Dict[str, Any], video_path: str, model: str = "") -> Dict[str, Any]:
    """把分镜表逐镜交给本机视觉模型 enrich（景别 / 运镜 / 画面描述）。

    就地回填 res：升级 shots 的 shot / camera / description，并追加
      vision_used / vision_model / vision_fallback / vision_message。
    `tone` / `brightness` 保留像素实测值（视觉模型不覆盖测量量，保持诚实）。
    """
    res["vision_used"] = False
    res["vision_model"] = ""
    res["vision_fallback"] = False
    res["vision_message"] = ""

    shots: List[Dict[str, Any]] = res.get("shots") or []
    if not shots:
        res["vision_fallback"] = True
        res["vision_message"] = "无可解析的镜头"
        return res
    if not video_path or not os.path.isfile(video_path):
        res["vision_fallback"] = True
        res["vision_message"] = "视频文件缺失，已降级为像素启发式"
        return res

    resolved = _resolve_vision_model(model)
    if not resolved:
        res["vision_fallback"] = True
        res["vision_message"] = "本机未发现视觉模型，已降级为像素启发式（请在配置页安装并选择）"
        return res

    try:
        from app.core.ffmpeg_utils import find_ffmpeg
    except ImportError:
        from core.ffmpeg_utils import find_ffmpeg  # type: ignore

    try:
        ffmpeg = find_ffmpeg()
    except Exception:
        ffmpeg = None
    if not ffmpeg:
        res["vision_fallback"] = True
        res["vision_message"] = "未找到 ffmpeg，无法抽帧，已降级为像素启发式"
        return res

    res["vision_model"] = resolved
    enriched = 0
    for row in shots:
        try:
            start = float(row.get("start") or 0.0)
            end = float(row.get("end") or start)
        except (TypeError, ValueError):
            start, end = 0.0, 0.0
        frames = _extract_vision_frames(video_path, start, end)
        parsed = _ask_vision(resolved, frames)
        if not parsed:
            row["vision"] = False
            continue
        row["shot"] = _norm(parsed.get("shot_size"), _SHOT_SIZES, str(row.get("shot") or "中景"))
        row["camera"] = _norm(parsed.get("camera"), _CAMERAS, str(row.get("camera") or "固定"))
        desc = str(parsed.get("description") or "").strip()
        if desc:
            row["description"] = desc
        row["vision"] = True
        enriched += 1

    res["vision_used"] = enriched > 0
    if enriched == 0:
        res["vision_fallback"] = True
        res["vision_message"] = "视觉模型未返回可用结果，已全部保留像素启发式"
    elif enriched < len(shots):
        res["vision_message"] = f"视觉解析 {enriched}/{len(shots)} 镜，其余保留启发式"
    else:
        res["vision_message"] = f"视觉解析完成：{enriched} 镜（模型 {resolved}）"
    return res


def ensure_shot_frames(
    res: Dict[str, Any],
    video_path: str,
    frames_dir: Optional[str] = None,
    frame_url_prefix: Optional[str] = None,
) -> Dict[str, Any]:
    """补齐分镜表「画面」列：仅回填 `frame` 为空的镜头（**纯增量兜底，不覆盖已有帧**）。

    背景：base `video_storyboard_breakdown` 的抽帧复用 `canvas_aigc._extract_shot_frame`，
    该函数把临时帧写到 `%TEMP%`；本机 AV 锁 `%TEMP%` 时 ffmpeg 报「Permission denied」
    ⇒ frame 全为空、画面列空白（实测）。这里用本项目安全抽帧（`.workbuddy/tmp`）回填，
    写出到 frames_dir 并复用同一 `frame_url_prefix`，与 base 产出的帧 URL 完全一致。
    若 base 已正常产出 frame，本函数为 no-op。
    """
    shots: List[Dict[str, Any]] = res.get("shots") or []
    if not shots or not frames_dir:
        return res
    try:
        os.makedirs(frames_dir, exist_ok=True)
    except OSError as e:
        logger.warning("分镜帧目录不可用: %s", e)
        return res

    filled = 0
    for row in shots:
        if row.get("frame"):
            continue
        try:
            start = float(row.get("start") or 0.0)
            end = float(row.get("end") or start)
        except (TypeError, ValueError):
            start, end = 0.0, 0.0
        b = _grab_frame(video_path, (start + end) / 2.0)
        if not b:
            continue
        fname = f"storyboard_{uuid.uuid4().hex[:12]}.jpg"
        try:
            with open(os.path.join(frames_dir, fname), "wb") as f:
                f.write(b)
        except OSError:
            continue
        if frame_url_prefix:
            row["frame"] = f"{frame_url_prefix.rstrip('/')}/{fname}"
        else:
            row["frame"] = "data:image/jpeg;base64," + base64.b64encode(b).decode("ascii")
        filled += 1
    res["frames_filled"] = filled
    return res
