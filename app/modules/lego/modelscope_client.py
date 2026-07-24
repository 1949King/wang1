"""
魔搭社区客户端模块 (ModelScopeClient)
======================================
ModelScope 模型下载与管理，支持从魔搭社区下载开源模型到本地。

┌──────────────────────────────────────────────────────────────┐
│  架构概述：                                                   │
│    单例模式 ModelScopeClient → modelscope SDK                 │
│    ├── 状态检测：is_sdk_available()                           │
│    ├── 模型管理：download_model() / list_local_models()       │
│    └── 配置持久化：data/modelscope_config.json                │
├──────────────────────────────────────────────────────────────┤
│  依赖说明：                                                   │
│    需要安装 modelscope SDK: pip install modelscope            │
│    可选：pip install modelscope[torch] 包含 PyTorch 依赖      │
└──────────────────────────────────────────────────────────────┘
"""

import os
import threading
from typing import Optional, Dict, List, Callable
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class ModelScopeModel:
    """魔搭社区模型信息数据类"""
    name: str
    local_path: str
    size: Optional[int] = None

    @property
    def display_name(self) -> str:
        return self.name.split("/")[-1] if "/" in self.name else self.name


@dataclass
class ModelScopeConfig:
    """魔搭社区配置"""
    download_dir: str = ""

    @property
    def default_download_dir(self) -> str:
        """默认下载目录"""
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        return os.path.join(base_dir, "data", "modelscope_models")


class ModelScopeClient:
    """魔搭社区客户端 - 线程安全单例

    使用 modelscope SDK 的 snapshot_download 下载模型到本地。
    """

    _instance: Optional['ModelScopeClient'] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized: bool = True
        self._config: ModelScopeConfig = self._load_config()
        os.makedirs(self.download_dir, exist_ok=True)

    @property
    def download_dir(self) -> str:
        """模型下载目录"""
        if self._config.download_dir and os.path.isdir(self._config.download_dir):
            return self._config.download_dir
        return self._config.default_download_dir

    def is_sdk_available(self) -> bool:
        """检查 modelscope SDK 是否可用"""
        try:
            import modelscope  # type: ignore
            return True
        except ImportError:
            return False

    def download_model(
        self,
        model_name: str,
        progress_callback: Optional[Callable[[str], None]] = None,
        **kwargs
    ) -> bool:
        """
        下载模型到本地

        参数:
          model_name: 模型名称（如 "qwen/Qwen2-7B-Instruct"）
          progress_callback: 进度回调函数
          kwargs: 额外参数传递给 snapshot_download

        返回:
          True 表示下载成功，False 表示失败
        """
        if not self.is_sdk_available():
            if progress_callback:
                progress_callback("错误: 未安装 modelscope SDK，请运行 pip install modelscope")
            return False

        try:
            from modelscope import snapshot_download  # type: ignore

            def progress_hook(download_progress: Dict[str, Any]) -> None:
                if progress_callback:
                    if download_progress.get("stage") == "download":
                        downloaded = download_progress.get("downloaded", 0)
                        total = download_progress.get("total", 0)
                        if total > 0:
                            percent = int((downloaded / total) * 100)
                            progress_callback(f"正在下载: {percent}% ({downloaded}/{total})")
                        else:
                            progress_callback(f"正在下载: {downloaded}")
                    elif download_progress.get("stage") == "extract":
                        progress_callback("正在解压模型...")

            if progress_callback:
                progress_callback(f"开始下载模型: {model_name}")

            local_path = snapshot_download(
                model_name=model_name,
                cache_dir=self.download_dir,
                progress_callback=progress_hook,
                **kwargs
            )

            if progress_callback:
                progress_callback(f"模型下载完成: {local_path}")

            logger.info(f"魔搭社区模型下载成功: {model_name} -> {local_path}")
            return True

        except Exception as e:
            logger.error(f"魔搭社区模型下载失败: {model_name}, 错误: {e}")
            if progress_callback:
                progress_callback(f"下载失败: {str(e)}")
            return False

    def list_local_models(self) -> List[ModelScopeModel]:
        """列出本地已下载的模型"""
        models: List[ModelScopeModel] = []
        if not os.path.isdir(self.download_dir):
            return models

        for dir_name in os.listdir(self.download_dir):
            dir_path = os.path.join(self.download_dir, dir_name)
            if os.path.isdir(dir_path):
                size = self._get_dir_size(dir_path)
                models.append(ModelScopeModel(name=dir_name, local_path=dir_path, size=size))

        return models

    def _get_dir_size(self, dir_path: str) -> Optional[int]:
        """获取目录大小（字节）"""
        try:
            total_size = 0
            for dirpath, dirnames, filenames in os.walk(dir_path):
                for filename in filenames:
                    filepath = os.path.join(dirpath, filename)
                    if os.path.isfile(filepath):
                        total_size += os.path.getsize(filepath)
            return total_size
        except Exception:
            return None

    def _load_config(self) -> ModelScopeConfig:
        """加载配置"""
        config_path = self._config_path()
        if os.path.exists(config_path):
            try:
                import json
                with open(config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return ModelScopeConfig(download_dir=data.get("download_dir", ""))
            except Exception:
                pass
        return ModelScopeConfig()

    def save_config(self, download_dir: str = "") -> None:
        """保存配置"""
        self._config.download_dir = download_dir
        config_path = self._config_path()
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        try:
            import json
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump({"download_dir": download_dir}, f, indent=2)
        except Exception as e:
            logger.error(f"保存配置失败: {e}")

    def _config_path(self) -> str:
        """配置文件路径"""
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        return os.path.join(base_dir, "data", "modelscope_config.json")


modelscope_client = ModelScopeClient()
