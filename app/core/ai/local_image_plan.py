# -*- coding: utf-8 -*-
"""本地生图「选模型 / 选质量档 / 适配尺寸」纯函数（2026-10-25 接线层）。

为什么单独成文件
================
hybrid_dispatch 此前把三件事写死了：
  · 模型恒 sd15-t2i（SDXL 永远用不上）；
  · 不传 preset（fast/high 两档在混合链里失效）；
  · i2i 参考图只认 data URL（/inbox_file/ 会静默退化成 t2i）。
本模块把那三条判断抽成**纯函数**，便于单测，也避免 hybrid_dispatch 继续膨胀。

口径
====
· 画布质量档是 draft / standard / fine / cinema（与引擎的 fast / high / final 不同名）；
· fast 对 SDXL 依赖 LCM-LoRA ⇒ 权重/peft 不可用时**降为 high**，绝不「说快却慢」；
· 尺寸按模型原生分辨率等比缩放并对齐 64（diffusers 的 VAE 下采样 8×，64 更安全）；
· 只有自研栈（diffusers）支持 preset 参数，主选栈（diffsynth）传了会 TypeError
  ⇒ 由调用方用 supports_preset() 判断，本模块只给建议值。
"""
from __future__ import annotations

from typing import Any, Iterable, Tuple

# 画布质量档 → 引擎质量档（引擎侧无此档位则 "" = 不干预）
QUALITY_TO_PRESET = {
    "draft": "fast",
    "standard": "high",
    "fine": "final",
    "cinema": "final",
}

# 偏「高质量」的档位：优先 SDXL
_HQ = {"fine", "cinema"}


def fit_size(width: int, height: int, native: int = 512,
             step: int = 64, minimum: int = 256) -> Tuple[int, int]:
    """把任意宽高等比收进模型原生分辨率，并对齐 step（默认 64）。

    width<=0 或 height<=0 ⇒ 直接用原生方形（引擎默认行为）。
    """
    w, h = int(width or 0), int(height or 0)
    n = int(native or 512)
    if w <= 0 or h <= 0:
        return n, n
    scale = min(1.0, n / float(max(w, h)))
    tw = max(minimum, int(round(w * scale / step)) * step)
    th = max(minimum, int(round(h * scale / step)) * step)
    # 收进原生上限（四舍五入可能越界一档）
    tw = min(tw, n)
    th = min(th, n)
    return tw, th


def pick_model(*, quality: str = "standard", width: int = 0, height: int = 0,
               downloaded: Iterable[str] = ()) -> str:
    """按质量档与目标尺寸选本地模型 id（只从**已下载**的里选；都没有则给 sd15）。

    · fine/cinema 或目标长边 ≥900 ⇒ 优先 sdxl；
    · 其余 ⇒ sd15（快、512² 原生，适合 draft/standard）；
    · sdxl 未下载 ⇒ 回落 sd15，由引擎在缺权重时如实报错（不假装）。
    """
    has = set(downloaded or ())
    want_hq = (str(quality or "").strip().lower() in _HQ) or max(int(width or 0), int(height or 0)) >= 900
    if want_hq and "sdxl-t2i" in has:
        return "sdxl-t2i"
    if "sd15-t2i" in has:
        return "sd15-t2i"
    return "sd15-t2i"


def supports_preset(backend: Any) -> bool:
    """该引擎的 generate() 是否接受 preset 参数（diffsynth 不接受）。"""
    try:
        import inspect

        return "preset" in inspect.signature(backend.generate).parameters
    except Exception:
        return False


def lcm_usable(backend: Any) -> bool:
    """该引擎当前 LCM-LoRA 是否可用（无 lcm_status 的引擎视为不可用）。"""
    try:
        st = backend.lcm_status()
        return bool(isinstance(st, dict) and st.get("usable"))
    except Exception:
        return False


def preset_for(*, backend: Any, model_id: str, quality: str = "",
               preset: str = "") -> str:
    """按引擎能力给出本次 preset（不支持 preset 的引擎恒 ""，调用方直接省掉该参数）。"""
    if not supports_preset(backend):
        return ""
    want = str(preset or "").strip().lower()
    if want in ("fast", "high", "final"):
        return want
    q = str(quality or "").strip().lower()
    if not q:
        return ""
    return resolve_preset(quality=q, model_id=model_id, lcm_usable=lcm_usable(backend))


def generate_kwargs(*, backend: Any, model_id: str, quality: str = "",
                    preset: str = "", **base: Any) -> dict:
    """组装 engine.generate 的关键字参数：只有非 None 的基础项 + 按能力追加 preset。"""
    kw = {k: v for k, v in base.items() if v is not None}
    p = preset_for(backend=backend, model_id=model_id, quality=quality, preset=preset)
    if p:
        kw["preset"] = p
    return kw


def resolve_preset(*, quality: str = "standard", model_id: str = "sd15-t2i",
                   lcm_usable: bool = False, supports_preset: bool = True) -> str:
    """画布质量档 → 引擎档位；不支持 preset 的引擎返回 ""。

    SDXL 的 fast 依赖 LCM-LoRA：不可用时降为 high（仍然少步，但不宣称快档）。
    """
    if not supports_preset:
        return ""
    preset = QUALITY_TO_PRESET.get(str(quality or "").strip().lower(), "")
    if not preset:
        return ""
    if preset == "fast" and str(model_id).startswith("sdxl") and not lcm_usable:
        return "high"
    return preset
