"""
代理预览渲染器 - 第一阶段核心组件
===================================
实现低分辨率代理预览，解决大素材预览卡顿问题
目标：预览卡顿率降低90%，低配设备流畅运行
"""

import os
import subprocess
import tempfile
import threading
from typing import Dict, Any, Optional, Tuple
from pathlib import Path
import time
from dataclasses import dataclass, field

try:
    from PyQt6.QtCore import QObject, pyqtSignal, QThread, Qt
    from PyQt6.QtGui import QImage, QPixmap, QPainter
    from PyQt6.QtWidgets import QApplication
    PYQT_AVAILABLE = True
except ImportError:
    PYQT_AVAILABLE = False
    print("⚠️ PyQt6未加载，代理预览功能将受限")

from app.modules.utils.logger import logger

@dataclass
class ProxyPreviewConfig:
    """代理预览配置"""
    enabled: bool = True  # 是否启用代理预览
    proxy_width: int = 640  # 代理宽度
    proxy_height: int = 360  # 代理高度
    proxy_quality: str = "medium"  # 代理质量
    auto_generate: bool = True  # 自动生成代理
    cache_proxies: bool = True  # 缓存代理文件

@dataclass
class ProxyInfo:
    """代理文件信息"""
    original_path: str
    proxy_path: str
    width: int
    height: int
    size: int
    created_time: float
    last_accessed: float

class ProxyPreviewRenderer(QObject):
    """代理预览渲染器"""
    
    # 信号
    proxy_generated = pyqtSignal(str)  # 代理生成完成
    proxy_failed = pyqtSignal(str, str)  # 代理生成失败
    
    def __init__(self, config: Optional[ProxyPreviewConfig] = None):
        super().__init__()
        self.config = config or ProxyPreviewConfig()
        self._proxies: Dict[str, ProxyInfo] = {}
        self._generating = set()
        self._lock = threading.Lock()
        self._temp_dir = tempfile.mkdtemp(prefix="proxy_preview_")
        
        logger.info(f"代理预览渲染器初始化: {self.config.proxy_width}x{self.config.proxy_height}")
    
    def generate_proxy(self, video_path: str) -> Optional[str]:
        """生成代理预览文件
        
        Args:
            video_path: 原始视频路径
            
        Returns:
            代理文件路径，失败返回None
        """
        if not self.config.enabled:
            return video_path
        
        # 检查是否已存在代理
        proxy_info = self._proxies.get(video_path)
        if proxy_info and os.path.exists(proxy_info.proxy_path):
            logger.debug(f"使用已缓存代理: {proxy_info.proxy_path}")
            proxy_info.last_accessed = time.time()
            return proxy_info.proxy_path
        
        # 检查是否正在生成
        if video_path in self._generating:
            logger.debug(f"代理正在生成中: {video_path}")
            return None
        
        # 开始生成代理
        self._generating.add(video_path)
        try:
            proxy_path = self._create_proxy_file(video_path)
            
            if proxy_path:
                # 记录代理信息
                file_size = os.path.getsize(proxy_path)
                self._proxies[video_path] = ProxyInfo(
                    original_path=video_path,
                    proxy_path=proxy_path,
                    width=self.config.proxy_width,
                    height=self.config.proxy_height,
                    size=file_size,
                    created_time=time.time(),
                    last_accessed=time.time()
                )
                
                self._generating.discard(video_path)
                self.proxy_generated.emit(video_path)
                logger.info(f"代理生成成功: {video_path} -> {proxy_path}")
                return proxy_path
            
        except Exception as e:
            self._generating.discard(video_path)
            error_msg = f"代理生成失败: {str(e)}"
            logger.error(error_msg)
            self.proxy_failed.emit(video_path, error_msg)
            return None
    
    def _create_proxy_file(self, video_path: str) -> Optional[str]:
        """创建代理文件"""
        try:
            # 生成代理文件路径
            video_name = Path(video_path).stem
            proxy_name = f"{video_name}_proxy_{self.config.proxy_width}x{self.config.proxy_height}.mp4"
            proxy_path = os.path.join(self._temp_dir, proxy_name)
            
            # 使用FFmpeg生成代理
            cmd = [
                'ffmpeg',
                '-i', video_path,
                '-vf', f'scale={self.config.proxy_width}:{self.config.proxy_height}',
                '-c:v', 'libx264',
                '-preset', 'ultrafast',
                '-crf', '28',
                '-y',
                proxy_path
            ]
            
            logger.debug(f"执行FFmpeg命令: {' '.join(cmd)}")
            
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True
            )
            
            stdout, stderr = process.communicate()
            
            if process.returncode != 0:
                logger.error(f"FFmpeg执行失败: {stderr}")
                return None
            
            if os.path.exists(proxy_path):
                return proxy_path
            
            return None
            
        except FileNotFoundError:
            logger.error(f"FFmpeg未找到，请确保已安装")
            return None
        except Exception as e:
            logger.error(f"创建代理文件异常: {str(e)}")
            return None
    
    def get_proxy_path(self, video_path: str) -> Optional[str]:
        """获取代理文件路径"""
        if not self.config.enabled:
            return video_path
        
        proxy_info = self._proxies.get(video_path)
        if proxy_info and os.path.exists(proxy_info.proxy_path):
            return proxy_info.proxy_path
        
        return None
    
    def clear_cache(self, max_age_hours: int = 24):
        """清理过期的代理缓存
        
        Args:
            max_age_hours: 最大缓存时长（小时）
        """
        with self._lock:
            current_time = time.time()
            max_age_seconds = max_age_hours * 3600
            
            expired_proxies = []
            for video_path, proxy_info in list(self._proxies.items()):
                age = current_time - proxy_info.created_time
                if age > max_age_seconds:
                    expired_proxies.append(video_path)
            
            # 删除过期代理
            for video_path in expired_proxies:
                proxy_info = self._proxies[video_path]
                try:
                    if os.path.exists(proxy_info.proxy_path):
                        os.remove(proxy_info.proxy_path)
                        logger.debug(f"删除过期代理: {proxy_info.proxy_path}")
                    del self._proxies[video_path]
                except Exception as e:
                    logger.error(f"删除代理失败: {str(e)}")
            
            if expired_proxies:
                logger.info(f"清理了{len(expired_proxies)}个过期代理文件")
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        total_size = sum(info.size for info in self._proxies.values())
        proxy_count = len(self._proxies)
        
        return {
            'proxy_count': proxy_count,
            'total_size_mb': total_size / (1024 * 1024),
            'config': {
                'enabled': self.config.enabled,
                'proxy_width': self.config.proxy_width,
                'proxy_height': self.config.proxy_height
            }
        }
    
    def shutdown(self):
        """关闭渲染器，清理资源"""
        try:
            # 清理临时目录
            if os.path.exists(self._temp_dir):
                import shutil
                shutil.rmtree(self._temp_dir)
                logger.info("清理代理预览临时目录")
            
            # 清理代理缓存
            self._proxies.clear()
            self._generating.clear()
            
        except Exception as e:
            logger.error(f"关闭代理预览渲染器失败: {str(e)}")

class ProxyPreviewThread(QThread):
    """代理预览生成线程"""
    
    def __init__(self, renderer: ProxyPreviewRenderer, video_path: str):
        super().__init__()
        self.renderer = renderer
        self.video_path = video_path
    
    def run(self):
        """线程运行"""
        self.renderer.generate_proxy(self.video_path)

# 全局代理预览渲染器实例
proxy_preview_renderer = None

def get_proxy_preview_renderer() -> ProxyPreviewRenderer:
    """获取代理预览渲染器实例（单例模式）"""
    global proxy_preview_renderer
    if proxy_preview_renderer is None:
        proxy_preview_renderer = ProxyPreviewRenderer()
    return proxy_preview_renderer