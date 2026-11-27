# -*- coding: utf-8 -*-
"""复核与回流（适配 B）—— 让精剪闭环，而不是"剪完就结束"。

为什么必须有这一层
------------------
用户原方案终点是「Agent 剪完」。但：
  · 没有验收标准就判不了对错，VLM 第二次出现只能描述画面、无法复核；
  · 成功的结果不沉淀，下次仍从零判断，永远不积累（``memory_store`` 目前
    「只记账、不改行为」的根因就在这里）。

本模块把 EditIntent 当作**可证伪的判据**：逐条检查 EDL 的 evidence 能否在语义表
里找到出处、是否违反硬约束、时长是否落在容差内。通过/不通过都写成结构化报告，
再把结果回流到 ``memory_store``（执行轨迹 / 用户偏好）与人审标签。

铁律
----
· 复核不通过**不自动重剪、不自动回滚**——只给差异原因，由人/上层决定重跑；
  撤销走既有 ``apply()`` 的 compound 条目，不另造第二套事务。
· 只在**人确认后**才写用户偏好，避免把一次模型的错误判断学成长期规则。
· 记忆写入失败不阻断主链路，如实记 warning。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

try:
    from app.core.editing.intent import EditIntent
    from app.core.editing.semantic_table import SemanticTable
except ImportError:  # 打包/副库路径兜底
    from core.editing.intent import EditIntent  # type: ignore
    from core.editing.semantic_table import SemanticTable  # type: ignore

logger = logging.getLogger(__name__)

__all__ = [
    "Check",
    "VerificationReport",
    "verify_proposal",
    "write_back",
    "submit_human_verdict",
]


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


@dataclass
class VerificationReport:
    passed: bool
    checks: List[Check] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    intent_fingerprint: str = ""
    plan_id: str = ""

    @property
    def failures(self) -> List[Check]:
        return [c for c in self.checks if not c.passed]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "checks": [c.to_dict() for c in self.checks],
            "warnings": list(self.warnings),
            "intent_fingerprint": self.intent_fingerprint,
            "plan_id": self.plan_id,
        }

    def difference_reason(self) -> str:
        """给「复核不通过 → 带差异原因回到感知层重跑」的那条回环用。"""
        return "；".join(f"{c.name}: {c.detail}" for c in self.failures) or "无差异"


def verify_proposal(
    proposal: Mapping[str, Any],
    table: SemanticTable,
    intent: EditIntent,
    *,
    applied_duration_sec: Optional[float] = None,
) -> VerificationReport:
    """按可证伪判据复核一份提案（或已执行的提案）。

    传入 ``applied_duration_sec``（执行后真实成片时长）时会额外核对实际时长；
    不传则只核对预测值，明确标注「未实测」，不把预测伪装成实测。
    """
    checks: List[Check] = []
    warnings: List[str] = []
    intervals = list(proposal.get("intervals") or [])

    # ① 证据可寻址：每条 interval 必须能回到语义表里的真实镜头
    missing = []
    for idx, iv in enumerate(intervals):
        sid = str(iv.get("shot_id") or "")
        shot = table.shot_by_id(sid)
        ev = iv.get("evidence") or {}
        if shot is None:
            missing.append(f"[{idx}]{sid or '无shot_id'}")
            continue
        if not ev or not all(k in ev for k in ("frame_in", "frame_out", "fps")):
            missing.append(f"[{idx}]{sid} 缺帧级证据")
        elif (int(ev["frame_in"]), int(ev["frame_out"])) != (shot.frame_in, shot.frame_out):
            missing.append(f"[{idx}]{sid} 证据帧与语义表不一致")
    checks.append(Check(
        "证据可寻址", not missing,
        "全部 interval 均可定位到语义表的帧区间" if not missing
        else "以下区间缺有效证据：" + "、".join(missing[:5]),
    ))

    # ② 硬约束：禁改区间 / 禁改片段 / 必须保留台词
    violations: List[str] = []
    for idx, iv in enumerate(intervals):
        try:
            a, b = float(iv.get("timeline_in")), float(iv.get("timeline_out"))
        except (TypeError, ValueError):
            violations.append(f"[{idx}] 时间坐标非法")
            continue
        if intent.is_protected(a, b):
            violations.append(f"[{idx}] 命中禁改区间 {a:.2f}~{b:.2f}")
        shot = table.shot_by_id(str(iv.get("shot_id") or ""))
        if shot and shot.clip_id and intent.is_protected_clip(shot.clip_id):
            violations.append(f"[{idx}] 命中禁改片段 {shot.clip_id}")
        if shot:
            for line in intent.keep_lines:
                if line and line in shot.asr_text:
                    violations.append(f"[{idx}] 含必留台词「{line}」")
    checks.append(Check(
        "硬约束", not violations,
        "未违反禁改与必留约束" if not violations else "；".join(violations[:5]),
    ))

    # ③ 可解释：每个决策都要有理由（否则「解释为什么」落空）
    no_reason = [str(iv.get("shot_id") or f"[{i}]")
                 for i, iv in enumerate(intervals) if not str(iv.get("reason") or "").strip()]
    checks.append(Check(
        "决策可解释", not no_reason,
        "每条操作均带理由" if not no_reason else "缺少理由：" + "、".join(no_reason[:5]),
    ))

    # ④ 时长目标（用实测值优先；无实测则如实标注）
    if intent.target_duration_sec > 0:
        measured = applied_duration_sec is not None
        value = float(applied_duration_sec if measured else proposal.get("predicted_duration") or 0.0)
        delta = abs(value - intent.target_duration_sec)
        ok = delta <= intent.duration_tolerance_sec
        checks.append(Check(
            "时长目标" + ("" if measured else "（预测值，未实测）"), ok,
            f"{'实测' if measured else '预测'} {value:.2f}s / 目标 "
            f"{intent.target_duration_sec:.2f}s，偏差 {delta:.2f}s",
        ))
        if not measured:
            warnings.append("未实测成片时长（未传 applied_duration_sec），时长项按预测值核对")
    else:
        checks.append(Check("时长目标", True, "未设目标时长，跳过"))

    # ⑤ 感知诚实度：纯启发式不能冒充模型理解
    if table.source == "heuristic":
        warnings.append("语义表来自像素启发式，非视觉模型结果；复核结论仅覆盖结构正确性")
    checks.append(Check(
        "感知诚实", table.source != "fabricated",
        f"source={table.source}，vision_model={table.vision_model or '无'}",
    ))

    return VerificationReport(
        passed=all(c.passed for c in checks),
        checks=checks, warnings=warnings,
        intent_fingerprint=str(proposal.get("intent_fingerprint") or intent.fingerprint()),
        plan_id=str(proposal.get("plan_id") or ""),
    )


def _memory_store():
    try:
        from app.core.memory_store import MemoryStore
    except ImportError:
        from core.memory_store import MemoryStore  # type: ignore
    return MemoryStore.get_instance()


def write_back(
    report: VerificationReport,
    proposal: Mapping[str, Any],
    *,
    human_confirmed: bool = False,
    note: str = "",
) -> Dict[str, Any]:
    """把复核结果回流记忆。返回写入结果，失败不抛异常。

    · ``execution_trace``：每次复核都写（成败都写，用于回流分析）；
    · ``user_preference``：**仅人确认后**写，避免把模型误判学成长期规则。
    """
    out: Dict[str, Any] = {"trace_id": "", "preference_id": "", "warnings": []}
    try:
        store = _memory_store()
    except Exception as e:
        logger.debug("[fine-cut] 记忆回流取 store 失败：%s", e, exc_info=True)
        out["warnings"].append(f"记忆不可用：{type(e).__name__}: {e}")
        return out
    payload = {
        "plan_id": report.plan_id,
        "intent_fingerprint": report.intent_fingerprint,
        "passed": report.passed,
        "reason": report.difference_reason() if not report.passed else "",
        "interval_count": len(proposal.get("intervals") or []),
        "predicted_duration": proposal.get("predicted_duration"),
        "semantic_source": proposal.get("semantic_source"),
        "decision_source": proposal.get("decision_source"),
        "note": str(note or ""),
    }
    try:
        out["trace_id"] = store.record(
            "execution_trace", payload,
            tags=["fine_cut", "verification", "pass" if report.passed else "fail"],
            score=0.6 if report.passed else 0.8,
        )
    except Exception as e:
        logger.debug("[fine-cut] execution_trace 写入失败：%s", e, exc_info=True)
        out["warnings"].append(f"轨迹写入失败：{type(e).__name__}: {e}")
    if human_confirmed and report.passed:
        try:
            out["preference_id"] = store.record(
                "user_preference",
                {"intent_fingerprint": report.intent_fingerprint,
                 "note": str(note or "") or "人工确认通过的精剪决策",
                 "plan_id": report.plan_id},
                tags=["fine_cut", "confirmed", report.intent_fingerprint],
                score=0.9,
            )
        except Exception as e:
            logger.debug("[fine-cut] user_preference 写入失败：%s", e, exc_info=True)
            out["warnings"].append(f"偏好写入失败：{type(e).__name__}: {e}")
    return out


def submit_human_verdict(
    report: VerificationReport,
    proposal: Mapping[str, Any],
    *,
    label: str,
    note: str = "",
) -> Dict[str, Any]:
    """人工复核结论回流：复用 ``sampling_review`` 的标签通道 + 记忆回流。

    label 约定：``accept`` / ``reject`` / ``partial``。reject 时不写长期偏好。
    """
    normalized = str(label or "").strip().lower()
    if normalized not in ("accept", "reject", "partial"):
        return {"ok": False, "error": "label 必须是 accept / reject / partial"}
    out: Dict[str, Any] = {"ok": True, "label": normalized, "review_label_id": ""}
    try:
        from app.core.ai.sampling_review import get_review
    except ImportError:
        try:
            from core.ai.sampling_review import get_review  # type: ignore
        except ImportError:
            get_review = None  # type: ignore
    if get_review is not None:
        try:
            review = get_review()
            if hasattr(review, "submit_human_label"):
                out["review_label_id"] = review.submit_human_label(
                    report.plan_id or "fine-cut", normalized, note=note,
                )
        except Exception as e:
            logger.debug("[fine-cut] 人审标签回流失败（不阻断）：%s", e, exc_info=True)
            out["review_warning"] = f"{type(e).__name__}: {e}"
    out["memory"] = write_back(
        report, proposal,
        human_confirmed=(normalized == "accept"),
        note=note or f"人工复核：{normalized}",
    )
    return out
