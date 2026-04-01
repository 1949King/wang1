"""
渲染管理器 - 第二阶段核心组件
=======================================
提供统一的渲染管理，支持预览/导出分离
目标：支持软渲染/GPU渲染自动切换，预览不阻塞导出
"""

import threading
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from enum import Enum

from app.modules.utils.logger import logger
from .soft_render import SoftwareRenderer, RenderConfig, RenderQuality
from .gpu_render import GPURenderer, GPUConfig
from .proxy_preview import ProxyPreviewRenderer
from .gpu_compatibility import get_gpu_compatibility_tester

class RenderMode(Enum):
    """渲染模式"""
    PREVIEW = "preview"      # 预览模式（低质量，快速）
    EDIT = "edit"           # 编辑模式（中等质量，平衡）
    EXPORT = "export"        # 导出模式（高质量，慢速）

class RenderPriority(Enum):
    """渲染优先级"""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4

@dataclass
class RenderTask:
    """渲染任务"""
    task_id: str
    mode: RenderMode
    priority: RenderPriority
    frame_data: Optional[Any] = None
    sequence_data: Optional[List[Any]] = None
    output_path: Optional[str] = None
    callback: Optional[callable] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class RenderManagerConfig:
    """渲染管理器配置"""
    enable_gpu: bool = True  # 是否启用GPU
    auto_switch_backend: bool = True  # 自动切换后端
    max_preview_threads: int = 2  # 预览最大线程数
    max_export_threads: int = 4  # 导出最大线程数
    enable_proxy_preview: bool = True  # 是否启用代理预览
    cache_preview_frames: bool = True  # 是否缓存预览帧

class RenderManager:
    """统一渲染管理器"""
    
    def __init__(self, config: Optional[RenderManagerConfig] = None):
        self.config = config or RenderManagerConfig()
        self._software_renderer = None
        self._gpu_renderer = None
        self._proxy_renderer = None
        self._current_mode = RenderMode.PREVIEW
        self._rendering = False
        self._lock = threading.Lock()
        self._task_queue = []
        self._current_task = None
        self._render_stats = {
            'total_tasks': 0,
            'completed_tasks': 0,
            'failed_tasks': 0,
            'preview_tasks': 0,
            'export_tasks': 0
        }
        
        logger.info(f"渲染管理器初始化: GPU={self.config.enable_gpu}, 代理预览={self.config.enable_proxy_preview}")
    
    def initialize(self) -> bool:
        """初始化渲染管理器"""
        try:
            # 初始化软渲染器
            self._software_renderer = SoftwareRenderer()
            if not self._software_renderer.initialize():
                logger.error("软渲染器初始化失败")
                return False
            
            # 初始化GPU渲染器
            if self.config.enable_gpu:
                # 测试GPU兼容性
                compatibility_result = self._test_gpu_compatibility()
                
                # 根据兼容性测试结果配置GPU渲染器
                gpu_config = self._configure_gpu_based_on_compatibility(compatibility_result)
                self._gpu_renderer = GPURenderer(gpu_config)
                
                if not self._gpu_renderer.initialize():
                    logger.warning("GPU渲染器初始化失败，使用软渲染器")
                    self._gpu_renderer = None
                else:
                    logger.info("GPU渲染器初始化成功")
            
            # 初始化代理预览
            if self.config.enable_proxy_preview:
                self._proxy_renderer = ProxyPreviewRenderer()
                logger.info("代理预览渲染器初始化成功")
            
            logger.info("渲染管理器初始化成功")
            return True
            
        except Exception as e:
            logger.error(f"渲染管理器初始化失败: {e}")
            return False
    
    def _test_gpu_compatibility(self):
        """测试GPU兼容性"""
        try:
            tester = get_gpu_compatibility_tester()
            result = tester.test_compatibility()
            if result:
                report = tester.generate_compatibility_report(result)
                logger.info(f"GPU兼容性测试报告:\n{report}")
                return result
            else:
                logger.warning("无法测试GPU兼容性")
                return None
        except Exception as e:
            logger.error(f"GPU兼容性测试失败: {e}")
            return None
    
    def _configure_gpu_based_on_compatibility(self, compatibility_result):
        """根据兼容性测试结果配置GPU渲染器"""
        gpu_config = GPUConfig()
        
        if compatibility_result:
            # 根据兼容性状态设置默认分辨率
            if compatibility_result.status.value == "fully_compatible":
                # 完全兼容，使用1080P
                gpu_config.width = 1920
                gpu_config.height = 1080
            elif compatibility_result.status.value == "partially_compatible":
                # 部分兼容，使用720P
                gpu_config.width = 1280
                gpu_config.height = 720
            else:
                # 不兼容，使用720P作为基础
                gpu_config.width = 1280
                gpu_config.height = 720
            
            # 根据支持的后端设置默认后端
            supported_backends = compatibility_result.supported_backends
            if "cuda" in supported_backends:
                from .gpu_render import GPUBackend
                gpu_config.backend = GPUBackend.CUDA
            elif "opencl" in supported_backends:
                from .gpu_render import GPUBackend
                gpu_config.backend = GPUBackend.OPENCL
            
            logger.info(f"基于兼容性测试配置GPU: {gpu_config.width}x{gpu_config.height}, 后端={gpu_config.backend.value}")
        
        return gpu_config
    
    def switch_mode(self, mode: RenderMode) -> bool:
        """切换渲染模式"""
        with self._lock:
            if self._rendering:
                logger.warning(f"渲染器正在渲染中，无法切换模式")
                return False
            
            self._current_mode = mode
            logger.info(f"渲染模式切换为: {mode.value}")
            return True
    
    def submit_preview_task(self, task: RenderTask) -> str:
        """提交预览任务"""
        task.mode = RenderMode.PREVIEW
        task.priority = RenderPriority.HIGH
        return self._submit_task(task)
    
    def submit_edit_task(self, task: RenderTask) -> str:
        """提交编辑任务"""
        task.mode = RenderMode.EDIT
        task.priority = RenderPriority.NORMAL
        return self._submit_task(task)
    
    def submit_export_task(self, task: RenderTask) -> str:
        """提交导出任务"""
        task.mode = RenderMode.EXPORT
        task.priority = RenderPriority.CRITICAL
        return self._submit_task(task)
    
    def _submit_task(self, task: RenderTask) -> str:
        """提交任务到队列"""
        with self._lock:
            if self._rendering:
                logger.warning("渲染器忙碌，任务已加入队列")
            
            self._task_queue.append(task)
            self._render_stats['total_tasks'] += 1
            
            logger.debug(f"任务已提交: {task.task_id}, 模式: {task.mode.value}")
            return task.task_id
    
    def _process_task_queue(self):
        """处理任务队列"""
        while self._task_queue and not self._rendering:
            task = self._task_queue.pop(0)
            self._current_task = task
            
            # 根据模式选择渲染器
            success = False
            if task.mode == RenderMode.PREVIEW:
                success = self._render_preview_task(task)
            elif task.mode == RenderMode.EDIT:
                success = self._render_edit_task(task)
            elif task.mode == RenderMode.EXPORT:
                success = self._render_export_task(task)
            
            # 更新统计
            if success:
                self._render_stats['completed_tasks'] += 1
                if task.mode == RenderMode.PREVIEW:
                    self._render_stats['preview_tasks'] += 1
                elif task.mode == RenderMode.EXPORT:
                    self._render_stats['export_tasks'] += 1
            else:
                self._render_stats['failed_tasks'] += 1
            
            # 执行回调
            if task.callback:
                try:
                    task.callback(success, task)
                except Exception as e:
                    logger.error(f"任务回调失败: {e}")
            
            self._current_task = None
    
    def _render_preview_task(self, task: RenderTask) -> bool:
        """渲染预览任务"""
        try:
            # 使用代理预览
            if self.config.enable_proxy_preview and self._proxy_renderer:
                proxy_path = self._proxy_renderer.generate_proxy(task.frame_data.get('video_path', ''))
                if proxy_path:
                    logger.debug(f"使用代理预览: {proxy_path}")
            
            # 使用软渲染器快速渲染
            if self._software_renderer:
                result = self._software_renderer.render_frame(task.frame_data)
                return result.success if result else False
            
            return False
            
        except Exception as e:
            logger.error(f"预览渲染失败: {e}")
            return False
    
    def _render_edit_task(self, task: RenderTask) -> bool:
        """渲染编辑任务"""
        try:
            # 使用软渲染器或GPU渲染器
            if self._gpu_renderer and self.config.enable_gpu:
                result = self._gpu_renderer.render_frame(task.frame_data)
                if result and result.success:
                    logger.info(f"GPU编辑渲染完成: {task.task_id}")
                    return True
                elif result:
                    logger.warning(f"GPU渲染失败，回退到软渲染: {result.error_message}")
            
            # 回退到软渲染器
            if self._software_renderer:
                result = self._software_renderer.render_frame(task.frame_data)
                if result and result.success:
                    logger.info(f"软编辑渲染完成: {task.task_id}")
                    return True
            
            return False
            
        except Exception as e:
            logger.error(f"编辑渲染失败: {e}")
            return False
    
    def _render_export_task(self, task: RenderTask) -> bool:
        """渲染导出任务"""
        try:
            # 使用GPU渲染器（如果可用）
            if self._gpu_renderer and self.config.enable_gpu:
                result = self._gpu_renderer.render_sequence(task.sequence_data, task.output_path)
                if result and result.success:
                    logger.info(f"GPU导出完成: {task.task_id}")
                    return True
                elif result:
                    logger.warning(f"GPU导出失败，回退到软渲染: {result.error_message}")
            
            # 回退到软渲染器
            if self._software_renderer:
                result = self._software_renderer.render_sequence(task.sequence_data, task.output_path)
                if result and result.success:
                    logger.info(f"软导出完成: {task.task_id}")
                    return True
            
            return False
            
        except Exception as e:
            logger.error(f"导出渲染失败: {e}")
            return False
    
    def start_rendering(self):
        """开始渲染处理"""
        with self._lock:
            if self._rendering:
                logger.warning("渲染器已在运行")
                return
            
            self._rendering = True
            logger.info("开始渲染处理")
    
    def stop_rendering(self):
        """停止渲染处理"""
        with self._lock:
            if not self._rendering:
                logger.warning("渲染器未在运行")
                return
            
            self._rendering = False
            logger.info("停止渲染处理")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取渲染统计"""
        with self._lock:
            return {
                'current_mode': self._current_mode.value,
                'rendering': self._rendering,
                'queue_size': len(self._task_queue),
                'current_task': self._current_task.task_id if self._current_task else None,
                'stats': self._render_stats,
                'gpu_enabled': self.config.enable_gpu,
                'gpu_available': self._gpu_renderer is not None and self._gpu_renderer.is_gpu_available() if self._gpu_renderer else False,
                'proxy_enabled': self.config.enable_proxy_preview
            }
    
    def get_current_mode(self) -> RenderMode:
        """获取当前渲染模式"""
        return self._current_mode
    
    def is_rendering(self) -> bool:
        """检查是否正在渲染"""
        return self._rendering
    
    def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        with self._lock:
            # 从队列中移除
            for i, task in enumerate(self._task_queue):
                if task.task_id == task_id:
                    self._task_queue.pop(i)
                    logger.info(f"任务已取消: {task_id}")
                    return True
            
            # 如果是当前任务，停止渲染
            if self._current_task and self._current_task.task_id == task_id:
                self.stop_rendering()
                logger.info(f"当前任务已停止: {task_id}")
                return True
        
        return False
    
    def shutdown(self) -> bool:
        """关闭渲染管理器"""
        with self._lock:
            if self._rendering:
                self.stop_rendering()
            
            # 关闭所有渲染器
            if self._software_renderer:
                self._software_renderer.shutdown()
            
            if self._gpu_renderer:
                self._gpu_renderer.shutdown()
            
            if self._proxy_renderer:
                self._proxy_renderer.shutdown()
            
            # 清空队列
            self._task_queue.clear()
            
            logger.info("渲染管理器已关闭")
        
        return True

# 全局渲染管理器实例
render_manager = None
_render_manager_lock = threading.Lock()

def get_render_manager(config: Optional[RenderManagerConfig] = None) -> RenderManager:
    """获取渲染管理器实例（单例模式）"""
    global render_manager
    if render_manager is None:
        with _render_manager_lock:
            if render_manager is None:
                render_manager = RenderManager(config)
    return render_manager