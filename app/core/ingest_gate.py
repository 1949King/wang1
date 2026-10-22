# -*- coding: utf-8 -*-
"""ingest_gate.py — 入轨治理闸门（刀3 / E2 · 2026-10-23）

## 为什么需要一层适配，而不直接调 evaluate_gate

`aesthetic_gate.evaluate_gate()` 的语义是「**有分数时，什么分数不许进下游**」。
它遇到**没有分数**的素材返回 `block`（reason=`missing_scores`）—— 那在
「评分卡复核」场景里是对的（没测过就不该放行），但**直接接进入轨链路会误拦
用户自己的素材**：

    `_add_clip_to_timeline` 有 13 个调用方，其中包含用户手动导入本地视频
    （editor_module.py:4417 / :4518）。用户的素材根本没有五维评分，
    若按 `missing_scores ⇒ block`，**用户导入的每一个视频都会被拦下**。

故本模块定义**入轨语境的判定语义**（与评分复核语境区分开）：

| 素材状态 | evaluate_gate 语境 | **入轨语境（本模块）** |
|---|---|---|
| 有分数且 D 级 | block | **block**（坏素材不许进） |
| 有分数且 C 级 | review | **review**（进，但要提示） |
| 有分数且 A/B 级 | pass | **pass** |
| **无任何分数** | block(missing_scores) | **pass（不判定）** —— 治理只判「测过的坏」，不判「没测过的」 |

理由（写进纪律）：治理层**没有资格**因为没有评分就否定用户自己的文件。
把「没测」当成「坏」是推理错误，也正是本项目 §8 诚实红线反复禁止的
「把没测出来说成测出来了」的镜像错误。

## 四条纪律

1. **无分数 ⇒ 放行**，且理由码明确写 `unscored_allow`（不静默）；
2. **block 就是 block**，除非调用方显式 `force=True` —— 且 force 必须留痕
   （返回里带 `forced: true` + 原判定），不许静默放行；
3. **agent 来源**才默认受管：`source` 白名单外的（用户手动导入）默认不判定，
   需要调用方显式开启（`enforce_unscored=False` 的默认值即「不管」）；
4. 只判不修：本模块不改 clip、不写时间线、不弹 UI（纯函数，零依赖）。

## 接线位置（本刀实际落点）

`EditorModule.agent_replace_timeline_clips(clips)` —— S3→S4 的**批量入轨**入口，
收的是 clip dict 列表，可携带 `semantic.quality`。不接在
`_add_clip_to_timeline(file_path)`：那里只有路径、拿不到分数，接了也是空转
（本项目明确反对「注册了但模型看不见」的空接线，见 §2d.6）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

try:
    from app.core.aesthetic_gate import evaluate_gate
except ImportError:  # 兼容 `core.*` 旧导入路径
    from core.aesthetic_gate import evaluate_gate  # type: ignore

GATE_VERSION = "ingest-1.0"

#: 默认受治理的入轨来源（AI 生成产物）。不在表内 ⇒ 无分数时一律不判定。
GOVERNED_SOURCES = ("canvas", "canvas_generated", "stage3d_pose_video",
                    "stage3d_frames", "ai", "agent", "code_video", "pipeline")


def has_scores(item: Any) -> bool:
    """该素材是否带有**可判定**的评分。

    判定口径与 `aesthetic_gate` 一致：有 `weighted_score`，或五维里至少有
    一项是真数字。只认数字（bool 不算）—— 避免 `"85"` 这类字符串被当分数。
    """
    if not isinstance(item, Mapping):
        return False
    score = item.get("weighted_score")
    if isinstance(score, (int, float)) and not isinstance(score, bool):
        return True
    dims = item.get("dimensions")
    if isinstance(dims, Mapping):
        for value in dims.values():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return True
    return False


def _collect_findings(decision: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """把 gate 的扁平结果整理成「可读的拦截明细」列表。"""
    return [{"decision": decision.get("decision", ""),
             "reasons": list(decision.get("reasons") or [])}]


def decide(
    item: Any,
    *,
    source: str = "",
    policy: Optional[Mapping[str, Any]] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """对**一个**待入轨素材做治理判定（纯函数）。

    返回::

        {
          "gate": "ingest-1.0",
          "decision": "pass" | "review" | "block",
          "reason": "<人可读一句话>",
          "reasons": [...],           # 细分原因码（来自 aesthetic_gate）
          "scored": bool,             # 是否真的做了评分判定
          "forced": bool,             # 是否由 force 放行
          "source": str,
        }

    `force=True` 只对 block 生效：放行但 `forced=True` 并把原判定留在 `reasons`，
    保证「放行这件事有痕迹」（纪律 2）。
    """
    src = str(source or "").strip().lower()
    if not src and isinstance(item, Mapping):
        # 显式参数优先；未给则从素材自身读（`decide_batch` 与单条调用口径统一，
        # 避免「批量传了、单条漏传」导致来源静默丢失）。
        src = str(item.get("source") or "").strip().lower()
    if not has_scores(item):
        if force:
            # force 不该改变「没测」这一事实，仍如实标注
            return {"gate": GATE_VERSION, "decision": "pass",
                    "reason": "素材无评分（不可判定），已放行", "reasons": [],
                    "scored": False, "forced": True, "source": src}
        return {"gate": GATE_VERSION, "decision": "pass",
                "reason": "素材无评分，治理不判定（只判测过的坏素材）",
                "reasons": [], "scored": False, "forced": False, "source": src}

    raw = evaluate_gate(dict(item) if isinstance(item, Mapping) else {},
                        dict(policy) if isinstance(policy, Mapping) else None)
    decision = str(raw.get("decision") or "block")
    reasons = list(raw.get("reasons") or [])
    forced = False

    if decision == "block" and force:
        decision = "review"   # 放行但仍要求人工确认，不直接 pass
        forced = True
        reasons = reasons + ["forced_by_caller"]

    label = {"pass": "通过", "review": "需人工确认", "block": "拒绝入轨"}.get(decision, decision)
    if forced:
        reason = f"治理判定为 block，调用方 force 放行（降为人工确认）：{label}"
    elif decision == "block":
        reason = f"治理拒绝：{'；'.join(reasons) or '分数不达标'}"
    elif decision == "review":
        reason = f"治理要求人工确认：{'；'.join(reasons) or '分数处于复核区间'}"
    else:
        reason = "治理通过"

    return {"gate": GATE_VERSION, "decision": decision, "reason": reason,
            "reasons": reasons, "scored": True, "forced": forced,
            "source": src}


def decide_batch(
    items: Any,
    *,
    policy: Optional[Mapping[str, Any]] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """对一批待入轨素材批量判定（S3→S4 批量入轨的入口用）。

    返回 ``{"verdict": "pass|review|block", "blocked": [...], "review": [...],
    "allowed": [...], "results": [...]}``：

    * 任一 block ⇒ 整体 verdict = block（硬闸门：坏素材混进来就不许整批过）；
    * 否则任一 review ⇒ verdict = review；
    * 全 pass ⇒ verdict = pass。
    * 无分数素材计入 allowed（不判定），且 `unscored_count` 如实报数。
    """
    seq = items if isinstance(items, (list, tuple)) else []
    results: List[Dict[str, Any]] = []
    blocked: List[Dict[str, Any]] = []
    review: List[Dict[str, Any]] = []
    allowed: List[Dict[str, Any]] = []
    unscored = 0

    for raw_item in seq:
        if not isinstance(raw_item, Mapping):
            continue
        decision = decide(raw_item, source=str(raw_item.get("source") or ""),
                          policy=policy, force=force)
        if not decision["scored"]:
            unscored += 1
        row = dict(decision)
        row["clip_id"] = str(raw_item.get("clip_id") or raw_item.get("id") or "")
        results.append(row)
        if decision["decision"] == "block":
            blocked.append(row)
        elif decision["decision"] == "review":
            review.append(row)
        else:
            allowed.append(row)

    if blocked:
        verdict = "block"
    elif review:
        verdict = "review"
    else:
        verdict = "pass"

    return {"gate": GATE_VERSION, "verdict": verdict, "blocked": blocked,
            "review": review, "allowed": allowed, "results": results,
            "unscored_count": unscored, "total": len(results)}


def rejection_payload(result: Mapping[str, Any], *, stage: str = "ingest") -> Dict[str, Any]:
    """把 block 结果整理成**统一的拒绝响应**（供能力层 / HTTP 层复用）。

    形状对齐项目既有约定：`{ok: False, code, message, ...明细}`。
    `code="gate_blocked"` 与刀1 的 `"conflict"` 并列，便于上层区分「冲突」
    与「治理拒绝」两类拒绝。
    """
    blocked = list(result.get("blocked") or [])
    preview = [{"clip_id": b.get("clip_id", ""),
                "reasons": b.get("reasons", [])[:3]} for b in blocked[:5]]
    return {
        "ok": False,
        "code": "gate_blocked",
        "stage": stage,
        "message": (
            f"治理闸门拒绝入轨：{len(blocked)} 个素材不达标准"
            + ("（另有 %d 个待人工确认）" % len(result.get("review") or [])
               if result.get("review") else "")
            + "。已放行: %d；未评分（不判定）: %d。"
              % (len(result.get("allowed") or []), result.get("unscored_count", 0))
        ),
        "blocked": preview,
        "blocked_count": len(blocked),
        "review_count": len(result.get("review") or []),
        "allowed_count": len(result.get("allowed") or []),
        "unscored_count": result.get("unscored_count", 0),
    }
