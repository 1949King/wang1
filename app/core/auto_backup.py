"""
自动备份引擎 (AutoBackupManager)
=================================
对标 Shotcut 的 hourly backup + 崩溃恢复机制。

特性:
- 定时后台线程，按间隔自动保存
- 多版本 .bak 文件保留 (默认保留 10 个版本)
- 崩溃恢复：启动时检测未关闭的备份文件
- 缩略图快存
"""
import os
import json
import time
import shutil
import logging
import threading
from typing import Dict, List, Optional, Callable
from datetime import datetime

logger = logging.getLogger("AI短剧编辑器.autobackup")


class AutoBackupManager(QObject if False else object):
    """
    自动备份管理器 (单例)

    使用方式:
        backup_mgr = AutoBackupManager(project_path)
        backup_mgr.start()  # 启动后台定时线程
        # ... 用户编辑 ...
        backup_mgr.stop()   # 退出前停止
    """

    _instance_lock = threading.Lock()
    _instance: Optional["AutoBackupManager"] = None

    def __init__(self, project_path: str = ""):
        self._project_path = ""
        self._backup_dir = ""
        self._interval = 300              # 默认 5 分钟
        self._max_versions = 10
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._last_backup_time = 0.0
        self._pending_data: Optional[dict] = None
        self._on_backup_callback: Optional[Callable] = None

        if project_path:
            self.set_project(project_path)

    # ---- 单例 ----

    @classmethod
    def get_instance(cls) -> "AutoBackupManager":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ---- 配置 ----

    def set_project(self, project_path: str):
        """设置当前项目，自动构建备份目录"""
        self._project_path = project_path
        if project_path:
            project_dir = os.path.dirname(project_path)
            base_name = os.path.splitext(os.path.basename(project_path))[0]
            self._backup_dir = os.path.join(project_dir, f".{base_name}_backups")
            os.makedirs(self._backup_dir, exist_ok=True)

    def set_interval(self, seconds: int):
        """设置备份间隔 (秒)"""
        self._interval = max(30, seconds)

    def set_max_versions(self, count: int):
        """设置最大保留版本数"""
        self._max_versions = max(1, count)

    def set_on_backup(self, callback: Callable):
        """设置备份完成回调"""
        self._on_backup_callback = callback

    def set_pending_data(self, data: dict):
        """设置待备份的项目数据 (由 UI 在数据变更时调用)"""
        with self._lock:
            self._pending_data = data

    # ---- 启动/停止 ----

    def start(self):
        """启动后台定时备份线程"""
        if self._running:
            return
        if not self._backup_dir:
            logger.warning("未设置项目路径，无法启动自动备份")
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info(f"自动备份已启动: 间隔={self._interval}s, 路径={self._backup_dir}")

    def stop(self):
        """停止备份线程"""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        # 停止前执行最后一次备份
        self._do_backup()

    # ---- 备份循环 ----

    def _run_loop(self):
        """后台循环"""
        while self._running:
            time.sleep(min(10, self._interval))
            if not self._running:
                break
            # 检查是否到达备份时间
            if time.time() - self._last_backup_time >= self._interval:
                self._do_backup()

    def _do_backup(self) -> bool:
        """执行一次备份"""
        if not self._backup_dir or not self._project_path:
            return False
        with self._lock:
            data = self._pending_data
        if not data:
            return False
        try:
            # 生成备份文件名: project_20260605_143022.bak.json
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"backup_{ts}.json"
            backup_path = os.path.join(self._backup_dir, backup_name)

            # 写入备份文件
            payload = {
                "version": "1.0",
                "project": self._project_path,
                "timestamp": ts,
                "data": data,
            }
            with open(backup_path, 'w', encoding='utf-8') as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)

            self._last_backup_time = time.time()
            logger.info(f"自动备份成功: {backup_path}")

            # 清理旧版本
            self._cleanup_old_versions()

            if self._on_backup_callback:
                try:
                    self._on_backup_callback(backup_path)
                except Exception:
                    pass
            return True
        except Exception as e:
            logger.error(f"自动备份失败: {e}")
            return False

    def _cleanup_old_versions(self):
        """清理旧版本, 保留最新的 max_versions 个"""
        try:
            files = []
            for f in os.listdir(self._backup_dir):
                if f.startswith("backup_") and f.endswith(".json"):
                    full = os.path.join(self._backup_dir, f)
                    files.append((os.path.getmtime(full), full))
            files.sort(reverse=True)
            # 删除超出数量的旧文件
            for _, path in files[self._max_versions:]:
                try:
                    os.remove(path)
                except OSError:
                    pass
        except Exception as e:
            logger.warning(f"清理旧备份失败: {e}")

    # ---- 崩溃恢复 ----

    @staticmethod
    def check_recovery_files(project_path: str) -> List[Dict[str, str]]:
        """
        检查项目的备份文件, 返回可恢复列表

        Returns:
            [{path, timestamp, size, age}, ...]
        """
        if not project_path:
            return []
        project_dir = os.path.dirname(project_path)
        base_name = os.path.splitext(os.path.basename(project_path))[0]
        backup_dir = os.path.join(project_dir, f".{base_name}_backups")
        if not os.path.isdir(backup_dir):
            return []

        results = []
        try:
            for f in os.listdir(backup_dir):
                if f.startswith("backup_") and f.endswith(".json"):
                    full = os.path.join(backup_dir, f)
                    stat = os.stat(full)
                    results.append({
                        "path": full,
                        "filename": f,
                        "timestamp": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                        "size": stat.st_size,
                        "age_seconds": time.time() - stat.st_mtime,
                    })
        except OSError:
            pass
        results.sort(key=lambda r: r["age_seconds"])
        return results

    @staticmethod
    def load_backup(backup_path: str) -> Optional[Dict]:
        """从备份文件加载数据"""
        try:
            with open(backup_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"加载备份失败: {e}")
            return None

    def get_backup_list(self) -> List[Dict[str, str]]:
        """获取当前项目的所有备份"""
        if not self._backup_dir:
            return []
        return AutoBackupManager.check_recovery_files(self._project_path)

    def get_status(self) -> Dict:
        """获取备份状态"""
        return {
            "running": self._running,
            "project": self._project_path,
            "backup_dir": self._backup_dir,
            "interval": self._interval,
            "max_versions": self._max_versions,
            "last_backup_time": self._last_backup_time,
            "backup_count": len(self.get_backup_list()),
        }


# 全局实例
auto_backup_manager = AutoBackupManager.get_instance()
