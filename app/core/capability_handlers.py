"""
能力 handlers —— 三大模块 + 多任务 + 账号运营的具体实现
======================================================
所有 handler 都通过 lazy 引用既有单例，不重新实现业务逻辑。

handler 分类：
  - EditorCapabilityHandlers: 剪辑模块（split/filter/transition/timeline_context/ripple_delete_range/suggest_cleanup）
  - ModelCapabilityHandlers: 模型模块（chat/chat_with_fallback/list_models）
  - ExtensionCapabilityHandlers: 拓展模块（run_extension/run_skill/list_tools）
  - WorkflowCapabilityHandlers: 多任务调度（start_workflow/submit_batch）
  - AccountCapabilityHandlers: 账号运营（collect_data/optimize_strategy/publish）
"""
from __future__ import annotations
import logging
from typing import Any, Callable, Dict, List, Optional

from app.core.capability_dispatcher import (
    CapabilityDispatcher, CapabilityRequest, CapabilityResult, CapabilityCategory,
)

logger = logging.getLogger(__name__)


# ────────────── 剪辑能力 handlers ──────────────
class EditorCapabilityHandlers:
    """剪辑能力 handlers —— 通过 EditorModule lazy 引用操作时间线"""

    def __init__(self, editor_module_ref: Callable[[], Any]):
        # lazy ref：调用时才取，避免 import 时拉起 UI
        self._get_editor = editor_module_ref

    def split_clip(self, req: CapabilityRequest) -> CapabilityResult:
        """切分片段"""
        editor = self._get_editor()
        if editor is None:
            return CapabilityResult(req.request_id, False, error="EditorModule 未就绪")
        clip_id = req.params.get("clip_id") or req.params.get("id")
        split_time = float(req.params.get("split_time", 0))
        clip = next((c for c in editor._clips if c.get("id") == clip_id), None)
        if not clip:
            return CapabilityResult(req.request_id, False, error=f"未找到片段 {clip_id}")
        res = editor.agent_split_clip(clip, split_time)
        msg = res.get("message", "") if isinstance(res, dict) else str(res)
        return CapabilityResult(req.request_id, success="成功" in msg or "已" in msg,
                                output=res, error=None if "已" in msg else msg)

    def apply_filter(self, req: CapabilityRequest) -> CapabilityResult:
        """应用滤镜"""
        editor = self._get_editor()
        if editor is None:
            return CapabilityResult(req.request_id, False, error="EditorModule 未就绪")
        clip_id = req.params.get("clip_id") or req.params.get("id")
        clip = next((c for c in editor._clips if c.get("id") == clip_id), None) \
            or getattr(editor, "_current_clip", None)
        if not clip:
            return CapabilityResult(req.request_id, False, error="未选中片段")
        # 修复：agent_apply_filter 内部有 try/except，失败时返回
        # {"success": False, "message": ...}，此前这里完全不看返回值，
        # 无条件报 True——滤镜应用异常（比如片段数据损坏）也会被包装成成功。
        res = editor.agent_apply_filter(clip, req.params.get("filter_name", "电影"),
                                        float(req.params.get("intensity", 0.7)))
        ok = bool(isinstance(res, dict) and res.get("success"))
        return CapabilityResult(req.request_id, ok, output={"clip_id": clip.get("id"), **(res or {})},
                                error=None if ok else (res or {}).get("message", "应用滤镜失败"))

    def add_transition(self, req: CapabilityRequest) -> CapabilityResult:
        """添加转场"""
        editor = self._get_editor()
        if editor is None:
            return CapabilityResult(req.request_id, False, error="EditorModule 未就绪")
        clip_id = req.params.get("clip_id") or req.params.get("id")
        clip = next((c for c in editor._clips if c.get("id") == clip_id), None) \
            or getattr(editor, "_current_clip", None)
        if not clip:
            return CapabilityResult(req.request_id, False, error="未选中片段")
        # 修复：同 apply_filter，此前忽略 agent_apply_transition 的返回值，
        # 失败也无条件报 True
        res = editor.agent_apply_transition(clip, req.params.get("transition_type", "fade"),
                                            float(req.params.get("duration", 0.5)))
        ok = bool(isinstance(res, dict) and res.get("success"))
        return CapabilityResult(req.request_id, ok, output=res or {},
                                error=None if ok else (res or {}).get("message", "添加转场失败"))

    def get_timeline_context(self, req: CapabilityRequest) -> CapabilityResult:
        """获取时间线上下文"""
        editor = self._get_editor()
        if editor is None:
            return CapabilityResult(req.request_id, False, error="EditorModule 未就绪")
        ctx = editor.agent_get_timeline_context()
        return CapabilityResult(req.request_id, True, output=ctx)

    def ripple_delete_range(self, req: CapabilityRequest) -> CapabilityResult:
        """波纹删除时间线区间 [t_in, t_out)（接 B1，可撤销）"""
        editor = self._get_editor()
        if editor is None:
            return CapabilityResult(req.request_id, False, error="EditorModule 未就绪")
        t_in = req.params.get("t_in", req.params.get("start_time"))
        t_out = req.params.get("t_out", req.params.get("end_time"))
        if t_in is None or t_out is None:
            return CapabilityResult(
                req.request_id, False,
                error="需要 t_in/t_out（或 start_time/end_time）",
            )
        track = req.params.get("track")
        track_i = int(track) if track is not None else None
        res = editor.agent_ripple_delete_range(
            float(t_in), float(t_out), track=track_i,
        )
        ok = bool(isinstance(res, dict) and res.get("success"))
        msg = res.get("message", "") if isinstance(res, dict) else str(res)
        return CapabilityResult(
            req.request_id, ok, output=res if isinstance(res, dict) else {"raw": res},
            error=None if ok else msg,
        )

    def suggest_cleanup(self, req: CapabilityRequest) -> CapabilityResult:
        """M5：建议去水词/静音区间；默认弹勾选确认，不默认 run_full / 静默删除。"""
        editor = self._get_editor()
        if editor is None:
            return CapabilityResult(req.request_id, False, error="EditorModule 未就绪")
        open_ui = bool(req.params.get("open_ui", True))
        res = editor.agent_suggest_cleanup(open_ui=open_ui)
        ok = bool(isinstance(res, dict) and res.get("success"))
        # 仅建议（awaiting_confirm）也算成功交付建议
        if isinstance(res, dict) and res.get("awaiting_confirm") and res.get("intervals"):
            ok = True
        msg = res.get("message", "") if isinstance(res, dict) else str(res)
        return CapabilityResult(
            req.request_id, ok, output=res if isinstance(res, dict) else {"raw": res},
            error=None if ok else msg,
        )


# ────────────── 模型能力 handlers ──────────────
class ModelCapabilityHandlers:
    """模型能力 handlers —— 封装 AIEngine"""

    def chat(self, req: CapabilityRequest) -> CapabilityResult:
        """调用指定 AI 提供者"""
        from app.core.ai_engine import ai_engine
        provider = req.params.get("provider", "")
        messages = req.params.get("messages", [])
        model = req.params.get("model")
        try:
            chunks = list(ai_engine.chat(provider, messages, model=model,
                                         stream=False, use_cache=req.params.get("use_cache", True)))
            text = "".join(chunks) if chunks else ""
            return CapabilityResult(req.request_id, True, output={"text": text})
        except Exception as e:
            return CapabilityResult(req.request_id, False, error=str(e))

    def chat_with_fallback(self, req: CapabilityRequest) -> CapabilityResult:
        """智能降级调用 AI"""
        from app.core.ai_engine import ai_engine
        messages = req.params.get("messages", [])
        try:
            chunks = list(ai_engine.chat_with_fallback(
                messages=messages,
                providers=req.params.get("providers"),
                model=req.params.get("model"),
                template=req.params.get("template"),
            ))
            return CapabilityResult(req.request_id, True, output={"text": "".join(chunks)})
        except Exception as e:
            return CapabilityResult(req.request_id, False, error=str(e))

    def list_models(self, req: CapabilityRequest) -> CapabilityResult:
        """列出可用 AI 提供者"""
        from app.core.ai_engine import ai_engine
        providers = ai_engine.get_available_providers()
        return CapabilityResult(req.request_id, True, output={"providers": providers})


# ────────────── 拓展能力 handlers ──────────────
class ExtensionCapabilityHandlers:
    """拓展能力 handlers —— 统一 ExtensionsRegistry + SkillEngine"""

    def run_extension(self, req: CapabilityRequest) -> CapabilityResult:
        """
        运行 ExtensionsRegistry 中的 Plugin/Skill/MCP
        保留既有 fallback 顺序：ExtensionsRegistry → SkillEngine
        """
        ext_id = req.params.get("extension_id") or req.params.get("ext_id")
        tool_id = req.params.get("tool_id") or ext_id
        call_params = req.params.get("params") or {}
        if not ext_id:
            return CapabilityResult(req.request_id, False, error="缺少 extension_id")

        # ① ExtensionsRegistry 优先
        try:
            from app.core.extension_base import get_extensions_registry
            registry = get_extensions_registry()
            ext = registry.get(ext_id)
            if ext is not None:
                if not ext.is_available and not ext.initialize():
                    return CapabilityResult(req.request_id, False,
                                            error=f"扩展 {ext.info.name} 初始化失败: {ext.error}")
                result = ext.run(tool_id, **call_params)
                return CapabilityResult(req.request_id, True, output={"result": result})
        except Exception as e:
            logger.warning(f"[ext.run_extension] ExtensionsRegistry 失败: {e}")

        # ② 回退 SkillEngine
        try:
            from app.modules.lego.skill_engine import skill_engine
            for skill in skill_engine.list_all():
                if skill.skill_id == ext_id:
                    from app.core.extensions_context import ExtensionsContext
                    ctx = ExtensionsContext(inputs=call_params)
                    result = skill.execute(ctx)
                    return CapabilityResult(req.request_id, True, output={"result": result})
        except Exception as e:
            logger.warning(f"[ext.run_extension] SkillEngine 失败: {e}")

        return CapabilityResult(req.request_id, False, error=f"未找到扩展: {ext_id}")

    def run_skill(self, req: CapabilityRequest) -> CapabilityResult:
        """直接通过 SkillEngine 执行 Skill（含 account_skills）"""
        from app.modules.lego.skill_engine import skill_engine
        skill_id = req.params.get("skill_id")
        inputs = req.params.get("inputs") or {}
        if not skill_id:
            return CapabilityResult(req.request_id, False, error="缺少 skill_id")
        result = skill_engine.execute_skill(skill_id, inputs=inputs)
        return CapabilityResult(req.request_id, bool(result.get("success", False)),
                                output=result, error=result.get("error"))

    def list_tools(self, req: CapabilityRequest) -> CapabilityResult:
        """列出所有可用拓展工具（供 Agent 构建提示词）"""
        tools: List[Dict[str, Any]] = []
        try:
            from app.core.extension_base import get_extensions_registry
            for ext in get_extensions_registry().list_all():
                if not (ext.is_enabled or ext.is_available):
                    continue
                for t in (ext.get_tools() or []):
                    tools.append({
                        "extension_id": ext.info.id, "extension_name": ext.info.name,
                        "extension_type": ext.extension_type.value,
                        "tool_id": t.id, "tool_name": t.name, "description": t.description,
                    })
        except Exception as e:
            logger.debug(f"list_tools ExtensionsRegistry 失败: {e}")
        try:
            from app.modules.lego.skill_engine import skill_engine
            for skill in skill_engine.list_all():
                tools.append({
                    "extension_id": skill.skill_id, "extension_name": skill.skill_name,
                    "extension_type": "skill", "tool_id": skill.skill_id,
                    "tool_name": skill.skill_name,
                    "description": getattr(skill, "skill_description", ""),
                })
        except Exception as e:
            logger.debug(f"list_tools SkillEngine 失败: {e}")
        return CapabilityResult(req.request_id, True, output={"tools": tools})


# ────────────── 多任务调度 handlers ──────────────
class WorkflowCapabilityHandlers:
    """多任务调度 handlers —— Flow/Workflow/Batch 三件套统一入口"""

    def start_workflow(self, req: CapabilityRequest) -> CapabilityResult:
        """启动全链路工作流"""
        from app.modules.lego.workflow_manager import WorkflowManager
        from app.modules.lego.drama_crawler import DramaInfo
        manager = WorkflowManager()
        drama_data = req.params.get("drama_info", {})
        try:
            drama = DramaInfo(**drama_data) if isinstance(drama_data, dict) else drama_data
            manager.start_workflow(drama)
            return CapabilityResult(req.request_id, True, output={"status": "started"})
        except Exception as e:
            return CapabilityResult(req.request_id, False, error=str(e))

    def submit_batch_task(self, req: CapabilityRequest) -> CapabilityResult:
        """提交批量任务"""
        from app.modules.lego.batch_task_manager import (
            BatchTaskManager, BatchTask, TaskPriority, TaskStatus,
        )
        from datetime import datetime
        manager = BatchTaskManager()
        task = BatchTask(
            task_id=req.params.get("task_id", req.request_id),
            name=req.params.get("name", "agent_batch"),
            task_type=req.params.get("task_type", "smart_clip"),
            params=req.params.get("params", {}),
            priority=TaskPriority[req.params.get("priority", "NORMAL").upper()],
            status=TaskStatus.PENDING,
            progress=0.0,
            created_at=datetime.now(),
        )
        # 兼容不同方法名
        if hasattr(manager, "submit_task"):
            manager.submit_task(task)
        elif hasattr(manager, "add_task"):
            manager.add_task(task)
        else:
            return CapabilityResult(req.request_id, False, error="BatchTaskManager 无入队接口")
        return CapabilityResult(req.request_id, True, output={"task_id": task.task_id})


# ────────────── 账号运营 handlers ──────────────
class AccountCapabilityHandlers:
    """账号运营 handlers —— 通过 SkillEngine 调用 account_skills"""

    def collect_data(self, req: CapabilityRequest) -> CapabilityResult:
        """采集账号数据"""
        from app.modules.lego.skill_engine import skill_engine
        result = skill_engine.execute_skill("account_data_collect",
                                            inputs=req.params.get("inputs", {}))
        return CapabilityResult(req.request_id, bool(result.get("success")),
                                output=result, error=result.get("error"))

    def optimize_strategy(self, req: CapabilityRequest) -> CapabilityResult:
        """调用 viral_optimization_engine 生成优化建议"""
        try:
            from app.modules.lego.viral_optimization_engine import (
                ViralOptimizationEngine, Platform, VideoFeatures,
            )
            engine = ViralOptimizationEngine()
            platform = req.params.get("platform", "douyin")
            platform_enum = getattr(Platform, platform.upper(), Platform.DOUYIN)
            features = VideoFeatures(**req.params.get("features", {}))
            suggestions = engine.generate_optimization_suggestions(features, platform_enum)
            return CapabilityResult(req.request_id, True, output={"suggestions": suggestions})
        except Exception as e:
            return CapabilityResult(req.request_id, False, error=str(e))

    def publish(self, req: CapabilityRequest) -> CapabilityResult:
        """发布作品

        真实注册的发布类 Skill 是 `publish_content`（单条内容发布）和
        `matrix_publish`（批量矩阵发布），历史遗留默认值 `account_publish`
        在 account_skills.py 中从未存在，任何未显式传 skill_id 的调用都必
        然 100% 失败。默认改为单条发布；批量场景需显式传
        `params={"skill_id": "matrix_publish", ...}`。
        """
        from app.modules.lego.skill_engine import skill_engine
        skill_id = req.params.get("skill_id", "publish_content")
        result = skill_engine.execute_skill(skill_id, inputs=req.params.get("inputs", {}))
        return CapabilityResult(req.request_id, bool(result.get("success")),
                                output=result, error=result.get("error"))


# ────────────── Agent 全链路闭环 handlers ──────────────
class PipelineCapabilityHandlers:
    """
    Agent 全链路闭环能力 handlers —— 串联分流/生成/预览/打分/脚本/精剪/成片。
    精剪执行通过 editor_module_ref 回调 EditorModule（与剪辑能力一致）。
    """

    def __init__(self, editor_module_ref: Callable[[], Any]):
        self._get_editor = editor_module_ref

    def route(self, req: CapabilityRequest) -> CapabilityResult:
        """业务分流：判断走 AI生成业务线 or AI素材剪辑业务线"""
        from app.core.agent_pipeline_router import agent_pipeline_router
        result = agent_pipeline_router.route(
            materials=req.params.get("materials", []),
            creative_brief=req.params.get("creative_brief", ""),
            request_id=req.request_id,
        )
        return CapabilityResult(req.request_id, True, output=result.to_dict())

    def generate(self, req: CapabilityRequest) -> CapabilityResult:
        """AI 视频生成业务线：创意拆解→生成→初检→回溯闭环"""
        from app.core.ai_video_generation_pipeline import ai_video_generation_pipeline
        result = ai_video_generation_pipeline.execute(
            creative_brief=req.params.get("creative_brief", ""),
            platform=req.params.get("platform", "douyin"),
            target_duration=float(req.params.get("target_duration", 30.0)),
            clip_duration=float(req.params.get("clip_duration", 5.0)),
            provider=req.params.get("provider", "auto"),
            request_id=req.request_id,
        )
        return CapabilityResult(
            req.request_id, result.success,
            output={"clips": [c.to_dict() for c in result.clips],
                    "outline": result.outline, "error": result.error},
            error=result.error,
        )

    def preview_validate(self, req: CapabilityRequest) -> CapabilityResult:
        """预览校验：片段进入剪辑模块轨道 + AI自动核验

        修复两处假成功：
        1. `registered == 0`（没有任何片段真正登记到时间线）此前仍然
           `success=True`，只把错误信息塞进 error 字段——调用方按
           CapabilityResult.success 判断会误以为流程正常。
        2. `auto_preview_pass=True`（默认值）此前直接对每个片段调用
           `mark_preview_passed`，不做任何检查地无脑标记"预览通过"，
           `PreviewValidationLoop.ai_auto_inspect` 现成的路径为空/时长异常
           规则校验完全没被用上——所谓"AI自动核验"名不副实。改为调用
           `ai_auto_inspect` 真正跑一遍规则检查，只有通过的才标记通过。
        """
        from app.core.preview_validation_loop import preview_validation_loop
        clips = req.params.get("clips", [])
        auto_pass = req.params.get("auto_preview_pass", True)
        preview_validation_loop.clear()
        registered = preview_validation_loop.load_clips_to_timeline(
            clips, request_id=req.request_id)
        inspect_results = []
        if auto_pass:
            for c in clips:
                cid = c.get("clip_id") or c.get("id")
                if cid:
                    inspect_results.append(preview_validation_loop.ai_auto_inspect(cid))
        status = preview_validation_loop.get_preview_status()
        ok = registered > 0
        error = None if ok else "无片段登记"
        return CapabilityResult(req.request_id, ok,
                                output={**status, "inspect_results": inspect_results},
                                error=error)

    def regenerate_clip(self, req: CapabilityRequest) -> CapabilityResult:
        """局部重生成：预览发现问题后，重生成替换指定片段"""
        from app.core.preview_validation_loop import preview_validation_loop
        clip_id = req.params.get("clip_id")
        new_prompt = req.params.get("new_prompt", "")
        provider = req.params.get("provider", "auto")
        if not clip_id:
            return CapabilityResult(req.request_id, False, error="缺少 clip_id")
        new_clip = preview_validation_loop.request_regenerate(
            clip_id, new_prompt=new_prompt, provider=provider)
        if new_clip:
            return CapabilityResult(req.request_id, True, output=new_clip)
        return CapabilityResult(req.request_id, False, error="重生成失败或超上限")

    def score(self, req: CapabilityRequest) -> CapabilityResult:
        """五维量化打分：100分制 + S/A/B/C/D分级 + D级剔除"""
        from app.core.five_dimension_scorer import five_dimension_scorer
        clips = req.params.get("clips", [])
        features_list = [
            five_dimension_scorer.extract_features_from_clip({
                "id": c.get("clip_id") or c.get("id"),
                "path": c.get("path", ""),
                "duration": c.get("duration", 5.0),
                "quality_scores": c.get("quality_scores", {}),
            })
            for c in clips
        ]
        results = five_dimension_scorer.score_batch(features_list)
        return CapabilityResult(req.request_id, True,
                                output={"results": [r.to_dict() for r in results]})

    def generate_script(self, req: CapabilityRequest) -> CapabilityResult:
        """剪辑创意脚本生成：根据打分结果生成最优剪辑脚本"""
        from app.core.editing_script_generator import editing_script_generator
        scored = req.params.get("scored_clips", [])
        script = editing_script_generator.generate(
            scored_clips=scored,
            target_duration=float(req.params.get("target_duration", 60.0)),
            platform=req.params.get("platform", "douyin"),
            request_id=req.request_id,
        )
        return CapabilityResult(req.request_id, True, output=script.to_dict())

    def execute_editing(self, req: CapabilityRequest) -> CapabilityResult:
        """
        执行精修剪辑 + 成片输出
        调用 EditorModule 的精剪方法（步骤11新增），失败回退提示手动精剪。
        """
        editor = self._get_editor()
        editing_script = req.params.get("editing_script", {})
        if editor is None:
            return CapabilityResult(req.request_id, False,
                                    error="EditorModule 未就绪，请手动精剪")
        # 优先调用 EditorModule 新增的精剪入口
        handler = getattr(editor, "agent_execute_pipeline_editing", None)
        if not callable(handler):
            return CapabilityResult(req.request_id, False,
                                    error="EditorModule 暂未实现精剪入口，请手动精剪")
        try:
            output_path = handler(editing_script, req.params.get("session_id", ""))
            if output_path:
                # 修复：这里此前用的 key 是 "output_path"，但 UI 侧
                # （editor_module.py 手动精剪结果展示 / pipeline 结果卡片）
                # 全部统一读 "final_video_path"（其它 pipeline 结果 dict
                # 也都用这个 key）。key 对不上导致 UI 永远读到空字符串，
                # 即使精剪真的成功也只显示"已执行精剪"这种不带路径的模糊
                # 文案，看起来像没有产出成片。
                return CapabilityResult(req.request_id, True,
                                        output={"final_video_path": output_path,
                                                "output_path": output_path})
            return CapabilityResult(req.request_id, False,
                                    error="精剪未产出成片，请检查剪辑模块")
        except Exception as e:
            logger.exception("[pipeline.execute_editing] 执行异常")
            return CapabilityResult(req.request_id, False, error=str(e))

    def run_full(self, req: CapabilityRequest) -> CapabilityResult:
        """全链路一键执行：分流→生成/剪辑→预览→打分→脚本→精剪→成片"""
        from app.core.agent_pipeline_orchestrator import agent_pipeline_orchestrator
        session = agent_pipeline_orchestrator.execute(
            materials=req.params.get("materials", []),
            creative_brief=req.params.get("creative_brief", ""),
            platform=req.params.get("platform", "douyin"),
            target_duration=float(req.params.get("target_duration", 30.0)),
            clip_duration=float(req.params.get("clip_duration", 5.0)),
            provider=req.params.get("provider", "auto"),
            auto_preview_pass=req.params.get("auto_preview_pass", True),
            session_id=req.request_id,
        )
        return CapabilityResult(req.request_id, session.success,
                                output=session.to_dict(), error=session.error)


# ────────────── 注册入口 ──────────────
def register_builtin_handlers(dispatcher: CapabilityDispatcher,
                              editor_module_ref: Optional[Callable[[], Any]] = None) -> None:
    """
    注册所有内置能力到 dispatcher

    参数：
        dispatcher: CapabilityDispatcher 实例
        editor_module_ref: 由 EditorModule 在面板创建时传入 lambda: self；
                          若为 None，则剪辑类能力返回 "未就绪"，但其他能力仍可用
    """
    if editor_module_ref is None:
        editor_module_ref = lambda: None

    ext_handlers = ExtensionCapabilityHandlers()
    model_handlers = ModelCapabilityHandlers()
    editor_handlers = EditorCapabilityHandlers(editor_module_ref)
    workflow_handlers = WorkflowCapabilityHandlers()
    account_handlers = AccountCapabilityHandlers()
    pipeline_handlers = PipelineCapabilityHandlers(editor_module_ref)

    # 拓展模块
    dispatcher.register("ext.run_extension", CapabilityCategory.EXTENSION,
                        ext_handlers.run_extension, "运行拓展中心插件/Skill/MCP")
    dispatcher.register("ext.run_skill", CapabilityCategory.EXTENSION,
                        ext_handlers.run_skill, "通过 SkillEngine 执行 Skill")
    dispatcher.register("ext.list_tools", CapabilityCategory.EXTENSION,
                        ext_handlers.list_tools, "列出所有可用拓展工具")

    # 模型模块
    dispatcher.register("model.chat", CapabilityCategory.MODEL,
                        model_handlers.chat, "调用指定 AI 提供者")
    dispatcher.register("model.chat_with_fallback", CapabilityCategory.MODEL,
                        model_handlers.chat_with_fallback, "智能降级调用 AI")
    dispatcher.register("model.list_models", CapabilityCategory.MODEL,
                        model_handlers.list_models, "列出可用 AI 提供者")

    # 剪辑模块
    dispatcher.register("editor.split_clip", CapabilityCategory.EDITOR,
                        editor_handlers.split_clip, "切分片段")
    dispatcher.register("editor.apply_filter", CapabilityCategory.EDITOR,
                        editor_handlers.apply_filter, "应用滤镜")
    dispatcher.register("editor.add_transition", CapabilityCategory.EDITOR,
                        editor_handlers.add_transition, "添加转场")
    dispatcher.register("editor.get_timeline_context", CapabilityCategory.EDITOR,
                        editor_handlers.get_timeline_context, "获取时间线上下文")
    dispatcher.register("editor.ripple_delete_range", CapabilityCategory.EDITOR,
                        editor_handlers.ripple_delete_range, "波纹删除时间线区间")
    dispatcher.register("editor.suggest_cleanup", CapabilityCategory.EDITOR,
                        editor_handlers.suggest_cleanup, "建议去水词/静音并确认后执行")

    # 多任务调度
    dispatcher.register("workflow.start", CapabilityCategory.WORKFLOW,
                        workflow_handlers.start_workflow, "启动全链路工作流")
    dispatcher.register("workflow.submit_batch", CapabilityCategory.WORKFLOW,
                        workflow_handlers.submit_batch_task, "提交批量任务")

    # 账号运营
    dispatcher.register("account.collect_data", CapabilityCategory.ACCOUNT,
                        account_handlers.collect_data, "采集账号数据")
    dispatcher.register("account.optimize_strategy", CapabilityCategory.ACCOUNT,
                        account_handlers.optimize_strategy, "生成优化建议")
    dispatcher.register("account.publish", CapabilityCategory.ACCOUNT,
                        account_handlers.publish, "发布作品")

    # Agent 全链路闭环
    dispatcher.register("pipeline.route", CapabilityCategory.PIPELINE,
                        pipeline_handlers.route, "业务分流：AI生成/素材剪辑")
    dispatcher.register("pipeline.generate", CapabilityCategory.PIPELINE,
                        pipeline_handlers.generate, "AI视频生成业务线")
    dispatcher.register("pipeline.preview_validate", CapabilityCategory.PIPELINE,
                        pipeline_handlers.preview_validate, "预览校验：轨道排布+画面质检")
    dispatcher.register("pipeline.regenerate_clip", CapabilityCategory.PIPELINE,
                        pipeline_handlers.regenerate_clip, "局部重生成替换片段")
    dispatcher.register("pipeline.score", CapabilityCategory.PIPELINE,
                        pipeline_handlers.score, "五维量化打分+分级筛选")
    dispatcher.register("pipeline.generate_script", CapabilityCategory.PIPELINE,
                        pipeline_handlers.generate_script, "剪辑创意脚本生成")
    dispatcher.register("pipeline.execute_editing", CapabilityCategory.PIPELINE,
                        pipeline_handlers.execute_editing, "精修剪辑+成片输出")
    dispatcher.register("pipeline.run_full", CapabilityCategory.PIPELINE,
                        pipeline_handlers.run_full, "全链路一键执行")

    logger.info("[capability_handlers] 已注册 25 个内置能力")

    # ── 左右脑神经链接：让 AgentBrain 感知所有已注册 capability ──
    try:
        from app.core.agent_brain import agent_brain
        agent_brain.sync_from_dispatcher(dispatcher)
    except Exception as e:
        logger.debug(f"[AgentBrain] 同步 dispatcher 失败: {e}")
