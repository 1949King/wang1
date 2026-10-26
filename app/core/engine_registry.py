# -*- coding: utf-8 -*-
"""自研引擎注册表（W1 · 2026-10-24）—— 9 族引擎的**单一事实源**。

为什么要有它（诊断结论，写进来免得后人重查）：
  · 全库有 ~55 个引擎模块，但「在册（有人 import）」不等于「可用（用户到得了）」。
    实测：`smart_editing_engine` 零生产调用；`super_resolution` / `face_restore` /
    `style_transfer` / `background_replace` 有后端调用、**画布没有入口**；
    画布右键「智能剪辑」发的 `smart_edit` 动作**没有 handler**（死按钮）。
  · 这些状态此前没有任何一张表能回答「谁在用、谁空着、谁只是库内能力」。

四档角色（`role`）—— 验收口径：
  · `primary`     有产品/Agent 入口且被真实调用（默认可选）
  · `fallback`    只在链里兜底（遥测证据够才可能升主选）
  · `library-only`有能力、无入口 —— **不得在 UI 宣称可用**
  · `retired`     零调用，待合并/删除（保留 30 天观察后清）
  · `disabled`    环境不满足（硬件/依赖），如实禁用

纪律：
  · **纯 stdlib + find_spec 探测**：不 import torch/diffusers（画布 HTTP 线程可安全调）；
  · 用量只从遥测读，**未埋点的引擎不伪造 0 调用**（返回 None）；
  · 本表只做「登记 + 健康 + 用量视图」，不做调度（调度在 execution_planner）。
"""
from __future__ import annotations

import glob
import importlib.util
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── 角色 / 健康枚举（字符串常量，避免 Enum 序列化麻烦）──
ROLE_PRIMARY = "primary"
ROLE_FALLBACK = "fallback"
ROLE_LIBRARY = "library-only"
ROLE_RETIRED = "retired"
ROLE_DISABLED = "disabled"
ROLES = (ROLE_PRIMARY, ROLE_FALLBACK, ROLE_LIBRARY, ROLE_RETIRED, ROLE_DISABLED)

ROLE_MEANINGS = {
    ROLE_PRIMARY: "有入口且在用",
    ROLE_FALLBACK: "链内兜底",
    ROLE_LIBRARY: "库内能力（无入口，不算可用）",
    ROLE_RETIRED: "零调用，待清理",
    ROLE_DISABLED: "环境不满足，如实禁用",
}

FAMILIES: Dict[str, str] = {
    "inference": "本地推理（生图/视频）",
    "code_video": "代码×扩散渲染",
    "editing": "剪辑执行",
    "effect": "AI 特效/理解",
    "audio": "配音/语音/音乐",
    "smart_edit": "剪辑智能",
    "draw": "抽卡闭环",
    "agent": "Agent 编排/AI 调用",
    "canvas": "画布侧引擎",
}


@dataclass(frozen=True)
class EngineSpec:
    """一个引擎模块的登记项。"""

    id: str
    family: str
    capability: str
    module: str                       # 仓库相对路径；支持 * 通配（.pyd 带平台后缀）
    role: str
    deps: Tuple[str, ...] = ()
    device: str = ""
    telemetry: str = ""               # 遥测里的 engine 名；空 = 未埋点
    note: str = ""


def _e(**kw: Any) -> EngineSpec:
    return EngineSpec(**kw)


ENGINES: Tuple[EngineSpec, ...] = (
    # ── 族 1 · 本地推理 ──────────────────────────────────────────────
    _e(id="infra.backend_registry", family="inference", capability="infra",
       module="app/core/neural/backend_registry.py", role=ROLE_PRIMARY,
       note="4 后端声明式登记"),
    _e(id="infra.device_profile", family="inference", capability="infra",
       module="app/core/neural/device_profile.py", role=ROLE_PRIMARY,
       note="CUDA/ROCm/MPS/CPU 四路探测"),
    _e(id="infra.engine_telemetry", family="inference", capability="infra",
       module="app/core/ai/engine_telemetry.py", role=ROLE_PRIMARY,
       note="n≥3 才选栈的证据账本"),
    _e(id="image.diffusers", family="inference", capability="image",
       module="app/core/neural/diffusers_image.py", role=ROLE_PRIMARY,
       deps=("torch", "diffusers"), device="cuda", telemetry="diffusers"),
    _e(id="image.diffsynth", family="inference", capability="image",
       module="app/core/neural/diffsynth_image.py", role=ROLE_PRIMARY,
       deps=("torch",), device="cuda", telemetry="diffsynth"),
    _e(id="video.svd", family="inference", capability="video",
       module="app/core/neural/video_gen.py", role=ROLE_PRIMARY,
       deps=("torch", "diffusers"), device="cuda", telemetry="svd"),
    _e(id="infra.memory_policy", family="inference", capability="infra",
       module="app/core/neural/memory_policy.py", role=ROLE_FALLBACK,
       note="显存策略（装不下不硬上）"),
    _e(id="infra.layer_offload", family="inference", capability="infra",
       module="app/core/neural/layer_offload.py", role=ROLE_FALLBACK),
    _e(id="infra.diffsynth_compat", family="inference", capability="infra",
       module="app/core/neural/diffsynth_compat.py", role=ROLE_FALLBACK),
    _e(id="effect.style_transfer", family="inference", capability="image_effect",
       module="app/core/neural/style_transfer.py", role=ROLE_LIBRARY,
       note="后端有调用、画布无入口（W2 接 /host/effect）"),
    _e(id="effect.super_resolution", family="inference", capability="image_effect",
       module="app/core/neural/super_resolution.py", role=ROLE_LIBRARY,
       note="同上"),
    _e(id="effect.face_restore", family="inference", capability="image_effect",
       module="app/core/neural/face_restore.py", role=ROLE_LIBRARY,
       note="同上"),
    _e(id="effect.background_replace", family="inference", capability="image_effect",
       module="app/core/neural/background_replace.py", role=ROLE_LIBRARY,
       note="同上"),
    _e(id="effect.inpainting", family="inference", capability="image_effect",
       module="app/core/neural/inpainting.py", role=ROLE_PRIMARY,
       note="/host/inpaint + /host/repair-image 已接"),
    # ── 调度层 / 资源层（2026-10-27 补齐：此前整层 0 登记）──────────────────
    # 纪律：这些是**自研编排层**，不做推理；推理内核全是三方（diffusers/diffsynth/comfy/云）。
    _e(id="infra.execution_decider", family="inference", capability="infra",
       module="app/core/ai/execution_decider.py", role=ROLE_PRIMARY,
       note="选栈决策（diffusers vs diffsynth），不做推理"),
    _e(id="infra.hybrid_dispatch", family="inference", capability="infra",
       module="app/core/ai/hybrid_dispatch.py", role=ROLE_PRIMARY,
       note="本地/云端混合派发（含 quality 总闸）"),
    _e(id="infra.inference_cache", family="inference", capability="infra",
       module="app/core/neural/inference_cache.py", role=ROLE_PRIMARY,
       note="推理结果缓存（1099 行）"),
    _e(id="infra.vram_budget", family="inference", capability="infra",
       module="app/core/neural/vram_budget.py", role=ROLE_PRIMARY,
       note="显存预算与准入判定"),
    _e(id="infra.quant_policy", family="inference", capability="infra",
       module="app/core/neural/quant_policy.py", role=ROLE_FALLBACK,
       note="fp8/量化策略；本机 torch 2.6 无 kernel ⇒ 实际不生效（已实测）"),
    _e(id="infra.accel_status", family="inference", capability="infra",
       module="app/core/neural/accel_status.py", role=ROLE_PRIMARY,
       note="加速能力诚实三态（实测优先，负收益也登记）"),
    _e(id="infra.model_family", family="inference", capability="infra",
       module="app/core/neural/model_family.py", role=ROLE_PRIMARY,
       note="9 族模型归族与验证态"),
    _e(id="video.local_video_infer", family="inference", capability="video",
       module="app/core/local_video_infer.py", role=ROLE_PRIMARY,
       deps=("torch", "diffusers"), device="cuda", telemetry="wan",
       note="Wan/CogVideoX 等本地推理壳（内核 diffusers）；含管线+embeds 常驻缓存"),
    _e(id="image.comfy_provider", family="inference", capability="image",
       module="app/core/ai/comfy_provider.py", role=ROLE_LIBRARY,
       note="ComfyUI 进程生命周期与结果保存；**未接画布生成**（引擎本体是 GPL 三方）"),
    _e(id="canvas.canvas_aigc", family="agent", capability="orchestrate",
       module="app/core/canvas_aigc.py", role=ROLE_PRIMARY,
       note="画布 AIGC 调度（127KB，三方内核的编排入口）"),

    # ── 族 2 · 代码×扩散渲染 ────────────────────────────────────────
    _e(id="render.spec", family="code_video", capability="render",
       module="app/core/code_video/spec.py", role=ROLE_PRIMARY),
    _e(id="render.host", family="code_video", capability="render",
       module="app/core/code_video/render_host.py", role=ROLE_PRIMARY),
    _e(id="render.page_builder", family="code_video", capability="render",
       module="app/core/code_video/page_builder.py", role=ROLE_PRIMARY),
    _e(id="render.worker", family="code_video", capability="render",
       module="app/core/code_video/render_worker.py", role=ROLE_PRIMARY),
    _e(id="render.security", family="code_video", capability="render",
       module="app/core/code_video/security.py", role=ROLE_PRIMARY),
    _e(id="render.critic", family="code_video", capability="render",
       module="app/core/code_video/video_critic.py", role=ROLE_PRIMARY),
    _e(id="render.audio_graph", family="code_video", capability="render",
       module="app/core/code_video/audio_graph.py", role=ROLE_PRIMARY),
    _e(id="render.progress", family="code_video", capability="render",
       module="app/core/code_video/progress.py", role=ROLE_FALLBACK),

    # ── 族 3 · 剪辑执行 ────────────────────────────────────────────
    _e(id="edit.mlt_cpp", family="editing", capability="edit",
       module="app/core/video_processing/mlt_engine_cpp.py", role=ROLE_PRIMARY,
       deps=("ctypes",), note="C++ 内核（DLL 分发）"),
    _e(id="edit.mlt_py", family="editing", capability="edit",
       module="app/core/video_processing/mlt_engine.py", role=ROLE_FALLBACK),
    _e(id="edit.pyav", family="editing", capability="edit",
       module="app/core/video_processing/pyav_engine.py", role=ROLE_FALLBACK,
       deps=("av",)),
    _e(id="edit.cpp_engine", family="editing", capability="edit",
       module="app/core/video_processing/cpp_engine", role=ROLE_PRIMARY,
       note="NVENC/QSV/AMF 硬编"),
    _e(id="edit.cython_effects", family="editing", capability="edit",
       module="app/core/video_processing/cython_effects*.pyd", role=ROLE_PRIMARY),
    _e(id="edit.cython_compositor", family="editing", capability="edit",
       module="app/core/video_processing/cython_compositor*.pyd", role=ROLE_PRIMARY),
    _e(id="edit.cython_cache", family="editing", capability="edit",
       module="app/core/video_processing/cython_cache*.pyd", role=ROLE_FALLBACK),

    # ── 族 4 · AI 特效/理解 ────────────────────────────────────────
    _e(id="effect.neural_engine", family="effect", capability="effect",
       module="app/core/neural_engine.py", role=ROLE_PRIMARY,
       deps=("cv2",), note="ONNX/PyTorch/OpenCV DNN/CPU 四后端"),
    _e(id="understand.drama", family="effect", capability="understand",
       module="app/modules/lego/drama_understanding_engine.py", role=ROLE_PRIMARY),
    _e(id="effect.lip_sync", family="effect", capability="video_effect",
       module="app/core/lip_sync.py", role=ROLE_FALLBACK,
       note="参数动画层；数字人口型尚未接线"),
    _e(id="effect.video_lipsync", family="effect", capability="video_effect",
       module="app/core/ai/video_lipsync.py", role=ROLE_LIBRARY,
       note="真人级；未接 DigitalHumanNode"),
    _e(id="score.five_dimension", family="effect", capability="score",
       module="app/core/five_dimension_scorer.py", role=ROLE_PRIMARY),
    _e(id="understand.perception", family="effect", capability="understand",
       module="app/core/media_perception.py", role=ROLE_FALLBACK,
       note="face/ocr 如实标 not_wired"),

    # ── 族 5 · 配音/语音/音乐 ──────────────────────────────────────
    _e(id="tts.voice_generator", family="audio", capability="tts",
       module="app/core/voice_generator.py", role=ROLE_PRIMARY),
    _e(id="tts.voice_clone", family="audio", capability="tts",
       module="app/core/ai/voice_clone.py", role=ROLE_LIBRARY,
       note="在册未接 UI"),
    _e(id="dub.pipeline", family="audio", capability="dub",
       module="app/core/ai/dub_pipeline.py", role=ROLE_PRIMARY),
    _e(id="dub.verify", family="audio", capability="dub",
       module="app/core/ai/dub_verify.py", role=ROLE_PRIMARY,
       note="听写回环/字幕=音频"),
    _e(id="dub.redub", family="audio", capability="dub",
       module="app/core/ai/redub_orchestrator.py", role=ROLE_LIBRARY),
    _e(id="asr.whisper", family="audio", capability="asr",
       module="app/core/ai/whisper_asr.py", role=ROLE_PRIMARY),
    _e(id="music.yue", family="audio", capability="music",
       module="app/core/ai/yue_music.py", role=ROLE_DISABLED,
       note="本机跑不动 ⇒ 诚实失败，不假音频"),

    # ── 族 6 · 剪辑智能 ────────────────────────────────────────────
    _e(id="edit.professional", family="smart_edit", capability="edit",
       module="app/modules/lego/professional_video_engine.py", role=ROLE_PRIMARY),
    _e(id="smart_edit.engine", family="smart_edit", capability="smart_edit",
       module="app/modules/lego/smart_editing_engine.py", role=ROLE_RETIRED,
       note="零生产调用；画布 smart_edit 按钮无 handler；待并入/删除"),
    _e(id="smart_edit.viral", family="smart_edit", capability="smart_edit",
       module="app/modules/lego/viral_optimization_engine.py", role=ROLE_FALLBACK,
       note="agent_workflow / editor_ai_tools 在用"),
    _e(id="smart_edit.skill", family="smart_edit", capability="smart_edit",
       module="app/modules/lego/skill_engine.py", role=ROLE_PRIMARY,
       note="main_qt6 单例 + external_loader 注册"),

    # ── 族 7 · 抽卡闭环 ────────────────────────────────────────────
    _e(id="draw.orchestrator", family="draw", capability="draw",
       module="app/core/ai/draw_orchestrator.py", role=ROLE_PRIMARY),
    _e(id="draw.critic", family="draw", capability="draw",
       module="app/core/ai/gen_critic.py", role=ROLE_PRIMARY),
    _e(id="draw.book", family="draw", capability="draw",
       module="app/core/ai/draw_book.py", role=ROLE_PRIMARY),
    _e(id="draw.score_book", family="draw", capability="draw",
       module="app/core/ai/score_book.py", role=ROLE_PRIMARY),

    # ── 族 8 · Agent 编排/AI 调用 ──────────────────────────────────
    _e(id="agent.host", family="agent", capability="agent",
       module="app/core/project_agent_host.py", role=ROLE_PRIMARY),
    _e(id="agent.brain", family="agent", capability="agent",
       module="app/core/agent_brain.py", role=ROLE_PRIMARY),
    _e(id="agent.ai_engine", family="agent", capability="agent",
       module="app/core/ai_engine.py", role=ROLE_PRIMARY),
    _e(id="agent.engine_api", family="agent", capability="agent",
       module="app/core/ai/engine_api.py", role=ROLE_FALLBACK),

    # ── 族 9 · 画布侧 ──────────────────────────────────────────────
    _e(id="canvas.magnetic", family="canvas", capability="canvas",
       module="vendor/packages/libtv/src/magnetic/MagneticEngine.ts", role=ROLE_PRIMARY),
    _e(id="canvas.stack", family="canvas", capability="canvas",
       module="vendor/packages/libtv/src", role=ROLE_PRIMARY,
       note="React19+xyflow12+three0.185+zustand5（技术栈形态，无单文件）"),
)


# ── 健康探测（不 import 重依赖）────────────────────────────────────
def _module_exists(module: str) -> bool:
    p = os.path.join(ROOT, module)
    if "*" in p:
        return bool(glob.glob(p))
    return os.path.exists(p)


def _dep_available(dep: str) -> bool:
    try:
        return importlib.util.find_spec(dep) is not None
    except Exception:
        return False


def health(engine: EngineSpec) -> Tuple[str, List[str]]:
    """返回 (health, 缺失依赖)。health ∈ ready|degraded|disabled|missing。"""
    if engine.role == ROLE_DISABLED:
        return "disabled", []
    if not _module_exists(engine.module):
        return "missing", []
    missing = [d for d in engine.deps if not _dep_available(d)]
    return ("degraded", missing) if missing else ("ready", [])


# ── 用量（只从遥测读；未埋点返回 None）────────────────────────────
def _telemetry_records() -> Dict[str, Dict[str, Any]]:
    try:
        from app.core.ai import engine_telemetry

        return dict((engine_telemetry.snapshot() or {}).get("records") or {})
    except Exception:
        return {}


def _usage_by_engine(records: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """把 `engine|arch|device` 键聚合成 engine → {calls, ok, last_ts}。"""
    out: Dict[str, Dict[str, Any]] = {}
    for key, rec in records.items():
        name = str(key).split("|")[0]
        if not name:
            continue
        agg = out.setdefault(name, {"calls": 0, "ok": 0, "last_ts": 0.0})
        agg["calls"] += int((rec or {}).get("n") or 0)
        agg["ok"] += int((rec or {}).get("ok") or 0)
        agg["last_ts"] = max(agg["last_ts"], float((rec or {}).get("last_ts") or 0.0))
    return out


def engine_view(engine: EngineSpec, usage: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    h, missing = health(engine)
    u = usage.get(engine.telemetry) if engine.telemetry else None
    return {
        "id": engine.id,
        "family": engine.family,
        "capability": engine.capability,
        "module": engine.module,
        "role": engine.role,
        "role_meaning": ROLE_MEANINGS.get(engine.role, engine.role),
        "health": h,
        "missing_deps": missing,
        "device": engine.device,
        "note": engine.note,
        "telemetry": engine.telemetry,
        "usage": u,  # None = 未埋点（不伪造 0 调用）
    }


def status() -> Dict[str, Any]:
    """全量视图：给 UI / 报告用。"""
    usage = _usage_by_engine(_telemetry_records())
    views = [engine_view(e, usage) for e in ENGINES]
    by_role: Dict[str, int] = dict.fromkeys(ROLES, 0)
    by_health: Dict[str, int] = {}
    by_family: Dict[str, int] = dict.fromkeys(FAMILIES, 0)
    for v in views:
        by_role[v["role"]] = by_role.get(v["role"], 0) + 1
        by_health[v["health"]] = by_health.get(v["health"], 0) + 1
        by_family[v["family"]] = by_family.get(v["family"], 0) + 1
    return {
        "total": len(views),
        "families": FAMILIES,
        "by_family": by_family,
        "by_role": by_role,
        "by_health": by_health,
        "role_meanings": ROLE_MEANINGS,
        "engines": views,
    }


def idle_engines() -> List[Dict[str, Any]]:
    """已埋点但 0 调用的引擎（真·空着）。未埋点的不算。"""
    usage = _usage_by_engine(_telemetry_records())
    out = []
    for e in ENGINES:
        u = usage.get(e.telemetry) if e.telemetry else None
        if u is not None and int(u.get("calls") or 0) == 0:
            out.append(engine_view(e, usage))
    return out
