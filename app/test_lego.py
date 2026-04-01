"""
简单测试脚本 - 验证乐高架构
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("=" * 50)
print("测试乐高积木架构")
print("=" * 50)

print("\n1. 测试导入核心模块...")
try:
    from modules.lego.base_block import LegoBlock, BlockInput, BlockOutput, BlockMeta
    print("  ✅ base_block 导入成功")
except Exception as e:
    print(f"  ❌ base_block 导入失败: {e}")

try:
    from modules.lego.core import EventBus, MasterClock, DataBus, EventType
    print("  ✅ core 导入成功")
except Exception as e:
    print(f"  ❌ core 导入失败: {e}")

try:
    from modules.lego.block_loader import BlockLoader, BlockRegistry
    print("  ✅ block_loader 导入成功")
except Exception as e:
    print(f"  ❌ block_loader 导入失败: {e}")

try:
    from modules.lego.flow_orchestrator import FlowOrchestrator, FlowNode
    print("  ✅ flow_orchestrator 导入成功")
except Exception as e:
    print(f"  ❌ flow_orchestrator 导入失败: {e}")

print("\n2. 测试 PyQt6...")
try:
    from PyQt6.QtWidgets import QApplication, QWidget
    print("  ✅ PyQt6 导入成功")
except Exception as e:
    print(f"  ❌ PyQt6 导入失败: {e}")
    print("  请运行: pip install PyQt6")

print("\n3. 测试事件总线...")
try:
    event_bus = EventBus.get_instance()
    print(f"  ✅ EventBus 实例: {event_bus}")
except Exception as e:
    print(f"  ❌ EventBus 失败: {e}")

print("\n4. 测试全局时钟...")
try:
    clock = MasterClock.get_instance()
    clock.fps = 30.0
    print(f"  ✅ MasterClock 实例: {clock}, FPS: {clock.fps}")
except Exception as e:
    print(f"  ❌ MasterClock 失败: {e}")

print("\n5. 测试积木创建...")
try:
    from modules.lego.builtin_blocks import AutoClipBlock
    
    block = AutoClipBlock()
    meta = block.info()
    print(f"  ✅ 积木创建成功: {meta.name} v{meta.version}")
    print(f"     描述: {meta.description}")
    print(f"     分类: {meta.category}")
except Exception as e:
    print(f"  ❌ 积木创建失败: {e}")

print("\n6. 测试流程编排...")
try:
    orchestrator = FlowOrchestrator()
    print(f"  ✅ FlowOrchestrator 创建成功")
except Exception as e:
    print(f"  ❌ FlowOrchestrator 失败: {e}")

print("\n" + "=" * 50)
print("测试完成！")
print("=" * 50)
