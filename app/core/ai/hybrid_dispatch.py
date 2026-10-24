# -*- coding: utf-8 -*-
"""混合算力分派（A-1）—— 按 compute_bias 档位把图像生成裁定到「本机 SD 引擎」或「云端渠道」。

来源：用户指令「让本地部署模型 + 云端 API 混合运算，为什么切换后没起作用」+「迭代执行层 SD 引擎」。

实测根因（2026-10-23，写进代码免得后人重查）：
  · 本机 SD 类执行引擎**健康、非降级**：resolve_execution_engine() → diffsynth(主选)，
    SD1.5/SDXL/SVD 权重均在 app/models/cache，且图像可纯 prompt 本地出图。
  · 但图像路径**根本不经过 decide_execution**（后者生产里只在视频 local/ 分支被消费一次），
    所以「把混合塞进 decide_execution」= 图像侧死代码。混合裁定必须落在图像真入口。

档位语义（与 compute_bias 一致，单一真源在那边）：
  local(≤24)  → 本机 SD 引擎；引擎不可用/出图失败 ⇒ 诚实降级云端（R9 可见）。
  engine(25-74) → 云端「动态混合」：沿用既有 provider 链 + 治理排序（质量/成本/λ），
                  全失败 ⇒ 回退本机（本地恒为兜底锚点，与既有降级链同纪律）。
  cloud(≥75)  → 纯云端，与改动前逐键一致（默认不改变任何既有行为）。

纪律：
  · **显式选择优先**：调用方已指定 local/ 前缀或非空 channel_id 时**不改道**，
    只记一条 reason —— 用户手选的机器/渠道是最高意图，档位偏好只作用于「未指定=自动」的请求。
  · 纯惰性 import，**绝不在模块级 import torch/diffusers/canvas_aigc**（避免环与重依赖）。
  · 任何异常不外抛：本地探测失败按云端走，云端失败按本地走，最后 ok=False 带 message。
  · 返回体与云端生图**同形**（image_data_url + image_url + seed…），前端零改动即可显示。
"""
from __future__ import annotations

import base64
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger("AI短剧编辑器.core.ai.hybrid_dispatch")

_MIME_BY_EXT = {".png": "image/png", ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg", ".webp": "image/webp"}


def _file_to_data_url(path: str) -> str:
    """本地图片 → data URL（与云端返回体同形用）。失败返回空串。"""
    try:
        ext = os.path.splitext(path)[1].lower()
        mime = _MIME_BY_EXT.get(ext, "image/png")
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        return f"data:{mime};base64,{b64}"
    except Exception:
        logger.debug("[hybrid_dispatch] 本地转 data URL 失败: %s", path, exc_info=True)
        return ""


def decide_compute_mode(*, channel_id: str = "",
                        capability: str = "image",
                        has_reference: bool = False) -> Dict[str, Any]:
    """裁定本次走本地/云端/混合 —— **委托 execution_planner.plan()（单一真源）**。

    历史：本函数曾自己实现过一版档位判断；2026-10-23 收敛到执行层专项决策器，
    避免「两处各算一次、迟早漂移」的项目老毛病。
    """
    from app.core.ai.execution_planner import plan as plan_execution

    p = plan_execution(capability=capability, has_reference=has_reference,
                       explicit_channel=channel_id)
    use_local = p.get("route") == "local" or (p.get("chain") or [""])[0] == "local"
    return {"mode": p.get("mode") or "engine",
            "route": p.get("route") or "cloud",
            "chain": list(p.get("chain") or ["cloud"]),
            "engines": list(p.get("engines") or []),
            "use_local": use_local,
            "explicit_channel": bool((channel_id or "").strip()),
            "model_hint": p.get("model_hint") or "",
            "reasons": list(p.get("reasons") or [])}


def _local_image(*, prompt: str, size: str, seed: Any, reference_image: str,
                 reasons: list, quality: str = "standard",
                 prefer_engine: str = "", model_id: str = "") -> Optional[Dict[str, Any]]:
    """走本机 SD 引擎出图。成功返回与云端同形的 dict；不可用/失败返回 None（调用方降级）。

    2026-10-25 接线（修三处写死）：
      · 模型不再恒 sd15——按质量档/尺寸选 sd15 或 sdxl；
      · 质量档透传为 preset（fast/high/final），仅对支持 preset 的引擎传；
      · i2i 参考图改走 resolve_image_path 三态（data URL / inbox URL / 本地路径），
        不再只认 data URL（否则 /inbox_file/ 会静默退化成 t2i）。
    """
    try:
        from app.core.ai import local_image_plan as LP
        from app.core.ai.execution_decider import resolve_local_image_engine

        sel = resolve_local_image_engine(prefer=prefer_engine)
        if not sel.get("ok"):
            reasons.append("本机引擎不可用：" + str(sel.get("message")
                           or (sel.get("reasons") or ["未知"])[-1]))
            return None
        backend = sel["backend"]
        # 参考图（i2i）：三态统一解析成文件路径（与视频首帧同一入口）。
        image_path = ""
        if reference_image:
            try:
                from app.core.local_video_infer import resolve_image_path

                image_path = resolve_image_path(
                    reference_image, dest_dir=os.path.join("短剧AI剪辑输出", "_image_input"),
                    name_hint="hybrid") or ""
            except Exception:
                logger.debug("[hybrid_dispatch] 参考图落地失败", exc_info=True)
            if not image_path:
                reasons.append("参考图无法解析（i2i 跳过，按 t2i 生成）")
        w = h = 0
        try:
            parts = (size or "").lower().split("x")
            if len(parts) == 2:
                w, h = int(parts[0]), int(parts[1])
        except (TypeError, ValueError):
            w = h = 0
        # 选模型 + 适配尺寸（纯函数层，可单测）：plan 指定优先（须已下载），否则按质量/尺寸选
        plan_model = str(model_id or "").strip()
        local_model, native = "sd15-t2i", 512
        try:
            from app.core.neural import diffusers_image as _dfe

            downloaded = [m["id"] for m in _dfe.available_models()
                          if _dfe.DiffusersImageEngine.is_downloaded(m["id"])]
            if plan_model and plan_model in downloaded:
                local_model = plan_model
                reasons.append("按执行层计划用模型 %s" % plan_model)
            else:
                if plan_model:
                    reasons.append("计划模型 %s 未下载 ⇒ 按质量/尺寸改选" % plan_model)
                local_model = LP.pick_model(quality=quality, width=w, height=h,
                                            downloaded=downloaded)
            native = int((_dfe.DIFFUSERS_IMAGE_MODELS.get(local_model) or {})
                         .get("native_size") or 512)
        except Exception:
            logger.debug("[hybrid_dispatch] 本地模型探测失败，按 sd15/512", exc_info=True)
        fw, fh = LP.fit_size(w, h, native)
        preset = LP.resolve_preset(
            quality=quality, model_id=local_model,
            lcm_usable=LP.lcm_usable(backend),
            supports_preset=LP.supports_preset(backend))
        gen_kw: Dict[str, Any] = {"prompt": prompt, "image_path": image_path,
                                  "width": fw, "height": fh,
                                  "seed": int(seed) if isinstance(seed, int) else 0}
        if preset:
            gen_kw["preset"] = preset
        res = backend.generate(local_model, **gen_kw)
        if not res.get("ok"):
            reasons.append("本机出图失败：" + str(res.get("message")))
            return None
        reasons.append("本机 SD 出图（engine=%s · model=%s · preset=%s · %dx%d）"
                       % (sel.get("engine"), local_model, preset or "默认", fw, fh))
        data_url = res.get("image_data_url") or _file_to_data_url(
            res.get("image_path") or "")
        return {"ok": True, "image_data_url": data_url,
                "image_url": res.get("image_url", ""),
                "image_path": res.get("image_path", ""),
                "source": "local", "engine": sel.get("engine"),
                "model": "local/" + local_model, "local_model": local_model,
                "preset": preset, "size": "%dx%d" % (fw, fh),
                "channel_id": "local",
                "seed": res.get("seed", seed), "seed_sent": True}
    except Exception as e:
        logger.debug("[hybrid_dispatch] 本机路径异常", exc_info=True)
        reasons.append(f"本机路径异常：{type(e).__name__}: {e}")
        return None


def generate_image_hybrid(*, prompt: str, model: str = "", size: str = "",
                          channel_id: str = "", reference_image: str = "",
                          strength: float = 0.65, quality: str = "standard",
                          seed: Any = None, aspect: str = "") -> Dict[str, Any]:
    """图像生成统一入口（混合算力落点）。返回体与云端生图同形，前端零改动。

    执行语义 = **严格按执行层计划里的 `chain` 顺序尝试**：
      chain=["local","cloud"] ⇒ 先本机，失败再云端；
      chain=["cloud","local"] ⇒ 先云端，失败再本机。
    这样「怎么调度」由 execution_planner 一处决定，执行器不再自己拍。
    """
    dec = decide_compute_mode(channel_id=channel_id, capability="image",
                              has_reference=bool(reference_image))
    reasons = list(dec["reasons"])
    chain = dec["chain"] or ["cloud"]
    failures: list = []       # 逐路失败原因（不覆盖前一条，最终一并交代）

    for step in chain:
        if step == "local":
            local_step = next((e for e in (dec.get("engines") or [])
                               if e.get("kind") == "local"), {})
            loc = _local_image(prompt=prompt, size=size, seed=seed,
                               reference_image=reference_image, reasons=reasons,
                               quality=quality,
                               prefer_engine=str(local_step.get("engine") or ""),
                               model_id=str(local_step.get("model") or ""))
            if loc is not None:
                loc["compute_mode"] = dec["mode"]
                loc["compute_route"] = dec["route"]
                loc["reasons"] = reasons
                return loc
            failures.append("本地：" + (reasons[-1] if reasons else "不可用"))
            continue

        # step == "cloud"：走既有云端函数（逐键不变，保证既有行为）
        from app.core.canvas_aigc import generate_image_openai_compatible

        cloud = generate_image_openai_compatible(
            prompt=prompt, model=model, size=size, channel_id=channel_id,
            reference_image=reference_image, strength=strength, quality=quality,
            seed=seed, aspect=aspect)
        cloud = (dict(cloud) if isinstance(cloud, dict)
                 else {"ok": False, "message": str(cloud)})
        prev = cloud.get("reasons")
        cloud["reasons"] = (list(prev) if isinstance(prev, list) else []) + reasons
        cloud["compute_mode"] = dec["mode"]
        cloud["compute_route"] = dec["route"]
        if cloud.get("ok"):
            return cloud
        failures.append("云端：" + str(cloud.get("message") or "失败"))

    # 整条链都失败：逐路如实交代（不隐藏任何一路的原因）
    return {"ok": False,
            "message": "；".join(failures) or "所有执行路径均失败",
            "compute_mode": dec["mode"], "compute_route": dec["route"],
            "tried": list(chain), "reasons": reasons}
