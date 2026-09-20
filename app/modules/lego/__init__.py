# Lego package — 延迟导入，避免包级拉齐全部业务模块导致启动失败

from .core import EventBus, MasterClock, DataBus, EventType, event_bus, master_clock, data_bus

__all__ = [
    "EventBus",
    "MasterClock",
    "DataBus",
    "EventType",
    "event_bus",
    "master_clock",
    "data_bus",
    "MainWindow",
    "SkillEngine",
]


def __getattr__(name: str):
    if name == "MainWindow":
        from .main_window import MainWindow
        return MainWindow
    if name == "SkillEngine":
        from .skill_engine import SkillEngine
        return SkillEngine
    if name == "auth_service":
        from .auth import auth_service
        return auth_service
    if name == "BUILTIN_BLOCKS":
        from .builtin_blocks import BUILTIN_BLOCKS
        return BUILTIN_BLOCKS
    if name == "register_skills":
        from .video_editing_skill import register_skills
        return register_skills
    if name in (
        "HomeModule",
        "EditorModule",
        "MaterialsModule",
        "CopywritingModule",
        "TasksModule",
        "PluginsModule",
        "PerformanceModule",
    ):
        from . import modules as _modules
        return getattr(_modules, name)
    # 拓展中心（升级版插件中心，整合 Skill + MCP）
    if name == "ExtensionsModule":
        from .extensions_module import ExtensionsModule
        return ExtensionsModule
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
