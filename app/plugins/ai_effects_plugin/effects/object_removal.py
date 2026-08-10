"""
智能物体移除效果模块
基于AI图像修复（Inpainting）的物体移除和背景填充
支持自动检测、手动选择、笔刷涂抹等多种移除方式
"""

import logging

import numpy as np
import cv2
from typing import Any, Dict, Optional, List, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


class RemovalMode(Enum):
    """移除模式"""
    AUTO_DETECT = "auto_detect"      # 自动检测并移除常见物体
    MANUAL_SELECT = "manual_select"  # 手动框选区域
    BRUSH_PAINT = "brush_paint"      # 笔刷涂抹标记


class FillMethod(Enum):
    """填充方法"""
    AI_INPAINTING = "ai_inpainting"      # AI驱动的修复（最佳质量）
    CONTENT_AWARE = "content_aware"       # 内容感知填充
    BLUR_FILL = "blur_fill"              # 模糊填充（快速但简单）
    CLONE_STAMP = "clone_stamp"          # 仿制图章（精确控制）


class ObjectRemovalEffect:
    """
    智能物体移除处理器
    
    使用AI图像修复技术从画面中移除指定物体，并用合理的背景内容填充空缺区域。
    支持多种物体识别和多种填充算法。
    
    特性：
    - 多种移除方式：自动检测、手动选择、笔刷涂抹
    - 4种填充算法：AI修复、内容感知、模糊填充、仿制图章
    - 边缘羽化和平滑过渡
    - 支持批量移除多个物体
    - GPU加速支持
    """
    
    # 常见可自动识别的物体类别
    DETECTABLE_OBJECTS = {
        'person': {'name': '人物', 'priority': 10},
        'car': {'name': '汽车', 'priority': 7},
        'dog': {'name': '狗', 'priority': 6},
        'cat': {'name': '猫', 'priority': 6},
        'bird': {'name': '鸟', 'priority': 5},
        'text': {'name': '文字/水印', 'priority': 9},
        'logo': {'name': 'Logo', 'priority': 8},
        'stamp': {'name': '印章', 'priority': 8},
        'date_stamp': {'name': '日期戳', 'priority': 9},
        'building': {'name': '建筑', 'priority': 4},
        'tree': {'name': '树木', 'priority': 3}
    }
    
    def __init__(self, models_path: str, gpu_enabled: bool = True, cache_dir: str = './cache'):
        """初始化物体移除处理器"""
        self.models_path = models_path
        self.gpu_enabled = gpu_enabled
        self.cache_dir = cache_dir
        
        self._inpainting_model = None
        self._object_detector = None
        self._device = None
        
        # 笔刷状态（用于交互式操作）
        self._brush_mask = None
        self._selected_regions = []  # 手动选择的区域列表
        
        import os
        os.makedirs(models_path, exist_ok=True)
        os.makedirs(cache_dir, exist_ok=True)
        
        print("[物体移除] 初始化完成")
    
    def load_model(self) -> bool:
        """加载AI修复模型 — 接入神经网络引擎"""
        try:
            from app.core.neural.inpainting import InpaintingEngine
            self._neural_engine = InpaintingEngine()
            if self._neural_engine.load():
                print("[物体移除] 神经网络 Inpainting 引擎就绪")
                self._inpainting_model = "neural"
                return True
            self._inpainting_model = "opencv_mode"
            print("[物体移除] 神经网络引擎不可用，将使用传统算法")
            return True
        except ImportError as e:
            print(f"[物体移除] 神经网络模块未安装: {e}")
            self._inpainting_model = "opencv_mode"
            return True
        except Exception as e:
            print(f"[物体移除] 模型加载失败: {e}")
            return False
    
    def unload_model(self) -> None:
        """卸载模型"""
        self._inpainting_model = None
        self._object_detector = None
        self._brush_mask = None
        self._selected_regions.clear()
        
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception as e:
            logger.debug(f"清理GPU缓存时失败: {e}")

        print("[物体移除] 模型已卸载")
    
    def remove_object(self,
                     frame_data: Any,
                     mode: str = 'auto_detect',
                     fill_method: str = 'ai_inpainting',
                     brush_size: int = 30,
                     edge_feathering: int = 10,
                     target_objects: Optional[List[str]] = None,
                     mask: Optional[np.ndarray] = None,
                     selected_rect: Optional[Tuple[int, int, int, int]] = None) -> Any:
        """
        执行物体移除
        
        Args:
            frame_data: 输入图像
            mode: 移除模式 ('auto_detect'/'manual_select'/'brush_paint')
            fill_method: 填充方法 ('ai_inpainting'/'content_aware'/'blur_fill'/'clone_stamp')
            brush_size: 笔刷大小(像素)
            edge_feathering: 边缘羽化程度
            target_objects: 自动模式下要移除的物体类别列表(如 ['text', 'logo'])
            mask: 自定义掩码(笔刷模式的输入)
            selected_rect: 手动选择的矩形区域(x, y, w, h)
        
        Returns:
            处理后的图像（已移除指定物体）
        """
        if self._inpainting_model is None:
            raise RuntimeError("模型未加载")
        
        image = self._to_numpy(frame_data).copy()
        h, w = image.shape[:2]
        
        print(f"[物体移除] 模式: {mode}, 填充: {fill_method}")
        
        # 根据模式生成要移除的区域掩码
        removal_mask = self._create_removal_mask(
            image, mode, brush_size, 
            target_objects, mask, selected_rect
        )
        
        if removal_mask is None or removal_mask.sum() == 0:
            print("[物体移除] ⚠️ 未检测到要移除的区域")
            return image
        
        print(f"[物体移除] 待移除区域占比: {removal_mask.sum()/(h*w)*100:.1f}%")
        
        # 对掩码进行边缘羽化
        if edge_feathering > 0:
            removal_mask = self._feather_edges(removal_mask, edge_feathering)
        
        # 应用填充方法
        result = self._fill_removal_area(image, removal_mask, fill_method)
        
        return result
    
    def _create_removal_mask(self, image: np.ndarray, 
                            mode: str, 
                            brush_size: int,
                            target_objects: Optional[List[str]],
                            mask: Optional[np.ndarray],
                            selected_rect: Optional[Tuple[int, int, int, int]]) -> Optional[np.ndarray]:
        """根据模式创建待移除区域的掩码"""
        h, w = image.shape[:2]
        base_mask = np.zeros((h, w), dtype=np.uint8)
        
        if mode == 'auto_detect':
            # 自动检测模式：尝试检测常见物体
            base_mask = self._auto_detect_objects(image, target_objects)
            
        elif mode == 'manual_select':
            # 手动选择模式
            if selected_rect:
                x, y, rw, rh = selected_rect
                base_mask[y:y+rh, x:x+rw] = 255
            else:
                print("[物体移除] ⚠️ 手动模式但未提供选择区域")
                return None
        
        elif mode == 'brush_paint':
            # 笔刷模式
            if mask is not None:
                base_mask = mask.copy()
            elif self._brush_mask is not None:
                base_mask = self._brush_mask.copy()
            else:
                print("[物体移除] ⚠️ 笔刷模式但未提供掩码")
                return None
        else:
            raise ValueError(f"未知移除模式: {mode}")
        
        return base_mask
    
    def _auto_detect_objects(self, image: np.ndarray, 
                           target_objects: Optional[List[str]]) -> np.ndarray:
        """
        自动检测可移除的物体
        
        使用多种方法检测：文字/水印检测、颜色聚类、边缘分析等
        （生产环境应使用YOLO等目标检测网络）
        """
        h, w = image.shape[:2]
        combined_mask = np.zeros((h, w), dtype=np.uint8)
        
        # 如果没有指定目标物体，默认移除文字和水印类
        if target_objects is None:
            target_objects = ['text', 'logo', 'stamp']
        
        print(f"[物体移除] 自动检测目标: {target_objects}")
        
        for obj_type in target_objects:
            obj_mask = np.zeros((h, w), dtype=np.uint8)
            
            if obj_type in ['text', 'logo', 'stamp', 'date_stamp']:
                # 文字/印章检测方法
                obj_mask = self._detect_text_and_stamps(image, obj_type)
            
            elif obj_type in ['person']:
                # 人物检测（简化版）
                obj_mask = self._detect_person_simple(image)
            
            elif obj_type in ['car', 'building']:
                # 大物体检测（基于颜色/边缘）
                obj_mask = self._detect_large_objects(image)
            
            # 合并到总掩码
            combined_mask = cv2.bitwise_or(combined_mask, obj_mask)
        
        # 后处理：形态学清理
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        combined_mask = cv2.morphologyEx(combined_mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        combined_mask = cv2.morphologyEx(combined_mask, cv2.MORPH_OPEN, kernel, iterations=1)
        
        return combined_mask
    
    def _detect_text_and_stamps(self, image: np.ndarray, 
                               obj_type: str) -> np.ndarray:
        """检测文字、水印、印章等"""
        h, w = image.shape[:2]
        mask = np.zeros((h, w), dtype=np.uint8)
        
        # 方法1：边缘密度检测（文字通常有高边缘密度）
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 50, 150)
        
        # 局部边缘密度
        kernel_size = 15
        kernel = np.ones((kernel_size, kernel_size), np.uint8)
        local_density = cv2.filter2D(edges, -1, kernel)
        
        # 高密度区域可能是文字
        _, thresh = cv2.threshold(local_density, kernel_size**2 * 0.4, 255, cv2.THRESH_BINARY)
        
        if obj_type in ['text', 'logo']:
            mask = thresh
        
        elif obj_type == 'stamp':
            # 印章通常是红色圆形或方形
            hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
            
            # 检测红色区域
            lower_red1 = np.array([0, 100, 100])
            upper_red1 = np.array([10, 255, 255])
            lower_red2 = np.array([160, 100, 100])
            upper_red2 = np.array([180, 255, 255])
            
            red_mask1 = cv2.inRange(hsv, lower_red1, upper_red1)
            red_mask2 = cv2.inRange(hsv, lower_red2, upper_red2)
            red_mask = cv2.bitwise_or(red_mask1, red_mask2)
            
            # 寻找轮廓
            contours, _ = cv2.findContours(red_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            for cnt in contours:
                area = cv2.contourArea(cnt)
                if area > 200 and area < h*w*0.1:  # 合理大小的区域
                    cv2.drawContours(mask, [cnt], -1, 255, -1)
        
        elif obj_type == 'date_stamp':
            # 日期戳通常是半透明的小字
            # 使用频率域检测周期性纹理
            gray_float = gray.astype(np.float32) / 255.0
            
            # FFT变换
            f_transform = np.fft.fft2(gray_float)
            f_shift = np.fft.fftshift(f_transform)
            
            # 高频分量增强（文字特征）
            magnitude = np.log(np.abs(f_shift) + 1e-10)
            mean_mag = np.mean(magnitude)
            
            # 高频区域
            high_freq_mask = magnitude > mean_mag * 1.5
            high_freq_mask_uint8 = (high_freq_mask * 255).astype(np.uint8)
            
            # 反FFT得到空间域的高频成分
            f_shift_filtered = f_shift * (magnitude < mean_mag * 2.0)
            f_ishift = np.fft.ifftshift(f_shift_filtered)
            img_back = np.fft.ifft2(f_ishift)
            img_back_real = np.abs(img_back_real := img_back.real)
            
            # 高频残差（可能包含文字）
            high_freq_residual = np.abs(gray_float - img_back_real / np.max(img_back_real))
            _, text_mask = cv2.threshold((high_freq_residual * 255).astype(np.uint8), 30, 255, cv2.THRESH_BINARY)
            
            # 形态学连接断开的笔画
            kernel = np.ones((3, 3), np.uint8)
            text_mask = cv2.dilate(text_mask, kernel, iterations=2)
            
            mask = text_mask
        
        return mask
    
    def _detect_person_simple(self, image: np.ndarray) -> np.ndarray:
        """简化版人物检测（基于肤色和形状）"""
        h, w = image.shape[:2]
        mask = np.zeros((h, w), dtype=np.uint8)
        
        # 肤色检测
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        lower_skin = np.array([0, 20, 70], dtype=np.uint8)
        upper_skin = np.array([20, 255, 255], dtype=np.uint8)
        skin_mask = cv2.inRange(hsv, lower_skin, upper_skin)
        
        # 寻找较大的连通区域（可能是人体）
        contours, _ = cv2.findContours(skin_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area > h*w * 0.02:  # 占比大于2%的区域
                # 扩展区域以覆盖整个人体
                x, y, cw, ch = cv2.boundingRect(cnt)
                padding_x = int(cw * 0.3)
                padding_y = int(ch * 0.5)
                
                x1 = max(0, x - padding_x)
                y1 = max(0, y - padding_y)
                x2 = min(w, x + cw + padding_x)
                y2 = min(h, y + ch + padding_y)
                
                mask[y1:y2, x1:x2] = 255
        
        return mask
    
    def _detect_large_objects(self, image: np.ndarray) -> np.ndarray:
        """检测大型物体（基于显著性和颜色差异）"""
        h, w = image.shape[:2]
        mask = np.zeros((h, w), dtype=np.uint8)
        
        # 使用GrabCut分割前景
        bgd_model = np.zeros((1, 65), np.float64)
        fgd_model = np.zeros((1, 65), np.float64)
        
        rect = (int(w*0.1), int(h*0.1), int(w*0.8), int(h*0.8))
        grabcut_mask = np.zeros((h, w), np.uint8)
        
        cv2.grabCut(image, grabcut_mask, rect, bgd_model, fgd_model, 5, cv2.GC_INIT_WITH_RECT)
        
        # 提取明显的前景区域
        foreground_mask = np.where((grabcut_mask == cv2.GC_FGD) | (grabcut_mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
        
        # 过滤掉太小的区域
        contours, _ = cv2.findContours(foreground_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area > h*w * 0.01:  # 大于1%画面面积
                cv2.drawContours(mask, [cnt], -1, 255, -1)
        
        return mask
    
    def _feather_edges(self, mask: np.ndarray, feather_amount: int) -> np.ndarray:
        """对掩码边缘进行羽化处理"""
        if feather_amount <= 0:
            return mask
        
        ksize = feather_amount * 2 + 1
        blurred = cv2.GaussianBlur(mask.astype(np.float32), (ksize, ksize), 0)
        
        # 保持核心区域为纯白
        core = cv2.erode(mask, np.ones((feather_amount, feather_amount), np.uint8), iterations=1)
        result = np.where(core > 0, 255, blurred)
        
        return result.clip(0, 255).astype(np.uint8)
    
    def _fill_removal_area(self, image: np.ndarray, 
                          mask: np.ndarray, 
                          fill_method: str) -> np.ndarray:
        """使用指定的方法填充被移除的区域"""
        
        if fill_method == 'ai_inpainting':
            return self._ai_inpainting(image, mask)
        
        elif fill_method == 'content_aware':
            return self._content_aware_fill(image, mask)
        
        elif fill_method == 'blur_fill':
            return self._blur_fill(image, mask)
        
        elif fill_method == 'clone_stamp':
            return self._clone_stamp_fill(image, mask)
        
        else:
            raise ValueError(f"未知填充方法: {fill_method}")
    
    def _ai_inpainting(self, image: np.ndarray, mask: np.ndarray) -> np.ndarray:
        """
        AI 驱动修复 — 优先使用 LaMa 神经网络，回退到传统算法
        """
        print("[填充] 使用AI Inpainting...")

        # 尝试神经网络引擎
        if hasattr(self, '_neural_engine') and self._neural_engine:
            try:
                result = self._neural_engine.inpaint(image, mask)
                if result is not None:
                    return result
            except Exception as e:
                logger.debug(f"神经网络修复失败，回退OpenCV算法: {e}")

        # OpenCV 传统回退
        
        # 使用改进的传统算法作为fallback或混合方案
        # OpenCV inpaint (Telea或Navier-Stokes方法)
        result_telea = cv2.inpaint(image, mask, inpaintRadius=5, flags=cv2.INPAINT_TELEA)
        result_ns = cv2.inpaint(image, mask, inpaintRadius=5, flags=cv2.INPAINT_NS)
        
        # 混合两种结果取优
        result = cv2.addWeighted(result_telea, 0.6, result_ns, 0.4, 0)
        
        # 后处理：纹理一致性优化
        result = self._texture_consistency_optimization(result, mask)
        
        return result
    
    def _content_aware_fill(self, image: np.ndarray, mask: np.ndarray) -> np.ndarray:
        """内容感知填充（PatchMatch算法的简化版）"""
        print("[填充] 使用Content-Aware Fill...")
        
        h, w = image.shape[:2]
        result = image.copy()
        
        # 迭代修复
        iterations = 10
        for i in range(iterations):
            # 从外向内逐层修复
            eroded_mask = cv2.erode(mask, np.ones((3, 3)), iterations=i+1)
            boundary = mask - eroded_mask
            
            if boundary.sum() == 0:
                break
            
            # 对于边界上的每个像素，寻找最佳匹配块
            coords = np.where(boundary > 0)
            for y, x in zip(coords[0], coords[1]):
                patch_size = 11
                half = patch_size // 2
                
                # 提取目标patch
                y1, y2 = max(0, y-half), min(h, y+half+1)
                x1, x2 = max(0, x-half), min(w, x+half+1)
                
                target_patch = result[y1:y2, x1:x2].astype(np.float32)
                target_mask = mask[y1:y2, x1:x2]
                
                # 在已知区域搜索最相似的patch（简化版：随机采样搜索）
                best_match = None
                best_score = float('inf')
                
                search_samples = 50  # 采样数量（增加以提高质量）
                known_coords = np.where(eroded_mask == 0)
                
                if len(known_coords[0]) > 0:
                    indices = np.random.choice(len(known_coords[0]), min(search_samples, len(known_coords[0])))
                    
                    for idx in indices:
                        sy, sx = known_coords[0][idx], known_coords[1][idx]
                        
                        sy1, sy2 = max(0, sy-half), min(h, sy+half+1)
                        sx1, sx2 = max(0, sx-half), min(w, sx+half+1)
                        
                        if abs(y2-y1) != abs(sy2-sy1) or abs(x2-x1) != abs(sx2-sx1):
                            continue
                        
                        candidate = result[sy1:sy2, sx1:sx2].astype(np.float32)
                        
                        # 只比较已知区域的误差
                        known_pixels = (target_mask == 0)
                        if known_pixels.sum() > 0:
                            diff = target_patch[candidate.shape[0]==target_patch.shape[0]][known_pixels] - \
                                   candidate[candidate.shape[0]==candidate.shape[0]][known_pixels]
                            score = np.sum(diff**2)
                            
                            if score < best_score:
                                best_score = score
                                best_match = (sy1, sy2, sx1, sx2)
                    
                    if best_match:
                        sy1, sy2, sx1, sx2 = best_match
                        source = result[sy1:sy2, sx1:sx2]
                        
                        # 只复制未知像素
                        unknown_pixels = (mask[y1:y2, x1:x2] > 0)
                        result[y1:y2, x1:x2][unknown_pixels] = source[unknown_pixels[:source.shape[0]][:source.shape[1]] if source.ndim==2 and source.shape[0]>unknown_pixels.shape[0] else source[unknown_pixels]]
        
        return result
    
    def _blur_fill(self, image: np.ndarray, mask: np.ndarray) -> np.ndarray:
        """模糊填充（快速但简单的填充方式）"""
        print("[填充] 使用Blur Fill...")
        
        # 强模糊周围环境
        blurred = cv2.GaussianBlur(image, (51, 51), 0)
        
        # 混合原图和模糊图
        mask_float = mask.astype(np.float32) / 255.0
        mask_3ch = np.stack([mask_float]*3, axis=-1)
        
        result = (image * (1 - mask_3ch) + blurred * mask_3ch)
        
        return result.clip(0, 255).astype(np.uint8)
    
    def _clone_stamp_fill(self, image: np.ndarray, mask: np.ndarray) -> np.ndarray:
        """仿制图章填充（需要用户交互指定源点）"""
        print("[填充] 使用Clone Stamp（需指定源点，当前使用自动源点）...")
        
        h, w = image.shape[:2]
        result = image.copy()
        
        # 简化版：自动选择距离掩码最远的已知区域作为源
        # 计算距离变换找到离掩码最远的点
        dist_transform = cv2.distanceTransform(255-mask, cv2.DIST_L2, 5)
        
        # 在多个远距离点采样
        num_sources = 5
        flat_indices = np.argpartition(dist_transform.flatten(), -num_sources)[-num_sources:]
        source_points = [(idx // w, idx % w) for idx in flat_indices]
        
        # 分块填充
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        for contour in contours:
            x, y, cw, ch = cv2.boundingRect(contour)
            
            # 选择最近的源点
            cx, cy = x+cw//2, y+ch//2
            distances = [(sx-cx)**2 + (sy-cy)**2 for sy, sx in source_points]
            best_source = source_points[np.argmin(distances)]
            
            sy, sx = best_source
            
            # 复制源区域
            for dy in range(ch):
                for dx in range(cw):
                    if mask[y+dy, x+dx] > 0:
                        src_y = (sy + dy) % h
                        src_x = (sx + dx) % w
                        result[y+dy, x+dx] = image[src_y, src_x]
        
        return result
    
    def _texture_consistency_optimization(self, image: np.ndarray, 
                                         mask: np.ndarray) -> np.ndarray:
        """纹理一致性后处理优化"""
        # 轻微的高斯模糊以消除接缝痕迹
        slightly_blurred = cv2.GaussianBlur(image, (3, 3), 0)
        
        mask_eroded = cv2.erode(mask, np.ones((5, 5)), iterations=2)
        boundary = mask - mask_eroded
        
        if boundary.sum() > 0:
            # 仅在边界处混合模糊结果
            mask_float = boundary.astype(np.float32) / 255.0
            mask_3ch = np.stack([mask_float]*3, axis=-1)
            
            image = (image * (1 - mask_3ch) + slightly_blurred * mask_3ch)
        
        return image.clip(0, 255).astype(np.uint8)
    
    def set_brush_position(self, x: int, y: int, size: int) -> None:
        """设置笔刷绘制位置（用于交互式操作）"""
        if self._brush_mask is None:
            return
        
        h, w = self._brush_mask.shape
        cv2.circle(self._brush_mask, (x, y), size, 255, -1)
    
    def clear_brush(self, shape: Tuple[int, ...]) -> None:
        """清空笔刷掩码"""
        if len(shape) == 2:
            self._brush_mask = np.zeros(shape, dtype=np.uint8)
        else:
            self._brush_mask = None
    
    def add_selected_region(self, rect: Tuple[int, int, int, int]) -> None:
        """添加手动选择的区域"""
        self._selected_regions.append(rect)
    
    def clear_selections(self) -> None:
        """清除所有选择"""
        self._selected_regions.clear()
    
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
            'name': '智能物体移除',
            'version': '1.0.0',
            'type': 'AI Object Removal + Image Inpainting',
            'removal_modes': ['auto_detect', 'manual_select', 'brush_paint'],
            'fill_methods': ['ai_inpainting', 'content_aware', 'blur_fill', 'clone_stamp'],
            'model_loaded': self._inpainting_model is not None
        }
