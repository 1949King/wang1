"""
插件热加载机制测试
测试插件发现、加载、卸载、热加载等功能
"""

import os
import sys
import tempfile
import shutil
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.plugin_loader import (
    PluginType, PluginCategory, PluginState, PluginInfo,
    IPlugin, IEffectPlugin, ITransitionPlugin, IFilterPlugin,
    PluginLoader, PluginHotLoader, PluginRegistry
)
from app.core.plugin_hotloader import PluginManager, PluginContext, PluginFactory


class TestEffectPlugin(IEffectPlugin):
    """测试特效插件"""
    
    @property
    def plugin_info(self) -> PluginInfo:
        return PluginInfo(
            id="test_effect",
            name="测试特效",
            version="1.0.0",
            description="用于测试的特效插件",
            author="Test",
            plugin_type=PluginType.EFFECT,
            category=PluginCategory.GENERAL,
            file_path=__file__,
            tags=["test", "effect"]
        )
    
    def initialize(self, context: dict) -> bool:
        print(f"初始化插件: {self.plugin_info.name}")
        return True
    
    def shutdown(self) -> bool:
        print(f"关闭插件: {self.plugin_info.name}")
        return True
    
    def get_ui_config(self) -> dict:
        return {
            "name": self.plugin_info.name,
            "params": [
                {
                    "name": "intensity",
                    "type": "slider",
                    "min": 0,
                    "max": 100,
                    "default": 50,
                    "label": "强度"
                }
            ]
        }
    
    def apply_effect(self, frame_data, params: dict):
        print(f"应用特效: {self.plugin_info.name}, 参数: {params}")
        return frame_data
    
    def get_effect_params(self) -> dict:
        return {
            "intensity": {
                "type": "float",
                "min": 0.0,
                "max": 1.0,
                "default": 0.5,
                "description": "特效强度"
            }
        }


class TestTransitionPlugin(ITransitionPlugin):
    """测试转场插件"""
    
    @property
    def plugin_info(self) -> PluginInfo:
        return PluginInfo(
            id="test_transition",
            name="测试转场",
            version="1.0.0",
            description="用于测试的转场插件",
            author="Test",
            plugin_type=PluginType.TRANSITION,
            category=PluginCategory.GENERAL,
            file_path=__file__,
            tags=["test", "transition"]
        )
    
    def initialize(self, context: dict) -> bool:
        print(f"初始化插件: {self.plugin_info.name}")
        return True
    
    def shutdown(self) -> bool:
        print(f"关闭插件: {self.plugin_info.name}")
        return True
    
    def get_ui_config(self) -> dict:
        return {
            "name": self.plugin_info.name,
            "params": [
                {
                    "name": "duration",
                    "type": "slider",
                    "min": 0.1,
                    "max": 5.0,
                    "default": 1.0,
                    "label": "持续时间"
                }
            ]
        }
    
    def apply_transition(self, from_frame, to_frame, progress: float, params: dict):
        print(f"应用转场: {self.plugin_info.name}, 进度: {progress}, 参数: {params}")
        return from_frame
    
    def get_transition_params(self) -> dict:
        return {
            "duration": {
                "type": "float",
                "min": 0.1,
                "max": 5.0,
                "default": 1.0,
                "description": "转场持续时间"
            }
        }


class TestFilterPlugin(IFilterPlugin):
    """测试滤镜插件"""
    
    @property
    def plugin_info(self) -> PluginInfo:
        return PluginInfo(
            id="test_filter",
            name="测试滤镜",
            version="1.0.0",
            description="用于测试的滤镜插件",
            author="Test",
            plugin_type=PluginType.FILTER,
            category=PluginCategory.GENERAL,
            file_path=__file__,
            tags=["test", "filter"]
        )
    
    def initialize(self, context: dict) -> bool:
        print(f"初始化插件: {self.plugin_info.name}")
        return True
    
    def shutdown(self) -> bool:
        print(f"关闭插件: {self.plugin_info.name}")
        return True
    
    def get_ui_config(self) -> dict:
        return {
            "name": self.plugin_info.name,
            "params": [
                {
                    "name": "brightness",
                    "type": "slider",
                    "min": -100,
                    "max": 100,
                    "default": 0,
                    "label": "亮度"
                }
            ]
        }
    
    def apply_filter(self, frame_data, params: dict):
        print(f"应用滤镜: {self.plugin_info.name}, 参数: {params}")
        return frame_data
    
    def get_filter_params(self) -> dict:
        return {
            "brightness": {
                "type": "int",
                "min": -100,
                "max": 100,
                "default": 0,
                "description": "亮度调整"
            }
        }


def test_plugin_discovery():
    """测试插件发现"""
    print("\n" + "="*50)
    print("测试插件发现")
    print("="*50)
    
    loader = PluginLoader()
    
    with tempfile.TemporaryDirectory() as temp_dir:
        loader.add_plugin_dir(temp_dir)
        
        plugin_code = '''
from app.core.plugin_loader import IEffectPlugin, PluginInfo, PluginType, PluginCategory

class Plugin(IEffectPlugin):
    @property
    def plugin_info(self):
        return PluginInfo(
            id="discovery_test",
            name="发现测试插件",
            version="1.0.0",
            description="测试插件发现功能",
            author="Test",
            plugin_type=PluginType.EFFECT,
            category=PluginCategory.GENERAL,
            file_path=__file__
        )
    
    def initialize(self, context):
        return True
    
    def shutdown(self):
        return True
    
    def get_ui_config(self):
        return {}
    
    def apply_effect(self, frame_data, params):
        return frame_data
    
    def get_effect_params(self):
        return {}
'''
        
        test_file = os.path.join(temp_dir, "test_plugin.py")
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write(plugin_code)
        
        discovered = loader.discover_plugins()
        
        print(f"发现插件数量: {len(discovered)}")
        for plugin_info in discovered:
            print(f"  - {plugin_info.name} ({plugin_info.id})")
        
        assert len(discovered) == 1
        assert discovered[0].id == "discovery_test"
        
        print("✓ 插件发现测试通过")


def test_plugin_loading():
    """测试插件加载"""
    print("\n" + "="*50)
    print("测试插件加载")
    print("="*50)
    
    loader = PluginLoader()
    
    with tempfile.TemporaryDirectory() as temp_dir:
        loader.add_plugin_dir(temp_dir)
        
        plugin_code = '''
from app.core.plugin_loader import IEffectPlugin, PluginInfo, PluginType, PluginCategory

class Plugin(IEffectPlugin):
    @property
    def plugin_info(self):
        return PluginInfo(
            id="loading_test",
            name="加载测试插件",
            version="1.0.0",
            description="测试插件加载功能",
            author="Test",
            plugin_type=PluginType.EFFECT,
            category=PluginCategory.GENERAL,
            file_path=__file__
        )
    
    def initialize(self, context):
        print("插件初始化")
        return True
    
    def shutdown(self):
        print("插件关闭")
        return True
    
    def get_ui_config(self):
        return {}
    
    def apply_effect(self, frame_data, params):
        return frame_data
    
    def get_effect_params(self):
        return {}
'''
        
        test_file = os.path.join(temp_dir, "test_plugin.py")
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write(plugin_code)
        
        discovered = loader.discover_plugins()
        assert len(discovered) == 1
        
        plugin_info = discovered[0]
        loader._plugin_infos[plugin_info.id] = plugin_info
        
        print(f"加载插件: {plugin_info.name}")
        loaded = loader.load_plugin(plugin_info.id)
        
        assert loaded == True
        assert loader.get_plugin_state(plugin_info.id) == PluginState.LOADED
        
        plugin = loader.get_plugin(plugin_info.id)
        assert plugin is not None
        assert isinstance(plugin, IEffectPlugin)
        
        print(f"插件状态: {loader.get_plugin_state(plugin_info.id)}")
        print("✓ 插件加载测试通过")


def test_plugin_hot_reload():
    """测试插件热加载"""
    print("\n" + "="*50)
    print("测试插件热加载")
    print("="*50)
    
    loader = PluginLoader()
    hot_loader = PluginHotLoader(loader)
    
    with tempfile.TemporaryDirectory() as temp_dir:
        loader.add_plugin_dir(temp_dir)
        
        plugin_code = '''
from app.core.plugin_loader import IEffectPlugin, PluginInfo, PluginType, PluginCategory

class Plugin(IEffectPlugin):
    @property
    def plugin_info(self):
        return PluginInfo(
            id="hot_reload_test",
            name="热加载测试插件",
            version="1.0.0",
            description="测试插件热加载功能",
            author="Test",
            plugin_type=PluginType.EFFECT,
            category=PluginCategory.GENERAL,
            file_path=__file__
        )
    
    def initialize(self, context):
        return True
    
    def shutdown(self):
        return True
    
    def get_ui_config(self):
        return {}
    
    def apply_effect(self, frame_data, params):
        return frame_data
    
    def get_effect_params(self):
        return {}
'''
        
        test_file = os.path.join(temp_dir, "test_plugin.py")
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write(plugin_code)
        
        discovered = loader.discover_plugins()
        assert len(discovered) == 1
        
        plugin_info = discovered[0]
        loader._plugin_infos[plugin_info.id] = plugin_info
        
        print(f"加载插件: {plugin_info.name}")
        loaded = loader.load_plugin(plugin_info.id)
        assert loaded == True
        
        print(f"修改插件文件...")
        modified_code = plugin_code.replace("1.0.0", "2.0.0")
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write(modified_code)
        
        print(f"热加载插件...")
        reloaded = loader.reload_plugin(plugin_info.id)
        assert reloaded == True
        
        print("✓ 插件热加载测试通过")


def test_plugin_registry():
    """测试插件注册表"""
    print("\n" + "="*50)
    print("测试插件注册表")
    print("="*50)
    
    registry = PluginRegistry()
    
    plugin_info1 = PluginInfo(
        id="registry_test_1",
        name="注册表测试1",
        version="1.0.0",
        description="测试注册表功能",
        author="Test",
        plugin_type=PluginType.EFFECT,
        category=PluginCategory.GENERAL,
        file_path="test1.py",
        tags=["test", "effect"]
    )
    
    plugin_info2 = PluginInfo(
        id="registry_test_2",
        name="注册表测试2",
        version="1.0.0",
        description="测试注册表功能",
        author="Test",
        plugin_type=PluginType.TRANSITION,
        category=PluginCategory.SUSPENSE,
        file_path="test2.py",
        tags=["test", "transition", "suspense"]
    )
    
    print(f"注册插件1: {plugin_info1.name}")
    registered1 = registry.register(plugin_info1)
    assert registered1 == True
    
    print(f"注册插件2: {plugin_info2.name}")
    registered2 = registry.register(plugin_info2)
    assert registered2 == True
    
    print(f"获取插件: {plugin_info1.id}")
    retrieved = registry.get(plugin_info1.id)
    assert retrieved is not None
    assert retrieved.name == plugin_info1.name
    
    print(f"按类型查询: {PluginType.EFFECT}")
    effect_plugins = registry.get_by_type(PluginType.EFFECT)
    assert len(effect_plugins) == 1
    assert effect_plugins[0].id == plugin_info1.id
    
    print(f"按分类查询: {PluginCategory.SUSPENSE}")
    suspense_plugins = registry.get_by_category(PluginCategory.SUSPENSE)
    assert len(suspense_plugins) == 1
    assert suspense_plugins[0].id == plugin_info2.id
    
    print(f"按标签查询: test")
    test_plugins = registry.get_by_tag("test")
    assert len(test_plugins) == 2
    
    print(f"注销插件: {plugin_info1.id}")
    unregistered = registry.unregister(plugin_info1.id)
    assert unregistered == True
    
    print("✓ 插件注册表测试通过")


def test_plugin_manager():
    """测试插件管理器"""
    print("\n" + "="*50)
    print("测试插件管理器")
    print("="*50)
    
    manager = PluginManager()
    
    with tempfile.TemporaryDirectory() as temp_dir:
        manager.add_plugin_dir(temp_dir)
        
        plugin_code = '''
from app.core.plugin_loader import IEffectPlugin, PluginInfo, PluginType, PluginCategory

class Plugin(IEffectPlugin):
    @property
    def plugin_info(self):
        return PluginInfo(
            id="manager_test",
            name="管理器测试插件",
            version="1.0.0",
            description="测试插件管理器功能",
            author="Test",
            plugin_type=PluginType.EFFECT,
            category=PluginCategory.GENERAL,
            file_path=__file__
        )
    
    def initialize(self, context):
        return True
    
    def shutdown(self):
        return True
    
    def get_ui_config(self):
        return {}
    
    def apply_effect(self, frame_data, params):
        return frame_data
    
    def get_effect_params(self):
        return {}
'''
        
        test_file = os.path.join(temp_dir, "test_plugin.py")
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write(plugin_code)
        
        print(f"发现插件...")
        discovered = manager.discover_plugins()
        assert len(discovered) == 1
        
        plugin_info = discovered[0]
        print(f"加载插件: {plugin_info.name}")
        loaded = manager.load_plugin(plugin_info.id)
        assert loaded == True
        
        print(f"获取插件状态: {manager.get_plugin_state(plugin_info.id)}")
        assert manager.get_plugin_state(plugin_info.id) == PluginState.INITIALIZED
        
        print(f"获取插件实例...")
        plugin = manager.get_plugin(plugin_info.id)
        assert plugin is not None
        assert isinstance(plugin, IEffectPlugin)
        
        print(f"应用特效...")
        result = manager.apply_effect(plugin_info.id, "test_frame", {"intensity": 0.5})
        assert result is not None
        
        print(f"获取UI配置...")
        ui_config = manager.get_plugin_ui_config(plugin_info.id)
        assert ui_config is not None
        
        print(f"获取统计信息...")
        stats = manager.get_statistics()
        assert stats["total_plugins"] >= 1
        assert stats["loaded_plugins"] >= 1
        
        print(f"卸载插件...")
        unloaded = manager.unload_plugin(plugin_info.id)
        assert unloaded == True
        
        print("✓ 插件管理器测试通过")


def test_plugin_factory():
    """测试插件工厂"""
    print("\n" + "="*50)
    print("测试插件工厂")
    print("="*50)
    
    effect_info = PluginFactory.create_effect_plugin(
        name="工厂测试特效",
        version="1.0.0",
        description="工厂创建的特效插件",
        author="Test",
        category=PluginCategory.COUNTERATTACK,
        file_path="effect.py"
    )
    
    print(f"创建特效插件: {effect_info.name}")
    assert effect_info.id == "effect_工厂测试特效"
    assert effect_info.plugin_type == PluginType.EFFECT
    assert effect_info.category == PluginCategory.COUNTERATTACK
    
    transition_info = PluginFactory.create_transition_plugin(
        name="工厂测试转场",
        version="1.0.0",
        description="工厂创建的转场插件",
        author="Test",
        category=PluginCategory.EMOTION,
        file_path="transition.py"
    )
    
    print(f"创建转场插件: {transition_info.name}")
    assert transition_info.id == "transition_工厂测试转场"
    assert transition_info.plugin_type == PluginType.TRANSITION
    assert transition_info.category == PluginCategory.EMOTION
    
    filter_info = PluginFactory.create_filter_plugin(
        name="工厂测试滤镜",
        version="1.0.0",
        description="工厂创建的滤镜插件",
        author="Test",
        category=PluginCategory.SUSPENSE,
        file_path="filter.py"
    )
    
    print(f"创建滤镜插件: {filter_info.name}")
    assert filter_info.id == "filter_工厂测试滤镜"
    assert filter_info.plugin_type == PluginType.FILTER
    assert filter_info.category == PluginCategory.SUSPENSE
    
    print("✓ 插件工厂测试通过")


def test_plugin_context():
    """测试插件上下文"""
    print("\n" + "="*50)
    print("测试插件上下文")
    print("="*50)
    
    context = PluginContext()
    
    print(f"设置上下文值...")
    context.set("key1", "value1")
    context.set("key2", 123)
    context.set("key3", {"nested": "data"})
    
    print(f"获取上下文值...")
    assert context.get("key1") == "value1"
    assert context.get("key2") == 123
    assert context.get("key3") == {"nested": "data"}
    assert context.get("nonexistent", "default") == "default"
    
    print(f"检查键存在...")
    assert context.has("key1") == True
    assert context.has("nonexistent") == False
    
    print(f"移除键...")
    assert context.remove("key1") == True
    assert context.has("key1") == False
    assert context.remove("nonexistent") == False
    
    print(f"转换为字典...")
    context_dict = context.to_dict()
    assert "key2" in context_dict
    assert "key3" in context_dict
    
    print(f"清空上下文...")
    context.clear()
    assert context.to_dict() == {}
    
    print("✓ 插件上下文测试通过")


def test_shortplay_plugins():
    """测试短剧专属插件"""
    print("\n" + "="*50)
    print("测试短剧专属插件")
    print("="*50)
    
    manager = PluginManager()
    
    with tempfile.TemporaryDirectory() as temp_dir:
        manager.add_plugin_dir(temp_dir)
        
        categories = [
            PluginCategory.COUNTERATTACK,
            PluginCategory.EMOTION,
            PluginCategory.SUSPENSE,
            PluginCategory.SELLING
        ]
        
        for i, category in enumerate(categories):
            plugin_code = f'''
from app.core.plugin_loader import IEffectPlugin, PluginInfo, PluginType, PluginCategory

class Plugin(IEffectPlugin):
    @property
    def plugin_info(self):
        return PluginInfo(
            id="shortplay_{i}",
            name="{category.value}特效",
            version="1.0.0",
            description="{category.value}特效插件",
            author="Test",
            plugin_type=PluginType.EFFECT,
            category=PluginCategory.{category.name},
            file_path=__file__
        )
    
    def initialize(self, context):
        return True
    
    def shutdown(self):
        return True
    
    def get_ui_config(self):
        return {{}}
    
    def apply_effect(self, frame_data, params):
        return frame_data
    
    def get_effect_params(self):
        return {{}}
'''
            
            test_file = os.path.join(temp_dir, f"plugin_{i}.py")
            with open(test_file, 'w', encoding='utf-8') as f:
                f.write(plugin_code)
        
        print(f"发现短剧插件...")
        discovered = manager.discover_plugins()
        assert len(discovered) == 4
        
        print(f"获取短剧专属插件...")
        shortplay_plugins = manager.get_shortplay_plugins()
        
        for category, plugins in shortplay_plugins.items():
            print(f"  {category.value}: {len(plugins)} 个插件")
        
        print("✓ 短剧专属插件测试通过")


def run_all_tests():
    """运行所有测试"""
    print("\n" + "="*60)
    print("插件热加载机制测试套件")
    print("="*60)
    
    try:
        test_plugin_discovery()
        test_plugin_loading()
        test_plugin_hot_reload()
        test_plugin_registry()
        test_plugin_manager()
        test_plugin_factory()
        test_plugin_context()
        test_shortplay_plugins()
        
        print("\n" + "="*60)
        print("✓ 所有测试通过!")
        print("="*60)
        
    except AssertionError as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
    except Exception as e:
        print(f"\n✗ 测试异常: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    run_all_tests()
