"""六种标准执行模式 + 可行集投影（规格书 §10/§11/§12，V4.37.8 切片⑤）
====================================================================
规格书第三篇把「单元由谁执行」形式化为六种模式::

    Mode ∈ {L, C, D, L→C, C→L, SkipMerge}
    L          纯本地推理（低成本、稳、默认基线）
    C          纯云端推理（高质量、耗成本）
    D          本地+云端并行 + 智能融合（分歧高、关键单元启用）
    L→C        本地优先，不达标自动补云端
    C→L        云端优先，网络不稳/失败回退本地
    SkipMerge  单路直出，跳过融合节省算力

本模块落地规格书两条铁律：

1. **基线锚点**（§11）：本地模式惩罚恒为 0 —— 云端/双路只惩罚**增量**成本、
   **增量**延迟。宽松预算下系统自然收敛到本地，杜绝 D 模式泛滥 / λ 顶饱和。
   λ 的物理意义：每牺牲 1 单位质量，愿意换取多少成本节省。

2. **可行集投影正交**（§12）：打分层纯收益最大化、无硬约束；投影层
   （显存 / QPS / 断网）**只删除不可行选项，绝不修改打分**——
   保证日志可完全归因、闭环可解释。

设计纪律（同 provider_caps / quality_prior / budget_pacer）：
  - 纯逻辑、不 import app 包；异常不抛；
  - 所有决策返回**完整归因字典**（分数、被删项+理由、λ、基线）；
  - 融合质量估计用独立误差上界 q_D = 1 − (1−q_L)(1−q_C)（双路都错才错）。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("AI短剧编辑器.core.ai.execution_modes")

# ═══════════════════════════════════════════════════════════
# 六种标准执行模式（§10）
# ═══════════════════════════════════════════════════════════

MODE_L = "L"
MODE_C = "C"
MODE_D = "D"
MODE_L2C = "L→C"
MODE_C2L = "C→L"
MODE_SKIP_MERGE = "SkipMerge"

ALL_MODES: Tuple[str, ...] = (MODE_L, MODE_C, MODE_D, MODE_L2C, MODE_C2L, MODE_SKIP_MERGE)

_MODE_LABELS = {
    MODE_L: "纯本地推理",
    MODE_C: "纯云端推理",
    MODE_D: "双路并行+融合",
    MODE_L2C: "本地优先补云端",
    MODE_C2L: "云端优先回退本地",
    MODE_SKIP_MERGE: "单路直出跳过融合",
}


def mode_label(mode: str) -> str:
    """模式 → 人话（审计日志 / UI 用）。"""
    return _MODE_LABELS.get(mode, mode)


# ═══════════════════════════════════════════════════════════
# 打分层：修正后最终收益函数（§11 v4.1 定稿）
# ═══════════════════════════════════════════════════════════
#
# V_i(m) = q̂_i(m) − λ_c·(ĉ_i(m) − c_base) − λ_l·(l̂_i(m) − l_base) − κ_sw·1{switch}
# 基线写死：c_base = 本地成本，l_base = 本地延迟 → 本地惩罚恒 0。


def fused_quality(q_local: float, q_cloud: float) -> float:
    """双路融合质量上界：独立误差假设下「两路都错才错」。

    q_D = 1 − (1−q_L)(1−q_C) ≥ max(q_L, q_C)，单调、恒在 [0,1]。
    """
    ql = min(1.0, max(0.0, float(q_local)))
    qc = min(1.0, max(0.0, float(q_cloud)))
    return 1.0 - (1.0 - ql) * (1.0 - qc)


def score_modes(q_local: float, q_cloud: float,
                cost_local: float, cost_cloud: float,
                lat_local: float = 0.0, lat_cloud: float = 0.0,
                lambda_c: float = 0.2, lambda_l: float = 0.0,
                kappa_sw: float = 0.0, current_mode: str = ""
                ) -> Dict[str, float]:
    """给六种模式逐一打收益分（**无硬约束**，硬约束归投影层）。

    参数均为**预测值**（q̂/ĉ/l̂）；``current_mode`` 非空且与候选模式不同
    时扣切换成本 κ_sw（§11 切换惩罚项）。

    成本/延迟基线 = 本地模式（本地惩罚恒 0）：
      L  : q_L                              （零成本锚点）
      C  : q_C − λ_c·Δc − λ_l·Δl
      D  : q_D − λ_c·(c_L+c_C−c_base) − λ_l·(max(l_L,l_C)−l_base)   双路双倍成本
      L→C: 期望 = P(本地达标)·V_L + P(补云端)·(V_C 减去二次延迟)
      C→L: 期望 = P(云端成功)·V_C + P(回退)·V_L（回退概率小 → 接近 V_C）
      SkipMerge: 单路直出 = V_C + 融合节省奖励（省一次融合/校验算力）
    """
    c_base = max(0.0, float(cost_local))
    l_base = max(0.0, float(lat_local))
    lam_c = max(0.0, float(lambda_c))
    lam_l = max(0.0, float(lambda_l))
    q_d = fused_quality(q_local, q_cloud)

    v: Dict[str, float] = {}
    v[MODE_L] = float(q_local)  # 基线锚点：惩罚恒 0
    v[MODE_C] = (float(q_cloud)
                 - lam_c * max(0.0, float(cost_cloud) - c_base)
                 - lam_l * max(0.0, float(lat_cloud) - l_base))
    v[MODE_D] = (q_d
                 - lam_c * max(0.0, float(cost_local) + float(cost_cloud) - c_base)
                 - lam_l * max(0.0, max(float(lat_local), float(lat_cloud)) - l_base))
    # L→C：本地不达标才补云端；达标率取本地质量先验（q_L 即「本地够好」的期望）
    p_local_ok = min(1.0, max(0.0, float(q_local)))
    v[MODE_L2C] = p_local_ok * v[MODE_L] + (1.0 - p_local_ok) * (
        v[MODE_C] - lam_l * max(0.0, float(lat_local)))  # 补云端要白等一次本地
    # C→L：云端失败才回退本地；失败率取 1−q_C
    p_cloud_ok = min(1.0, max(0.0, float(q_cloud)))
    v[MODE_C2L] = p_cloud_ok * v[MODE_C] + (1.0 - p_cloud_ok) * v[MODE_L]
    # SkipMerge：单路直出省融合校验，给固定小额算力节省奖励（等价成本视角）
    v[MODE_SKIP_MERGE] = v[MODE_C] + lam_c * 0.05

    if current_mode and kappa_sw > 0.0:
        for m in v:
            if m != current_mode:
                v[m] -= float(kappa_sw)
    return v


# ═══════════════════════════════════════════════════════════
# 投影层：可行集投影（§12 工程铁律——只删不改分）
# ═══════════════════════════════════════════════════════════


def project_feasible(scores: Dict[str, float],
                     infeasible: Optional[Dict[str, str]] = None
                     ) -> Dict[str, Any]:
    """可行集投影：硬约束**只删除**不可行选项，**绝不修改打分**。

    参数：
        scores:     打分层输出 {mode: V}
        infeasible: {mode: 人话理由} —— 由调用方按硬约束（断网 / 显存 /
                    QPS / 无云端 key / 本地无模型）给出

    Returns::
        {"kept": [(mode, score), ...] 按收益降序,
         "dropped": [(mode, 理由), ...]}
    """
    inf = dict(infeasible) if isinstance(infeasible, dict) else {}
    kept = sorted(
        ((m, float(s)) for m, s in scores.items() if m not in inf),
        key=lambda kv: -kv[1])
    dropped = [(m, inf[m]) for m in scores if m in inf]
    for m, reason in dropped:
        logger.info("[execution_modes] 模式 %s 被投影删除：%s", m, reason)
    return {"kept": kept, "dropped": dropped}


def choose_mode(q_local: float, q_cloud: float,
                cost_local: float, cost_cloud: float,
                lat_local: float = 0.0, lat_cloud: float = 0.0,
                lambda_c: float = 0.2, lambda_l: float = 0.0,
                kappa_sw: float = 0.0, current_mode: str = "",
                infeasible: Optional[Dict[str, str]] = None
                ) -> Dict[str, Any]:
    """**主入口**：打分 → 投影 → 选最优，返回完整归因（§12 可解释性）。

    Returns::
        {"mode": 最优模式, "label": 人话,
         "scores": {mode: V},            # 打分层原始分（投影不改分）
         "kept": [...], "dropped": [(mode, 理由)...],
         "baseline": {"cost": c_base, "latency": l_base},
         "lambda_c": …, "lambda_l": …, "kappa_sw": …}
    """
    scores = score_modes(q_local, q_cloud, cost_local, cost_cloud,
                         lat_local, lat_cloud, lambda_c, lambda_l,
                         kappa_sw, current_mode)
    proj = project_feasible(scores, infeasible)
    chosen = proj["kept"][0][0] if proj["kept"] else MODE_L  # 全删光 → 本地锚点
    return {
        "mode": chosen,
        "label": mode_label(chosen),
        "scores": scores,
        "kept": proj["kept"],
        "dropped": proj["dropped"],
        "baseline": {"cost": max(0.0, float(cost_local)),
                     "latency": max(0.0, float(lat_local))},
        "lambda_c": float(lambda_c),
        "lambda_l": float(lambda_l),
        "kappa_sw": float(kappa_sw),
    }


# ═══════════════════════════════════════════════════════════
# 硬约束采集（桌面单机版：网络 / 云端 key / 显存占位）
# ═══════════════════════════════════════════════════════════


def collect_infeasible(*, online: bool = True, cloud_available: bool = True,
                       local_available: bool = True,
                       vram_ok: bool = True) -> Dict[str, str]:
    """把全局硬约束翻译成「模式删除清单」（§12/§40：L0 令牌池的桌面简化）。

    断网 / 无云端 key → 删掉一切含云端的模式；本地不可用 → 删含本地的；
    显存不足 → 删双路（要同时驻留两路）。
    """
    inf: Dict[str, str] = {}
    if not online:
        for m in (MODE_C, MODE_D, MODE_L2C, MODE_C2L, MODE_SKIP_MERGE):
            inf[m] = "断网：云端不可达"
    elif not cloud_available:
        for m in (MODE_C, MODE_D, MODE_L2C, MODE_SKIP_MERGE):
            inf[m] = "云端不可用（无 key / 熔断）"
    if not local_available:
        for m in (MODE_L, MODE_D, MODE_L2C, MODE_C2L):
            inf[m] = "本地推理不可用"
    if not vram_ok:
        inf[MODE_D] = "显存不足：双路需同时驻留"
    return inf
