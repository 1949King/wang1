"""
Agent 左右脑神经链接引擎
=========================
将内置 capability 注册为"神经元"，按左右脑分工（创意/逻辑/混合），
通过 Hebbian 学习规则强化突触权重，实现联想调用与左右脑协同思考。

设计原则：
- 不修改任何既有 capability 调用路径
- 所有调用点 try/except 静默降级
- 突触权重持久化复用 MemoryStore（category=brain_synapse）
- 单例模式，模块加载即初始化

类比映射：
- 神经元 = capability_id
- 突触 = Synapse(pre → post, weight)
- 神经递质 = EventBus 信号 + MemoryStore 记忆
- 激活函数 = top-K 相似度 + 阈值 0.5 + 时间衰减
- 学习 = Hebbian 规则：同时激活的神经元突触权重 +Δ
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 数据结构定义
# ═══════════════════════════════════════════════════════════════

class BrainHemisphere(Enum):
    """大脑半球归属枚举。"""
    LEFT = "left"            # 左脑：逻辑/分析/执行
    RIGHT = "right"          # 右脑：创意/生成/想象
    CORPUS_CALLOSUM = "cc"   # 胼胝体：混合/协同


@dataclass
class Neuron:
    """神经元：对应一个 capability_id。

    属性：
        neuron_id: 神经元 ID（等于 capability_id）
        hemisphere: 左右脑归属
        label: 中文标签（用于关键词匹配与 UI 显示）
        activation: 当前激活值 [0.0, 1.0]
        last_fired: 最近一次激活的时间戳
    """
    neuron_id: str
    hemisphere: BrainHemisphere
    label: str
    activation: float = 0.0
    last_fired: float = 0.0


@dataclass
class Synapse:
    """突触：两个神经元之间的连接。

    属性：
        pre: 前神经元 ID
        post: 后神经元 ID
        weight: 突触权重 [0.0, 1.0]，越高越容易联动激活
        fire_count: 历史共同激活次数
        last_reinforced: 最近一次强化时间戳
    """
    pre: str
    post: str
    weight: float = 0.5
    fire_count: int = 0
    last_reinforced: float = 0.0


# ═══════════════════════════════════════════════════════════════
# 内置 capability 的左右脑分类表（与 capability_handlers 对齐）
# ═══════════════════════════════════════════════════════════════

# 格式: (capability_id, hemisphere(字符串), 中文标签, 关键词列表)
# 单一事实来源：app/core/agent_capability_catalog.py（neuron_taxonomy）。
# 此前这里是硬编码 27 个神经元、且漏了 9 个已注册能力（靠 sync_from_dispatcher
# 兜底成无标签的胼胝体神经元）。现从目录派生，hemisphere 用字符串、由
# _init_neuron_taxonomy 转成 BrainHemisphere 枚举，避免本模块 import 目录层造成循环。
from app.core.agent_capability_catalog import neuron_taxonomy

_NEURON_TAXONOMY: List[Tuple[str, str, str, List[str]]] = neuron_taxonomy()

_HEMI_MAP = {
    "right": BrainHemisphere.RIGHT,
    "left": BrainHemisphere.LEFT,
    "cc": BrainHemisphere.CORPUS_CALLOSUM,
}


# ═══════════════════════════════════════════════════════════════
# AgentBrain 单例
# ═══════════════════════════════════════════════════════════════

class AgentBrain:
    """Agent 左右脑神经链接引擎。

    职责：
    1. 把内置 capability 注册为神经元，标记左右脑归属
    2. 维护神经元之间的突触权重（联想调用的基础）
    3. 通过 Hebbian 规则学习（成功 +Δ，失败 -Δ）
    4. 提供左右脑协同思考接口（胼胝体）
    5. 突触权重持久化到 MemoryStore
    """

    _instance: Optional["AgentBrain"] = None
    _lock: Any = None  # 类级锁，延迟初始化（避免 import 时拉起 threading）

    # 学习参数
    _DEFAULT_DELTA = 0.05        # 默认学习步长
    _DEFAULT_DECAY = 0.7         # 激活扩散衰减系数
    _ACTIVATION_THRESHOLD = 0.5  # 突触激活阈值
    _MAX_SPREAD = 3              # 单次激活最多扩散到几个神经元
    _MAX_SYNAPSES = 500          # 突触数量上限（防膨胀）

    def __new__(cls):
        if cls._instance is None:
            import threading
            if cls._lock is None:
                cls._lock = threading.Lock()
            with cls._lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._initialized = False
                    cls._instance = inst
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self._neurons: Dict[str, Neuron] = {}
        self._synapses: Dict[Tuple[str, str], Synapse] = {}
        self._loaded: bool = False
        self._init_neuron_taxonomy()
        # 修复：此前只写不读——reinforce_path 每次都持久化突触，但从没有调用方
        # 在启动时调回 load_synapses()，导致每次重启"长期记忆"实际上都是空的。
        self.load_synapses()

    # ─────────────── 神经元注册 ───────────────

    def _init_neuron_taxonomy(self) -> None:
        """初始化神经元（按 _NEURON_TAXONOMY 表注册）。"""
        for nid, hemi, label, _kw in _NEURON_TAXONOMY:
            self._neurons[nid] = Neuron(
                neuron_id=nid,
                hemisphere=_HEMI_MAP.get(hemi, BrainHemisphere.CORPUS_CALLOSUM),
                label=label,
            )
        logger.debug(f"[AgentBrain] 注册 {len(self._neurons)} 个神经元")

    def sync_from_dispatcher(self, dispatcher) -> None:
        """从 CapabilityDispatcher 同步已注册的 capability（只增不删）。"""
        try:
            listed = dispatcher.list_capabilities() if hasattr(dispatcher, "list_capabilities") else []
            existing = set(listed)
            # 只记录 dispatcher 有但 brain 没有的（避免覆盖分类）
            unknown = existing - set(self._neurons.keys())
            for nid in unknown:
                # 未知 capability 默认归胼胝体
                self._neurons[nid] = Neuron(
                    neuron_id=nid,
                    hemisphere=BrainHemisphere.CORPUS_CALLOSUM,
                    label=nid,
                )
                logger.debug(f"[AgentBrain] 同步未知能力为神经元: {nid}")
        except Exception as e:
            logger.debug(f"[AgentBrain] sync_from_dispatcher 失败: {e}")

    # ─────────────── 激活与扩散 ───────────────

    def activate(self, neuron_id: str, context: Optional[Dict] = None,
                 strength: float = 1.0) -> List[str]:
        """激活一个神经元，沿突触扩散到相关神经元（联想调用）。

        Args:
            neuron_id: 起始神经元 ID
            context: 激活上下文（用于持久化）
            strength: 初始激活强度 [0,1]

        Returns:
            被激活的神经元 ID 列表（包括起始神经元）
        """
        if neuron_id not in self._neurons:
            return []
        now = time.time()
        n = self._neurons[neuron_id]
        n.activation = max(n.activation, min(1.0, strength))
        n.last_fired = now

        fired = [neuron_id]
        # 找出所有从该神经元出发的突触，按权重降序
        candidates: List[Tuple[str, float]] = []
        for (pre, post), syn in self._synapses.items():
            if pre == neuron_id and syn.weight >= self._ACTIVATION_THRESHOLD:
                candidates.append((post, syn.weight))
        candidates.sort(key=lambda x: -x[1])

        # 取 top-K 扩散
        for post_id, w in candidates[:self._MAX_SPREAD]:
            if post_id in self._neurons:
                self._neurons[post_id].activation = w * strength * self._DEFAULT_DECAY
                self._neurons[post_id].last_fired = now
                fired.append(post_id)

        logger.debug(f"[AgentBrain] 激活链: {' -> '.join(fired)}")
        return fired

    def decay_all(self, factor: float = 0.9) -> None:
        """全局激活值衰减（避免激活值永久残留）。"""
        for n in self._neurons.values():
            n.activation *= factor

    # ─────────────── 学习（Hebbian 规则） ───────────────

    def reinforce_path(self, path: List[str], success: bool,
                       delta: float = _DEFAULT_DELTA) -> None:
        """强化一条链路上的突触（pipeline 完成时调用）。

        Hebbian 规则：同时激活的神经元突触权重 +Δ（成功）/ -Δ（失败）。

        Args:
            path: 神经元 ID 序列（如 ["pipeline.route", "pipeline.generate", ...]）
            success: 是否成功
            delta: 权重调整步长
        """
        if len(path) < 2:
            return
        now = time.time()
        for pre, post in zip(path[:-1], path[1:]):
            key = (pre, post)
            if key not in self._synapses:
                # 突触数量超限时跳过新建
                if len(self._synapses) >= self._MAX_SYNAPSES:
                    continue
                self._synapses[key] = Synapse(pre=pre, post=post, weight=0.5)
            syn = self._synapses[key]
            if success:
                syn.weight = min(1.0, syn.weight + delta)
            else:
                syn.weight = max(0.0, syn.weight - delta)
            syn.fire_count += 1
            syn.last_reinforced = now
        self._persist_synapses()
        logger.debug(
            f"[AgentBrain] 链路强化 path={path} success={success} "
            f"delta={delta} 总突触={len(self._synapses)}"
        )

    def learn_from_feedback(self, feedback: Dict[str, Any]) -> None:
        """反馈桥调用：根据反馈调整权重。

        Args:
            feedback: 反馈字典，可包含字段：
                - type: 反馈类型（quality/success/preview_issue）
                - related_capabilities: 相关 capability_id 列表
                - severity: 严重程度（low/medium/high）
        """
        try:
            issue_type = feedback.get("type", "")
            related = feedback.get("related_capabilities", []) or []
            severity = feedback.get("severity", "low")

            # 根据严重程度调整 delta
            sev_delta = {"low": 0.02, "medium": 0.04, "high": 0.08}.get(severity, 0.03)

            if issue_type in ("quality", "preview_issue"):
                # 质量问题：弱化相关链路
                self.reinforce_path(related, success=False, delta=sev_delta)
            elif issue_type == "success":
                # 成功反馈：强化相关链路
                self.reinforce_path(related, success=True, delta=sev_delta)
            else:
                # 其他类型：默认弱学习
                if related:
                    self.reinforce_path(related, success=True, delta=0.01)
        except Exception as e:
            logger.debug(f"[AgentBrain] learn_from_feedback 失败: {e}")

    # ─────────────── 左右脑协同思考 ───────────────

    def right_brain_think(self, task: str, context: Optional[Dict] = None) -> List[str]:
        """右脑思考：根据任务激活创意类神经元，返回推荐 capability 序列。

        Args:
            task: 用户任务描述
            context: 思考上下文

        Returns:
            推荐激活的右脑神经元 ID 列表（按匹配度降序）
        """
        candidates = [n for n in self._neurons.values()
                      if n.hemisphere == BrainHemisphere.RIGHT]
        scored = [(n, self._match_score(task, n)) for n in candidates]
        scored.sort(key=lambda x: -x[1])
        result = [n.neuron_id for n, s in scored[:3] if s > 0.3]
        logger.debug(f"[AgentBrain] 右脑思考 task='{task[:30]}' → {result}")
        return result

    def left_brain_think(self, task: str, context: Optional[Dict] = None) -> List[str]:
        """左脑思考：根据任务激活逻辑类神经元。"""
        candidates = [n for n in self._neurons.values()
                      if n.hemisphere == BrainHemisphere.LEFT]
        scored = [(n, self._match_score(task, n)) for n in candidates]
        scored.sort(key=lambda x: -x[1])
        result = [n.neuron_id for n, s in scored[:3] if s > 0.3]
        logger.debug(f"[AgentBrain] 左脑思考 task='{task[:30]}' → {result}")
        return result

    def correlate(self, task: str, context: Optional[Dict] = None) -> Dict[str, Any]:
        """胼胝体协同：左右脑联合思考，返回完整执行计划。

        Args:
            task: 用户任务描述
            context: 思考上下文

        Returns:
            Dict 包含:
                - right_brain_plan: 右脑推荐 capability 列表
                - left_brain_plan: 左脑推荐 capability 列表
                - correlation_strength: 左右脑协同强度 [0,1]
                - merged_plan: 合并后的完整执行计划
        """
        right = self.right_brain_think(task, context)
        left = self.left_brain_think(task, context)
        corr = self._calc_correlation(right, left)

        # 合并计划：右脑创意先行，左脑逻辑跟进
        merged = right + [c for c in left if c not in right]

        return {
            "right_brain_plan": right,
            "left_brain_plan": left,
            "correlation_strength": corr,
            "merged_plan": merged,
        }

    def _match_score(self, task: str, neuron: Neuron) -> float:
        """任务-神经元匹配评分（基于关键词，避免引入 embedding 依赖）。

        Args:
            task: 用户任务描述
            neuron: 神经元对象

        Returns:
            匹配评分 [0.0, 1.0]
        """
        if not task:
            return 0.0
        task_lower = task.lower()

        # 从 _NEURON_TAXONOMY 找到该神经经元的关键词列表
        keywords: List[str] = []
        for nid, _, _, kw in _NEURON_TAXONOMY:
            if nid == neuron.neuron_id:
                keywords = kw
                break

        # 关键词命中数 → 评分
        hits = 0
        for kw in keywords:
            if kw.lower() in task_lower:
                hits += 1
        if hits == 0:
            return 0.1  # 默认低分
        return min(1.0, 0.4 + 0.2 * hits)

    def _calc_correlation(self, right: List[str], left: List[str]) -> float:
        """计算左右脑协同强度（基于突触连接数）。"""
        if not right or not left:
            return 0.0
        connections = 0
        for r in right:
            for l in left:
                if (r, l) in self._synapses or (l, r) in self._synapses:
                    connections += 1
        max_possible = len(right) * len(left)
        return connections / max_possible if max_possible > 0 else 0.0

    # ─────────────── 决策咨询：把学到的权重用回路径选择 ───────────────
    #
    # 这是学习回路此前缺失的最后一步：
    #   invoke → activate → reinforce_path 写权重 → 【此处】用权重选分支 → 结果再 reinforce
    # 设计要点：
    #   1. 无数据时所有候选权重 = _NEUTRAL_WEIGHT(0.5)，且 default 排在候选首位，
    #      稳定排序保证平票时选中 default ⇒ **冷启动行为与「没有大脑」完全一致**。
    #   2. 不做 ε 随机探索：本项目拒绝随机效果，宁可冷启动保守，也不引入不可复现的抖动。

    _NEUTRAL_WEIGHT = 0.5  # 与 Synapse.weight 默认值一致：未学过的分支按中性处理

    def synapse_weight(self, pre: str, post: str) -> Optional[float]:
        """查询突触权重；无记录返回 None（与「学到 0.5」区分开）。"""
        syn = self._synapses.get((pre, post))
        if syn is None:
            return None
        return float(syn.weight)

    def score_candidates(self, from_id: str,
                         candidates: List[str]) -> List[Tuple[str, float, bool]]:
        """给候选后继打分：返回 [(cand, weight, learned)]，按权重降序（平票保持传入次序）。"""
        out: List[Tuple[str, float, bool]] = []
        for cand in candidates or []:
            w = self.synapse_weight(from_id, cand)
            out.append((cand, self._NEUTRAL_WEIGHT if w is None else w, w is not None))
        out.sort(key=lambda x: -x[1])  # 稳定排序 ⇒ 平票保持传入次序
        return out

    def suggest_next(self, from_id: str, candidates: List[str],
                     default: Optional[str] = None,
                     trust: Optional[float] = None) -> Dict[str, Any]:
        """在候选后继里选一个：权重最高者胜；无学习数据则回退 default（= 既有行为）。

        Args:
            from_id: 当前所处的 capability_id（决策点）
            candidates: 候选后继 capability_id 列表
            default: 无差异时的默认选择（**必须传「现状行为」**，保证冷启动不改变行为）
            trust: 可选，内心状态（affect_model）给出的信任值 [0,1]。
                中性 0.5 ⇒ 不收缩（行为与未传时一致）；< 0.5 ⇒ 学到的权重向
                中性 0.5 收缩（低信任时少信历史）；None ⇒ 完全不干预（冷启动）。

        Returns:
            Dict: from / choice / default / changed / learned / weights / reason
        """
        cands = [c for c in (candidates or []) if c]
        if not cands:
            return {"from": from_id, "choice": None, "default": None, "changed": False,
                    "learned": False, "weights": {}, "reason": "无候选分支"}

        # default 置顶：稳定排序下平票必然选中它
        default_id = default if default in cands else cands[0]
        ordered = [default_id] + [c for c in cands if c != default_id]

        # 信任收缩（内心状态接入点，2026-09-15）：
        # factor = clamp(0.5 + trust, 0.5, 1.0) —— trust=0.5 → 1.0（原样生效）；
        # trust 低 → 学到的偏差减半向 0.5 收缩；不放大（trust 高也不超过 1.0，不冒险）。
        factor = 1.0
        if trust is not None:
            try:
                t = max(0.0, min(1.0, float(trust)))
            except (TypeError, ValueError):
                t = 0.5
            factor = max(0.5, min(1.0, 0.5 + t))
        ranked = [
            (c,
             self._NEUTRAL_WEIGHT + (w - self._NEUTRAL_WEIGHT) * factor if learned else w,
             learned)
            for c, w, learned in self.score_candidates(from_id, ordered)
        ]
        choice, best_w, _ = ranked[0]
        weights = {c: round(w, 4) for c, w, _l in ranked}
        learned = any(l for _c, _w, l in ranked)
        changed = choice != default_id

        if not learned:
            reason = f"无学习数据，沿用默认 {default_id}"
        elif changed:
            reason = (f"历史权重 {choice}={best_w:.3f} 高于默认 "
                      f"{default_id}={weights.get(default_id, 0.0):.3f}，改走 {choice}")
        else:
            reason = f"历史权重最高的仍是默认 {default_id}（{best_w:.3f}）"

        logger.debug(f"[AgentBrain] 决策咨询 from={from_id} → {choice}（{reason}）")
        return {
            "from": from_id,
            "choice": choice,
            "default": default_id,
            "changed": changed,
            "learned": learned,
            "weights": weights,
            "reason": reason,
        }

    # ─────────────── 持久化 ───────────────

    def _persist_synapses(self) -> None:
        """突触权重持久化到 MemoryStore（category=brain_synapse）。

        修复（此前从未真正生效的 bug）：
        1. ``MemoryStore.record()`` 签名里没有 ``metadata`` 形参——旧代码每次调用都会
           抛 ``TypeError``，被外层 ``except Exception`` 静默吞掉，导致突触**从未**
           被写盘成功，"长期记忆"名不副实。
        2. ``content`` 字段类型是 ``Dict[str, Any]``，旧代码却传入了一个字符串
           ``f"{pre}->{post}"``，与读取端 ``load_synapses()`` 的解析逻辑也对不上。
        现改为把 pre/post/weight/fire_count 都放进 ``content`` 字典里。
        """
        try:
            from app.core.memory_store import memory_store
            now = time.time()
            for (pre, post), syn in self._synapses.items():
                memory_store.record(
                    category="brain_synapse",
                    content={
                        "pre": pre,
                        "post": post,
                        "weight": syn.weight,
                        "fire_count": syn.fire_count,
                        "last_reinforced": syn.last_reinforced,
                        "updated_at": now,
                    },
                    tags=[pre, post, "synapse", "brain"],
                    score=syn.weight,
                )
        except Exception as e:
            logger.debug(f"[AgentBrain] 突触持久化失败: {e}")

    def load_synapses(self) -> None:
        """启动时从 MemoryStore 加载历史突触权重（只调用一次）。"""
        if self._loaded:
            return
        self._loaded = True
        try:
            from app.core.memory_store import memory_store
            # 同一突触每次持久化都会新增一条记录；query 按 score 降序返回 + 循环后写覆盖，
            # 会保留「分数最低的旧版本」——强化过的权重重启后退回最弱版（2026-09-13 修正）。
            # latest_per_key 按 (pre, post) 去重、取 timestamp 最新的一条，不受排序影响。
            entries = memory_store.latest_per_key(
                category="brain_synapse", key_fields=("pre", "post"), limit=200
            )
            loaded = 0
            for e in entries:
                try:
                    content = e.content or {}
                    if not isinstance(content, dict):
                        continue
                    pre = str(content.get("pre") or "").strip()
                    post = str(content.get("post") or "").strip()
                    if not pre or not post:
                        continue
                    key = (pre, post)
                    weight = content.get("weight", getattr(e, "score", 0.5))
                    fire_count = content.get("fire_count", 0)
                    self._synapses[key] = Synapse(
                        pre=pre, post=post,
                        weight=float(weight),
                        fire_count=int(fire_count),
                        last_reinforced=float(content.get("last_reinforced", 0.0) or 0.0),
                    )
                    loaded += 1
                except Exception:
                    continue
            logger.info(f"[AgentBrain] 从 MemoryStore 加载 {loaded} 个突触")
        except Exception as e:
            logger.debug(f"[AgentBrain] 突触加载失败: {e}")

    # ─────────────── 状态查询（供 UI 显示） ───────────────

    def get_brain_status(self) -> Dict[str, Any]:
        """获取大脑状态摘要（供 UI 显示）。

        Returns:
            Dict 包含:
                - total_neurons: 神经元总数
                - total_synapses: 突触总数
                - right_brain_count: 右脑神经元数
                - left_brain_count: 左脑神经元数
                - cc_count: 胼胝体神经元数
                - active_neurons: 当前激活的神经元 ID 列表
                - top_synapses: 权重最高的 5 个突触
        """
        right_count = sum(1 for n in self._neurons.values()
                          if n.hemisphere == BrainHemisphere.RIGHT)
        left_count = sum(1 for n in self._neurons.values()
                         if n.hemisphere == BrainHemisphere.LEFT)
        cc_count = sum(1 for n in self._neurons.values()
                       if n.hemisphere == BrainHemisphere.CORPUS_CALLOSUM)
        active = [n.neuron_id for n in self._neurons.values()
                  if n.activation > 0.3]
        top_syns = sorted(
            [{"pre": s.pre, "post": s.post, "weight": round(s.weight, 3),
              "fire_count": s.fire_count}
             for s in self._synapses.values()],
            key=lambda x: -x["weight"]
        )[:5]
        return {
            "total_neurons": len(self._neurons),
            "total_synapses": len(self._synapses),
            "right_brain_count": right_count,
            "left_brain_count": left_count,
            "cc_count": cc_count,
            "active_neurons": active,
            "top_synapses": top_syns,
        }

    def get_neuron(self, neuron_id: str) -> Optional[Neuron]:
        """获取神经元对象（只读）。"""
        return self._neurons.get(neuron_id)

    def list_neurons_by_hemisphere(self, hemi: BrainHemisphere) -> List[Neuron]:
        """按半球列出神经元。"""
        return [n for n in self._neurons.values() if n.hemisphere == hemi]


# ═══════════════════════════════════════════════════════════════
# 模块级单例
# ═══════════════════════════════════════════════════════════════

agent_brain = AgentBrain()
