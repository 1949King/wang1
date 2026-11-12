"""
AI短剧编辑器 - Qt6 主程序入口
============================
专业级架构：乐高积木式插件系统 + Skill 执行引擎

功能模块结构：
├── 首页模块 (HomeModule) - 快速入口、统计、最近项目
├── 剪辑模块 (EditorModule) - 轨道、预览、滤镜、字幕
├── 文案生成模块 (CopywritingModule) - AI文案、标题、脚本
├── 多任务模块 (TasksModule) - 批量处理、任务队列
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

# V4.43.6 — QtWebEngine（内置 Chromium）在本机起不来会导致「画布白屏」：
# 症状 = 进画布只有壳 + 日志 `canvas page loadFinished FAIL`
#        （前端提示「画布页面加载完成（遭遇 断网）」）。
# 定案 2026-10-06（已证伪：非代理 / 非 GPU / 非 _SPAHandler / 非 dist 内容），
# 2026-10-11 真机再次复现；对照实验（加载 data: URL）：
#     不加 flags → loadFinished ok=False；加 --no-sandbox → ok=True。
# 注意：必须在**任何** PyQt6.QtWebEngine* 导入之前设置，故置于模块顶层。
_webengine_flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
if "--no-sandbox" not in _webengine_flags:
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
        f"{_webengine_flags} --no-sandbox".strip()
    )
del _webengine_flags

def _probe_webengine() -> bool:
    """子进程预检 QtWebEngine 能否真正加载页面（2026-10-25）。

    本机踩坑：PyQt6/Qt 6.10.2 与 PyQt6-WebEngine 6.10.0 混装 ⇒ 渲染进程
    fail-fast（0xC0000409），连 data: URL 都崩，无法 try/except。
    只能子进程试；失败则置 SHIGUANG_NO_WEBENGINE=1，画布改走系统浏览器。

    成功结果按「PyQt6 + WebEngine 版本」缓存到 data/webengine_probe.json，
    避免每次启动多等 2~5s；失败不缓存（装好依赖后下次启动自动重试）。

    🔴 2026-10-25 二次修正：探针**本身**曾因 ``QApplication([])`` 传空 argv 而必崩
    （Chromium：base::CommandLine cannot be properly initialized ⇒ 0xC0000409），
    结论恒为「不可用」⇒ 应用内画布被永久禁用。已修在 probe_webengine.py。
    这里补三件事：① 探针 stderr 落 data/startup.log（失败原因可见）；
    ② ``SHIGUANG_FORCE_WEBENGINE=1`` 强制启用（用户自救，跳过探针）；
    ③ 探针超时/崩溃与「真不可用」在日志里区分开，避免再次误判无据可查。
    """
    if os.environ.get("SHIGUANG_SKIP_WEBENGINE_PROBE") == "1":
        return os.environ.get("SHIGUANG_NO_WEBENGINE") != "1"
    if os.environ.get("SHIGUANG_FORCE_WEBENGINE") == "1":
        _startup_mark("[startup] SHIGUANG_FORCE_WEBENGINE=1 ⇒ 跳过 QtWebEngine 预检，强制启用")
        return True
    try:
        import subprocess
        import sys as _sys

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ver = {"pyqt6": "", "webengine": ""}
        try:
            from importlib.metadata import version as _v

            ver = {"pyqt6": _v("PyQt6"), "webengine": _v("PyQt6-WebEngine")}
        except Exception:  # stability-gate: allow-swallow（读不到版本 ⇒ 不缓存，只多探一次，不影响启动）
            pass
        cache = os.path.join(root, "data", "webengine_probe.json")
        if all(ver.values()):
            try:
                import json as _json

                with open(cache, "r", encoding="utf-8") as f:
                    got = _json.load(f) or {}
                if got.get("key") == ver and got.get("ok") is True:
                    return True
            except Exception:  # stability-gate: allow-swallow（缓存损坏 ⇒ 重新预检，不影响启动）
                pass
        probe = os.path.join(root, "_verify", "probe_webengine.py")
        if not os.path.isfile(probe):
            return True
        try:
            r = subprocess.run([_sys.executable, probe], timeout=30,
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.PIPE)
            detail = (r.stderr or b"").decode("utf-8", "replace").strip()
            rc = r.returncode
        except subprocess.TimeoutExpired:
            _startup_mark("[startup] QtWebEngine 预检超时(>30s) ⇒ 按不可用处理")
            return False
        if rc == 0:
            try:
                import json as _json

                os.makedirs(os.path.dirname(cache), exist_ok=True)
                with open(cache, "w", encoding="utf-8") as f:
                    _json.dump({"key": ver, "ok": True}, f, ensure_ascii=False)
            except Exception:  # stability-gate: allow-swallow（写缓存失败 ⇒ 下次重探，不影响启动）
                pass
            return True
        _startup_mark(
            f"[startup] QtWebEngine 预检失败 rc={rc} :: "
            + (detail[-400:] if detail else "无 stderr（疑似渲染进程 fail-fast）")
        )
        return False
    except Exception as _e:
        _startup_mark(f"[startup] QtWebEngine 预检异常 :: {_e}")
        return False


def _startup_mark(msg: str) -> None:
    """把启动诊断同时写入 data/startup.log（PowerShell 管道缓冲时也能查）。"""
    try:
        _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        _p = os.path.join(_root, "data", "startup.log")
        os.makedirs(os.path.dirname(_p), exist_ok=True)
        with open(_p, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:  # stability-gate: allow-swallow（诊断日志写失败不得影响启动）
        pass


if not _probe_webengine():
    os.environ["SHIGUANG_NO_WEBENGINE"] = "1"
    _startup_mark("[startup] QtWebEngine 不可用 ⇒ AI 画布将用系统浏览器打开")
    print("[startup] QtWebEngine 不可用（版本错配/渲染进程崩溃）⇒ AI 画布将用系统浏览器打开")  # stability-gate: allow-print（启动诊断：预检失败必须让用户看见）
    print("[startup] 若确信 WebEngine 正常，可设 SHIGUANG_FORCE_WEBENGINE=1 跳过预检")  # stability-gate: allow-print（自救开关必须让用户看见）

# ── 2026-11-01 段错误根因修复：**推理栈必须早于 QtWebEngine 导入** ──────────
# 实测（EXIT=139 SIGSEGV，无 traceback）：
#   · 先 Qt 后 diffusers  ⇒ 崩在 `from diffusers import StableDiffusionPipeline` 这一行；
#   · 先 diffusers 后 Qt  ⇒ diffusers 出图 2.1s / diffsynth 出图 4.2s，均正常。
# 原因是 Windows 的 DLL 加载顺序冲突（Chromium 的 ICU/OpenSSL/ffmpeg 与
# torch/transformers 的同名库互斥）；先加载 torch 侧，Chromium 会让路。
# 关闭开关：SHIGUANG_PRELOAD_INFER=0（排查用；关掉后本地出图大概率段错误）。
if os.environ.get("SHIGUANG_PRELOAD_INFER", "1") != "0":
    try:
        import torch  # noqa: F401  先占住 CUDA/OpenMP 侧 DLL
        import diffusers  # noqa: F401  再占 tokenizers/safetensors 侧
        from diffusers import StableDiffusionPipeline  # noqa: F401  这条正是崩溃点，必须在此成功
        import transformers  # noqa: F401
        _startup_mark("[startup] 推理栈预载完成（torch/diffusers/transformers，早于 QtWebEngine）")
    except Exception as _e:  # stability-gate: allow-swallow（预载失败不得阻止应用启动；出图时会如实报错）
        _startup_mark(f"[startup] 推理栈预载失败（本地出图可能段错误）：{type(_e).__name__}: {_e}")

# 2026-10-25 深夜根因修复：QtWebEngineWidgets 必须在 QApplication 之前导入，
# 2026-10-25 深夜根因修复：QtWebEngineWidgets 必须在 QApplication 之前导入，
# 否则 App 里懒加载（QApplication 之后）会让首次导航静默失败：
#   loadFinished ok=False、page_url 为空、HTTP 200 明明可达（实测 data/canvas_load.log）。
# 预检通过（子进程已证可用）才早导入；失败走浏览器兜底，不冒崩溃风险。
if os.environ.get("SHIGUANG_NO_WEBENGINE") != "1":
    try:
        from PyQt6 import QtWebEngineWidgets  # noqa: F401  必须早于 QApplication
    except Exception:  # stability-gate: allow-swallow（导入失败 ⇒ 走浏览器兜底）
        pass
import sys
import json
import time
import importlib.util
import traceback
import logging
from pathlib import Path
from typing import Any

# §13.3 波次1-1（N5）启动打点基准：入口模块顶层 import 就绪时刻。
# run() 内各阶段耗时以此为起点，日志前缀统一「startup timing:」，供启动链前后对比。
_T_BOOT = time.perf_counter()

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
        # logger 在下方 :59 才初始化，此处用 lastResort 保障可见
        logging.getLogger(__name__).warning("[main_qt6] Windows API 初始化警告: %s", e)

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
    """依赖检查器

    ⚠️ 陷阱备忘（2026-09-25 实测，勿踩）：
    **不要在 PyQt6 已加载之后，在本进程内 `import mediapipe`** ——
    实测必然失败：`ImportError: DLL load failed while importing _framework_bindings:
    动态链接库(DLL)初始化例程失败`。顺序敏感，反过来（mediapipe 先、PyQt6 后）则正常；
    与 cv2 / torch / easyocr / transformers 的任意组合也正常。
    ⇒ 这是「PyQt6 与 mediapipe 的 DLL 加载顺序冲突」。

    当前架构**没有踩到这个坑**：姿态解析走独立子进程
    （`app/core/ai/pose_extract_service.py` 用 `subprocess` 跑 `pose_worker.py`），
    子进程不加载 PyQt6，故正常。
    但本类的 ``check_dependencies`` 历史实现在**本进程内**真导入了 mediapipe，
    于是把它误报成「未安装」（装了的！）—— 这也是改用 ``find_spec`` 的附带收益：
    它只定位不执行，顺带消掉了这个误诊。
    若将来要把媒体的姿态推理搬进主进程，**必须先解决此 DLL 冲突**。
    """
    
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
        # 离线注音字典（2026-09-25）：缺失时 agent 注音能力诚实降级不报错
        "pypinyin": "pypinyin",
        # 本地推理栈（2026-10-28 补）：这三个缺了图像/视频生成整条链路直接不可用，
        # 但**不该阻塞启动**（无 GPU 的机器仍能剪辑/配音）。
        # 此前这张表里没有它们 ⇒ 新机装完「依赖检查全绿」，出图却静默不可用。
        "diffusers": "diffusers",
        "accelerate": "accelerate",
        "safetensors": "safetensors",
        "diffsynth-engine": "diffsynth_engine",
        "torchao": "torchao",
    }
    
    # 严格模式：置 1 时退化为「真导入」探测（排查环境问题时才用）
    STRICT_ENV = "SHIGUANG_STRICT_DEPS"

    @classmethod
    def _probe_installed(cls, import_name: str) -> bool:
        """探测某个包是否**已安装**。

        ⚠️ 默认用 ``importlib.util.find_spec`` —— 它只**定位**模块，不执行模块代码。
        历史实现是 ``__import__(import_name)``，那会把整个 AI 栈真的导一遍：
        实测 torch 11.2s · transformers 33.7s · mediapipe 4.3s（冷启动时更久），
        而调用方 ``_check_environment`` **只用到其中一项**（PyQt6 的存在性）。
        ⇒ 冷启动白等约 50s。2026-09-25 修。

        代价说明：find_spec 判「装了」，不判「装好且能导入」（例如二进制损坏时
        spec 存在但 import 会失败）。这对「依赖是否存在」的语义是够的，且各功能
        都有诚实降级；若需排查这类问题，置 ``SHIGUANG_STRICT_DEPS=1`` 恢复旧行为。
        """
        if os.environ.get(cls.STRICT_ENV) == "1":
            try:
                __import__(import_name)
                return True
            except Exception as e:
                logger.debug("依赖(%s)严格模式导入失败: %s", import_name, e)
                return False
        try:
            return importlib.util.find_spec(import_name) is not None
        except (ImportError, ValueError, AttributeError) as e:
            logger.debug("依赖(%s)定位失败: %s", import_name, e)
            return False

    @classmethod
    def check_dependencies(cls) -> dict[str, dict[str, bool]]:
        """检查依赖（只定位、不导入，见 ``_probe_installed``）。"""
        results: dict[str, dict[str, bool]] = {"required": {}, "optional": {}}

        for package, import_name in cls.REQUIRED_PACKAGES.items():
            results["required"][package] = cls._probe_installed(import_name)

        for package, import_name in cls.OPTIONAL_PACKAGES.items():
            results["optional"][package] = cls._probe_installed(import_name)

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
        """检查 GPU。

        优化（2026-09-25）：**先走 pynvml 轻量路径**（实测 0.47s），
        只有 pynvml 不可用时才退回 ``import torch``（实测 11.2s，冷启动更久）。
        探测目的只是「有没有 GPU、叫什么名字」，不需要把整个 torch 拉起来
        —— 后者会让冷启动白等十几秒。

        行为保持：命中 NVIDIA 时仍返回 type="NVIDIA CUDA" 与真实设备名，
        与 torch 路径一致。
        """
        gpu_info: dict[str, bool | str | None] = {"available": False, "type": None, "name": None}

        # ① 轻量路径：pynvml（快约 20 倍）
        try:
            import pynvml
            pynvml.nvmlInit()
            try:
                if pynvml.nvmlDeviceGetCount() > 0:
                    gpu_info["available"] = True
                    gpu_info["type"] = "NVIDIA CUDA"
                    handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                    raw_name = pynvml.nvmlDeviceGetName(handle)
                    if isinstance(raw_name, bytes):
                        raw_name = raw_name.decode("utf-8", "replace")
                    gpu_info["name"] = str(raw_name)
                    return gpu_info
            finally:
                try:
                    pynvml.nvmlShutdown()
                except Exception as e:
                    logger.debug("nvmlShutdown 失败，忽略: %s", e)
        except Exception as e:
            logger.debug("pynvml 探测不可用，回退 torch 路径: %s", e)

        # ② 回退路径：torch（慢，但能覆盖 Apple Metal / ROCm 等 pynvml 不管的场景）
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
        logger.info("=" * 50)
        logger.info("依赖检查报告")
        logger.info("=" * 50)

        deps = cls.check_dependencies()

        logger.info("必需依赖:")
        for package, installed in deps["required"].items():
            status = "✅" if installed else "❌"
            logger.info(f"  {status} {package}")

        logger.info("可选依赖:")
        for package, installed in deps["optional"].items():
            status = "✅" if installed else "⚠️"
            logger.info(f"  {status} {package}")

        logger.info(f"FFmpeg: {'✅ 已安装' if cls.check_ffmpeg() else '❌ 未安装'}")

        gpu = cls.check_gpu()
        if gpu["available"]:
            logger.info(f"GPU: ✅ {gpu['type']} - {gpu['name']}")
        else:
            logger.warning("GPU: ⚠️ 未检测到GPU加速")

        logger.info("=" * 50)


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
        self._instance_server: 'object | None' = None
    
    def _check_environment(self) -> bool:
        """检查运行环境"""
        logger.info("🔍 检查运行环境...")

        deps = DependencyChecker.check_dependencies()

        pyqt6_installed = deps["required"].get("PyQt6", False)
        if not pyqt6_installed:
            logger.error("❌ 缺少必需依赖: PyQt6")
            logger.error("请运行: pip install PyQt6")
            return False

        if not DependencyChecker.check_ffmpeg():
            logger.warning("⚠️ FFmpeg 未安装，部分功能可能受限")

        gpu = DependencyChecker.check_gpu()
        if gpu["available"]:
            logger.info(f"✅ GPU 加速: {gpu['type']} - {gpu['name']}")
        else:
            logger.warning("⚠️ 未检测到 GPU，将使用 CPU 运行")

        return True

    def _init_paths(self):
        """初始化路径"""
        logger.info("📁 初始化路径...")

        paths = self._config.paths
        for name, path in paths.items():
            Path(path).mkdir(parents=True, exist_ok=True)
            logger.info(f"  ✅ {name}: {path}")

    def _init_core(self):
        """初始化核心组件"""
        logger.info("🔧 初始化核心组件...")

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

        logger.info("  ✅ EventBus - 事件总线")
        logger.info("  ✅ MasterClock - 全局时钟")
        logger.info("  ✅ DataBus - 数据总线")
        logger.info("  ✅ SkillEngine - Skill执行引擎")
        logger.info("  ✅ AuthService - 认证服务")

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
        logger.info("🧱 初始化积木系统...")

        from .modules.lego import BUILTIN_BLOCKS

        for block_class in BUILTIN_BLOCKS:
            try:
                temp_instance = block_class()
                meta = temp_instance.info()
                logger.info(f"  ✅ {meta.icon} {meta.name} v{meta.version}")
            except Exception as e:
                logger.error(f"  ❌ 积木加载失败: {e}")

        logger.info(f"✅ 已加载 {len(BUILTIN_BLOCKS)} 个内置积木")

    def _init_skills(self):
        """初始化 Skill 系统"""
        logger.info("🎯 初始化 Skill 系统...")

        from .modules.lego import register_skills

        register_skills()
        logger.info("✅ Skill 系统初始化完成")

    def _init_qt(self):
        """初始化 Qt 应用"""
        logger.info("🖥️ 初始化 Qt6 应用...")

        # QtWebEngine 必须在 QApplication 之前导入，否则懒加载模块里会 ImportError，
        # 镶嵌页误报「未安装 PyQt6-WebEngine」。
        try:
            from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
            from PyQt6.QtWebEngineCore import QWebEngineScript  # noqa: F401
            logger.info("  ✅ QtWebEngine 预加载")
        except Exception as e:
            logger.warning(f"  ⚠️ QtWebEngine 不可用（AI 画布将外开浏览器）: {e}")

        from PyQt6.QtWidgets import QApplication  # type: ignore[reportMissingImports]
        from PyQt6.QtGui import QFont  # type: ignore[reportMissingImports]
        
        # 🔴 argv 必须非空（2026-10-25）：Qt 6.11 的 QtWebEngine 依赖 base::CommandLine，
        # 空 argv 会让 Chromium 渲染进程 fail-fast（0xC0000409），整块画布黑屏。
        # 打包/被别的进程以无参方式拉起时 sys.argv 可能为空，这里兜底一个程序名。
        _qargv = [a for a in (sys.argv or []) if isinstance(a, str)] or ["shiguang"]
        self._qt_app = QApplication(_qargv)
        # 2026-11-12：WebEngine 默认右键菜单是英文（Back/Forward/Save image…）。
        # 用应用级事件过滤器换成中文；不改冻结区里的画布模块。
        try:
            from .core.web_context_menu import install_chinese_context_menu

            install_chinese_context_menu(self._qt_app)
        except Exception as _cm:  # stability-gate: allow-swallow（菜单失败不得影响启动）
            logger.debug("中文右键菜单安装失败: %s", _cm)
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
        
        logger.info("  ✅ Qt6 应用初始化完成")

    def _init_modules(self):
        """初始化功能模块 — 通过注册表按需加载（仅加载用户启用的模块）"""
        logger.info("🧩 初始化功能模块（按注册表开关）...")

        from .modules.lego import MainWindow  # type: ignore[import-untyped]
        from .modules.lego.module_registry import get_registry

        mw = MainWindow()
        self._main_window = mw

        # ★ 进入软件的首个提示（免责/风险告知）：本软件用机器指纹派生密钥加密配置、做设备绑定，
        #   指纹变化（换硬件/重装系统/系统查询接口变化等）会导致旧密文解不开、设备绑定失效。
        #   首次启动（或提示文本升版）弹一次讲清楚，并声明责任边界
        #   （由此产生的数据损失与作者本人及本项目无关）。
        #   放在 MainWindow 之后弹出 ⇒ 以主窗口为父窗口、居中显示；异常绝不阻断启动。
        try:
            from .modules.lego.notice_dialog import show_first_run_notice

            show_first_run_notice(mw)
        except Exception as _e:  # pragma: no cover - 兜底，绝不影响启动
            logger.warning("首启提示未能显示（不影响使用）: %s", _e)

        # V4.43.14：按设置开关恢复上次会话（模块 / 项目）—— 用户裁定「默认开启」。
        # 延迟 1.6s：等主窗口完成首帧布局再切模块，避免抢在渲染之前。
        try:
            from PyQt6.QtCore import QTimer as _QTimer

            _QTimer.singleShot(1600, mw._restore_last_session)
        except Exception as _e:  # pragma: no cover - 兜底，绝不影响启动
            logger.debug("会话恢复挂载失败（忽略）: %s", _e)

        # MainWindow.__init__() 已调用 _setup_default_modules()
        # 该方法从注册表读取启用状态，只注册已启用的模块导航按钮
        # 模块 widget 采用懒加载：首次点击时才实例化（大幅降低启动内存）

        registry = get_registry()
        enabled = registry.enabled_modules()
        logger.info(f"✅ 注册表：{len(registry.all_modules())} 个定义，"
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

        def on_canvas_tauri_closed(_event: object) -> None:
            """Tauri 桌面画布主窗口已关闭：刷新角色管理模块状态条并记录日志。

            实际进程清理已在 canvas_bridge → /host/tauri-closing 中调用
            canvas_runtime.mark_tauri_closed() 完成，此处仅做 UI 反馈。
            """
            try:
                logger.info("Tauri 画布窗口已关闭，UI 状态已刷新")
            except Exception:
                logger.debug("忽略异常（原为 pass）: main_qt6.py", exc_info=True)

        eb.on(EventType.VIDEO_LOADED, on_video_loaded)  # type: ignore[reportAttributeAccessIssue]
        eb.on(EventType.TASK_STARTED, on_task_started)  # type: ignore[reportAttributeAccessIssue]
        eb.on(EventType.TASK_COMPLETED, on_task_completed)  # type: ignore[reportAttributeAccessIssue]
        eb.on(EventType.ERROR_OCCURRED, on_error)  # type: ignore[reportAttributeAccessIssue]
        if hasattr(EventType, "CANVAS_TAURI_CLOSED"):
            eb.on(EventType.CANVAS_TAURI_CLOSED, on_canvas_tauri_closed)  # type: ignore[reportAttributeAccessIssue]
    
    def _show_login(self) -> bool:
        """显示登录界面"""
        from .modules.lego import LoginWindow  # type: ignore[reportAttributeAccessIssue]
        
        login_win = LoginWindow()
        self._login_window = login_win
        
        if login_win.try_auto_login():
            logger.info("✅ 自动登录成功")
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
            print(msg)  # stability-gate: allow-print（有意：GBK 控制台兜底工具的实现本体）
        except UnicodeEncodeError:
            # 回退：用 ASCII 安全字符替换
            safe = msg.encode('gbk', errors='replace').decode('gbk', errors='replace')
            print(safe)  # stability-gate: allow-print（有意：同上）

    def _acquire_single_instance(self) -> bool:
        """单实例守卫：若已有实例在跑，通知其激活窗口并让本进程退出。

        防止多会话遗留的 GUI 进程叠加、互抢画布端口（3011/18765）导致白屏。
        返回 True 表示本进程成为主实例继续启动；False 表示应直接退出。
        """
        try:
            from PyQt6.QtNetwork import QLocalServer, QLocalSocket
        except Exception as e:
            logger.debug("QLocalServer 不可用，跳过单实例守卫: %s", e)
            return True

        key = "shiguang-editor-single-instance"
        probe = QLocalSocket()
        probe.connectToServer(key)
        if probe.waitForConnected(300):
            try:
                probe.write(b"activate")
                probe.flush()
                probe.waitForBytesWritten(300)
                probe.disconnectFromServer()
            except Exception:
                logger.debug("忽略异常（原为 pass）: main_qt6.py", exc_info=True)
            logger.info("检测到已运行的编辑器实例，已请求其激活窗口，本实例退出")
            return False

        self._instance_server = QLocalServer()
        try:
            QLocalServer.removeServer(key)  # 清理崩溃残留的陈旧命名管道
        except Exception:
            logger.debug("忽略异常（原为 pass）: main_qt6.py", exc_info=True)
        if self._instance_server.listen(key):
            self._instance_server.newConnection.connect(self._on_instance_activated)
            logger.debug("单实例守卫已就位（成为主实例）")
        # listen 失败也不阻塞启动（降级为允许多实例，不因锁而打不开应用）
        return True

    def _on_instance_activated(self) -> None:
        """收到第二个实例的 activate 请求 → 激活本实例主窗口。"""
        try:
            server = self._instance_server
            if server is not None:
                conn = server.nextPendingConnection()
                if conn is not None:
                    conn.disconnectFromServer()
        except Exception:
            logger.debug("忽略异常（原为 pass）: main_qt6.py", exc_info=True)
        try:
            mw = self._main_window
            if mw is not None:
                mw.show()  # type: ignore[reportAttributeAccessIssue]
                mw.raise_()  # type: ignore[reportAttributeAccessIssue]
                mw.activateWindow()  # type: ignore[reportAttributeAccessIssue]
        except Exception as e:
            logger.debug("激活主窗口失败: %s", e)

    def run(self) -> int:
        """运行应用"""
        # §13.3 波次1-1（N5）启动链打点：逐阶段记录耗时（相对上一阶段 + 相对入口就绪），
        # 零行为变化；日志前缀「startup timing:」与 canvas boot timing 风格对齐。
        _t_prev = _T_BOOT

        def _tick(stage: str) -> None:
            nonlocal _t_prev
            _now = time.perf_counter()
            logger.info("startup timing: %s +%.2fs (boot %.2fs)",
                        stage, _now - _t_prev, _now - _T_BOOT)
            _t_prev = _now

        self._safe_print("\n" + "=" * 60)
        self._safe_print(f"AI短剧编辑器 v{__version__} - Qt6版")
        self._safe_print("   乐高积木式插件系统 + Skill 执行引擎")
        self._safe_print("=" * 60)
        
        if not self._check_environment():
            return 1
        _tick("env check")
        
        try:
            self._init_paths()
            _tick("paths")
            self._init_core()
            _tick("core (lego import)")
            self._init_blocks()
            _tick("blocks")
            self._init_skills()
            _tick("skills")
            self._init_qt()
            _tick("qt app")
            if not self._acquire_single_instance():
                return 0
            _tick("single instance")
            self._init_modules()
            _tick("modules (MainWindow)")
            self._setup_event_handlers()
            _tick("event handlers")
            
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
            _tick("window shown")

            if os.environ.get("SHIGUANG_AUTO_CANVAS") == "1":
                # 诊断开关（2026-10-25）：启动后自动打开 AI 画布，便于抓画布加载现场
                try:
                    from PyQt6.QtCore import QTimer

                    _m = getattr(mw, "_modules", {}).get("characters")
                    if _m is not None:
                        # 懒加载模块的 instance 此时为空，_activate_module 会静默无效；
                        # switch_to_module 才会走 _on_module_selected → 真正加载。
                        QTimer.singleShot(
                            int(os.environ.get("SHIGUANG_AUTO_CANVAS_DELAY", "2500")),
                            lambda: mw.switch_to_module("characters"),
                        )
                        print("[diag] SHIGUANG_AUTO_CANVAS ⇒ 自动打开 AI 画布")  # stability-gate: allow-print（诊断开关）
                except Exception:  # stability-gate: allow-swallow（诊断开关不得影响启动）
                    pass
            # 启动后环境自检（延迟执行，避免阻塞启动；仅在缺失关键依赖时提示）
            self._schedule_startup_check(mw)

            auth = self._auth_service
            if auth is not None and auth.is_logged_in:  # type: ignore[reportAttributeAccessIssue]
                user = auth.current_user  # type: ignore[reportAttributeAccessIssue]
                if user:
                    self._safe_print(f"\n欢迎回来, {user.nickname}!")  # type: ignore[reportAttributeAccessIssue]
            else:
                self._safe_print("\n未登录 - 请点击右上角 👤 头像按钮登录（V4.42.0 起顶 navbar 改 4 按钮）")
            
            self._safe_print("\n" + "=" * 60)
            self._safe_print("[OK] 启动完成!")
            self._safe_print("   - 左侧导航栏: 点击切换模块")
            self._safe_print("   - 标签页: 同一模块内功能切换")
            self._safe_print("   - 右上角 5 按钮：🔔 通知 / 🎨 主题 / ⚙ 设置 / 👥 团队 / 👤 用户中心")
            self._safe_print("   - 状态栏: 显示执行状态和时间码")
            self._safe_print("=" * 60 + "\n")
            
            logger.info("应用启动成功")
            return qt_app.exec()  # type: ignore[reportAttributeAccessIssue]
            
        except Exception as e:
            logger.error(f"应用启动失败: {e}")
            traceback.print_exc()
            return 1

    def _schedule_startup_check(self, parent_window) -> None:
        """延迟执行一次启动环境自检（仅缺失关键依赖时提示用户）"""
        try:
            from PyQt6.QtCore import QTimer
            from .modules.lego.settings_module import EnvironmentDiagnosticDialog

            def _run():
                try:
                    EnvironmentDiagnosticDialog.startup_check(parent_window)
                except Exception as e:
                    logger.debug("启动环境自检执行异常（不阻塞启动）: %s", e)

            # 延迟 1.2s，等主窗口完全进入事件循环后再提示
            QTimer.singleShot(1200, _run)
        except Exception as e:
            logger.debug("启动环境自检初始化异常（不阻塞启动）: %s", e)


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
            print(f"\n应用启动失败: {e}")  # stability-gate: allow-print（有意：logger 也可能未就绪时的最后可见输出）
        except UnicodeEncodeError:
            print(f"\n[ERROR] 应用启动失败: {e}")  # stability-gate: allow-print（有意：同上）
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
