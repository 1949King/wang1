"""
稳定性优化的视频处理模块
============================
包含异步处理、异常捕获、自动清理等功能
"""

import os
import tempfile
import logging
from typing import Optional, Callable, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from enum import Enum
import traceback

from PyQt6.QtCore import QThread, pyqtSignal, QObject
import numpy as np

logger = logging.getLogger("AI短剧编辑器.video_processor_stable")


class ProcessingStatus(Enum):
    """处理状态"""
    PENDING = "等待中"
    PROCESSING = "处理中"
    COMPLETED = "完成"
    FAILED = "失败"
    CANCELLED = "已取消"


@dataclass
class ProcessingTask:
    """处理任务"""
    task_id: str
    input_path: str
    output_path: str
    params: Dict[str, Any]
    status: ProcessingStatus = ProcessingStatus.PENDING
    progress: float = 0.0
    error_message: str = ""
    callback: Optional[Callable] = None


class VideoProcessingWorker(QThread):
    """视频处理工作线程"""
    
    progress_updated = pyqtSignal(str, float)  # task_id, progress
    task_completed = pyqtSignal(str, bool, str)  # task_id, success, message
    
    def __init__(self, task: ProcessingTask):
        super().__init__()
        self.task = task
        self._is_cancelled = False
        
    def run(self):
        """执行视频处理"""
        try:
            self.task.status = ProcessingStatus.PROCESSING
            logger.info(f"开始处理任务: {self.task.task_id}")
            
            # 模拟处理过程
            for i in range(101):
                if self._is_cancelled:
                    self.task.status = ProcessingStatus.CANCELLED
                    self.task_completed.emit(self.task.task_id, False, "任务已取消")
                    return
                    
                self.task.progress = i
                self.progress_updated.emit(self.task.task_id, i)
                self.msleep(50)  # 模拟处理时间
            
            self.task.status = ProcessingStatus.COMPLETED
            self.task_completed.emit(self.task.task_id, True, "处理完成")
            logger.info(f"任务完成: {self.task.task_id}")
            
        except Exception as e:
            self.task.status = ProcessingStatus.FAILED
            self.task.error_message = str(e)
            error_trace = traceback.format_exc()
            logger.error(f"任务失败 {self.task.task_id}: {e}\n{error_trace}")
            self.task_completed.emit(self.task.task_id, False, str(e))
    
    def cancel(self):
        """取消任务"""
        self._is_cancelled = True
        logger.info(f"取消任务: {self.task.task_id}")


class VideoProcessorManager(QObject):
    """视频处理器管理器"""
    
    task_progress = pyqtSignal(str, float)
    task_finished = pyqtSignal(str, bool, str)
    all_tasks_completed = pyqtSignal()
    
    def __init__(self, max_workers: int = 3):
        super().__init__()
        self.max_workers = max_workers
        self.tasks: Dict[str, ProcessingTask] = {}
        self.workers: Dict[str, VideoProcessingWorker] = {}
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.temp_files: list = []
        
        logger.info(f"视频处理器管理器初始化完成，最大工作线程: {max_workers}")
    
    def add_task(self, task_id: str, input_path: str, output_path: str, 
                 params: Dict[str, Any], callback: Optional[Callable] = None) -> ProcessingTask:
        """添加处理任务"""
        task = ProcessingTask(
            task_id=task_id,
            input_path=input_path,
            output_path=output_path,
            params=params,
            callback=callback
        )
        self.tasks[task_id] = task
        
        # 创建工作线程
        worker = VideoProcessingWorker(task)
        worker.progress_updated.connect(self._on_progress_updated)
        worker.task_completed.connect(self._on_task_completed)
        self.workers[task_id] = worker
        
        logger.info(f"添加任务: {task_id}")
        return task
    
    def start_task(self, task_id: str):
        """启动任务"""
        if task_id in self.workers:
            worker = self.workers[task_id]
            worker.start()
            logger.info(f"启动任务: {task_id}")
    
    def start_all(self):
        """启动所有任务"""
        for task_id in self.workers:
            self.start_task(task_id)
    
    def cancel_task(self, task_id: str):
        """取消任务"""
        if task_id in self.workers:
            self.workers[task_id].cancel()
            logger.info(f"取消任务: {task_id}")
    
    def cancel_all(self):
        """取消所有任务"""
        for worker in self.workers.values():
            worker.cancel()
        logger.info("取消所有任务")
    
    def _on_progress_updated(self, task_id: str, progress: float):
        """进度更新回调"""
        if task_id in self.tasks:
            self.tasks[task_id].progress = progress
            self.task_progress.emit(task_id, progress)
    
    def _on_task_completed(self, task_id: str, success: bool, message: str):
        """任务完成回调"""
        self.task_finished.emit(task_id, success, message)
        
        # 检查是否所有任务都完成
        all_completed = all(
            task.status in [ProcessingStatus.COMPLETED, ProcessingStatus.FAILED, ProcessingStatus.CANCELLED]
            for task in self.tasks.values()
        )
        
        if all_completed:
            self.all_tasks_completed.emit()
            logger.info("所有任务已完成")
    
    def get_task_status(self, task_id: str) -> Optional[ProcessingStatus]:
        """获取任务状态"""
        if task_id in self.tasks:
            return self.tasks[task_id].status
        return None
    
    def cleanup_temp_files(self):
        """清理临时文件"""
        cleaned = 0
        for temp_file in self.temp_files[:]:
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
                    self.temp_files.remove(temp_file)
                    cleaned += 1
            except Exception as e:
                logger.warning(f"清理临时文件失败 {temp_file}: {e}")
        
        logger.info(f"清理了 {cleaned} 个临时文件")
    
    def create_temp_file(self, suffix: str = ".mp4") -> str:
        """创建临时文件"""
        temp_file = tempfile.mktemp(suffix=suffix)
        self.temp_files.append(temp_file)
        return temp_file
    
    def shutdown(self):
        """关闭管理器"""
        self.cancel_all()
        self.executor.shutdown(wait=True)
        self.cleanup_temp_files()
        logger.info("视频处理器管理器已关闭")


class SafeVideoProcessor:
    """安全的视频处理器 - 带完整异常捕获"""
    
    @staticmethod
    def safe_process_video(input_path: str, output_path: str, 
                          process_func: Callable, **kwargs) -> tuple:
        """
        安全地处理视频，捕获所有异常
        
        Returns:
            (success: bool, result: Any, error_message: str)
        """
        try:
            # 验证输入文件
            if not os.path.exists(input_path):
                return False, None, f"输入文件不存在: {input_path}"
            
            # 确保输出目录存在
            output_dir = os.path.dirname(output_path)
            if output_dir and not os.path.exists(output_dir):
                os.makedirs(output_dir, exist_ok=True)
            
            # 执行处理
            result = process_func(input_path, output_path, **kwargs)
            
            # 验证输出文件
            if os.path.exists(output_path):
                return True, result, ""
            else:
                return False, None, "输出文件未生成"
                
        except Exception as e:
            error_trace = traceback.format_exc()
            logger.error(f"视频处理失败: {e}\n{error_trace}")
            return False, None, str(e)
    
    @staticmethod
    def safe_extract_clip(input_path: str, output_path: str, 
                         start_time: float, duration: float) -> tuple:
        """安全地提取视频片段"""
        def extract_clip(input_path, output_path, start_time, duration):
            from moviepy.editor import VideoFileClip
            
            with VideoFileClip(input_path) as video:
                clip = video.subclip(start_time, start_time + duration)
                clip.write_videofile(output_path, codec='libx264', audio_codec='aac')
                clip.close()
        
        return SafeVideoProcessor.safe_process_video(
            input_path, output_path, extract_clip, 
            start_time=start_time, duration=duration
        )
    
    @staticmethod
    def safe_merge_videos(video_paths: list, output_path: str) -> tuple:
        """安全地合并视频"""
        def merge_videos(input_paths, output_path):
            from moviepy.editor import concatenate_videoclips, VideoFileClip
            
            clips = []
            try:
                for path in input_paths:
                    clips.append(VideoFileClip(path))
                
                final_clip = concatenate_videoclips(clips)
                final_clip.write_videofile(output_path, codec='libx264', audio_codec='aac')
                final_clip.close()
                
            finally:
                for clip in clips:
                    clip.close()
        
        return SafeVideoProcessor.safe_process_video(
            video_paths[0], output_path, merge_videos, input_paths=video_paths
        )


# 全局处理器实例
_video_processor_manager = None

def get_video_processor_manager(max_workers: int = 3) -> VideoProcessorManager:
    """获取视频处理器管理器实例"""
    global _video_processor_manager
    if _video_processor_manager is None:
        _video_processor_manager = VideoProcessorManager(max_workers=max_workers)
    return _video_processor_manager


def shutdown_video_processor():
    """关闭视频处理器"""
    global _video_processor_manager
    if _video_processor_manager is not None:
        _video_processor_manager.shutdown()
        _video_processor_manager = None
