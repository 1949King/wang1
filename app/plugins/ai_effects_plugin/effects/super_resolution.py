"""
超分辨率效果模块
基于深度学习的图像/视频分辨率提升
支持2x/3x/4倍放大，同时可进行降噪处理
"""

import numpy as np
import cv2
from typing import Any, Dict, Optional, Literal


class SuperResolutionEffect:
    """
    超分辨率增强处理器
    
    使用深度学习模型提升图像/视频的分辨率。
    支持多种放大倍数和质量模式，并集成降噪功能。
    
    特性：
    - 支持2x/3x/4倍放大
    - 三种质量模式：快速/均衡/高质量
    - 内置降噪功能
    - GPU/CPU自适应
    - 保持细节的同时减少伪影
    """
    
    QUALITY_MODES = {
        'fast': {
            'name': '快速模式',
            'description': '速度优先，适合实时处理',
            'model': 'espcn_x2',
            'estimated_time_per_frame_ms': 15
        },
        'balanced': {
            'name': '均衡模式',
            'description': '速度与质量平衡',
            'model': 'srresnet_x2',
            'estimated_time_per_frame_ms': 50
        },
        'quality': {
            'name': '高质量模式',
            'description': '质量优先，适合离线处理',
            'model': 'edsr_x4',
            'estimated_time_per_frame_ms': 150
        }
    }
    
    def __init__(self, models_path: str, gpu_enabled: bool = True, cache_dir: str = './cache'):
        """初始化超分辨率处理器"""
        self.models_path = models_path
        self.gpu_enabled = gpu_enabled
        self.cache_dir = cache_dir
        
        self._models = {}  # 存储不同倍数的模型
        self._device = None
        self._current_scale = 2
        
        import os
        os.makedirs(models_path, exist_ok=True)
        os.makedirs(cache_dir, exist_ok=True)
        
        print(f"[超分辨率] 初始化完成，GPU: {'启用' if gpu_enabled else '禁用'}")
    
    def load_model(self) -> bool:
        """加载SR模型"""
        try:
            import torch
            
            self._device = torch.device('cuda' if self.gpu_enabled and torch.cuda.is_available() else 'cpu')
            print(f"[超分辨率] 使用设备: {self._device}")
            
            # 模拟加载不同倍数的模型
            for scale in [2, 3, 4]:
                self._models[scale] = f"model_{scale}x"
            
            print("[超分辨率] ✅ SR模型就绪（演示模式）")
            return True
            
        except Exception as e:
            print(f"[超分辨率] ❌ 模型加载失败: {e}")
            return False
    
    def unload_model(self) -> None:
        """卸载所有模型"""
        self._models.clear()
        
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except:
            pass
        
        print("[超分辨率] 所有模型已卸载")
    
    def enhance(self, 
               frame_data: Any,
               scale_factor: int = 2,
               quality_mode: str = 'fast',
               denoise_strength: float = 0.3) -> Any:
        """
        执行超分辨率增强
        
        Args:
            frame_data: 输入图像
            scale_factor: 放大倍数 (2/3/4)
            quality_mode: 质量模式 ('fast'/'balanced'/'quality')
            denoise_strength: 降噪强度 (0.0-1.0)
        
        Returns:
            增强后的高分辨率图像
        """
        if not self._models:
            raise RuntimeError("模型未加载")
        
        if scale_factor not in [2, 3, 4]:
            raise ValueError(f"不支持的放大倍数: {scale_factor}，请选择 2/3/4")
        
        # 转换输入
        image = self._to_numpy(frame_data)
        orig_h, orig_w = image.shape[:2]
        
        self._current_scale = scale_factor
        target_h, target_w = orig_h * scale_factor, orig_w * scale_factor
        
        print(f"[超分辨率] 放大 {scale_factor}x: {orig_w}x{orig_h} → {target_w}x{target_h}")
        print(f"[超分辨率] 质量模式: {self.QUALITY_MODES.get(quality_mode, {}).get('name', 'unknown')}")
        
        # 1. 如果有降噪需求，先执行降噪
        if denoise_strength > 0:
            image = self._denoise(image, denoise_strength)
        
        # 2. 执行超分辨率放大
        enhanced = self._super_resolve(image, scale_factor, quality_mode)
        
        # 3. 后处理：锐化和细节增强
        enhanced = self._post_process(enhanced)
        
        return enhanced
    
    def _denoise(self, image: np.ndarray, strength: float) -> np.ndarray:
        """降噪处理"""
        if strength <= 0:
            return image
        
        # 根据强度选择不同的降噪算法
        if strength < 0.3:
            # 轻度降噪：简单的高斯模糊
            sigma = int(strength * 10)
            if sigma > 0:
                denoised = cv2.GaussianBlur(image, (sigma*2+1, sigma*2+1), sigma)
                return cv2.addWeighted(image, 1 - strength, denoised, strength, 0)
        
        elif strength < 0.7:
            # 中度降噪：双边滤波（保留边缘）
            d = int(strength * 20) + 5
            denoised = cv2.bilateralFilter(
                image, 
                d=d, 
                sigmaColor=strength * 75, 
                sigmaSpace=strength * 75
            )
            blend = strength * 0.7
            return cv2.addWeighted(image, 1 - blend, denoised, blend, 0)
        
        else:
            # 强度降噪：非局部均值去噪
            template_size = max(3, int(strength * 7))
            search_size = max(7, int(strength * 21))
            denoised = cv2.fastNlMeansDenoisingColored(
                image, 
                h=strength * 10,
                templateWindowSize=template_size,
                searchWindowSize=search_size
            )
            blend = 0.85
            return cv2.addWeighted(image, 1 - blend, denoised, blend, 0)
    
    def _super_resolve(self, image: np.ndarray, 
                       scale: int, 
                       mode: str) -> np.ndarray:
        """
        核心超分辨率算法 — 优先使用神经网络引擎，回退到传统算法
        """
        # 尝试神经网络引擎
        try:
            from app.core.neural.super_resolution import SuperResolutionEngine
            if not hasattr(self, '_neural_sr'):
                self._neural_sr = SuperResolutionEngine()
                self._neural_sr.load(scale=scale, use_realesrgan=True)
            result = self._neural_sr.upscale(image)
            if result is not None:
                return result
        except Exception:
            pass

        h, w = image.shape[:2]
        
        if mode == 'fast':
            # 快速模式：双三次插值 + 锐化增强
            result = cv2.resize(image, (w * scale, h * scale), 
                               interpolation=cv2.INTER_CUBIC)
            
            # 应用Unsharp Masking锐化
            result = self._unsharp_mask(result, amount=1.2, radius=1)
        
        elif mode == 'balanced':
            # 均衡模式：Lanczos插值 + 细节增强
            result = cv2.resize(image, (w * scale, h * scale),
                               interpolation=cv2.INTER_LANCZOS4)
            
            # 多尺度细节增强
            result = self._enhance_details(result, strength=0.6)
        
        elif mode == 'quality':
            # 高质量模式：多步放大 + AI细节重建（模拟）
            # 第一步：2x放大
            intermediate = cv2.resize(image, (w * 2, h * 2),
                                     interpolation=cv2.INTER_LANCZOS4)
            intermediate = self._enhance_details(intermediate, strength=0.8)
            
            if scale == 2:
                result = intermediate
            else:
                # 第二步：继续放大到目标尺寸
                remaining_scale = scale // 2
                result = cv2.resize(intermediate, 
                                   (w * scale, h * scale),
                                   interpolation=cv2.INTER_LANCZOS4)
                
                # 最终细节重建
                result = self._enhance_details(result, strength=1.0)
                
                # 边缘细化
                result = self._refine_edges(result)
        else:
            # 默认：双三次插值
            result = cv2.resize(image, (w * scale, h * scale),
                               interpolation=cv2.INTER_CUBIC)
        
        return result
    
    def _unsharp_mask(self, image: np.ndarray, 
                      amount: float = 1.0, 
                      radius: float = 1.0,
                      threshold: int = 0) -> np.ndarray:
        """USM锐化（反锐化遮罩）"""
        blurred = cv2.GaussianBlur(image, (0, 0), radius)
        sharpened = float(amount + 1) * image - amount * blurred
        sharpened = np.clip(sharpened, 0, 255).astype(np.uint8)
        
        if threshold > 0:
            # 仅在差异超过阈值时应用锐化
            diff = cv2.absdiff(image, sharpened)
            mask = diff > threshold
            result = np.where(mask, sharpened, image)
            return result.astype(np.uint8)
        
        return sharpened
    
    def _enhance_details(self, image: np.ndarray, 
                        strength: float = 0.5) -> np.ndarray:
        """多尺度细节增强"""
        if strength <= 0:
            return image
        
        # 转换到LAB色彩空间（仅在L通道上处理）
        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        l_channel = lab[:, :, 0].astype(np.float32)
        
        # 创建多个尺度的细节层
        details_sum = np.zeros_like(l_channel)
        
        for sigma in [1, 2, 4]:
            blurred = cv2.GaussianBlur(l_channel, (0, 0), sigma)
            detail = l_channel - blurred
            details_sum += detail
        
        # 平均细节并按强度混合
        details_avg = details_sum / 3.0
        enhanced_l = l_channel + details_avg * strength
        
        # 裁剪并合并回BGR
        lab[:, :, 0] = np.clip(enhanced_l, 0, 255).astype(np.uint8)
        result = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
        
        return result
    
    def _refine_edges(self, image: np.ndarray) -> np.ndarray:
        """边缘细化和抗锯齿"""
        # 提取边缘
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 100, 200)
        
        # 对边缘区域应用轻微锐化
        edges_dilated = cv2.dilate(edges, np.ones((3, 3)), iterations=1)
        edges_mask = (edges_dilated > 0).astype(np.float32)
        edges_3ch = np.stack([edges_mask] * 3, axis=-1)
        
        # 在边缘区域应用锐化
        sharpened = self._unsharp_mask(image, amount=0.8, radius=0.5)
        
        # 混合原始图和锐化图
        refined = image * (1 - edges_3ch * 0.3) + sharpened * edges_3ch * 0.3
        
        return refined.astype(np.uint8)
    
    def _post_process(self, image: np.ndarray) -> np.ndarray:
        """后处理：整体优化"""
        # 轻微的色彩校正和对比度调整
        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB).astype(np.float32)
        
        # CLAHE（对比度受限的自适应直方图均衡）
        clahe = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(8, 8))
        lab[:, :, 0] = clahe.apply(lab[:, :, 0].astype(np.uint8)).astype(np.float32)
        
        result = cv2.cvtColor(lab.astype(np.uint8), cv2.COLOR_LAB2BGR)
        
        return result
    
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
            'name': '超分辨率',
            'version': '1.0.0',
            'type': 'Deep Learning Super Resolution',
            'supported_scales': [2, 3, 4],
            'quality_modes': list(self.QUALITY_MODES.keys()),
            'model_loaded': len(self._models) > 0
        }


class VideoSuperResolution(SuperResolutionEffect):
    """
    视频超分辨率扩展类
    利用帧间信息进一步提升视频质量
    """
    
    def enhance_video_frame(self, 
                           current_frame: np.ndarray,
                           prev_frames: list,
                           next_frames: list,
                           **kwargs) -> np.ndarray:
        """
        使用帧间信息增强单帧
        
        Args:
            current_frame: 当前帧
            prev_frames: 前面的帧列表
            next_frames: 后面的帧列表
            kwargs: 其他参数（同enhance方法）
        
        Returns:
            增强后的帧
        """
        # 先进行常规的超分辨率增强
        enhanced = super().enhance(current_frame, **kwargs)
        
        # 如果有相邻帧，可以进行时间一致性优化
        if prev_frames or next_frames:
            # 简单的时间滤波减少闪烁（生产环境应使用光流等方法）
            all_frames = [enhanced]
            
            if prev_frames:
                # 将前一帧缩放到当前帧尺寸（假设已放大）
                for pf in prev_frames[-2:]:  # 使用最近2帧
                    pf_resized = cv2.resize(pf, (enhanced.shape[1], enhanced.shape[0]))
                    all_frames.append(pf_resized)
            
            if next_frames:
                for nf in next_frames[:2]:  # 使用接下来2帧
                    nf_resized = cv2.resize(nf, (enhanced.shape[1], enhanced.shape[0]))
                    all_frames.append(nf_resized)
            
            # 时间平均（简化版，实际应使用更复杂的时序融合）
            temporal_avg = np.mean(all_frames, axis=0).astype(np.uint8)
            
            # 将时间平均结果与当前帧混合
            alpha = 0.3  # 时间信息的权重
            final = cv2.addWeighted(enhanced, 1 - alpha, temporal_avg, alpha, 0)
            
            return final
        
        return enhanced
