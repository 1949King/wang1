"""
模块注册表 (Module Registry)
=============================
核心机制：把所有模块按「功能层级」分级管理，通过开关控制是否加载到导航栏。

┌──────────────────────────────────────────────────────────────┐
│  三级分类：                                                   │
│    CORE          → 核心功能（默认开启，不可关闭，不可隐藏）       │
│    ADVANCED      → 高级功能（默认关闭，手动开启，适合进阶用户）    │
│    EXPERIMENTAL  → 实验功能（默认关闭，手动开启，不保证稳定）     │
├──────────────────────────────────────────────────────────────┤
│  设计原则：                                                   │
│    1. 首屏只暴露核心功能，降低新用户学习成本                     │
│    2. 高级/实验功能通过设置面板手动开启，有明确的预期管理         │
│    3. 开关状态双保险持久化：QSettings(注册表) + JSON文件备份     │
│    4. 运行时开关切换支持动态增删导航栏按钮（无需重启）            │
│    5. 勾选复选框即时生效，无需额外点击「保存」按钮               │
├──────────────────────────────────────────────────────────────┤
│  关键数据流：                                                 │
│    用户勾选 → registry.toggle() → _save_overrides()          │
│    → QSettings 写入 + JSON文件写入                             │
│    → EventBus.emit(MODULE_CONFIG_CHANGED)                     │
│    → MainWindow.apply_module_changes() → 导航栏更新           │
│                                                               │
│    启动加载：get_registry() → _load_overrides()               │
│    → QSettings 读取 → 若无则 JSON 兜底 → _overrides 填充      │
└──────────────────────────────────────────────────────────────┘

使用示例：
    from .module_registry import get_registry, ModuleTier
    reg = get_registry()
    for mod in reg.enabled_modules():
        print(mod["name"], mod["tier"])
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, NotRequired, TypedDict, cast

import logging
logger = logging.getLogger("AI短剧编辑器.modules.lego.module_registry")

if TYPE_CHECKING:
    from PyQt6.QtCore import QSettings  # pyright: ignore[reportMissingImports,reportUnknownVariableType]
else:
    from PyQt6.QtCore import QSettings


class ModuleTier(str, Enum):
    """模块功能分级枚举

    子类化 str 使得在 JSON 序列化/反序列化时
    可以直接用字符串 "core"/"advanced"/"experimental" 比较。
    """
    CORE = "core"                  # 核心功能：默认开启，can_disable=False 强制不可关
    ADVANCED = "advanced"          # 高级功能：默认关闭，面向有经验的用户
    EXPERIMENTAL = "experimental"  # 实验功能：默认关闭，可能不稳定


class ModuleDefinition(TypedDict):
    """模块元信息定义 — 替代裸 dict[str, Any]，提供精确的类型约束

    仅包含 _MODULE_DEFINITIONS 中的原始字段；
    enabled / tier_label 由 all_modules() 动态注入，
    仅在子类 EnrichedModuleInfo 中声明。
    """
    id: str
    name: str
    icon: str
    description: str
    tier: ModuleTier
    import_module: str
    import_class: str
    default_enabled: bool
    can_disable: bool
    optional: NotRequired[bool]  # 模块文件可能不存在，导入失败时静默跳过


class EnrichedModuleInfo(ModuleDefinition):
    """all_modules() 返回值 — 继承 ModuleDefinition 并添加动态计算字段
    
    enabled / tier_label 在此声明为 Required，
    避免调用者访问时触发 NotRequired 警告。
    """
    enabled: bool
    tier_label: str


# ═══════════════════════════════════════════════════════════════
# 模块元信息定义表（新增模块只需在此添加一个字典）
# import_module / import_class 使用 importlib 延迟导入，
# 避免在启动时一次性加载所有模块造成内存爆炸。
# ═══════════════════════════════════════════════════════════════
_MODULE_DEFINITIONS: list[ModuleDefinition] = [
    # ╔══════════════════╗
    # ║ 核心功能 (CORE) ║ ← 默认全开，不可关闭
    # ╚══════════════════╝
    {
        "id": "home",
        "name": "首页",
        "icon": "🏠",
        "description": "快速入口、最近项目、统计概览",
        "tier": ModuleTier.CORE,
        "import_module": ".modules",
        "import_class": "HomeModule",
        "default_enabled": True,
        "can_disable": False,      # 不可关闭，toggle() 直接拒绝
    },
    {
        "id": "editor",
        "name": "剪辑",
        "icon": "🎬",
        "description": "轨道编辑、预览、滤镜、字幕、转场",
        "tier": ModuleTier.CORE,
        "import_module": ".editor_module",
        "import_class": "EditorModule",
        "default_enabled": True,
        "can_disable": False,
    },
    {
        "id": "settings",
        "name": "设置",
        "icon": "⚙️",
        "description": "应用设置、主题、快捷键、功能开关",
        "tier": ModuleTier.CORE,
        "import_module": ".settings_module",
        "import_class": "SettingsModule",
        "default_enabled": True,
        "can_disable": False,
    },
    {
        "id": "help",
        "name": "帮助",
        "icon": "❓",
        "description": "使用帮助、文档、反馈",
        "tier": ModuleTier.CORE,
        "import_module": ".help_module",
        "import_class": "HelpModule",
        "default_enabled": True,
        "can_disable": False,
    },

    # ╔════════════════════╗
    # ║ 高级功能 (ADVANCED)║ ← 默认关闭，手动开启
    # ╚════════════════════╝
    {
        "id": "copywriting",
        "name": "文案生成",
        "icon": "✍️",
        "description": "AI 文案/标题/脚本。需在「模型管理」配置 Provider；可选「本地模板（非 AI）」",
        "tier": ModuleTier.ADVANCED,
        "import_module": ".copywriting_module",
        "import_class": "CopywritingModule",
        "default_enabled": False,    # 默认不显示在导航栏
        "can_disable": True,         # 用户可自由开关
    },
    {
        "id": "tasks",
        "name": "多任务",
        "icon": "📋",
        "description": "批量处理、任务队列管理",
        "tier": ModuleTier.ADVANCED,
        "import_module": ".tasks_module",
        "import_class": "TasksModule",
        "default_enabled": False,
        "can_disable": True,
    },
    {
        "id": "materials",
        "name": "素材库",
        "icon": "📁",
        "description": "视频、音频、图片素材管理",
        "tier": ModuleTier.ADVANCED,
        "import_module": ".materials_module",
        "import_class": "MaterialsModule",
        "default_enabled": False,
        "can_disable": True,
    },
    {
        "id": "models",
        "name": "模型管理",
        "icon": "🤖",
        "description": "本地/云端 AI 模型管理与切换（文案/剪辑流水线依赖此处配置）",
        "tier": ModuleTier.ADVANCED,
        "import_module": ".model_management",
        "import_class": "ModelManagementModule",
        "default_enabled": False,
        "can_disable": True,
    },
    {
        "id": "characters",
        "name": "AI 画布",
        "icon": "🎨",
        "description": "镶嵌自研拾光导演台画布：角色资产 + 生图/生视频回流剪辑",
        "tier": ModuleTier.ADVANCED,
        "import_module": ".character_management_module",
        "import_class": "CharacterManagementModule",
        "default_enabled": True,
        "can_disable": True,
        "optional": True,  # WebEngine / vendor 缺失时仍可导入，界面内提示
    },

    # ╔═════════════════════════╗
    # ║ 实验功能 (EXPERIMENTAL) ║ ← 默认关闭，手动开启，不保证稳定
    # ╚═════════════════════════╝
    {
        "id": "extensions",
        "name": "拓展中心",
        "icon": "🔌",
        "description": "Skill 插件 + MCP 服务统一管理（实验性）",
        "tier": ModuleTier.EXPERIMENTAL,
        "import_module": ".extensions_module",
        "import_class": "ExtensionsModule",
        "default_enabled": True,
        "can_disable": True,
        "optional": True,
    },
    {
        "id": "performance",
        "name": "性能监控",
        "icon": "📊",
        "description": "系统资源监控、性能指标",
        "tier": ModuleTier.EXPERIMENTAL,
        "import_module": ".performance_module",
        "import_class": "PerformanceModule",
        "default_enabled": False,
        "can_disable": True,
    },
]


# ═══════════════════════════════════════════════════════════════
# 模块注册表单例类
#
# 核心职责：
#   1. 管理所有模块的启用/禁用状态
#   2. 通过 _overrides 字典记录用户偏离默认值的开关选择
#   3. 双保险持久化（QSettings 注册表 + JSON 文件备份）
#   4. 提供查询接口供 MainWindow 决定导航栏显示哪些模块
#
# 状态判断优先级（is_enabled 逻辑）：
#   ① can_disable=False 的 CORE 模块 → 强制 True（不可被覆盖）
#   ② _overrides 中有记录 → 使用用户选择值
#   ③ 以上均无 → 使用 default_enabled 默认值
#
# 持久化设计（双保险）：
#   主存储：QSettings("拾光剪影", "Settings") → Windows 注册表
#   备份存储：{项目根}/data/module_switches.json → 纯文本 JSON
#   启动时：QSettings 优先，若为空则 JSON 兜底，若都有则合并
# ═══════════════════════════════════════════════════════════════


@dataclass
class ModuleRegistry:
    """模块注册表 - 全局单例，管理所有功能模块的启用状态"""

    # _definitions: 从 _MODULE_DEFINITIONS 拷贝的模块元信息列表
    _definitions: list[ModuleDefinition] = field(default_factory=list)
    # _overrides: 用户偏离默认值的开关选择，key=module_id, value=True/False
    # 只记录与 default_enabled 不同的值，减少持久化数据量
    _overrides: dict[str, bool] = field(default_factory=dict)
    # QSettings 中存储的键名
    _settings_key: str = "module_switches"
    # 防止重复初始化的标记
    _initialized: bool = False

    # ─── 初始化 ──────────────────────────────────────────────

    def initialize(self):
        """一次性初始化：加载模块定义 + 从持久化存储读取用户开关。

        该方法设计为幂等：_initialized 标记确保只执行一次，
        避免 QSettings 反复读取。
        """
        if self._initialized:
            return
        # 深拷贝模块定义列表，防止外部修改原始数据
        self._definitions = list(_MODULE_DEFINITIONS)
        # 从 QSettings + JSON 备份恢复用户之前的开关选择
        self._load_overrides()
        self._initialized = True

    # ─── 持久化（双保险）────────────────────────────────────

    def _load_overrides(self):
        """从 QSettings（注册表）和 JSON 备份文件读取开关覆盖。

        双保险策略：
          ① 优先从 QSettings 读取（Windows 注册表，速度快）
          ② 若 QSettings 为空，从 JSON 文件兜底
          ③ 若两者都有，合并（QSettings 优先，JSON 补充缺失项）

        这样即使注册表损坏或用户迁移电脑（复制 JSON），
        开关设置也不会丢失。
        """
        overrides: dict[str, bool] = {}
        loaded_from = "none"  # 记录数据来源，方便调试

        # ── 方式①：QSettings（存储于 Windows 注册表）──
        try:
            settings = QSettings("拾光剪影", "Settings")  # pyright: ignore[reportUnknownVariableType]
            raw: object = settings.value(self._settings_key, None)  # pyright: ignore[reportUnknownMemberType]
            if raw:
                # QSettings 可能返回 str（JSON字符串）或 dict 类型
                if isinstance(raw, str):
                    parsed = cast(object, json.loads(raw))
                    if isinstance(parsed, dict):
                        pd = cast(dict[str, object], parsed)
                        overrides = {k: bool(v) for k, v in pd.items()}
                elif isinstance(raw, dict):
                    rd = cast(dict[str, object], raw)
                    overrides = {k: bool(v) for k, v in rd.items()}
                loaded_from = "QSettings"
        except Exception as e:
            logger.error(f'[ModuleRegistry] QSettings 读取失败: {e}')

        # ── 方式②：JSON 文件备份（兜底+补充）──
        try:
            import os as _os
            # 路径：{项目根}/data/module_switches.json
            backup_path = _os.path.join(
                _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))),
                "data", "module_switches.json"
            )
            if _os.path.exists(backup_path):
                with open(backup_path, "r", encoding="utf-8") as f:
                    file_raw = cast(object, json.load(f))
                if not overrides and isinstance(file_raw, dict):
                    # QSettings 为空 → 完全使用 JSON 备份
                    fd = cast(dict[str, object], file_raw)
                    overrides = {k: bool(v) for k, v in fd.items()}
                    loaded_from = "json_backup"
                elif file_raw and isinstance(file_raw, dict):
                    # QSettings 和 JSON 都有 → 合并，QSettings 优先
                    fd = cast(dict[str, object], file_raw)
                    for k, v in fd.items():
                        if k not in overrides:
                            overrides[k] = bool(v)
                    loaded_from = "merged"
        except Exception as e:
            logger.error(f'[ModuleRegistry] JSON 备份读取失败: {e}')

        # ── 迁移旧模块 ID（plugins → extensions）──
        # 升级提示：用户之前可能使用旧的 "plugins" 模块 ID
        # 迁移到新的 "extensions" 模块 ID，保持用户设置不丢失
        if "plugins" in overrides and "extensions" not in overrides:
            overrides["extensions"] = overrides.pop("plugins")
            logger.info('[ModuleRegistry] 已迁移模块设置: plugins → extensions')

        # 账号运营已彻底移除，丢弃导航开关残留，避免设置页出现死项
        if "account" in overrides:
            overrides.pop("account", None)
            logger.info('[ModuleRegistry] 已移除废弃模块开关: account')

        self._overrides = overrides
        if overrides:
            msg = (
                f"[ModuleRegistry] 加载了 {len(overrides)} 个功能开关覆盖 "
                f"(来源: {loaded_from}): {list(overrides.keys())}"
            )
            logger.info(msg)
        else:
            logger.info(f'[ModuleRegistry] 无功能开关覆盖（全部使用默认值）')

    def _save_overrides(self):
        """双保险保存开关覆盖：同时写入 QSettings 和 JSON 备份文件。

        为什么需要 JSON 备份？
          • Windows 注册表（QSettings）在某些环境下可能被安全软件拦截
          • JSON 文件方便用户手动编辑或迁移到其他电脑
          • 注册表损坏时 JSON 可以兜底恢复
        """
        data_str = json.dumps(self._overrides, ensure_ascii=False)

        # ── 方式①：写入 QSettings ──
        try:
            settings = QSettings("拾光剪影", "Settings")  # type: ignore[reportUnknownVariableType]
            settings.setValue(self._settings_key, data_str)  # type: ignore[reportUnknownMemberType]
            # sync() 强制立即刷盘，避免进程崩溃导致数据丢失
            settings.sync()  # type: ignore[reportUnknownMemberType]
        except Exception as e:
            logger.error(f'[ModuleRegistry] QSettings 保存失败: {e}')

        # ── 方式②：写入 JSON 备份文件 ──
        try:
            import os as _os
            data_dir = _os.path.join(
                _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))),
                "data"
            )
            _os.makedirs(data_dir, exist_ok=True)
            backup_path = _os.path.join(data_dir, "module_switches.json")
            with open(backup_path, "w", encoding="utf-8") as f:
                # indent=2 生成人类可读的格式，方便手动检查
                json.dump(self._overrides, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f'[ModuleRegistry] JSON 备份保存失败: {e}')

        msg = (
            f"[ModuleRegistry] 保存了 {len(self._overrides)} 个功能开关覆盖: "
            f"{list(self._overrides.keys())}"
        )
        logger.info(msg)

    # ─── 查询接口 ────────────────────────────────────────────

    def all_modules(self) -> list[EnrichedModuleInfo]:
        """返回所有模块定义，每个包含动态计算的 enabled 状态和中文分级标签"""
        self.initialize()
        result: list[EnrichedModuleInfo] = []
        for mod in self._definitions:
            # 双重 cast：spread dict 类型为联合类型，需经 object 中转
            m = cast(EnrichedModuleInfo, cast(object, {
                **mod,
                "enabled": self.is_enabled(mod["id"]),
                "tier_label": self._tier_label(mod["tier"]),
            }))
            result.append(m)
        return result

    def modules_by_tier(self, tier: ModuleTier) -> list[EnrichedModuleInfo]:
        """按分级过滤，用于设置面板的分组展示"""
        return [m for m in self.all_modules() if m["tier"] == tier]

    def enabled_modules(self) -> list[EnrichedModuleInfo]:
        """返回当前已启用的模块（MainWindow 用来构建导航栏）"""
        return [m for m in self.all_modules() if m["enabled"]]

    def disabled_modules(self) -> list[EnrichedModuleInfo]:
        """返回当前已关闭的模块（仅用于统计）"""
        return [m for m in self.all_modules() if not m["enabled"]]

    def is_enabled(self, module_id: str) -> bool:
        """判断某个模块当前是否启用。

        优先级（从高到低）：
          ① CORE 模块且 can_disable=False → 强制 True，不可覆盖
          ② _overrides 中有记录 → 返回用户选择值
          ③ 以上都不满足 → 返回 default_enabled 默认值
        """
        self.initialize()
        for mod in self._definitions:
            if mod["id"] == module_id:
                # ① 核心不可关闭模块 → 强制启用
                if mod["tier"] == ModuleTier.CORE and not mod.get("can_disable", True):
                    return True
                # ② 用户覆盖值优先
                if module_id in self._overrides:
                    return bool(self._overrides[module_id])
                # ③ 回退到默认值
                return bool(mod.get("default_enabled", False))
        # 模块 id 不存在于定义表中
        return False

    def can_toggle(self, module_id: str) -> bool:
        """判断模块是否允许用户切换开关。
        只有 can_disable=True 的模块才能被 toggle() 操作。
        """
        self.initialize()
        for mod in self._definitions:
            if mod["id"] == module_id:
                return bool(mod.get("can_disable", True))
        return False

    def get_definition(self, module_id: str) -> ModuleDefinition | None:
        """获取指定模块的元信息定义，不存在返回 None"""
        self.initialize()
        for mod in self._definitions:
            if mod["id"] == module_id:
                return cast(ModuleDefinition, cast(object, {**mod}))
        return None

    # ─── 修改接口 ────────────────────────────────────────────

    def toggle(self, module_id: str, enabled: bool) -> bool:
        """切换模块开关。

        参数:
          module_id: 模块标识符（如 "copywriting"）
          enabled:   True=开启, False=关闭

        返回:
          True  表示开关状态确实发生了变化（触发导航栏更新）
          False 表示无变化或操作被拒绝（can_disable=False 的模块）

        核心逻辑：
          用户值 == default_enabled  → 从 _overrides 移除（节省存储）
          用户值 != default_enabled  → 写入 _overrides（覆盖默认值）

        注意：此方法不依赖 is_enabled() 来判断变化，
        而是直接比较用户目标和当前 _overrides 状态，
        避免了 is_enabled() 的多级回退逻辑造成的误判。
        """
        self.initialize()
        definition = self.get_definition(module_id)
        if definition is None:
            return False                     # 模块不存在
        if not self.can_toggle(module_id):
            return False                     # 核心模块不可关

        enabled = bool(enabled)
        old_override = module_id in self._overrides    # 之前是否有用户覆盖
        default_enabled = bool(definition.get("default_enabled", False))

        if enabled == default_enabled:
            # 用户选择与默认值一致 → 从覆盖中移除（恢复默认）
            if old_override:
                # 之前有覆盖记录，现在移除了 → 状态变化
                del self._overrides[module_id]
                self._save_overrides()
                return True
            # 本来就无覆盖且与默认值一致 → 无变化
            return False
        else:
            # 用户选择与默认值不同 → 必须记录覆盖
            if old_override and self._overrides.get(module_id) == enabled:
                # 覆盖值已经与目标相同 → 无变化
                return False
            # 写入新的覆盖值
            self._overrides[module_id] = enabled
            self._save_overrides()
            return True

    def reset_all(self):
        """重置所有开关为默认值（清空所有 _overrides 记录）"""
        self.initialize()
        self._overrides.clear()
        self._save_overrides()

    # ─── 工具方法 ────────────────────────────────────────────

    @staticmethod
    def _tier_label(tier: ModuleTier) -> str:
        """将枚举值转为中文显示标签"""
        labels = {
            ModuleTier.CORE: "核心功能",
            ModuleTier.ADVANCED: "高级功能",
            ModuleTier.EXPERIMENTAL: "实验功能",
        }
        return labels.get(tier, str(tier))

    def summary(self) -> dict[str, int]:
        """返回模块统计数据，用于性能监控面板"""
        stats = {
            ModuleTier.CORE: 0,
            ModuleTier.ADVANCED: 0,
            ModuleTier.EXPERIMENTAL: 0,
            "enabled": 0,
            "disabled": 0,
        }
        for m in self.all_modules():
            stats[m["tier"]] = stats.get(m["tier"], 0) + 1
            if m["enabled"]:
                stats["enabled"] += 1
            else:
                stats["disabled"] += 1
        return stats


# ─── 全局单例管理 ────────────────────────────────────────────

# 模块级变量，存储唯一的 ModuleRegistry 实例（单例模式）
# 注意：虽然以 _ 开头表示模块私有，但使用小写命名表明它是可变变量而非常量
_registry_instance: ModuleRegistry | None = None


def get_registry() -> ModuleRegistry:
    """获取模块注册表全局单例（使用懒初始化模式）。

    首次调用时创建实例并加载持久化数据，
    后续调用直接返回已初始化的实例。
    """
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = ModuleRegistry()
        _registry_instance.initialize()
    return _registry_instance


def reload_registry() -> ModuleRegistry:
    """强制重新加载注册表。

    使用场景：
      • 设置面板中用户点击「恢复默认设置」
      • 手动修改了 data/module_switches.json 后热加载
    """
    global _registry_instance
    _registry_instance = None   # 清空缓存，下次 get_registry() 重新创建
    return get_registry()
