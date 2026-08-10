"""
Agent 业务分流器 (AgentPipelineRouter)
======================================
Agent 全链路闭环的「第一步：智能业务分流」。

职责：
  读取导入栏素材列表 → 判断走哪条业务线
    - 情况A：无外部素材     → AI 视频生成业务线 (GENERATION)
    - 情况B：已有视频/图文  → AI 素材剪辑业务线 (EDITING)

设计原则：
  - 单例，纯逻辑（core 层），不直接读取 UI 控件，由调用方传入素材列表。
  - 分流结果广播 PIPELINE_ROUTED 事件，并写入 MemoryStore 便于回流。
  - 不阻塞主线程（调用方应在 worker 线程调用）。

架构位置：
  Agent → AgentPipelineRouter.route() → AIVideoGenerationPipeline / AI素材剪辑
"""
from __future__ import annotations
import logging
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class PipelineRoute(str, Enum):
    """业务线路由结果"""
    GENERATION = "generation"  # AI 视频生成业务线（无素材 → 全新创作）
    EDITING = "editing"        # AI 素材剪辑业务线（已有素材 → 剪辑加工）


@dataclass
class RouteResult:
    """分流结果"""
    route: PipelineRoute
    has_material: bool                 # 是否有可用素材
    material_count: int                # 素材数量
    material_summary: Dict[str, Any] = field(default_factory=dict)  # 素材摘要（按类型统计）
    reason: str = ""                   # 分流理由（便于 trace）
    request_id: str = ""               # 关联本次会话

    def to_dict(self) -> Dict[str, Any]:
        return {
            "route": self.route.value,
            "has_material": self.has_material,
            "material_count": self.material_count,
            "material_summary": self.material_summary,
            "reason": self.reason,
            "request_id": self.request_id,
        }


# 支持的素材类型（与导入栏/MediaSource 约定一致）
_VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".m4v"}
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif"}
_AUDIO_EXTS = {".mp3", ".wav", ".aac", ".m4a", ".flac", ".ogg"}
_TEXT_EXTS = {".txt", ".srt", ".ass", ".md"}


class AgentPipelineRouter:
    """
    业务分流器 —— 单例

    使用方式：
        from app.core.agent_pipeline_router import agent_pipeline_router
        result = agent_pipeline_router.route(materials=[{"path": "...", "type": "video"}])
        if result.route == PipelineRoute.GENERATION:
            ...  # 走 AI 视频生成
    """
    _instance: Optional['AgentPipelineRouter'] = None
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

    @classmethod
    def get_instance(cls) -> 'AgentPipelineRouter':
        return cls()

    def route(self, materials: Optional[List[Dict[str, Any]]] = None,
              creative_brief: str = "",
              request_id: str = "") -> RouteResult:
        """
        执行业务分流

        参数：
            materials: 导入栏素材列表，每项形如 {"path": "...", "type": "video", "duration": 10.0}
                       （type 可缺省，按扩展名推断）
            creative_brief: 用户创意简报（无素材时用于生成业务线）
            request_id: 关联本次会话 id（便于 trace）

        返回：
            RouteResult
        """
        materials = materials or []
        request_id = request_id or str(__import__("uuid").uuid4().hex[:12])

        # 统计可用素材
        usable = self._filter_usable(materials)
        summary = self._summarize(usable)
        has_material = len(usable) > 0

        if has_material:
            route = PipelineRoute.EDITING
            reason = (f"检测到 {len(usable)} 个可用素材"
                      f"（视频 {summary['video']} / 图片 {summary['image']}"
                      f" / 音频 {summary['audio']} / 文本 {summary['text']}），走 AI 素材剪辑业务线")
        else:
            route = PipelineRoute.GENERATION
            reason = ("导入栏无可用外部素材，走 AI 视频生成业务线"
                      + (f"（创意简报: {creative_brief[:40]}）" if creative_brief else ""))

        result = RouteResult(
            route=route,
            has_material=has_material,
            material_count=len(usable),
            material_summary=summary,
            reason=reason,
            request_id=request_id,
        )

        # 广播分流完成 + 写记忆
        self._emit_route(result)
        self._record_route(result, creative_brief)

        logger.info(f"[AgentPipelineRouter] 分流完成: {route.value} | {reason}")
        return result

    # ────────────── 内部方法 ──────────────

    def _filter_usable(self, materials: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """过滤出可用素材（路径存在且类型可识别）"""
        import os
        usable: List[Dict[str, Any]] = []
        for m in materials:
            if not isinstance(m, dict):
                continue
            path = m.get("path", "")
            mtype = m.get("type") or self._infer_type(path)
            if not path:
                # 无路径但显式声明类型的（如纯文本创意）也视为可用
                if mtype in ("video", "image", "audio", "text"):
                    usable.append({**m, "type": mtype})
                continue
            # 有路径：检查存在性（容错，不存在也保留但标记）
            entry = {**m, "type": mtype, "exists": os.path.exists(path)}
            usable.append(entry)
        return usable

    @staticmethod
    def _infer_type(path: str) -> str:
        """根据扩展名推断素材类型"""
        import os
        ext = os.path.splitext(path)[1].lower()
        if ext in _VIDEO_EXTS:
            return "video"
        if ext in _IMAGE_EXTS:
            return "image"
        if ext in _AUDIO_EXTS:
            return "audio"
        if ext in _TEXT_EXTS:
            return "text"
        return "unknown"

    @staticmethod
    def _summarize(usable: List[Dict[str, Any]]) -> Dict[str, int]:
        """按类型统计素材数量"""
        summary = {"video": 0, "image": 0, "audio": 0, "text": 0, "unknown": 0}
        for m in usable:
            t = m.get("type", "unknown")
            summary[t] = summary.get(t, 0) + 1
        return summary

    def _emit_route(self, result: RouteResult) -> None:
        """广播 PIPELINE_ROUTED 事件"""
        try:
            from app.modules.lego.core import EventBus, EventType
            EventBus.get_instance().emit(
                EventType.PIPELINE_ROUTED,
                result.to_dict(),
                source="AgentPipelineRouter",
            )
        except Exception as e:
            logger.debug(f"[AgentPipelineRouter] emit PIPELINE_ROUTED 失败: {e}")

    def _record_route(self, result: RouteResult, creative_brief: str) -> None:
        """写入 MemoryStore 便于回流分析"""
        try:
            from app.core.memory_store import memory_store
            memory_store.record(
                category="execution_trace",
                content={
                    "stage": "pipeline_route",
                    "route": result.route.value,
                    "material_count": result.material_count,
                    "material_summary": result.material_summary,
                    "creative_brief": creative_brief[:80],
                },
                tags=["pipeline", "route", result.route.value],
                score=0.4,
            )
        except Exception as e:
            logger.debug(f"[AgentPipelineRouter] 写记忆失败: {e}")


# 全局单例便捷引用
agent_pipeline_router = AgentPipelineRouter.get_instance()
