# -*- coding: utf-8 -*-
"""本地 SD1.5-inpainting 语义重绘（Semantic Inpaint，T3 2026-11-20）。

原理（对标上游 GH_CropRestore，纯 numpy 简化，不搬 GPL 代码）
==========================================================
单图 + 蒙版 → 蒙版 bbox 外扩 1.3 裁切 → 512 重绘 → 羽化回贴。
**核心不变量：蒙版外像素逐字节保持原图**（alpha = blur(mask) * (mask>0)，
蒙版外 alpha 恒 0 ⇒ 回贴结果与原图完全一致）。

许可（T0 条件放行，2026-11-20 用户已确认）
========================================
SD1.5-inpainting 为 CreativeML Open RAIL-M：再分发须附许可副本（随包
license/third_party/），Attachment A 使用限制传导至衍生与全部用户，
输出合规责任由使用者承担。权重**绝不自动下载、不随包**，只给自取 guidance。

remove 模式：绿幕覆盖（#00ff00 opacity 0.4）+ 提示词「移除图像中的绿色区域」，
无专用移除 LoRA ⇒ 诚实标注效果可能折扣。
"""
from __future__ import annotations

import base64
import logging
import os
from typing import Any, Dict, Optional, Tuple

import numpy as np

logger = logging.getLogger("AI短剧编辑器.core.neural.semantic_inpaint")

SD_INPAINT_DIRNAME = "sd15-inpainting"

#: 权重缺失 / 降级时给用户的自取指引 + OpenRAIL-M 使用限制摘要（单一真源）。
SD_INPAINT_GUIDANCE = (
    "未检测到 SD1.5-inpainting 语义重绘权重目录（sd15-inpainting，含 model_index.json）。本软件绝不自动下载模型：\n"
    "【资源地址（CreativeML Open RAIL-M，T0 条件放行已获用户确认）】\n"
    "  · https://huggingface.co/stable-diffusion-v1-5/stable-diffusion-inpainting\n"
    "【部署步骤】\n"
    "  1. 自取整个 diffusers 权重目录（含 model_index.json / unet / vae / text_encoder 等）。\n"
    "  2. 放到以下任一位置：\n"
    "     ① 环境变量 SHIGUANG_SD_INPAINT_DIR 指向的目录；\n"
    "     ② 仓库 thirdparty/models/sd15-inpainting/。\n"
    "  3. 重启画布桥后重试「语义重绘」。缺失时诚实降级 LaMa/Telea（degraded=True）。\n"
    "【OpenRAIL-M 使用限制摘要（Attachment A，传导至衍生与全部用户）】\n"
    "  禁止用于：违法或伤害未成年人；生成可识别个人信息以害人；诽谤/骚扰/歧视；\n"
    "  不利法律权益的全自动决策；虚假信息害人等。输出合规责任由使用者承担。\n"
    "  完整许可副本见随包 license/third_party/SD15-INPAINTING-OpenRAIL-M.txt。"
)


def find_sd_inpaint_dir() -> str:
    """返回**实际存在**的 SD1.5-inpainting diffusers 目录（认 model_index.json）；缺返空串。

    只找本地目录，绝不触发下载：
      ① 环境变量 SHIGUANG_SD_INPAINT_DIR 指向的目录
      ② <仓库>/thirdparty/models/sd15-inpainting/
    """
    def _ok(d: str) -> bool:
        return bool(d) and os.path.isfile(os.path.join(d, "model_index.json"))

    env = os.environ.get("SHIGUANG_SD_INPAINT_DIR", "").strip()
    if _ok(env):
        return env
    repo = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    d = os.path.join(repo, "thirdparty", "models", SD_INPAINT_DIRNAME)
    if _ok(d):
        return d
    return ""


# ─────────────────────── 纯函数：bbox / 羽化回贴（蒙版外不变量）───────────────────────

def mask_bbox(mask: np.ndarray, expand: float = 1.3) -> Tuple[int, int, int, int]:
    """蒙版非零区 bbox 外扩 expand 倍（围绕中心），并 clamp 到图像边界。"""
    h, w = mask.shape[:2]
    m = mask > 0
    if not m.any():
        return (0, 0, w, h)
    ys, xs = np.nonzero(m)
    x_min, x_max = int(xs.min()), int(xs.max())
    y_min, y_max = int(ys.min()), int(ys.max())
    cx = (x_min + x_max) / 2.0
    cy = (y_min + y_max) / 2.0
    half_w = (x_max - x_min + 1) / 2.0 * expand
    half_h = (y_max - y_min + 1) / 2.0 * expand
    x0 = max(0, int(round(cx - half_w)))
    y0 = max(0, int(round(cy - half_h)))
    x1 = min(w, int(round(cx + half_w)))
    y1 = min(h, int(round(cy + half_h)))
    return (x0, y0, x1, y1)


def _blur_mask(mf: np.ndarray) -> np.ndarray:
    """羽化用高斯模糊；cv2 不可用时退化硬边（不变量仍成立）。"""
    try:
        import cv2
        return cv2.GaussianBlur(mf, (15, 15), 0)
    except Exception:
        logger.debug("[semantic_inpaint] cv2 不可用，羽化退化为硬边", exc_info=True)
        return mf


def feathered_paste(
    original: np.ndarray,
    repaint: np.ndarray,
    mask: np.ndarray,
    bbox: Tuple[int, int, int, int],
) -> np.ndarray:
    """把重绘裁切羽化回贴原图。**蒙版外像素逐字节不变**（alpha=blur(mask)*(mask>0)）。

    Args:
        original: (H,W,3) BGR uint8 原图
        repaint:  (bh,bw,3) BGR uint8 重绘裁切（bbox 尺寸，不一致则缩放）
        mask:     (H,W) uint8 全图蒙版（255=重绘区）
        bbox:     (x0,y0,x1,y1)
    """
    x0, y0, x1, y1 = bbox
    result = original.copy()
    crop_mask = mask[y0:y1, x0:x1]
    if crop_mask.size == 0:
        return result
    mf = (crop_mask > 0).astype(np.float32)
    alpha = _blur_mask(mf) * mf                 # 蒙版外恒 0 ⇒ 逐字节保留原图
    alpha3 = alpha[..., np.newaxis]
    region = original[y0:y1, x0:x1].astype(np.float32)
    rep = repaint.astype(np.float32)
    if rep.shape[:2] != region.shape[:2]:
        try:
            import cv2
            rep = cv2.resize(rep, (region.shape[1], region.shape[0])).astype(np.float32)
        except Exception:
            logger.debug("[semantic_inpaint] 重绘裁切缩放失败，按原尺寸回贴", exc_info=True)
    blended = region * (1.0 - alpha3) + rep * alpha3
    result[y0:y1, x0:x1] = np.clip(blended, 0, 255).astype(np.uint8)
    return result


def _green_overlay(crop_img: np.ndarray, crop_mask: np.ndarray) -> np.ndarray:
    """remove 绿幕 trick：蒙版区覆盖 #00ff00（BGR 0,255,0）opacity 0.4。"""
    out = crop_img.astype(np.float32)
    green = np.array([0, 255, 0], dtype=np.float32)
    m = (crop_mask > 0)[..., np.newaxis].astype(np.float32) * 0.4
    out = out * (1.0 - m) + green * m
    return np.clip(out, 0, 255).astype(np.uint8)


# ─────────────────────── pipeline 加载 / 推理（可 mock，不依赖真权重）───────────────────────

def _load_pipeline(model_dir: str):
    """懒加载 diffusers StableDiffusionInpaintPipeline；失败返 None（诚实，不冒充）。"""
    try:
        import torch
        from diffusers import StableDiffusionInpaintPipeline
        use_cuda = torch.cuda.is_available()
        dtype = torch.float16 if use_cuda else torch.float32
        pipe = StableDiffusionInpaintPipeline.from_pretrained(
            model_dir, torch_dtype=dtype, safety_checker=None)
        pipe = pipe.to("cuda" if use_cuda else "cpu")
        pipe.set_progress_bar_config(disable=True)
        return pipe
    except Exception as exc:
        logger.warning("[semantic_inpaint] SD1.5-inpainting 加载失败: %s", exc)
        return None


def _run_pipeline(pipe, crop_img_bgr: np.ndarray, crop_mask: np.ndarray,
                  prompt: str, steps: int) -> Optional[np.ndarray]:
    """裁切 BGR → 512 RGB PIL 重绘 → 回裁切尺寸 BGR。失败返 None。"""
    try:
        import cv2
        from PIL import Image
        h, w = crop_img_bgr.shape[:2]
        rgb = cv2.cvtColor(crop_img_bgr, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(rgb).resize((512, 512))
        m = Image.fromarray(crop_mask).resize((512, 512))
        out = pipe(prompt=prompt, image=img, mask_image=m, num_inference_steps=steps)
        pil = out.images[0].resize((w, h))
        arr = np.asarray(pil.convert("RGB"))
        return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    except Exception as exc:
        logger.warning("[semantic_inpaint] 推理失败: %s", exc)
        return None


def semantic_inpaint(
    image: np.ndarray,
    mask: np.ndarray,
    prompt: str,
    mode: str = "inpaint",
    *,
    pipeline=None,
    steps: int = 25,
) -> Dict[str, Any]:
    """本地 SD1.5 语义重绘（numpy API）。缺权重 ⇒ ok:false + guidance；蒙版外逐字节不变。

    pipeline 可注入（测试 mock）；为 None 时自取目录并加载。
    """
    if image is None or mask is None:
        return {"ok": False, "message": "缺少原图或蒙版"}
    mode = (mode or "inpaint").strip().lower()
    h, w = image.shape[:2]
    if mask.shape[:2] != (h, w):
        try:
            import cv2
            mask = cv2.resize(mask, (w, h))
        except Exception:
            return {"ok": False, "message": "蒙版尺寸与原图不一致且无法缩放"}

    bbox = mask_bbox(mask, 1.3)
    x0, y0, x1, y1 = bbox
    crop_img = image[y0:y1, x0:x1]
    crop_mask = mask[y0:y1, x0:x1]
    note = ""
    if mode == "remove":
        crop_img = _green_overlay(crop_img, crop_mask)
        prompt = "移除图像中的绿色区域" + (("；" + prompt) if prompt else "")
        note = "remove 走绿幕覆盖 + 提示词（无专用移除 LoRA，效果可能折扣）"

    if pipeline is None:
        d = find_sd_inpaint_dir()
        if not d:
            return {"ok": False, "message": "未检测到 SD1.5-inpainting 权重目录",
                    "guidance": SD_INPAINT_GUIDANCE}
        pipeline = _load_pipeline(d)
        if pipeline is None:
            return {"ok": False, "message": "SD1.5-inpainting 加载失败",
                    "guidance": SD_INPAINT_GUIDANCE}

    repaint = _run_pipeline(pipeline, crop_img, crop_mask, prompt, steps)
    if repaint is None:
        return {"ok": False, "message": "SD1.5-inpainting 推理失败"}
    result = feathered_paste(image, repaint, mask, bbox)
    return {"ok": True, "image": result, "mode": mode,
            "engine": "sd15-inpaint", "degraded": False, "note": note}


# ─────────────────────── data URL 编解码 + 本地优先调度（供路由薄调用）───────────────────────

def _decode_dataurl_to_bgr(data_url: str) -> Optional[np.ndarray]:
    """data URL → BGR uint8；非法返 None。"""
    try:
        import cv2
        s = str(data_url or "")
        b64 = s.split(",", 1)[1] if "," in s else s
        arr = np.frombuffer(base64.b64decode(b64), dtype=np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)
    except Exception:
        logger.debug("[semantic_inpaint] 原图 data URL 解码失败", exc_info=True)
        return None


def _decode_dataurl_to_mask(data_url: str) -> Optional[np.ndarray]:
    """data URL → 灰度蒙版 uint8；非法返 None。"""
    try:
        import cv2
        s = str(data_url or "")
        b64 = s.split(",", 1)[1] if "," in s else s
        arr = np.frombuffer(base64.b64decode(b64), dtype=np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
    except Exception:
        logger.debug("[semantic_inpaint] 蒙版 data URL 解码失败", exc_info=True)
        return None


def _encode_bgr(image: np.ndarray) -> str:
    """BGR uint8 → PNG data URL。"""
    import cv2
    ok, buf = cv2.imencode(".png", image)
    if not ok:
        return ""
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode("ascii")


def _local_fallback(img: np.ndarray, mask: np.ndarray, mode: str) -> Dict[str, Any]:
    """本地兜底：LaMa（本地优先）→ Telea，诚实标 degraded。"""
    try:
        from app.core.neural.inpainting import InpaintingEngine
        eng = InpaintingEngine()
        if eng.load():
            out = eng.inpaint(img, mask)
            if out is not None:
                return {"ok": True, "image_data_url": _encode_bgr(out), "engine": "lama",
                        "degraded": True, "mode": mode,
                        "message": "语义权重缺失，降级本地 LaMa 局部修补（无提示词语义）"}
    except Exception:
        logger.debug("[semantic_inpaint] LaMa 降级失败", exc_info=True)
    try:
        import cv2
        out = cv2.inpaint(img, mask, 3, cv2.INPAINT_TELEA)
        return {"ok": True, "image_data_url": _encode_bgr(out), "engine": "telea",
                "degraded": True, "mode": mode,
                "message": "降级传统 Telea 修补（无 AI 语义）"}
    except Exception as exc:
        logger.warning("[semantic_inpaint] Telea 兜底失败: %s", exc)
        return {"ok": False, "message": "本地局部修补不可用"}


def semantic_edit_via_host(
    image_dataurl: str,
    mask_dataurl: str,
    prompt: str,
    mode: str = "inpaint",
    *,
    channel_id: str = "",
    megapixels: float = 1.0,
    size: str = "1024x1024",
) -> Dict[str, Any]:
    """本地优先 + 可选网关的局部编辑调度（供 /host/gateway-edit 路由薄调用）。

    顺序：① 本地 SD1.5 语义（权重在盘）→ ② 可选网关（默认关）→
    ③ 本地 LaMa/Telea 兜底（degraded）→ ④ 全失败诚实 guidance。
    outpaint 无本地路径，直接走网关。
    """
    mode = (mode or "inpaint").strip().lower()
    img = _decode_dataurl_to_bgr(image_dataurl) if mode in ("inpaint", "remove") else None
    mask = _decode_dataurl_to_mask(mask_dataurl) if mode in ("inpaint", "remove") else None

    # ① 本地 SD1.5 语义（权重在盘才走，纯本地优先）
    if img is not None and mask is not None and find_sd_inpaint_dir():
        res = semantic_inpaint(img, mask, prompt, mode)
        if res.get("ok"):
            return {"ok": True, "image_data_url": _encode_bgr(res["image"]),
                    "engine": res["engine"], "degraded": False, "mode": mode,
                    "note": res.get("note", ""), "message": "本地 SD1.5 语义重绘成功"}

    # ② 可选网关（默认关；未启用诚实返 guidance）
    from app.core.ai.gateway_edits import gateway_edit
    gres = gateway_edit(mode=mode, image=image_dataurl, mask=mask_dataurl, prompt=prompt,
                        channel_id=channel_id, megapixels=megapixels, size=size)
    if gres.get("ok"):
        return gres

    # ③ 本地 LaMa/Telea 兜底（仅 inpaint/remove）
    if img is not None and mask is not None:
        fb = _local_fallback(img, mask, mode)
        if fb.get("ok"):
            fb["guidance"] = gres.get("guidance") or SD_INPAINT_GUIDANCE
            return fb

    # ④ 全失败 ⇒ 诚实 guidance
    return {"ok": False, "message": gres.get("message") or "局部编辑不可用",
            "guidance": gres.get("guidance") or SD_INPAINT_GUIDANCE}
