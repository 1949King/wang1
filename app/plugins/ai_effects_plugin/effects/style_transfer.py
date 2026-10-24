"""
风格迁移效果模块
基于神经风格迁移（Neural Style Transfer）实现图像艺术化
支持多种预设艺术风格：梵高、莫奈、毕加索、赛博朋克、动漫等
"""

import logging

import numpy as np
import cv2
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class StyleTransferEffect:
    """
    风格迁移特效处理器
    
    实现基于深度学习的艺术风格迁移，将内容图像转换为指定的艺术风格。
    支持多种经典和现代艺术风格的实时转换。
    
    特性：
    - 8种预设艺术风格（可扩展）
    - 可调节的风格强度
    - 颜色保留选项
    - 支持GPU/CPU双模式
    - 基于预训练模型的快速推理
    """
    
    # 预设风格配置
    STYLE_PRESETS = {
        'vangogh': {
            'name': '梵高星空',
            'description': '模仿文森特·梵高的漩涡状笔触',
            'brush_size': 15,
            'color_shift': 0.3,
            'texture_strength': 0.8,
            'model_file': 'vgg_vangogh.pth'
        },
        'monet': {
            'name': '莫奈睡莲',
            'description': '克劳德·莫奈的印象派柔和笔触',
            'brush_size': 20,
            'color_shift': 0.2,
            'texture_strength': 0.6,
            'model_file': 'vgg_monet.pth'
        },
        'picasso': {
            'name': '毕加索抽象',
            'description': '巴勃罗·毕加索的立体主义几何风格',
            'brush_size': 10,
            'color_shift': 0.5,
            'texture_strength': 0.9,
            'model_file': 'vgg_picasso.pth'
        },
        'cyberpunk': {
            'name': '赛博朋克',
            'description': '霓虹色彩与未来科技感的融合',
            'brush_size': 8,
            'color_shift': 0.7,
            'texture_strength': 0.7,
            'model_file': 'cyberpunk.pth'
        },
        'anime': {
            'name': '动漫风',
            'description': '日式动漫的平滑色彩和线条感',
            'brush_size': 12,
            'color_shift': 0.4,
            'texture_strength': 0.5,
            'model_file': 'anime_transfer.pth'
        },
        'oil_painting': {
            'name': '油画',
            'description': '经典油画质感和厚重颜料效果',
            'brush_size': 18,
            'color_shift': 0.25,
            'texture_strength': 0.85,
            'model_file': 'oil_painting.pth'
        },
        'watercolor': {
            'name': '水彩画',
            'description': '水彩颜料的透明流动感',
            'brush_size': 22,
            'color_shift': 0.35,
            'texture_strength': 0.55,
            'model_file': 'watercolor.pth'
        },
        'sketch': {
            'name': '素描',
            'description': '铅笔素描的黑白线条质感',
            'brush_size': 5,
            'color_shift': 0.1,
            'texture_strength': 0.95,
            'model_file': 'sketch.pth'
        }
    }
    
    def __init__(self, models_path: str, gpu_enabled: bool = True, cache_dir: str = './cache'):
        """
        初始化风格迁移处理器
        
        Args:
            models_path: 模型文件存储路径
            gpu_enabled: 是否启用GPU加速
            cache_dir: 缓存目录
        """
        self.models_path = models_path
        self.gpu_enabled = gpu_enabled
        self.cache_dir = cache_dir
        
        self._model = None
        self._device = None
        self._current_style = None
        
        # 创建必要的目录
        import os
        os.makedirs(models_path, exist_ok=True)
        os.makedirs(cache_dir, exist_ok=True)
        
        logger.info(f"[风格迁移] 初始化完成，GPU: {('启用' if gpu_enabled else '禁用')}")
    
    def load_model(self) -> bool:
        """加载风格迁移模型 — 接入神经网络引擎"""
        try:
            from app.core.neural.style_transfer import StyleTransferEngine
            self._neural_engine = StyleTransferEngine()
            if self._neural_engine.load():
                logger.info('[风格迁移] 神经网络引擎就绪')
                self._model = "neural"
                return True
            self._model = "fallback"
            logger.info('[风格迁移] 神经网络引擎不可用，将使用传统算法')
            return True
        except ImportError as e:
            logger.info(f'[风格迁移] 神经网络模块未安装: {e}')
            self._model = "fallback"
            return True
        except Exception as e:
            logger.error(f'[风格迁移] 模型加载失败: {e}')
            return False
    
    def unload_model(self) -> None:
        """卸载模型释放内存"""
        if self._model is not None:
            del self._model
            self._model = None
            
            # 清理GPU缓存
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception as e:
                logger.debug(f"清理GPU缓存时失败: {e}")

            logger.info('[风格迁移] 模型已卸载')
    
    def apply(self, frame_data: Any, 
              style_name: str = 'cyberpunk',
              strength: float = 0.8,
              preserve_color: bool = True) -> Any:
        """
        应用风格迁移效果
        
        Args:
            frame_data: 输入图像 (numpy数组或PIL Image)
            style_name: 风格名称（见STYLE_PRESETS）
            strength: 风格强度 (0.0-1.0)
            preserve_color: 是否保留原图颜色
        
        Returns:
            处理后的图像
        """
        if self._model is None:
            raise RuntimeError("模型未加载，请先调用load_model()")
        
        # 转换输入为numpy数组
        input_image = self._to_numpy(frame_data)
        original = input_image.copy()
        
        # 获取风格配置
        if style_name not in self.STYLE_PRESETS:
            raise ValueError(f"未知风格: {style_name}，可选: {list(self.STYLE_PRESETS.keys())}")
        
        style_config = self.STYLE_PRESETS[style_name]
        self._current_style = style_name
        
        logger.info(f"[风格迁移] 应用风格: {style_config['name']} (强度: {strength})")
        
        # 应用风格迁移效果
        result = self._transfer_style(input_image, style_config, strength, preserve_color)
        
        return result
    
    def _transfer_style(self, image: np.ndarray, 
                       style_config: Dict[str, Any],
                       strength: float,
                       preserve_color: bool) -> np.ndarray:
        """
        执行风格迁移 — 优先使用神经网络引擎，回退到传统算法
        """
        # 尝试神经网络引擎
        if hasattr(self, '_neural_engine') and self._neural_engine:
            try:
                result = self._neural_engine.transfer(
                    image, style=self._current_style,
                    strength=strength, preserve_color=preserve_color
                )
                if result is not None:
                    return result
            except Exception as e:
                logger.debug(f"神经网络风格迁移失败，回退传统算法: {e}")

        # 传统算法回退
        h, w = image.shape[:2]
        result = image.astype(np.float32)
        
        # ====== 1. 颜色调整 ======
        color_shift = style_config['color_shift'] * strength
        if color_shift > 0:
            # 应用色调偏移
            hsv = cv2.cvtColor(result, cv2.COLOR_BGR2HSV).astype(np.float32)
            
            # 根据不同风格应用不同的色相偏移
            hue_shift = {'vangogh': 15, 'monet': 8, 'picasso': 25, 
                        'cyberpunk': 180, 'anime': 10, 'oil_painting': 5,
                        'watercolor': 12, 'sketch': 0}
            shift_amount = hue_shift.get(self._current_style, 0) * color_shift
            hsv[:, :, 0] = (hsv[:, :, 0] + shift_amount) % 180
            
            # 饱和度增强
            sat_boost = 1.0 + color_shift * 0.3
            hsv[:, :, 1] = np.clip(hsv[:, :, 1] * sat_boost, 0, 255)
            
            result = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR).astype(np.float32)
        
        # ====== 2. 纹理/笔触模拟 ======
        texture_str = style_config['texture_strength'] * strength
        brush_size = style_config['brush_size']
        
        if texture_str > 0 and self._current_style != 'sketch':
            # 应用油画/水彩质感滤镜
            if self._current_style in ['oil_painting', 'vangogh']:
                # 厚重笔触效果 - 双边滤波+边缘增强
                bilateral = cv2.bilateralFilter(
                    (result / 255).astype(np.uint8), 
                    d=brush_size * 2, 
                    sigmaColor=75, 
                    sigmaSpace=75
                ).astype(np.float32) * 255
                
                # 边缘增强
                gray = cv2.cvtColor(result.astype(np.uint8), cv2.COLOR_BGR2GRAY)
                edges = cv2.Laplacian(gray, cv2.CV_64F)
                edges = np.abs(edges).astype(np.float32)
                edges = cv2.GaussianBlur(edges, (3, 3), 0)
                
                result = result * (1 - texture_str * 0.3) + bilateral * texture_str * 0.3
                
            elif self._current_style == 'watercolor':
                # 水彩效果 - 形态学操作
                kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, 
                                                  (brush_size, brush_size))
                watercolor = cv2.morphologyEx(
                    (result / 255).astype(np.uint8), 
                    cv2.MORPH_CLOSE, kernel
                ).astype(np.float32) * 255
                
                watercolor = cv2.GaussianBlur(watercolor, (brush_size//2+1, brush_size//2+1), 0)
                result = result * (1 - texture_str * 0.5) + watercolor * texture_str * 0.5
            
            elif self._current_style == 'cyberpunk':
                # 赛博朋克 - 霓虹发光效果
                glow = cv2.GaussianBlur(result, (21, 21), 0) * 0.3
                result = result + glow * texture_str
                
                # 增强对比度
                alpha = 1.0 + texture_str * 0.3
                beta = -30 * texture_str
                result = cv2.convertScaleAbs(result, alpha=alpha, beta=beta).astype(np.float32)
            
            elif self._current_style == 'anime':
                # 动漫风 - 边缘检测+平滑
                blurred = cv2.GaussianBlur(result, (7, 7), 0)
                
                # 边缘提取并强化
                gray = cv2.cvtColor(blurred.astype(np.uint8), cv2.COLOR_BGR2GRAY)
                edges = cv2.Canny(gray, 50, 150)
                edges_bgr = cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR).astype(np.float32)
                
                # 平滑区域 + 强化边缘
                result = blurred * (1 - texture_str * 0.4) + result * texture_str * 0.4
                result = result - edges_bgr * texture_str * 0.2
            
            elif self._current_style == 'picasso':
                # 立体主义 - 几何分割
                cell_size = max(20, int(min(h, w) * 0.08))
                for y in range(0, h - cell_size, cell_size):
                    for x in range(0, w - cell_size, cell_size):
                        cell = result[y:y+cell_size, x:x+cell_size]
                        mean_color = np.mean(cell.reshape(-1, 3), axis=0)
                        result[y:y+cell_size, x:x+cell_size] = mean_color
                
                # 轻微旋转扰动
                if texture_str > 0.5:
                    M = cv2.getRotationMatrix2D((w//2, h//2), 2, 1)
                    result = cv2.warpAffine(result, M, (w, h))
        
        # ====== 3. 特殊效果处理 ======
        if self._current_style == 'sketch':
            # 素描效果
            gray = cv2.cvtColor(result.astype(np.uint8), cv2.COLOR_BGR2GRAY)
            gray = gray.astype(np.float32)
            
            # 反转并模糊
            inverted = 255 - gray
            blurred = cv2.GaussianBlur(inverted, (21, 21), sigmaX=0, sigmaY=0)
            
            # 颜色减淡混合
            sketch = gray / (255 - blurred + 0.001) * 255
            sketch = np.clip(sketch, 0, 255)
            
            # 强度控制
            result_gray = gray * (1 - texture_str) + sketch * texture_str
            result = cv2.cvtColor(result_gray.astype(np.uint8), cv2.COLOR_GRAY2BGR).astype(np.float32)
        
        elif self._current_style == 'monet':
            # 莫奈印象派 - 点彩效果
            noise = np.random.normal(0, 15 * strength, result.shape)
            result = result + noise
        
        # ====== 4. 颜色融合 ======
        if preserve_color:
            # 保留原图的主要色调
            original_float = image.astype(np.float32)
            
            # 在Lab色彩空间进行混合
            orig_lab = cv2.cvtColor(original_float.astype(np.uint8), cv2.COLOR_BGR2LAB).astype(np.float32)
            stylized_lab = cv2.cvtColor(np.clip(result, 0, 255).astype(np.uint8), cv2.COLOR_BGR2LAB).astype(np.float32)
            
            # 保留L通道（亮度）的部分原始信息
            blend_alpha = 0.6  # 保留60%原始亮度分布
            stylized_lab[:, :, 0] = (orig_lab[:, :, 0] * blend_alpha + 
                                    stylized_lab[:, :, 0] * (1 - blend_alpha))
            
            result = cv2.cvtColor(stylized_lab.astype(np.uint8), cv2.COLOR_LAB2BGR).astype(np.float32)
        
        # 最终裁剪和类型转换
        result = np.clip(result, 0, 255).astype(np.uint8)
        
        # 与原图混合以控制整体强度
        if strength < 1.0:
            result = cv2.addWeighted(image, 1 - strength, result, strength, 0)
        
        return result
    
    def _to_numpy(self, data: Any) -> np.ndarray:
        """将各种输入格式转换为numpy数组"""
        if isinstance(data, np.ndarray):
            return data
        elif hasattr(data, 'convert'):  # PIL Image
            return np.array(data.convert('RGB'))
        elif isinstance(data, str):  # 文件路径
            return cv2.imread(data)
        else:
            raise ValueError(f"不支持的输入格式: {type(data)}")
    
    def get_available_styles(self) -> Dict[str, Dict]:
        """获取所有可用的风格列表"""
        return self.STYLE_PRESETS.copy()
    
    def get_info(self) -> Dict[str, str]:
        """获取处理器信息"""
        return {
            'name': '风格迁移',
            'version': '1.0.0',
            'type': 'Neural Style Transfer',
            'supported_styles': len(self.STYLE_PRESETS),
            'model_loaded': self._model is not None
        }
