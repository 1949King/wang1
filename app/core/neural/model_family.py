"""模型族注册表（ModelFamily）—— 统一推理引擎的**协议层**（设计稿 M1）。

为什么需要（用户指令：「支持市面已有视频/大模型/多模态的引擎」+「把三条线合并成一条」）：
  现状是四条平行线（实测，file:line 见设计稿 §1）：
    ① neural/diffsynth_image   图像主选   ② neural/diffusers_image  图像备选
    ③ local_video_infer        手写 7 族（仅 svd 真机跑过）
    ④ neural/video_gen         SVD·diffsynth 通道（TUNED 实测调优表）
  SVD 在 ③④ 各有一份实现 = 双轨漂移病根；③ 的 6 个未验证族在 UI 上"看起来可选"。

  本模块把「模型族 → 后端」的映射从散落代码收拢成**一张声明表 + 一个 resolve()**：
  新模型接入 = 登记一条 ModelFamilySpec（+ 可选适配器），不再新写 `_infer_xxx`。

与其他注册表的分工（刻意不合并，字段正交）：
  · backend_registry（neural/）：后端**进程内健康**（find_spec 级），是本表 resolve 的输入之一；
  · engine_registry（core/）：**观测视图**（登记+健康+用量），本表落成它的 family=inference 条目；
  · agent_capability_catalog：Agent 面能力清单，与本表无交集。
  调度真源在本表 + execution_planner；观测真源在 engine_registry。

纪律（对齐项目既有法条）：
  · 顶层零重依赖：只 import stdlib；探测一律函数内惰性 import + try（画布 HTTP 线程可安全调）；
  · 诚实三态 verification：verified（本机真机跑过）| unverified（有适配、未验证）| blocked（环境不满足）；
    unverified 不得进默认可选列表（对齐 engine_registry 的 library-only 法条）；
  · resolve 查无 ⇒ ok=False + reasons 留痕，绝不静默降级成别的行为；
  · SVD 只有一个家：④ video_gen（TUNED 唯一真源）；③ 的 _infer_svd 在 M3 前是双轨，
    本表先声明正确归属，M3 把代码归一。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("AI短剧编辑器.core.neural.model_family")

# ── 能力常量（与 canvas_aigc.CAPABILITY_* 字符串一致；不 import 它，防拉 Qt/画布依赖）──
CAP_IMAGE = "image"
CAP_VIDEO = "video"
CAP_AUDIO = "audio"
CAP_MUSIC = "music"
CAP_LLM = "llm"

# ── 验证三态 ──
VERIFIED = "verified"  # 本机真机跑过（有产物/有实测数据背书）
UNVERIFIED = "unverified"  # 有适配代码，但权重不在盘或从未跑通 ⇒ 不得进默认可选
BLOCKED = "blocked"  # 环境不满足（硬件/依赖），如实标，不装可用


# ── 后端 id（与 backend_registry / engine_telemetry 的 engine 名对齐）──────────
BACKEND_DIFFSYNTH_IMAGE = "diffsynth_image"
BACKEND_DIFFUSERS_IMAGE = "diffusers_image"
BACKEND_VIDEO_GEN = "video_gen"  # diffsynth 系 SVD 通道（TUNED 真源）
BACKEND_LOCAL_VIDEO = "local_video_infer"  # diffusers 系手写族（M3 起 svd 委托 ④）


@dataclass(frozen=True)
class ModelFamilySpec:
    """一个模型族的登记项。只写声明，不 import 执行代码。"""

    family: str  # "sd15" | "sdxl" | "svd" | "wan" | ...
    capability: str  # CAP_* 之一
    backends: Tuple[str, ...]  # 按优先级；resolve 逐个验健康，首个可用为主选
    weight_probe: str = ""  # 本模块内探测函数名；"" = 无需探测（如 llm 云端族）
    min_vram_gb: float = 0.0  # 整卡准入（口径同 diffusers_image.promotion_fits）
    native_fps: int = 0  # 视频族必填：编码帧率语义（V4.46.11/12 的 _native_fps 纪律上收）
    tuned_ref: str = ""  # 参数唯一真源指针，如 "video_gen.TUNED:svd-xt-i2v"
    verification: str = UNVERIFIED
    telemetry_arch: str = ""  # engine_telemetry 的 model_arch 维度；"" = 用 family
    note: str = ""


# ── 权重探测（全部惰性 + try，画布 HTTP 线程可安全调）────────────────────────
def _probe_image(model_id: str) -> Callable[[], bool]:
    def f() -> bool:
        try:
            from app.core.neural.diffsynth_image import IMAGE_MODELS, is_downloaded

            return model_id in IMAGE_MODELS and bool(is_downloaded(model_id))
        except Exception:
            logger.debug("[model_family] 图像权重探测失败（%s）", model_id, exc_info=True)
            return False

    return f


def _probe_svd() -> bool:
    try:
        from app.core.neural.video_gen import is_downloaded

        return bool(is_downloaded("svd-xt-i2v"))
    except Exception:
        logger.debug("[model_family] SVD 权重探测失败", exc_info=True)
        return False


def _probe_local_video(kind: str) -> Callable[[], bool]:
    """③ 系各族：扫本地权重目录（local_video_infer 顶层纯 stdlib，可安全惰性 import）。"""

    def f() -> bool:
        try:
            from app.core.local_video_infer import _guess_model_kind, _scan_local_models

            return any(m.kind == kind for m in _scan_local_models()) or bool(
                _guess_model_kind(kind)
            )
        except Exception:
            logger.debug("[model_family] 本地视频权重探测失败（%s）", kind, exc_info=True)
            return False

    return f


_PROBES: Dict[str, Callable[[], bool]] = {
    "sd15": _probe_image("sd15-t2i"),
    "sdxl": _probe_image("sdxl-t2i"),
    "svd": _probe_svd,
    "wan": _probe_local_video("wan"),
    "cogvideox": _probe_local_video("cogvideox"),
    "hunyuan": _probe_local_video("hunyuan"),
    "ltx": _probe_local_video("ltx"),
    "mochi": _probe_local_video("mochi"),
    "minimax_h3": _probe_local_video("minimax_h3"),
}


# ── 注册表（单一真源）──────────────────────────────────────────────────────
FAMILIES: Tuple[ModelFamilySpec, ...] = (
    # 图像：双后端（diffsynth 主选 / diffusers 备选），与 resolve_local_image_engine 现状一致
    ModelFamilySpec(
        family="sd15",
        capability=CAP_IMAGE,
        backends=(BACKEND_DIFFSYNTH_IMAGE, BACKEND_DIFFUSERS_IMAGE),
        weight_probe="sd15",
        min_vram_gb=2.5,
        verification=VERIFIED,
        telemetry_arch="sd15",
        note="实测整卡 4.34GB，8GB 可热提升",
    ),
    ModelFamilySpec(
        family="sdxl",
        capability=CAP_IMAGE,
        backends=(BACKEND_DIFFSYNTH_IMAGE, BACKEND_DIFFUSERS_IMAGE),
        weight_probe="sdxl",
        min_vram_gb=5.0,
        verification=VERIFIED,
        telemetry_arch="sdxl",
        note="fp16 权重占满 8GB ⇒ 永远 offload（实测）",
    ),
    # 视频 · SVD：唯一归属 ④ video_gen（diffsynth 通道，TUNED 实测表 + 守卫）
    ModelFamilySpec(
        family="svd",
        capability=CAP_VIDEO,
        backends=(BACKEND_VIDEO_GEN, BACKEND_LOCAL_VIDEO),
        weight_probe="svd",
        min_vram_gb=5.0,
        native_fps=7,
        tuned_ref="video_gen.TUNED:svd-xt-i2v",
        verification=VERIFIED,
        telemetry_arch="svd",
        note="i2v：必须有参考图/首帧；③ 的 _infer_svd 是历史双轨，M3 委托到 ④ 后退役",
    ),
    # 视频 · ③ 系六族：有适配代码，但权重不在盘 / pipeline 类存在性未验证 ⇒ unverified。
    # native_fps 取自各族 num_frames 系数（V4.46.11 实测登记），杜绝编码帧率再写死。
    ModelFamilySpec(
        family="wan",
        capability=CAP_VIDEO,
        backends=(BACKEND_LOCAL_VIDEO,),
        weight_probe="wan",
        min_vram_gb=12.0,
        native_fps=16,
        verification=UNVERIFIED,
        note="WanVideoPipeline 在 diffusers 0.40 存在性未验证；RAM 墙见设计稿 M5",
    ),
    ModelFamilySpec(
        family="cogvideox",
        capability=CAP_VIDEO,
        backends=(BACKEND_LOCAL_VIDEO,),
        weight_probe="cogvideox",
        min_vram_gb=8.0,
        native_fps=16,
        verification=UNVERIFIED,
        note="2B 档理论可试 8GB；从未真机跑过",
    ),
    ModelFamilySpec(
        family="hunyuan",
        capability=CAP_VIDEO,
        backends=(BACKEND_LOCAL_VIDEO,),
        weight_probe="hunyuan",
        min_vram_gb=16.0,
        native_fps=16,
        verification=UNVERIFIED,
    ),
    ModelFamilySpec(
        family="ltx",
        capability=CAP_VIDEO,
        backends=(BACKEND_LOCAL_VIDEO,),
        weight_probe="ltx",
        min_vram_gb=12.0,
        native_fps=25,
        verification=UNVERIFIED,
    ),
    ModelFamilySpec(
        family="mochi",
        capability=CAP_VIDEO,
        backends=(BACKEND_LOCAL_VIDEO,),
        weight_probe="mochi",
        min_vram_gb=24.0,
        native_fps=16,
        verification=UNVERIFIED,
    ),
    ModelFamilySpec(
        family="minimax_h3",
        capability=CAP_VIDEO,
        backends=(BACKEND_LOCAL_VIDEO,),
        weight_probe="minimax_h3",
        min_vram_gb=24.0,
        native_fps=24,
        verification=UNVERIFIED,
    ),
)

_BY_FAMILY: Dict[str, ModelFamilySpec] = {s.family: s for s in FAMILIES}

# 模块 id（本表 backends）→ 引擎 id（backend_registry / execution_planner / 遥测命名空间）。
# 关键事实（统一引擎 M2 核实）：④ video_gen 与 ③ local_video_infer 两条 SVD 实现
# import 的都是 diffusers（video_gen.py:419 `from diffusers import DiffusionPipeline`）
# ⇒ 它们的引擎归属是 "diffusers"，不是 "diffsynth"。
BACKEND_TO_ENGINE: Dict[str, str] = {
    BACKEND_DIFFSYNTH_IMAGE: "diffsynth",
    BACKEND_DIFFUSERS_IMAGE: "diffusers",
    BACKEND_VIDEO_GEN: "diffusers",
    BACKEND_LOCAL_VIDEO: "diffusers",
}


def preferred_engines(family: str) -> List[str]:
    """族 → 引擎 id 优先级序（去重保序，backend_registry 命名空间）。

    供 execution_planner 取「无实测证据时的保守默认」，替代写死的 diffsynth→diffusers。
    查无族 ⇒ []（调用方自行兜底，绝不武断判死——svd 漏登记误杀视频路径的教训）。
    """
    s = spec_of(family)
    if s is None:
        return []
    out: List[str] = []
    for b in s.backends:
        e = BACKEND_TO_ENGINE.get(b)
        if e and e not in out:
            out.append(e)
    return out


def spec_of(family: str) -> Optional[ModelFamilySpec]:
    return _BY_FAMILY.get((family or "").strip().lower())


def families(
    capability: Optional[str] = None, *, include_unverified: bool = True
) -> List[ModelFamilySpec]:
    out = [
        s
        for s in FAMILIES
        if (not capability or s.capability == capability)
        and (include_unverified or s.verification == VERIFIED)
    ]
    return out


def weights_present(family: str) -> bool:
    s = spec_of(family)
    if s is None or not s.weight_probe:
        return False
    f = _PROBES.get(s.weight_probe)
    return bool(f()) if f else False


def _backend_available(bid: str) -> Tuple[bool, str]:
    """后端健康 = 模块可解析 + 关键依赖 find_spec（不 import 重库）。"""
    import importlib.util as u

    mods = {
        BACKEND_DIFFSYNTH_IMAGE: ("app.core.neural.diffsynth_image", ("torch",)),
        BACKEND_DIFFUSERS_IMAGE: ("app.core.neural.diffusers_image", ("torch", "diffusers")),
        BACKEND_VIDEO_GEN: ("app.core.neural.video_gen", ("torch",)),
        BACKEND_LOCAL_VIDEO: ("app.core.local_video_infer", ("torch", "diffusers")),
    }
    entry = mods.get(bid)
    if entry is None:
        return False, "未知后端 id（注册表拼写错误？）"
    mod, deps = entry
    try:
        if u.find_spec(mod.split(".")[0]) is None:
            return False, "包缺失"
        if u.find_spec(mod) is None:
            return False, "模块缺失"
    except Exception:
        return False, "模块解析异常"
    missing = [d for d in deps if u.find_spec(d) is None]
    if missing:
        return False, "依赖缺失：" + ",".join(missing)
    return True, "可用"


def resolve(family: str, *, capability_hint: str = "") -> Dict[str, Any]:
    """族 → 可执行后端的裁定（纯声明 ∩ 后端健康 ∩ 权重在盘；遥测留给 execution_planner 叠加）。

    返回 {ok, family, backend, fallbacks, verification, native_fps, reasons[]}。
    查无 / 全不可用 ⇒ ok=False + 原因（诚实失败，绝不静默换族或降级行为）。
    """
    reasons: List[str] = []
    s = spec_of(family)
    if s is None:
        return {
            "ok": False,
            "family": family,
            "backend": "",
            "fallbacks": [],
            "verification": "",
            "native_fps": 0,
            "reasons": [
                "族 %r 未登记 ⇒ 新模型请先在 model_family 登记（这正是合一的意义）" % family
            ],
        }
    if capability_hint and s.capability != capability_hint:
        reasons.append("能力不匹配：族=%s 请求=%s" % (s.capability, capability_hint))
        return {
            "ok": False,
            "family": s.family,
            "backend": "",
            "fallbacks": [],
            "verification": s.verification,
            "native_fps": s.native_fps,
            "reasons": reasons,
        }

    if not weights_present(s.family):
        reasons.append("权重不在盘（探测=%s）" % (s.weight_probe or "无"))
        return {
            "ok": False,
            "family": s.family,
            "backend": "",
            "fallbacks": [],
            "verification": s.verification,
            "native_fps": s.native_fps,
            "reasons": reasons,
        }

    avail: List[str] = []
    for i, bid in enumerate(s.backends):
        ok, why = _backend_available(bid)
        if not ok:
            reasons.append("后端 %s 不可用：%s" % (bid, why))
            continue
        if i == 0:
            avail.insert(0, bid)
        else:
            avail.append(bid)
    if not avail:
        return {
            "ok": False,
            "family": s.family,
            "backend": "",
            "fallbacks": [],
            "verification": s.verification,
            "native_fps": s.native_fps,
            "reasons": reasons + ["无可用后端"],
        }

    if s.verification == UNVERIFIED:
        reasons.append(
            "⚠ 该族从未在本机真机验证（unverified）：可显式选用，但不得进默认可选、失败按事实上报"
        )
    reasons.append(
        "族 %s：权重在盘 · 后端健康（首选 %s）· 验证态 %s" % (s.family, avail[0], s.verification)
    )
    return {
        "ok": True,
        "family": s.family,
        "backend": avail[0],
        "fallbacks": avail[1:],
        "verification": s.verification,
        "native_fps": s.native_fps,
        "tuned_ref": s.tuned_ref,
        "reasons": reasons,
    }


def status() -> Dict[str, Any]:
    """全量视图（供 /host/execution-status 扩展与排障）。"""
    rows = []
    for s in FAMILIES:
        ok_b = {b: _backend_available(b)[0] for b in s.backends}
        rows.append(
            {
                "family": s.family,
                "capability": s.capability,
                "verification": s.verification,
                "weights": weights_present(s.family),
                "backends": ok_b,
                "native_fps": s.native_fps,
                "note": s.note,
            }
        )
    return {
        "total": len(rows),
        "verified": sum(1 for r in rows if r["verification"] == VERIFIED),
        "unverified": sum(1 for r in rows if r["verification"] == UNVERIFIED),
        "families": rows,
    }
