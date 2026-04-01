"""
AI短剧编辑器 - Qt6 主程序入口
============================
专业级架构：乐高积木式插件系统 + Skill 执行引擎

功能模块结构：
├── 首页模块 (HomeModule) - 快速入口、统计、最近项目
├── 剪辑模块 (EditorModule) - 轨道、预览、滤镜、字幕
├── 文案生成模块 (CopywritingModule) - AI文案、标题、脚本
├── 多任务模块 (TasksModule) - 批量处理、任务队列
├── 短剧筛选模块 (DramaFinderModule) - 剧单、热度、佣金
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
import threading
from pathlib import Path
from typing import Optional, Dict, List, Any
from datetime import datetime

if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("com.ai-drama-editor.app.1.0.0")
        ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)
    except:
        pass

APP_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(APP_DIR))

from core.log_manager import setup_logging, get_logger

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


class AppConfig:
    """应用配置管理"""
    
    _instance: Optional['AppConfig'] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        
        self._config: Dict[str, Any] = {}
        self._config_path = APP_DIR / "config.json"
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
    def paths(self) -> Dict[str, str]:
        return self._config.get("paths", {})
    
    @property
    def models(self) -> Dict[str, Any]:
        return self._config.get("models", {})
    
    @property
    def processing(self) -> Dict[str, Any]:
        return self._config.get("processing", {})


class DependencyChecker:
    """依赖检查器"""
    
    REQUIRED_PACKAGES = {
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
    
    OPTIONAL_PACKAGES = {
        "mediapipe": "mediapipe",
        "dashscope": "dashscope",
        "anthropic": "anthropic",
        "zhipuai": "zhipuai",
        "gTTS": "gtts",
        "pynvml": "pynvml",
    }
    
    @classmethod
    def check_dependencies(cls) -> Dict[str, Dict[str, bool]]:
        """检查依赖"""
        results = {"required": {}, "optional": {}}
        
        for package, import_name in cls.REQUIRED_PACKAGES.items():
            try:
                __import__(import_name)
                results["required"][package] = True
            except (ImportError, OSError):
                results["required"][package] = False
        
        for package, import_name in cls.OPTIONAL_PACKAGES.items():
            try:
                __import__(import_name)
                results["optional"][package] = True
            except (ImportError, OSError):
                results["optional"][package] = False
        
        return results
    
    @classmethod
    def check_ffmpeg(cls) -> bool:
        """检查 FFmpeg"""
        try:
            import subprocess
            result = subprocess.run(
                ["ffmpeg", "-version"],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            return result.returncode == 0
        except:
            return False
    
    @classmethod
    def check_gpu(cls) -> Dict[str, Any]:
        """检查 GPU"""
        gpu_info = {"available": False, "type": None, "name": None}
        
        try:
            import torch
            if torch.cuda.is_available():
                gpu_info["available"] = True
                gpu_info["type"] = "NVIDIA CUDA"
                gpu_info["name"] = torch.cuda.get_device_name(0)
            elif hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
                gpu_info["available"] = True
                gpu_info["type"] = "Apple Metal"
                gpu_info["name"] = "Apple GPU"
        except:
            pass
        
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
        self._config = AppConfig()
        self._qt_app = None
        self._main_window = None
        self._login_window = None
        self._event_bus = None
        self._master_clock = None
        self._data_bus = None
        self._skill_engine = None
        self._auth_service = None
    
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
        
        from modules.lego import EventBus, MasterClock, DataBus, SkillEngine, auth_service
        
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
    
    def _init_blocks(self):
        """初始化积木系统"""
        print("\n🧱 初始化积木系统...")
        
        from modules.lego import BUILTIN_BLOCKS
        
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
        
        from modules.lego import register_account_skills
        
        register_account_skills()
        print("✅ Skill 系统初始化完成")
    
    def _init_qt(self):
        """初始化 Qt 应用"""
        print("\n🖥️ 初始化 Qt6 应用...")
        
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtGui import QFont
        from PyQt6.QtCore import Qt
        
        self._qt_app = QApplication(sys.argv)
        self._qt_app.setStyle("Fusion")
        
        font = QFont("Microsoft YaHei", 10)
        self._qt_app.setFont(font)
        
        self._qt_app.setStyleSheet("""
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
        """初始化功能模块"""
        print("\n🧩 初始化功能模块...")
        
        from modules.lego import MainWindow
        from modules.lego import (
            HomeModule, EditorModule, CopywritingModule,
            TasksModule, DramaFinderModule, AccountOpsModule,
            MaterialsModule, PluginsModule, PerformanceModule,
            ModelManagementModule, SettingsModule, HelpModule
        )
        
        self._main_window = MainWindow()
        
        modules = [
            ("home", "首页", "🏠", HomeModule),
            ("editor", "剪辑", "🎬", EditorModule),
            ("copywriting", "文案生成", "✍️", CopywritingModule),
            ("tasks", "多任务", "📋", TasksModule),
            ("drama", "短剧筛选", "🎭", DramaFinderModule),
            ("account", "账号运营", "👤", AccountOpsModule),
            ("materials", "素材库", "📁", MaterialsModule),
            ("plugins", "插件中心", "🧩", PluginsModule),
            ("performance", "性能监控", "📊", PerformanceModule),
            ("models", "模型管理", "🤖", ModelManagementModule),
            ("settings", "设置", "⚙️", SettingsModule),
            ("help", "帮助", "❓", HelpModule),
        ]
        
        for module_id, name, icon, module_class in modules:
            try:
                self._main_window.set_module_widget(module_id, module_class())
                print(f"  ✅ {icon} {name}")
            except Exception as e:
                print(f"  ❌ {icon} {name} 加载失败: {e}")
                logger.error(f"模块 {name} 加载失败: {e}")
        
        print(f"✅ 已初始化 {len(modules)} 个功能模块")
    
    def _setup_event_handlers(self):
        """设置事件处理器"""
        from modules.lego import EventType
        
        def on_video_loaded(event):
            video_path = event.data.get("path", "")
            logger.info(f"视频已加载: {video_path}")
            self._data_bus.set("current_video", video_path)
        
        def on_task_started(event):
            task_name = event.data.get("task", "")
            logger.info(f"任务开始: {task_name}")
        
        def on_task_completed(event):
            logger.info("任务完成")
        
        def on_error(event):
            error_msg = event.data.get("error", "未知错误")
            logger.error(f"错误: {error_msg}")
        
        self._event_bus.on(EventType.VIDEO_LOADED, on_video_loaded)
        self._event_bus.on(EventType.TASK_STARTED, on_task_started)
        self._event_bus.on(EventType.TASK_COMPLETED, on_task_completed)
        self._event_bus.on(EventType.ERROR_OCCURRED, on_error)
    
    def _show_login(self) -> bool:
        """显示登录界面"""
        from modules.lego import LoginWindow
        
        self._login_window = LoginWindow()
        
        if self._login_window.try_auto_login():
            print("✅ 自动登录成功")
            return True
        
        login_success = [False]
        login_done = [False]
        
        def on_login_success():
            login_success[0] = True
            self._login_window.close()
        
        def on_rejected():
            login_done[0] = True
        
        self._login_window.login_success.connect(on_login_success)
        self._login_window.rejected.connect(on_rejected)
        self._login_window.finished.connect(lambda: login_done.__setitem__(0, True))
        self._login_window.show()
        
        while not login_done[0]:
            self._qt_app.processEvents()
        
        return login_success[0]
    
    def run(self) -> int:
        """运行应用"""
        print("\n" + "=" * 60)
        print("🎬 AI短剧编辑器 v3.0 - Qt6版")
        print("   乐高积木式插件系统 + Skill 执行引擎")
        print("=" * 60)
        
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
            
            print("\n🚀 启动主窗口...")
            self._main_window.show()
            
            if self._auth_service.is_logged_in:
                user = self._auth_service.current_user
                if user:
                    print(f"\n👋 欢迎回来, {user.nickname}!")
            else:
                print("\nℹ️ 未登录 - 请点击右上角登录/激活按钮")
            
            print("\n" + "=" * 60)
            print("✅ 启动完成!")
            print("   - 左侧导航栏: 点击切换模块")
            print("   - 标签页: 同一模块内功能切换")
            print("   - 右上角: 登录/激活按钮")
            print("   - 状态栏: 显示执行状态和时间码")
            print("=" * 60 + "\n")
            
            logger.info("应用启动成功")
            return self._qt_app.exec()
            
        except Exception as e:
            logger.error(f"应用启动失败: {e}")
            traceback.print_exc()
            return 1


def main():
    """主入口"""
    try:
        app = Application()
        return app.run()
    except Exception as e:
        print(f"\n❌ 应用启动失败: {e}")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
