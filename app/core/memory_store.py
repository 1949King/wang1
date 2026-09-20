"""
长期记忆 & 自主学习 (MemoryStore)
================================
单例。内存 FIFO(5000) + JSONL 持久化，关键词/标签召回，命中即巩固。
不依赖重型 ML 库；如未来需要向量检索可接入 neural_engine。

记忆类别：
  - execution_trace: 能力调用 trace（成功/失败）
  - feedback: 发布效果反馈
  - learned_rule: 自主学习提炼的规则（3条同模式 feedback 自动合成）
  - strategy_adjustment: 策略调整记录
  - user_preference: 用户偏好
  - project_context: 当前剧名/集数/平台备注（Dify 式「应用变量」轻量版）
  - episode_note: 某一集剪辑备忘
"""
from __future__ import annotations
import json
import logging
import math
import os
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_MAX_IN_MEMORY = 5000
# 存储路径基于本文件定位（项目根/data），与启动时的工作目录无关。
# 旧实现是相对 CWD 的 "data/agent_memory.jsonl"——从其他目录启动会写到别处，
# 造成「记忆在这里、程序读那里」的静默分裂。
_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_STORAGE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(_MODULE_DIR)), "data", "agent_memory.jsonl"
)
_COMPRESS_THRESHOLD = 5 * 1024 * 1024  # 5MB

# ── 记忆强度：动态衰减 + 召回强化 ──
#
# 与 app/core/ai/memory_model.py **同源**（同一套指数衰减形式 λ = λ0·(1-α·C)），
# 但参数体系不同，不要混用：
#   memory_model 描述**观众**对片段的记忆 —— 小时级衰减；
#   这里描述**系统**对经验的记忆 —— 天级衰减，λ0 小两个数量级。
# 两处尚未抽成共用层，改任一处请同步核对另一处。
_STRENGTH_LAMBDA0 = 0.001      # 基准衰减率（每小时）→ 30 天约剩 0.49
_RECALL_SATURATION = 10        # 召回满多少次算「充分巩固」
_STRENGTH_ALPHA = 0.6          # 召回对衰减的抑制强度

# 排序开关。默认 False = 保持既有「静态 score」排序（只记账、不改行为）。
# 打开方式：环境变量 SHIGUANG_MEMORY_STRENGTH=1，或 set_strength_ranking(True)。
_USE_STRENGTH_RANKING = os.getenv("SHIGUANG_MEMORY_STRENGTH", "0") == "1"


def set_strength_ranking(enabled: bool) -> None:
    """运行时切换强度排序；默认关（保持既有行为，只记账）。"""
    global _USE_STRENGTH_RANKING
    _USE_STRENGTH_RANKING = bool(enabled)

# 压缩时无条件保留的类别（与 score 无关）
_KEEP_CATEGORIES = (
    "feedback", "learned_rule", "strategy_adjustment",
    "user_preference", "project_context", "episode_note",
)
# trace 的「近期失败」是 get_agent_context 的固定来源，
# 而 trace 的 score 只有 0.4 —— 若只按 score 压缩会被整体清空。
_KEEP_TRACE_WITH_ERROR = True


@dataclass
class MemoryEntry:
    """记忆条目"""
    entry_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    category: str = ""                       # execution_trace / strategy_adjustment / feedback / learned_rule / user_preference
    content: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    tags: List[str] = field(default_factory=list)
    score: float = 0.0                       # 写入权重（静态，不再随使用变化）
    # ── 动态部分：让「被用过的记忆」比「写完就没人碰的」更耐忘 ──
    # score 是写入时的判断；current_strength() 才是「此刻还值不值得注入」。
    recall_count: int = 0                    # 被注入 Agent 上下文的次数（= 巩固程度 C）
    last_recalled: float = 0.0               # 最近一次被注入的时间（衰减起点）


class MemoryStore:
    """
    长期记忆存储 —— 线程安全单例

    使用方式：
        from app.core.memory_store import memory_store
        memory_store.record(category="feedback", content={...}, tags=["douyin"], score=0.85)
        ctx = memory_store.get_agent_context(top_k=5)  # 注入 Agent system prompt
    """
    _instance: Optional['MemoryStore'] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._entries: 'OrderedDict[str, MemoryEntry]' = OrderedDict()
        self._lock = threading.RLock()
        self._load()

    @classmethod
    def get_instance(cls) -> 'MemoryStore':
        return cls()

    def record(self, category: str, content: Dict[str, Any],
               tags: Optional[List[str]] = None, score: float = 0.0) -> str:
        """
        记录一条记忆，返回 entry_id

        参数：
            category: 记忆类别
            content: 记忆内容（dict）
            tags: 检索标签
            score: 召回权重（0~1，越高越优先召回）
        """
        entry = MemoryEntry(category=category, content=content,
                            tags=list(tags or []), score=score)
        with self._lock:
            self._entries[entry.entry_id] = entry
            # 超限淘汰最早写入的条目（实现是 FIFO：插入顺序无 move_to_end，
            # 旧注释写的 "LRU" 与实现不符，2026-09-13 修正注释）
            if len(self._entries) > _MAX_IN_MEMORY:
                self._entries.popitem(last=False)
        self._append_to_disk(entry)
        return entry.entry_id

    # ─────────────── 强度：时间衰减 + 召回强化 ───────────────

    @staticmethod
    def strength_at(entry: MemoryEntry, now: Optional[float] = None) -> float:
        """条目在 ``now`` 时刻的「当前强度」，0~1。

        strength = score · e^(-λ·t)，λ = λ0 · (1 - α·C)
        其中 C = min(recall_count / _RECALL_SATURATION, 1)

        语义：**写入权重决定起点，被用过多少次决定它能撑多久。**
        反复被注入的记忆衰减得慢；写完从没被用过的会自然沉底。
        （与 memory_model 同一套形式，参数体系不同，见文件头注释。）
        """
        base = max(0.0, min(1.0, float(entry.score or 0.0)))
        if base <= 0.0:
            return 0.0
        now_ts = time.time() if now is None else float(now)
        anchor = float(entry.last_recalled or 0.0) or float(entry.timestamp or now_ts)
        hours = max(0.0, (now_ts - anchor) / 3600.0)
        consolidation = min(
            1.0, float(entry.recall_count or 0) / float(_RECALL_SATURATION)
        )
        rate = max(_STRENGTH_LAMBDA0 * (1.0 - _STRENGTH_ALPHA * consolidation), 1e-6)
        return base * math.exp(-rate * hours)

    def reinforce(self, entry_ids: List[str], *, now: Optional[float] = None) -> int:
        """把条目标记为「被用过」= 强化（recall_count +1，刷新衰减起点）。

        只对**真正被注入**的条目调用，而不是所有被 query 扫到的条目 ——
        否则召回次数会虚高，失去「常用 vs 没人碰」的区分度。
        """
        now_ts = time.time() if now is None else float(now)
        touched: List[MemoryEntry] = []
        with self._lock:
            for eid in entry_ids:
                entry = self._entries.get(eid)
                if entry is None:
                    continue
                entry.recall_count = int(entry.recall_count or 0) + 1
                entry.last_recalled = now_ts
                touched.append(entry)
        # 落盘放在锁外，避免持锁做 IO
        # 同一 entry_id 的后续行会在 _load 时覆盖前一行，等价于更新
        for entry in touched:
            self._append_to_disk(entry)
        return len(touched)

    def latest_per_key(
        self,
        category: str,
        key_fields: tuple = ("pre", "post"),
        *,
        limit: Optional[int] = None,
    ) -> List[MemoryEntry]:
        """按逻辑键去重，每个键只返回 **timestamp 最新** 的一条。

        用于「同一对象被反复持久化成多条记录」的场景（典型：brain_synapse
        每次持久化都为每个突触新增一条）。直接 query 会因 score 排序 + limit
        截断而拿到**旧的或最弱的**版本，本方法按时间取最新，不受排序影响。
        """
        with self._lock:
            entries = [e for e in self._entries.values() if e.category == category]
        latest: Dict[tuple, MemoryEntry] = {}
        for entry in entries:
            content = entry.content if isinstance(entry.content, dict) else {}
            key = tuple(str(content.get(f) or "") for f in key_fields)
            if not any(key):
                continue
            current = latest.get(key)
            if current is None or float(entry.timestamp or 0.0) > float(current.timestamp or 0.0):
                latest[key] = entry
        rows = sorted(latest.values(), key=lambda e: float(e.timestamp or 0.0), reverse=True)
        return rows[:limit] if limit else rows

    def propose_user_preference(
        self,
        content: Dict[str, Any],
        *,
        mode: str = "collaborative",
        approved: bool = False,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """B 需确认、C 自动写入；Plan 拒绝。禁止密钥/绝对路径/全文。"""
        from app.core.agent_policy import (
            DECISION_ALLOW,
            DECISION_DENY,
            decide,
            memory_content_allowed,
        )

        ok, reason = memory_content_allowed(content if isinstance(content, dict) else {})
        if not ok:
            return {"ok": False, "message": reason, "require_approval": False}
        decision = decide(tool_id="memory.suggest", mode=mode, approved=approved)
        if decision.action == DECISION_DENY:
            return {"ok": False, "message": decision.reason, "require_approval": False}
        if decision.action != DECISION_ALLOW:
            return {
                "ok": False,
                "message": decision.reason,
                "require_approval": True,
                "suggestion": content,
            }
        eid = self.record(
            category="user_preference",
            content=content,
            tags=list(tags or ["preference"]),
            score=0.8,
        )
        return {"ok": True, "entry_id": eid}

    def query(self, category: Optional[str] = None,
              tags: Optional[List[str]] = None,
              keyword: Optional[str] = None,
              limit: int = 10) -> List[MemoryEntry]:
        """
        检索记忆：按 category + tags + 关键词交集

        默认按 score 降序 + 时间近因排序（既有行为，未开开关时完全不变）；
        set_strength_ranking(True) 或环境变量 SHIGUANG_MEMORY_STRENGTH=1 时
        改按 strength_at（时间衰减 × 召回巩固）排序。
        注意：命中不等于强化——只有真正被注入 Agent 的条目才 reinforce（见 get_agent_context）。
        """
        with self._lock:
            entries = list(self._entries.values())
        result = []
        for e in entries:
            if category and e.category != category:
                continue
            if tags and not set(tags).intersection(e.tags):
                continue
            if keyword:
                blob = json.dumps(e.content, ensure_ascii=False).lower()
                if keyword.lower() not in blob:
                    continue
            result.append(e)
        if _USE_STRENGTH_RANKING:
            result.sort(key=self.strength_at, reverse=True)
        else:
            # 既有行为：score 降序 + 时间近因
            result.sort(key=lambda x: (x.score, x.timestamp), reverse=True)
        return result[:limit]

    def set_project_context(
        self,
        *,
        drama_title: str = "",
        episode: str = "",
        platform: str = "",
        notes: str = "",
    ) -> str:
        """写入/覆盖当前项目·多集上下文（高权重，优先注入 Agent）。"""
        content = {
            "drama_title": (drama_title or "").strip(),
            "episode": str(episode or "").strip(),
            "platform": (platform or "").strip(),
            "notes": (notes or "").strip(),
        }
        tags = ["project"]
        if content["episode"]:
            tags.append(f"ep:{content['episode']}")
        if content["drama_title"]:
            tags.append("drama")
        # 去掉旧的 project_context，只保留最新一条
        with self._lock:
            stale = [eid for eid, e in self._entries.items() if e.category == "project_context"]
            for eid in stale:
                del self._entries[eid]
        return self.record(
            category="project_context",
            content=content,
            tags=tags,
            score=0.95,
        )

    def add_episode_note(self, episode: str, note: str, *, drama_title: str = "") -> str:
        """追加一集备忘。"""
        ep = str(episode or "").strip() or "?"
        return self.record(
            category="episode_note",
            content={
                "drama_title": (drama_title or "").strip(),
                "episode": ep,
                "note": (note or "").strip(),
            },
            tags=["episode", f"ep:{ep}"],
            score=0.7,
        )

    def get_project_context(self) -> Dict[str, Any]:
        rows = self.query(category="project_context", limit=1)
        if not rows:
            return {}
        return dict(rows[0].content or {})

    def get_agent_context(self, top_k: int = 5, include_preferences: bool = False) -> str:
        """
        生成注入 Agent system prompt 的记忆摘要

        优先召回：
        0. project_context / episode_note（多集）
        1. feedback（发布效果反馈）
        2. learned_rule（自主学习规则）
        3. 近期失败 trace
        4. user_preference（用户偏好，仅 ``include_preferences=True`` 时召回，
           用于「知心秘书」完整档；默认关以保持零额外成本）
        """
        lines: List[str] = []

        project = self.get_project_context()
        if any(project.get(k) for k in ("drama_title", "episode", "platform", "notes")):
            lines.append("\n\n[项目 / 多集上下文]")
            if project.get("drama_title"):
                lines.append(f"- 剧名: {project['drama_title']}")
            if project.get("episode"):
                lines.append(f"- 集数: {project['episode']}")
            if project.get("platform"):
                lines.append(f"- 平台: {project['platform']}")
            if project.get("notes"):
                lines.append(f"- 备注: {project['notes']}")

        ep_notes = self.query(category="episode_note", limit=2)
        if ep_notes:
            if not any(project.get(k) for k in ("drama_title", "episode", "platform", "notes")):
                lines.append("\n\n[项目 / 多集上下文]")
            for e in ep_notes:
                c = e.content or {}
                lines.append(
                    f"- 集备忘 ep:{c.get('episode', '?')}: {str(c.get('note', ''))[:120]}"
                )

        feedbacks = self.query(category="feedback", limit=2)
        rules = self.query(category="learned_rule", limit=2)
        failures = [e for e in self.query(category="execution_trace", limit=10)
                    if e.content.get("error")]
        failures = failures[:2]
        merged = (feedbacks + rules + failures)[:top_k]
        if merged:
            lines.append("\n\n[长期记忆 · 历史经验]")
            for e in merged:
                ts = time.strftime("%m-%d %H:%M", time.localtime(e.timestamp))
                content_str = json.dumps(e.content, ensure_ascii=False)[:160]
                lines.append(f"- [{e.category}] {ts} {content_str}")

        # 用户偏好（知心秘书完整档才召回，避免轻量档平白烧 token）
        prefs: List[MemoryEntry] = []
        if include_preferences:
            # 先过滤再截断：称呼/开关条目 score 高，若先 limit 会把偏好挤掉
            raw = [
                e for e in self.query(category="user_preference", limit=20)
                # 称呼与温度开关由 agent_persona 单独注入，不在这里重复
                if (e.content or {}).get("key") not in ("agent_nickname", "agent_persona")
            ]
            prefs = raw[:3]
            if prefs:
                lines.append("\n\n[用户偏好 · 记住用户的事]")
                for p in prefs:
                    lines.append(f"- {json.dumps(p.content, ensure_ascii=False)[:120]}")
        # 只强化「真正被注入」的条目（被 query 扫到不算），
        # 否则召回次数虚高，失去「常用 vs 没人碰」的区分度
        injected = list(ep_notes) + list(merged) + list(prefs)
        if injected:
            try:
                self.reinforce([e.entry_id for e in injected])
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"[MemoryStore] 巩固回写失败: {exc}")
        return "".join(lines) if lines else ""

    def learn_from_feedback(self, feedback: Dict[str, Any]) -> Optional[str]:
        """
        从反馈中提炼规则。

        简单规则挖掘：
        若 3 条以上同类 feedback 共享 (platform, low_metric) 模式，则合成一条 learned_rule
        """
        platform = feedback.get("platform", "")
        metric = feedback.get("low_metric", "")
        if not platform or not metric:
            return None
        related = self.query(category="feedback", keyword=platform, limit=10)
        same_pattern = [r for r in related if r.content.get("low_metric") == metric]
        if len(same_pattern) >= 3:
            rule_content = {
                "pattern": f"{platform}+{metric}",
                "rule": f"在 {platform} 平台 {metric} 偏低时，建议优先调整 hook/节奏",
                "evidence_count": len(same_pattern),
            }
            return self.record(category="learned_rule", content=rule_content,
                               tags=["rule", platform], score=0.9)
        return None

    def _append_to_disk(self, entry: MemoryEntry):
        """追加写入 JSONL 持久化"""
        try:
            os.makedirs(os.path.dirname(_STORAGE_PATH), exist_ok=True)
            with open(_STORAGE_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"[MemoryStore] 持久化失败: {e}")
        # 触发压缩检查
        try:
            if os.path.exists(_STORAGE_PATH) and \
               os.path.getsize(_STORAGE_PATH) > _COMPRESS_THRESHOLD:
                self._compress()
        except Exception as e:
            logger.debug(f"[MemoryStore] 压缩检查失败: {e}")

    def _load(self):
        """启动时从 JSONL 加载历史记忆"""
        if not os.path.exists(_STORAGE_PATH):
            return
        try:
            with open(_STORAGE_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    entry = MemoryEntry(**data)
                    # 同 entry_id 后行覆盖前行：reinforce() 的追加新版
                    # 依赖此语义在重启后恢复 recall_count / last_recalled
                    self._entries[entry.entry_id] = entry
                    if len(self._entries) > _MAX_IN_MEMORY:
                        self._entries.popitem(last=False)
            logger.info(f"[MemoryStore] 加载 {len(self._entries)} 条历史记忆")
        except Exception as e:
            logger.warning(f"[MemoryStore] 加载失败: {e}")

    def _compress(self):
        """压缩：保留高 score、核心类别、含 error 的 trace 与全部突触。

        execution_trace 的 score 只有 0.4 且不在核心类别里，但 get_agent_context
        专门检索其中的 error 记录（近期失败经验）——只按 score 压缩会把消费层
        正依赖的数据整体清空（延迟暴露缺陷，2026-09-13 修正）。
        brain_synapse 是 AgentBrain 的学习状态，全部保留（量级由突触上限约束）。
        """
        with self._lock:
            keep = [
                e for e in self._entries.values()
                if e.score >= 0.5
                or e.category in _KEEP_CATEGORIES
                or e.category == "brain_synapse"
                or (_KEEP_TRACE_WITH_ERROR
                    and e.category == "execution_trace"
                    and (e.content or {}).get("error"))
            ]
            self._entries = OrderedDict((e.entry_id, e) for e in keep)
        try:
            with open(_STORAGE_PATH, "w", encoding="utf-8") as f:
                for e in keep:
                    f.write(json.dumps(asdict(e), ensure_ascii=False) + "\n")
            logger.info(f"[MemoryStore] 压缩完成，保留 {len(keep)} 条记忆")
        except Exception as e:
            logger.warning(f"[MemoryStore] 压缩写入失败: {e}")


# 全局单例便捷引用
memory_store = MemoryStore.get_instance()
