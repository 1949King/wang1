"""
预览校验闭环 (PreviewValidationLoop)
===================================
对应流程图中「强制进入剪辑模块：轨道排布 + 实时预览 + 画面质检」一节。

核心职责（用户最在意的点）：
  1. 所有片段（AI生成 / 用户导入）必须进入剪辑模块轨道预览。
  2. 预览发现问题（断层/崩坏/人物漂移/音画不同步）→ 即时反馈 Agent。
  3. 支持局部重生成替换片段（仅 AI 生成片段）。
  4. AI + 人工双重核验，预览通过后才进入打分流程。

设计原则：
  - 单例，纯逻辑（core 层），不直接操作 UI 控件。
  - 「加载到时间线」通过广播事件通知 editor_module 执行（不越层）。
  - 预览问题广播 PREVIEW_VALIDATION_FAILED，由 AgentFeedbackBridge 回流 Agent。
  - 重生成复用 VideoGenerationClient，不重复造轮子。

架构位置：
  统一汇合流程 → PreviewValidationLoop（质检闭环）→ 通过 → 五维打分
                                    ↓ 未通过
                              回流 Agent + 局部重生成
"""
from __future__ import annotations
import logging
import threading
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class PreviewStatus(str, Enum):
    """片段预览状态"""
    PENDING = "pending"      # 待预览
    PASSED = "passed"        # 预览通过
    FAILED = "failed"        # 预览发现问题
    REGENERATED = "regenerated"  # 已局部重生成


@dataclass
class PreviewIssue:
    """预览问题记录"""
    clip_id: str
    issue_type: str          # gap(断层) / drift(人物漂移) / desync(音画不同步) / corrupt(崩坏) / other
    description: str
    severity: str = "medium"  # low / medium / high
    reporter: str = "human"   # human / ai
    timestamp: float = 0.0


class PreviewValidationLoop:
    """
    预览校验闭环 —— 单例

    使用方式：
        from app.core.preview_validation_loop import preview_validation_loop
        # 1. 加载片段到时间线（广播事件，editor_module 监听执行）
        preview_validation_loop.load_clips_to_timeline(clips)
        # 2. 预览发现问题，提交（回流 Agent）
        preview_validation_loop.submit_preview_issue(clip_id, "gap", "镜头转场断层")
        # 3. 局部重生成替换（仅 AI 生成片段）
        preview_validation_loop.request_regenerate(clip_id, new_prompt="...")
        # 4. 标记预览通过
        preview_validation_loop.mark_preview_passed(clip_id)
    """
    _instance: Optional['PreviewValidationLoop'] = None
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
        self._lock_rw = threading.RLock()
        # clip_id → {"clip": dict, "status": PreviewStatus, "issues": [PreviewIssue], "regen_count": int}
        self._registry: Dict[str, Dict[str, Any]] = {}
        self._max_regen = 2  # 局部重生成上限

    @classmethod
    def get_instance(cls) -> 'PreviewValidationLoop':
        return cls()

    # ────────────── 主流程 ──────────────

    def load_clips_to_timeline(self, clips: List[Dict[str, Any]],
                               request_id: str = "") -> int:
        """
        加载片段到剪辑模块时间线（广播事件，由 editor_module 监听执行）。

        参数：
            clips: 片段列表，每项形如 {"clip_id": "...", "path": "...", "duration": 5.0,
                   "source": "generation"/"import", "prompt": "..."}
        返回：
            成功登记的片段数
        """
        request_id = request_id or uuid.uuid4().hex[:12]
        registered = 0
        with self._lock_rw:
            for clip in clips:
                cid = clip.get("clip_id") or clip.get("id") or uuid.uuid4().hex[:10]
                self._registry[cid] = {
                    "clip": {**clip, "clip_id": cid},
                    "status": PreviewStatus.PENDING,
                    "issues": [],
                    "regen_count": 0,
                }
                registered += 1

        # 广播「素材→时间线」事件，复用既有 MATERIAL_TO_TIMELINE，editor_module 监听加载
        try:
            from app.modules.lego.core import EventBus, EventType
            EventBus.get_instance().emit(
                EventType.MATERIAL_TO_TIMELINE,
                {
                    "clips": [c.get("clip") for c in self._registry.values()],
                    "source": "pipeline_preview",
                    "request_id": request_id,
                },
                source="PreviewValidationLoop",
            )
        except Exception as e:
            logger.debug(f"[PreviewValidationLoop] emit MATERIAL_TO_TIMELINE 失败: {e}")

        logger.info(f"[PreviewValidationLoop] 已登记 {registered} 个片段待预览")
        return registered

    def submit_preview_issue(self, clip_id: str, issue_type: str,
                             description: str, severity: str = "medium",
                             reporter: str = "human") -> str:
        """
        提交预览问题（人工/AI 双重核验入口）

        返回：issue_id
        """
        import time
        issue = PreviewIssue(
            clip_id=clip_id, issue_type=issue_type, description=description,
            severity=severity, reporter=reporter, timestamp=time.time(),
        )
        with self._lock_rw:
            entry = self._registry.get(clip_id)
            if entry:
                entry["issues"].append(issue)
                entry["status"] = PreviewStatus.FAILED

        # 广播预览失败事件 → AgentFeedbackBridge 回流 Agent
        self._emit_preview_failed(issue)

        # 写记忆
        try:
            from app.core.memory_store import memory_store
            memory_store.record(
                category="feedback",
                content={
                    "issue_type": "preview_gap",
                    "clip_id": clip_id,
                    "preview_issue_type": issue_type,
                    "description": description,
                    "severity": severity,
                    "reporter": reporter,
                },
                tags=["feedback", "preview_gap", issue_type],
                score=0.9,
            )
        except Exception as e:
            logger.debug(f"[PreviewValidationLoop] 写记忆失败: {e}")

        logger.info(f"[PreviewValidationLoop] 预览问题已提交: clip={clip_id} type={issue_type} sev={severity}")
        return f"issue_{uuid.uuid4().hex[:8]}"

    def request_regenerate(self, clip_id: str, new_prompt: str = "",
                           provider: str = "auto") -> Optional[Dict[str, Any]]:
        """
        请求局部重生成替换片段（仅 AI 生成片段）。

        返回：
            新片段信息 {"clip_id", "path", "prompt"} 或 None（不可重生成/超上限）
        """
        with self._lock_rw:
            entry = self._registry.get(clip_id)
            if not entry:
                logger.warning(f"[PreviewValidationLoop] 未找到片段 {clip_id}")
                return None
            clip = entry["clip"]
            # 仅 AI 生成片段可重生成
            if clip.get("source") != "generation" and not clip.get("prompt"):
                logger.info(f"[PreviewValidationLoop] 片段 {clip_id} 非生成片段，不可重生成")
                return None
            if entry["regen_count"] >= self._max_regen:
                logger.warning(f"[PreviewValidationLoop] 片段 {clip_id} 重生成次数超上限 ({self._max_regen})")
                return None
            entry["regen_count"] += 1
            regen_count = entry["regen_count"]
            duration = float(clip.get("duration", 5.0))
            prompt = new_prompt or clip.get("prompt", "")

        # 调用视频生成客户端重新生成
        try:
            from app.core.ai.video_generation_client import video_generation_client
            paths = video_generation_client.generate(
                prompt=prompt, duration=duration, count=1, provider=provider,
            )
            if not paths:
                logger.warning(f"[PreviewValidationLoop] 重生成失败：无输出 (clip={clip_id})")
                return None
            new_path = paths[0]
            new_clip = {
                "clip_id": clip_id,  # 保持 id 便于替换
                "path": new_path,
                "prompt": prompt,
                "source": "generation",
                "regenerated": True,
                "regen_count": regen_count,
                "duration": duration,
            }
            with self._lock_rw:
                if clip_id in self._registry:
                    self._registry[clip_id]["clip"] = new_clip
                    self._registry[clip_id]["status"] = PreviewStatus.REGENERATED
            # 广播替换事件，editor_module 监听替换时间线片段
            try:
                from app.modules.lego.core import EventBus, EventType
                EventBus.get_instance().emit(
                    EventType.CUSTOM,
                    {"subtype": "preview_clip_replaced", "clip_id": clip_id,
                     "new_path": new_path, "regen_count": regen_count},
                    source="PreviewValidationLoop",
                )
            except Exception as e:
                logger.debug(f"[PreviewValidationLoop] emit 替换事件失败: {e}")
            logger.info(f"[PreviewValidationLoop] 片段 {clip_id} 已重生成 (第{regen_count}次)")
            return new_clip
        except Exception as e:
            logger.exception(f"[PreviewValidationLoop] 重生成异常")
            return None

    def mark_preview_passed(self, clip_id: str) -> bool:
        """标记片段预览通过"""
        with self._lock_rw:
            entry = self._registry.get(clip_id)
            if not entry:
                return False
            entry["status"] = PreviewStatus.PASSED
        logger.info(f"[PreviewValidationLoop] 片段 {clip_id} 预览通过")
        return True

    def ai_auto_inspect(self, clip_id: str) -> Dict[str, Any]:
        """
        AI 自动预检（补充人工核验）：基于片段元数据做轻量规则校验。
        实际视觉模型检测可后续接入 neural_engine，此处先做元数据校验。
        """
        with self._lock_rw:
            entry = self._registry.get(clip_id)
            if not entry:
                return {"clip_id": clip_id, "passed": False, "issues": ["未找到片段"]}
            clip = entry["clip"]

        issues: List[str] = []
        path = clip.get("path", "")
        duration = float(clip.get("duration", 0))
        # 规则1：路径为空
        if not path:
            issues.append("片段路径为空")
        # 规则2：时长异常
        if duration <= 0:
            issues.append("片段时长异常")
        elif duration > 60:
            issues.append("片段时长过长（>60s）")

        passed = not issues
        if not passed:
            self.submit_preview_issue(clip_id, "ai_rule", "; ".join(issues),
                                      severity="medium", reporter="ai")
        else:
            self.mark_preview_passed(clip_id)
        return {"clip_id": clip_id, "passed": passed, "issues": issues}

    # ────────────── 查询 ──────────────

    def get_preview_status(self) -> Dict[str, Any]:
        """获取全部片段预览状态摘要"""
        with self._lock_rw:
            total = len(self._registry)
            by_status = {s.value: 0 for s in PreviewStatus}
            for entry in self._registry.values():
                by_status[entry["status"].value] += 1
            return {
                "total": total,
                "by_status": by_status,
                "all_passed": total > 0 and by_status["passed"] + by_status["regenerated"] == total,
            }

    def get_clips_by_status(self, status: PreviewStatus) -> List[Dict[str, Any]]:
        """按状态获取片段"""
        with self._lock_rw:
            return [e["clip"] for e in self._registry.values() if e["status"] == status]

    def clear(self):
        """清空登记（新会话时调用）"""
        with self._lock_rw:
            self._registry.clear()

    # ────────────── 内部 ──────────────

    def _emit_preview_failed(self, issue: PreviewIssue) -> None:
        """广播预览失败事件"""
        try:
            from app.modules.lego.core import EventBus, EventType
            EventBus.get_instance().emit(
                EventType.PREVIEW_VALIDATION_FAILED,
                {
                    "clip_id": issue.clip_id,
                    "issue_type": issue.issue_type,
                    "description": issue.description,
                    "severity": issue.severity,
                    "reporter": issue.reporter,
                },
                source="PreviewValidationLoop",
            )
        except Exception as e:
            logger.debug(f"[PreviewValidationLoop] emit PREVIEW_VALIDATION_FAILED 失败: {e}")


# 全局单例便捷引用
preview_validation_loop = PreviewValidationLoop.get_instance()
