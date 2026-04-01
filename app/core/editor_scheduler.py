import sys
import os

OPENSHOT_PY_PATH = os.path.join(
    os.path.dirname(__file__),
    "../../thirdparty/openshot/python"
)
sys.path.insert(0, OPENSHOT_PY_PATH)

from typing import Dict, Any, Optional, List
from enum import Enum
import threading
import time
from pathlib import Path

class EditorKernel(Enum):
    """编辑器内核类型"""
    LIGHTWEIGHT = "lightweight"  # 轻量级内核
    PROFESSIONAL = "professional"  # 专业内核（OpenShot）

class EditorScheduler:
    """双内核调度器"""
    
    def __init__(self):
        """初始化双内核调度器"""
        self._current_kernel = EditorKernel.LIGHTWEIGHT
        self._kernels = {}
        self._kernel_lock = threading.Lock()
        self._initialize_kernels()
        
    def _initialize_kernels(self):
        """初始化所有内核"""
        # 轻量级内核（默认启用）
        self._kernels[EditorKernel.LIGHTWEIGHT] = {
            'enabled': True,
            'capabilities': [
                'basic_editing',
                'simple_effects',
                'quick_export',
                'preview'
            ],
            'performance': 'high'
        }
        
        # 专业内核（OpenShot，按需启用）
        self._kernels[EditorKernel.PROFESSIONAL] = {
            'enabled': False,
            'capabilities': [
                'advanced_editing',
                'complex_effects',
                'multi_track',
                'professional_export',
                'color_grading',
                'audio_mixing'
            ],
            'performance': 'medium'
        }
        
    def switch_kernel(self, kernel: EditorKernel) -> bool:
        """切换编辑器内核
        
        Args:
            kernel: 目标内核类型
            
        Returns:
            切换是否成功
        """
        with self._kernel_lock:
            if kernel not in self._kernels:
                return False
                
            if not self._kernels[kernel]['enabled']:
                # 尝试启用内核
                if not self._enable_kernel(kernel):
                    return False
            
            self._current_kernel = kernel
            return True
    
    def _enable_kernel(self, kernel: EditorKernel) -> bool:
        """启用指定内核
        
        Args:
            kernel: 要启用的内核
            
        Returns:
            启用是否成功
        """
        if kernel == EditorKernel.PROFESSIONAL:
            # 检查OpenShot是否可用
            try:
                import openshot
                self._kernels[kernel]['enabled'] = True
                return True
            except ImportError:
                return False
        
        return True
    
    def get_current_kernel(self) -> EditorKernel:
        """获取当前内核类型"""
        return self._current_kernel
    
    def get_kernel_capabilities(self) -> List[str]:
        """获取当前内核的能力列表"""
        return self._kernels[self._current_kernel]['capabilities']
    
    def supports_feature(self, feature: str) -> bool:
        """检查当前内核是否支持指定功能
        
        Args:
            feature: 功能名称
            
        Returns:
            是否支持该功能
        """
        capabilities = self.get_kernel_capabilities()
        return feature in capabilities
    
    def get_performance_mode(self) -> str:
        """获取当前性能模式"""
        return self._kernels[self._current_kernel]['performance']
    
    def is_professional_mode(self) -> bool:
        """是否为专业模式"""
        return self._current_kernel == EditorKernel.PROFESSIONAL

# 全局调度器实例
editor_scheduler = EditorScheduler()