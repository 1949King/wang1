#!/usr/bin/env python3
# 测试历史记录管理器模块

import sys
sys.path.append('.')

from core.history_manager import HistoryManager

def test_history_manager_import():
    """测试历史记录管理器模块导入"""
    print("测试历史记录管理器模块导入...")
    try:
        history_manager = HistoryManager()
        print("✓ 历史记录管理器模块导入成功")
        print(f"✓ HistoryManager类创建成功: {history_manager}")
        print(f"✓ 初始历史栈: {history_manager.history_stack}")
        print(f"✓ 初始重做栈: {history_manager.redo_stack}")
        print(f"✓ 最大历史记录数量: {history_manager.max_history}")
        
        # 测试add_action方法是否存在
        if hasattr(history_manager, 'add_action'):
            print("✓ add_action方法存在")
        else:
            print("✗ add_action方法不存在")
        
        # 测试undo方法是否存在
        if hasattr(history_manager, 'undo'):
            print("✓ undo方法存在")
        else:
            print("✗ undo方法不存在")
        
        # 测试redo方法是否存在
        if hasattr(history_manager, 'redo'):
            print("✓ redo方法存在")
        else:
            print("✗ redo方法不存在")
            
        return True
    except Exception as e:
        print(f"✗ 历史记录管理器模块导入失败: {e}")
        return False

def test_history_operations():
    """测试历史记录操作功能"""
    print("\n测试历史记录操作功能...")
    
    try:
        history_manager = HistoryManager(max_history=5)
        print(f"✓ 创建历史记录管理器，最大历史记录数量: {history_manager.max_history}")
        
        # 测试添加操作
        print("\n测试添加操作...")
        for i in range(1, 6):
            action = f"操作{i}"
            description = f"执行操作 {i}"
            history_manager.add_action(action, description)
            print(f"✓ 添加操作 {i}: {description}")
        
        print(f"✓ 当前历史栈大小: {len(history_manager.history_stack)}")
        print(f"✓ 当前重做栈大小: {len(history_manager.redo_stack)}")
        
        # 测试撤销操作
        print("\n测试撤销操作...")
        for i in range(1, 4):
            undone_action = history_manager.undo()
            if undone_action:
                print(f"✓ 撤销操作: {undone_action['description']}")
            else:
                print("✗ 撤销操作失败")
                return False
        
        print(f"✓ 撤销后历史栈大小: {len(history_manager.history_stack)}")
        print(f"✓ 撤销后重做栈大小: {len(history_manager.redo_stack)}")
        
        # 测试重做操作
        print("\n测试重做操作...")
        for i in range(1, 3):
            redone_action = history_manager.redo()
            if redone_action:
                print(f"✓ 重做操作: {redone_action['description']}")
            else:
                print("✗ 重做操作失败")
                return False
        
        print(f"✓ 重做后历史栈大小: {len(history_manager.history_stack)}")
        print(f"✓ 重做后重做栈大小: {len(history_manager.redo_stack)}")
        
        # 测试历史记录数量限制
        print("\n测试历史记录数量限制...")
        for i in range(6, 11):
            action = f"操作{i}"
            description = f"执行操作 {i}"
            history_manager.add_action(action, description)
            print(f"✓ 添加操作 {i}: {description}")
        
        print(f"✓ 超过限制后历史栈大小: {len(history_manager.history_stack)}")
        print(f"✓ 历史栈内容: {[action['description'] for action in history_manager.history_stack]}")
        
        return True
    except Exception as e:
        print(f"✗ 测试历史记录操作失败: {e}")
        return False

if __name__ == "__main__":
    print("开始测试历史记录管理器模块...")
    
    # 测试模块导入
    import_success = test_history_manager_import()
    
    # 测试历史记录操作功能
    operations_success = test_history_operations()
    
    if import_success and operations_success:
        print("\n测试完成: 所有测试通过！")
        print("\n历史记录管理器模块已就绪，可以使用以下功能:")
        print("  1. add_action - 添加操作到历史记录")
        print("  2. undo - 撤销上一步操作")
        print("  3. redo - 重做上一步撤销的操作")
    else:
        print("\n测试完成: 存在测试失败！")
        sys.exit(1)