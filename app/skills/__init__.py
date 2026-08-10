"""
Skills 模块
============

项目内 Skill 资源根包，分为两类：

- ``custom/`` : 项目自带的轻量 Skill（每个目录一个 metadata.json）。
- ``external/`` : 从外部克隆的第三方 Skill 仓库（每个目录一个 SKILL.md）。

本包仅承担「目录定位」职责，不引入业务逻辑；
外部 Skill 的发现、解析、注册统一由 ``app.skills.external_loader`` 负责。
"""

from pathlib import Path

# skills 包根目录（绝对路径），供 loader 与 UI 层复用
SKILLS_ROOT: Path = Path(__file__).resolve().parent
EXTERNAL_SKILLS_ROOT: Path = SKILLS_ROOT / "external"
CUSTOM_SKILLS_ROOT: Path = SKILLS_ROOT / "custom"


__all__ = [
    "SKILLS_ROOT",
    "EXTERNAL_SKILLS_ROOT",
    "CUSTOM_SKILLS_ROOT",
]
