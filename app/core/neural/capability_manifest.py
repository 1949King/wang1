# -*- coding: utf-8 -*-
"""能力清单（capability manifest）—— 「声明即承诺」的合并出口（P0 · 2026-10-28）

它解决什么问题
==============
`engine_registry` 能回答「谁在册、健康不健康、有没有被调用」，
但回答不了自主可控最要紧的那一问：

    **这个引擎到底自己持有哪些能力？哪一部分还是别人在跑？**

此前这些信息散在注释里——「diffusers_image 支持四档 offload」「SVD 必须 offload」
「步缓存只在 SD 系挂」全是散文，没有一处机器可读。散文的后果是可预见的：
新接一个族时没人知道要补哪几项，UI 也可能「显示支持、实际静默回退」。

本模块把 registry 的 5 个能力字段（quant / offload_tiers / step_cache /
verified / loop_owner）**合并成一份可校验的清单**，并给出 K5 覆盖率与违约清单。

三条纪律（对齐项目既有法条）
============================
1. **复用真源，不另造词表**：三态 `verified/unverified/blocked` 与族名直接取
   `model_family`（那里已经是真源），本模块不定义第二套。
2. **覆盖率只报实话**：K5 = 「`loop_owner=shiguang` 且 `verified` 的目标族数 / 4」。
   现在内核还没写，所以它报 **0/4** —— 这正是它存在的意义：P2/P3 落地前，
   任何人都不该在文档或 UI 里说"自研循环已覆盖 SD"。
3. **纯 stdlib、零 torch**：画布 HTTP 线程与门禁脚本都要能直接调。

与 registry 的分工：registry 是**登记条目**，本模块是**合并视图 + 违约检查**。
两者字段不一致时以 registry 为准，本模块只读不写（守卫负责发现漂移）。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

# ★ 复用真源：三态与族名不在这里重新定义（定义两套必然漂移）
from app.core.neural.model_family import BLOCKED, UNVERIFIED, VERIFIED

logger = logging.getLogger(__name__)

# ── K5 分母：P2/P3 的目标族（不是全部 9 族）─────────────────────────
# 依据 `docs/design/推理引擎架构设计.md` §7：
#   P2 图像内核 sd15 → sdxl（2 族），P3 视频内核 svd（1 族），wan 待实测（第 4 族）。
# 其余族（cogvideox / hunyuan / ltx / mochi / minimax_h3）**不在目标里**——
# 本机无权重，硬做即假验证（见架构文档 §7「不做」表）。
TARGET_FAMILIES: Tuple[str, ...] = ("sd15", "sdxl", "svd", "wan")

#: 目标族 → 承载它的 registry 引擎 id。
#: K5 判定看**承载引擎**的 loop_owner/verified，不看族自己的 verification
#: （族说「本机跑过」，引擎说「循环归谁」——两件事，不能混）。
FAMILY_ENGINE: Dict[str, str] = {
    "sd15": "image.diffusers",
    "sdxl": "image.diffusers",
    "svd": "video.svd",
    "wan": "video.local_video_infer",
}

#: 两腿声明位（D6.1：同一 engine id 允许 pipe 兜底 + kernel 主路径并存）。
#: 结构一旦填了，`violations()` 会要求 kernel 腿有真实模块、且能力不与 pipe 腿混报。
#:
#: 2026-10-28 P2 填了 sd15 / sdxl 两条：图像族现在**确实**有两腿 ——
#:   pipe 腿（`diffusers_image.py` 直调 `pipe()`）是默认与回退，
#:   kernel 腿（`kernel/loop.py`）在 `SHIGUANG_KERNEL=on` 时接管。
#: 两腿都标 verified，因为两腿都实测过（四门判据见 `docs/knowledge/kernel_evidence.json`）。
#: 2026-10-28 P3 加入 svd：视频族同样两腿（`video_gen.generate` 直调 `pipe()` 为默认与回退），
#:   四门实测见台账（逐帧 PSNR=inf / Δ=0 / 1.014× / 1.000×，门槛 1.10）。
#: wan 仍只有一腿（无 adapter），故不在此列 —— 列了就是预告，不是事实。
TWO_LEGS: Tuple[Dict[str, Any], ...] = (
    {
        "engine_id": "image.diffusers",
        "family": "sd15",
        "pipe_leg": {
            "module": "app/core/neural/diffusers_image.py",
            "verified": VERIFIED,
            "role": "default+fallback",
        },
        "kernel_leg": {
            "module": "app/core/neural/kernel/loop.py",
            "adapter": "app/core/neural/kernel/adapters/sd15.py",
            "verified": VERIFIED,
            "gate": "SHIGUANG_KERNEL=on",
        },
    },
    {
        "engine_id": "image.diffusers",
        "family": "sdxl",
        "pipe_leg": {
            "module": "app/core/neural/diffusers_image.py",
            "verified": VERIFIED,
            "role": "default+fallback",
        },
        "kernel_leg": {
            "module": "app/core/neural/kernel/loop.py",
            "adapter": "app/core/neural/kernel/adapters/sdxl.py",
            "verified": VERIFIED,
            "gate": "SHIGUANG_KERNEL=on",
        },
    },
    {
        "engine_id": "video.svd",
        "family": "svd",
        "pipe_leg": {
            "module": "app/core/neural/video_gen.py",
            "verified": VERIFIED,
            "role": "default+fallback",
        },
        "kernel_leg": {
            "module": "app/core/neural/kernel/loop.py",
            "adapter": "app/core/neural/kernel/adapters/svd.py",
            "verified": VERIFIED,
            "gate": "SHIGUANG_KERNEL=on",
        },
    },
)


def _registry() -> Tuple[Any, ...]:
    """惰性取 registry（避免 import 顺序问题；registry 本身也是 stdlib）。"""
    from app.core import engine_registry as ER

    return ER.ENGINES


def _quant_state(scheme: str) -> Tuple[bool, str]:
    """量化方案能否进主路径 —— 判定权在 `quant_descriptor`，此处只转述。"""
    if not scheme:
        return False, "未声明量化方案"
    try:
        from app.core.neural import quant_descriptor as QD

        return QD.is_admissible(scheme)
    except Exception:  # 台账不可用时不许猜「可准入」
        logger.debug("[capability_manifest] quant_descriptor 不可用", exc_info=True)
        return False, "量化台账不可用 ⇒ 无法证明可准入"


def engine_capabilities(engine: Any) -> Dict[str, Any]:
    """单个引擎的能力条目（只读 registry 字段，不探测 GPU）。"""
    try:
        from app.core import engine_registry as ER

        health, missing = ER.health(engine)
    except Exception:
        health, missing = "unknown", []

    quant = str(getattr(engine, "quant", "") or "")
    quant_ok, quant_why = _quant_state(quant)
    return {
        "id": engine.id,
        "family": engine.family,
        "capability": engine.capability,
        "role": engine.role,
        # ── 5 个能力字段（P0 契约）──
        "quant": quant or "",
        "quant_admissible": bool(quant_ok),
        "quant_why": quant_why,
        "offload_tiers": tuple(getattr(engine, "offload_tiers", ()) or ()),
        "step_cache": bool(getattr(engine, "step_cache", False)),
        "verified": str(getattr(engine, "verified", UNVERIFIED) or UNVERIFIED),
        "loop_owner": str(getattr(engine, "loop_owner", "upstream") or "upstream"),
        # ── 观测 ──
        "health": health,
        "missing_deps": missing,
    }


def registrations() -> List[Dict[str, Any]]:
    """全部登记项的能力条目。"""
    return [engine_capabilities(e) for e in _registry()]


def coverage() -> Dict[str, Any]:
    """K5 覆盖率：`loop_owner=shiguang` 且 `verified` 的目标族数 / 目标族数。

    口径写死在这里，不许各报告各自算：分子只认**承载引擎**的两个字段同时成立。
    """
    by_id = {r["id"]: r for r in registrations()}
    owned: List[str] = []
    pending: List[Dict[str, str]] = []
    for fam in TARGET_FAMILIES:
        eid = FAMILY_ENGINE.get(fam, "")
        rec = by_id.get(eid)
        if rec is None:
            pending.append({"family": fam, "engine": eid, "why": "承载引擎未登记"})
            continue
        if rec["loop_owner"] == "shiguang" and rec["verified"] == VERIFIED:
            owned.append(fam)
        else:
            pending.append({
                "family": fam, "engine": eid,
                "why": "loop_owner=%s / verified=%s"
                       % (rec["loop_owner"], rec["verified"]),
            })
    denom = len(TARGET_FAMILIES)
    return {
        "kpi": "K5",
        "owned": owned,
        "target": list(TARGET_FAMILIES),
        "ratio": "%d/%d" % (len(owned), denom),
        "value": round(len(owned) / denom, 3) if denom else 0.0,
        "pending": pending,
        "note": "分子要求 loop_owner=shiguang 且 verified 同时成立；内核未落地时应为 0",
    }


def violations() -> List[str]:
    """契约违约清单（空 = 干净）。守卫脚本与测试共用同一份判定。"""
    out: List[str] = []
    try:
        from app.core.neural import memory_policy as MP

        active = set(MP.ACTIVE_MODES)
    except Exception:
        active = set()

    seen: Dict[str, int] = {}
    for rec in registrations():
        eid = rec["id"]
        seen[eid] = seen.get(eid, 0) + 1
        # ① 值域
        if rec["loop_owner"] not in ("shiguang", "upstream"):
            out.append("%s: loop_owner=%r 不是 shiguang/upstream" % (eid, rec["loop_owner"]))
        if rec["verified"] not in (VERIFIED, UNVERIFIED, BLOCKED):
            out.append("%s: verified=%r 不在三态值域" % (eid, rec["verified"]))
        # ② offload 档位必须是已实现档（不许声明预告档）
        if active:
            bad = [t for t in rec["offload_tiers"] if t not in active]
            if bad:
                out.append("%s: offload_tiers 含未实现档 %s" % (eid, bad))
        # ③ 推理引擎必须显式声明量化方案，且可准入。
        #    豁免 library-only / retired / disabled：这些不在我们的主路径上
        #    （如 comfy_provider 的精度由 ComfyUI 工作流决定，我们无权也不该代它声明），
        #    逼它填一个 quant 只会变成"为了过门禁而编数据"——正是本项目最反对的事。
        must_declare = rec["capability"] in ("image", "video") and \
            rec["role"] not in ("library-only", "retired", "disabled")
        if must_declare and not rec["quant"]:
            out.append("%s: 主路径推理引擎未声明 quant（标准 4 要求显式）" % eid)
        if rec["quant"] and not rec["quant_admissible"]:
            out.append("%s: quant=%r 不可准入（%s）" % (eid, rec["quant"], rec["quant_why"]))
        # ④ 「声明即承诺」：说循环归自己，就必须真有内核模块；说 verified 同理
        if rec["loop_owner"] == "shiguang" and rec["verified"] == VERIFIED:
            try:
                from app.core import engine_registry as ER

                if not ER._module_exists("app/core/neural/kernel/loop.py"):
                    out.append(
                        "%s: 声称 loop_owner=shiguang+verified，但 kernel/loop.py 不存在"
                        % eid)
            except Exception:
                out.append("%s: 无法验证内核模块是否存在" % eid)
        # ⑤ library-only / retired 不得声明为 verified 主路径
        if rec["role"] in ("library-only", "retired") and rec["verified"] == VERIFIED:
            out.append("%s: role=%s 却声明 verified（无入口的能力不算可用）"
                       % (eid, rec["role"]))
    for eid, n in seen.items():
        if n > 1:
            out.append("重复登记：%s 出现 %d 次" % (eid, n))
    # ⑥ 目标族必须都在 model_family 里（防本模块自说自话）
    try:
        from app.core.neural import model_family as MF

        for fam in TARGET_FAMILIES:
            if MF.spec_of(fam) is None:
                out.append("目标族 %s 在 model_family 中不存在（K5 分母失真）" % fam)
    except Exception:
        out.append("model_family 不可用 ⇒ K5 目标族无法交叉校验")
    # ⑦ 两腿声明必须自洽
    for leg in TWO_LEGS:
        eid = str(leg.get("engine_id") or "")
        if not eid:
            out.append("TWO_LEGS 有条目缺 engine_id")
        kernel = leg.get("kernel_leg") or {}
        if kernel.get("verified") == VERIFIED and not kernel.get("module"):
            out.append("%s: kernel 腿声明 verified 但没给 module" % eid)
    return out


def manifest() -> Dict[str, Any]:
    """合并视图：一页回答「自己有什么、还欠什么、有没有撒谎」。"""
    regs = registrations()
    by_verified: Dict[str, int] = {}
    by_owner: Dict[str, int] = {}
    for r in regs:
        by_verified[r["verified"]] = by_verified.get(r["verified"], 0) + 1
        by_owner[r["loop_owner"]] = by_owner.get(r["loop_owner"], 0) + 1
    return {
        "engines_n": len(regs),
        "by_verified": by_verified,
        "by_loop_owner": by_owner,
        "coverage": coverage(),
        "two_legs": [dict(x) for x in TWO_LEGS],
        "violations": violations(),
        "engines": regs,
    }


def describe() -> str:
    """人类可读的一页账（CLI / 日志 / 门禁输出用）。"""
    m = manifest()
    cov = m["coverage"]
    lines = [
        "能力清单：%d 个引擎 ｜ verified %s ｜ loop_owner %s"
        % (m["engines_n"], m["by_verified"], m["by_loop_owner"]),
        "K5 覆盖率 %s（目标 %s）: %s"
        % (cov["ratio"], "/".join(cov["target"]), "、".join(cov["owned"]) or "（无）"),
    ]
    for p in cov["pending"]:
        lines.append("  · 待补 %-12s → %-24s %s" % (p["family"], p["engine"], p["why"]))
    lines.append("违约 %d 条" % len(m["violations"]))
    for v in m["violations"]:
        lines.append("  ✗ %s" % v)
    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover - CLI
    print(describe())  # stability-gate: allow-print（__main__ CLI 入口，输出给人看）
