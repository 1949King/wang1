import os
import json
import time
from datetime import datetime
from typing import Dict, List, Optional, Any


class TransitionManager:
    """
    转场管理系统
    负责转场的管理、应用、参数调整等功能
    """
    
    def __init__(self):
        """初始化转场管理器"""
        self.transitions_dir = "transitions"
        self.transitions_db = os.path.join(self.transitions_dir, "transitions.json")
        self.transitions = {}
        
        # 创建目录
        os.makedirs(self.transitions_dir, exist_ok=True)
        
        # 加载转场数据库
        self._load_transitions()
        
        # 内置转场
        self._init_builtin_transitions()
    
    def _load_transitions(self):
        """加载转场数据库"""
        if os.path.exists(self.transitions_db):
            try:
                with open(self.transitions_db, "r", encoding="utf-8") as f:
                    self.transitions = json.load(f)
            except Exception as e:
                print(f"加载转场数据库失败: {e}")
                self.transitions = {}
    
    def _save_transitions(self):
        """保存转场数据库"""
        try:
            with open(self.transitions_db, "w", encoding="utf-8") as f:
                json.dump(self.transitions, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"保存转场数据库失败: {e}")
            return False
    
    def _init_builtin_transitions(self):
        """初始化内置转场"""
        builtin_transitions = {
            "fade": {
                "name": "淡入淡出",
                "category": "basic",
                "description": "简单的淡入淡出效果",
                "parameters": {
                    "duration": {
                        "type": "float",
                        "default": 1.0,
                        "min": 0.1,
                        "max": 5.0,
                        "step": 0.1
                    }
                }
            },
            "slide": {
                "name": "滑动",
                "category": "basic",
                "description": "滑动转场效果",
                "parameters": {
                    "duration": {
                        "type": "float",
                        "default": 1.0,
                        "min": 0.1,
                        "max": 5.0,
                        "step": 0.1
                    },
                    "direction": {
                        "type": "string",
                        "default": "left",
                        "options": ["left", "right", "up", "down"]
                    }
                }
            },
            "zoom": {
                "name": "缩放",
                "category": "basic",
                "description": "缩放转场效果",
                "parameters": {
                    "duration": {
                        "type": "float",
                        "default": 1.0,
                        "min": 0.1,
                        "max": 5.0,
                        "step": 0.1
                    },
                    "direction": {
                        "type": "string",
                        "default": "in",
                        "options": ["in", "out"]
                    }
                }
            },
            "wipe": {
                "name": "擦除",
                "category": "basic",
                "description": "擦除转场效果",
                "parameters": {
                    "duration": {
                        "type": "float",
                        "default": 1.0,
                        "min": 0.1,
                        "max": 5.0,
                        "step": 0.1
                    },
                    "direction": {
                        "type": "string",
                        "default": "left",
                        "options": ["left", "right", "up", "down", "diagonal"]
                    }
                }
            },
            "dissolve": {
                "name": "溶解",
                "category": "basic",
                "description": "溶解转场效果",
                "parameters": {
                    "duration": {
                        "type": "float",
                        "default": 1.0,
                        "min": 0.1,
                        "max": 5.0,
                        "step": 0.1
                    }
                }
            },
            "glitch": {
                "name": " glitch",
                "category": "special",
                "description": "故障艺术转场效果",
                "parameters": {
                    "duration": {
                        "type": "float",
                        "default": 0.5,
                        "min": 0.1,
                        "max": 2.0,
                        "step": 0.1
                    },
                    "intensity": {
                        "type": "float",
                        "default": 1.0,
                        "min": 0.1,
                        "max": 3.0,
                        "step": 0.1
                    }
                }
            },
            "flip": {
                "name": "翻转",
                "category": "special",
                "description": "翻转转场效果",
                "parameters": {
                    "duration": {
                        "type": "float",
                        "default": 1.0,
                        "min": 0.1,
                        "max": 3.0,
                        "step": 0.1
                    },
                    "axis": {
                        "type": "string",
                        "default": "x",
                        "options": ["x", "y", "z"]
                    }
                }
            },
            "spin": {
                "name": "旋转",
                "category": "special",
                "description": "旋转转场效果",
                "parameters": {
                    "duration": {
                        "type": "float",
                        "default": 1.0,
                        "min": 0.1,
                        "max": 3.0,
                        "step": 0.1
                    },
                    "degrees": {
                        "type": "float",
                        "default": 360.0,
                        "min": 90.0,
                        "max": 720.0,
                        "step": 90.0
                    }
                }
            }
        }
        
        # 添加内置转场到数据库
        for transition_id, transition_info in builtin_transitions.items():
            if transition_id not in self.transitions:
                self.transitions[transition_id] = transition_info
        
        # 保存数据库
        self._save_transitions()
    
    def get_transition(self, transition_id: str) -> Optional[Dict[str, Any]]:
        """
        获取转场信息
        
        Args:
            transition_id: 转场ID
            
        Returns:
            转场信息字典，如果转场不存在则返回None
        """
        return self.transitions.get(transition_id)
    
    def list_transitions(self, category: str = None) -> List[Dict[str, Any]]:
        """
        列出转场
        
        Args:
            category: 转场类别，如果为None则列出所有类别
            
        Returns:
            转场列表
        """
        transitions = []
        
        for transition_id, transition_info in self.transitions.items():
            if category and transition_info.get("category") != category:
                continue
            transitions.append({
                "id": transition_id,
                **transition_info
            })
        
        # 按名称排序
        transitions.sort(key=lambda x: x.get("name", ""))
        return transitions
    
    def get_categories(self) -> List[str]:
        """
        获取转场类别列表
        
        Returns:
            类别列表
        """
        categories = set()
        for transition_info in self.transitions.values():
            category = transition_info.get("category")
            if category:
                categories.add(category)
        return list(categories)
    
    def create_transition_instance(self, transition_id: str, parameters: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        创建转场实例
        
        Args:
            transition_id: 转场ID
            parameters: 转场参数
            
        Returns:
            转场实例字典
        """
        transition_info = self.get_transition(transition_id)
        if not transition_info:
            raise ValueError(f"转场不存在: {transition_id}")
        
        # 使用默认参数
        default_params = {}
        for param_name, param_info in transition_info.get("parameters", {}).items():
            default_params[param_name] = param_info.get("default")
        
        # 更新为用户提供的参数
        if parameters:
            default_params.update(parameters)
        
        # 创建转场实例
        instance_id = f"transition_instance_{int(time.time())}"
        transition_instance = {
            "id": instance_id,
            "transition_id": transition_id,
            "name": transition_info["name"],
            "parameters": default_params,
            "created_at": datetime.now().isoformat()
        }
        
        return transition_instance
    
    def apply_transition(self, clip_id1: str, clip_id2: str, transition_instance: Dict[str, Any]) -> bool:
        """
        在两个片段之间应用转场
        
        Args:
            clip_id1: 第一个片段ID
            clip_id2: 第二个片段ID
            transition_instance: 转场实例
        """
        transition_name = transition_instance.get('name', 'fade')
        try:
            plugin_map = {
                'fade': 'transition_fade', 'slide': 'transition_slide',
                'zoom': 'transition_zoom', 'wipe': 'transition_wipe',
                'dissolve': 'transition_dissolve', 'glitch': 'transition_glitch',
                'flip': 'transition_flip', 'spin': 'transition_spin',
            }
            module_name = plugin_map.get(transition_name)
            if module_name:
                __import__(f'plugins.{module_name}', fromlist=['Plugin'])
            print(f"应用转场 {transition_name} 在片段 {clip_id1} 和 {clip_id2} 之间")
            return True
        except Exception as e:
            print(f"转场应用失败: {e}")
            return False

    def update_transition_parameters(self, transition_instance: Dict[str, Any], **parameters) -> Dict[str, Any]:
        """
        更新转场参数
        
        Args:
            transition_instance: 转场实例
            **parameters: 要更新的参数
            
        Returns:
            更新后的转场实例
        """
        transition_instance["parameters"].update(parameters)
        transition_instance["updated_at"] = datetime.now().isoformat()
        return transition_instance
    
    def remove_transition(self, clip_id1: str, clip_id2: str, transition_instance_id: str) -> bool:
        """
        移除转场
        
        Args:
            clip_id1: 第一个片段ID
            clip_id2: 第二个片段ID
            transition_instance_id: 转场实例ID
            
        Returns:
            是否移除成功
        """
        # 这里需要与时间线管理系统集成
        # 暂时返回True，表示移除成功
        print(f"从片段 {clip_id1} 和 {clip_id2} 之间移除转场实例 {transition_instance_id}")
        return True
    
    def save_transition_preset(self, name: str, transition_id: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        保存转场预设
        
        Args:
            name: 预设名称
            transition_id: 转场ID
            parameters: 转场参数
            
        Returns:
            预设信息字典
        """
        preset_id = f"transition_preset_{int(time.time())}"
        preset = {
            "id": preset_id,
            "name": name,
            "transition_id": transition_id,
            "parameters": parameters,
            "created_at": datetime.now().isoformat()
        }
        
        # 保存预设到数据库
        if "presets" not in self.transitions:
            self.transitions["presets"] = {}
        self.transitions["presets"][preset_id] = preset
        
        self._save_transitions()
        return preset
    
    def load_transition_preset(self, preset_id: str) -> Optional[Dict[str, Any]]:
        """
        加载转场预设
        
        Args:
            preset_id: 预设ID
            
        Returns:
            预设信息字典，如果预设不存在则返回None
        """
        presets = self.transitions.get("presets", {})
        return presets.get(preset_id)
    
    def list_transition_presets(self, transition_id: str = None) -> List[Dict[str, Any]]:
        """
        列出转场预设
        
        Args:
            transition_id: 转场ID，如果为None则列出所有预设
            
        Returns:
            预设列表
        """
        presets = []
        for preset_id, preset_info in self.transitions.get("presets", {}).items():
            if transition_id and preset_info.get("transition_id") != transition_id:
                continue
            presets.append({
                "id": preset_id,
                **preset_info
            })
        
        # 按名称排序
        presets.sort(key=lambda x: x.get("name", ""))
        return presets


# 全局转场管理器实例
transition_manager = TransitionManager()


def get_transition_manager() -> TransitionManager:
    """供 EditorModule 懒加载使用。"""
    return transition_manager
