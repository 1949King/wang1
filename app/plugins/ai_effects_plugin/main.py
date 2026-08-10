"""
AI特效制作插件 - 主逻辑模块
实现IEffectPlugin接口，提供完整的AI特效处理能力

特效子模块懒加载：导入 Plugin 本身不因缺 torch/模型而整包失败。
"""

import json
from typing import Dict, Any, List, Optional, Callable
from enum import Enum

# 导入插件系统核心接口
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

try:
    from app.core.plugin_loader import IEffectPlugin, PluginInfo, PluginType, PluginCategory
except ImportError:
    # 兼容不同导入路径
    from core.plugin_loader import IEffectPlugin, PluginInfo, PluginType, PluginCategory

# UI 懒加载（避免顶层 import 拖垮整包）
AIEffectsWidget = None


def _load_ai_effects_widget():
    global AIEffectsWidget
    if AIEffectsWidget is not None:
        return AIEffectsWidget
    from .ui.ai_effects_widget import AIEffectsWidget as _W
    AIEffectsWidget = _W
    return AIEffectsWidget


class AIEffectType(Enum):
    """AI特效类型枚举"""
    STYLE_TRANSFER = "style_transfer"           # 风格迁移
    BACKGROUND_REPLACE = "background_replace"   # 背景替换
    SUPER_RESOLUTION = "super_resolution"       # 超分辨率
    BEAUTY_FILTER = "beauty_filter"             # 智能美颜
    OBJECT_REMOVAL = "object_removal"           # 物体移除


class Plugin(IEffectPlugin):
    """
    AI特效制作插件主类
    
    实现IEffectPlugin接口，提供基于深度学习的智能视频/图像特效处理功能。
    
    支持的特效类型：
    - 风格迁移：将图像转换为艺术风格（梵高、莫奈、赛博朋克等）
    - 背景替换：智能识别前景并替换背景
    - 超分辨率：提升视频/图像分辨率，最高4倍放大
    - 智能美颜：AI驱动的磨皮、美白、瘦脸等效果
    - 物体移除：移除指定物体并自动填充背景
    """
    
    # 插件实例状态
    _instance = None
    _initialized = False
    
    def __new__(cls):
        """单例模式确保插件唯一性"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """初始化插件实例"""
        if not hasattr(self, '_effects'):
            self._effects: Dict[AIEffectType, Any] = {}
            self._current_effect: Optional[AIEffectType] = None
            self._effect_params: Dict[str, Any] = {}
            self._models_loaded: Dict[AIEffectType, bool] = {
                effect_type: False for effect_type in AIEffectType
            }
            self._context: Dict[str, Any] = {}
            self._callbacks: Dict[str, Callable] = {}
            self._last_error: str = ""
            info = self.plugin_info
            self.name = info.name
            self.version = info.version
            self.description = (info.description or "").split("\n")[0]

    def run(self, **kwargs) -> bool:
        """PluginManager 兼容入口。"""
        if not self._initialized:
            return self.initialize(kwargs.get("context") or self._context or {})
        return True
    
    @property
    def plugin_info(self) -> PluginInfo:
        """获取插件元信息"""
        return PluginInfo(
            id="ai_effects_studio",
            name="AI特效制作",
            version="1.0.0",
            description=(
                "基于深度学习的智能特效制作工具\n"
                "支持风格迁移、背景替换、超分辨率、智能美颜、物体移除"
            ),
            author="拾光剪影官方",
            plugin_type=PluginType.AI,
            category=PluginCategory.GENERAL,
            file_path=__file__,
            tags=[
                "AI", "深度学习", "神经网络", "风格迁移", "背景替换",
                "超分辨率", "美颜", "物体移除", "智能特效"
            ]
        )
    
    def initialize(self, context: Dict[str, Any]) -> bool:
        """
        初始化插件
        
        Args:
            context: 初始化上下文，包含：
                - models_path: 模型文件存储路径
                - gpu_enabled: 是否启用GPU加速
                - cache_dir: 缓存目录
        
        Returns:
            bool: 初始化是否成功
        """
        try:
            self._context = context or {}
            self._last_error = ""
            
            # 解析上下文参数
            models_path = self._context.get('models_path', './models/ai_effects')
            gpu_enabled = self._context.get('gpu_enabled', True)
            cache_dir = self._context.get('cache_dir', './cache/ai_effects')
            
            # 确保目录存在
            os.makedirs(models_path, exist_ok=True)
            os.makedirs(cache_dir, exist_ok=True)
            
            print(f"[AI特效] 初始化中... GPU加速: {'开启' if gpu_enabled else '关闭'}")
            print(f"[AI特效] 模型路径: {models_path}")
            print(f"[AI特效] 缓存路径: {cache_dir}")
            
            # 初始化所有特效处理器（懒导入）
            self._init_effect_processors(models_path, gpu_enabled, cache_dir)
            
            self._initialized = True
            print("[AI特效] ✅ 初始化完成")
            return True
            
        except Exception as e:
            self._last_error = str(e)
            print(f"[AI特效] ❌ 初始化失败: {str(e)}")
            return False
    
    def _init_effect_processors(self, models_path: str, gpu_enabled: bool, cache_dir: str):
        """初始化所有特效处理器（逐个尝试，单个失败不阻断其它）"""
        loaders = [
            (AIEffectType.STYLE_TRANSFER, "style_transfer", "StyleTransferEffect", "style_transfer"),
            (AIEffectType.BACKGROUND_REPLACE, "background_replace", "BackgroundReplaceEffect", "background_seg"),
            (AIEffectType.SUPER_RESOLUTION, "super_resolution", "SuperResolutionEffect", "sr"),
            (AIEffectType.BEAUTY_FILTER, "beauty_filter", "BeautyFilterEffect", "beauty"),
            (AIEffectType.OBJECT_REMOVAL, "object_removal", "ObjectRemovalEffect", "inpainting"),
        ]
        errors = []
        for effect_type, mod_name, cls_name, subdir in loaders:
            try:
                mod = __import__(
                    f"app.plugins.ai_effects_plugin.effects.{mod_name}",
                    fromlist=[cls_name],
                )
                cls = getattr(mod, cls_name)
                self._effects[effect_type] = cls(
                    models_path=os.path.join(models_path, subdir),
                    gpu_enabled=gpu_enabled,
                    cache_dir=cache_dir,
                )
            except Exception as e:
                errors.append(f"{effect_type.value}: {e}")
                print(f"[AI特效] 特效 {effect_type.value} 加载失败: {e}")
        if errors and not self._effects:
            raise RuntimeError("全部特效子模块加载失败: " + "; ".join(errors))
        if errors:
            self._last_error = "部分特效不可用: " + "; ".join(errors)
    
    def shutdown(self) -> bool:
        """
        关闭插件，释放所有资源
        
        Returns:
            bool: 是否成功关闭
        """
        try:
            print("[AI特效] 正在关闭...")
            
            # 卸载所有模型
            for effect_type, processor in self._effects.items():
                if self._models_loaded.get(effect_type, False):
                    try:
                        processor.unload_model()
                        self._models_loaded[effect_type] = False
                        print(f"[AI特效] 已卸载 {effect_type.value} 模型")
                    except Exception as e:
                        print(f"[AI特效] 卸载 {effect_type.value} 失败: {e}")
            
            # 清空状态
            self._effects.clear()
            self._current_effect = None
            self._effect_params.clear()
            self._callbacks.clear()
            self._initialized = False
            
            print("[AI特效] ✅ 已关闭")
            return True
            
        except Exception as e:
            print(f"[AI特效] ❌ 关闭失败: {str(e)}")
            return False
    
    def get_ui_config(self) -> Dict[str, Any]:
        """
        获取UI配置信息
        
        Returns:
            Dict: UI配置，包含参数定义和布局信息
        """
        return {
            "name": "AI特效制作",
            "icon": "🎨",
            "category": "AI工具",
            "has_custom_widget": True,
            "widget_class": "AIEffectsWidget",
            "params": [
                # ====== 风格迁移参数 ======
                {
                    "group": "风格迁移",
                    "params": [
                        {
                            "name": "style_name",
                            "type": "select",
                            "options": [
                                {"value": "vangogh", "label": "梵高星空"},
                                {"value": "monet", "label": "莫奈睡莲"},
                                {"value": "picasso", "label": "毕加索抽象"},
                                {"value": "cyberpunk", "label": "赛博朋克"},
                                {"value": "anime", "label": "动漫风"},
                                {"value": "oil_painting", "label": "油画"},
                                {"value": "watercolor", "label": "水彩画"},
                                {"value": "sketch", "label": "素描"}
                            ],
                            "default": "cyberpunk",
                            "label": "艺术风格",
                            "description": "选择要应用的艺术风格"
                        },
                        {
                            "name": "style_strength",
                            "type": "slider",
                            "min": 0.0,
                            "max": 1.0,
                            "default": 0.8,
                            "step": 0.01,
                            "label": "风格强度",
                            "description": "控制风格化的强度"
                        },
                        {
                            "name": "preserve_color",
                            "type": "checkbox",
                            "default": True,
                            "label": "保留原色",
                            "description": "是否保留原图的颜色"
                        }
                    ]
                },
                # ====== 背景替换参数 ======
                {
                    "group": "背景替换",
                    "params": [
                        {
                            "name": "background_type",
                            "type": "select",
                            "options": [
                                {"value": "solid_color", "label": "纯色背景"},
                                {"value": "blur", "label": "模糊背景"},
                                {"value": "image", "label": "自定义图片"},
                                {"value": "gradient", "label": "渐变背景"},
                                {"value": "transparent", "label": "透明背景"}
                            ],
                            "default": "blur",
                            "label": "背景类型",
                            "description": "选择替换后的背景类型"
                        },
                        {
                            "name": "background_color",
                            "type": "color",
                            "default": "#4A90E2",
                            "label": "背景颜色",
                            "description": "纯色背景时的颜色"
                        },
                        {
                            "name": "blur_strength",
                            "type": "slider",
                            "min": 0,
                            "max": 50,
                            "default": 15,
                            "label": "模糊程度",
                            "description": "模糊背景的模糊半径"
                        },
                        {
                            "name": "edge_smoothness",
                            "type": "slider",
                            "min": 0,
                            "max": 20,
                            "default": 5,
                            "label": "边缘平滑度",
                            "description": "前景边缘的平滑处理程度"
                        }
                    ]
                },
                # ====== 超分辨率参数 ======
                {
                    "group": "超分辨率",
                    "params": [
                        {
                            "name": "scale_factor",
                            "type": "select",
                            "options": [
                                {"value": "2", "label": "2倍放大"},
                                {"value": "3", "label": "3倍放大"},
                                {"value": "4", "label": "4倍放大"}
                            ],
                            "default": "2",
                            "label": "放大倍数",
                            "description": "分辨率提升的倍数"
                        },
                        {
                            "name": "model_quality",
                            "type": "select",
                            "options": [
                                {"value": "fast", "label": "快速模式 (推荐)"},
                                {"value": "balanced", "label": "均衡模式"},
                                {"value": "quality", "label": "高质量模式"}
                            ],
                            "default": "fast",
                            "label": "质量模式",
                            "description": "处理速度与质量的平衡"
                        },
                        {
                            "name": "denoise_strength",
                            "type": "slider",
                            "min": 0.0,
                            "max": 1.0,
                            "default": 0.3,
                            "label": "降噪强度",
                            "description": "同时进行的降噪处理强度"
                        }
                    ]
                },
                # ====== 智能美颜参数 ======
                {
                    "group": "智能美颜",
                    "params": [
                        {
                            "name": "smoothing",
                            "type": "slider",
                            "min": 0.0,
                            "max": 1.0,
                            "default": 0.5,
                            "label": "磨皮强度",
                            "description": "皮肤磨皮光滑程度"
                        },
                        {
                            "name": "whitening",
                            "type": "slider",
                            "min": 0.0,
                            "max": 1.0,
                            "default": 0.3,
                            "label": "美白强度",
                            "description": "皮肤提亮程度"
                        },
                        {
                            "name": "face_slimming",
                            "type": "slider",
                            "min": 0.0,
                            "max": 1.0,
                            "default": 0.2,
                            "label": "瘦脸程度",
                            "description": "脸部轮廓调整幅度"
                        },
                        {
                            "name": "eye_enlargement",
                            "type": "slider",
                            "min": 0.0,
                            "max": 1.0,
                            "default": 0.15,
                            "label": "大眼效果",
                            "description": "眼睛放大程度"
                        },
                        {
                            "name": "natural_look",
                            "type": "checkbox",
                            "default": True,
                            "label": "自然效果",
                            "description": "启用更自然的美颜效果"
                        }
                    ]
                },
                # ====== 物体移除参数 ======
                {
                    "group": "物体移除",
                    "params": [
                        {
                            "name": "removal_mode",
                            "type": "select",
                            "options": [
                                {"value": "auto_detect", "label": "自动检测"},
                                {"value": "manual_select", "label": "手动选择"},
                                {"value": "brush_paint", "label": "笔刷涂抹"}
                            ],
                            "default": "auto_detect",
                            "label": "移除模式",
                            "description": "选择物体的方式"
                        },
                        {
                            "name": "fill_method",
                            "type": "select",
                            "options": [
                                {"value": "ai_inpainting", "label": "AI修复 (推荐)"},
                                {"value": "content_aware", "label": "内容感知填充"},
                                {"value": "blur_fill", "label": "模糊填充"},
                                {"value": "clone_stamp", "label": "仿制图章"}
                            ],
                            "default": "ai_inpainting",
                            "label": "填充方法",
                            "description": "移除区域的填充算法"
                        },
                        {
                            "name": "brush_size",
                            "type": "slider",
                            "min": 5,
                            "max": 100,
                            "default": 30,
                            "label": "笔刷大小",
                            "description": "手动选择时笔刷的大小"
                        },
                        {
                            "name": "edge_feathering",
                            "type": "slider",
                            "min": 0,
                            "max": 50,
                            "default": 10,
                            "label": "边缘羽化",
                            "description": "移除区域边缘的柔和过渡"
                        }
                    ]
                }
            ]
        }
    
    def apply_effect(self, frame_data: Any, params: Dict[str, Any]) -> Any:
        """
        应用AI特效到帧数据
        
        Args:
            frame_data: 输入的帧数据（numpy数组或图像路径）
            params: 特效参数字典，必须包含：
                - effect_type: 特效类型 (AIEffectType枚举值或字符串)
                - 其他参数根据特效类型而定
        
        Returns:
            Any: 处理后的帧数据
        """
        try:
            # 确定当前使用的特效类型
            effect_type_str = params.get('effect_type', '')
            
            if isinstance(effect_type_str, str):
                try:
                    self._current_effect = AIEffectType(effect_type_str)
                except ValueError:
                    raise ValueError(f"未知的特效类型: {effect_type_str}")
            elif isinstance(effect_type_str, AIEffectType):
                self._current_effect = effect_type_str
            else:
                raise ValueError("必须提供有效的 effect_type 参数")
            
            # 更新参数
            self._effect_params = params
            
            # 获取对应的特效处理器
            processor = self._effects.get(self._current_effect)
            if not processor:
                raise ValueError(f"特效处理器未初始化: {self._current_effect}")
            
            # 确保模型已加载
            if not self._models_loaded.get(self._current_effect, False):
                print(f"[AI特效] 正在加载 {self._current_effect.value} 模型...")
                success = processor.load_model()
                if success:
                    self._models_loaded[self._current_effect] = True
                    print(f"[AI特效] ✅ {self._current_effect.value} 模型加载完成")
                else:
                    raise RuntimeError(f"{self._current_effect.value} 模型加载失败")
            
            # 根据特效类型应用处理
            result = self._apply_specific_effect(processor, frame_data, params)
            self._last_error = ""

            return result
            
        except Exception as e:
            print(f"[AI特效] ❌ 应用特效失败: {str(e)}")
            import traceback
            traceback.print_exc()
            # 修复：此前失败只打印+原样返回输入帧，调用方（UI 线程）拿到"结果"后
            # 会走完成路径弹"✅ 特效应用完成"，用户根本不知道其实什么都没处理。
            # 这里记录到 _last_error，UI 侧据此判断是否要提示失败，同时仍返回
            # frame_data 保证批处理/流水线场景不会因为一帧失败而整体中断。
            self._last_error = str(e)
            return frame_data
    
    def _apply_specific_effect(self, processor: Any, frame_data: Any, params: Dict[str, Any]) -> Any:
        """根据特效类型调用具体的处理方法"""
        
        if self._current_effect == AIEffectType.STYLE_TRANSFER:
            style_name = params.get('style_name', 'cyberpunk')
            strength = params.get('style_strength', 0.8)
            preserve_color = params.get('preserve_color', True)
            
            return processor.apply(
                frame_data,
                style_name=style_name,
                strength=strength,
                preserve_color=preserve_color
            )
        
        elif self._current_effect == AIEffectType.BACKGROUND_REPLACE:
            bg_type = params.get('background_type', 'blur')
            bg_color = params.get('background_color', '#4A90E2')
            blur_strength = params.get('blur_strength', 15)
            edge_smooth = params.get('edge_smoothness', 5)
            
            return processor.replace_background(
                frame_data,
                background_type=bg_type,
                background_color=bg_color,
                blur_radius=blur_strength,
                edge_smoothness=edge_smooth
            )
        
        elif self._current_effect == AIEffectType.SUPER_RESOLUTION:
            scale = int(params.get('scale_factor', '2'))
            quality = params.get('model_quality', 'fast')
            denoise = params.get('denoise_strength', 0.3)
            
            return processor.enhance(
                frame_data,
                scale_factor=scale,
                quality_mode=quality,
                denoise_strength=denoise
            )
        
        elif self._current_effect == AIEffectType.BEAUTY_FILTER:
            smoothing = params.get('smoothing', 0.5)
            whitening = params.get('whitening', 0.3)
            face_slim = params.get('face_slimming', 0.2)
            eye_large = params.get('eye_enlargement', 0.15)
            natural = params.get('natural_look', True)
            
            return processor.beautify(
                frame_data,
                smoothing_level=smoothing,
                whitening_level=whitening,
                face_slimming=face_slim,
                eye_enlargement=eye_large,
                natural_look=natural
            )
        
        elif self._current_effect == AIEffectType.OBJECT_REMOVAL:
            mode = params.get('removal_mode', 'auto_detect')
            fill_method = params.get('fill_method', 'ai_inpainting')
            brush_size = params.get('brush_size', 30)
            edge_feather = params.get('edge_feathering', 10)
            
            return processor.remove_object(
                frame_data,
                mode=mode,
                fill_method=fill_method,
                brush_size=brush_size,
                edge_feathering=edge_feather
            )
        
        else:
            raise ValueError(f"不支持的特效类型: {self._current_effect}")
    
    def get_effect_params(self) -> Dict[str, Any]:
        """
        获取当前特效类型的参数定义
        
        Returns:
            Dict: 参数定义字典
        """
        if not self._current_effect:
            return {}
        
        param_definitions = {
            AIEffectType.STYLE_TRANSFER: {
                "effect_type": {
                    "type": "string",
                    "required": True,
                    "description": "特效类型标识"
                },
                "style_name": {
                    "type": "string",
                    "default": "cyberpunk",
                    "options": ["vangogh", "monet", "picasso", "cyberpunk", 
                               "anime", "oil_painting", "watercolor", "sketch"],
                    "description": "艺术风格名称"
                },
                "style_strength": {
                    "type": "float",
                    "range": [0.0, 1.0],
                    "default": 0.8,
                    "description": "风格化强度"
                },
                "preserve_color": {
                    "type": "bool",
                    "default": True,
                    "description": "是否保留原图颜色"
                }
            },
            
            AIEffectType.BACKGROUND_REPLACE: {
                "effect_type": {
                    "type": "string",
                    "required": True,
                    "description": "特效类型标识"
                },
                "background_type": {
                    "type": "string",
                    "default": "blur",
                    "options": ["solid_color", "blur", "image", "gradient", "transparent"],
                    "description": "背景类型"
                },
                "background_color": {
                    "type": "string",
                    "default": "#4A90E2",
                    "description": "背景颜色(HEX)"
                },
                "blur_strength": {
                    "type": "int",
                    "range": [0, 50],
                    "default": 15,
                    "description": "模糊半径"
                },
                "edge_smoothness": {
                    "type": "int",
                    "range": [0, 20],
                    "default": 5,
                    "description": "边缘平滑度"
                }
            },
            
            AIEffectType.SUPER_RESOLUTION: {
                "effect_type": {
                    "type": "string",
                    "required": True,
                    "description": "特效类型标识"
                },
                "scale_factor": {
                    "type": "int",
                    "options": [2, 3, 4],
                    "default": 2,
                    "description": "放大倍数"
                },
                "model_quality": {
                    "type": "string",
                    "default": "fast",
                    "options": ["fast", "balanced", "quality"],
                    "description": "质量模式"
                },
                "denoise_strength": {
                    "type": "float",
                    "range": [0.0, 1.0],
                    "default": 0.3,
                    "description": "降噪强度"
                }
            },
            
            AIEffectType.BEAUTY_FILTER: {
                "effect_type": {
                    "type": "string",
                    "required": True,
                    "description": "特效类型标识"
                },
                "smoothing": {
                    "type": "float",
                    "range": [0.0, 1.0],
                    "default": 0.5,
                    "description": "磨皮强度"
                },
                "whitening": {
                    "type": "float",
                    "range": [0.0, 1.0],
                    "default": 0.3,
                    "description": "美白强度"
                },
                "face_slimming": {
                    "type": "float",
                    "range": [0.0, 1.0],
                    "default": 0.2,
                    "description": "瘦脸程度"
                },
                "eye_enlargement": {
                    "type": "float",
                    "range": [0.0, 1.0],
                    "default": 0.15,
                    "description": "大眼效果"
                },
                "natural_look": {
                    "type": "bool",
                    "default": True,
                    "description": "自然效果开关"
                }
            },
            
            AIEffectType.OBJECT_REMOVAL: {
                "effect_type": {
                    "type": "string",
                    "required": True,
                    "description": "特效类型标识"
                },
                "removal_mode": {
                    "type": "string",
                    "default": "auto_detect",
                    "options": ["auto_detect", "manual_select", "brush_paint"],
                    "description": "移除模式"
                },
                "fill_method": {
                    "type": "string",
                    "default": "ai_inpainting",
                    "options": ["ai_inpainting", "content_aware", "blur_fill", "clone_stamp"],
                    "description": "填充方法"
                },
                "brush_size": {
                    "type": "int",
                    "range": [5, 100],
                    "default": 30,
                    "description": "笔刷大小"
                },
                "edge_feathering": {
                    "type": "int",
                    "range": [0, 50],
                    "default": 10,
                    "description": "边缘羽化程度"
                }
            }
        }
        
        return param_definitions.get(self._current_effect, {})
    
    def on_enable(self) -> None:
        """插件启用回调"""
        print("[AI特效] 插件已启用 🎨")
    
    def on_disable(self) -> None:
        """插件禁用回调"""
        print("[AI特效] 插件已禁用")
        # 可选：卸载所有模型以释放显存
        for effect_type in list(self._models_loaded.keys()):
            if self._models_loaded[effect_type]:
                try:
                    self._effects[effect_type].unload_model()
                    self._models_loaded[effect_type] = False
                except:
                    pass
    
    def validate(self) -> bool:
        """验证插件配置和环境依赖"""
        try:
            # 检查必要的依赖库
            required_libs = ['numpy', 'cv2', 'PIL']
            for lib in required_libs:
                __import__(lib.split('.')[0])
            
            # 检查PyTorch（可选但推荐）
            try:
                import torch
                print(f"[AI特效] PyTorch版本: {torch.__version__}, CUDA可用: {torch.cuda.is_available()}")
            except ImportError:
                print("[AI特效] ⚠️ PyTorch未安装，部分功能将使用CPU模式")
            
            return True
        except ImportError as e:
            print(f"[AI特效] ❌ 依赖检查失败: {e}")
            return False
    
    def get_supported_effects(self) -> List[Dict[str, str]]:
        """获取所有支持的特效列表"""
        effects_info = []
        for effect_type in AIEffectType:
            info = {
                "id": effect_type.value,
                "name": effect_type.name.replace('_', ' ').title(),
                "loaded": self._models_loaded.get(effect_type, False)
            }
            effects_info.append(info)
        return effects_info
    
    def preload_model(self, effect_type: str) -> bool:
        """
        预加载指定效果的模型
        
        Args:
            effect_type: 特效类型字符串
        
        Returns:
            bool: 是否加载成功
        """
        try:
            et = AIEffectType(effect_type)
            if et in self._effects and not self._models_loaded.get(et, False):
                success = self._effects[et].load_model()
                if success:
                    self._models_loaded[et] = True
                return success
            return True
        except:
            return False
    
    def register_callback(self, event: str, callback: Callable) -> None:
        """
        注册事件回调函数
        
        Args:
            event: 事件名称 ('on_progress', 'on_complete', 'on_error')
            callback: 回调函数
        """
        self._callbacks[event] = callback


# 便捷访问函数
def get_plugin_instance() -> Plugin:
    """获取插件单例实例"""
    return Plugin()


__all__ = ['Plugin', 'AIEffectsWidget', 'AIEffectType', 'get_plugin_instance']
