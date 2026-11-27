# -*- coding: utf-8 -*-
"""画布「意图级」增强层 —— 把散落的神经引擎收拢成**意图**，而不是**节点**

为什么不走 ComfyUI 的老路
==========================
ComfyUI 的做法是**把底层原语暴露成节点**：要做「修脸」你得连
`Load GFPGAN → Detect Face → Crop 512 → Restore → Paste Back` 五六个节点，
还要懂采样器/步数/CFG。后果是 60000+ 节点、用户必须是扩散模型工程师。

本模块走**相反**的路：**只暴露「意图」，把实现留给系统**。

| | ComfyUI | 本模块 |
|---|---|---|
| 用户面对的语言 | 模型名 / 采样器 / 潜空间 | **「修复人脸」「放大」「抠像」** |
| 组合方式 | 有向图（DAG） | **有序列表**（`["face","sharpen"]`） |
| 实现选择 | 用户选模型 | **系统选**，并**如实报告用了哪个** |
| 质量档位 | steps/cfg/denoise 全暴露 | `fast / standard / high` 三档 |

**核心判断：后处理天然是线性的（图 → 图），不需要 DAG。**
所以这里**把「链」从「图」降级为「列表」** —— 这是与 ComfyUI 最本质的分歧。

三条纪律
--------
1. **诚实报告**：每一步都回报**实际用了哪个引擎**（gfpgan / espcn / realesrgan / bicubic /
   cpu-fallback），以及**是否降级**及原因。绝不把「双三次插值」说成「AI 超分」。
2. **绝不抛异常**：任何一步失败只跳过该步、记进 `skipped`，主链路继续。
3. **绝不自动下载模型**（T2，2026-11-20）：`high` 档也只认用户**自取放置**的
   RealESRGAN 权重；缺失时诚实降级，获取方式见「下载中心」，绝不替用户下载几百 MB。

边界（不做的事）
----------------
- 不做「把每个引擎变成一个节点」——那正是本模块要避免的。
- 不做通用 DAG 编排——需要 DAG 的场景请用 `canvas_workflow_runner`（生成类节点）。
- 不判审美（那是 `gen_critic` / `five_dimension_scorer` 的职责）。

实现纪律
--------
每个意图处理器**只实现一次**，返回 `(report, out_image)` ——
报告给用户、数组给下一步（列表式流水线）。**不存在第二份引擎调用**。
"""
from __future__ import annotations

import base64
import logging
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── 意图目录（**唯一真源**：这里加一行 = 多一个能力，不加节点、不改前端布局）──
# ⚠️ 文案纪律：`label`/`hint` **只描述意图，绝不写模型名或算法名**
#    （写「用 RealESRGAN」就是把用户推回 ComfyUI 的「选模型」老路）。
#    用户该看到的是「更清晰但更慢」，不是「ESPCN 还是 RealESRGAN」。
ENHANCE_INTENTS: Dict[str, Dict[str, Any]] = {
    "face": {
        "label": "修复人脸",
        "hint": "让面部更清晰自然；没有检测到人脸时原样返回",
    },
    "cutout": {
        "label": "抠像换背景",
        "hint": "把主体从背景里分离出来；可换成纯色底或保留透明底",
    },
    "sharpen": {
        "label": "超分放大",
        "hint": "放大画面并补细节；高质量档更清晰但更慢，高清权重需自取（获取方式见下载中心）",
    },
    "style": {
        "label": "风格迁移",
        "hint": "按指定的画风重绘，可调强度",
    },
    "heal": {
        "label": "局部修图",
        "hint": "只重绘你框选（涂抹）的区域，其余像素保持不动",
    },
}

# ── 质量档位 → 实现层参数（**用户不碰模型名**）──
# 注：只有 high 档置 use_realesrgan=True ⇒ 只有它会尝试 RealESRGAN（T2：绝不自动下载，
# 只认用户自取放置的权重，缺失诚实降级）。其余档位走 OpenCV 内置 ESPCN，不碰任何下载。
QUALITY_TIERS: Dict[str, Dict[str, Any]] = {
    "fast": {"sr_scale": 2, "use_realesrgan": False},
    "standard": {"sr_scale": 2, "use_realesrgan": False},
    "high": {"sr_scale": 4, "use_realesrgan": True},
}

_DATA_URL_RE = re.compile(r"^data:image/[a-zA-Z0-9.+-]+;base64,(.+)$", re.S)


def available_intents() -> List[Dict[str, str]]:
    """供 UI 渲染意图选择器（不暴露任何模型名）。"""
    return [{"id": k, "label": v["label"], "hint": v["hint"]}
            for k, v in ENHANCE_INTENTS.items()]


# ────────────────────────── 编解码 ──────────────────────────


def _decode(data_url: str):
    """data URL → BGR/BGRA ndarray。失败返回 None（不抛）。"""
    if not data_url or not isinstance(data_url, str):
        return None
    m = _DATA_URL_RE.match(data_url.strip())
    if not m:
        return None
    try:
        import cv2
        import numpy as np
        raw = base64.b64decode(m.group(1), validate=False)
        buf = np.frombuffer(raw, dtype="uint8")
        # IMREAD_UNCHANGED：保留 alpha（抠像输出可能带透明通道）
        return cv2.imdecode(buf, cv2.IMREAD_UNCHANGED)
    except Exception:
        logger.debug("[canvas_enhance] 解码失败", exc_info=True)
        return None


def _encode(img) -> Optional[str]:
    """ndarray → PNG data URL（保留 alpha）。失败返回 None（不抛）。"""
    if img is None:
        return None
    try:
        import cv2
        ok, buf = cv2.imencode(".png", img)
        if not ok:
            return None
        return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode("ascii")
    except Exception:
        logger.debug("[canvas_enhance] 编码失败", exc_info=True)
        return None


def _bgr(img):
    """统一成 3 通道 BGR（丢掉 alpha）——给不支持 alpha 的引擎用。"""
    if img is not None and getattr(img, "ndim", 0) == 3 and img.shape[2] == 4:
        return img[:, :, :3]
    return img


# ────────────────────────── 意图处理器（**每个只实现一次**） ──────────────────────────
# 约定：返回 (report_dict, out_image_or_None)
#   report 内含 applied / engine / degraded / reason —— 全部**如实**
#   out_image 给下一步用（列表式流水线）；None 表示本步无产物


def _step_face(img, quality: str, params: Dict[str, Any]) -> Tuple[Dict[str, Any], Any]:
    from app.core.neural.face_restore import FaceRestoreEngine
    out = FaceRestoreEngine().enhance(img)
    if out is None:
        return {"applied": False, "reason": "人脸修复引擎返回空"}, None
    changed = out is not img
    if not changed:
        return {"applied": False, "engine": "region-sr",
                "reason": "未检测到人脸或修复未改变图像（原样返回）"}, None
    return {"applied": True, "engine": "region-sr"}, out


def _step_sharpen(img, quality: str, params: Dict[str, Any]) -> Tuple[Dict[str, Any], Any]:
    tier = QUALITY_TIERS.get(quality) or QUALITY_TIERS["standard"]
    want_realesrgan = bool(tier["use_realesrgan"])
    from app.core.neural.super_resolution import SuperResolutionEngine
    engine = SuperResolutionEngine()
    loaded = engine.load(scale=int(tier["sr_scale"]),
                         use_realesrgan=want_realesrgan)
    out = engine.upscale(img)
    if out is None:
        return {"applied": False, "reason": "超分引擎返回空"}, None
    model = getattr(engine, "_model_name", "") or ("bicubic" if not loaded else "unknown")
    # degraded 的判据必须与 reason **一致**：
    #  ① 落到双三次（未加载任何模型）= 降级
    #  ② 要了 RealESRGAN 却没拿到（权重未自取/后端不支持）= 降级
    degraded = (model == "bicubic") or (want_realesrgan and model != "realesrgan")
    reason = ""
    if want_realesrgan and model != "realesrgan":
        reason = f"RealESRGAN 未就绪（权重未自取放置或后端不支持），已降级为 {model}；获取方式见下载中心"
    elif model == "bicubic":
        reason = "无可用超分模型，已降级为双三次插值（非 AI 放大）"
    return {"applied": True, "engine": model, "degraded": degraded,
            "scale": int(tier["sr_scale"]), "reason": reason}, out


def _step_cutout(img, quality: str, params: Dict[str, Any]) -> Tuple[Dict[str, Any], Any]:
    import numpy as np
    from app.core.neural.background_replace import BackgroundReplaceEngine
    engine = BackgroundReplaceEngine()
    if not engine.load():
        return {"applied": False, "reason": "抠像模型不可用（MODNet/U2Net 未就绪）"}, None
    mask = engine.segment(img)
    if mask is None:
        return {"applied": False, "reason": "未分离出前景"}, None
    bg = params.get("bg_color")
    if isinstance(bg, (list, tuple)) and len(bg) == 3:
        out = engine.replace_background(img, mask, bg_color=tuple(int(c) for c in bg))
        return {"applied": True, "engine": "modnet", "mode": "solid-bg",
                "bg_color": list(bg)}, out
    out = np.dstack([_bgr(img), mask])          # 透明底：BGR + alpha
    return {"applied": True, "engine": "modnet", "mode": "alpha"}, out


def _step_style(img, quality: str, params: Dict[str, Any]) -> Tuple[Dict[str, Any], Any]:
    style = str(params.get("style") or "cyberpunk")
    strength = float(params.get("strength") or 0.8)
    from app.core.neural.style_transfer import StyleTransferEngine
    engine = StyleTransferEngine()
    loaded = engine.load()
    out = engine.transfer(_bgr(img), style=style,
                          strength=max(0.0, min(1.0, strength)))
    if out is None:
        return {"applied": False, "reason": "风格迁移返回空"}, None
    return {"applied": True, "engine": "onnx-style" if loaded else "cpu-fallback",
            "style": style, "degraded": not loaded,
            "reason": "" if loaded else "风格模型未就绪，走了 CPU 回退"}, out


def _step_heal(img, quality: str, params: Dict[str, Any]) -> Tuple[Dict[str, Any], Any]:
    """局部修图：**必须给遮罩**；没遮罩就如实跳过（绝不瞎猜区域）。"""
    mask_url = params.get("mask")
    if not mask_url:
        return {"applied": False,
                "reason": "缺少遮罩（params.mask），无法确定重绘区域"}, None
    mask = _decode(str(mask_url))
    if mask is None:
        return {"applied": False, "reason": "遮罩解码失败"}, None
    import cv2
    base = _bgr(img)
    if mask.ndim == 3:
        mask = cv2.cvtColor(mask, cv2.COLOR_BGR2GRAY)
    if mask.shape[:2] != base.shape[:2]:
        mask = cv2.resize(mask, (base.shape[1], base.shape[0]))
    from app.core.neural.inpainting import InpaintingEngine
    engine = InpaintingEngine()
    if not engine.load():
        return {"applied": False, "reason": "重绘模型不可用（LaMa 未就绪）"}, None
    out = engine.inpaint(base, mask)
    if out is None:
        return {"applied": False, "reason": "重绘返回空"}, None
    return {"applied": True, "engine": "lama"}, out


_STEP_FUNCS: Dict[str, Callable[..., Tuple[Dict[str, Any], Any]]] = {
    "face": _step_face,
    "cutout": _step_cutout,
    "sharpen": _step_sharpen,
    "style": _step_style,
    "heal": _step_heal,
}


# ────────────────────────── 主入口 ──────────────────────────


def apply_intents(
    image_data_url: str,
    intents: List[str],
    *,
    quality: str = "standard",
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """按**有序列表**依次应用意图。返回诚实报告。**绝不抛异常。**

    返回::

        {"ok", "image_data_url", "applied": [{intent,label,applied,engine,...}],
         "skipped": [{intent,label,reason}], "quality", "changed"}
    """
    p = dict(params or {})
    q = quality if quality in QUALITY_TIERS else "standard"
    wanted = [str(i).strip() for i in (intents or []) if str(i).strip()]
    if not wanted:
        return {"ok": False, "message": "未指定任何意图",
                "applied": [], "skipped": [], "quality": q, "changed": False}

    img = _decode(image_data_url)
    if img is None:
        return {"ok": False, "message": "图像解码失败（需要 data URL）",
                "applied": [], "skipped": [], "quality": q, "changed": False}

    applied: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    for name in wanted:
        spec = ENHANCE_INTENTS.get(name)
        if not spec:
            skipped.append({"intent": name, "label": name,
                            "reason": f"未知意图（可用：{', '.join(ENHANCE_INTENTS)}）"})
            continue
        fn = _STEP_FUNCS.get(name)
        if fn is None:
            skipped.append({"intent": name, "label": spec["label"], "reason": "未实现"})
            continue
        try:
            report, out = fn(img, q, p)
        except Exception as e:
            logger.debug("[canvas_enhance] 意图 %s 执行异常", name, exc_info=True)
            report, out = {"applied": False, "reason": f"{type(e).__name__}: {e}"}, None

        if report.get("applied") and out is not None:
            applied.append({"intent": name, "label": spec["label"], **report})
            img = out          # 列表式流水线：本步产物交给下一步
        else:
            skipped.append({"intent": name, "label": spec["label"],
                            "reason": str(report.get("reason") or "未生效")})

    out_url = _encode(img)
    return {
        "ok": out_url is not None,
        "image_data_url": out_url,
        "applied": applied,
        "skipped": skipped,
        "quality": q,
        "changed": bool(applied),
        "note": ("每一步都回报了实际使用的引擎；degraded=True 表示走了降级路径。"
                 if applied else "没有任何意图生效，原图返回。"),
    }


def stats() -> Dict[str, Any]:
    """诊断：意图目录 + 后端可用性（**不加载任何模型**）。"""
    backend = "none"
    try:
        from app.core.neural_engine import get_neural_engine
        backend = str(getattr(get_neural_engine(), "_backend", "none"))
    except Exception:  # stability-gate: allow-swallow（诊断用：探后端名只为展示，探不到就回落 "none"，且刻意不加载模型）
        pass
    return {
        "intents": list(ENHANCE_INTENTS),
        "quality_tiers": list(QUALITY_TIERS),
        "neural_backend": backend,
    }
