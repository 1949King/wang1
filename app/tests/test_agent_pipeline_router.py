# -*- coding: utf-8 -*-
"""Agent 业务分流器单元测试（纯数据层，无 GUI）。

对应 docs/Agent诊断与优化方案.md 第三步（P1-4 补测试）。
"""

import pytest

from app.core.agent_pipeline_router import (
    AgentPipelineRouter,
    PipelineRoute,
)


@pytest.mark.unit
class TestAgentPipelineRouter:
    """分流器：无素材→GENERATION，有素材→EDITING"""

    def test_no_material_routes_to_generation(self):
        """无任何素材 → AI 视频生成业务线"""
        result = AgentPipelineRouter().route(materials=[], creative_brief="都市逆袭")
        assert result.route == PipelineRoute.GENERATION
        assert result.has_material is False

    def test_video_material_routes_to_editing(self):
        """有视频素材 → AI 素材剪辑业务线"""
        result = AgentPipelineRouter().route(
            materials=[{"type": "video", "path": "/fake/video.mp4", "duration": 10.0}]
        )
        assert result.route == PipelineRoute.EDITING
        assert result.has_material is True
        assert result.material_count == 1

    def test_text_only_material_routes_to_editing(self):
        """只有文本素材也视为可用素材 → 剪辑业务线"""
        result = AgentPipelineRouter().route(
            materials=[{"type": "text"}]
        )
        assert result.route == PipelineRoute.EDITING

    def test_empty_and_none_materials_equal(self):
        """materials=None 与空列表行为一致 → GENERATION"""
        r1 = AgentPipelineRouter().route(materials=None)
        r2 = AgentPipelineRouter().route(materials=[])
        assert r1.route == r2.route == PipelineRoute.GENERATION

    def test_unknown_type_material_not_usable(self):
        """未知类型素材不可用 → 仍走 GENERATION"""
        result = AgentPipelineRouter().route(
            materials=[{"type": "unknown", "path": "/fake/weird.xyz"}]
        )
        assert result.route == PipelineRoute.GENERATION
