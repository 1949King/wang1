# Lego package

# 导入核心组件
from .core import EventBus, MasterClock, DataBus, EventType, event_bus, master_clock, data_bus
from .skill_engine import SkillEngine, skill_engine
from .auth import auth_service
from .builtin_blocks import BUILTIN_BLOCKS
from .main_window import MainWindow
from .modules import HomeModule, EditorModule, MaterialsModule, AccountOpsModule, CopywritingModule, TasksModule, DramaFinderModule, PluginsModule, PerformanceModule
from .model_management import ModelManagementModule
from .settings_module import SettingsModule, HelpModule
from .ai_clip_flow import AIClipFlowModule

# 导入视频编辑技能
from .video_editing_skill import register_skills
from .account_skills import register_account_skills

# 注册技能
register_skills()
register_account_skills()
