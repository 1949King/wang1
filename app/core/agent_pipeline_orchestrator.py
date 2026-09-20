"""
Agent 全链路闭环总编排器 (AgentPipelineOrchestrator)
===================================================
对应「Agent 全量双向闭环最终完整版业务流程」的总指挥。

完整流程（用户定稿）：
  1. 读取导入栏素材 → 智能业务分流
     - 路线A 无素材 → AI 视频生成业务线（创意拆解→生成→初检→预览→打分→脚本→精剪→成片）
     - 路线B 有素材 → AI 素材剪辑业务线（解析→打分→脚本→预览→精剪→成片）
  2. 两条业务线统一汇合：预览校验 → 五维打分 → 剪辑脚本 → 精修剪辑 → 正式成片
  3. 后置：多任务调度 + 数据回流（由既有 capability 支持）
  4. 全局双向回流：所有问题/数据/缺陷回流 Agent 持续迭代

设计原则：
  - 单例，纯逻辑（core 层），不写 UI。
  - execute() 同步执行（调用方应在 worker 线程）；execute_async() 后台线程 + 回调。
  - 各阶段通过 EventBus 广播进度，UI 层监听渲染。
  - 精剪执行通过 CapabilityDispatcher 调用 editor 能力，不越层直接操作 UI。
  - 任一阶段失败有回退，保证流程不中断（可演示）。

大脑路由（2026-09-13 · V4.14.2）：
  预览校验是全链路唯一真正的岔路：失败片段可以「重生成补救」也可以「带瑕疵继续」。
  此处向 AgentBrain.suggest_next() 咨询，按历史突触权重选分支，并把选择写进
  `session.executed_path` —— 会话结束时 reinforce_path 会回灌这次选择的好坏，
  学习回路自此闭合。无学习数据时权重全为中性 ⇒ 恒选默认（现状行为），冷启动零风险；
  设 `SG_BRAIN_ROUTE=0` 可整体关闭。

架构位置：
  Agent 面板 → AgentPipelineOrchestrator → 各子模块 → 成片
"""
from __future__ import annotations
import logging
import os
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# P1-3 取消异常：管线任务化后，生成深处的取消经 execute() 上抛到任务层。
# 无 app 包的独立加载场景不可能出现取消，空元组 except 子句永不匹配。
try:
    from app.core.canvas_gen_jobs import GenCancelled
except Exception:  # noqa: BLE001
    GenCancelled = ()  # type: ignore[assignment]

# ── 大脑路由（学习回路最后一步）──
# 预览失败时的两个分支：
#   CONTINUE   = 带瑕疵继续（打分→脚本→精剪）——**现状行为，永远作为默认**
#   REGENERATE = 先局部重生成问题片段再继续（花钱/耗时，可能救回质量）
_BRANCH_CONTINUE = "pipeline.score"
_BRANCH_REGENERATE = "pipeline.regenerate_clip"
# 单次会话最多重生成几个片段（`preview_validation_loop` 自身还有 _max_regen 上限）
_MAX_REGEN_PER_SESSION = 3
# 总开关：设 SG_BRAIN_ROUTE=0 可整体关闭大脑路由（回到纯规则行为）
BRAIN_ROUTING_ENABLED = os.environ.get("SG_BRAIN_ROUTE", "1") == "1"


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
    executed_path: List[str] = field(default_factory=list) # 真实执行经过的 capability 序列（供 Hebbian 精确强化）
    brain_advice: Optional[Dict[str, Any]] = None          # 大脑给出的分支建议（含权重依据，供 UI/排障）

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
            "brain_advice": self.brain_advice,
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
            session.executed_path.append("pipeline.route")
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
                # 仅当真实产出片段时才追加生成步骤到学习路径
                if unified_clips:
                    session.executed_path.append("pipeline.generate")
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
                # 素材剪辑线：解析即真实服务（与生成线对应，供学习路径精确化）
                if unified_clips:
                    session.executed_path.append("pipeline.route_editing")

            if not unified_clips:
                session.success = False
                session.error = "业务线执行后无可用片段"
                self._emit_done(session)
                return session

            # ── 第三步：统一汇合 - 预览校验 ──
            session.stage = "preview"
            self._emit_progress(session, "片段进入剪辑模块预览校验...")
            self._run_preview_validation(unified_clips, session_id)
            session.executed_path.append("pipeline.preview_validate")
            from app.core.preview_validation_loop import preview_validation_loop
            session.preview_status = preview_validation_loop.get_preview_status()
            failed_count = int(
                (session.preview_status.get("by_status", {}) or {}).get("failed", 0) or 0
            )

            # ── 第三步半：大脑决策（学习回路最后一步）──
            # 预览有失败片段时，向 AgentBrain 咨询「重生成补救」还是「带瑕疵继续」。
            # 无学习数据时权重全为中性 ⇒ 选中默认（= 既有行为），冷启动不改变任何东西。
            if failed_count > 0:
                session.brain_advice = self._consult_brain(failed_count)
                if (session.brain_advice.get("choice") == _BRANCH_REGENERATE
                        and auto_preview_pass):
                    replaced = self._try_regenerate_failed(
                        unified_clips, max_clips=_MAX_REGEN_PER_SESSION
                    )
                    if replaced:
                        # 记入真实执行路径 ⇒ 结果好坏会自动回灌给突触（闭环）
                        session.executed_path.append("pipeline.regenerate_clip")
                        session.preview_status = preview_validation_loop.get_preview_status()
                        failed_count = int(
                            (session.preview_status.get("by_status", {}) or {}).get("failed", 0) or 0
                        )
                        self._emit_progress(
                            session, f"大脑选择重生成：已替换 {replaced} 个问题片段"
                        )
                    else:
                        self._emit_progress(session, "重生成未成功，回退原有策略")

            # 自动核验模式：标记通过（与既有行为一致）
            if auto_preview_pass:
                for c in unified_clips:
                    cid = c.get("clip_id") or c.get("id") or ""
                    if cid:
                        preview_validation_loop.mark_preview_passed(cid)
                session.preview_status = preview_validation_loop.get_preview_status()
                failed_count = 0

            # 人工模式且仍有失败 → 暂停等待确认（带上大脑建议供人参考）
            if failed_count > 0 and not auto_preview_pass:
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
                            "brain_advice": session.brain_advice,
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
            session.executed_path.append("pipeline.score")

            # ── 第五步：生成剪辑创意脚本 ──
            session.stage = "scripting"
            self._emit_progress(session, "生成剪辑创意脚本...")
            session.editing_script = self._run_script_generation(
                session.scored_results, target_duration, platform, session_id,
            )
            if session.editing_script is not None:
                session.executed_path.append("pipeline.generate_script")

            # ── 第六步：精修剪辑 + 成片 ──
            session.stage = "editing"
            self._emit_progress(session, "执行精修剪辑...")
            session.final_video_path = self._run_editing(session, session_id)
            if session.final_video_path:
                session.executed_path.append("pipeline.execute_editing")

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
        except GenCancelled:
            # P1-3：取消是控制流（段间/阶段间生效），交任务层标记 cancelled，
            # 不吞成「会话执行异常」；非任务线程调用不可能走到这里，行为零变化。
            raise
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
                                session_id: str) -> None:
        """统一预览校验：加载到时间线 + AI 自动核验。

        注意：这里**不再**顺手把失败片段标记通过 —— 是否强制通过、是否先重生成，
        交由 `execute()` 里的大脑决策/人工确认决定（原实现把「自动通过」埋在这里，
        导致预览失败这个唯一岔路根本没有分支可言）。
        """
        from app.core.preview_validation_loop import preview_validation_loop
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

    # ────────────── 大脑决策（学习回路出口）──────────────

    def _consult_brain(self, failed_count: int) -> Dict[str, Any]:
        """向 AgentBrain 咨询「预览失败后走哪条分支」。

        - 默认分支恒为 `pipeline.score`（带瑕疵继续）—— 与接入大脑前完全一致；
        - 只有真的学到「重生成更能成功」时才会偏离默认；
        - `SG_BRAIN_ROUTE=0` 或大脑不可用时，返回默认，行为不变。
        """
        fallback = {
            "from": "pipeline.preview_validate",
            "choice": _BRANCH_CONTINUE,
            "default": _BRANCH_CONTINUE,
            "changed": False,
            "learned": False,
            "weights": {},
            "failed_count": failed_count,
            "reason": "大脑路由关闭或不可用，沿用默认",
        }
        if not BRAIN_ROUTING_ENABLED:
            return fallback
        try:
            from app.core.agent_brain import agent_brain
            # 内心状态（affect_model）：低信任时让大脑少信历史权重（向默认收缩）。
            # 冷启动 trust=0.5 ⇒ 不干预，与未接入时行为一致。
            trust = None
            try:
                from app.core.ai.affect_model import agent_affect
                trust = agent_affect.current_trust()
            except Exception:
                trust = None
            advice = agent_brain.suggest_next(
                "pipeline.preview_validate",
                [_BRANCH_CONTINUE, _BRANCH_REGENERATE],
                default=_BRANCH_CONTINUE,
                trust=trust,
            )
            advice["failed_count"] = failed_count
            return advice
        except Exception as e:
            logger.debug(f"[AgentPipelineOrchestrator] 大脑咨询失败: {e}")
            return fallback

    def _try_regenerate_failed(self, clips: List[Dict[str, Any]],
                               max_clips: int = _MAX_REGEN_PER_SESSION) -> int:
        """对预览失败的片段做局部重生成（走 capability，受 policy 与 _max_regen 双重约束）。

        成功替换的片段会**回写进 clips 的 path**，保证后续打分/精剪用的是新片段。
        返回实际替换成功的数量。
        """
        try:
            from app.core.preview_validation_loop import (
                preview_validation_loop, PreviewStatus,
            )
            from app.core.capability_dispatcher import (
                capability_dispatcher, CapabilityRequest,
            )
        except Exception as e:
            logger.debug(f"[AgentPipelineOrchestrator] 重生成依赖不可用: {e}")
            return 0

        try:
            failed = preview_validation_loop.get_clips_by_status(PreviewStatus.FAILED)
        except Exception as e:
            logger.debug(f"[AgentPipelineOrchestrator] 取失败片段失败: {e}")
            return 0

        replaced = 0
        new_by_id: Dict[str, Dict[str, Any]] = {}
        for c in (failed or [])[:max_clips]:
            cid = c.get("clip_id") or c.get("id") or ""
            if not cid:
                continue
            try:
                result = capability_dispatcher.invoke(CapabilityRequest(
                    capability_id="pipeline.regenerate_clip",
                    params={"clip_id": cid},
                    caller="orchestrator",
                ))
            except Exception as e:
                logger.debug(f"[AgentPipelineOrchestrator] 重生成 {cid} 异常: {e}")
                continue
            if result is not None and getattr(result, "success", False):
                out = getattr(result, "output", None)
                if isinstance(out, dict):
                    new_by_id[cid] = out
                replaced += 1
            else:
                logger.debug(
                    f"[AgentPipelineOrchestrator] 重生成 {cid} 未成功: "
                    f"{getattr(result, 'error', '')}"
                )

        # 回写统一片段列表，避免后续打分/精剪仍在用旧片段
        if new_by_id:
            for c in clips:
                cid = c.get("clip_id") or c.get("id") or ""
                new_clip = new_by_id.get(cid)
                if not new_clip:
                    continue
                if new_clip.get("path"):
                    c["path"] = new_clip["path"]
                c["regenerated"] = True
        logger.info(f"[AgentPipelineOrchestrator] 局部重生成完成：{replaced} 个片段被替换")
        return replaced

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
        # 优先用【真实执行路径】强化（走到哪记到哪），空则回退到按 route 的预设路径，
        # 避免中途失败时仍整体强化预设链路导致学习信号失真。
        try:
            from app.core.agent_brain import agent_brain
            real_path = list(session.executed_path)
            if len(real_path) >= 2:
                path = real_path
            else:
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

        # ── 内心状态（affect_model）：观察本次会话，更新分支期望（公式⑩ EWMA）──
        # decision_key 用「决策点→选择」记录期望成功率；失败静默降级。
        try:
            from app.core.ai.affect_model import agent_affect
            branch = ""
            advice = getattr(session, "brain_advice", None)
            if isinstance(advice, dict):
                branch = str(advice.get("choice") or "")
            agent_affect.observe_run(
                success=bool(session.success),
                decision_key=f"preview_validate->{branch}" if branch else "",
            )
        except Exception as e:
            logger.debug(f"[AgentPipelineOrchestrator] 内心状态观察失败: {e}")


# 全局单例便捷引用
agent_pipeline_orchestrator = AgentPipelineOrchestrator.get_instance()
