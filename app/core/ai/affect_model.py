# -*- coding: utf-8 -*-
"""Agent 内心状态模型（Affect Model）—— 让 Agent 从「工具遥控器」变成「有状态的执行体」。

来源与定位
----------
公式体系来自用户提供的「小凌意识」手稿（10 组公式：感受生成 / 冷热感受 / 激活与
进取欲 / 期望生成 / 天然惰性·信任 / SoulDrive 触发线索 / 心理落量 / 学习与期望
更新）。本模块是**面向剪辑 Agent 语境的独立实现**，不是对生物意识的模拟——
把「身体状态」替换成 Agent 的运行时环境（预算、失败率、重试、审批事件）。

三条使用前提（改参数前务必先读，与 memory_model.py 同一纪律）
--------------------------------------------------------------
1. **所有量夹紧 [0,1]。**  任何输入越界都先裁剪，NaN/非数值归中性或 0，
   不允许「感受爆炸」把决策推向极端。

2. **冷启动 = 行为完全不变。**  无数据时：pain=0、trust=0.5（中性）、
   arousal 低于进取阈值、drive 低于主动建议阈值、期望 M=0.5。
   此时所有门控输出「不干预」⇒ 与没有本模块时逐字节一致。
   红线与 agent_brain.suggest_next 相同：default 置顶 + 稳定排序，**不做 ε 随机探索**。

3. **本模型描述「Agent 对任务的内心状态」，不是「用户情绪」。**
   形式与情绪计算相同、参数语义不同，勿混用；也不得拿它向用户输出「我很难过」
   这类拟人话术——它只参与内部门控与控制台展示。

公式 → Agent 语境的映射（关键设计决策）
----------------------------------------
| 手稿公式 | Agent 语境替换 |
|----------|----------------|
| pain = S×I×C 的 C「身体状态」 | 疲劳 = 预算消耗率 + 连续失败升压 |
| 冷/热感受 | 冷=资源匮乏感（记忆稀薄/预算见底），热=过载感（调用密集/连续重试） |
| A = w1·S+w2·N+w3·E+w4·G+w5·M 的「进取/保守」 | 进取=可建议更多主动动作；保守=只观察、少建议。**永不自动执行写操作** |
| Trust = α·P+β·Cons−γ·V−δ·B | 信任决定「学到的突触权重打几折用」：低信任 → 权重向中性 0.5 收缩 |
| SoulDrive 触发线索 | 是否产出「主动建议」的门控（如失败片段要不要局部重生成） |
| Impact = P×H×U×D | 习得性谨慎：连续不可控失败时收敛建议、如实报告走不通的原因 |
| M_{t+1} = M_t + α(E−M_t) | 对每个决策分支的成功率期望做 EWMA，α=0.3，M0=0.5 |
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import logging

logger = logging.getLogger(__name__)

__all__ = [
    "AffectWeights",
    "AffectState",
    "agent_affect",
    "clamp01",
    "disappointment",
    "psych_impact",
    "trust_score",
    "update_expectation",
]

# ═══════════════════════════════════════════════════════════════
# 夹紧工具（前提 1）
# ═══════════════════════════════════════════════════════════════

def clamp01(value: Any, neutral: float = 0.0) -> float:
    """裁剪到 [0,1]；非数值/NaN 归 neutral。"""
    try:
        num = float(value)
    except (TypeError, ValueError):
        return float(neutral)
    if math.isnan(num):
        return float(neutral)
    return min(1.0, max(0.0, num))


# ═══════════════════════════════════════════════════════════════
# 公式参数（集中一处，注释写明中性条件，防止改崩冷启动）
# ═══════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class AffectWeights:
    """全部公式系数。**中性不变量**：α+β=1 且中性输入(0.5,0.5,0,0)时 Trust=0.5；
    疲劳权重和=1 且中性输入时 arousal=0.5 < 阈值（保守）。"""

    # ② pain = S × I × C
    # ③ 冷热感受的内外环境权重（归一）
    cold_w: Dict[str, float] = field(default_factory=lambda: {
        "memory_scarcity": 0.4,   # 记忆/突触稀薄 → 对世界一无所知的不安
        "budget_low": 0.4,        # 预算见底
        "isolated": 0.2,          # 长期无反馈（无用户确认/无回流观察）
    })
    heat_w: Dict[str, float] = field(default_factory=lambda: {
        "call_density": 0.4,      # 单位轮次工具调用过密
        "retry_pressure": 0.4,    # 重试占比
        "budget_burn": 0.2,       # 预算燃烧率
    })
    # ④ 激活 A = w1·S + w2·N + w3·E + w4·G + w5·M（和=1）
    arousal_w: Dict[str, float] = field(default_factory=lambda: {
        "novelty": 0.20,          # S 新颖性：触达没学过的能力
        "need": 0.20,             # N 需求：任务紧迫/预算压力
        "emotion": 0.20,          # E 情绪强度：max(pain, disappointment)
        "goal": 0.20,             # G 目标相关：任务与已学路径的匹配
        "memory": 0.20,           # M 记忆：突触经验量
    })
    AROUSAL_THRESHOLD = 0.60      # A 高于此 → 进取模式；中性 0.5 < 0.6 ⇒ 冷启动保守
    # ⑤ 失望 Disappointment = E × I × (1 − PE)（E=期望值 M，PE=负面意外度）
    # ⑥ 信任 Trust = α·P + β·Cons − γ·V − δ·B（α+β=1 保证中性=0.5）
    trust_alpha: float = 0.70     # P 过去成功率
    trust_beta: float = 0.30      # Cons 一致性
    trust_gamma: float = 0.40     # V 疲劳/代价
    trust_delta: float = 0.20     # B 边界事件（审批被打断/被拒）
    # ⑦/⑨ SoulDrive 触发线索权重（和=1），中性≈0.5
    drive_w: Dict[str, float] = field(default_factory=lambda: {
        "trigger": 0.20,          # T 任务线索：确有任务在身
        "pain": 0.15,             # P 内部需求
        "habit": 0.15,            # H 习惯：突触成熟度
        "urgency": 0.15,          # U 紧急度：预算压力
        "effectiveness": 0.15,    # V 有效性：近期成功率
        "familiarity": 0.10,      # F 熟悉度：期望模型置信
        "reward": 0.10,           # R 奖励线索：最近成功
    })
    DRIVE_THRESHOLD = 0.70        # drive 高于此才发主动建议；冷启动≈0.5 < 0.7 ⇒ 不打扰
    # ⑧ 心理落量 Impact = P × H × U × D（乘法：四者皆大才大）
    # ⑩ 期望 EWMA
    expectation_alpha: float = 0.30
    EXPECTATION_DEFAULT = 0.50    # M0：无数据的中性期望

    def __post_init__(self) -> None:
        # 中性不变量校验（防手滑改崩冷启动）
        if abs(self.trust_alpha + self.trust_beta - 1.0) > 1e-9:
            raise ValueError("trust_alpha + trust_beta 必须为 1（中性输入时 Trust=0.5）")
        for name in ("cold_w", "heat_w", "arousal_w", "drive_w"):
            total = sum(getattr(self, name).values())
            if abs(total - 1.0) > 1e-9:
                raise ValueError(f"{name} 权重和必须为 1（当前 {total}）")


WEIGHTS = AffectWeights()


# ═══════════════════════════════════════════════════════════════
# 纯公式（无状态，可独立单测）
# ═══════════════════════════════════════════════════════════════

def pain_signal(stimulus: Any, sensitivity: Any, body_state: Any) -> float:
    """② 感受生成：pain = S × I × C。

    S 刺激强度（事件幅度）；I 个体敏感度（写类失败 > 读类失败）；
    C 身体状态修正（疲劳）。任意一端为 0 ⇒ 无痛感（乘法结构保真）。
    """
    return clamp01(stimulus) * clamp01(sensitivity) * clamp01(body_state)


def discomfort(weighted: Dict[str, Any]) -> float:
    """③ 冷/热感受：加权和后夹紧。入参 {分量名: [0,1]}。"""
    total = 0.0
    for k, v in weighted.items():
        total += clamp01(v)
    return clamp01(total)


def arousal(novelty: Any, need: Any, emotion: Any, goal: Any, memory: Any,
            weights: Optional[AffectWeights] = None) -> float:
    """④ 激活与进取欲：A = w1·S + w2·N + w3·E + w4·G + w5·M。"""
    w = (weights or WEIGHTS).arousal_w
    return clamp01(
        w["novelty"] * clamp01(novelty)
        + w["need"] * clamp01(need)
        + w["emotion"] * clamp01(emotion)
        + w["goal"] * clamp01(goal)
        + w["memory"] * clamp01(memory)
    )


def disappointment(expectation: Any, importance: Any, negative_pe: Any) -> float:
    """⑤ 期望的生成：Disappointment = E × I × (1 − PE)。

    PE 是「负面预测误差」：预期好但实际差 → PE 小 → (1−PE) 大 → 失望大；
    预期本来就差（PE 大）→ 落差小 → 失望小。符合「期望越高、摔得越疼」。
    """
    e = clamp01(expectation)
    i = clamp01(importance)
    pe = clamp01(negative_pe)
    return e * i * (1.0 - pe)


def trust_score(positive: Any, consistency: Any, fatigue: Any, boundary: Any,
                weights: Optional[AffectWeights] = None) -> float:
    """⑥ 天然惰性/信任：Trust = α·P + β·Cons − γ·V − δ·B，夹紧 [0,1]。

    中性输入 (P=0.5, Cons=0.5, V=0, B=0) ⇒ 0.5（不收缩学到的权重）。
    """
    w = weights or WEIGHTS
    raw = (
        w.trust_alpha * clamp01(positive)
        + w.trust_beta * clamp01(consistency)
        - w.trust_gamma * clamp01(fatigue)
        - w.trust_delta * clamp01(boundary)
    )
    return clamp01(raw)


def soul_drive(trigger: Any, pain_v: Any, habit: Any, urgency: Any,
               effectiveness: Any, familiarity: Any, reward: Any,
               weights: Optional[AffectWeights] = None) -> float:
    """⑦/⑨ SoulDrive 触发线索：加权和，≥ 阈值才允许主动建议。"""
    w = (weights or WEIGHTS).drive_w
    return clamp01(
        w["trigger"] * clamp01(trigger)
        + w["pain"] * clamp01(pain_v)
        + w["habit"] * clamp01(habit)
        + w["urgency"] * clamp01(urgency)
        + w["effectiveness"] * clamp01(effectiveness)
        + w["familiarity"] * clamp01(familiarity)
        + w["reward"] * clamp01(reward)
    )


def psych_impact(pain_v: Any, helplessness: Any, uncontrollability: Any,
                 duration: Any) -> float:
    """⑧ 心理落量：Impact = P × H × U × D。乘法结构：四者皆大才产生「习得性谨慎」。"""
    return (clamp01(pain_v) * clamp01(helplessness)
            * clamp01(uncontrollability) * clamp01(duration))


def update_expectation(prev: Any, actual: Any,
                       alpha: Optional[float] = None) -> float:
    """⑩ 学习与期望更新：M_{t+1} = M_t + α·(E − M_t)。EWMA，收敛到真实成功率。"""
    a = WEIGHTS.expectation_alpha if alpha is None else clamp01(alpha)
    m = clamp01(prev, neutral=WEIGHTS.EXPECTATION_DEFAULT)
    e = clamp01(actual)
    return clamp01(m + a * (e - m))


# ═══════════════════════════════════════════════════════════════
# 有状态：Agent 内心状态（单例，持久化复用 MemoryStore）
# ═══════════════════════════════════════════════════════════════

_AFFECT_KEY = "global"        # 目前是 Agent 级单状态；预留 per-session 扩展
_MAX_EXPECTATIONS = 64        # 期望模型条目上限（防膨胀）


@dataclass
class AffectState:
    """Agent 的可累积内心状态。冷启动时全部字段 = 中性值。"""

    # 累积统计（持久化）
    total_runs: int = 0
    success_runs: int = 0
    total_tool_calls: int = 0
    failed_tool_calls: int = 0
    approval_events: int = 0        # 写工具等待确认/被拒次数（边界事件 B）
    retry_like_steps: int = 0       # 同能力短窗内重复执行（重试压力）
    recent_window: List[int] = field(default_factory=list)  # 最近 N 次 run 的 0/1 成功
    # 期望模型 M：{分支 key: 期望成功率}（持久化）
    expectations: Dict[str, float] = field(default_factory=dict)
    # 最近一次快照（不持久化也行，但持久化便于控制台重启后回显）
    last: Dict[str, float] = field(default_factory=dict)

    # ─────────── 观察入口（由 agent_loop._finalize 调用） ───────────

    def observe_run(
        self,
        *,
        success: bool,
        tool_calls: int = 0,
        failed_calls: int = 0,
        approval_events: int = 0,
        retry_like: int = 0,
        budget_used_ratio: Any = 0.0,
        max_budget: int = 0,
        path: Optional[List[str]] = None,
        decision_key: str = "",
    ) -> Dict[str, float]:
        """一次 run 结束后更新内心状态，返回本次各量快照。

        决策 key 的期望更新（公式⑩）：actual = 本次成功 1/0；
        无 key 时不更新期望（不乱记）。
        """
        self.total_runs += 1
        self.success_runs += 1 if success else 0
        self.total_tool_calls += max(0, int(tool_calls))
        self.failed_tool_calls += max(0, int(failed_calls))
        self.approval_events += max(0, int(approval_events))
        self.retry_like_steps += max(0, int(retry_like))

        self.recent_window.append(1 if success else 0)
        if len(self.recent_window) > 20:
            self.recent_window = self.recent_window[-20:]

        if decision_key:
            prev = self.expectations.get(decision_key, WEIGHTS.EXPECTATION_DEFAULT)
            self.expectations[decision_key] = update_expectation(prev, 1.0 if success else 0.0)
            # 防膨胀：超出上限时丢最旧的（dict 保序）
            while len(self.expectations) > _MAX_EXPECTATIONS:
                self.expectations.pop(next(iter(self.expectations)))

        snap = self._compute(budget_used_ratio=budget_used_ratio, max_budget=max_budget)
        self.last = snap
        self._persist()
        return snap

    # ─────────── 派生量（公式②③④⑥⑧） ───────────

    def fatigue(self, budget_used_ratio: Any = 0.0) -> float:
        """C 身体状态修正：预算消耗率 + 近期失败升压。"""
        burn = clamp01(budget_used_ratio)
        window = self.recent_window[-10:]
        fail_rate = (1.0 - sum(window) / len(window)) if window else 0.0
        # 近期失败占 60%、预算燃烧占 40%（连续失败会让 Agent「更脆」）
        return clamp01(0.6 * fail_rate + 0.4 * burn)

    def sensitivity(self, wrote_kind: bool = False) -> float:
        """I 个体敏感度：写类/协作事件更敏感（把「确认后执行」红线内化为痛感）。"""
        return 0.8 if wrote_kind else 0.5

    def _compute(self, budget_used_ratio: Any = 0.0, max_budget: int = 0) -> Dict[str, float]:
        runs = max(1, self.total_runs)
        success_rate = self.success_runs / runs
        window = self.recent_window
        recent_rate = (sum(window) / len(window)) if window else WEIGHTS.EXPECTATION_DEFAULT
        recent_n = len(window)
        variance = (sum((x - recent_rate) ** 2 for x in window) / recent_n) if recent_n else 0.25
        consistency = clamp01(1.0 - math.sqrt(variance) * 2.0) if recent_n else 0.5
        fatigue = self.fatigue(budget_used_ratio)

        # ② 全局痛感：失败刺激 × 写敏感 × 疲劳
        p = pain_signal(
            stimulus=1.0 - success_rate,           # 刺激 = 失败占比
            sensitivity=0.5,                        # 全局口径取中敏感
            body_state=fatigue,
        )
        # ③ 冷热
        synapse_maturity = clamp01(min(1.0, self.total_runs / 50.0))
        cold = discomfort({
            "memory_scarcity": 1.0 - synapse_maturity,
            "budget_low": clamp01(budget_used_ratio),
            "isolated": clamp01(self.approval_events / max(1, self.approval_events + 5)),
        })
        call_density = clamp01(
            (self.total_tool_calls / runs) / max(1, max_budget or 24)
        )
        heat = discomfort({
            "call_density": call_density,
            "retry_pressure": clamp01(
                self.retry_like_steps / max(1, self.total_tool_calls)
            ),
            "budget_burn": clamp01(budget_used_ratio),
        })
        # ⑥ 信任
        trust = trust_score(
            positive=success_rate,
            consistency=consistency,
            fatigue=fatigue,
            boundary=clamp01(self.approval_events / runs),
        )
        # ⑧ 心理落量（无助=失败且重试多；不可控=期望与实际长期背离；持续=窗口内连败）
        helplessness = clamp01(
            (1.0 - recent_rate) * clamp01(self.retry_like_steps / max(1, self.total_tool_calls) * 2)
        )
        uncontrollability = clamp01(
            1.0 - abs(recent_rate - WEIGHTS.EXPECTATION_DEFAULT) * 2.0
        ) if recent_n >= 5 else 0.0   # 数据不足时不可控性记 0（不武断）
        duration = clamp01(
            (1.0 - sum(window[-5:]) / max(1, len(window[-5:]))) if window else 0.0
        )
        impact = psych_impact(p, helplessness, uncontrollability, duration)
        # ④ 激活（冷启动各输入中性/0 ⇒ A ≤ 0.5 < 0.6 阈值 ⇒ 保守）
        a = arousal(
            novelty=clamp01(1.0 - synapse_maturity),
            need=clamp01(budget_used_ratio),
            emotion=max(p, impact),
            goal=recent_rate,
            memory=synapse_maturity,
        )
        # ⑦/⑨ SoulDrive
        drive = soul_drive(
            trigger=1.0 if self.total_runs > 0 else 0.0,
            pain_v=p,
            habit=synapse_maturity,
            urgency=clamp01(budget_used_ratio),
            effectiveness=recent_rate,
            familiarity=clamp01(consistency),
            reward=recent_rate,
        )
        return {
            "pain": round(p, 4),
            "cold": round(cold, 4),
            "heat": round(heat, 4),
            "arousal": round(a, 4),
            "trust": round(trust, 4),
            "drive": round(drive, 4),
            "impact": round(impact, 4),
            "fatigue": round(fatigue, 4),
            "success_rate": round(success_rate, 4),
            "recent_rate": round(recent_rate, 4),
            "mode": "aggressive" if a >= WEIGHTS.AROUSAL_THRESHOLD else "conservative",
            "proactive": drive >= WEIGHTS.DRIVE_THRESHOLD and impact < 0.5,
        }

    # ─────────── 决策接口 ───────────

    def trust_factor(self) -> float:
        """信任 → 突触权重收缩因子 ∈ [0.5, 1.0]。

        trust=0.5（中性）→ 1.0：学到的权重原样生效（与现在完全一致）；
        trust<0.5 → 向 0.5 收缩（低信任时少信历史）；下限 0.5（保留一半，不归零）。
        """
        t = self.last.get("trust", 0.5)
        return clamp01(0.5 + clamp01(t, neutral=0.5), neutral=1.0)

    def current_trust(self) -> float:
        """当前信任值 [0,1]；无数据 → 中性 0.5（suggest_next 语义 = 不干预）。"""
        return clamp01(self.last.get("trust", 0.5), neutral=0.5)

    def suggest_mode(self) -> str:
        """进取/保守模式（仅影响「建议的激进程度」，永不自动执行写操作）。"""
        return str(self.last.get("mode", "conservative"))

    def allow_proactive(self) -> bool:
        """是否允许主动建议（SoulDrive 门控 + 心理落量刹车）。"""
        return bool(self.last.get("proactive", False))

    def expectation_of(self, key: str) -> float:
        """查询某分支的期望成功率（无数据 → 中性 0.5）。"""
        return clamp01(self.expectations.get(key, WEIGHTS.EXPECTATION_DEFAULT),
                       neutral=WEIGHTS.EXPECTATION_DEFAULT)

    # ─────────── 序列化 / 持久化 / 快照 ───────────

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_runs": self.total_runs,
            "success_runs": self.success_runs,
            "total_tool_calls": self.total_tool_calls,
            "failed_tool_calls": self.failed_tool_calls,
            "approval_events": self.approval_events,
            "retry_like_steps": self.retry_like_steps,
            "recent_window": list(self.recent_window),
            "expectations": dict(self.expectations),
            "last": dict(self.last),
        }

    def snapshot(self) -> Dict[str, Any]:
        """控制台快照：统计 + 派生内心量 + 门控结论。"""
        out = self.to_dict()
        out["weights"] = {
            "trust_alpha": WEIGHTS.trust_alpha, "trust_beta": WEIGHTS.trust_beta,
            "trust_gamma": WEIGHTS.trust_gamma, "trust_delta": WEIGHTS.trust_delta,
            "arousal_threshold": WEIGHTS.AROUSAL_THRESHOLD,
            "drive_threshold": WEIGHTS.DRIVE_THRESHOLD,
            "expectation_alpha": WEIGHTS.expectation_alpha,
        }
        return out

    def restore(self, data: Dict[str, Any]) -> None:
        """从持久化数据恢复（字段逐一容错）。"""
        if not isinstance(data, dict):
            return
        try:
            self.total_runs = int(data.get("total_runs") or 0)
            self.success_runs = int(data.get("success_runs") or 0)
            self.total_tool_calls = int(data.get("total_tool_calls") or 0)
            self.failed_tool_calls = int(data.get("failed_tool_calls") or 0)
            self.approval_events = int(data.get("approval_events") or 0)
            self.retry_like_steps = int(data.get("retry_like_steps") or 0)
            rw = data.get("recent_window")
            self.recent_window = [1 if int(x) else 0 for x in rw][-20:] if isinstance(rw, list) else []
            exp = data.get("expectations")
            if isinstance(exp, dict):
                self.expectations = {
                    str(k)[:64]: clamp01(v, neutral=0.5)
                    for k, v in list(exp.items())[:_MAX_EXPECTATIONS]
                }
            last = data.get("last")
            if isinstance(last, dict):
                self.last = {str(k): clamp01(v, neutral=0.5) if isinstance(v, (int, float)) else v
                             for k, v in last.items()}
        except Exception:
            return

    def _persist(self) -> None:
        """持久化到 MemoryStore（category=brain_affect，key=global），失败静默降级。"""
        try:
            from app.core.memory_store import memory_store
            memory_store.record(
                category="brain_affect",
                content={"key": _AFFECT_KEY, **self.to_dict()},
                tags=["affect", "brain", _AFFECT_KEY],
                score=self.last.get("trust", 0.5),
            )
        except Exception:
            logger.debug("忽略异常（原为 pass）: affect_model.py", exc_info=True)

    def load(self) -> None:
        """启动时恢复最近一条内心状态（只调一次）。"""
        try:
            from app.core.memory_store import memory_store
            entries = memory_store.latest_per_key(
                category="brain_affect", key_fields=("key",), limit=1
            )
            for e in entries:
                content = getattr(e, "content", None)
                if isinstance(content, dict) and content.get("key") == _AFFECT_KEY:
                    self.restore(content)
                break
        except Exception:
            logger.debug("忽略异常（原为 pass）: affect_model.py", exc_info=True)


# 模块级单例
agent_affect = AffectState()
