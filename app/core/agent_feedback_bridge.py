"""
Agent 反馈桥 (AgentFeedbackBridge)
==================================
把 DataAnalyzer 的策略调整回流到 Agent + MemoryStore，闭环 5→6→7→1。

架构位置：
  业务数据 → DataAnalyzer → AgentFeedbackBridge → MemoryStore + Agent 面板

工作流：
  1. 发布完成 → EventBus.emit(PUBLISH_RESULT)
  2. AgentFeedbackBridge 订阅 → 自动生成 feedback
  3. 写 MemoryStore(category="feedback")
  4. 触发 learn_from_feedback（3条同模式→learned_rule）
  5. emit AGENT_FEEDBACK_AVAILABLE → Agent 面板显示提示
  6. 下次 Agent 调用 → 注入记忆 + 待处理反馈
"""
from __future__ import annotations
import logging
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class AgentFeedbackBridge:
    """
    反馈桥 —— 单例

    使用方式：
        from app.core.agent_feedback_bridge import agent_feedback_bridge
        agent_feedback_bridge.submit_feedback({"platform": "douyin", "views": 15000})
    """
    _instance: Optional['AgentFeedbackBridge'] = None
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
        self._pending: List[Dict[str, Any]] = []
        self._lock = threading.RLock()
        self._event_bus = None
        self._memory = None
        self._subscribed = False

    @classmethod
    def get_instance(cls) -> 'AgentFeedbackBridge':
        return cls()

    @property
    def event_bus(self):
        """延迟获取 EventBus 并订阅事件（仅一次）"""
        if self._event_bus is None:
            from app.modules.lego.core import EventBus, EventType
            self._event_bus = EventBus.get_instance()
            if not self._subscribed:
                try:
                    self._event_bus.on(EventType.PUBLISH_RESULT, self._on_publish_result)
                    self._event_bus.on(EventType.WORKFLOW_COMPLETED, self._on_workflow_completed)
                    # Agent 全链路闭环质检事件（新增）
                    self._event_bus.on(EventType.GENERATION_INSPECTION_FAILED,
                                       lambda e: self._on_quality_event("generation_bug", e))
                    self._event_bus.on(EventType.PREVIEW_VALIDATION_FAILED,
                                       lambda e: self._on_quality_event("preview_gap", e))
                    self._subscribed = True
                    logger.info("[AgentFeedbackBridge] 已订阅 PUBLISH_RESULT / WORKFLOW_COMPLETED / 质检事件")
                except Exception as e:
                    logger.warning(f"[AgentFeedbackBridge] 订阅事件失败: {e}")
        return self._event_bus

    @property
    def memory(self):
        """延迟获取 MemoryStore"""
        if self._memory is None:
            from app.core.memory_store import MemoryStore
            self._memory = MemoryStore.get_instance()
        return self._memory

    def submit_feedback(self, feedback: Dict[str, Any]) -> str:
        """
        主动提交反馈（DataAnalyzer 或其他模块调用）

        参数：
            feedback: 反馈数据，建议包含 platform/success/views/low_metric
        返回：entry_id
        """
        platform = feedback.get("platform", "")
        tags = ["feedback", platform] if platform else ["feedback"]
        entry_id = self.memory.record(
            category="feedback", content=feedback, tags=tags, score=0.85,
        )
        with self._lock:
            self._pending.append({"feedback_id": entry_id, **feedback})

        # 触发自主学习
        try:
            self.memory.learn_from_feedback(feedback)
        except Exception as e:
            logger.debug(f"[AgentFeedbackBridge] 自主学习失败: {e}")

        # ── 左右脑神经链接：根据运营反馈调整突触权重 ──
        try:
            from app.core.agent_brain import agent_brain
            views = feedback.get("views", 0)
            try:
                views_f = float(views)
            except (TypeError, ValueError):
                views_f = 0.0
            # 严重程度：低播放 → high；中等 → medium；高 → low
            if views_f < 5000:
                severity = "high"
            elif views_f < 20000:
                severity = "medium"
            else:
                severity = "low"
            brain_feedback = {
                "type": "success" if feedback.get("success") else "quality",
                "related_capabilities": [],
                "severity": severity,
                "platform": feedback.get("platform", ""),
                "views": views_f,
            }
            agent_brain.learn_from_feedback(brain_feedback)
        except Exception as e:
            logger.debug(f"[AgentFeedbackBridge] 突触学习失败: {e}")

        # 通知 Agent 面板
        try:
            from app.modules.lego.core import EventType
            self.event_bus.emit(
                EventType.AGENT_FEEDBACK_AVAILABLE,
                {"feedback_id": entry_id, "summary": self._brief(feedback)},
                source="AgentFeedbackBridge",
            )
        except Exception as e:
            logger.debug(f"[AgentFeedbackBridge] emit 失败: {e}")

        logger.info(f"[AgentFeedbackBridge] 反馈已提交: {self._brief(feedback)}")
        return entry_id

    def submit_quality_issue(self, issue_type: str, details: Dict[str, Any]) -> str:
        """
        提交质检问题（统一入口）

        参数：
            issue_type: 问题类型
                - generation_bug: AI生成BUG（穿模/手部畸形/逻辑混乱）
                - preview_gap: 预览断层（镜头不连续/音画不同步）
                - edit_flaw: 精剪瑕疵（插帧/转场问题）
                - scoring_deviation: 打分偏差
            details: 问题详情，建议包含 clip_id / description / severity
        返回：entry_id
        """
        feedback = {
            "issue_type": issue_type,
            "source": "pipeline",
            **details,
        }
        tags = ["feedback", issue_type]
        if details.get("platform"):
            tags.append(details["platform"])
        entry_id = self.memory.record(
            category="feedback", content=feedback, tags=tags, score=0.9,
        )
        with self._lock:
            self._pending.append({"feedback_id": entry_id, **feedback})
        # 触发自主学习
        try:
            self.memory.learn_from_feedback(feedback)
        except Exception as e:
            logger.debug(f"[AgentFeedbackBridge] 质检问题学习失败: {e}")

        # ── 左右脑神经链接：按质检问题类型映射相关神经元，调整突触 ──
        try:
            from app.core.agent_brain import agent_brain
            # issue_type → 相关 capability 链路 + 反馈类型映射
            issue_map = {
                "generation_bug":     (["pipeline.generate", "model.chat"],
                                       "quality"),
                "preview_gap":        (["pipeline.preview_validate",
                                        "editor.get_timeline_context"],
                                       "preview_issue"),
                "edit_flaw":          (["pipeline.execute_editing",
                                        "editor.add_transition"],
                                       "quality"),
                "scoring_deviation":  (["pipeline.score"], "quality"),
            }
            related, fb_type = issue_map.get(issue_type, ([], "quality"))
            severity = details.get("severity", "medium")
            if severity not in ("low", "medium", "high"):
                severity = "medium"
            brain_feedback = {
                "type": fb_type,
                "related_capabilities": related,
                "severity": severity,
                "issue_type": issue_type,
                "clip_id": details.get("clip_id", ""),
            }
            agent_brain.learn_from_feedback(brain_feedback)
        except Exception as e:
            logger.debug(f"[AgentFeedbackBridge] 质检突触学习失败: {e}")

        # 通知 Agent 面板
        try:
            from app.modules.lego.core import EventType
            self.event_bus.emit(
                EventType.AGENT_FEEDBACK_AVAILABLE,
                {"feedback_id": entry_id,
                 "summary": f"[{issue_type}] {details.get('description', '')[:80]}"},
                source="AgentFeedbackBridge",
            )
        except Exception as e:
            logger.debug(f"[AgentFeedbackBridge] 质检问题 emit 失败: {e}")
        logger.info(f"[AgentFeedbackBridge] 质检问题已提交: [{issue_type}] {details.get('description', '')[:60]}")
        return entry_id

    def _on_quality_event(self, issue_type: str, event):
        """监听质检事件，自动入记忆"""
        data = event.data or {}
        self.submit_quality_issue(issue_type, data)

    def get_pending_feedback(self, limit: int = 5) -> List[Dict[str, Any]]:
        """获取待处理反馈，供 Agent 注入提示词"""
        with self._lock:
            return list(self._pending[:limit])

    def mark_feedback_consumed(self, feedback_ids: List[str]):
        """标记反馈已被 Agent 消费"""
        with self._lock:
            self._pending = [f for f in self._pending
                             if f.get("feedback_id") not in feedback_ids]

    def _on_publish_result(self, event):
        """监听发布结果，自动生成反馈条目"""
        data = event.data or {}
        platform = data.get("platform", "")
        success = data.get("success", False)
        views = data.get("views", 0)
        feedback = {
            "platform": platform,
            "success": success,
            "views": views,
            "low_metric": "views" if views < 5000 else "",
            "source": "publish_result",
        }
        self.submit_feedback(feedback)

    def _on_workflow_completed(self, event):
        """工作流完成时记录 trace，不主动生成 feedback"""
        try:
            self.memory.record(
                category="execution_trace",
                content={
                    "source": "workflow_completed",
                    "data_keys": list((event.data or {}).keys()),
                },
                tags=["workflow", "trace"], score=0.4,
            )
        except Exception as e:
            logger.debug(f"[AgentFeedbackBridge] 记录 workflow trace 失败: {e}")

    @staticmethod
    def _brief(feedback: Dict[str, Any]) -> str:
        """生成反馈简述"""
        platform = feedback.get("platform", "")
        views = feedback.get("views", 0)
        success = "成功" if feedback.get("success") else "失败"
        return f"{platform} 发布{success}，播放 {views}"


# 全局单例便捷引用
agent_feedback_bridge = AgentFeedbackBridge.get_instance()
