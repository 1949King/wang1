"""
ShortPlayAI Engine V1.0 更新机制
支持自动检查、下载和安装更新
"""

import os
import sys
import json
import hashlib
import requests
import shutil
import threading
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass
from enum import Enum
import tempfile
import zipfile


class UpdateChannel(Enum):
    """更新渠道"""
    STABLE = "stable"       # 稳定版
    BETA = "beta"           # 测试版
    NIGHTLY = "nightly"     # 每日构建版


@dataclass
class UpdateInfo:
    """更新信息"""
    version: str
    release_date: str
    download_url: str
    file_size: int
    checksum: str
    changelog: str
    channel: UpdateChannel
    mandatory: bool = False


class UpdateManager:
    """更新管理器"""
    
    def __init__(self):
        self._config_dir = self._get_config_dir()
        self._config_file = os.path.join(self._config_dir, "update_config.json")
        self._current_version = "1.0.0"
        self._update_server = "https://api.shortplayai.com/updates"
        self._update_channel = UpdateChannel.STABLE
        self._auto_check_enabled = True
        self._check_interval = 86400  # 24小时（秒）
        self._last_check_time = 0
        self._download_callbacks = []
        self._lock = threading.RLock()
        
        self._load_config()
    
    def _get_config_dir(self):
        """获取配置目录"""
        if sys.platform == "win32":
            return os.path.join(os.environ.get("APPDATA", ""), "ShortPlayAI", "updates")
        elif sys.platform == "darwin":
            return os.path.expanduser("~/Library/Application Support/ShortPlayAI/updates")
        else:
            return os.path.expanduser("~/.config/shortplayai/updates")
    
    def _load_config(self):
        """加载配置"""
        try:
            if os.path.exists(self._config_file):
                with open(self._config_file, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    self._update_channel = UpdateChannel(config.get("channel", "stable"))
                    self._auto_check_enabled = config.get("auto_check_enabled", True)
                    self._check_interval = config.get("check_interval", 86400)
                    self._last_check_time = config.get("last_check_time", 0)
        except Exception as e:
            print(f"加载更新配置失败: {e}")
    
    def _save_config(self):
        """保存配置"""
        try:
            os.makedirs(self._config_dir, exist_ok=True)
            config = {
                "channel": self._update_channel.value,
                "auto_check_enabled": self._auto_check_enabled,
                "check_interval": self._check_interval,
                "last_check_time": self._last_check_time
            }
            with open(self._config_file, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"保存更新配置失败: {e}")
    
    def set_current_version(self, version: str):
        """设置当前版本"""
        self._current_version = version
    
    def set_update_channel(self, channel: UpdateChannel):
        """设置更新渠道"""
        self._update_channel = channel
        self._save_config()
    
    def set_auto_check_enabled(self, enabled: bool):
        """设置自动检查"""
        self._auto_check_enabled = enabled
        self._save_config()
    
    def set_check_interval(self, interval: int):
        """设置检查间隔"""
        self._check_interval = interval
        self._save_config()
    
    def check_for_updates(self, force: bool = False) -> Optional[UpdateInfo]:
        """检查更新"""
        with self._lock:
            current_time = int(time.time())
            
            # 检查是否需要检查
            if not force and self._auto_check_enabled:
                if current_time - self._last_check_time < self._check_interval:
                    print("距离上次检查时间不足，跳过更新检查")
                    return None
            
            try:
                print("检查更新...")
                
                # 构建请求参数
                params = {
                    "version": self._current_version,
                    "channel": self._update_channel.value,
                    "platform": sys.platform,
                    "machine": os.uname().machine
                }
                
                # 发送请求到更新服务器
                response = requests.get(
                    f"{self._update_server}/check",
                    params=params,
                    timeout=30
                )
                
                if response.status_code == 200:
                    data = response.json()
                    
                    if data.get("has_update", False):
                        update_info = UpdateInfo(
                            version=data["version"],
                            release_date=data["release_date"],
                            download_url=data["download_url"],
                            file_size=data["file_size"],
                            checksum=data["checksum"],
                            changelog=data["changelog"],
                            channel=self._update_channel,
                            mandatory=data.get("mandatory", False)
                        )
                        
                        self._last_check_time = current_time
                        self._save_config()
                        
                        print(f"发现新版本: {update_info.version}")
                        return update_info
                    else:
                        print("当前已是最新版本")
                        self._last_check_time = current_time
                        self._save_config()
                        return None
                else:
                    print(f"更新检查失败: HTTP {response.status_code}")
                    return None
                    
            except requests.RequestException as e:
                print(f"网络请求失败: {e}")
                return None
            except Exception as e:
                print(f"检查更新时发生错误: {e}")
                return None
    
    def download_update(self, update_info: UpdateInfo, 
                     progress_callback: Optional[Callable[[int, str], None]] = None) -> str:
        """下载更新"""
        print(f"开始下载更新: {update_info.version}")
        
        try:
            # 创建临时目录
            temp_dir = tempfile.mkdtemp(prefix="shortplayai_update_")
            download_path = os.path.join(temp_dir, "update.zip")
            
            # 下载文件
            response = requests.get(update_info.download_url, stream=True)
            total_size = int(response.headers.get('content-length', 0))
            downloaded_size = 0
            
            with open(download_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded_size += len(chunk)
                        
                        # 调用进度回调
                        if progress_callback:
                            progress = int((downloaded_size / total_size) * 100)
                            progress_callback(progress, f"下载中... {progress}%")
            
            print(f"下载完成: {download_path}")
            
            # 验证文件完整性
            if not self._verify_file_checksum(download_path, update_info.checksum):
                print("文件校验失败，删除下载的文件")
                os.remove(download_path)
                return None
            
            return download_path
            
        except Exception as e:
            print(f"下载更新失败: {e}")
            return None
    
    def _verify_file_checksum(self, file_path: str, expected_checksum: str) -> bool:
        """验证文件校验和"""
        try:
            sha256_hash = hashlib.sha256()
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(chunk)
            
            actual_checksum = sha256_hash.hexdigest()
            return actual_checksum.lower() == expected_checksum.lower()
        except Exception as e:
            print(f"校验和验证失败: {e}")
            return False
    
    def install_update(self, update_file: str, 
                   progress_callback: Optional[Callable[[int, str], None]] = None) -> bool:
        """安装更新"""
        print("开始安装更新...")
        
        try:
            # 解压更新文件
            extract_dir = tempfile.mkdtemp(prefix="shortplayai_extract_")
            
            with zipfile.ZipFile(update_file, 'r') as zip_ref:
                total_files = len(zip_ref.namelist())
                extracted_files = 0
                
                for file_info in zip_ref.infolist():
                    zip_ref.extract(file_info, extract_dir)
                    extracted_files += 1
                    
                    if progress_callback:
                        progress = int((extracted_files / total_files) * 100)
                        progress_callback(progress, f"解压中... {progress}%")
            
            print(f"解压完成: {extract_dir}")
            
            # 运行安装脚本
            install_script = os.path.join(extract_dir, "install_update.sh")
            
            if sys.platform == "win32":
                install_script = os.path.join(extract_dir, "install_update.bat")
            
            if os.path.exists(install_script):
                if progress_callback:
                    progress_callback(100, "安装更新...")
                
                # 执行安装脚本
                result = subprocess.run(
                    [install_script],
                    capture_output=True,
                    text=True
                )
                
                if result.returncode == 0:
                    print("更新安装成功")
                    
                    # 清理临时文件
                    self._cleanup_temp_files([update_file, extract_dir])
                    
                    return True
                else:
                    print(f"更新安装失败: {result.stderr}")
                    return False
            else:
                print("未找到安装脚本")
                return False
                
        except Exception as e:
            print(f"安装更新失败: {e}")
            return False
    
    def _cleanup_temp_files(self, file_paths: List[str]):
        """清理临时文件"""
        for path in file_paths:
            try:
                if os.path.isfile(path):
                    os.remove(path)
                elif os.path.isdir(path):
                    shutil.rmtree(path)
                print(f"清理临时文件: {path}")
            except OSError as e:
                # 可预期的文件系统错误（占用/权限/不存在）→ 警告即可
                print(f"清理临时文件失败 {path}: {e}")
            except Exception as e:
                # 非文件系统错误（如 NameError/AttributeError）= 代码缺陷，
                # 不能与「清理失败」混为一谈，否则缺陷会被静默吞掉。
                print(f"[内部错误] 清理临时文件异常 {path}: {type(e).__name__}: {e}")
                raise
    
    def register_download_callback(self, callback: Callable[[UpdateInfo], None]):
        """注册下载回调"""
        self._download_callbacks.append(callback)
    
    def unregister_download_callback(self, callback: Callable[[UpdateInfo], None]):
        """取消注册下载回调"""
        if callback in self._download_callbacks:
            self._download_callbacks.remove(callback)
    
    def get_update_info(self) -> Dict[str, Any]:
        """获取更新信息"""
        return {
            "current_version": self._current_version,
            "update_channel": self._update_channel.value,
            "auto_check_enabled": self._auto_check_enabled,
            "check_interval": self._check_interval,
            "last_check_time": self._last_check_time
        }
    
    def start_auto_update_check(self):
        """启动自动更新检查"""
        if not self._auto_check_enabled:
            print("自动更新检查已禁用")
            return
        
        def check_worker():
            while True:
                update_info = self.check_for_updates()
                if update_info:
                    for callback in self._download_callbacks:
                        callback(update_info)
                
                # 等待下一次检查
                time.sleep(self._check_interval)
        
        thread = threading.Thread(target=check_worker, daemon=True)
        thread.start()
        print("自动更新检查已启动")


class UpdateDialog:
    """更新对话框"""
    
    def __init__(self, update_info: UpdateInfo, parent=None):
        from PyQt6.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
            QPushButton, QTextEdit, QProgressBar, QMessageBox
        )
        from PyQt6.QtCore import Qt
        
        super().__init__(parent)
        self._update_info = update_info
        self._download_path = None
        self._setup_ui()
    
    def _setup_ui(self):
        """设置UI"""
        self.setWindowTitle("发现新版本")
        self.setMinimumWidth(600)
        self.setMinimumHeight(400)
        
        layout = QVBoxLayout(self)
        
        # 版本信息
        version_layout = QHBoxLayout()
        version_label = QLabel(f"新版本: {self._update_info.version}")
        version_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #333;")
        version_layout.addWidget(version_label)
        version_layout.addStretch()
        layout.addLayout(version_layout)
        
        # 发布日期
        date_label = QLabel(f"发布日期: {self._update_info.release_date}")
        date_label.setStyleSheet("color: #666; font-size: 12px;")
        layout.addWidget(date_label)
        
        # 更新日志
        changelog_label = QLabel("更新内容:")
        changelog_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
        layout.addWidget(changelog_label)
        
        changelog_text = QTextEdit()
        changelog_text.setReadOnly(True)
        changelog_text.setPlainText(self._update_info.changelog)
        changelog_text.setMaximumHeight(150)
        layout.addWidget(changelog_text)
        
        # 进度条
        self._progress_bar = QProgressBar()
        self._progress_bar.setVisible(False)
        layout.addWidget(self._progress_bar)
        
        # 状态标签
        self._status_label = QLabel()
        self._status_label.setStyleSheet("color: #666; margin-top: 10px;")
        layout.addWidget(self._status_label)
        
        # 按钮布局
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        if self._update_info.mandatory:
            # 强制更新
            self._update_button = QPushButton("立即更新")
            self._update_button.clicked.connect(self._start_update)
            self._update_button.setStyleSheet("""
                QPushButton {
                    background-color: #f44336;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 10px 20px;
                    font-weight: bold;
                }
            """)
            button_layout.addWidget(self._update_button)
        else:
            # 可选更新
            self._update_button = QPushButton("下载更新")
            self._update_button.clicked.connect(self._start_update)
            self._update_button.setStyleSheet("""
                QPushButton {
                    background-color: #4caf50;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 10px 20px;
                    font-weight: bold;
                }
            """)
            button_layout.addWidget(self._update_button)
            
            self._skip_button = QPushButton("跳过此版本")
            self._skip_button.clicked.connect(self.reject)
            self._skip_button.setStyleSheet("""
                QPushButton {
                    background-color: #9e9e9e;
                    color: #333;
                    border: none;
                    border-radius: 4px;
                    padding: 10px 20px;
                }
            """)
            button_layout.addWidget(self._skip_button)
        
        layout.addLayout(button_layout)
    
    def _start_update(self):
        """开始更新"""
        self._update_button.setEnabled(False)
        self._progress_bar.setVisible(True)
        self._status_label.setText("准备下载...")
        
        # 创建更新管理器
        manager = UpdateManager()
        
        def progress_callback(progress, message):
            self._progress_bar.setValue(progress)
            self._status_label.setText(message)
        
        def download_complete(file_path):
            self._download_path = file_path
            self._update_button.setText("安装更新")
            self._update_button.setEnabled(True)
            self._status_label.setText("下载完成，准备安装...")
        
        # 下载更新
        thread = threading.Thread(
            target=lambda: download_complete(
                manager.download_update(self._update_info, progress_callback)
            )
        )
        thread.start()
    
    def get_install_path(self):
        """获取安装文件路径"""
        return self._download_path


def main():
    """主函数"""
    import time
    
    # 创建更新管理器
    manager = UpdateManager()
    manager.set_current_version("1.0.0")
    
    # 检查更新
    print("检查更新...")
    update_info = manager.check_for_updates(force=True)
    
    if update_info:
        print(f"\n发现新版本: {update_info.version}")
        print(f"发布日期: {update_info.release_date}")
        print(f"文件大小: {update_info.file_size / 1024 / 1024:.2f} MB")
        print(f"下载地址: {update_info.download_url}")
        print(f"\n更新内容:\n{update_info.changelog}")
    else:
        print("当前已是最新版本")


if __name__ == "__main__":
    main()