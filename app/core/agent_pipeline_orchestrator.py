"""
Agent 全链路闭环总编排器 (AgentPipelineOrchestrator)
===================================================
对应「Agent 全量双向闭环最终完整版业务流程」的总指挥。

完整流程（用户定稿）：
  1. 读取导入栏素材 → 智能业务分流
     - 路线A 无素材 → AI 视频生成业务线（创意拆解→生成→初检→预览→打分→脚本→精剪→成片）
     - 路线B 有素材 → AI 素材剪辑业务线（解析→打分→脚本→预览→精剪→成片）
  2. 两条业务线统一汇合：预览校验 → 五维打分 → 剪辑脚本 → 精修剪辑 → 正式成片
  3. 后置：多任务调度 + 账号运营 + 数据回流（由既有 capability 支持）
  4. 全局双向回流：所有问题/数据/缺陷回流 Agent 持续迭代

设计原则：
  - 单例，纯逻辑（core 层），不写 UI。
  - execute() 同步执行（调用方应在 worker 线程）；execute_async() 后台线程 + 回调。
  - 各阶段通过 EventBus 广播进度，UI 层监听渲染。
  - 精剪执行通过 CapabilityDispatcher 调用 editor 能力，不越层直接操作 UI。
  - 任一阶段失败有回退，保证流程不中断（可演示）。

架构位置：
  Agent 面板 → AgentPipelineOrchestrator → 各子模块 → 成片
"""
from __future__ import annotations
import logging
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class PipelineSession:
    """一次全链路执行的会话记录"""
    session_id: str
    route: Optional[Dict[str, Any]] = None                 # 分流结果
    generation_result: Optional[Dict[str, Any]] = None     # 业务线1产出
    imported_clips: List[Dict[str, Any]] = field(default_factory=list)  # 业务线2产出
    preview_status: Dict[str, Any] = field(default_factory=dict)        # 预览校验状态
    scored_results: List[Dict[str, Any]] = field(default_factory=list)  # 五维打分
    editing_script: Optional[Dict[str, Any]] = None        # 剪辑创意脚本
    final_video_path: str = ""                             # 成片路径
    success: bool = False
    degraded: bool = False                                 # C：仅有脚本/无成片时为 True
    error: Optional[str] = None
    stage: str = "idle"                                    # 当前阶段

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id, "route": self.route,
            "generation_result": self.generation_result,
            "imported_clips_count": len(self.imported_clips),
            "preview_status": self.preview_status,
            "scored_count": len(self.scored_results),
            "editing_script": self.editing_script,
            "final_video_path": self.final_video_path,
            "success": self.success, "degraded": self.degraded,
            "error": self.error, "stage": self.stage,
        }


class AgentPipelineOrchestrator:
    """
    Agent 全链路闭环总编排器 —— 单例

    使用方式：
        from app.core.agent_pipeline_orchestrator import agent_pipeline_orchestrator
        # 同步（在 worker 线程）
        session = agent_pipeline_orchestrator.execute(
            materials=[...], creative_brief="...", platform="douyin", target_duration=30.0,
        )
        # 异步（后台线程 + 回调）
        agent_pipeline_orchestrator.execute_async(
            materials=[...], creative_brief="...",
            callback=lambda s: print(s.success, s.final_video_path),
        )
    """
    _instance: Optional['AgentPipelineOrchestrator'] = None
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
        self._active_sessions: Dict[str, PipelineSession] = {}
        self._lock_rw = threading.RLock()

    @classmethod
    def get_instance(cls) -> 'AgentPipelineOrchestrator':
        return cls()

    # ────────────── 主入口 ──────────────

    def execute(self, materials: Optional[List[Dict[str, Any]]] = None,
                creative_brief: str = "",
                platform: str = "douyin",
                target_duration: float = 30.0,
                clip_duration: float = 5.0,
                provider: str = "auto",
                auto_preview_pass: bool = False,  # 默认改为 False，启用人工核验
                session_id: str = "") -> PipelineSession:
        """
        同步执行全链路（调用方应在 worker 线程调用，避免阻塞 Qt 主线程）

        参数：
            materials:       导入栏素材列表
            creative_brief:  创意简报（无素材时用于生成业务线）
            platform:        目标平台
            target_duration: 目标总时长（秒）
            clip_duration:   单段时长（生成业务线用）
            provider:        视频生成 provider
            auto_preview_pass: 是否自动标记预览通过（True=AI自动核验；False=等待人工确认）
            session_id:      会话 id
        """
        session_id = session_id or uuid.uuid4().hex[:12]
        session = PipelineSession(session_id=session_id)
        with self._lock_rw:
            self._active_sessions[session_id] = session

        try:
            # ── 第一步：业务分流 ──
            session.stage = "routing"
            self._emit_progress(session, "智能业务分流中...")
            from app.core.agent_pipeline_router import agent_pipeline_router, PipelineRoute
            route_result = agent_pipeline_router.route(
                materials=materials, creative_brief=creative_brief, request_id=session_id,
            )
            session.route = route_result.to_dict()
            self._emit_progress(session, f"分流完成：{route_result.route.value}")

            # ── 第二步：执行对应业务线，产出统一片段列表 ──
            unified_clips: List[Dict[str, Any]] = []
            if route_result.route == PipelineRoute.GENERATION:
                session.stage = "generation"
                self._emit_progress(session, "AI 视频生成业务线启动...")
                unified_clips = self._run_generation_line(
                    creative_brief=creative_brief, platform=platform,
                    target_duration=target_duration, clip_duration=clip_duration,
                    provider=provider, session_id=session_id,
                )
                session.generation_result = {
                    "clip_count": len(unified_clips),
                    "clips": [c.to_dict() if hasattr(c, "to_dict") else c for c in unified_clips],
                }
            else:
                session.stage = "import_parsing"
                self._emit_progress(session, "AI 素材剪辑业务线启动...")
                unified_clips = self._run_editing_line(
                    materials=materials, session_id=session_id,
                )
                session.imported_clips = unified_clips

            if not unified_clips:
                session.success = False
                session.error = "业务线执行后无可用片段"
                self._emit_done(session)
                return session

            # ── 第三步：统一汇合 - 预览校验 ──
            session.stage = "preview"
            self._emit_progress(session, "片段进入剪辑模块预览校验...")
            self._run_preview_validation(unified_clips, auto_preview_pass, session_id)
            from app.core.preview_validation_loop import preview_validation_loop
            session.preview_status = preview_validation_loop.get_preview_status()

            # 如果存在未通过的片段且未启用自动通过，暂停流程等待人工确认
            if not auto_preview_pass and session.preview_status.get("by_status", {}).get("failed", 0) > 0:
                session.stage = "waiting_for_preview_confirmation"
                self._emit_progress(session, "⚠️ 预览未通过，等待人工确认...")
                # 广播需要人工确认的事件
                try:
                    from app.modules.lego.core import EventBus, EventType
                    EventBus.get_instance().emit(
                        EventType.CUSTOM,
                        {
                            "subtype": "pipeline_waiting_preview",
                            "session_id": session_id,
                            "status": session.preview_status,
                            "message": "预览校验发现问题，请在时间线确认后点击继续",
                        },
                        source="AgentPipelineOrchestrator",
                    )
                except Exception as e:
                    logger.debug(f"[AgentPipelineOrchestrator] emit waiting 事件失败: {e}")
                return session  # 暂停并返回当前状态，等待人工确认后续执行

            # ── 第四步：统一五维打分 ──
            session.stage = "scoring"
            self._emit_progress(session, "五维量化打分中...")
            session.scored_results = self._run_scoring(unified_clips)

            # ── 第五步：生成剪辑创意脚本 ──
            session.stage = "scripting"
            self._emit_progress(session, "生成剪辑创意脚本...")
            session.editing_script = self._run_script_generation(
                session.scored_results, target_duration, platform, session_id,
            )

            # ── 第六步：精修剪辑 + 成片 ──
            session.stage = "editing"
            self._emit_progress(session, "执行精修剪辑...")
            session.final_video_path = self._run_editing(session, session_id)

            if session.final_video_path:
                session.success = True
                session.degraded = False
            elif session.editing_script is not None:
                # C：有脚本无成片 = 降级完成，禁止当作成片成功
                session.success = True
                session.degraded = True
                session.error = session.error or "未产出成片文件，仅有剪辑脚本（降级）"
            else:
                session.success = False
                session.degraded = False
                session.error = session.error or "未产出成片或剪辑脚本"
            session.stage = "done"
            self._emit_progress(
                session,
                "全链路降级完成（仅脚本）" if session.degraded else "全链路执行完成",
            )
        except Exception as e:
            logger.exception(f"[AgentPipelineOrchestrator] 会话 {session_id} 执行异常")
            session.success = False
            session.error = str(e)
            session.stage = "error"

        self._emit_done(session)
        return session

    def execute_async(self, materials: Optional[List[Dict[str, Any]]] = None,
                      creative_brief: str = "",
                      platform: str = "douyin",
                      target_duration: float = 30.0,
                      clip_duration: float = 5.0,
                      provider: str = "auto",
                      auto_preview_pass: bool = False,  # 与 execute 一致，默认启用人工核验
                      callback: Optional[Callable[[PipelineSession], None]] = None) -> str:
        """
        异步执行全链路（后台线程）

        返回 session_id，调用方可监听 EventBus CUSTOM(subtype=pipeline_progress/done) 事件，
        或通过 callback 接收最终结果。
        """
        session_id = uuid.uuid4().hex[:12]

        def _runner():
            try:
                result = self.execute(
                    materials=materials, creative_brief=creative_brief,
                    platform=platform, target_duration=target_duration,
                    clip_duration=clip_duration, provider=provider,
                    auto_preview_pass=auto_preview_pass, session_id=session_id,
                )
                if callback:
                    try:
                        callback(result)
                    except Exception:
                        logger.exception("[AgentPipelineOrchestrator] async callback 异常")
            except Exception as e:
                logger.exception(f"[AgentPipelineOrchestrator] 异步执行异常: {e}")

        t = threading.Thread(target=_runner, daemon=True,
                             name=f"pipeline_{session_id}")
        t.start()
        return session_id

    # ────────────── 业务线1：AI 视频生成 ──────────────

    def _run_generation_line(self, creative_brief: str, platform: str,
                             target_duration: float, clip_duration: float,
                             provider: str, session_id: str) -> List[Dict[str, Any]]:
        """执行 AI 生成业务线，返回统一片段列表"""
        from app.core.ai_video_generation_pipeline import ai_video_generation_pipeline
        result = ai_video_generation_pipeline.execute(
            creative_brief=creative_brief, platform=platform,
            target_duration=target_duration, clip_duration=clip_duration,
            provider=provider, request_id=session_id,
        )
        # 转成统一 dict 格式（供预览/打分消费）
        clips: List[Dict[str, Any]] = []
        for c in result.clips:
            clips.append({
                "clip_id": c.clip_id,
                "path": c.path,
                "duration": c.duration,
                "source": "generation",
                "prompt": c.prompt,
                "visual_description": c.visual_description,
                "dialogue": c.dialogue,
                "emotion": c.emotion,
                "scene_index": c.scene_index,
                "inspection_passed": c.inspection_passed,
                "inspection_skipped": c.inspection_skipped,
            })
        return clips

    # ────────────── 业务线2：素材剪辑 ──────────────

    def _run_editing_line(self, materials: List[Dict[str, Any]],
                          session_id: str) -> List[Dict[str, Any]]:
        """执行素材剪辑业务线：解析导入素材，返回统一片段列表"""
        import os
        video_exts = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".m4v"}
        image_exts = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif"}

        clips: List[Dict[str, Any]] = []
        for idx, m in enumerate(materials or []):
            if not isinstance(m, dict):
                continue
            path = m.get("path", "")
            mtype = m.get("type", "")

            # 如果没有 type，尝试根据扩展名推断
            if not mtype and path:
                ext = os.path.splitext(path)[1].lower()
                if ext in video_exts:
                    mtype = "video"
                elif ext in image_exts:
                    mtype = "image"
                else:
                    mtype = "video"  # 默认按视频处理

            # 仅处理视频/图片素材（音频/文本不进剪辑轨道）
            if mtype not in ("video", "image") and path:
                continue

            clip_id = m.get("clip_id") or m.get("id") or f"import_{idx}_{uuid.uuid4().hex[:6]}"
            duration = float(m.get("duration", 5.0))

            # 注入基于素材元数据的质量分（智能基线）
            quality_scores = self._compute_imported_quality_scores(m, mtype, duration)

            clips.append({
                "clip_id": clip_id,
                "path": path,
                "duration": duration,
                "source": "import",
                "name": m.get("name", ""),
                "type": mtype,
                "dialogue": m.get("dialogue", ""),
                "inspection_passed": True,
                "quality_scores": quality_scores,
            })
        # 尝试调用既有引擎补充时长信息（容错）
        self._enrich_clip_durations(clips)
        return clips

    @staticmethod
    def _compute_imported_quality_scores(
        clip_meta: Dict[str, Any], mtype: str, duration: float
    ) -> Dict[str, float]:
        """
        根据导入素材的基础元数据计算初始质量分。

        策略：
        - 已显式提供 quality_scores → 保留，仅补齐缺失维度
        - 未提供 → 根据素材类型/时长/分辨率推断合理基线
        """
        existing = clip_meta.get("quality_scores", {})
        baseline = 70.0

        # 时长合理性评分
        if duration <= 0:
            duration_score = 50.0  # 异常时长
        elif 2.0 <= duration <= 8.0:
            duration_score = 85.0  # 黄金时长
        elif 1.0 <= duration <= 15.0:
            duration_score = 75.0  # 可接受
        else:
            duration_score = 60.0  # 偏长/偏短

        # 视频 vs 图片：图片没有 BGM/镜头时长维度，适当加权
        if mtype == "image":
            visual_base = 72.0
            narrative_base = 68.0
            copy_base = 70.0
            bgm_base = 60.0  # 图片无 BGM，给低基准
        else:
            visual_base = 75.0
            narrative_base = 70.0
            copy_base = 68.0
            bgm_base = 72.0

        return {
            "visual_quality": float(existing.get("visual_quality", visual_base)),
            "narrative_highlight": float(existing.get("narrative_highlight", narrative_base)),
            "copy_match": float(existing.get("copy_match", copy_base)),
            "bgm_match": float(existing.get("bgm_match", bgm_base)),
            "shot_duration": float(existing.get("shot_duration", duration_score)),
        }

    def _enrich_clip_durations(self, clips: List[Dict[str, Any]]) -> None:
        """用既有 ProfessionalVideoEngine 补充视频时长（失败静默）"""
        try:
            from app.modules.lego.professional_video_engine import ProfessionalVideoEngine
            eng = ProfessionalVideoEngine(max_workers=1)
            for c in clips:
                if c.get("duration", 0) > 0 or not c.get("path"):
                    continue
                if c.get("type") != "video":
                    continue
                try:
                    info = eng.get_video_info(c["path"])
                    c["duration"] = float(info.get("duration", 5.0))
                except Exception as e:
                    logger.debug(f"[AgentPipelineOrchestrator] 补充单个片段时长失败 ({c.get('clip_id')}): {e}")
        except Exception as e:
            logger.debug(f"[AgentPipelineOrchestrator] 补充时长失败（忽略）: {e}")

    # ────────────── 统一汇合流程 ──────────────

    def _run_preview_validation(self, clips: List[Dict[str, Any]],
                                auto_preview_pass: bool, session_id: str) -> None:
        """统一预览校验：加载到时间线 + AI 自动核验"""
        from app.core.preview_validation_loop import preview_validation_loop, PreviewStatus
        preview_validation_loop.clear()
        preview_validation_loop.load_clips_to_timeline(clips, request_id=session_id)

        def _get_cid(c: Dict[str, Any]) -> str:
            """兼容 clip_id / id / 自动生成"""
            return c.get("clip_id") or c.get("id") or ""

        # AI 自动核验（轻量规则）
        for c in clips:
            cid = _get_cid(c)
            if not cid:
                continue
            preview_validation_loop.ai_auto_inspect(cid)
        # auto_preview_pass=True 时，未失败的片段自动标记通过
        if auto_preview_pass:
            for c in clips:
                cid = _get_cid(c)
                if not cid:
                    continue
                preview_validation_loop.mark_preview_passed(cid)

    def _run_scoring(self, clips: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """统一五维打分"""
        from app.core.five_dimension_scorer import five_dimension_scorer
        features_list = []
        for c in clips:
            # 兼容 clip_id / id 键
            clip_id = c.get("clip_id") or c.get("id") or ""
            # 构造 clip_meta 供 extract_features_from_clip 使用
            meta = {
                "id": clip_id,
                "path": c.get("path", ""),
                "duration": c.get("duration", 5.0),
                "quality_scores": c.get("quality_scores", {}),
            }
            features = five_dimension_scorer.extract_features_from_clip(meta)
            features_list.append(features)
        results = five_dimension_scorer.score_batch(features_list)
        return [r.to_dict() for r in results]

    def _run_script_generation(self, scored: List[Dict[str, Any]],
                               target_duration: float, platform: str,
                               session_id: str) -> Optional[Dict[str, Any]]:
        """生成剪辑创意脚本"""
        from app.core.editing_script_generator import editing_script_generator
        script = editing_script_generator.generate(
            scored_clips=scored, target_duration=target_duration,
            platform=platform, request_id=session_id,
        )
        return script.to_dict()

    def _run_editing(self, session: PipelineSession, session_id: str) -> str:
        """
        执行精修剪辑 + 成片输出
        通过 CapabilityDispatcher 调用 pipeline.execute_editing 能力（步骤10注册）。
        若能力未就绪，返回空串（脚本已生成，用户可手动精剪）。
        """
        if not session.editing_script:
            return ""
        try:
            from app.core.capability_dispatcher import (
                capability_dispatcher, CapabilityRequest,
            )
            result = capability_dispatcher.invoke(CapabilityRequest(
                capability_id="pipeline.execute_editing",
                params={
                    "editing_script": session.editing_script,
                    "session_id": session_id,
                },
                caller="orchestrator",
            ))
            if result.success and isinstance(result.output, dict):
                return str(result.output.get("output_path", ""))
            logger.warning(f"[AgentPipelineOrchestrator] 精剪执行未就绪/失败: {result.error}")
            return ""
        except Exception as e:
            logger.warning(f"[AgentPipelineOrchestrator] 调用精剪能力异常: {e}")
            return ""

    # ────────────── 事件 & 查询 ──────────────

    def get_session(self, session_id: str) -> Optional[PipelineSession]:
        """获取会话记录"""
        with self._lock_rw:
            return self._active_sessions.get(session_id)

    def _emit_progress(self, session: PipelineSession, message: str) -> None:
        """广播进度事件（UI 监听渲染）"""
        try:
            from app.modules.lego.core import EventBus, EventType
            EventBus.get_instance().emit(
                EventType.CUSTOM,
                {
                    "subtype": "pipeline_progress",
                    "session_id": session.session_id,
                    "stage": session.stage,
                    "message": message,
                },
                source="AgentPipelineOrchestrator",
            )
        except Exception as e:
            logger.debug(f"[AgentPipelineOrchestrator] emit progress 失败: {e}")

    def _emit_done(self, session: PipelineSession) -> None:
        """广播完成事件"""
        try:
            from app.modules.lego.core import EventBus, EventType
            EventBus.get_instance().emit(
                EventType.CUSTOM,
                {
                    "subtype": "pipeline_done",
                    "session_id": session.session_id,
                    "result": session.to_dict(),
                },
                source="AgentPipelineOrchestrator",
            )
        except Exception as e:
            logger.debug(f"[AgentPipelineOrchestrator] emit done 失败: {e}")

        # ── 左右脑神经链接：强化链路突触（Hebbian 学习）──
        try:
            from app.core.agent_brain import agent_brain
            route = (session.route or {}).get("route", "")
            path = ["pipeline.route"]
            if route == "generation":
                path.extend([
                    "pipeline.generate",
                    "pipeline.preview_validate",
                    "pipeline.score",
                    "pipeline.generate_script",
                    "pipeline.execute_editing",
                ])
            else:
                path.extend([
                    "pipeline.preview_validate",
                    "pipeline.score",
                    "pipeline.generate_script",
                    "pipeline.execute_editing",
                ])
            agent_brain.reinforce_path(path, success=bool(session.success))
        except Exception as e:
            logger.debug(f"[AgentBrain] 链路强化失败: {e}")


# 全局单例便捷引用
agent_pipeline_orchestrator = AgentPipelineOrchestrator.get_instance()
