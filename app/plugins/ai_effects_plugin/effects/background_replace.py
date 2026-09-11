"""
AI背景替换效果模块
基于语义分割的智能背景替换，支持多种背景类型
"""

import logging

import numpy as np
import cv2
from typing import Any, Dict, Optional, Tuple
from PIL import Image

logger = logging.getLogger(__name__)


class BackgroundReplaceEffect:
    """
    AI背景替换处理器
    
    使用深度学习模型进行前景/背景分割，然后替换为指定的背景。
    支持多种背景类型：纯色、模糊、自定义图片、渐变、透明。
    
    特性：
    - 基于语义分割的精确前景提取
    - 边缘平滑和抗锯齿处理
    - 多种背景填充选项
    - 实时预览支持
    """
    
    # 预设颜色
    PRESET_COLORS = {
        'white': (255, 255, 255),
        'black': (0, 0, 0),
        'blue': (74, 144, 226),       # #4A90E2
        'green': (76, 175, 80),
        'red': (244, 67, 54),
        'purple': (156, 39, 176),
        'gray': (158, 158, 158)
    }
    
    def __init__(self, models_path: str, gpu_enabled: bool = True, cache_dir: str = './cache'):
        """初始化背景替换处理器"""
        self.models_path = models_path
        self.gpu_enabled = gpu_enabled
        self.cache_dir = cache_dir
        
        self._model = None
        self._device = None
        
        import os
        os.makedirs(models_path, exist_ok=True)
        os.makedirs(cache_dir, exist_ok=True)
        
        logger.info(f'[背景替换] 初始化完成')
    
    def load_model(self) -> bool:
        """加载分割模型 — 接入神经网络引擎"""
        try:
            from app.core.neural.background_replace import BackgroundReplaceEngine
            self._neural_engine = BackgroundReplaceEngine()
            if self._neural_engine.load(model="modnet"):
                logger.info('[背景替换] 神经网络分割引擎就绪')
                self._model = "neural"
                return True
            self._model = "fallback"
            logger.info('[背景替换] 神经网络引擎不可用，将使用传统算法')
            return True
        except ImportError as e:
            logger.info(f'[背景替换] 神经网络模块未安装: {e}')
            self._model = "fallback"
            return True
        except Exception as e:
            logger.error(f'[背景替换] 模型加载失败: {e}')
            return False
    
    def unload_model(self) -> None:
        """卸载模型"""
        if self._model is not None:
            del self._model
            self._model = None
            
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception as e:
                logger.debug(f"清理GPU缓存时失败: {e}")

            logger.info('[背景替换] 模型已卸载')
    
    def replace_background(self, 
                         frame_data: Any,
                         background_type: str = 'blur',
                         background_color: str = '#4A90E2',
                         blur_radius: int = 15,
                         edge_smoothness: int = 5,
                         custom_image: Optional[np.ndarray] = None,
                         gradient_colors: Optional[Tuple[str, str]] = None) -> Any:
        """
        执行背景替换
        
        Args:
            frame_data: 输入图像
            background_type: 背景类型 ('solid_color', 'blur', 'image', 'gradient', 'transparent')
            background_color: 背景颜色(HEX格式)
            blur_radius: 模糊半径(仅blur模式)
            edge_smoothness: 边缘平滑度
            custom_image: 自定义背景图像(仅image模式)
            gradient_colors: 渐变颜色(仅gradient模式)
        
        Returns:
            处理后的图像
        """
        if self._model is None:
            raise RuntimeError("模型未加载")
        
        # 转换输入
        image = self._to_numpy(frame_data)
        h, w = image.shape[:2]
        
        logger.info(f'[背景替换] 处理中... 类型: {background_type}, 尺寸: {w}x{h}')
        
        # 1. 获取前景掩码（模拟分割结果）
        mask = self._segment_foreground(image)
        
        # 2. 对掩码进行边缘平滑
        if edge_smoothness > 0:
            mask = self._smooth_mask(mask, edge_smoothness)
        
        # 3. 生成新背景
        new_bg = self._create_background(
            image, background_type, background_color, 
            blur_radius, custom_image, gradient_colors
        )
        
        # 4. 合成前景和新背景
        result = self._composite(image, new_bg, mask)
        
        return result
    
    def _segment_foreground(self, image: np.ndarray) -> np.ndarray:
        """
        前景分割 — 优先使用神经网络 (MODNet/U2Net)，回退 GrabCut
        返回值: 掩码 (0=背景, 255=前景)
        """
        # 尝试神经网络引擎
        if hasattr(self, '_neural_engine') and self._neural_engine:
            try:
                mask = self._neural_engine.segment(image)
                if mask is not None:
                    return mask
            except Exception as e:
                logger.debug(f"神经网络前景分割失败，回退传统算法: {e}")
        h, w = image.shape[:2]
        
        try:
            # 方法1: 使用GrabCut进行初步分割（快速但不够精确）
            mask = np.zeros((h, w), np.uint8)
            bgd_model = np.zeros((1, 65), np.float64)
            fgd_model = np.zeros((1, 65), np.float64)
            
            # 使用整个图像作为ROI（实际应用应有用户交互）
            rect = (10, 10, w-20, h-20)
            
            cv2.grabCut(image, mask, rect, bgd_model, fgd_model, 5, cv2.GC_INIT_WITH_RECT)
            
            # 转换掩码格式: GC_BGD=0, GC_FGD=1 -> 0和255
            mask_result = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
            
            # 形态学操作清理噪声
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
            mask_result = cv2.morphologyEx(mask_result, cv2.MORPH_CLOSE, kernel, iterations=2)
            mask_result = cv2.morphologyEx(mask_result, cv2.MORPH_OPEN, kernel, iterations=1)
            
            return mask_result
            
        except Exception as e:
            logger.error(f'[背景分割] GrabCut失败，使用备用方法: {e}')
            # 备用方案：基于颜色的简单分割
            hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
            lower = np.array([0, 0, 200])
            upper = np.array([180, 30, 255])
            mask = cv2.inRange(hsv, lower, upper)
            return cv2.bitwise_not(mask)
    
    def _smooth_mask(self, mask: np.ndarray, smoothness: int) -> np.ndarray:
        """对掩码边缘进行平滑/羽化处理"""
        if smoothness <= 0:
            return mask
        
        # 高斯模糊实现柔和边缘
        ksize = smoothness * 2 + 1
        blurred = cv2.GaussianBlur(mask.astype(np.float32), (ksize, ksize), 0)
        
        # 归一化到0-255范围
        smoothed = (blurred / 255.0 * 255).astype(np.uint8)
        
        return smoothed
    
    def _create_background(self, 
                          original_image: np.ndarray,
                          bg_type: str,
                          color_hex: str,
                          blur_radius: int,
                          custom_image: Optional[np.ndarray],
                          gradient_colors: Optional[Tuple[str, str]]) -> np.ndarray:
        """根据类型创建新背景"""
        h, w = original_image.shape[:2]
        
        if bg_type == 'solid_color':
            # 纯色背景
            bgr_color = self._hex_to_bgr(color_hex)
            bg = np.full((h, w, 3), bgr_color, dtype=np.uint8)
        
        elif bg_type == 'blur':
            # 模糊背景（使用原图模糊）
            ksize = blur_radius * 2 + 1
            bg = cv2.GaussianBlur(original_image, (ksize, ksize), 0)
            # 可选：轻微调暗使前景更突出
            bg = (bg * 0.85).astype(np.uint8)
        
        elif bg_type == 'image':
            # 自定义图片背景
            if custom_image is not None:
                bg = cv2.resize(custom_image, (w, h))
            else:
                # 默认渐变作为后备
                bg = self._create_gradient_background(h, w)
        
        elif bg_type == 'gradient':
            # 渐变背景
            if gradient_colors:
                bg = self._create_gradient_background(h, w, gradient_colors[0], gradient_colors[1])
            else:
                color1 = color_hex
                color2 = self._shift_color(color_hex, 60)
                bg = self._create_gradient_background(h, w, color1, color2)
        
        elif bg_type == 'transparent':
            # 透明背景（返回带alpha通道的图像）
            bg = np.zeros((h, w, 3), dtype=np.uint8)
        
        else:
            raise ValueError(f"未知背景类型: {bg_type}")
        
        return bg
    
    def _composite(self, foreground: np.ndarray, 
                   background: np.ndarray, 
                   mask: np.ndarray) -> np.ndarray:
        """使用掩码合成前景和背景"""
        # 确保掩码是浮点数用于平滑混合
        mask_float = mask.astype(np.float32) / 255.0
        
        # 扩展mask维度以匹配图像通道
        mask_3ch = np.stack([mask_float] * 3, axis=-1)
        
        # 混合
        result = (foreground * mask_3ch + background * (1 - mask_3ch))
        
        return result.clip(0, 255).astype(np.uint8)
    
    def _hex_to_bgr(self, hex_color: str) -> Tuple[int, int, int]:
        """将HEX颜色转换为BGR元组"""
        hex_color = hex_color.lstrip('#')
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        return (b, g, r)
    
    def _shift_color(self, hex_color: str, shift_degrees: int) -> str:
        """在色轮上偏移颜色"""
        bgr = self._hex_to_bgr(hex_color)
        hsv = cv2.cvtColor(np.array([[bgr]], dtype=np.uint8), cv2.COLOR_BGR2HSV)[0][0]
        hsv[0] = (hsv[0] + shift_degrees // 2) % 180  # OpenCV的H范围是0-179
        rgb = cv2.cvtColor(np.array([[hsv]], dtype=np.uint8), cv2.COLOR_HSV2BGR)[0][0]
        return '#{:02x}{:02x}{:02x}'.format(rgb[2], rgb[1], rgb[0])
    
    def _create_gradient_background(self, h: int, w: int, 
                                   color1_hex: Optional[str] = None,
                                   color2_hex: Optional[str] = None) -> np.ndarray:
        """创建渐变背景"""
        c1 = self._hex_to_bgr(color1_hex or '#667eea')
        c2 = self._hex_to_bgr(color2_hex or '#764ba2')
        
        # 创建线性渐变
        gradient = np.linspace(0, 1, h, dtype=np.float32).reshape(-1, 1, 1)
        gradient = np.broadcast_to(gradient, (h, w, 1))
        
        # 插值颜色
        c1_arr = np.array(c1, dtype=np.float32)
        c2_arr = np.array(c2, dtype=np.float32)
        bg = c1_arr * (1 - gradient) + c2_arr * gradient
        
        return bg.astype(np.uint8)
    
    def _to_numpy(self, data: Any) -> np.ndarray:
        """转换为numpy数组"""
        if isinstance(data, np.ndarray):
            return data
        elif hasattr(data, 'convert'):
            return np.array(data.convert('RGB'))
        elif isinstance(data, str):
            return cv2.imread(data)
        else:
            raise ValueError(f"不支持的输入格式: {type(data)}")
    
    def get_info(self) -> Dict[str, str]:
        """获取处理器信息"""
        return {
            'name': 'AI背景替换',
            'version': '1.0.0',
            'type': 'Semantic Segmentation + Background Replacement',
            'supported_types': ['solid_color', 'blur', 'image', 'gradient', 'transparent'],
            'model_loaded': self._model is not None
        }
