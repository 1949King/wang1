import os
import json
import time
from datetime import datetime
from typing import Dict, List, Optional, Any


class EffectManager:
    """
    特效管理系统
    负责特效的管理、应用、参数调整等功能
    """
    
    def __init__(self):
        """初始化特效管理器"""
        self.effects_dir = "effects"
        self.effects_db = os.path.join(self.effects_dir, "effects.json")
        self.effects = {}
        
        # 创建目录
        os.makedirs(self.effects_dir, exist_ok=True)
        
        # 加载特效数据库
        self._load_effects()
        
        # 内置特效
        self._init_builtin_effects()
    
    def _load_effects(self):
        """加载特效数据库"""
        if os.path.exists(self.effects_db):
            try:
                with open(self.effects_db, "r", encoding="utf-8") as f:
                    self.effects = json.load(f)
            except Exception as e:
                print(f"加载特效数据库失败: {e}")
                self.effects = {}
    
    def _save_effects(self):
        """保存特效数据库"""
        try:
            with open(self.effects_db, "w", encoding="utf-8") as f:
                json.dump(self.effects, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"保存特效数据库失败: {e}")
            return False
    
    def _init_builtin_effects(self):
        """初始化内置特效"""
        builtin_effects = {
            "brightness": {
                "name": "亮度",
                "category": "color",
                "description": "调整视频亮度",
                "parameters": {
                    "brightness": {
                        "type": "float",
                        "default": 1.0,
                        "min": 0.0,
                        "max": 2.0,
                        "step": 0.1
                    }
                }
            },
            "contrast": {
                "name": "对比度",
                "category": "color",
                "description": "调整视频对比度",
                "parameters": {
                    "contrast": {
                        "type": "float",
                        "default": 1.0,
                        "min": 0.0,
                        "max": 3.0,
                        "step": 0.1
                    }
                }
            },
            "saturation": {
                "name": "饱和度",
                "category": "color",
                "description": "调整视频饱和度",
                "parameters": {
                    "saturation": {
                        "type": "float",
                        "default": 1.0,
                        "min": 0.0,
                        "max": 3.0,
                        "step": 0.1
                    }
                }
            },
            "blur": {
                "name": "模糊",
                "category": "filter",
                "description": "添加模糊效果",
                "parameters": {
                    "radius": {
                        "type": "float",
                        "default": 5.0,
                        "min": 0.0,
                        "max": 50.0,
                        "step": 1.0
                    }
                }
            },
            "sharpen": {
                "name": "锐化",
                "category": "filter",
                "description": "添加锐化效果",
                "parameters": {
                    "amount": {
                        "type": "float",
                        "default": 1.0,
                        "min": 0.0,
                        "max": 5.0,
                        "step": 0.1
                    }
                }
            },
            "grayscale": {
                "name": "黑白",
                "category": "color",
                "description": "将视频转换为黑白",
                "parameters": {}
            },
            "sepia": {
                "name": "复古",
                "category": "color",
                "description": "添加复古效果",
                "parameters": {
                    "intensity": {
                        "type": "float",
                        "default": 1.0,
                        "min": 0.0,
                        "max": 1.0,
                        "step": 0.1
                    }
                }
            },
            "vignette": {
                "name": "暗角",
                "category": "filter",
                "description": "添加暗角效果",
                "parameters": {
                    "size": {
                        "type": "float",
                        "default": 0.5,
                        "min": 0.0,
                        "max": 1.0,
                        "step": 0.05
                    },
                    "strength": {
                        "type": "float",
                        "default": 0.5,
                        "min": 0.0,
                        "max": 1.0,
                        "step": 0.05
                    }
                }
            }
        }
        
        # 添加内置特效到数据库
        for effect_id, effect_info in builtin_effects.items():
            if effect_id not in self.effects:
                self.effects[effect_id] = effect_info
        
        # 保存数据库
        self._save_effects()
    
    def get_effect(self, effect_id: str) -> Optional[Dict[str, Any]]:
        """
        获取特效信息
        
        Args:
            effect_id: 特效ID
            
        Returns:
            特效信息字典，如果特效不存在则返回None
        """
        return self.effects.get(effect_id)
    
    def list_effects(self, category: str = None) -> List[Dict[str, Any]]:
        """
        列出特效
        
        Args:
            category: 特效类别，如果为None则列出所有类别
            
        Returns:
            特效列表
        """
        effects = []
        
        for effect_id, effect_info in self.effects.items():
            if category and effect_info.get("category") != category:
                continue
            effects.append({
                "id": effect_id,
                **effect_info
            })
        
        # 按名称排序
        effects.sort(key=lambda x: x.get("name", ""))
        return effects
    
    def get_categories(self) -> List[str]:
        """
        获取特效类别列表
        
        Returns:
            类别列表
        """
        categories = set()
        for effect_info in self.effects.values():
            category = effect_info.get("category")
            if category:
                categories.add(category)
        return list(categories)
    
    def create_effect_instance(self, effect_id: str, parameters: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        创建特效实例
        
        Args:
            effect_id: 特效ID
            parameters: 特效参数
            
        Returns:
            特效实例字典
        """
        effect_info = self.get_effect(effect_id)
        if not effect_info:
            raise ValueError(f"特效不存在: {effect_id}")
        
        # 使用默认参数
        default_params = {}
        for param_name, param_info in effect_info.get("parameters", {}).items():
            default_params[param_name] = param_info.get("default")
        
        # 更新为用户提供的参数
        if parameters:
            default_params.update(parameters)
        
        # 创建特效实例
        instance_id = f"effect_instance_{int(time.time())}"
        effect_instance = {
            "id": instance_id,
            "effect_id": effect_id,
            "name": effect_info["name"],
            "parameters": default_params,
            "created_at": datetime.now().isoformat()
        }
        
        return effect_instance
    
    def apply_effect(self, clip_id: str, effect_instance: Dict[str, Any]) -> bool:
        """
        应用特效到片段：写入 preview 可用参数，供 Editor 同步。
        """
        if not hasattr(self, "_applied_effects"):
            self._applied_effects = {}
        params = dict(effect_instance.get("parameters") or {})
        name = str(effect_instance.get("name") or effect_instance.get("effect_id") or "effect")
        # 映射常见参数到 PreviewManager 键
        preview = {}
        for k in ("blur", "sharpen", "vignette", "brightness", "contrast",
                  "saturation", "hue", "opacity", "scale"):
            if k in params:
                preview[k] = params[k]
        # 名称启发式
        low = name.lower()
        if "blur" in low or "模糊" in name:
            preview.setdefault("blur", float(params.get("intensity", params.get("radius", 3)) or 3))
        if "sharp" in low or "锐化" in name:
            preview.setdefault("sharpen", float(params.get("intensity", 1) or 1))
        if "vignette" in low or "暗角" in name:
            preview.setdefault("vignette", float(params.get("intensity", 0.5) or 0.5))
        effect_instance["_preview_params"] = preview
        self._applied_effects.setdefault(str(clip_id), []).append(effect_instance)
        print(f"应用特效 {name} 到片段 {clip_id}: {preview}")
        return True
    
    def update_effect_parameters(self, effect_instance: Dict[str, Any], **parameters) -> Dict[str, Any]:
        """
        更新特效参数
        
        Args:
            effect_instance: 特效实例
            **parameters: 要更新的参数
            
        Returns:
            更新后的特效实例
        """
        effect_instance["parameters"].update(parameters)
        effect_instance["updated_at"] = datetime.now().isoformat()
        return effect_instance
    
    def remove_effect(self, clip_id: str, effect_instance_id: str) -> bool:
        """
        从片段中移除特效
        
        Args:
            clip_id: 片段ID
            effect_instance_id: 特效实例ID
            
        Returns:
            是否移除成功
        """
        # 这里需要与时间线管理系统集成
        # 暂时返回True，表示移除成功
        print(f"从片段 {clip_id} 移除特效实例 {effect_instance_id}")
        return True
    
    def save_effect_preset(self, name: str, effect_id: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        保存特效预设
        
        Args:
            name: 预设名称
            effect_id: 特效ID
            parameters: 特效参数
            
        Returns:
            预设信息字典
        """
        preset_id = f"preset_{int(time.time())}"
        preset = {
            "id": preset_id,
            "name": name,
            "effect_id": effect_id,
            "parameters": parameters,
            "created_at": datetime.now().isoformat()
        }
        
        # 保存预设到数据库
        if "presets" not in self.effects:
            self.effects["presets"] = {}
        self.effects["presets"][preset_id] = preset
        
        self._save_effects()
        return preset
    
    def load_effect_preset(self, preset_id: str) -> Optional[Dict[str, Any]]:
        """
        加载特效预设
        
        Args:
            preset_id: 预设ID
            
        Returns:
            预设信息字典，如果预设不存在则返回None
        """
        presets = self.effects.get("presets", {})
        return presets.get(preset_id)
    
    def list_effect_presets(self, effect_id: str = None) -> List[Dict[str, Any]]:
        """
        列出特效预设
        
        Args:
            effect_id: 特效ID，如果为None则列出所有预设
            
        Returns:
            预设列表
        """
        presets = []
        for preset_id, preset_info in self.effects.get("presets", {}).items():
            if effect_id and preset_info.get("effect_id") != effect_id:
                continue
            presets.append({
                "id": preset_id,
                **preset_info
            })
        
        # 按名称排序
        presets.sort(key=lambda x: x.get("name", ""))
        return presets


# 全局特效管理器实例
effect_manager = EffectManager()
