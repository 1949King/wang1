"""
剪辑创意脚本生成器 (EditingScriptGenerator)
=========================================
对应流程图中「AI 生成最优剪辑创意脚本」一节。

职责：
  根据五维打分结果，生成最优剪辑创意脚本，包含：
    - 镜头顺序（按分数优先级，剔除 D 级）
    - 转场方案（fade/cut/zoom/slide）
    - 卡点位置（与节奏对齐）
    - 配乐段落
    - 字幕布局
    - 节奏快慢（fast/normal/slow）

设计原则：
  - 单例，纯逻辑（core 层）。
  - 优先调用 LLM（editing_script_from_scores 模板）；失败回退到基于分数的规则排序。
  - 广播 EDITING_SCRIPT_GENERATED 事件，供精剪模块消费。
  - 不直接操作剪辑模块，脚本生成后由 orchestrator 通过 CapabilityDispatcher 驱动精剪。

架构位置：
  五维打分完成 → EditingScriptGenerator → 剪辑创意脚本 → 精修剪辑
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
class EditingScript:
    """剪辑创意脚本"""
    clip_order: List[str] = field(default_factory=list)        # 镜头顺序（clip_id 列表）
    transitions: Dict[str, str] = field(default_factory=dict)  # clip_id → 转场类型
    beat_points: List[float] = field(default_factory=list)     # 卡点时间（秒）
    bgm: str = ""                                              # 配乐风格
    bgm_segments: List[Dict[str, Any]] = field(default_factory=list)  # 配乐段落
    subtitle_layout: str = "bottom_center"                     # 字幕布局
    pacing: str = "normal"                                     # fast/normal/slow
    pacing_curve: List[Dict[str, Any]] = field(default_factory=list)  # 节奏曲线
    rationale: str = ""                                        # 创意说明
    target_duration: float = 60.0
    platform: str = "douyin"
    dropped_clips: List[str] = field(default_factory=list)     # 被剔除的 D 级片段
    request_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "clip_order": self.clip_order,
            "transitions": self.transitions,
            "beat_points": self.beat_points,
            "bgm": self.bgm,
            "bgm_segments": self.bgm_segments,
            "subtitle_layout": self.subtitle_layout,
            "pacing": self.pacing,
            "pacing_curve": self.pacing_curve,
            "rationale": self.rationale,
            "target_duration": self.target_duration,
            "platform": self.platform,
            "dropped_clips": self.dropped_clips,
            "request_id": self.request_id,
        }


class EditingScriptGenerator:
    """
    剪辑创意脚本生成器 —— 单例

    使用方式：
        from app.core.editing_script_generator import editing_script_generator
        script = editing_script_generator.generate(
            scored_clips=[{"clip_id": "...", "weighted_score": 88, "grade": "A", ...}],
            target_duration=30.0, platform="douyin",
        )
    """
    _instance: Optional['EditingScriptGenerator'] = None
    _lock = threading.Lock()

    # 转场候选（与 editor_module 既有转场类型对齐）
    _TRANSITION_POOL = ["fade", "cut", "zoom", "slide", "dissolve"]

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
    def get_instance(cls) -> 'EditingScriptGenerator':
        return cls()

    # ────────────── 主入口 ──────────────

    def generate(self, scored_clips: List[Dict[str, Any]],
                 target_duration: float = 60.0,
                 platform: str = "douyin",
                 request_id: str = "") -> EditingScript:
        """
        根据打分结果生成剪辑创意脚本

        参数：
            scored_clips: 五维打分结果列表，每项形如：
                          {"clip_id", "weighted_score", "grade", "should_drop",
                           "dimensions": {...}, "duration", "suggestions": [...]}
            target_duration: 目标总时长（秒）
            platform: 目标平台
            request_id: 会话 id
        """
        request_id = request_id or uuid.uuid4().hex[:12]
        if not scored_clips:
            return EditingScript(request_id=request_id, rationale="无可用镜头")

        # 剔除 D 级（should_drop=True）；兼容 clip_id / id 键，避免 KeyError
        dropped = [c.get("clip_id") or c.get("id") for c in scored_clips if c.get("should_drop")]
        usable = [c for c in scored_clips if not c.get("should_drop")]

        # 兜底：若全部为 D 级，降级使用全部素材并标记 degraded 模式
        all_clips_fallback = False
        if not usable and scored_clips:
            logger.warning(
                f"[EditingScriptGenerator] 全部 {len(scored_clips)} 镜头评级 D，"
                f"降级使用全部素材（degraded 模式）"
            )
            usable = list(scored_clips)  # 降级：全部可用
            all_clips_fallback = True

        if not usable:
            return EditingScript(request_id=request_id, dropped_clips=dropped,
                                 rationale="无可用素材")

        # 优先 LLM 生成；失败回退规则排序
        script = self._gen_via_llm(usable, target_duration, platform, request_id)
        if script is None:
            script = self._gen_via_rules(usable, target_duration, platform)

        script.dropped_clips = dropped
        script.request_id = request_id
        script.target_duration = target_duration
        script.platform = platform

        # 降级模式：记录到剪辑创意脚本供精剪层感知
        if all_clips_fallback:
            script.rationale = (script.rationale +
                                " [降级模式：全部素材为 D 级，建议精剪时加强转场/调色]")

        # 广播脚本生成完成 + 写记忆
        self._emit_script_generated(script)
        self._record_script(script)

        logger.info(f"[EditingScriptGenerator] 脚本生成完成：{len(script.clip_order)} 镜头，"
                    f"剔除 {len(dropped)} 个 D 级，节奏 {script.pacing}")
        return script

    # ────────────── LLM 生成 ──────────────

    def _gen_via_llm(self, usable: List[Dict[str, Any]],
                     target_duration: float, platform: str,
                     request_id: str) -> Optional[EditingScript]:
        """通过 LLM 生成剪辑脚本（失败返回 None，交由规则回退）"""
        try:
            from app.core.ai.prompt_templates import PROMPT_TEMPLATES
            tpl = PROMPT_TEMPLATES.get("editing_script_from_scores")
            if not tpl:
                return None
            # 精简打分数据，避免 token 过长；兼容 clip_id / id 键，跳过无 ID 片段
            scored_brief = [
                {
                    "clip_id": c.get("clip_id") or c.get("id"),
                    "score": round(float(c.get("weighted_score", 0)), 1),
                    "grade": c.get("grade"),
                    "duration": c.get("duration", 5.0),
                    "weak_dim": self._weakest_dim(c.get("dimensions", {})),
                }
                for c in usable
                if c.get("clip_id") or c.get("id")  # 跳过无 ID 片段，避免向 LLM 传 None
            ]
            user = tpl["user"].format(
                scored_clips=json.dumps(scored_brief, ensure_ascii=False),
                target_duration=int(target_duration),
                platform=platform,
            )
            from app.core.ai_engine import ai_engine
            chunks = list(ai_engine.chat_with_fallback(
                messages=[{"role": "system", "content": tpl["system"]},
                          {"role": "user", "content": user}],
            ))
            text = "".join(chunks) if chunks else ""
            data = self._extract_json(text)
            if not isinstance(data, dict):
                return None
            return self._parse_llm_script(data, usable, target_duration, platform)
        except Exception as e:
            logger.warning(f"[EditingScriptGenerator] LLM 生成失败，回退规则: {e}")
            return None

    def _parse_llm_script(self, data: Dict[str, Any],
                          usable: List[Dict[str, Any]],
                          target_duration: float, platform: str) -> EditingScript:
        """
        解析 LLM 返回的脚本 JSON。

        容错策略：
          1. 兼容 clip_id / id 键；
          2. clip_order 过滤后为空 → 用规则补全 clip_order/transitions，
             但保留 LLM 已解析的 pacing/bgm/subtitle_layout 等创意字段，避免数据丢失；
          3. 补全遗漏的高分镜头。
        """
        # 兼容 clip_id / id 键，构建有效 ID 集合
        valid_ids = {c.get("clip_id") or c.get("id") for c in usable}
        valid_ids.discard(None)

        clip_order = [str(c) for c in data.get("clip_order", [])]
        clip_order = [c for c in clip_order if c in valid_ids]

        # LLM 已解析的创意字段（无论 clip_order 是否为空都先取出，便于回退时保留）
        llm_transitions = {str(k): str(v) for k, v in data.get("transitions", {}).items()}
        llm_pacing = str(data.get("pacing", "normal"))
        llm_bgm = str(data.get("bgm", ""))
        llm_subtitle_layout = str(data.get("subtitle_layout", "bottom_center"))
        llm_beat_points = [float(x) for x in data.get("beat_points", [])]
        llm_bgm_segments = data.get("bgm_segments", []) if isinstance(data.get("bgm_segments"), list) else []
        llm_pacing_curve = data.get("pacing_curve", []) if isinstance(data.get("pacing_curve"), list) else []
        llm_rationale = str(data.get("rationale", ""))

        # clip_order 过滤后为空：用规则补全，避免脚本无镜头可用
        rule_fallback_used = False
        if not clip_order:
            logger.warning("[EditingScriptGenerator] LLM clip_order 过滤后为空，回退规则补全镜头顺序")
            rule_script = self._gen_via_rules(usable, target_duration, platform)
            clip_order = rule_script.clip_order
            llm_transitions = llm_transitions or rule_script.transitions
            rule_fallback_used = True

        # 补全遗漏的高分镜头
        existing = set(clip_order)
        for c in sorted(usable, key=lambda x: float(x.get("weighted_score", 0)), reverse=True):
            cid = c.get("clip_id") or c.get("id")
            if cid and cid not in existing:
                clip_order.append(cid)
                existing.add(cid)

        rationale = llm_rationale
        if rule_fallback_used:
            rationale = (rationale + " [clip_order 回退规则补全]").strip()

        return EditingScript(
            clip_order=clip_order,
            transitions=llm_transitions,
            beat_points=llm_beat_points,
            bgm=llm_bgm,
            bgm_segments=llm_bgm_segments,
            subtitle_layout=llm_subtitle_layout,
            pacing=llm_pacing,
            pacing_curve=llm_pacing_curve,
            rationale=rationale,
            target_duration=target_duration,
            platform=platform,
        )

    # ────────────── 规则回退生成 ──────────────

    def _gen_via_rules(self, usable: List[Dict[str, Any]],
                       target_duration: float, platform: str) -> EditingScript:
        """无 LLM 时基于分数的规则排序生成脚本"""
        # 按分数降序排
        sorted_clips = sorted(usable, key=lambda x: float(x.get("weighted_score", 0)), reverse=True)
        # 按目标时长筛选
        clip_order: List[str] = []
        transitions: Dict[str, str] = {}
        total = 0.0
        for c in sorted_clips:
            dur = float(c.get("duration", 5.0))
            if total + dur > target_duration:
                continue
            cid = c.get("clip_id") or c.get("id")  # 兼容 clip_id / id 键
            if not cid:
                continue
            clip_order.append(cid)
            total += dur
            # 转场：高分用 fade，中分用 cut，低分用 zoom 增强表现
            score = float(c.get("weighted_score", 0))
            if score >= 85:
                transitions[cid] = "fade"
            elif score >= 70:
                transitions[cid] = "cut"
            else:
                transitions[cid] = "zoom"

        # 节奏：按平均时长判断
        avg_dur = (total / len(clip_order)) if clip_order else 0
        if avg_dur <= 2.5:
            pacing = "fast"
        elif avg_dur >= 6:
            pacing = "slow"
        else:
            pacing = "normal"

        # 卡点：每 2-3 秒一个
        beat_points = [round(i * 2.5, 2) for i in range(int(target_duration // 2.5))]

        return EditingScript(
            clip_order=clip_order,
            transitions=transitions,
            beat_points=beat_points,
            bgm=self._infer_bgm(platform, pacing),
            subtitle_layout="bottom_center",
            pacing=pacing,
            rationale=f"规则回退生成：按分数降序排布，节奏 {pacing}，总时长 {total:.1f}s",
            target_duration=target_duration,
            platform=platform,
        )

    # ────────────── 辅助 ─────────────️

    @staticmethod
    def _weakest_dim(dimensions: Dict[str, float]) -> str:
        if not dimensions:
            return "unknown"
        return min(dimensions, key=dimensions.get)

    @staticmethod
    def _infer_bgm(platform: str, pacing: str) -> str:
        """推断配乐风格"""
        if pacing == "fast":
            return "电子快节奏" if platform in ("douyin", "kuaishou") else "快节奏纯音乐"
        if pacing == "slow":
            return "抒情慢节奏"
        return "通用中速"

    @staticmethod
    def _extract_json(text: str) -> Any:
        """从 LLM 返回文本中提取 JSON"""
        if not text:
            return None
        text = text.strip()
        try:
            return json.loads(text)
        except Exception as e:
            logger.debug(f"[EditingScriptGenerator] 直接 JSON 解析失败，尝试正则提取: {e}")
        m = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception as e:
                logger.debug(f"[EditingScriptGenerator] 正则提取 JSON 失败: {e}")
                return None
        return None

    def _emit_script_generated(self, script: EditingScript) -> None:
        """广播脚本生成完成事件"""
        try:
            from app.modules.lego.core import EventBus, EventType
            EventBus.get_instance().emit(
                EventType.EDITING_SCRIPT_GENERATED,
                script.to_dict(),
                source="EditingScriptGenerator",
            )
        except Exception as e:
            logger.debug(f"[EditingScriptGenerator] emit 失败: {e}")

    def _record_script(self, script: EditingScript) -> None:
        """写入记忆"""
        try:
            from app.core.memory_store import memory_store
            memory_store.record(
                category="execution_trace",
                content={
                    "stage": "editing_script",
                    "clip_count": len(script.clip_order),
                    "dropped_count": len(script.dropped_clips),
                    "pacing": script.pacing,
                    "bgm": script.bgm,
                    "platform": script.platform,
                },
                tags=["pipeline", "editing_script", script.platform],
                score=0.4,
            )
        except Exception as e:
            logger.debug(f"[EditingScriptGenerator] 写记忆失败: {e}")


# 全局单例便捷引用
editing_script_generator = EditingScriptGenerator.get_instance()
