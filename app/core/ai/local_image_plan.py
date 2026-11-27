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

import logging
from typing import Any, Iterable, Optional, Tuple

logger = logging.getLogger(__name__)

# 画布质量档 → 引擎质量档（引擎侧无此档位则 "" = 不干预）
QUALITY_TO_PRESET = {
    "draft": "fast",
    "standard": "high",
    "fine": "final",
    "cinema": "final",
}

# 画质档 → **长边上限**（2026-10-27 实测：SDXL 1024²=30.7s / 832²=16.4s / 768²=14.3s）
# 语义：这是「出图分辨率总闸」，画布每个生成节点/意图卡片都靠 qualityTier 走这一条。
QUALITY_MAX_SIDE_SDXL = {"draft": 768, "standard": 832, "fine": 1024, "cinema": 1024}
QUALITY_MAX_SIDE_SD15 = {"draft": 512, "standard": 640, "fine": 768, "cinema": 768}

# 偏「高质量」的档位：优先 SDXL
_HQ = {"fine", "cinema"}

# SDXL 的 fast 档（LCM-LoRA 8 步 cfg1）2026-10-27 本机实测是**负收益**：
#   draft(768², LCM) = 97.9s / 峰值 6.95GB  vs  standard(832², 12 步) = 13.6s
# 原因：LCM 让 cfg 降为 1 不省算力，但 LoRA 注入 + 峰值抬升触发显存换页。
# ⇒ 即便 lcm 可用，SDXL 也不走 fast（只对 SD1.5 保留，那里 8 步 1.5s 确实快）。
_SDXL_FAST_PROFITABLE = False


def fit_size(width: int, height: int, native: int = 512,
             step: int = 64, minimum: int = 256, max_side: int = 0) -> Tuple[int, int]:
    """把任意宽高等比收进模型原生分辨率，并对齐 step（默认 64）。

    width<=0 或 height<=0 ⇒ 直接用原生方形（引擎默认行为）。
    max_side>0 时以它为上限（画质档给出的长边总闸），否则用 native。
    """
    w, h = int(width or 0), int(height or 0)
    n = int(native or 512)
    if w <= 0 or h <= 0:
        return n, n
    limit = int(max_side) if int(max_side or 0) > 0 else n
    scale = min(1.0, limit / float(max(w, h)))
    tw = max(minimum, int(round(w * scale / step)) * step)
    th = max(minimum, int(round(h * scale / step)) * step)
    # 收进原生上限（四舍五入可能越界一档）
    tw = min(tw, limit)
    th = min(th, limit)
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


def max_side_for(quality: str = "standard", model_id: str = "") -> int:
    """画质档 + 模型族 → 出图长边上限（单一真源，后端收口与前端预估共用口径）。"""
    q = str(quality or "").strip().lower() or "standard"
    table = QUALITY_MAX_SIDE_SDXL if str(model_id).startswith("sdxl") else QUALITY_MAX_SIDE_SD15
    return int(table.get(q, table["standard"]))


def target_size(width: int = 0, height: int = 0, quality: str = "standard",
                model_id: str = "", native: int = 0) -> Tuple[int, int]:
    """一站式计算「本次实际出图尺寸」：档位上限 + 等比 + 对齐 64。

    画布节点/意图卡片只传 qualityTier 与画幅，具体像素由这里定（前端预估同口径）。
    """
    n = int(native or 0) or (1024 if str(model_id).startswith("sdxl") else 512)
    limit = min(max_side_for(quality, model_id), n)
    return fit_size(width, height, n, max_side=limit)


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
                    preset: str = "", person_card: Optional[dict] = None,
                    genre: str = "", **base: Any) -> dict:
    """组装 engine.generate 的关键字参数：非 None 的基础项 + 按能力追加 preset。

    2026-11-01 在这里统一做三件事（本地生图**唯一漏斗**，路由/能力处理器都自动受益）：

    ① **中文 ⇒ 英文**（CLIP 只认英文；失败保留原文，不阻塞生成）；
    ② **人种锚定**（SD 底座先验偏西方，不锚就全是美式脸；用户写欧美则尊重）；
    ③ **分档负向词库**（古装压现代服饰、短剧压欧美脸/塑料感…）。

    `person_card`（C 项）：人物卡字段按固定顺序拼英文提示词，优先于自由文本。
    `genre`：题材分档（负向词库用）；缺省按提示词猜。
    """
    kw = {k: v for k, v in base.items() if v is not None}
    _raw = str(kw.get("prompt") or "").strip()
    _neg_extra: list = []
    try:
        from app.core.ai import prompt_bridge as _PB

        # ① 中文 ⇒ 英文
        _used, _info = _PB.prepare_for_local(_raw)
        if _info.get("translated") and _used:
            kw["prompt"] = _used
        _en_after_tr = str(kw.get("prompt") or "")

        # ③ C 项：人物卡优先（结构化真源），自由文本仅作尾部补充
        from app.core.ai import prompt_template as _PT

        if _PT.has_card(person_card):
            kw["prompt"] = _PT.render_prompt(person_card, extra=_en_after_tr if _raw else "")
            _en_after_tr = str(kw.get("prompt") or "")

        # ② 人种锚定（英文提示词同样要锚，不只翻译路径）
        _biased, _neg_face = _PB.apply_face_bias(_en_after_tr, _raw)
        if _biased:
            kw["prompt"] = _biased
        if _neg_face:
            _neg_extra.append(_neg_face)
    except Exception:
        logger.debug("[local_image_plan] 提示词预处理跳过", exc_info=True)

    # ③ 分档负向词库（用户自带 negative 永远保留并排在最前）
    try:
        from app.core.ai import negative_presets as _NP

        # 分档看中文原值：卡里写「汉服」但自由文本为空时，也要能判成 ancient
        _zh_hint = _raw
        if isinstance(person_card, dict):
            _zh_hint = (_zh_hint + " " + " ".join(str(v) for v in person_card.values())).strip()
        kw["negative_prompt"] = _NP.build_negatives(
            prompt=_zh_hint, genre=genre,
            user_negative=str(kw.get("negative_prompt") or ""),
            extra=_neg_extra,
        )
    except Exception:
        logger.debug("[local_image_plan] 负向词库跳过", exc_info=True)

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
    if preset == "fast" and str(model_id).startswith("sdxl"):
        # SDXL：LCM 可用与否都不走 fast（实测负收益，见 _SDXL_FAST_PROFITABLE）
        if not lcm_usable or not _SDXL_FAST_PROFITABLE:
            return "high"
    return preset
