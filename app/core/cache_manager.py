"""缓存管理模块"""

import os
import tempfile
import shutil
import time
import threading
from app.modules.utils.logger import logger
from app.modules.utils.cache_system import cache_system

class CacheManager:
    """缓存管理器"""
    
    def __init__(self, max_frame_cache=100, temp_dir=None):
        """初始化缓存管理器
        
        Args:
            max_frame_cache: 最大帧缓存数量
            temp_dir: 临时文件目录
        """
        self.max_frame_cache = max_frame_cache
        self.temp_dir = temp_dir or os.path.join(os.getcwd(), "temp")
        self.frame_cache = {}
        self.video_resources = {}
        self.lock = threading.Lock()
        self._initialize_directories()
        
    def _initialize_directories(self):
        """初始化目录"""
        os.makedirs(self.temp_dir, exist_ok=True)
        logger.info(f"缓存管理器初始化成功，临时目录: {self.temp_dir}")
    
    def cache_frame(self, video_id, frame_index, frame_data):
        """缓存视频帧
        
        Args:
            video_id: 视频ID
            frame_index: 帧索引
            frame_data: 帧数据
        """
        with self.lock:
            # 构建缓存键
            cache_key = f"frame_{video_id}_{frame_index}"
            
            # 检查缓存大小
            if len(self.frame_cache) >= self.max_frame_cache:
                # 移除最旧的帧
                oldest_key = next(iter(self.frame_cache))
                del self.frame_cache[oldest_key]
                logger.debug(f"移除最旧的帧缓存: {oldest_key}")
            
            # 添加新帧到缓存
            self.frame_cache[cache_key] = {
                "data": frame_data,
                "timestamp": time.time()
            }
            logger.debug(f"缓存视频帧: {cache_key}")
    
    def get_cached_frame(self, video_id, frame_index):
        """获取缓存的视频帧
        
        Args:
            video_id: 视频ID
            frame_index: 帧索引
        """
        with self.lock:
            cache_key = f"frame_{video_id}_{frame_index}"
            if cache_key in self.frame_cache:
                # 更新访问时间
                self.frame_cache[cache_key]["timestamp"] = time.time()
                logger.debug(f"获取缓存的视频帧: {cache_key}")
                return self.frame_cache[cache_key]["data"]
            return None
    
    def release_video_resources(self, video_id):
        """释放视频资源
        
        Args:
            video_id: 视频ID
        """
        with self.lock:
            # 移除该视频的所有帧缓存
            keys_to_remove = []
            for key in self.frame_cache:
                if f"frame_{video_id}_" in key:
                    keys_to_remove.append(key)
            
            for key in keys_to_remove:
                del self.frame_cache[key]
                logger.debug(f"释放视频帧缓存: {key}")
            
            # 释放视频资源
            if video_id in self.video_resources:
                resource = self.video_resources[video_id]
                # 这里可以添加具体的资源释放逻辑
                # 例如关闭视频文件句柄等
                del self.video_resources[video_id]
                logger.info(f"释放视频资源: {video_id}")
    
    def register_video_resource(self, video_id, resource):
        """注册视频资源
        
        Args:
            video_id: 视频ID
            resource: 视频资源
        """
        with self.lock:
            self.video_resources[video_id] = resource
            logger.debug(f"注册视频资源: {video_id}")
    
    def create_temp_file(self, suffix=".tmp"):
        """创建临时文件
        
        Args:
            suffix: 文件后缀
        """
        temp_file = tempfile.NamedTemporaryFile(
            dir=self.temp_dir,
            suffix=suffix,
            delete=False
        )
        temp_file_path = temp_file.name
        temp_file.close()
        logger.debug(f"创建临时文件: {temp_file_path}")
        return temp_file_path
    
    def cleanup_temp_files(self, older_than=3600):
        """清理临时文件
        
        Args:
            older_than: 清理多久之前的临时文件（秒）
        """
        current_time = time.time()
        cleaned_count = 0
        
        if not os.path.exists(self.temp_dir):
            return cleaned_count
        
        for root, dirs, files in os.walk(self.temp_dir):
            for file in files:
                file_path = os.path.join(root, file)
                try:
                    file_mtime = os.path.getmtime(file_path)
                    if current_time - file_mtime > older_than:
                        os.remove(file_path)
                        cleaned_count += 1
                        logger.debug(f"清理临时文件: {file_path}")
                except Exception as e:
                    logger.error(f"清理临时文件失败 {file_path}: {e}")
        
        logger.info(f"清理完成，共删除 {cleaned_count} 个临时文件")
        return cleaned_count
    
    def clear_frame_cache(self):
        """清空帧缓存"""
        with self.lock:
            cache_size = len(self.frame_cache)
            self.frame_cache.clear()
            logger.info(f"清空帧缓存，共 {cache_size} 个帧")
    
    def clear_all_resources(self):
        """清空所有资源"""
        with self.lock:
            # 清空帧缓存
            self.clear_frame_cache()
            
            # 释放所有视频资源
            resource_count = len(self.video_resources)
            self.video_resources.clear()
            logger.info(f"释放所有视频资源，共 {resource_count} 个资源")
            
            # 清理临时文件
            self.cleanup_temp_files()
    
    def get_cache_stats(self):
        """获取缓存统计信息"""
        with self.lock:
            return {
                "frame_cache_size": len(self.frame_cache),
                "max_frame_cache": self.max_frame_cache,
                "video_resources_count": len(self.video_resources),
                "temp_dir": self.temp_dir,
                "temp_files_count": sum(len(files) for _, _, files in os.walk(self.temp_dir)) if os.path.exists(self.temp_dir) else 0
            }
    
    def auto_cleanup(self, interval=300):
        """自动清理
        
        Args:
            interval: 清理间隔（秒）
        """
        def cleanup_task():
            while True:
                try:
                    # 清理过期的帧缓存
                    self._cleanup_expired_frames()
                    # 清理临时文件
                    self.cleanup_temp_files()
                except Exception as e:
                    logger.error(f"自动清理失败: {e}")
                time.sleep(interval)
        
        # 启动自动清理线程
        cleanup_thread = threading.Thread(target=cleanup_task, daemon=True)
        cleanup_thread.start()
        logger.info(f"启动自动清理线程，间隔 {interval} 秒")
    
    def _cleanup_expired_frames(self, expire_time=300):
        """清理过期的帧缓存
        
        Args:
            expire_time: 过期时间（秒）
        """
        with self.lock:
            current_time = time.time()
            expired_keys = []
            
            for key, frame_info in self.frame_cache.items():
                if current_time - frame_info["timestamp"] > expire_time:
                    expired_keys.append(key)
            
            for key in expired_keys:
                del self.frame_cache[key]
                logger.debug(f"清理过期帧缓存: {key}")
            
            if expired_keys:
                logger.info(f"清理了 {len(expired_keys)} 个过期帧缓存")

# 全局缓存管理器实例
cache_manager = CacheManager()
