"""
AI 视频生成业务线 (AIVideoGenerationPipeline)
============================================
对应「业务线1：AI 视频生成完整全流程」。

完整步骤（用户定稿）：
  1. 创意层拆解：大纲构思 → 完整剧本 → 关键词提取 → 标准化提示词
  2. AI 抽卡生成多段原始画面片段
  3. Agent 后台初检：穿模/手部畸形/肢体错误/动作逻辑混乱/画风崩坏
     - 不合格 → 回溯重写提示词 → 重新生成（最多 max_retries 次）
     - 合格   → 全部送入剪辑模块轨道
  4.（预览校验/打分/精剪由后续模块统一处理，本管线止于「合格片段 + 元数据」）

设计原则：
  - 单例，纯逻辑（core 层），不写 UI；调用方在 worker 线程调用。
  - 失败回退：LLM 不可用 → 用模板占位；生成失败 → 占位片段；保证流程可演示。
  - 质检不合格广播 GENERATION_INSPECTION_FAILED，由 AgentFeedbackBridge 回流 Agent。

架构位置：
  AgentPipelineRouter(GENERATION) → AIVideoGenerationPipeline → 合格片段 → 统一汇合流程
"""
from __future__ import annotations
import json
import logging
import re
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# P1-3 取消异常：gen-jobs 任务线程内抛出；无 app 包的独立加载场景不可能出现，
# 空元组 except 子句永不匹配（等价于没有该子句）。
try:
    from app.core.canvas_gen_jobs import GenCancelled
except Exception:  # noqa: BLE001 - 独立加载场景不可能出现取消
    GenCancelled = ()  # type: ignore[assignment]


def _job_ctx():
    """取管线任务上下文（pipeline_jobs：阶段上报/取消检查）。

    gen-jobs 任务线程内非 None；直连调用（无任务底座）返回 None，
    所有上报/取消检查随之静默跳过——既有调用方行为零变化。
    """
    try:
        from app.core.ai import pipeline_jobs
        return pipeline_jobs
    except Exception:  # noqa: BLE001
        return None


@dataclass
class GeneratedClip:
    """单个 AI 生成片段（含元数据，供打分/剪辑使用）"""
    clip_id: str
    path: str
    prompt: str                       # 生成用的标准化提示词
    visual_description: str = ""      # 画面描述（来自剧本）
    dialogue: str = ""                # 台词
    emotion: str = ""                 # 情绪标记
    scene_index: int = 0              # 场景序号
    duration: float = 5.0
    inspection_passed: bool = False   # 后台初检是否通过
    inspection_issues: List[str] = field(default_factory=list)
    retries: int = 0                  # 回溯次数
    # 如实标注：LLM 不可用/调用异常/返回无法解析时，_inspect 会"默认放行"以
    # 避免整条流水线卡死，但那种放行不是真的跑过穿模/畸形检测——下游报告/
    # UI 应据此区分"真正核验通过"和"未能核验、直接放行"两种情况。
    inspection_skipped: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "clip_id": self.clip_id, "path": self.path, "prompt": self.prompt,
            "visual_description": self.visual_description, "dialogue": self.dialogue,
            "emotion": self.emotion, "scene_index": self.scene_index,
            "duration": self.duration, "inspection_passed": self.inspection_passed,
            "inspection_issues": self.inspection_issues, "retries": self.retries,
            "inspection_skipped": self.inspection_skipped,
        }


@dataclass
class GenerationPipelineResult:
    """AI 生成业务线产出"""
    success: bool
    clips: List[GeneratedClip] = field(default_factory=list)
    outline: Dict[str, Any] = field(default_factory=dict)    # 大纲
    script: List[Dict[str, Any]] = field(default_factory=list)  # 剧本
    keywords: Dict[str, List[str]] = field(default_factory=dict)  # 关键词
    prompts: List[str] = field(default_factory=list)         # 标准化提示词
    error: Optional[str] = None
    request_id: str = ""
    cost_estimate: float = 0.0   # 生成前报价（P1-1，估算值；供 UI/审计展示）


class AIVideoGenerationPipeline:
    """
    AI 视频生成业务线 —— 单例

    使用方式：
        from app.core.ai_video_generation_pipeline import ai_video_generation_pipeline
        result = ai_video_generation_pipeline.execute(
            creative_brief="一个关于城市夜景的短视频",
            platform="douyin", target_duration=30.0,
        )
    """
    _instance: Optional['AIVideoGenerationPipeline'] = None
    _lock = threading.Lock()

    # 回溯重试上限（避免无限循环）
    MAX_RETRIES = 2

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
    def get_instance(cls) -> 'AIVideoGenerationPipeline':
        return cls()

    # ────────────── 主入口 ──────────────

    def execute(self, creative_brief: str,
                platform: str = "douyin",
                target_duration: float = 30.0,
                scene_count: Optional[int] = None,
                clip_duration: float = 5.0,
                provider: str = "auto",
                request_id: str = "",
                guards: Optional[Dict[str, Any]] = None) -> GenerationPipelineResult:
        """
        执行 AI 视频生成业务线全流程

        参数：
            creative_brief:  用户创意简报
            platform:        目标平台
            target_duration: 目标总时长（秒）
            scene_count:     场景数（缺省按时长 / clip_duration 推算）
            clip_duration:   单段时长
            provider:        视频生成 provider（auto/seedance/cogvideo/local）
            request_id:      会话 id
            guards:          **生成质量守护上下文**（可选，V4.33.2）。传入后：
                             ① 生成前自动把守护约束注入每个提示词（角色卡 / 道具结构 / 表情幅度）；
                             ② 初检时叠加守护的结构化质检（道具 / 角色漂移）。
                             形如 ``{"character": {...}, "prop": {...}, "expression": {...}}``；
                             缺省 None 时行为与接入前完全一致。
                             **成本提示（V4.33.5）**：质检里的 LLM 聚焦审核**默认关** ——
                             它在回溯循环里每轮都会跑，默认开会线性增加调用费用。
                             需要时在 guards 里加 ``"use_llm": true`` 显式开启。
        """
        request_id = request_id or uuid.uuid4().hex[:12]
        if not creative_brief:
            return GenerationPipelineResult(success=False, error="creative_brief 不能为空",
                                            request_id=request_id)

        result = GenerationPipelineResult(success=True, request_id=request_id)
        ctx = _job_ctx()  # P1-3：任务上下文（无任务时为 None，全部静默）
        logger.info(f"[AIVideoGenerationPipeline] 启动生成业务线 | brief={creative_brief[:40]} "
                    f"| platform={platform} | duration={target_duration}s")

        try:
            if ctx:
                ctx.pipeline_stage("creative", "创意层拆解（大纲→剧本→关键词→提示词）")
            # 1. 创意层拆解：大纲 → 剧本 → 关键词 → 提示词
            result.outline = self._gen_outline(creative_brief, platform, target_duration)
            result.script = self._gen_script(result.outline)
            result.keywords = self._gen_keywords(result.script)
            scene_n = scene_count or max(1, int(target_duration // clip_duration))
            result.prompts = self._gen_prompts(result.keywords, scene_n, guards=guards)

            # 生成前报价（P1-1）：预估花费写进日志与结果（只读预演，不消耗额度）
            try:
                from app.core.ai.video_generation_client import video_generation_client

                _q = video_generation_client.quote(
                    provider, count=scene_n, duration=clip_duration)
                result.cost_estimate = float(_q.get("cost_estimate") or 0.0)
                logger.info(
                    "[AIVideoGenerationPipeline] 生成前报价：%s × %d 段 ≈ ¥%.2f（%s）",
                    _q.get("provider"), scene_n, result.cost_estimate,
                    _q.get("reason") or "正常")
            except Exception:
                logger.debug("[AIVideoGenerationPipeline] 报价失败（不阻断生成）",
                             exc_info=True)

            # 2. AI 抽卡生成 + 3. 后台初检（含回溯闭环）
            total_scenes = len(result.prompts)
            for idx, prompt in enumerate(result.prompts):
                if ctx:
                    ctx.raise_if_cancelled()  # P1-3：场景与场景之间响应取消
                    ctx.pipeline_stage("generation", f"生成片段 {idx + 1}/{total_scenes}")
                clip = self._generate_and_inspect(
                    prompt=prompt,
                    visual_description=self._scene_visual(result.script, idx),
                    dialogue=self._scene_dialogue(result.script, idx),
                    emotion=self._scene_emotion(result.script, idx),
                    scene_index=idx,
                    duration=clip_duration,
                    provider=provider,
                    request_id=request_id,
                    guards=guards,
                )
                if clip:
                    result.clips.append(clip)
                    if ctx and total_scenes > 0:
                        # 诚实进度：只报真实完成数（段内拿不到信号，不伪造平滑条）
                        ctx.pipeline_progress(round((idx + 1) * 100.0 / total_scenes))

            if not result.clips:
                result.success = False
                result.error = "全部片段生成/初检失败"
            else:
                logger.info(f"[AIVideoGenerationPipeline] 生成完成：{len(result.clips)} 个合格片段")

        except GenCancelled:
            # 取消是控制流：交任务层标记 cancelled（结果丢弃不落盘），不吞成执行失败
            raise
        except Exception as e:
            logger.exception(f"[AIVideoGenerationPipeline] 执行异常")
            result.success = False
            result.error = str(e)

        return result

    # ────────────── 创意层拆解 ──────────────

    def _gen_outline(self, brief: str, platform: str, duration: float) -> Dict[str, Any]:
        """大纲构思"""
        try:
            resp = self._call_llm("creative_outline",
                                  creative_brief=brief, platform=platform,
                                  target_duration=int(duration))
            outline = self._extract_json(resp)
            if isinstance(outline, dict):
                return outline
        except Exception as e:
            logger.warning(f"[AIVideoGenerationPipeline] 大纲生成失败，用占位: {e}")
        # 占位大纲
        return {
            "title": brief[:20] or "AI生成作品",
            "theme": brief[:30] or "通用",
            "audience": "通用受众",
            "emotion_curve": ["平静", "起伏", "高潮"],
            "scenes": [f"场景{i + 1}" for i in range(3)],
            "estimated_duration": int(duration),
        }

    def _gen_script(self, outline: Dict[str, Any]) -> List[Dict[str, Any]]:
        """分集剧本生成"""
        try:
            resp = self._call_llm("script_from_outline", outline=json.dumps(outline, ensure_ascii=False))
            script = self._extract_json(resp)
            if isinstance(script, list):
                return script
            if isinstance(script, dict) and "scenes" in script:
                return script["scenes"]
        except Exception as e:
            logger.warning(f"[AIVideoGenerationPipeline] 剧本生成失败，用占位: {e}")
        # 占位剧本（基于大纲场景数）
        scenes = outline.get("scenes", ["场景1", "场景2", "场景3"])
        return [
            {"scene": i + 1, "visual": f"画面描述{i + 1}",
             "dialogue": "", "shot": "中景", "emotion": "中性"}
            for i in range(len(scenes))
        ]

    def _gen_keywords(self, script: List[Dict[str, Any]]) -> Dict[str, List[str]]:
        """关键词提取"""
        try:
            resp = self._call_llm("keywords_from_script",
                                  script=json.dumps(script, ensure_ascii=False))
            kw = self._extract_json(resp)
            if isinstance(kw, dict):
                return kw
        except Exception as e:
            logger.warning(f"[AIVideoGenerationPipeline] 关键词提取失败，用占位: {e}")
        return {"plot": ["故事"], "emotion": ["中性"], "shot": ["中景"], "style": ["写实"]}

    def _gen_prompts(self, keywords: Dict[str, List[str]], scene_count: int,
                     guards: Optional[Dict[str, Any]] = None) -> List[str]:
        """标准化提示词生成（传入 ``guards`` 时**自动注入守护约束**）"""
        prompts: List[str] = []
        try:
            resp = self._call_llm("prompt_from_keywords",
                                  keywords=json.dumps(keywords, ensure_ascii=False),
                                  scene_count=scene_count)
            got = self._extract_json(resp)
            if isinstance(got, list) and got:
                prompts = [str(p) for p in got][:scene_count]
        except Exception as e:
            logger.warning(f"[AIVideoGenerationPipeline] 提示词生成失败，用占位: {e}")
        if not prompts:
            # 占位提示词
            style = " ".join(keywords.get("style", ["cinematic"]))
            prompts = [f"a cinematic shot, {style}, scene {i + 1}, high quality"
                       for i in range(scene_count)]

        # ── 生成前守护：把角色卡 / 道具结构 / 表情幅度约束注进每个提示词 ──
        if guards:
            prompts = [self._apply_guard_to_prompt(p, guards) for p in prompts]
        return prompts

    def _apply_guard_to_prompt(self, prompt: str, guards: Dict[str, Any]) -> str:
        """把守护约束注入单个提示词；守护层不可用时**原样返回**（诚实降级）。"""
        try:
            from app.core.ai.guard_pipeline import enhance_prompt

            out = enhance_prompt(prompt, guards=guards)
            if out.get("changed"):
                logger.info(f"[AIVideoGenerationPipeline] 已注入守护约束：{out.get('parts')}")
            return str(out.get("prompt") or prompt)
        except Exception:
            logger.debug("[AIVideoGenerationPipeline] 守护约束注入失败，用原提示词", exc_info=True)
            return prompt

    # ────────────── 生成 + 初检（含回溯闭环） ──────────────

    def _generate_and_inspect(self, prompt: str, visual_description: str,
                              dialogue: str, emotion: str, scene_index: int,
                              duration: float, provider: str,
                              request_id: str,
                              guards: Optional[Dict[str, Any]] = None) -> Optional[GeneratedClip]:
        """生成单段 + 后台初检，不合格回溯重写提示词重新生成

        传 ``guards`` 时，初检会**叠加守护的结构化质检**（见 ``_guard_inspect``）：
        守护不通过 → 问题并入 ``issues`` → 走同一条回溯重写路径。
        """
        from app.core.ai.video_generation_client import video_generation_client

        ctx = _job_ctx()
        current_prompt = prompt
        retries = 0
        while retries <= self.MAX_RETRIES:
            if ctx:
                ctx.raise_if_cancelled()  # P1-3：回溯重试之间也响应取消
            # 生成
            paths = video_generation_client.generate(
                prompt=current_prompt, duration=duration, count=1, provider=provider,
            )
            if not paths:
                logger.warning(f"[AIVideoGenerationPipeline] 场景{scene_index + 1} 生成失败 (retries={retries})")
                retries += 1
                continue

            path = paths[0]
            # 后台初检
            passed, issues, suggestion, skipped = self._inspect(current_prompt, visual_description)
            # 生成后守护：叠加结构化质检（不通过则并入 issues，走同一条回溯）
            guard_hint = ""
            if guards:
                g_ok, g_issues, guard_hint = self._guard_inspect(current_prompt, guards)
                if not g_ok:
                    issues = list(issues or []) + list(g_issues)
                    passed = False
                    skipped = False
                    logger.info(f"[AIVideoGenerationPipeline] 场景{scene_index + 1} 守护质检未过：{g_issues}")
            if passed:
                return GeneratedClip(
                    clip_id=uuid.uuid4().hex[:10], path=path, prompt=current_prompt,
                    visual_description=visual_description, dialogue=dialogue,
                    emotion=emotion, scene_index=scene_index, duration=duration,
                    inspection_passed=True, retries=retries, inspection_skipped=skipped,
                )

            # 不合格：广播 + 回溯
            self._emit_inspection_failed(scene_index, current_prompt, issues, suggestion, request_id)
            logger.info(f"[AIVideoGenerationPipeline] 场景{scene_index + 1} 初检未过，回溯重写提示词 "
                        f"(retries={retries}): {issues}")
            # 用 suggestion（+ 守护的明确提示）修正提示词
            current_prompt = self._revise_prompt(current_prompt, suggestion, issues,
                                                 guard_hint=guard_hint)
            retries += 1

        # 回溯次数用尽仍失败，返回未通过片段（交由上层决定是否剔除）
        logger.warning(f"[AIVideoGenerationPipeline] 场景{scene_index + 1} 回溯 {self.MAX_RETRIES} 次仍未通过初检")
        if paths:
            return GeneratedClip(
                clip_id=uuid.uuid4().hex[:10], path=paths[0], prompt=current_prompt,
                visual_description=visual_description, dialogue=dialogue,
                emotion=emotion, scene_index=scene_index, duration=duration,
                inspection_passed=False, inspection_issues=issues, retries=retries,
            )
        return None

    def _inspect(self, prompt: str, visual_description: str) -> tuple:
        """后台初检：检测穿模/手部畸形/肢体错误/逻辑混乱/画风崩坏

        返回 (passed, issues, suggestion, skipped)。skipped=True 表示
        LLM 不可用/调用异常/返回无法解析，本次根本没有跑真正的初检，
        只是为了不卡死流水线而"默认放行"——调用方需要把这个信号透传给
        GeneratedClip.inspection_skipped，不能让用户以为每个片段都真的
        过了穿模/畸形检测。
        """
        try:
            resp = self._call_llm("generation_inspection",
                                  prompt=prompt, visual_description=visual_description)
            data = self._extract_json(resp)
            if isinstance(data, dict):
                passed = bool(data.get("passed", True))
                issues = data.get("issues", []) or []
                suggestion = data.get("suggestion", "")
                return passed, issues, suggestion, False
            logger.debug("[AIVideoGenerationPipeline] 初检返回无法解析为 JSON，默认放行（未真正核验）")
        except Exception as e:
            logger.debug(f"[AIVideoGenerationPipeline] 初检调用失败，默认放行（未真正核验）: {e}")
        # LLM 不可用/解析失败时默认通过（保证流程不卡死），但如实标记为「未核验」
        return True, [], "", True

    @staticmethod
    def _guard_inspect(prompt: str, guards: Dict[str, Any]) -> tuple:
        """生成后**守护质检**（委托 ``guard_pipeline.augment_inspection``）。

        返回 ``(ok, issues, revise_hint)``。守护层不可用时**默认通过**（不拖垮管线）。

        ⚠️ **默认不调 LLM**（V4.33.5）：本函数在回溯循环里**每轮**都会跑，
        若默认调 LLM，``MAX_RETRIES`` 轮就是同样多次额外费用。规则层（道具 / 角色漂移）零成本；
        需要更精准审核时，在 guards 里写 ``{"use_llm": true}`` 显式开启。
        """
        try:
            from app.core.ai.guard_pipeline import augment_inspection

            r = augment_inspection(prompt, guards=guards,
                                   use_llm=bool(guards.get("use_llm", False)))
            return (bool(r.get("ok")), list(r.get("issues") or []),
                    str(r.get("revise_hint") or ""))
        except Exception:
            logger.debug("[AIVideoGenerationPipeline] 守护质检失败，默认通过", exc_info=True)
            return True, [], ""

    def _revise_prompt(self, prompt: str, suggestion: str, issues: List[str],
                       guard_hint: str = "") -> str:
        """根据初检建议（+ 守护的明确提示）回溯重写提示词"""
        hint = suggestion or ("；".join(issues) if issues else "")
        # 守护提示是「针对守护维度的明确规避项」，优先并入（原实现只有一句笼统 avoid）
        if guard_hint:
            hint = f"{hint}；{guard_hint}" if hint else guard_hint
        if not hint:
            return prompt
        return f"{prompt} | avoid: {hint[:160]}"

    # ────────────── LLM 调用封装 ──────────────

    def _call_llm(self, template_key: str, **kwargs) -> str:
        """调用 LLM（chat_with_fallback），返回文本"""
        from app.core.ai.prompt_templates import PROMPT_TEMPLATES
        tpl = PROMPT_TEMPLATES.get(template_key)
        if not tpl:
            return ""
        system = tpl["system"]
        user = tpl["user"].format(**kwargs) if kwargs else tpl["user"]
        try:
            from app.core.ai_engine import ai_engine
            chunks = list(ai_engine.chat_with_fallback(
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}],
            ))
            return "".join(chunks) if chunks else ""
        except Exception as e:
            logger.debug(f"[AIVideoGenerationPipeline] LLM 调用失败 ({template_key}): {e}")
            return ""

    @staticmethod
    def _extract_json(text: str) -> Any:
        """从 LLM 返回文本中提取 JSON（容错：提取首个 {}/[] 块）"""
        if not text:
            return None
        text = text.strip()
        # 直接尝试
        try:
            return json.loads(text)
        except Exception as e:
            logger.debug(f"[AIVideoGenerationPipeline] JSON直接解析失败: {e}")
        # 提取首个 JSON 块
        m = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception as e:
                logger.debug(f"[AIVideoGenerationPipeline] JSON块解析失败: {e}")
                return None
        return None

    # ────────────── 辅助 ──────────────

    @staticmethod
    def _scene_visual(script: List[Dict[str, Any]], idx: int) -> str:
        if idx < len(script):
            return str(script[idx].get("visual", ""))
        return ""

    @staticmethod
    def _scene_dialogue(script: List[Dict[str, Any]], idx: int) -> str:
        if idx < len(script):
            return str(script[idx].get("dialogue", ""))
        return ""

    @staticmethod
    def _scene_emotion(script: List[Dict[str, Any]], idx: int) -> str:
        if idx < len(script):
            return str(script[idx].get("emotion", ""))
        return ""

    def _emit_inspection_failed(self, scene_index: int, prompt: str,
                                issues: List[str], suggestion: str,
                                request_id: str) -> None:
        """广播初检失败事件，由 AgentFeedbackBridge 回流 Agent"""
        try:
            from app.modules.lego.core import EventBus, EventType
            EventBus.get_instance().emit(
                EventType.GENERATION_INSPECTION_FAILED,
                {
                    "scene_index": scene_index,
                    "prompt": prompt[:80],
                    "issues": issues,
                    "suggestion": suggestion,
                    "request_id": request_id,
                    "description": f"场景{scene_index + 1}初检未过: {', '.join(issues) if issues else '未知问题'}",
                    "severity": "high",
                },
                source="AIVideoGenerationPipeline",
            )
        except Exception as e:
            logger.debug(f"[AIVideoGenerationPipeline] emit INSPECTION_FAILED 失败: {e}")


# 全局单例便捷引用
ai_video_generation_pipeline = AIVideoGenerationPipeline.get_instance()
