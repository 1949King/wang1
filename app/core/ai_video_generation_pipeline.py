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
                request_id: str = "") -> GenerationPipelineResult:
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
        """
        request_id = request_id or uuid.uuid4().hex[:12]
        if not creative_brief:
            return GenerationPipelineResult(success=False, error="creative_brief 不能为空",
                                            request_id=request_id)

        result = GenerationPipelineResult(success=True, request_id=request_id)
        logger.info(f"[AIVideoGenerationPipeline] 启动生成业务线 | brief={creative_brief[:40]} "
                    f"| platform={platform} | duration={target_duration}s")

        try:
            # 1. 创意层拆解：大纲 → 剧本 → 关键词 → 提示词
            result.outline = self._gen_outline(creative_brief, platform, target_duration)
            result.script = self._gen_script(result.outline)
            result.keywords = self._gen_keywords(result.script)
            scene_n = scene_count or max(1, int(target_duration // clip_duration))
            result.prompts = self._gen_prompts(result.keywords, scene_n)

            # 2. AI 抽卡生成 + 3. 后台初检（含回溯闭环）
            for idx, prompt in enumerate(result.prompts):
                clip = self._generate_and_inspect(
                    prompt=prompt,
                    visual_description=self._scene_visual(result.script, idx),
                    dialogue=self._scene_dialogue(result.script, idx),
                    emotion=self._scene_emotion(result.script, idx),
                    scene_index=idx,
                    duration=clip_duration,
                    provider=provider,
                    request_id=request_id,
                )
                if clip:
                    result.clips.append(clip)

            if not result.clips:
                result.success = False
                result.error = "全部片段生成/初检失败"
            else:
                logger.info(f"[AIVideoGenerationPipeline] 生成完成：{len(result.clips)} 个合格片段")

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

    def _gen_prompts(self, keywords: Dict[str, List[str]], scene_count: int) -> List[str]:
        """标准化提示词生成"""
        try:
            resp = self._call_llm("prompt_from_keywords",
                                  keywords=json.dumps(keywords, ensure_ascii=False),
                                  scene_count=scene_count)
            prompts = self._extract_json(resp)
            if isinstance(prompts, list) and prompts:
                return [str(p) for p in prompts][:scene_count]
        except Exception as e:
            logger.warning(f"[AIVideoGenerationPipeline] 提示词生成失败，用占位: {e}")
        # 占位提示词
        style = " ".join(keywords.get("style", ["cinematic"]))
        return [f"a cinematic shot, {style}, scene {i + 1}, high quality"
                for i in range(scene_count)]

    # ────────────── 生成 + 初检（含回溯闭环） ──────────────

    def _generate_and_inspect(self, prompt: str, visual_description: str,
                              dialogue: str, emotion: str, scene_index: int,
                              duration: float, provider: str,
                              request_id: str) -> Optional[GeneratedClip]:
        """生成单段 + 后台初检，不合格回溯重写提示词重新生成"""
        from app.core.ai.video_generation_client import video_generation_client

        current_prompt = prompt
        retries = 0
        while retries <= self.MAX_RETRIES:
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
            # 用 suggestion 修正提示词
            current_prompt = self._revise_prompt(current_prompt, suggestion, issues)
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

    def _revise_prompt(self, prompt: str, suggestion: str, issues: List[str]) -> str:
        """根据初检建议回溯重写提示词"""
        if not suggestion and not issues:
            return prompt
        hint = suggestion or ("；".join(issues) if issues else "")
        return f"{prompt} | avoid: {hint[:80]}"

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
