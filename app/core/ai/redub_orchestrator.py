# -*- coding: utf-8 -*-
"""一键换词重配（Redub Orchestrator）—— 串联 T1+T2+T3 的编排器（2026-10-09，刀 T4 骨架）。

目标态（用户故事）
==================
导演台改一句台词 → 自动识别原角色 → 克隆其音色按新台词重配 → 对口型到已拍片段 →
出片并建议入轨。让"改文案"直接回流到"已拍素材"，而不是只能重新生成。

本模块做**编排**（不重复造 T1/T2/T3 的能力）
========================================
· T1 `speaker_diarize`：说话人分离（回答"有几个人在说话"，**不回答是谁**）
· T2 `voice_clone`：角色↔音色绑定 + 克隆 + 情感解耦
· T3 `video_lipsync`：真人视频对口型（三级降级）
本模块把它们串成一条**重配计划**（`plan_redub()` 纯函数），并逐级诚实降级。

诚实边界（本模块的红线）
========================
· **说话人分离只回答"有几个人说话"，不回答"是谁"**。所以：
  目标角色未显式指定、且无法从角色↔音色绑定推断时，plan 必须 `ok=False`
  并说明"不知道给谁配"，**绝不瞎猜一个角色名**。
· 各环节引擎未装 ⇒ 逐步诚实降级，最终产物必须携带**诚实标记**
  （`is_ai_redub` / 是否真用了角色音色 / 是否真对口型），不能把降级结果冒充成品。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class RedubRequest:
    """一次换词重配请求。"""
    video_path: str                 # 已拍片段
    new_line: str                   # 新台词
    target_character: Optional[str] = None   # 目标角色名（None = 需自动识别/绑定推断）
    emotion: str = "neutral"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RedubStep:
    """重配链的一步。"""
    name: str           # 识别角色 / 匹配音色 / 克隆重配 / 对口型 / 出片
    capability: str     # diarize / voice / lipsync / render
    path: str           # real / fallback / skip
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RedubPlan:
    """重配计划（纯函数产物）。"""
    ok: bool
    steps: List[RedubStep] = field(default_factory=list)
    final_marks: List[str] = field(default_factory=list)   # 最终产物要打的诚实标记
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "steps": [s.to_dict() for s in self.steps],
                "final_marks": self.final_marks, "reason": self.reason}


# ── 编排纯函数 ─────────────────────────────────────────────────────

def plan_redub(request: RedubRequest, *,
               diarize_available: bool,
               voice_available: bool,
               lipsync_available: bool,
               character_voice_known: bool = False,
               ) -> RedubPlan:
    """**纯函数**：把「输入 + 各环节可用性」映射成一条重配计划（逐级诚实降级）。

    决策矩阵：
      · 目标角色：显式给了 → 用；没给但能靠角色↔音色绑定推断 → 用推断；
        两者皆无 → **plan 失败**（不知道给谁配，不瞎猜）。
      · 说话人分离：可用 → 做（辅助确认"谁在说话"）；不可用 → 跳过（不影响主链，只要目标角色已定）。
      · 音色克隆：可用 → 克隆重配（真角色音色）；不可用 → 降级用固定声线（标"非角色音色"）。
      · 对口型：可用 → 真对口型；不可用 → dub_only（标 is_ai_redub）。
    """
    steps: List[RedubStep] = []
    marks: List[str] = []

    # ① 目标角色判定（红线：不知道给谁配就失败，不瞎猜）
    if request.target_character:
        who = request.target_character
        steps.append(RedubStep("识别角色", "diarize", "real" if diarize_available else "skip",
                               f"目标角色已指定：{who}"))
    elif character_voice_known:
        who = "<由角色↔音色绑定推断>"
        steps.append(RedubStep("识别角色", "diarize", "real" if diarize_available else "skip",
                               "目标角色由角色↔音色绑定推断"))
    else:
        return RedubPlan(ok=False, steps=[RedubStep("识别角色", "diarize", "skip",
                                                    "未指定目标角色，且无角色↔音色绑定可推断")],
                         final_marks=[], reason="不知道给谁配：请指定 target_character 或先绑定角色音色")

    # ② 匹配音色
    if voice_available:
        steps.append(RedubStep("匹配音色", "voice", "real", "命中角色音色库"))
    else:
        steps.append(RedubStep("匹配音色", "voice", "fallback", "用固定声线（非角色音色）"))
        marks.append("voice=fallback")

    # ③ 克隆重配
    if voice_available:
        steps.append(RedubStep("克隆重配", "voice", "real", "按角色音色 + 新台词 + 情感重配"))
    else:
        steps.append(RedubStep("克隆重配", "voice", "fallback", "固定声线重配"))

    # ④ 对口型
    if lipsync_available:
        steps.append(RedubStep("对口型", "lipsync", "real", "真人视频对口型"))
    else:
        steps.append(RedubStep("对口型", "lipsync", "fallback", "只换音不換口型"))
        marks.append("lipsync=fallback")

    # ⑤ 出片
    steps.append(RedubStep("出片", "render", "real", "RenderManager 出片 + 建议入轨"))
    marks.append("is_ai_redub=True")   # 重配产物恒打 AI 重配标记

    return RedubPlan(ok=True, steps=steps, final_marks=marks, reason="")


# ── 执行入口（诚实失败，调用真实 T1/T2/T3 骨架）──────────────────────

def execute_redub(request: RedubRequest,
                  character_voice: Optional[str] = None) -> Dict[str, Any]:
    """主入口：按 plan 执行（当前各环节是**骨架**，引擎未装时诚实降级/失败）。

    返回 `{ok, plan, artifacts, marks, reason}`；artifacts 里各产物在引擎未接时为空。
    """
    from app.core.ai import speaker_diarize, voice_clone, video_lipsync

    diar_ok = speaker_diarize.funasr_available()
    voice_ok = voice_clone.clone_available()
    lip_ok = video_lipsync.video_lipsync_available()
    known = bool(character_voice)

    plan = plan_redub(request, diarize_available=diar_ok,
                      voice_available=voice_ok, lipsync_available=lip_ok,
                      character_voice_known=known)
    if not plan.ok:
        return {"ok": False, "plan": plan.to_dict(), "artifacts": {},
                "marks": [], "reason": plan.reason}

    artifacts: Dict[str, Any] = {}

    # 音色（诚实失败/降级）
    if character_voice:
        artifacts["voice_id"] = character_voice
    elif voice_ok:
        r = voice_clone.clone_voice("", request.target_character or "")
        artifacts["voice_id"] = r.get("asset", None)  # 引擎未接时为 None，诚实
    else:
        artifacts["voice_id"] = None                   # 降级：固定声线

    # 对口型（诚实失败/降级）
    lip_req = video_lipsync.LipSyncVideoRequest(
        video_path=request.video_path, audio_path="",
        is_real_person=True)
    lip_res = video_lipsync.sync_video(lip_req)
    artifacts["lipsync"] = lip_res.to_dict()

    return {"ok": True, "plan": plan.to_dict(), "artifacts": artifacts,
            "marks": plan.final_marks,
            "reason": "骨架已串联（引擎未接，产物为空是预期，详见各 step.note）"}


# ── V4.41.7 升级：预检（执行前给用户完整能力预览）────────────────────

def preflight_check(request: RedubRequest,
                    character_voice: Optional[str] = None) -> Dict[str, Any]:
    """执行前的**能力预检**：报告每个环节「能用 / 要降级 / 缺什么」。

    为什么需要：用户点「一键换词重配」前最关心的是"这次跑出来会是完整效果还是降级版"。
    旧版只有执行后才知道（甚至要跑一半才失败）。预检把降级信息**前置**，
    用户可以决定"先去装引擎"还是"接受降级版先出草稿"。

    诚实边界：预检只报告**当前已知**状态（依赖是否装、显存是否够），
    **不预测**执行一定成功（运行时仍可能出错，那由执行阶段诚实报告）。
    """
    from app.core.ai import speaker_diarize, video_lipsync, voice_clone

    # 依赖检测
    diar_dep = speaker_diarize.funasr_available()
    voice_dep = voice_clone.clone_available()
    lip_dep = video_lipsync.video_lipsync_available()

    # 显存预检（借 model_registry 的探测；无 CUDA 时如实报）
    vram_note = ""
    try:
        from app.core.ai.model_registry import _free_vram_mb
        free = _free_vram_mb()
        vram_note = f"当前空闲显存约 {free}MB"
    except Exception:
        vram_note = "无法探测显存（无 CUDA/驱动）"

    who = request.target_character or (character_voice and "<音色绑定推断>") or None
    missing = []
    if not who:
        missing.append("目标角色未指定且无音色绑定")
    if not voice_dep:
        missing.append("音色克隆引擎未装（将降级为固定声线）")
    if not lip_dep:
        missing.append("对口型引擎未装（将降级为只换音不換口型）")

    return {
        "ready": len(missing) == 0,
        "character_resolved": who is not None,
        "diarize_available": diar_dep,
        "voice_available": voice_dep,
        "lipsync_available": lip_dep,
        "vram": vram_note,
        "missing": missing,
        "expected_quality": ("完整效果（角色音色+对口型）" if voice_dep and lip_dep
                             else "降级版（" + "；".join(missing or ["全部就绪"]) + "）"),
    }
