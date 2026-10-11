"""
五维量化打分系统 (FiveDimensionScorer)
======================================
对每个镜头/片段进行 100 分制量化评分 + S/A/B/C/D 分级 + D 级剔除。

五维权重（用户定稿）：
  1. 画面质量      25%
  2. 高光叙事价值   25%
  3. 文案/台词匹配度 20%
  4. BGM/音效适配度  15%
  5. 镜头时长合理性   15%

分级标准：
  S ≥ 90  保留
  A ≥ 80  保留
  B ≥ 70  保留
  C ≥ 60  保留
  D < 60  直接剔除
"""
from __future__ import annotations
import logging
import os
import threading
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _env_flag(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() not in ("0", "false", "off", "no", "")


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(str(os.environ.get(name, default)).strip()))
    except (TypeError, ValueError):
        return default


#: 是否启用真实像素审美分析（关掉就退回旧的固定基线行为）
_AESTHETIC_ENV = "SHIGUANG_AESTHETIC_ANALYSIS"
#: 每个镜头抽帧数
_AESTHETIC_FRAMES_ENV = "SHIGUANG_AESTHETIC_FRAMES"

#: 维度名 → 中文（建议文案 / 提示共用，避免各处重复）
DIM_LABELS = {
    "visual_quality": "画面质量",
    "narrative_highlight": "高光叙事",
    "copy_match": "文案匹配",
    "bgm_match": "BGM适配",
    "shot_duration": "镜头时长",
}


class ScoreGrade(str, Enum):
    """镜头等级"""
    S = "S"   # ≥90 顶级
    A = "A"   # ≥80 优秀
    B = "B"   # ≥70 良好
    C = "C"   # ≥60 合格
    D = "D"   # <60 劣质（剔除）


@dataclass
class ClipFeatures:
    """被评分的镜头特征（每维 0-100）"""
    clip_id: str = ""
    path: str = ""
    duration: float = 0.0
    visual_quality: float = 50.0           # 画面质量（清晰度/构图/色彩）
    narrative_highlight: float = 50.0      # 高光叙事（冲突/反转/情绪峰值）
    copy_match: float = 50.0              # 文案匹配度（字幕与创意的语义匹配）
    bgm_match: float = 50.0               # BGM 适配（节奏/情绪吻合）
    shot_duration_reasonableness: float = 50.0  # 镜头时长合理性
    # 如实标注：extract_features_from_clip 缺失 quality_scores 时会用固定
    # 70 分基线填充，这里记录哪些维度是基线估值（而非真实 AI/人工评分），
    # 供 ScoreResult/UI 判断要不要提示用户"部分分数是估算的"
    estimated_dims: List[str] = field(default_factory=list)
    #: 真实像素分析明细（sharpness/contrast/colorfulness/noise 及子分）；
    #: 未做分析（无 path / 关开关 / 读不到帧）时为空 dict
    visual_metrics: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ScoreResult:
    """打分结果"""
    clip_id: str
    dimensions: Dict[str, float] = field(default_factory=dict)  # 五维各自 0-100
    weighted_score: float = 0.0           # 加权总分
    grade: ScoreGrade = ScoreGrade.C
    should_drop: bool = False             # D 级 (<60) 直接剔除
    suggestions: List[str] = field(default_factory=list)  # 优化建议
    estimated_dims: List[str] = field(default_factory=list)  # 用了固定基线（非真实评分）的维度
    metrics: Dict[str, Any] = field(default_factory=dict)  # 真实像素分析明细（可空）

    def to_dict(self) -> Dict[str, Any]:
        return {
            "clip_id": self.clip_id,
            "dimensions": self.dimensions,
            "weighted_score": round(self.weighted_score, 1),
            "grade": self.grade.value,
            "should_drop": self.should_drop,
            "suggestions": self.suggestions,
            "estimated_dims": self.estimated_dims,
            "is_fully_estimated": len(self.estimated_dims) >= len(self.dimensions),
            "metrics": self.metrics,
            "measured_dims": [d for d in self.dimensions if d not in self.estimated_dims],
        }


class FiveDimensionScorer:
    """
    五维量化打分器 —— 单例

    使用方式：
        from app.core.five_dimension_scorer import five_dimension_scorer
        result = five_dimension_scorer.score(features)
        results = five_dimension_scorer.score_batch([features1, features2])
    """
    # 五维权重（用户定稿：25+25+20+15+15=100）
    WEIGHTS = {
        "visual_quality": 0.25,            # 画面质量 25%
        "narrative_highlight": 0.25,       # 高光叙事 25%
        "copy_match": 0.20,               # 文案匹配 20%
        "bgm_match": 0.15,                # BGM 适配 15%
        "shot_duration": 0.15,            # 镜头时长 15%
    }
    # 分级阈值
    GRADE_THRESHOLDS = {"S": 90, "A": 80, "B": 70, "C": 60}

    _instance: Optional['FiveDimensionScorer'] = None
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
    def get_instance(cls) -> 'FiveDimensionScorer':
        return cls()

    def score(self, features: ClipFeatures) -> ScoreResult:
        """
        对单个镜头打分

        流程：
        1. 五维各自 0-100
        2. 加权计算总分
        3. 映射 S/A/B/C/D 等级
        4. D 级 (<60) 标记 should_drop=True
        5. 生成优化建议
        """
        dimensions = {
            "visual_quality": self._clamp(features.visual_quality),
            "narrative_highlight": self._clamp(features.narrative_highlight),
            "copy_match": self._clamp(features.copy_match),
            "bgm_match": self._clamp(features.bgm_match),
            "shot_duration": self._clamp(features.shot_duration_reasonableness),
        }
        # 加权总分
        weighted = sum(
            dimensions[key] * self.WEIGHTS[key]
            for key in self.WEIGHTS
        )
        # 分级
        grade = self._compute_grade(weighted)
        # D 级剔除
        should_drop = grade == ScoreGrade.D
        # 优化建议
        suggestions = self._generate_suggestions(dimensions, grade)

        return ScoreResult(
            clip_id=features.clip_id,
            dimensions=dimensions,
            weighted_score=weighted,
            grade=grade,
            should_drop=should_drop,
            suggestions=suggestions,
            estimated_dims=list(features.estimated_dims),
            metrics=dict(features.visual_metrics or {}),
        )

    def score_batch(self, features_list: List[ClipFeatures]) -> List[ScoreResult]:
        """
        批量打分 + D 级剔除

        返回所有结果（含 D 级），调用方通过 should_drop 判断是否剔除
        """
        results = []
        for features in features_list:
            result = self.score(features)
            results.append(result)
            if result.should_drop:
                logger.info(f"[FiveDimensionScorer] 镜头 {features.clip_id} 评级 D ({result.weighted_score:.1f})，标记剔除")
        # 按分数降序
        results.sort(key=lambda r: r.weighted_score, reverse=True)
        # 广播打分完成事件
        self._emit_scoring_completed(results)
        return results

    # 智能基线分：当无显式质量评分时使用，保证素材不因缺失元数据被误判为 D 级
    _SMART_BASELINE = 70.0  # C 级合格基线

    def extract_features_from_clip(self, clip_meta: Dict[str, Any]) -> ClipFeatures:
        """
        从镜头元数据提取特征

        评分来源优先级（逐维独立判定，且**如实登记**哪些维度是估算的）：

        1. ``quality_scores`` 里有显式分 → 用显式分（尊重 AI/人工评分）
        2. **真实测量**（本版新增，可用 ``SHIGUANG_AESTHETIC_ANALYSIS=0`` 关闭）：
           - ``visual_quality`` ← ``aesthetic_analyzer`` 抽帧测量（清晰度/曝光/对比度/
             彩色度/噪声 → 0-100），不再是固定 70
           - ``shot_duration`` ← 真实时长对照「1.5~4s 舒适区」曲线
        3. 兜底 → ``_SMART_BASELINE``，并记入 ``estimated_dims``

        参数：
            clip_meta: 镜头元数据，可含 path/duration/quality_scores；
                       置 ``skip_aesthetic_analysis=True`` 可跳过像素测量。
        """
        clip_id = clip_meta.get("id") or clip_meta.get("clip_id") or uuid.uuid4().hex[:8]
        scores = clip_meta.get("quality_scores") or {}
        if not isinstance(scores, dict):
            scores = {}
        path = str(clip_meta.get("path") or "")
        try:
            duration = float(clip_meta.get("duration", 0) or 0)
        except (TypeError, ValueError):
            duration = 0.0
        estimated_dims: List[str] = []
        metrics: Dict[str, Any] = {}

        def _explicit(key: str) -> bool:
            return key in scores and scores[key] is not None

        def _dim(key: str) -> float:
            """单维评分：有显式分用显式分，否则用基线（并记录为估算维度）"""
            if _explicit(key):
                return float(scores[key])
            estimated_dims.append(key)
            return self._SMART_BASELINE

        # —— 画面质量：显式 > 真实像素测量 > 基线 ——
        if _explicit("visual_quality"):
            visual_quality = float(scores["visual_quality"])
        else:
            visual_quality = None
            if self.aesthetic_enabled and not clip_meta.get("skip_aesthetic_analysis"):
                metrics = self._measure_visual(path) or {}
                if "visual_quality" in metrics:
                    visual_quality = float(metrics["visual_quality"])
            if visual_quality is None:
                estimated_dims.append("visual_quality")
                visual_quality = self._SMART_BASELINE

        # —— 镜头时长：显式 > 真实时长曲线 > 基线 ——
        if _explicit("shot_duration"):
            shot_duration = float(scores["shot_duration"])
        elif duration > 0:
            try:
                from app.core.ai.aesthetic_analyzer import duration_reasonableness

                shot_duration = duration_reasonableness(duration)
            except Exception as e:
                logger.debug("时长合理性计算失败: %s", e)
                estimated_dims.append("shot_duration")
                shot_duration = self._SMART_BASELINE
        else:
            estimated_dims.append("shot_duration")
            shot_duration = self._SMART_BASELINE

        return ClipFeatures(
            clip_id=clip_id,
            path=path,
            duration=duration,
            visual_quality=visual_quality,
            narrative_highlight=_dim("narrative_highlight"),
            copy_match=_dim("copy_match"),
            bgm_match=_dim("bgm_match"),
            shot_duration_reasonableness=shot_duration,
            estimated_dims=estimated_dims,
            visual_metrics=metrics,
        )

    # ─────────── 真实像素测量 ───────────

    @property
    def aesthetic_enabled(self) -> bool:
        """是否启用真实像素审美分析（环境变量，默认开）。"""
        return _env_flag(_AESTHETIC_ENV, True)

    def _measure_visual(self, path: str) -> Optional[Dict[str, Any]]:
        """调 ``aesthetic_analyzer`` 测真实画面质量；不可用/失败返回 None。"""
        if not path:
            return None
        try:
            from app.core.ai.aesthetic_analyzer import analyze_media

            return analyze_media(path, max_frames=_env_int(_AESTHETIC_FRAMES_ENV, 9))
        except Exception as e:
            logger.debug("画面审美分析失败 %s: %s", path, e)
            return None

    def _compute_grade(self, total: float) -> ScoreGrade:
        """根据总分映射 S/A/B/C/D"""
        for grade_name, threshold in self.GRADE_THRESHOLDS.items():
            if total >= threshold:
                return ScoreGrade(grade_name)
        return ScoreGrade.D

    def _generate_suggestions(self, dimensions: Dict[str, float], grade: ScoreGrade) -> List[str]:
        """根据五维分数生成优化建议"""
        suggestions = []
        # 找出最低维度
        min_dim = min(dimensions, key=dimensions.get)
        min_score = dimensions[min_dim]

        if min_score < 60:
            dim_names = DIM_LABELS
            suggestions.append(f"建议优先提升{dim_names.get(min_dim, min_dim)}（当前 {min_score:.0f} 分）")

        if dimensions["visual_quality"] < 70:
            suggestions.append("画面质量偏低，建议增强清晰度或调整构图")
        if dimensions["narrative_highlight"] < 70:
            suggestions.append("高光叙事不足，建议加强冲突或反转")
        if dimensions["copy_match"] < 70:
            suggestions.append("文案匹配度低，建议调整字幕与画面的关联")
        if dimensions["bgm_match"] < 70:
            suggestions.append("BGM适配度低，建议更换配乐或调整节奏")
        if dimensions["shot_duration"] < 70:
            suggestions.append("镜头时长不合理，建议调整剪辑节奏")

        if grade == ScoreGrade.D:
            suggestions.insert(0, "⚠️ 该镜头评级 D，建议直接剔除或重新生成")
        elif grade == ScoreGrade.S:
            suggestions.insert(0, "✅ 顶级镜头，建议作为开场或高潮使用")

        return suggestions if suggestions else ["镜头质量良好，保持当前状态"]

    @staticmethod
    def _clamp(value: float, min_val: float = 0.0, max_val: float = 100.0) -> float:
        """限制数值范围"""
        return max(min_val, min(max_val, value))

    def _emit_scoring_completed(self, results: List[ScoreResult]):
        """广播打分完成事件"""
        try:
            from app.modules.lego.core import EventBus, EventType
            bus = EventBus.get_instance()
            summary = {
                "total": len(results),
                "dropped": sum(1 for r in results if r.should_drop),
                "grades": {g.value: sum(1 for r in results if r.grade == g) for g in ScoreGrade},
                "avg_score": sum(r.weighted_score for r in results) / len(results) if results else 0,
            }
            bus.emit(EventType.SCORING_COMPLETED, summary, source="FiveDimensionScorer")
        except Exception as e:
            logger.debug(f"[FiveDimensionScorer] emit SCORING_COMPLETED 失败: {e}")


# 全局单例便捷引用
five_dimension_scorer = FiveDimensionScorer.get_instance()
