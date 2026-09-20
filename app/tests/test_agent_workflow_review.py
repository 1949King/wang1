# -*- coding: utf-8 -*-
"""ReviewAgent 真实打分特征单元测试（纯数据层，无 GUI）。

对应 docs/_archive/docs/Agent诊断与优化方案.md 第三步（P1-4 补测试）。
覆盖：有真实 ASR dialogues → uses_placeholder_features=False；
无 dialogues → 回退占位值 True。
"""

from types import SimpleNamespace

import pytest

from app.modules.lego.agent_workflow import (
    ClipTask,
    EditPlan,
    ReviewAgent,
)


def _make_plan(dialogues=None, platform="抖音") -> EditPlan:
    """构造带/不带 ASR 对话数据的剪辑计划"""
    analysis = {
        "title": "测试剧",
        "genre": "都市",
        "characters": ["男主", "女主"],
        "plot_points": 2,
        "scenes": 3,
        "themes": ["逆袭"],
        "pacing_type": "normal",
    }
    if dialogues is not None:
        analysis["dialogues"] = dialogues
    return EditPlan(
        video_path="/fake/video.mp4",
        platform=platform,
        style="高光剪辑",
        target_duration=60.0,
        structure="",
        pacing="normal",
        bgm_style="",
        subtitle_style="",
        transition_style="",
        analysis=analysis,
    )


def _make_tasks() -> list:
    """构造两个已完成的剪辑任务"""
    return [
        ClipTask(
            task_id="clip_0_5", start_time=0.0, end_time=5.0,
            clip_type="hook", score=85.0, title="开场钩子",
            status="completed",
        ),
        ClipTask(
            task_id="clip_10_20", start_time=10.0, end_time=20.0,
            clip_type="climax", score=90.0, title="高潮冲突",
            status="completed",
        ),
    ]


# 真实 ASR 对话样例（PlanAgent.analysis 里的精简 dict 形态）
_REAL_DIALOGUES = [
    {"start_time": 0.0, "end_time": 1.5, "speaker": "男主",
     "text": "你竟然背叛我，滚！", "emotion": "愤怒"},
    {"start_time": 2.0, "end_time": 3.5, "speaker": "女主",
     "text": "你听我解释，我没想到会这样。", "emotion": "紧张"},
    {"start_time": 4.0, "end_time": 5.5, "speaker": "男主",
     "text": "离婚！从今天起我们彻底结束！", "emotion": "愤怒"},
    {"start_time": 6.0, "end_time": 7.5, "speaker": "女主",
     "text": "原来真相是这样，我爱你。", "emotion": "浪漫"},
]


class _FakePrediction:
    completion_rate_3s = 0.7
    completion_rate_full = 0.5
    like_rate = 0.04
    comment_rate = 0.02
    share_rate = 0.01
    viral_probability = 0.4


class _FakeSuggestion:
    def __init__(self):
        self.factor = SimpleNamespace(value="dialogue_density")
        self.current_score = 0.5
        self.target_score = 0.7
        self.suggestion = "提高开场对话密度"
        self.expected_improvement = 0.1


class _FakeViralEngine:
    """替代 ViralOptimizationEngine 的假引擎（避免依赖本地模型）"""

    def predict_performance(self, features, platform):
        return _FakePrediction()

    def generate_optimization_suggestions(self, features, platform):
        return [_FakeSuggestion()]


@pytest.mark.unit
class TestReviewAgentRealFeatures:
    """ReviewAgent 真实特征提取"""

    def test_extract_real_features_returns_7_tuple(self):
        """有 ASR 对话数据 → 返回 7 维真实特征元组"""
        reviewer = ReviewAgent()
        plan = _make_plan(dialogues=_REAL_DIALOGUES)
        real = reviewer._extract_real_features(plan, _make_tasks())
        assert real is not None
        assert len(real) == 7
        # 对话密度 / 情绪方差 / 冲突强度 应在 [0,1] 区间
        dialogue_density, emotion_variance, conflict_intensity = real[0], real[1], real[2]
        assert 0.0 <= dialogue_density <= 1.0
        assert 0.0 <= emotion_variance <= 1.0
        assert 0.0 <= conflict_intensity <= 1.0

    def test_extract_real_features_empty_dialogues_returns_none(self):
        """无 dialogues → 返回 None（调用方回退占位值）"""
        reviewer = ReviewAgent()
        plan = _make_plan(dialogues=[])
        assert reviewer._extract_real_features(plan, _make_tasks()) is None

    def test_extract_real_features_no_analysis_returns_none(self):
        """analysis 为空 → 返回 None"""
        reviewer = ReviewAgent()
        plan = _make_plan(dialogues=None)
        plan.analysis = {}
        assert reviewer._extract_real_features(plan, _make_tasks()) is None

    def test_review_with_real_dialogues_marks_placeholder_false(self):
        """有真实对话数据 → uses_placeholder_features=False"""
        reviewer = ReviewAgent()
        reviewer._viral_engine = _FakeViralEngine()
        plan = _make_plan(dialogues=_REAL_DIALOGUES)
        review = reviewer.review(plan, _make_tasks())
        assert review.uses_placeholder_features is False

    def test_review_without_dialogues_keeps_placeholder_true(self):
        """无对话数据 → uses_placeholder_features=True（向后兼容）"""
        reviewer = ReviewAgent()
        reviewer._viral_engine = _FakeViralEngine()
        plan = _make_plan(dialogues=None)
        review = reviewer.review(plan, _make_tasks())
        assert review.uses_placeholder_features is True

    def test_extract_real_features_conflict_dense_content_scores_high(self):
        """冲突密集内容 → conflict_intensity 应明显高于温和内容"""
        reviewer = ReviewAgent()
        conflict_plan = _make_plan(dialogues=_REAL_DIALOGUES)
        calm_plan = _make_plan(dialogues=[
            {"start_time": 0.0, "end_time": 1.0, "speaker": "A",
             "text": "天气真好，我们去散步吧。", "emotion": "温馨"},
            {"start_time": 2.0, "end_time": 3.0, "speaker": "B",
             "text": "好啊，公园的风景一定很美。", "emotion": "开心"},
        ])
        real_c = reviewer._extract_real_features(conflict_plan, _make_tasks())
        real_m = reviewer._extract_real_features(calm_plan, _make_tasks())
        assert real_c is not None and real_m is not None
        assert real_c[2] >= real_m[2]
