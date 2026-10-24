"""
外部 Skill 加载器
==================

扫描 ``app/skills/external/`` 下的第三方 SKILL.md 资源，动态生成
继承自项目 ``Skill`` 基类的知识型子类，并注册到 ``SkillEngine``。

设计目标
--------
- **最小侵入**：不修改现有 ``Skill`` 基类与 ``SkillEngine`` 逻辑，仅通过
  公开的 ``register_skill`` 接口注入新 skill。
- **幂等**：重复调用 ``register_external_skills`` 不会重复注册（受模块级
  标志位保护）。
- **健壮**：单个外部 skill 解析失败不影响其他 skill 的注册。
- **零新增依赖**：YAML frontmatter 用内置正则解析，不引入 PyYAML。
- **可观测**：所有解析/注册行为打日志，便于排查。

实现说明
--------
工厂函数使用 ``type()`` 动态创建子类，而非 ``class`` 语句。原因：Python
类体作用域对外层同名变量的查找有特殊规则（``skill_id = skill_id`` 在类
体内会因左侧赋值把 ``skill_id`` 视为类体局部变量，导致右侧 NameError）。
用 ``type()`` 通过 namespace dict 显式注入类属性与方法，干净利落。

支持的外部 skill 形态
---------------------
1. 顶层 SKILL.md（如 ``external/seedance2-skill/SKILL.md``）。
2. 嵌套 ``skills/<name>/SKILL.md``（如 videocut-skills 的子 skill）。
3. 同级 ``helpers/`` ``scripts/`` ``references/`` ``agents/`` 目录会被
   一并收集，通过 ``execute()`` 返回值暴露给 AI 调用方。

注册后的 Skill 行为
-------------------
- ``skill_id`` 形如 ``<repo>__<name>``，避免不同仓库的同名 skill 冲突。
- ``skill_category`` 形如 ``外部/<repo>``，在拓展中心列表里分组清晰。
- ``execute()`` 单步：读取 SKILL.md 全文 + 收集同级资源清单，
  返回结构化 dict 供 AI 研究。
"""

import os
import re
import logging
from pathlib import Path
from typing import Dict, List, Optional, Type

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────
# 模块级状态：防止重复注册（仅本进程内有效）
# ──────────────────────────────────────────────────────────────────
_registered_flag: bool = False
_registered_count: int = 0

# SKILL.md frontmatter 正则：匹配开头 `---\n...\n---\n` 之间的内容
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", re.DOTALL)


# ══════════════════════════════════════════════════════════════════
# 解析工具
# ══════════════════════════════════════════════════════════════════
def _parse_frontmatter(content: str) -> Dict[str, str]:
    """解析 SKILL.md 顶部 YAML frontmatter

    仅支持简单的 ``key: value`` 单行格式（外部 skill 普遍采用此格式）。
    多行 ``|`` / ``>`` 块未支持——遇到再扩展，避免过度设计。

    Args:
        content: SKILL.md 文件全文

    Returns:
        Dict[str, str]: 字段映射（如 {"name": "...", "description": "..."}）
    """
    match = _FRONTMATTER_RE.match(content)
    if not match:
        return {}

    front_text = match.group(1)
    result: Dict[str, str] = {}
    for line in front_text.splitlines():
        line = line.strip()
        # 跳过空行与注释
        if not line or line.startswith("#"):
            continue
        # 仅处理 `key: value` 形式
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        # 去掉首尾成对引号
        if len(value) >= 2 and value[0] in ('"', "'") and value[-1] == value[0]:
            value = value[1:-1]
        if key:
            result[key] = value
    return result


def _find_skill_md_files(root: Path) -> List[Path]:
    """递归扫描 root 下所有 SKILL.md 文件，跳过 .git 目录

    Args:
        root: 外部 skill 根目录

    Returns:
        List[Path]: 所有 SKILL.md 的绝对路径
    """
    result: List[Path] = []
    if not root.is_dir():
        return result

    for dirpath, dirnames, filenames in os.walk(root):
        # 原地过滤 dirnames，阻止 os.walk 进入 .git
        dirnames[:] = [d for d in dirnames if d != ".git"]
        # 跳过 .git 自身（虽然上面已阻止进入，这里防御性兜底）
        if ".git" in Path(dirpath).parts:
            continue
        if "SKILL.md" in filenames:
            result.append(Path(dirpath) / "SKILL.md")
    return result


def _detect_companion_dirs(skill_md: Path) -> Dict[str, Optional[Path]]:
    """检测 SKILL.md 同级的辅助资源目录

    Args:
        skill_md: SKILL.md 完整路径

    Returns:
        Dict: 含 helpers_dir / scripts_dir / agents_dir / references_dir，
              不存在则对应值为 None
    """
    skill_dir = skill_md.parent
    companions: Dict[str, Optional[Path]] = {
        "helpers_dir": None,
        "scripts_dir": None,
        "agents_dir": None,
        "references_dir": None,
    }
    for key, name in [
        ("helpers_dir", "helpers"),
        ("scripts_dir", "scripts"),
        ("agents_dir", "agents"),
        ("references_dir", "references"),
    ]:
        candidate = skill_dir / name
        if candidate.is_dir():
            companions[key] = candidate
    return companions


def _list_agent_yamls(agents_dir: Optional[Path]) -> List[Path]:
    """列出 agents/ 目录下的 .yaml/.yml 文件（排序后返回）"""
    if not agents_dir or not agents_dir.is_dir():
        return []
    return sorted(
        [
            p for p in agents_dir.iterdir()
            if p.is_file() and p.suffix.lower() in (".yaml", ".yml")
        ]
    )


def _extract_source_repo(skill_md: Path, external_root: Path) -> str:
    """从路径推断来源仓库名（external/ 下第一级目录名）

    Examples:
        external/seedance2-skill/SKILL.md            -> "seedance2-skill"
        external/videocut-skills/plugins/.../cut/SKILL.md -> "videocut-skills"
    """
    try:
        rel = skill_md.relative_to(external_root)
        return rel.parts[0] if rel.parts else "unknown"
    except ValueError:
        return "unknown"


# ══════════════════════════════════════════════════════════════════
# Skill 子类工厂（用 type() 创建，避开类体作用域陷阱）
# ══════════════════════════════════════════════════════════════════
def _make_external_skill_class(
    skill_id: str,
    name: str,
    description: str,
    source_repo: str,
    skill_dir: Path,
    companions: Dict[str, Optional[Path]],
    agent_yamls: List[Path],
) -> Type:
    """工厂：动态生成一个继承 Skill 的外部知识型 Skill 子类

    生成的类在 ``execute()`` 时返回 SKILL.md 内容 + 同级资源路径，
    供 AI 调用方研究使用。

    使用 ``type()`` 而非 ``class`` 语句创建子类，原因：Python 类体作用域
    对同名赋值有特殊规则（``skill_id = skill_id`` 在类体内会因左侧赋值把
    ``skill_id`` 标记为类体局部变量，导致右侧查找 NameError）。通过
    ``type()`` 用 namespace dict 显式注入类属性与方法，干净利落。

    Args:
        skill_id: 完整 skill id（含 repo 前缀，避免冲突）
        name: 显示名（frontmatter 的 name 字段）
        description: 描述文本
        source_repo: 来源仓库名
        skill_dir: SKILL.md 所在目录
        companions: 同级辅助目录映射
        agent_yamls: agents/ 下的 yaml 文件列表

    Returns:
        Type[Skill]: 动态生成的 Skill 子类
    """
    # 延迟导入避免循环依赖（skill_engine 反向不依赖本模块）
    from app.modules.lego.skill_engine import Skill, StepResult

    # 显示名优先用 frontmatter 的 name，回退到目录名
    display_name = name or skill_dir.name
    # 描述截断（防止 UI 列表显示过长）
    short_desc = description.strip() if description else f"外部 Skill（来源: {source_repo}）"
    if len(short_desc) > 120:
        short_desc = short_desc[:117] + "..."

    skill_md_path = skill_dir / "SKILL.md"
    helpers_dir = companions.get("helpers_dir")
    scripts_dir = companions.get("scripts_dir")
    agents_dir = companions.get("agents_dir")
    references_dir = companions.get("references_dir")

    # ── 闭包捕获外层变量，供 __init__ / _load_skill_doc 使用 ──
    def __init__(self):
        """设置外部资源路径实例属性，再调用 Skill 基类初始化"""
        self._external_skill_dir: Path = skill_dir
        self._external_skill_md: Path = skill_md_path
        self._external_source_repo: str = source_repo
        self._external_helpers_dir: Optional[Path] = helpers_dir
        self._external_scripts_dir: Optional[Path] = scripts_dir
        self._external_agents_dir: Optional[Path] = agents_dir
        self._external_references_dir: Optional[Path] = references_dir
        self._external_agent_yamls: List[Path] = agent_yamls
        # 调用 Skill.__init__（会触发 _setup_steps）
        Skill.__init__(self)

    def _setup_steps(self):
        """设置执行步骤：单步加载 SKILL.md 文档"""
        self.add_step(
            name="加载外部 Skill 文档",
            description=f"读取 {self._external_skill_md.name} 全文与同级资源清单",
            handler=self._load_skill_doc,
        )

    def _load_skill_doc(self, context):
        """步骤 handler：读取 SKILL.md 并返回结构化结果

        返回 StepResult.output 包含：
            - skill_id / skill_name / source_repo
            - skill_md_content: SKILL.md 全文
            - skill_md_path / skill_dir
            - helpers_dir / helper_files
            - scripts_dir / script_files
            - references_dir / reference_files
            - agents_dir / agent_yamls
        """
        try:
            if not self._external_skill_md.exists():
                return StepResult(
                    success=False,
                    error=f"SKILL.md 不存在: {self._external_skill_md}"
                )
            content = self._external_skill_md.read_text(encoding="utf-8")

            # 收集 helpers/ 下的脚本文件清单
            helper_files: List[str] = []
            if self._external_helpers_dir and self._external_helpers_dir.is_dir():
                helper_files = [
                    str(p) for p in sorted(self._external_helpers_dir.iterdir())
                    if p.is_file()
                ]
            script_files: List[str] = []
            if self._external_scripts_dir and self._external_scripts_dir.is_dir():
                script_files = [
                    str(p) for p in sorted(self._external_scripts_dir.iterdir())
                    if p.is_file()
                ]
            reference_files: List[str] = []
            if self._external_references_dir and self._external_references_dir.is_dir():
                reference_files = [
                    str(p) for p in sorted(self._external_references_dir.iterdir())
                    if p.is_file()
                ]
            agent_yaml_files: List[str] = [str(p) for p in self._external_agent_yamls]

            output_payload = {
                "skill_id": self.skill_id,
                "skill_name": self.skill_name,
                "source_repo": self._external_source_repo,
                "skill_md_content": content,
                "skill_md_path": str(self._external_skill_md),
                "skill_dir": str(self._external_skill_dir),
                "helpers_dir": str(self._external_helpers_dir) if self._external_helpers_dir else None,
                "helper_files": helper_files,
                "scripts_dir": str(self._external_scripts_dir) if self._external_scripts_dir else None,
                "script_files": script_files,
                "references_dir": str(self._external_references_dir) if self._external_references_dir else None,
                "reference_files": reference_files,
                "agents_dir": str(self._external_agents_dir) if self._external_agents_dir else None,
                "agent_yamls": agent_yaml_files,
            }

            # 同时写入 context.outputs，供 extensions_module._run_selected_skill
            # 通过 result["outputs"] 读取（Skill 基类把 StepResult.output 合并到
            # variables 而非 outputs，需显式 set_output 才能暴露给调用方）
            if context is not None:
                for out_key, out_val in output_payload.items():
                    try:
                        context.set_output(out_key, out_val)
                    except Exception:
                        # set_output 失败不应阻塞整个步骤
                        logger.debug("set_output 失败 %s", out_key, exc_info=True)

            return StepResult(success=True, output=output_payload)
        except Exception as e:
            logger.exception("加载外部 Skill 文档失败: %s", self._external_skill_md)
            return StepResult(success=False, error=str(e))

    # 类属性 namespace：通过 type() 注入，绕开类体作用域陷阱
    namespace: Dict[str, object] = {
        # ── 类属性（被 SkillRegistry.list_all() 读取）──
        "skill_id": skill_id,
        "skill_name": display_name,
        "skill_description": short_desc,
        "skill_category": f"外部/{source_repo}",
        "skill_icon": "📦",
        "skill_version": "1.0.0",
        # ── 方法 ──
        "__init__": __init__,
        "_setup_steps": _setup_steps,
        "_load_skill_doc": _load_skill_doc,
        # ── 文档字符串 ──
        "__doc__": (
            "外部知识型 Skill 包装器：将 Markdown 形式的外部 SKILL.md 包装"
            "为可被 SkillEngine 调度的 Skill。execute() 单步：读取 SKILL.md"
            " 全文 + 收集同级辅助资源清单，返回结构化 dict 供上层 AI 研究与调用。"
        ),
    }

    cls_name = f"ExternalSkill_{skill_id.replace('-', '_').title()}"
    cls = type(cls_name, (Skill,), namespace)
    return cls


# ══════════════════════════════════════════════════════════════════
# 发现与注册
# ══════════════════════════════════════════════════════════════════
def discover_external_skills(external_root: Optional[Path] = None) -> List[Type]:
    """扫描 external/ 目录并返回外部 Skill 子类列表

    Args:
        external_root: 外部 skill 根目录；默认为 ``app/skills/external/``

    Returns:
        List[Type]: 动态生成的 Skill 子类列表（解析失败的会被跳过并记日志）
    """
    if external_root is None:
        # 延迟导入避免循环依赖
        from app.skills import EXTERNAL_SKILLS_ROOT
        external_root = EXTERNAL_SKILLS_ROOT

    skill_classes: List[Type] = []

    if not external_root.is_dir():
        logger.warning("外部 skill 根目录不存在: %s", external_root)
        return skill_classes

    skill_md_files = _find_skill_md_files(external_root)
    logger.info("发现 %d 个外部 SKILL.md 文件", len(skill_md_files))

    seen_ids: set = set()
    for skill_md in skill_md_files:
        try:
            content = skill_md.read_text(encoding="utf-8")
            front = _parse_frontmatter(content)

            raw_name = front.get("name") or skill_md.parent.name
            # 防止不同仓库同名 skill 冲突：拼上 repo 前缀
            source_repo = _extract_source_repo(skill_md, external_root)
            full_skill_id = f"{source_repo}__{raw_name}"
            if full_skill_id in seen_ids:
                logger.warning("外部 skill ID 重复，跳过: %s", full_skill_id)
                continue
            seen_ids.add(full_skill_id)

            description = front.get("description", "")
            companions = _detect_companion_dirs(skill_md)
            agent_yamls = _list_agent_yamls(companions.get("agents_dir"))

            cls = _make_external_skill_class(
                skill_id=full_skill_id,
                name=raw_name,
                description=description,
                source_repo=source_repo,
                skill_dir=skill_md.parent,
                companions=companions,
                agent_yamls=agent_yamls,
            )
            skill_classes.append(cls)
            logger.debug(
                "发现外部 skill: id=%s, name=%s, repo=%s, helpers=%s, agents=%d",
                full_skill_id, raw_name, source_repo,
                bool(companions.get("helpers_dir")), len(agent_yamls)
            )
        except Exception as e:
            logger.exception("解析外部 skill 失败 %s: %s", skill_md, e)
            continue

    return skill_classes


def register_external_skills(engine=None) -> int:
    """发现并注册所有外部 skill 到 SkillEngine

    幂等：重复调用不会重复注册（受模块级 ``_registered_flag`` 保护）。

    Args:
        engine: 可选的 SkillEngine 实例；默认使用 ``skill_engine`` 全局单例

    Returns:
        int: 本次新注册的 skill 数量（已注册过则返回 0）
    """
    global _registered_flag, _registered_count

    if _registered_flag:
        logger.debug("外部 skill 已注册过，跳过")
        return 0

    try:
        from app.modules.lego.skill_engine import skill_engine as _default_engine
    except Exception as e:
        logger.error("无法导入 SkillEngine 单例: %s", e)
        return 0

    target_engine = engine or _default_engine

    discovered = discover_external_skills()
    success_count = 0
    for cls in discovered:
        try:
            if target_engine.register_skill(cls):
                success_count += 1
            else:
                logger.warning("注册外部 skill 失败: %s", cls.__name__)
        except Exception as e:
            logger.exception("注册外部 skill 异常 %s: %s", cls.__name__, e)

    _registered_flag = True
    _registered_count = success_count
    logger.info("外部 skill 注册完成：成功 %d/%d", success_count, len(discovered))
    return success_count


def ensure_external_skills_registered() -> int:
    """便捷别名：供 extensions_module 调用，确保外部 skill 已注册

    与 ``register_external_skills`` 等价，名字更直白地表达意图。
    """
    return register_external_skills()


def get_registered_count() -> int:
    """获取已注册的外部 skill 数量"""
    return _registered_count


def is_registered() -> bool:
    """是否已完成外部 skill 注册"""
    return _registered_flag


def reset_registration_state() -> None:
    """重置注册状态（仅用于测试）

    注意：不会反注册已注册到 SkillEngine 的类，
    仅清除幂等标志位，让下一次 ``register_external_skills`` 可以再次扫描。
    """
    global _registered_flag, _registered_count
    _registered_flag = False
    _registered_count = 0
