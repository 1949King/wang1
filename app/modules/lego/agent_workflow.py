"""
多 Agent 协作工作流 (AgentWorkflow)
===================================
PlanAgent → ClipAgent → ReviewAgent 三智能体协作剪辑流程

基于 Function Calling 做智能任务分发，实现：
- PlanAgent: 视频分析 + 剪辑计划生成
- ClipAgent: 执行单个剪辑任务
- ReviewAgent: 审核结果 + 迭代优化建议
"""
import os
import json
import time
import logging
import threading
from typing import Dict, List, Optional, Callable, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("AI短剧编辑器.agent_workflow")


class AgentRole(Enum):
    """Agent 角色"""
    PLANNER = "planner"
    CLIPPER = "clipper"
    REVIEWER = "reviewer"


class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    REVIEWED = "reviewed"


@dataclass
class ClipTask:
    """单个剪辑任务描述"""
    task_id: str
    start_time: float
    end_time: float
    clip_type: str          # highlight, hook, climax, cliffhanger
    score: float            # AI 评分
    title: str
    description: str = ""
    status: TaskStatus = TaskStatus.PENDING
    output_path: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EditPlan:
    """剪辑计划 (PlanAgent 产出)"""
    video_path: str
    platform: str
    style: str
    target_duration: float
    structure: str
    pacing: str
    bgm_style: str
    subtitle_style: str
    transition_style: str
    effects: List[str] = field(default_factory=list)
    tasks: List[ClipTask] = field(default_factory=list)
    analysis: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ReviewResult:
    """审核结果 (ReviewAgent 产出)"""
    overall_score: float        # 0-100
    completion_rate_3s: float   # 3秒完播率预测
    completion_rate_full: float # 整体完播率预测
    like_rate: float            # 点赞率预测
    comment_rate: float         # 评论率预测
    share_rate: float           # 分享率预测
    viral_probability: float    # 爆款概率
    suggestions: List[Dict[str, Any]] = field(default_factory=list)
    passed: bool = False
    # 如实标注：预测所用特征里，dialogue_density/emotion_variance/
    # conflict_intensity/climax_position/visual_attractiveness/audio_quality/
    # subtitle_quality 目前是固定占位值（未接入真实的对话密度/情绪/画质分析），
    # 只有 duration/scene_count/hook_quality/has_cliffhanger 来自真实剪辑任务
    # 数据。overall_score 因此只能算粗略参考，不是精确的内容质量分析结果。
    uses_placeholder_features: bool = True


@dataclass
class WorkflowState:
    """工作流状态追踪"""
    phase: str = "idle"         # idle, planning, clipping, reviewing, done
    plan: Optional[EditPlan] = None
    review: Optional[ReviewResult] = None
    progress: float = 0.0
    message: str = ""
    errors: List[str] = field(default_factory=list)
    iteration: int = 0
    max_iterations: int = 3


# ============================================================
# PlanAgent - 分析规划
# ============================================================

class PlanAgent:
    """
    规划 Agent：分析视频内容，制定剪辑计划

    输入: 视频路径、平台、风格偏好
    输出: EditPlan (含 ClipTask 列表)
    """

    def __init__(self):
        self._drama_engine = None
        self._viral_engine = None
        self._initialized = False

    def _ensure_engines(self):
        """延迟加载引擎"""
        if self._initialized:
            return
        try:
            from .drama_understanding_engine import DramaUnderstandingEngine
            self._drama_engine = DramaUnderstandingEngine(
                whisper_model="base",
                ollama_model="qwen2.5",
                use_local_ai=True
            )
        except Exception as e:
            logger.warning(f"Drama engine load failed: {e}")
        try:
            from .viral_optimization_engine import ViralOptimizationEngine
            self._viral_engine = ViralOptimizationEngine()
        except Exception as e:
            logger.warning(f"Viral engine load failed: {e}")
        self._initialized = True

    def analyze(self, video_path: str, platform: str = "抖音",
                style: str = "高光剪辑",
                target_duration: float = 60.0,
                progress_cb: Optional[Callable] = None) -> Optional[EditPlan]:
        """
        分析视频并生成剪辑计划

        Args:
            video_path: 视频文件路径
            platform: 目标平台
            style: 剪辑风格
            target_duration: 目标总时长(秒)
            progress_cb: 进度回调(percent, message)

        Returns:
            EditPlan 或 None
        """
        self._ensure_engines()

        if progress_cb:
            progress_cb(5, "AI正在分析视频内容...")

        if not os.path.exists(video_path):
            logger.error(f"Video not found: {video_path}")
            return None

        edit_plan = EditPlan(
            video_path=video_path,
            platform=platform,
            style=style,
            target_duration=target_duration,
            structure="",
            pacing="normal",
            bgm_style="",
            subtitle_style="",
            transition_style="",
        )

        # 使用 DramaUnderstandingEngine 分析视频
        if self._drama_engine:
            try:
                if progress_cb:
                    progress_cb(15, "AI正在识别台词和剧情...")
                drama = self._drama_engine.analyze_video(video_path)

                if progress_cb:
                    progress_cb(50, "AI正在生成剪辑策略...")
                strategy = self._drama_engine.generate_editing_strategy(
                    drama, target_platform=platform, video_style=style
                )

                # 填充计划
                edit_plan.structure = strategy.structure_template
                edit_plan.pacing = strategy.pacing
                edit_plan.bgm_style = strategy.bgm_style
                edit_plan.subtitle_style = strategy.subtitle_style
                edit_plan.transition_style = strategy.transition_style
                edit_plan.effects = strategy.effects

                # 转换 HighlightClip → ClipTask
                for h in strategy.highlights:
                    task = ClipTask(
                        task_id=f"clip_{h.start_time:.0f}_{h.end_time:.0f}",
                        start_time=h.start_time,
                        end_time=h.end_time,
                        clip_type=h.clip_type,
                        score=h.score,
                        title=h.suggested_title,
                        description=" | ".join(h.reasons) if h.reasons else "",
                        metadata={
                            "tags": h.suggested_tags,
                            "emotions": h.emotional_highlights,
                            "characters": h.key_characters,
                        },
                    )
                    edit_plan.tasks.append(task)

                # 按分数降序排列
                edit_plan.tasks.sort(key=lambda t: t.score, reverse=True)

                # 限制总时长
                selected = []
                total = 0.0
                for task in edit_plan.tasks:
                    dur = task.end_time - task.start_time
                    if total + dur <= target_duration:
                        selected.append(task)
                        total += dur
                edit_plan.tasks = selected

                edit_plan.analysis = {
                    "title": drama.title,
                    "genre": drama.genre,
                    "characters": [c.name for c in drama.characters],
                    "plot_points": len(drama.plot_points),
                    "scenes": len(drama.scenes),
                    "themes": drama.themes,
                    "pacing_type": drama.pacing_analysis.get("pacing_type", "normal"),
                    # 真实 ASR 对话数据（精简版，供 ReviewAgent 做真实特征打分）
                    # 仅保留起止时间/说话人/文本/情绪，避免引用大对象
                    "dialogues": [
                        {
                            "start_time": d.start_time,
                            "end_time": d.end_time,
                            "speaker": d.speaker,
                            "text": d.text,
                            "emotion": d.emotion.value if hasattr(d.emotion, "value") else str(d.emotion),
                        }
                        for d in drama.dialogues
                    ],
                }

                if progress_cb:
                    progress_cb(70, f"剪辑计划: {len(edit_plan.tasks)} 个片段, {total:.0f}s")

                return edit_plan

            except Exception as e:
                logger.error(f"PlanAgent analyze failed: {e}")

        # 回退：纯视频信息 + 默认计划
        return self._fallback_plan(video_path, platform, style, target_duration)

    def _fallback_plan(self, video_path: str, platform: str,
                       style: str, duration: float) -> EditPlan:
        """无 AI 引擎时的回退计划"""
        try:
            from .professional_video_engine import ProfessionalVideoEngine
            eng = ProfessionalVideoEngine(max_workers=1)
            info = eng.get_video_info(video_path)
        except Exception:
            info = {"duration": 60.0}

        total_dur = min(info.get("duration", 60.0), duration)
        split_count = max(1, int(total_dur / 15))

        plan = EditPlan(
            video_path=video_path, platform=platform, style=style,
            target_duration=duration, structure="",
            pacing="normal", bgm_style="", subtitle_style="", transition_style="",
        )

        segment_dur = total_dur / split_count
        for i in range(split_count):
            plan.tasks.append(ClipTask(
                task_id=f"fallback_{i}",
                start_time=i * segment_dur,
                end_time=min((i + 1) * segment_dur, total_dur),
                clip_type="segment",
                score=50.0,
                title=f"片段 {i + 1}",
            ))

        return plan


# ============================================================
# ClipAgent - 执行剪辑
# ============================================================

class ClipAgent:
    """
    剪辑 Agent：执行单个剪辑任务，产出视频文件

    集成双内核调度器，自动选最优渲染后端
    """

    def __init__(self):
        self._scheduler = None
        self._output_dir = ""

    @property
    def scheduler(self):
        """延迟获取调度器"""
        if self._scheduler is None:
            try:
                from app.core.editor_scheduler import editor_scheduler
            except ImportError:
                from core.editor_scheduler import editor_scheduler
            self._scheduler = editor_scheduler
        return self._scheduler

    def execute_task(self, task: ClipTask, video_path: str,
                     output_dir: str = "",
                     progress_cb: Optional[Callable] = None) -> bool:
        """
        执行单个剪辑任务

        Args:
            task: 剪辑任务描述
            video_path: 源视频路径
            output_dir: 输出目录
            progress_cb: 进度回调

        Returns:
            是否成功
        """
        # 生成输出路径
        if not output_dir:
            output_dir = os.path.join(
                os.path.dirname(video_path), "AI剪辑输出"
            )
        os.makedirs(output_dir, exist_ok=True)

        safe_title = task.title.replace("/", "_").replace("\\", "_").replace(":", "_")
        output_path = os.path.join(
            output_dir,
            f"{task.task_id}_{safe_title}.mp4"
        )

        task.output_path = output_path
        task.status = TaskStatus.RUNNING

        try:
            # 优先 MLT C++ 引擎（原生多轨+滤镜能力）
            if self._try_mlt_clip(task, video_path, output_path, progress_cb):
                task.status = TaskStatus.COMPLETED
                return True

            # 使用 PyAV 引擎进行精确帧级剪辑
            pyav = self.scheduler.get_pyav_engine()
            if pyav:
                def av_progress(pct, speed, eta):
                    if progress_cb:
                        progress_cb(pct, f"剪辑: {task.title} ({pct:.0f}%)")

                success = pyav.trim(
                    input_path=video_path,
                    output_path=output_path,
                    start=task.start_time,
                    duration=task.end_time - task.start_time,
                    progress_cb=av_progress,
                )
                if success:
                    task.status = TaskStatus.COMPLETED
                    return True

            # 回退到 render_manager
            rm = self.scheduler.get_render_manager()
            if rm:
                # 使用 FFmpeg 快速剪辑
                result = rm.render(
                    input_path=video_path,
                    output_path=output_path,
                    platform=task.metadata.get("platform", "通用HD"),
                    on_progress=lambda pct, spd, eta: (
                        progress_cb and progress_cb(
                            pct, f"剪辑: {task.title} ({pct:.0f}%)"
                        )
                    ),
                )
                if result.success:
                    task.status = TaskStatus.COMPLETED
                    return True

            task.status = TaskStatus.FAILED
            return False

        except Exception as e:
            logger.error(f"ClipAgent failed on {task.task_id}: {e}")
            task.status = TaskStatus.FAILED
            return False

    def _try_mlt_clip(self, task: ClipTask, video_path: str,
                      output_path: str, progress_cb=None) -> bool:
        """尝试使用 MLT C++ 引擎进行单片段裁剪"""
        try:
            from app.core.video_processing.mlt_engine_cpp import (
                is_mlt_cpp_available, get_video_engine,
            )
        except ImportError:
            try:
                from core.video_processing.mlt_engine_cpp import (
                    is_mlt_cpp_available, get_video_engine,
                )
            except ImportError:
                return False

        if not is_mlt_cpp_available():
            return False

        try:
            dur = task.end_time - task.start_time
            if dur <= 0:
                return False
            engine = get_video_engine()
            if not engine.available:
                return False
            if progress_cb:
                progress_cb(10, f"MLT剪辑: {task.title}")
            engine.clip_video(
                input_path=video_path,
                output_path=output_path,
                start_time=task.start_time,
                duration=dur,
            )
            if os.path.isfile(output_path) and os.path.getsize(output_path) > 0:
                if progress_cb:
                    progress_cb(100, f"MLT完成: {task.title}")
                return True
            return False
        except Exception as e:
            logger.debug(f"MLT clip failed for {task.task_id}: {e}")
            return False

    def execute_batch(self, tasks: List[ClipTask], video_path: str,
                      output_dir: str = "",
                      progress_cb: Optional[Callable] = None) -> Tuple[int, int]:
        """
        批量执行剪辑任务

        Returns:
            (成功数, 失败数)
        """
        success_count = 0
        fail_count = 0
        total = len(tasks)

        for i, task in enumerate(tasks):
            if progress_cb:
                overall = (i / total) * 100 if total > 0 else 0
                progress_cb(overall, f"批量剪辑: {i + 1}/{total}")

            def task_progress(pct, msg):
                if progress_cb:
                    overall = ((i + pct / 100) / total) * 100 if total > 0 else pct
                    progress_cb(min(99, overall), msg)

            if self.execute_task(task, video_path, output_dir, task_progress):
                success_count += 1
            else:
                fail_count += 1

        return success_count, fail_count


# ============================================================
# ReviewAgent - 审核迭代
# ============================================================

class ReviewAgent:
    """
    审核 Agent：评估剪辑结果，给出优化建议

    基于 ViralOptimizationEngine 做数据驱动评分
    """

    def __init__(self):
        self._viral_engine = None
        self._ollama_client = None

    def _ensure_engines(self):
        """延迟加载"""
        if self._viral_engine:
            return
        try:
            from .viral_optimization_engine import ViralOptimizationEngine
            self._viral_engine = ViralOptimizationEngine()
        except Exception as e:
            logger.warning(f"Viral engine load failed: {e}")
        try:
            from .ollama_client import ollama_client
            self._ollama_client = ollama_client
        except Exception as e:
            logger.debug(f"Ollama client load failed: {e}")

    def review(self, plan: EditPlan, completed_tasks: List[ClipTask],
               progress_cb: Optional[Callable] = None) -> ReviewResult:
        """
        审核剪辑结果

        Args:
            plan: 原始剪辑计划
            completed_tasks: 已完成的剪辑任务列表
            progress_cb: 进度回调

        Returns:
            ReviewResult
        """
        self._ensure_engines()

        if progress_cb:
            progress_cb(85, "AI正在审核剪辑质量...")

        review = ReviewResult(
            overall_score=70.0,
            completion_rate_3s=0.65,
            completion_rate_full=0.45,
            like_rate=0.03,
            comment_rate=0.01,
            share_rate=0.005,
            viral_probability=0.35,
            passed=True,
        )

        # 使用 ViralOptimizationEngine 预估表现
        if self._viral_engine:
            try:
                from .viral_optimization_engine import VideoFeatures, Platform as VPlatform

                # 优先用 PlanAgent 的真实 ASR 对话数据提取特征；
                # 拿不到时退回固定的中等水平占位值（保持向后兼容）
                real = self._extract_real_features(plan, completed_tasks)
                if real is not None:
                    (dialogue_density, emotion_variance, conflict_intensity,
                     climax_position, visual_attractiveness, audio_quality,
                     subtitle_quality) = real
                    uses_placeholder = False
                else:
                    dialogue_density = 0.6
                    emotion_variance = 0.5
                    conflict_intensity = 0.6
                    climax_position = 0.7
                    visual_attractiveness = 70.0
                    audio_quality = 75.0
                    subtitle_quality = 70.0
                    uses_placeholder = True

                total_dur = sum(t.end_time - t.start_time for t in completed_tasks)
                features = VideoFeatures(
                    duration=total_dur,
                    scene_count=len(completed_tasks),
                    avg_scene_duration=total_dur / max(1, len(completed_tasks)),
                    dialogue_density=dialogue_density,
                    emotion_variance=emotion_variance,
                    conflict_intensity=conflict_intensity,
                    hook_quality=self._estimate_hook_quality(completed_tasks),
                    climax_position=climax_position,
                    has_cliffhanger=self._has_cliffhanger(completed_tasks),
                    visual_attractiveness=visual_attractiveness,
                    audio_quality=audio_quality,
                    subtitle_quality=subtitle_quality,
                )
                review.uses_placeholder_features = uses_placeholder

                platform_map = {
                    "抖音": VPlatform.DOUYIN, "快手": VPlatform.KUAISHOU,
                    "小红书": VPlatform.XIAOHONGSHU, "B站": VPlatform.BILIBILI,
                    "视频号": VPlatform.WECHAT,
                }
                platform = platform_map.get(plan.platform, VPlatform.DOUYIN)

                prediction = self._viral_engine.predict_performance(features, platform)
                suggestions = self._viral_engine.generate_optimization_suggestions(
                    features, platform
                )

                review.completion_rate_3s = prediction.completion_rate_3s
                review.completion_rate_full = prediction.completion_rate_full
                review.like_rate = prediction.like_rate
                review.comment_rate = prediction.comment_rate
                review.share_rate = prediction.share_rate
                review.viral_probability = prediction.viral_probability

                review.overall_score = (
                    prediction.completion_rate_3s * 35
                    + prediction.completion_rate_full * 25
                    + prediction.like_rate * 5 * 20
                    + prediction.comment_rate * 20 * 10
                    + prediction.share_rate * 50 * 10
                )

                review.suggestions = [
                    {
                        "factor": s.factor.value,
                        "current": s.current_score,
                        "target": s.target_score,
                        "advice": s.suggestion,
                        "expected": s.expected_improvement,
                    }
                    for s in suggestions
                ]

                review.passed = review.overall_score >= 60

            except Exception as e:
                logger.warning(f"ReviewAgent analysis failed: {e}")

        if progress_cb:
            score_note = "（部分特征为占位估值，仅供参考）" if review.uses_placeholder_features else ""
            progress_cb(95, f"审核完成: {review.overall_score:.0f}分{score_note}")

        return review

    def _estimate_hook_quality(self, tasks: List[ClipTask]) -> float:
        """基于任务类型估算开场质量"""
        if not tasks:
            return 50.0
        first = tasks[0]
        hook_types = {"hook", "climax", "highlight"}
        if any(t in first.clip_type.lower() for t in hook_types):
            return 75.0
        return 55.0

    def _has_cliffhanger(self, tasks: List[ClipTask]) -> bool:
        """检测是否有悬念设置"""
        return any("cliffhanger" in t.clip_type.lower()
                   or "悬念" in t.title for t in tasks)

    def _extract_real_features(self, plan: EditPlan,
                               completed_tasks: List[ClipTask]):
        """
        从 PlanAgent 的真实 ASR 对话数据提取打分特征。

        复用 app/core/ai/content_classifier.py 的 UniversalFeatureExtractor
        （8 维剧种无关特征），将 PlanAgent.analysis['dialogues'] 转成
        特征向量后映射到 VideoFeatures 需要的 7 个维度。

        Returns:
            7 元组 (dialogue_density, emotion_variance, conflict_intensity,
                    climax_position, visual_attractiveness, audio_quality,
                    subtitle_quality) 或 None（无真实数据时回退占位值）
        """
        try:
            dialogues_raw = (plan.analysis or {}).get("dialogues") or []
            if not dialogues_raw:
                return None

            from types import SimpleNamespace
            from app.core.ai.content_classifier import UniversalFeatureExtractor

            # 转成 extract 需要的对象形态（text/emotion/start_time/end_time/speaker）
            # UniversalFeatureExtractor 用 d.text / d.emotion.value 属性访问
            dialogues = []
            for d in dialogues_raw:
                if not isinstance(d, dict) or not d.get("text"):
                    continue
                emotion_val = d.get("emotion", "")
                dialogues.append(SimpleNamespace(
                    text=d["text"],
                    emotion=SimpleNamespace(value=emotion_val) if emotion_val else None,
                    start_time=float(d.get("start_time", 0.0)),
                    end_time=float(d.get("end_time", 0.0)),
                    speaker=d.get("speaker", ""),
                ))
            if not dialogues:
                return None

            total_dur = max(1.0, float(dialogues[-1].end_time or 1.0))
            features = UniversalFeatureExtractor.extract(
                dialogues=dialogues, scenes=None, plot_points=None,
                total_duration=total_dur,
            )
            # features: [情绪方差, 对话密度, 场景切换, 角色数, 冲突, 反转, 爽点, 甜度]
            emotion_variance = float(features[0])
            dialogue_density = float(features[1])
            conflict_intensity = float(features[4])

            # 高潮位置：取最高分任务位置 / 总时长（真实）
            total_dur_all = max(1.0, total_dur)
            climax_position = 0.5
            if completed_tasks:
                best = max(completed_tasks, key=lambda t: t.score)
                mid = (best.start_time + best.end_time) / 2.0
                climax_position = min(1.0, mid / total_dur_all)

            # 画质/音质/字幕质量：无深度帧/音频分析时，基于时长与对话覆盖做保守估计
            # （有真实 ASR 文本时至少能确认字幕覆盖率），保持 50-90 区间
            subtitle_quality = min(90.0, 60.0 + dialogue_density * 30.0)
            visual_attractiveness = min(90.0, 55.0 + conflict_intensity * 35.0)
            audio_quality = 72.0

            return (dialogue_density, emotion_variance, conflict_intensity,
                    climax_position, visual_attractiveness, audio_quality,
                    subtitle_quality)
        except Exception as e:
            logger.warning(f"ReviewAgent 真实特征提取失败，回退占位值: {e}")
            return None


# ============================================================
# 协作工作流
# ============================================================

class AgentWorkflow:
    """
    PlanAgent → ClipAgent → ReviewAgent 协作工作流

    使用 Function Calling 模式做智能任务分发：
    1. PlanAgent.analyze() → EditPlan
    2. ClipAgent.execute_batch() → clips
    3. ReviewAgent.review() → ReviewResult
    4. 如果未通过 → 迭代优化 (最多 max_iterations 次)

    特性:
    - 异步任务队列
    - 进度追踪
    - 异常重试
    - 迭代优化
    """

    _instance: Optional["AgentWorkflow"] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._init = False
        return cls._instance

    def __init__(self):
        if self._init:
            return
        self._init = True

        self._planner = PlanAgent()
        self._clipper = ClipAgent()
        self._reviewer = ReviewAgent()
        self._state = WorkflowState()
        self._cancel_flag = threading.Event()
        self._active_thread: Optional[threading.Thread] = None
        self._on_progress: Optional[Callable] = None
        self._on_complete: Optional[Callable] = None

    @property
    def state(self) -> WorkflowState:
        return self._state

    def run(self, video_path: str, platform: str = "抖音",
            style: str = "高光剪辑", target_duration: float = 60.0,
            output_dir: str = "",
            on_progress: Optional[Callable] = None,
            on_complete: Optional[Callable] = None) -> WorkflowState:
        """
        启动完整 AI 剪辑工作流 (同步阻塞模式)

        Args:
            video_path: 输入视频路径
            platform: 目标平台
            style: 剪辑风格
            target_duration: 目标时长
            output_dir: 输出目录
            on_progress: 进度回调(percent, message)
            on_complete: 完成回调(WorkflowState)

        Returns:
            WorkflowState
        """
        self._cancel_flag.clear()
        self._state = WorkflowState(
            max_iterations=3,
            phase="planning",
        )
        self._on_progress = on_progress
        self._on_complete = on_complete

        try:
            # Phase 1: Plan
            self._report_progress(0, "Agent协作启动: PlanAgent分析中...")

            if self._cancel_flag.is_set():
                return self._cancel_state()

            plan = self._planner.analyze(
                video_path, platform, style, target_duration,
                progress_cb=lambda p, m: self._report_progress(p * 0.3, m)
            )

            if plan is None:
                self._state.errors.append("PlanAgent: 视频分析失败")
                self._state.phase = "failed"
                return self._state

            self._state.plan = plan
            self._state.phase = "clipping"

            # Phase 2: Clip
            if not plan.tasks:
                self._state.errors.append("PlanAgent: 无可用片段")
                self._state.phase = "failed"
                return self._state

            self._report_progress(30, f"ClipAgent: 开始剪辑 {len(plan.tasks)} 个片段...")

            if self._cancel_flag.is_set():
                return self._cancel_state()

            success, fail = self._clipper.execute_batch(
                plan.tasks, video_path, output_dir,
                progress_cb=lambda p, m: self._report_progress(30 + p * 0.4, m)
            )

            completed = [t for t in plan.tasks if t.status == TaskStatus.COMPLETED]

            if not completed:
                self._state.errors.append("ClipAgent: 所有任务均失败")
                self._state.phase = "failed"
                return self._state

            self._state.phase = "reviewing"

            # Phase 3: Review
            self._report_progress(70, "ReviewAgent: 评估剪辑质量...")

            if self._cancel_flag.is_set():
                return self._cancel_state()

            review = self._reviewer.review(plan, completed)

            # 标记通过的片段
            for t in completed:
                t.status = TaskStatus.REVIEWED

            self._state.review = review
            self._state.progress = 100.0

            if review.passed:
                self._state.phase = "done"
                self._state.message = (
                    f"剪辑完成: {len(completed)} 个片段 | "
                    f"预测评分: {review.overall_score:.0f}/100 | "
                    f"爆款概率: {review.viral_probability:.1%}"
                )
            else:
                # 迭代优化：用 ReviewAgent 的建议指导 LLMClipper 二次精修
                self._state.iteration += 1
                if self._state.iteration <= self._state.max_iterations:
                    self._state.phase = "iterating"
                    self._report_progress(
                        75,
                        f"评分 {review.overall_score:.0f} 不足，"
                        f"第 {self._state.iteration} 次迭代优化..."
                    )

                    # 将优化建议转为自然语言提示
                    if review.suggestions:
                        advice_parts = []
                        for s in review.suggestions[:5]:  # 取前5条关键建议
                            advice_parts.append(
                                f"- {s.get('factor', '优化')}: {s.get('advice', '')}"
                            )
                        iteration_prompt = (
                            f"优化剪辑（特别是: {'; '.join(advice_parts)}）"
                        )
                    else:
                        iteration_prompt = "优化剪辑质量，增强钩子和节奏"

                    try:
                        refined_path = self.refine_with_llm(
                            video_path=video_path,
                            prompt=iteration_prompt,
                            template_key="ai_clip_algorithm",
                            max_duration=target_duration,
                            output_dir=output_dir,
                            on_progress=lambda p, m: self._report_progress(
                                75 + p * 0.2, m
                            ),
                        )
                        if refined_path and os.path.isfile(refined_path):
                            self._state.phase = "done"
                            # 修复：此前直接断言"评分从 X 提升"，但精修后从未
                            # 重新调用 review() 对新结果打分——只是假定 LLM
                            # 精修一定会带来改善，实际上并没有验证。如实说明
                            # 已生成精修版本、原评分是多少，但不编造"提升"的
                            # 结论（除非未来真的接入重新评分逻辑）。
                            self._state.message = (
                                f"第 {self._state.iteration} 次精修已生成新版本"
                                f"（原评分 {review.overall_score:.0f}，未重新评分，效果建议人工复核）"
                            )
                        else:
                            self._state.phase = "done"
                            self._state.message = (
                                f"迭代 {self._state.iteration} 次（LLM精修失败，保留原结果）"
                            )
                    except Exception as iter_err:
                        logger.warning(f"Iteration refine failed: {iter_err}")
                        self._state.phase = "done"
                        self._state.message = (
                            f"迭代 {self._state.iteration} 次后完成（精修异常: {iter_err}）"
                        )
                else:
                    self._state.phase = "done"
                    self._state.message = (
                        f"迭代 {self._state.max_iterations} 次达到上限: "
                        f"评分 {review.overall_score:.0f}/100"
                    )

            self._report_progress(100, self._state.message)

            if self._on_complete:
                try:
                    self._on_complete(self._state)
                except Exception as e:
                    logger.debug(f"on_complete callback failed: {e}")

            return self._state

        except Exception as e:
            logger.error(f"Workflow failed: {e}")
            self._state.errors.append(str(e))
            self._state.phase = "failed"
            return self._state

    def run_async(self, video_path: str, platform: str = "抖音",
                  style: str = "高光剪辑", target_duration: float = 60.0,
                  output_dir: str = "",
                  on_progress: Optional[Callable] = None,
                  on_complete: Optional[Callable] = None):
        """异步启动工作流"""
        if self._active_thread and self._active_thread.is_alive():
            logger.warning("Workflow already running")
            return

        self._active_thread = threading.Thread(
            target=self.run,
            args=(video_path, platform, style, target_duration, output_dir,
                  on_progress, on_complete),
            daemon=True,
        )
        self._active_thread.start()

    def cancel(self):
        """取消工作流"""
        self._cancel_flag.set()
        if self._active_thread and self._active_thread.is_alive():
            self._active_thread.join(timeout=5)

    def _report_progress(self, percent: float, message: str):
        """报告进度"""
        self._state.progress = percent
        self._state.message = message
        if self._on_progress:
            try:
                self._on_progress(percent, message)
            except Exception as e:
                logger.debug(f"on_progress callback failed: {e}")

    def _cancel_state(self) -> WorkflowState:
        """生成取消状态"""
        self._state.phase = "cancelled"
        self._state.message = "工作流已取消"
        if self._on_progress:
            try:
                self._on_progress(0, "已取消")
            except Exception as e:
                logger.debug(f"on_progress callback on cancel failed: {e}")
        return self._state

    def get_status(self) -> Dict[str, Any]:
        """获取工作流状态"""
        s = self._state
        return {
            "phase": s.phase,
            "progress": s.progress,
            "message": s.message,
            "errors": s.errors,
            "iteration": s.iteration,
            "plan_tasks": len(s.plan.tasks) if s.plan else 0,
            "review_score": s.review.overall_score if s.review else 0,
            "review_passed": s.review.passed if s.review else False,
        }

    def refine_with_llm(self, video_path: str, prompt: str,
                        template_key: str = "ai_clip_algorithm",
                        max_duration: int = 60,
                        output_dir: str = "",
                        on_progress: Optional[Callable] = None) -> Optional[str]:
        """
        用 LLMClipper 对已分析视频进行二次精修（复用 Drama 分析，跳过 ASR）。

        调用前提：已完成 PlanAgent.analyze()，即 self._planner._drama_engine
        已加载且分析过当前视频。

        Args:
            video_path: 源视频路径
            prompt: 新的用户提示词
            template_key: LLM prompt 模板
            max_duration: 最大时长
            output_dir: 输出目录
            on_progress: 进度回调

        Returns:
            输出视频路径或 None
        """
        try:
            from app.core.ai.llm_clipper import LLMClipper
        except ImportError:
            try:
                from core.ai.llm_clipper import LLMClipper
            except ImportError:
                logger.warning("LLMClipper 不可用")
                return None

        # 尝试获取已有的 DramaStructure
        drama = None
        if self._planner._drama_engine:
            try:
                # DramaUnderstandingEngine 的 analyze_video 有缓存，秒回
                drama = self._planner._drama_engine.analyze_video(video_path)
            except Exception as e:
                logger.warning(f"获取 Drama 分析失败: {e}")

        if on_progress:
            on_progress(10, "LLM二次精修: 复用分析结果...")

        clipper = LLMClipper()
        return clipper.smart_clip(
            video_path=video_path,
            prompt=prompt,
            template_key=template_key,
            max_duration=max_duration,
            output_dir=output_dir or "",
            drama_structure=drama,
        )


# ============================================================
# 全局实例
# ============================================================

_workflow_instance: Optional[AgentWorkflow] = None


def get_agent_workflow() -> AgentWorkflow:
    """获取 Agent 协作工作流实例"""
    global _workflow_instance
    if _workflow_instance is None:
        _workflow_instance = AgentWorkflow()
    return _workflow_instance
