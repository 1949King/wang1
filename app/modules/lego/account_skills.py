# -*- coding: utf-8 -*-
"""账号运营 Skills 接口壳。功能已卸，执行即失败。"""

from .skill_engine import Skill, SkillContext, StepResult, skill_engine

UNLOADED_MSG = "插件功能已卸，仅保留接口"


class _UnloadedAccountSkill(Skill):
    skill_category = "账号运营"
    skill_icon = "👤"
    skill_version = "1.0.0"

    def _setup_steps(self):
        self.step("功能已卸", handler=self._refuse)

    def _refuse(self, context: SkillContext) -> StepResult:
        return StepResult(success=False, error=UNLOADED_MSG)


class AccountDataCollectSkill(_UnloadedAccountSkill):
    skill_id = "account_data_collect"
    skill_name = "账号数据采集"
    skill_description = UNLOADED_MSG


class AccountAnalysisSkill(_UnloadedAccountSkill):
    skill_id = "account_analysis"
    skill_name = "账号分析"
    skill_description = UNLOADED_MSG


class PublishContentSkill(_UnloadedAccountSkill):
    skill_id = "publish_content"
    skill_name = "发布内容"
    skill_description = UNLOADED_MSG


class MatrixPublishSkill(_UnloadedAccountSkill):
    skill_id = "matrix_publish"
    skill_name = "矩阵发布"
    skill_description = UNLOADED_MSG


ACCOUNT_SKILLS = [
    AccountDataCollectSkill,
    AccountAnalysisSkill,
    PublishContentSkill,
    MatrixPublishSkill,
]


def register_account_skills():
    """注册账号运营 Skill 壳（执行即诚实失败）。"""
    for skill_class in ACCOUNT_SKILLS:
        skill_engine.register_skill(skill_class)
