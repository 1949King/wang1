"""
长期记忆 & 自主学习 (MemoryStore)
================================
单例。内存 LRU + JSONL 持久化，关键词/标签召回。
不依赖重型 ML 库；如未来需要向量检索可接入 neural_engine。

记忆类别：
  - execution_trace: 能力调用 trace（成功/失败）
  - feedback: 发布效果反馈
  - learned_rule: 自主学习提炼的规则（3条同模式 feedback 自动合成）
  - strategy_adjustment: 策略调整记录
  - user_preference: 用户偏好
"""
from __future__ import annotations
import json
import logging
import os
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_MAX_IN_MEMORY = 5000
_STORAGE_PATH = os.path.join("data", "agent_memory.jsonl")
_COMPRESS_THRESHOLD = 5 * 1024 * 1024  # 5MB


@dataclass
class MemoryEntry:
    """记忆条目"""
    entry_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    category: str = ""                       # execution_trace / strategy_adjustment / feedback / learned_rule / user_preference
    content: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    tags: List[str] = field(default_factory=list)
    score: float = 0.0                       # 召回权重


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
            # LRU 淘汰
            if len(self._entries) > _MAX_IN_MEMORY:
                self._entries.popitem(last=False)
        self._append_to_disk(entry)
        return entry.entry_id

    def query(self, category: Optional[str] = None,
              tags: Optional[List[str]] = None,
              keyword: Optional[str] = None,
              limit: int = 10) -> List[MemoryEntry]:
        """
        检索记忆：按 category + tags + 关键词交集

        返回按 score 降序 + 时间近因排序的记忆列表
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
        # 按 score 降序 + 时间近因
        result.sort(key=lambda x: (x.score, x.timestamp), reverse=True)
        return result[:limit]

    def get_agent_context(self, top_k: int = 5) -> str:
        """
        生成注入 Agent system prompt 的记忆摘要

        优先召回：
        1. feedback（发布效果反馈）
        2. learned_rule（自主学习规则）
        3. 近期失败 trace
        """
        feedbacks = self.query(category="feedback", limit=2)
        rules = self.query(category="learned_rule", limit=2)
        # 失败的 trace（error 非空）
        failures = [e for e in self.query(category="execution_trace", limit=10)
                    if e.content.get("error")]
        failures = failures[:2]
        merged = (feedbacks + rules + failures)[:top_k]
        if not merged:
            return ""
        lines = ["\n\n[长期记忆 · 历史经验]"]
        for e in merged:
            ts = time.strftime("%m-%d %H:%M", time.localtime(e.timestamp))
            content_str = json.dumps(e.content, ensure_ascii=False)[:160]
            lines.append(f"- [{e.category}] {ts} {content_str}")
        return "\n".join(lines)

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
                    self._entries[entry.entry_id] = entry
                    if len(self._entries) > _MAX_IN_MEMORY:
                        self._entries.popitem(last=False)
            logger.info(f"[MemoryStore] 加载 {len(self._entries)} 条历史记忆")
        except Exception as e:
            logger.warning(f"[MemoryStore] 加载失败: {e}")

    def _compress(self):
        """压缩：保留高 score 与 feedback/learned_rule 类别"""
        with self._lock:
            keep = [e for e in self._entries.values()
                    if e.score >= 0.5 or e.category in (
                        "feedback", "learned_rule",
                        "strategy_adjustment", "user_preference",
                    )]
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
