"""
AI短剧编辑器 - Qt6 主程序入口
============================
专业级架构：乐高积木式插件系统 + Skill 执行引擎

功能模块结构：
├── 首页模块 (HomeModule) - 快速入口、统计、最近项目
├── 剪辑模块 (EditorModule) - 轨道、预览、滤镜、字幕
├── 文案生成模块 (CopywritingModule) - AI文案、标题、脚本
├── 多任务模块 (TasksModule) - 批量处理、任务队列
├── 短剧筛选（插件 drama_finder_plugin，含 crawler）- 剧单、热度、佣金
├── 账号运营模块 (AccountOpsModule) - Skill化运营
├── 素材库模块 (MaterialsModule) - 视频、音频、图片管理
├── 插件中心模块 (PluginsModule) - 积木管理
└── 性能监控模块 (PerformanceModule) - 系统监控

内核 Core：
├── EventBus - 全局事件总线
├── MasterClock - 全局时钟
├── DataBus - 数据总线
├── SkillEngine - Skill执行引擎
└── BlockLoader - 积木加载器

认证系统：
├── AuthService - 本地认证服务
├── SQLite数据库 - 用户数据存储
└── 设备绑定 - 最多3台设备
"""

import os
import sys
import json
import traceback
import logging
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = APP_DIR.parent
# 确保项目根目录在 sys.path 中，以便 `from app.core.xxx` 等绝对导入生效
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(APP_DIR))

from app.version import __version__

if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"com.ai-drama-editor.app.{__version__}")
        # DEBUG: 暂时不禁用控制台，方便排查问题
        # ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)
    except Exception as e:
        print(f"[main_qt6] Windows API 初始化警告: {e}")

from .core.log_manager import setup_logging

LOGS_DIR = APP_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)

logger = setup_logging(
    app_name="AI短剧编辑器",
    log_dir=str(LOGS_DIR),
    console_level=logging.INFO,
    file_level=logging.DEBUG,
    max_bytes=10*1024*1024,
    backup_count=5,
    enable_console=True,
    enable_file=True,
)

# ===== 崩溃日志钩子 =====
_CRASH_LOG = APP_DIR / "_crash_report.log"
def _install_crash_hook():
    """安装全局异常捕获，确保闪退时能记录到文件"""
    _orig_excepthook = sys.excepthook
    def _crash_handler(exc_type: type[BaseException], exc_value: BaseException, exc_tb: object) -> None:
        # type: ignore[reportArgumentType] — exc_tb is actually TracebackType at runtime
        with open(_CRASH_LOG, "w", encoding="utf-8") as f:
            traceback.print_exception(exc_type, exc_value, exc_tb, file=f)  # type: ignore[reportArgumentType]
        _orig_excepthook(exc_type, exc_value, exc_tb)  # type: ignore[reportArgumentType]
    sys.excepthook = _crash_handler

_install_crash_hook()


class AppConfig:
    """应用配置管理"""
    
    _instance: 'AppConfig | None' = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False  # type: ignore[reportInvalidTypeForm]
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        
        self._config: dict[str, Any] = {}
        self._config_path: Path = APP_DIR / "config.json"
        self._load_config()
    
    def _load_config(self):
        """加载配置文件"""
        if self._config_path.exists():
            try:
                with open(self._config_path, 'r', encoding='utf-8') as f:
                    self._config = json.load(f)
                logger.info(f"配置文件加载成功: {self._config_path}")
            except Exception as e:
                logger.warning(f"配置文件加载失败: {e}")
                self._set_default_config()
        else:
            self._set_default_config()
    
    def _set_default_config(self):
        """设置默认配置"""
        self._config = {
            "paths": {
                "temp_dir": str(APP_DIR / "temp"),
                "models_dir": str(APP_DIR / "models"),
                "素材库_path": str(APP_DIR / "素材库"),
                "output_dir": str(APP_DIR / "output"),
                "脚本库_path": str(APP_DIR / "脚本库"),
                "运营数据": str(APP_DIR / "运营数据"),
                "发布记录": str(APP_DIR / "发布记录")
            },
            "models": {
                "sentiment_analyzer": "uer/roberta-base-finetuned-chinanews-chinese",
                "faster_whisper_size": "tiny",
                "easyocr_languages": ["ch_sim", "en"],
                "ai_model": "DeepSeek"
            },
            "processing": {
                "max_duration_per_clip": 10,
                "target_durations": {
                    "short": 60,
                    "medium": 360,
                    "long": 900
                },
                "max_threads": 15,
                "gpu_encoder": "auto"
            },
            "ui": {
                "theme": "dark",
                "language": "zh_CN",
                "auto_save": True,
                "auto_save_interval": 300
            }
        }
        logger.info("使用默认配置")
    
    def get(self, key: str, default: Any = None) -> Any:
        """获取配置项"""
        keys = key.split('.')
        value = self._config
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value
    
    def set(self, key: str, value: Any):
        """设置配置项"""
        keys = key.split('.')
        config = self._config
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        config[keys[-1]] = value
    
    def save(self):
        """保存配置"""
        try:
            with open(self._config_path, 'w', encoding='utf-8') as f:
                json.dump(self._config, f, ensure_ascii=False, indent=2)
            logger.info("配置已保存")
        except Exception as e:
            logger.error(f"配置保存失败: {e}")
    
    @property
    def paths(self) -> dict[str, str]:
        return self._config.get("paths", {})
    
    @property
    def models(self) -> dict[str, Any]:
        return self._config.get("models", {})
    
    @property
    def processing(self) -> dict[str, Any]:
        return self._config.get("processing", {})


class DependencyChecker:
    """依赖检查器"""
    
    REQUIRED_PACKAGES: dict[str, str] = {
        "PyQt6": "PyQt6",
        "moviepy": "moviepy",
        "opencv-python-headless": "cv2",
        "torch": "torch",
        "transformers": "transformers",
        "faster-whisper": "faster_whisper",
        "easyocr": "easyocr",
        "Pillow": "PIL",
        "numpy": "numpy",
    }
    
    OPTIONAL_PACKAGES: dict[str, str] = {
        "mediapipe": "mediapipe",
        "dashscope": "dashscope",
        "anthropic": "anthropic",
        "zhipuai": "zhipuai",
        "gTTS": "gtts",
        "pynvml": "pynvml",
    }
    
    @classmethod
    def check_dependencies(cls) -> dict[str, dict[str, bool]]:
        """检查依赖"""
        results: dict[str, dict[str, bool]] = {"required": {}, "optional": {}}
        
        for package, import_name in cls.REQUIRED_PACKAGES.items():
            try:
                __import__(import_name)
                results["required"][package] = True
            except Exception:
                results["required"][package] = False
        
        for package, import_name in cls.OPTIONAL_PACKAGES.items():
            try:
                __import__(import_name)
                results["optional"][package] = True
            except Exception:
                results["optional"][package] = False
        
        return results
    
    @classmethod
    def check_ffmpeg(cls) -> bool:
        """检查 FFmpeg"""
        try:
            from app.core.ffmpeg_utils import find_ffmpeg
            ffmpeg_path = find_ffmpeg()
            if ffmpeg_path and os.path.exists(ffmpeg_path):
                return True
        except ImportError as e:
            logger.debug(f"find_ffmpeg 导入失败，回退到系统 ffmpeg 检测: {e}")
        
        try:
            import subprocess
            result = subprocess.run(
                ["ffmpeg", "-version"],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            return result.returncode == 0
        except Exception as e:
            logger.debug(f"系统 ffmpeg 检测失败，返回 False: {e}")
            return False
    
    @classmethod
    def check_gpu(cls) -> dict[str, bool | str | None]:
        """检查 GPU"""
        gpu_info: dict[str, bool | str | None] = {"available": False, "type": None, "name": None}
        
        try:
            import torch  # type: ignore[reportMissingImports]
            if hasattr(torch, 'cuda') and callable(getattr(torch.cuda, 'is_available', None)) and torch.cuda.is_available():
                gpu_info["available"] = True
                gpu_info["type"] = "NVIDIA CUDA"
                gpu_info["name"] = torch.cuda.get_device_name(0)
            elif hasattr(torch, 'backends') and hasattr(torch.backends, 'mps') and getattr(torch.backends.mps, 'is_available', lambda: False)():
                gpu_info["available"] = True
                gpu_info["type"] = "Apple Metal"
                gpu_info["name"] = "Apple GPU"
        except Exception as e:
            logger.debug(f"GPU 检测失败，按未检测到处理: {e}")
        
        return gpu_info
    
    @classmethod
    def print_report(cls):
        """打印依赖报告"""
        print("\n" + "=" * 50)
        print("依赖检查报告")
        print("=" * 50)
        
        deps = cls.check_dependencies()
        
        print("\n必需依赖:")
        for package, installed in deps["required"].items():
            status = "✅" if installed else "❌"
            print(f"  {status} {package}")
        
        print("\n可选依赖:")
        for package, installed in deps["optional"].items():
            status = "✅" if installed else "⚠️"
            print(f"  {status} {package}")
        
        ffmpeg = cls.check_ffmpeg()
        print(f"\nFFmpeg: {'✅ 已安装' if ffmpeg else '❌ 未安装'}")
        
        gpu = cls.check_gpu()
        if gpu["available"]:
            print(f"\nGPU: ✅ {gpu['type']} - {gpu['name']}")
        else:
            print(f"\nGPU: ⚠️ 未检测到GPU加速")
        
        print("=" * 50 + "\n")


class Application:
    """应用程序主类"""
    
    def __init__(self):
        self._config: AppConfig = AppConfig()
        self._qt_app: 'object | None' = None
        self._main_window: 'object | None' = None
        self._login_window: 'object | None' = None
        self._event_bus: 'object | None' = None
        self._master_clock: 'object | None' = None
        self._data_bus: 'object | None' = None
        self._skill_engine: 'object | None' = None
        self._auth_service: 'object | None' = None
        self._security_checker: 'object | None' = None
        self._permission_manager: 'object | None' = None
        self._apm_collector: 'object | None' = None
        self._alert_manager: 'object | None' = None
        self._i18n: 'object | None' = None
    
    def _check_environment(self) -> bool:
        """检查运行环境"""
        print("\n🔍 检查运行环境...")
        
        deps = DependencyChecker.check_dependencies()
        
        pyqt6_installed = deps["required"].get("PyQt6", False)
        if not pyqt6_installed:
            print(f"\n❌ 缺少必需依赖: PyQt6")
            print("请运行: pip install PyQt6")
            return False
        
        if not DependencyChecker.check_ffmpeg():
            print("\n⚠️ FFmpeg 未安装，部分功能可能受限")
        
        gpu = DependencyChecker.check_gpu()
        if gpu["available"]:
            print(f"✅ GPU 加速: {gpu['type']} - {gpu['name']}")
        else:
            print("⚠️ 未检测到 GPU，将使用 CPU 运行")
        
        return True
    
    def _init_paths(self):
        """初始化路径"""
        print("\n📁 初始化路径...")
        
        paths = self._config.paths
        for name, path in paths.items():
            Path(path).mkdir(parents=True, exist_ok=True)
            print(f"  ✅ {name}: {path}")
    
    def _init_core(self):
        """初始化核心组件"""
        print("\n🔧 初始化核心组件...")

        from .modules.lego import EventBus, MasterClock, DataBus, SkillEngine, auth_service

        # 修复 P0-C: 启动时自动升级 PII 文件为加密格式 (一次性, 失败不阻塞)
        try:
            from .core.secure_store import upgrade_pii_files
            upgrade_pii_files()
            logger.info("  ✅ PII 加密升级 (P0-C)")
        except Exception as e:
            logger.warning(f"  ⚠️ PII 升级跳过: {e}")

        self._event_bus = EventBus.get_instance()
        self._master_clock = MasterClock.get_instance()
        self._data_bus = DataBus.get_instance()
        self._skill_engine = SkillEngine.get_instance()
        self._auth_service = auth_service
        
        self._data_bus.set("config", self._config)
        self._data_bus.set("app_dir", str(APP_DIR))

        print("  ✅ EventBus - 事件总线")
        print("  ✅ MasterClock - 全局时钟")
        print("  ✅ DataBus - 数据总线")
        print("  ✅ SkillEngine - Skill执行引擎")
        print("  ✅ AuthService - 认证服务")

        # 修复 C1: 接线 5 大基础设施模块 (apm/alert/security/permission/i18n)
        # 全部包 try/except, 失败降级不阻塞启动
        self._init_infrastructure()

    def _init_infrastructure(self):
        """C1: 初始化 5 大基础设施模块 (apm/alert/security/permission/i18n)"""
        # 1. 安全检查器 (路径白名单/输入校验)
        try:
            from .core.security import get_security_checker
            self._security_checker = get_security_checker(
                allowed_base_dirs=[str(APP_DIR)]
            )
            logger.info("  ✅ SecurityChecker - 路径安全/输入校验")
        except Exception as e:
            self._security_checker = None
            logger.warning(f"  ⚠️ SecurityChecker 降级: {e}")

        # 2. 权限管理 (RBAC)
        try:
            from .core.permission_management import get_permission_manager
            self._permission_manager = get_permission_manager()
            logger.info("  ✅ PermissionManager - RBAC 权限管理")
        except Exception as e:
            self._permission_manager = None
            logger.warning(f"  ⚠️ PermissionManager 降级: {e}")

        # 3. APM 监控 (性能指标采集)
        try:
            from .core.apm_monitoring import get_apm_collector
            self._apm_collector = get_apm_collector()
            logger.info("  ✅ APMCollector - 性能监控")
        except Exception as e:
            self._apm_collector = None
            logger.warning(f"  ⚠️ APMCollector 降级: {e}")

        # 4. 告警系统
        try:
            from .core.alert_system import get_alert_manager
            self._alert_manager = get_alert_manager()
            logger.info("  ✅ AlertManager - 告警管理")
        except Exception as e:
            self._alert_manager = None
            logger.warning(f"  ⚠️ AlertManager 降级: {e}")

        # 5. 国际化
        try:
            from .core.i18n import I18n
            self._i18n = I18n()
            locale = self._config.get("ui", {}).get("language", "zh_CN")
            self._i18n.set_locale(locale)
            logger.info(f"  ✅ I18n - 国际化 (locale={locale})")
        except Exception as e:
            self._i18n = None
            logger.warning(f"  ⚠️ I18n 降级: {e}")
    
    def _init_blocks(self):
        """初始化积木系统"""
        print("\n🧱 初始化积木系统...")
        
        from .modules.lego import BUILTIN_BLOCKS
        
        for block_class in BUILTIN_BLOCKS:
            try:
                temp_instance = block_class()
                meta = temp_instance.info()
                print(f"  ✅ {meta.icon} {meta.name} v{meta.version}")
            except Exception as e:
                print(f"  ❌ 积木加载失败: {e}")
        
        print(f"✅ 已加载 {len(BUILTIN_BLOCKS)} 个内置积木")
    
    def _init_skills(self):
        """初始化 Skill 系统"""
        print("\n🎯 初始化 Skill 系统...")
        
        from .modules.lego import register_account_skills, register_skills
        
        register_skills()
        register_account_skills()
        print("✅ Skill 系统初始化完成")
    
    def _init_qt(self):
        """初始化 Qt 应用"""
        print("\n🖥️ 初始化 Qt6 应用...")
        
        from PyQt6.QtWidgets import QApplication  # type: ignore[reportMissingImports]
        from PyQt6.QtGui import QFont  # type: ignore[reportMissingImports]
        
        self._qt_app = QApplication(sys.argv)
        self._qt_app.setStyle("Fusion")  # type: ignore[reportAttributeAccessIssue,reportOptionalMemberAccess]
        
        font = QFont("Microsoft YaHei", 10)
        self._qt_app.setFont(font)  # type: ignore[reportAttributeAccessIssue,reportOptionalMemberAccess]
        
        self._qt_app.setStyleSheet("""  # type: ignore[reportAttributeAccessIssue,reportOptionalMemberAccess]
            QWidget {
                font-family: "Microsoft YaHei", "Segoe UI", "PingFang SC", sans-serif;
            }
            QToolTip {
                background-color: #1a1a1a;
                color: #ffffff;
                border: none;
                padding: 8px 12px;
                border-radius: 6px;
            }
            QScrollBar:vertical {
                background-color: #1a1a1a;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background-color: #3a3a3a;
                border-radius: 6px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #4a4a4a;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar:horizontal {
                background-color: #1a1a1a;
                height: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:horizontal {
                background-color: #3a3a3a;
                border-radius: 6px;
                min-width: 30px;
            }
            QScrollBar::handle:horizontal:hover {
                background-color: #4a4a4a;
            }
            QMenu {
                background-color: #1a1a1a;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 6px;
                padding: 4px;
            }
            QMenu::item {
                padding: 8px 24px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #1e6bde;
            }
            QComboBox {
                background-color: #1a1a1a;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 6px;
                padding: 6px 12px;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox QAbstractItemView {
                background-color: #1a1a1a;
                color: #ffffff;
                selection-background-color: #1e6bde;
                border: 1px solid #333333;
            }
            QLineEdit {
                background-color: #1a1a1a;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 6px;
                padding: 8px 12px;
            }
            QLineEdit:focus {
                border-color: #1e6bde;
            }
            QTextEdit {
                background-color: #1a1a1a;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 6px;
            }
            QTableWidget {
                background-color: #1a1a1a;
                color: #ffffff;
                gridline-color: #333333;
                border: 1px solid #333333;
                border-radius: 6px;
            }
            QTableWidget::item {
                padding: 8px;
            }
            QTableWidget::item:selected {
                background-color: #1e6bde;
            }
            QHeaderView::section {
                background-color: #2a2a2a;
                color: #808080;
                padding: 10px;
                border: none;
                border-bottom: 1px solid #333333;
            }
            QListWidget {
                background-color: #1a1a1a;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 6px;
            }
            QListWidget::item {
                padding: 10px;
                border-bottom: 1px solid #2a2a2a;
            }
            QListWidget::item:selected {
                background-color: #1e6bde;
            }
            QListWidget::item:hover:!selected {
                background-color: #2a2a2a;
            }
            QGroupBox {
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px;
            }
            QProgressBar {
                background-color: #1a1a1a;
                border: none;
                border-radius: 4px;
                text-align: center;
                color: #ffffff;
            }
            QProgressBar::chunk {
                background-color: #1e6bde;
                border-radius: 4px;
            }
            QSlider::groove:horizontal {
                background-color: #2a2a2a;
                height: 6px;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background-color: #1e6bde;
                width: 16px;
                height: 16px;
                margin: -5px 0;
                border-radius: 8px;
            }
            QCheckBox {
                color: #ffffff;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 1px solid #333333;
            }
            QCheckBox::indicator:checked {
                background-color: #1e6bde;
                border-color: #1e6bde;
            }
            QRadioButton {
                color: #ffffff;
                spacing: 8px;
            }
            QRadioButton::indicator {
                width: 18px;
                height: 18px;
                border-radius: 9px;
                border: 1px solid #333333;
            }
            QRadioButton::indicator:checked {
                background-color: #1e6bde;
                border-color: #1e6bde;
            }
        """)
        
        print("  ✅ Qt6 应用初始化完成")
    
    def _init_modules(self):
        """初始化功能模块 — 通过注册表按需加载（仅加载用户启用的模块）"""
        print("\n🧩 初始化功能模块（按注册表开关）...")
        
        from .modules.lego import MainWindow  # type: ignore[import-untyped]
        from .modules.lego.module_registry import get_registry
        
        mw = MainWindow()
        self._main_window = mw
        
        # MainWindow.__init__() 已调用 _setup_default_modules()
        # 该方法从注册表读取启用状态，只注册已启用的模块导航按钮
        # 模块 widget 采用懒加载：首次点击时才实例化（大幅降低启动内存）
        
        registry = get_registry()
        enabled = registry.enabled_modules()
        print(f"✅ 注册表：{len(registry.all_modules())} 个定义，"
              f"当前启用 {len(enabled)} 个，关闭 {len(registry.disabled_modules())} 个")
        
        # 预加载首页模块 widget（用户看到的第一个页面）
        if mw._nav_bar.has_module("home"):
            mw._nav_bar.select_module("home")
    
    def _setup_event_handlers(self):
        """设置事件处理器"""
        from .modules.lego import EventType
        
        eb = self._event_bus
        db = self._data_bus
        if eb is None:
            return
        
        def on_video_loaded(event: object) -> None:
            video_path = getattr(event, 'data', {}).get("path", "")
            logger.info(f"视频已加载: {video_path}")
            if db is not None:
                db.set("current_video", video_path)  # type: ignore[reportAttributeAccessIssue]
        
        def on_task_started(event: object) -> None:
            task_name = getattr(event, 'data', {}).get("task", "")
            logger.info(f"任务开始: {task_name}")
        
        def on_task_completed(_event: object) -> None:
            logger.info("任务完成")
        
        def on_error(event: object) -> None:
            error_msg = getattr(event, 'data', {}).get("error", "未知错误")
            logger.error(f"错误: {error_msg}")
        
        eb.on(EventType.VIDEO_LOADED, on_video_loaded)  # type: ignore[reportAttributeAccessIssue]
        eb.on(EventType.TASK_STARTED, on_task_started)  # type: ignore[reportAttributeAccessIssue]
        eb.on(EventType.TASK_COMPLETED, on_task_completed)  # type: ignore[reportAttributeAccessIssue]
        eb.on(EventType.ERROR_OCCURRED, on_error)  # type: ignore[reportAttributeAccessIssue]
    
    def _show_login(self) -> bool:
        """显示登录界面"""
        from .modules.lego import LoginWindow  # type: ignore[reportAttributeAccessIssue]
        
        login_win = LoginWindow()
        self._login_window = login_win
        
        if login_win.try_auto_login():
            print("✅ 自动登录成功")
            return True
        
        login_success = [False]
        login_done = [False]
        
        def on_login_success() -> None:
            login_success[0] = True
            login_win.close()
        
        def on_rejected() -> None:
            login_done[0] = True
        
        login_win.login_success.connect(on_login_success)
        login_win.rejected.connect(on_rejected)
        login_win.finished.connect(lambda: login_done.__setitem__(0, True))
        login_win.show()
        
        qt_app = self._qt_app
        while not login_done[0] and qt_app is not None:
            qt_app.processEvents()  # type: ignore[reportAttributeAccessIssue]
        
        return login_success[0]
    
    @staticmethod
    def _safe_print(msg: str) -> None:
        """安全打印，自动处理 GBK 编码问题"""
        try:
            print(msg)
        except UnicodeEncodeError:
            # 回退：用 ASCII 安全字符替换
            safe = msg.encode('gbk', errors='replace').decode('gbk', errors='replace')
            print(safe)

    def run(self) -> int:
        """运行应用"""
        self._safe_print("\n" + "=" * 60)
        self._safe_print(f"AI短剧编辑器 v{__version__} - Qt6版")
        self._safe_print("   乐高积木式插件系统 + Skill 执行引擎")
        self._safe_print("=" * 60)
        
        if not self._check_environment():
            return 1
        
        try:
            self._init_paths()
            self._init_core()
            self._init_blocks()
            self._init_skills()
            self._init_qt()
            self._init_modules()
            self._setup_event_handlers()
            
            mw = self._main_window
            if mw is None:
                logger.error("主窗口未初始化")
                return 1
            qt_app = self._qt_app
            if qt_app is None:
                logger.error("Qt 应用未初始化")
                return 1
            
            self._safe_print("\n>> 启动主窗口...")
            mw.show()  # type: ignore[reportAttributeAccessIssue]
            mw.raise_()  # type: ignore[reportAttributeAccessIssue]
            mw.activateWindow()  # type: ignore[reportAttributeAccessIssue]
            
            auth = self._auth_service
            if auth is not None and auth.is_logged_in:  # type: ignore[reportAttributeAccessIssue]
                user = auth.current_user  # type: ignore[reportAttributeAccessIssue]
                if user:
                    self._safe_print(f"\n欢迎回来, {user.nickname}!")  # type: ignore[reportAttributeAccessIssue]
            else:
                self._safe_print("\n未登录 - 请点击右上角登录/激活按钮")
            
            self._safe_print("\n" + "=" * 60)
            self._safe_print("[OK] 启动完成!")
            self._safe_print("   - 左侧导航栏: 点击切换模块")
            self._safe_print("   - 标签页: 同一模块内功能切换")
            self._safe_print("   - 右上角: 登录/激活按钮")
            self._safe_print("   - 状态栏: 显示执行状态和时间码")
            self._safe_print("=" * 60 + "\n")
            
            logger.info("应用启动成功")
            return qt_app.exec()  # type: ignore[reportAttributeAccessIssue]
            
        except Exception as e:
            logger.error(f"应用启动失败: {e}")
            traceback.print_exc()
            return 1


def main():
    """主入口"""
    # 设置全局异常钩子，捕获未处理的异常
    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logger.critical(f"未处理的异常: {exc_value}", exc_info=(exc_type, exc_value, exc_traceback))
        traceback.print_exception(exc_type, exc_value, exc_traceback)
    
    sys.excepthook = handle_exception
    
    # 强制 stdout/stderr 使用 UTF-8，避免 GBK emoji 编码错误
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception as e:
        logger.debug(f"stdout/stderr 重配置 UTF-8 失败，保持默认编码: {e}")
    
    try:
        app = Application()
        return app.run()
    except Exception as e:
        logger.critical(f"应用启动失败: {e}", exc_info=True)
        try:
            print(f"\n应用启动失败: {e}")
        except UnicodeEncodeError:
            print(f"\n[ERROR] 应用启动失败: {e}")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
