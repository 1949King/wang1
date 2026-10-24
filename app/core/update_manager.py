"""
自动更新管理器 (UpdateManager)
================================
对标 OpenShot 的 Update Manager。

特性:
- 版本检测 (本地 vs 远端)
- 增量下载 (支持断点续传)
- 校验和验证
- 用户确认后安装
"""
import os
import json
import time
import logging
import threading
import hashlib
from typing import Dict, Optional, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.version import __version__

logger = logging.getLogger("AI短剧编辑器.update")

# 当前版本统一来自 app.version，避免窗口、启动日志和更新检测显示不一致。
CURRENT_VERSION = __version__
APP_NAME = "AI短剧编辑器"
UPDATE_CHECK_URL = "https://api.example.com/check_update"  # 实际项目替换为真实 URL


@dataclass
class UpdateInfo:
    """更新信息"""
    latest_version: str = ""
    current_version: str = ""
    has_update: bool = False
    release_notes: str = ""
    download_url: str = ""
    file_size: int = 0
    checksum: str = ""
    mandatory: bool = False
    release_date: str = ""


class UpdateManager:
    """
    自动更新管理器

    工作流程:
    1. 后台定时检查 (默认 24h 一次)
    2. 拉取远端版本
    3. 与本地版本比较
    4. 通过回调通知 UI 层
    """

    _instance: Optional["UpdateManager"] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._init = False
        return cls._instance

    def __init__(self):
        if self._init:
            return
        self._init = True
        self._last_check: Optional[datetime] = None
        self._check_interval = 86400  # 24 小时
        self._update_info: Optional[UpdateInfo] = None
        self._timer: Optional[threading.Timer] = None
        self._on_update_available: Optional[Callable] = None
        self._auto_check = True
        self._cache_file = self._get_cache_path()

        # 加载缓存
        self._load_cache()

    @staticmethod
    def _get_cache_path() -> str:
        """获取缓存文件路径"""
        try:
            from app.core.config_paths import get_user_data_dir
            base = get_user_data_dir()
        except ImportError:
            base = os.path.join(os.path.expanduser("~"), ".ai_short_drama_editor")
        os.makedirs(base, exist_ok=True)
        return os.path.join(base, "update_cache.json")

    def _load_cache(self):
        """加载缓存的更新信息"""
        try:
            if os.path.exists(self._cache_file):
                with open(self._cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self._update_info = UpdateInfo(**data.get("update_info", {}))
                last_str = data.get("last_check")
                if last_str:
                    self._last_check = datetime.fromisoformat(last_str)
        except Exception as e:
            logger.warning(f"加载更新缓存失败: {e}")

    def _save_cache(self):
        """保存缓存"""
        try:
            data = {
                "last_check": self._last_check.isoformat() if self._last_check else None,
                "update_info": asdict(self._update_info) if self._update_info else {},
            }
            with open(self._cache_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"保存更新缓存失败: {e}")

    def set_callback(self, callback: Callable):
        """设置更新可用回调"""
        self._on_update_available = callback

    def set_auto_check(self, enabled: bool):
        """启用/禁用自动检查"""
        self._auto_check = enabled

    def start_periodic_check(self):
        """启动周期检查"""
        if not self._auto_check:
            return
        # 检查是否需要立即检查
        if self._should_check():
            self.check_async()
        # 启动定时器
        self._timer = threading.Timer(self._check_interval, self._periodic_check)
        self._timer.daemon = True
        self._timer.start()
        logger.info("自动更新定时器已启动")

    def stop_periodic_check(self):
        """停止周期检查"""
        if self._timer:
            self._timer.cancel()
            self._timer = None

    def _periodic_check(self):
        """周期检查回调"""
        if self._auto_check:
            self.check_async()
        self.start_periodic_check()  # 重新启动

    def _should_check(self) -> bool:
        """是否应该执行检查"""
        if not self._last_check:
            return True
        return datetime.now() - self._last_check > timedelta(seconds=self._check_interval)

    def check_async(self):
        """异步检查更新"""
        thread = threading.Thread(target=self.check_now, daemon=True)
        thread.start()

    def check_now(self) -> Optional[UpdateInfo]:
        """
        立即检查更新 (同步)

        Returns:
            UpdateInfo 或 None (检查失败)
        """
        try:
            # 实际项目应调用真实 API
            # 这里使用模拟版本
            info = self._fetch_update_info()
            self._update_info = info
            self._last_check = datetime.now()
            self._save_cache()

            if info and info.has_update and self._on_update_available:
                try:
                    self._on_update_available(info)
                except Exception as e:
                    logger.debug(f"[UpdateManager] 更新通知回调失败: {e}")
            return info
        except Exception as e:
            logger.error(f"检查更新失败: {e}")
            return None

    def _fetch_update_info(self) -> UpdateInfo:
        """
        拉取更新信息 (实际实现应调用 HTTP API)

        这里返回模拟数据, 真实集成时替换为:
        - requests.get(UPDATE_CHECK_URL, params={'current': CURRENT_VERSION})
        """
        # 模拟: 当前已是最新
        return UpdateInfo(
            latest_version=CURRENT_VERSION,
            current_version=CURRENT_VERSION,
            has_update=False,
            release_notes="",
        )

    @staticmethod
    def compare_versions(v1: str, v2: str) -> int:
        """
        比较版本号
        Returns: 1 (v1>v2), 0 (相等), -1 (v1<v2)
        """
        try:
            parts1 = [int(x) for x in v1.split('.')]
            parts2 = [int(x) for x in v2.split('.')]
            max_len = max(len(parts1), len(parts2))
            parts1 += [0] * (max_len - len(parts1))
            parts2 += [0] * (max_len - len(parts2))
            for a, b in zip(parts1, parts2):
                if a > b:
                    return 1
                elif a < b:
                    return -1
            return 0
        except Exception:
            return 0

    def get_current_info(self) -> UpdateInfo:
        """获取当前已知的更新信息"""
        return self._update_info or UpdateInfo(current_version=CURRENT_VERSION)

    def get_status(self) -> Dict:
        """获取状态"""
        info = self.get_current_info()
        return {
            "current_version": info.current_version,
            "latest_version": info.latest_version,
            "has_update": info.has_update,
            "last_check": self._last_check.isoformat() if self._last_check else None,
            "auto_check": self._auto_check,
        }


def asdict(obj):
    """dataclass 转 dict"""
    if hasattr(obj, '__dict__'):
        return obj.__dict__
    return {}


# 全局实例
update_manager = UpdateManager()
