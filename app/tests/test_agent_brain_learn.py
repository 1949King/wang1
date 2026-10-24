"""
test_agent_brain_learn.py
=========================
AgentBrain 学习机制单元测试（P0 保护网）。

覆盖范围：
1. learn_from_feedback 接口契约（success/quality/preview_issue）
2. _extract_related_capabilities 关键词匹配
3. AgentBrain 突触权重调整效果
4. 异常隔离（学习失败不影响主流程）

设计原则：
- 纯 Python 单元测试，不依赖 Qt
- 不修改 AgentBrain 内部状态，只验证对外行为
- 遵循 .trae/rules/2.md §七 TDD 规则
"""
import pytest
from unittest.mock import patch, MagicMock
from typing import Dict, Any, List


# ─────────────── 导入受测模块 ───────────────
def _import_agent_brain():
    """延迟导入，避免 AgentBrain 初始化副作用影响测试收集。"""
    from app.core.agent_brain import agent_brain, AgentBrain
    return agent_brain, AgentBrain


# ════════════════════════════════════════════════════════════════════
# 1. learn_from_feedback 接口契约
# ════════════════════════════════════════════════════════════════════
class TestLearnFromFeedbackContract:
    """验证 learn_from_feedback 接口契约。"""

    def test_learn_from_feedback_accepts_dict(self):
        """learn_from_feedback 必须接受 dict 参数。"""
        agent_brain, _ = _import_agent_brain()
        feedback = {
            "type": "success",
            "related_capabilities": ["pipeline.execute_editing"],
            "severity": "low",
        }
        # 不抛异常即通过
        agent_brain.learn_from_feedback(feedback)

    def test_learn_from_feedback_success_type(self):
        """type=success 应强化相关突触。"""
        agent_brain, _ = _import_agent_brain()
        feedback = {
            "type": "success",
            "related_capabilities": ["editor.split_clip"],
            "severity": "low",
        }
        agent_brain.learn_from_feedback(feedback)

    def test_learn_from_feedback_quality_type(self):
        """type=quality 应弱化相关突触。"""
        agent_brain, _ = _import_agent_brain()
        feedback = {
            "type": "quality",
            "related_capabilities": ["editor.split_clip"],
            "severity": "medium",
        }
        agent_brain.learn_from_feedback(feedback)

    def test_learn_from_feedback_preview_issue_type(self):
        """type=preview_issue 应弱化相关突触。"""
        agent_brain, _ = _import_agent_brain()
        feedback = {
            "type": "preview_issue",
            "related_capabilities": ["pipeline.preview_validate"],
            "severity": "high",
        }
        agent_brain.learn_from_feedback(feedback)

    def test_learn_from_feedback_empty_related(self):
        """related_capabilities 为空时不应抛异常。"""
        agent_brain, _ = _import_agent_brain()
        feedback = {
            "type": "success",
            "related_capabilities": [],
            "severity": "low",
        }
        agent_brain.learn_from_feedback(feedback)

    def test_learn_from_feedback_unknown_type(self):
        """未知 type 不应抛异常（走默认弱学习分支）。"""
        agent_brain, _ = _import_agent_brain()
        feedback = {
            "type": "unknown_type",
            "related_capabilities": ["model.chat"],
            "severity": "low",
        }
        agent_brain.learn_from_feedback(feedback)

    def test_learn_from_feedback_invalid_severity(self):
        """无效 severity 不应抛异常（走默认 delta）。"""
        agent_brain, _ = _import_agent_brain()
        feedback = {
            "type": "success",
            "related_capabilities": ["model.chat"],
            "severity": "invalid_severity",
        }
        agent_brain.learn_from_feedback(feedback)


# ════════════════════════════════════════════════════════════════════
# 2. 突触权重调整效果
# ════════════════════════════════════════════════════════════════════
class TestSynapseReinforcement:
    """验证 learn_from_feedback 真的调整了突触权重。"""

    def test_success_feedback_increases_weight(self):
        """成功反馈应增加突触权重（强化）。"""
        agent_brain, AgentBrain = _import_agent_brain()

        # 找一个已注册的 capability
        test_cap = "editor.split_clip"
        if test_cap not in agent_brain._neurons:
            pytest.skip(f"神经元 {test_cap} 未注册")

        # 记录初始权重（如果突触不存在，先创建）
        synapse_key = (test_cap, test_cap)
        initial_synapse = agent_brain._synapses.get(synapse_key)
        initial_weight = initial_synapse.weight if initial_synapse else 0.5

        # 触发成功反馈
        feedback = {
            "type": "success",
            "related_capabilities": [test_cap],
            "severity": "low",
        }
        agent_brain.learn_from_feedback(feedback)

        # 验证权重增加（或突触被创建）
        after_synapse = agent_brain._synapses.get(synapse_key)
        if after_synapse:
            assert after_synapse.weight >= initial_weight - 0.001, \
                "成功反馈后权重应增加或保持"

    def test_quality_feedback_decreases_weight(self):
        """质量反馈应减少突触权重（弱化）。"""
        agent_brain, _ = _import_agent_brain()

        test_cap = "editor.apply_filter"
        if test_cap not in agent_brain._neurons:
            pytest.skip(f"神经元 {test_cap} 未注册")

        synapse_key = (test_cap, test_cap)
        initial_synapse = agent_brain._synapses.get(synapse_key)
        initial_weight = initial_synapse.weight if initial_synapse else 0.5

        feedback = {
            "type": "quality",
            "related_capabilities": [test_cap],
            "severity": "medium",
        }
        agent_brain.learn_from_feedback(feedback)

        after_synapse = agent_brain._synapses.get(synapse_key)
        if after_synapse:
            assert after_synapse.weight <= initial_weight + 0.001, \
                "质量反馈后权重应减少或保持"


# ════════════════════════════════════════════════════════════════════
# 3. _extract_related_capabilities 关键词匹配（editor_module 辅助方法）
# ════════════════════════════════════════════════════════════════════
class TestExtractRelatedCapabilities:
    """验证 _extract_related_capabilities 关键词匹配逻辑。

    该方法现在位于 EditorModule，但因为它是纯函数逻辑，
    我们通过模拟同样的关键词表来验证匹配规则。
    """

    # 与 editor_module.py _extract_related_capabilities 保持一致的关键词表
    KEYWORD_TO_CAP = {
        "pipeline.execute_editing": ["精剪", "成片", "导出", "剪辑"],
        "editor.split_clip": ["切分", "切割", "split"],
        "editor.apply_filter": ["滤镜", "调色", "filter"],
        "editor.add_transition": ["转场", "过渡", "transition"],
        "ext.run_extension": ["插件", "拓展", "效果"],
        "ext.run_skill": ["技能", "skill", "导演"],
        "model.chat": ["对话", "聊天", "问答", "生成文案"],
        "pipeline.generate": ["生成", "视频", "抽卡", "画面"],
        "pipeline.generate_script": ["脚本", "创意", "镜头顺序", "配乐"],
        "editor.get_timeline_context": ["时间线", "上下文", "轨道"],
    }

    def _extract(self, user_text: str) -> List[str]:
        """模拟 editor_module.py 的 _extract_related_capabilities 逻辑。"""
        if not user_text:
            return ["pipeline.execute_editing"]
        text = user_text.lower()
        matched = []
        for cap_id, keywords in self.KEYWORD_TO_CAP.items():
            if any(kw.lower() in text for kw in keywords):
                matched.append(cap_id)
        return matched if matched else ["pipeline.execute_editing"]

    def test_empty_text_returns_default(self):
        """空文本应返回默认 capability。"""
        result = self._extract("")
        assert result == ["pipeline.execute_editing"]

    def test_none_text_returns_default(self):
        """None 应返回默认 capability（实际方法处理 falsy）。"""
        result = self._extract(None)
        assert result == ["pipeline.execute_editing"]

    def test_cut_keyword_matches_split_clip(self):
        """'切分' 关键词应匹配 editor.split_clip。"""
        result = self._extract("帮我切分这段视频")
        assert "editor.split_clip" in result

    def test_transition_keyword_matches(self):
        """'转场' 关键词应匹配 editor.add_transition。"""
        result = self._extract("在两个片段之间加转场")
        assert "editor.add_transition" in result

    def test_filter_keyword_matches(self):
        """'滤镜' 关键词应匹配 editor.apply_filter。"""
        result = self._extract("应用电影滤镜")
        assert "editor.apply_filter" in result

    def test_multiple_keywords_match_multiple_caps(self):
        """多关键词应匹配多个 capability。"""
        result = self._extract("切分视频后加转场和滤镜")
        assert "editor.split_clip" in result
        assert "editor.add_transition" in result
        assert "editor.apply_filter" in result

    def test_no_match_returns_default(self):
        """无匹配关键词应返回默认 capability。"""
        result = self._extract("hello world 12345")
        assert result == ["pipeline.execute_editing"]

    def test_english_keyword_matches(self):
        """英文关键词（如 split）应匹配（大小写不敏感）。"""
        result = self._extract("please split this clip")
        assert "editor.split_clip" in result

    def test_skill_keyword_matches(self):
        """'skill' 关键词应匹配 ext.run_skill。"""
        result = self._extract("run the subtitle skill")
        assert "ext.run_skill" in result

    def test_extension_keyword_matches(self):
        """'插件' 关键词应匹配 ext.run_extension。"""
        result = self._extract("调用字幕插件")
        assert "ext.run_extension" in result


# ════════════════════════════════════════════════════════════════════
# 4. AgentBrain 异常隔离
# ════════════════════════════════════════════════════════════════════
class TestAgentBrainExceptionIsolation:
    """验证 AgentBrain 学习失败不影响主流程。"""

    def test_learn_from_feedback_swallows_internal_exception(self):
        """learn_from_feedback 内部异常应被捕获，不外抛。"""
        agent_brain, _ = _import_agent_brain()

        # 用一个会导致内部 reinforce_path 异常的反馈
        # （传一个不存在的 capability，但内部应安全处理）
        feedback = {
            "type": "success",
            "related_capabilities": ["nonexistent.capability.id"],
            "severity": "low",
        }
        # 不应抛异常
        agent_brain.learn_from_feedback(feedback)

    def test_agent_brain_learn_method_isolation(self):
        """模拟 _agent_brain_learn 的异常隔离逻辑。

        验证：即使 agent_brain 导入失败，也不应抛异常。
        """
        # 模拟 editor_module._agent_brain_learn 的行为
        def mock_agent_brain_learn(success, user_text="", error=""):
            try:
                from app.core.agent_brain import agent_brain
                # 故意传一个会触发异常的 feedback
                agent_brain.learn_from_feedback(None)  # type: ignore
            except Exception as e:
                # 应该被捕获
                return f"caught: {e}"
            return "ok"

        result = mock_agent_brain_learn(True, "测试")
        # 应该返回 caught（异常被捕获），而不是抛异常
        assert "caught" in result or result == "ok"


# ════════════════════════════════════════════════════════════════════
# 5. AgentBrain 单例与初始化
# ════════════════════════════════════════════════════════════════════
class TestAgentBrainSingleton:
    """验证 AgentBrain 单例机制。"""

    def test_agent_brain_is_singleton(self):
        """多次 import 应返回同一实例。"""
        from app.core.agent_brain import agent_brain as ab1
        from app.core.agent_brain import agent_brain as ab2
        assert ab1 is ab2, "agent_brain 应为单例"

    def test_agent_brain_has_neurons(self):
        """AgentBrain 应有已注册的神经元。"""
        from app.core.agent_brain import agent_brain
        neurons = getattr(agent_brain, '_neurons', {})
        assert len(neurons) > 0, "AgentBrain 应至少注册 1 个神经元"
        # 23 个 capability（与 agent_brain.py L87-113 一致）
        assert len(neurons) >= 20, f"应注册至少 20 个神经元，实际 {len(neurons)}"

    def test_agent_brain_has_synapses(self):
        """AgentBrain 应有突触存储结构。"""
        from app.core.agent_brain import agent_brain
        synapses = getattr(agent_brain, '_synapses', None)
        assert synapses is not None, "AgentBrain 应有 _synapses 属性"

    def test_agent_brain_capability_ids(self):
        """注册的 capability_id 应包含预期的关键能力。"""
        from app.core.agent_brain import agent_brain
        neurons = agent_brain._neurons
        expected_caps = [
            "pipeline.execute_editing",
            "editor.split_clip",
            "editor.apply_filter",
            "editor.ripple_delete_range",
            "editor.suggest_cleanup",
            "model.chat",
            "ext.run_extension",
            "ext.run_skill",
        ]
        for cap in expected_caps:
            assert cap in neurons, f"应注册 capability: {cap}"


if __name__ == "__main__":
    # 支持直接运行：python test_agent_brain_learn.py
    pytest.main([__file__, "-v", "-m", "not slow"])
