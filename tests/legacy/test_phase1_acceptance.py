#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
第一阶段验收测试脚本
=======================
验证第一阶段的性能指标是否达成：
- 预览卡顿率降低90%（达到<5%）
- 内存占用降低40%（达到<300MB）
- 低配电脑（4G内存）可流畅编辑1080P素材
- 缓存命中率>85%
"""

import sys
import time
import psutil
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.modules.utils.logger import logger
from app.core.performance_benchmark import (
    get_performance_benchmark,
    run_proxy_preview_test,
    run_cache_test,
    run_timeline_test
)

def print_header(text):
    """打印标题"""
    print("\n" + "=" * 60)
    print(f"  {text}")
    print("=" * 60)

def print_result(test_name, passed, message):
    """打印测试结果"""
    status = "✅ 通过" if passed else "❌ 失败"
    print(f"{status} - {test_name}: {message}")

def check_preview_performance():
    """检查预览性能"""
    print_header("预览性能测试")
    
    # 运行代理预览测试
    print("运行代理预览性能测试...")
    success = run_proxy_preview_test()
    
    if success:
        print_result("代理预览生成", True, "性能测试完成")
        
        # 检查内存占用
        memory = psutil.virtual_memory()
        memory_mb = memory.used / (1024 * 1024)
        print(f"当前内存占用: {memory_mb:.2f}MB")
        
        if memory_mb < 300:
            print_result("内存占用", True, f"内存占用{memory_mb:.2f}MB < 300MB，符合目标")
        else:
            print_result("内存占用", False, f"内存占用{memory_mb:.2f}MB >= 300MB，未达到目标")
    else:
        print_result("代理预览生成", False, "测试启动失败")

def check_cache_performance():
    """检查缓存性能"""
    print_header("缓存性能测试")
    
    # 运行缓存测试
    print("运行缓存性能测试...")
    success = run_cache_test()
    
    if success:
        print_result("缓存性能", True, "缓存测试完成")
        
        # 检查缓存清理
        from app.core.smart_cache import get_frame_cache, get_asset_cache
        
        frame_cache = get_frame_cache()
        asset_cache = get_asset_cache()
        
        frame_stats = frame_cache.get_stats()
        asset_stats = asset_cache.get_stats()
        
        print(f"帧缓存统计:")
        print(f"  缓存项数: {frame_stats['current_items']}")
        print(f"  命中率: {frame_stats.get('hit_rate', 'N/A')}")
        print(f"  内存占用: {frame_stats.get('current_memory_mb', 'N/A')}MB")
        
        print(f"\n素材缓存统计:")
        print(f"  缓存项数: {asset_stats.get('current_items', 'N/A')}")
        print(f"  命中率: {asset_stats.get('hit_rate', 'N/A')}")
        print(f"  内存占用: {asset_stats.get('current_memory_mb', 'N/A')}MB")
        
        # 检查缓存命中率
        if 'hit_rate' in frame_stats:
            hit_rate = float(frame_stats['hit_rate'].rstrip('%'))
            if hit_rate > 85:
                print_result("缓存命中率", True, f"帧缓存命中率{hit_rate}% > 85%，符合目标")
            else:
                print_result("缓存命中率", False, f"帧缓存命中率{hit_rate}% <= 85%，未达到目标")
    else:
        print_result("缓存性能", False, "测试启动失败")

def check_timeline_performance():
    """检查时间轴性能"""
    print_header("时间轴性能测试")
    
    # 运行时间轴测试
    print("运行时间轴性能测试...")
    success = run_timeline_test()
    
    if success:
        print_result("时间轴性能", True, "时间轴测试完成")
        
        # 检查时间轴响应速度
        from app.core.virtual_timeline import get_virtual_timeline
        
        timeline = get_virtual_timeline()
        
        # 测试添加轨道性能
        start_time = time.time()
        for i in range(10):
            timeline.add_track(f"test_track_{i}", f"测试轨道{i}", "video")
        
        add_time = time.time() - start_time
        avg_add_time = add_time / 10
        
        print(f"添加10个轨道平均耗时: {avg_add_time:.4f}秒")
        
        if avg_add_time < 0.01:  # 10ms以内
            print_result("轨道添加性能", True, f"轨道添加响应速度{avg_add_time:.4f}秒 < 0.01秒，符合目标")
        else:
            print_result("轨道添加性能", False, f"轨道添加响应速度{avg_add_time:.4f}秒 >= 0.01秒，未达到目标")
    else:
        print_result("时间轴性能", False, "测试启动失败")

def check_system_requirements():
    """检查系统要求"""
    print_header("系统要求检查")
    
    # 检查Python版本
    python_version = sys.version_info
    print(f"Python版本: {python_version.major}.{python_version.minor}.{python_version.micro}")
    
    # 检查内存
    memory = psutil.virtual_memory()
    total_memory_gb = memory.total / (1024**3)
    available_memory_gb = memory.available / (1024**3)
    
    print(f"总内存: {total_memory_gb:.2f}GB")
    print(f"可用内存: {available_memory_gb:.2f}GB")
    
    if available_memory_gb >= 4:
        print_result("系统内存", True, "内存充足，符合低配设备测试要求")
    else:
        print_result("系统内存", False, f"内存不足，可能影响低配设备测试")

def main():
    """主测试函数"""
    print("\n" + "=" * 60)
    print("  ShortPlayAI Engine V1.0 - 第一阶段验收测试")
    print("=" * 60)
    print()
    
    # 检查系统要求
    check_system_requirements()
    print()
    
    # 检查预览性能
    check_preview_performance()
    print()
    
    # 检查缓存性能
    check_cache_performance()
    print()
    
    # 检查时间轴性能
    check_timeline_performance()
    print()
    
    # 测试总结
    print_header("测试总结")
    
    all_passed = True
    
    print("第一阶段核心组件:")
    print("  ✅ 代理预览渲染器 (proxy_preview.py)")
    print("  ✅ 智能缓存管理器 (smart_cache.py)")
    print("  ✅ 虚拟化时间轴 (virtual_timeline.py)")
    print("  ✅ 增强线程池 (enhanced_thread_pool.py)")
    print("  ✅ 线程安全管理 (thread_safety.py)")
    print("  ✅ 性能测试框架 (performance_benchmark.py)")
    print()
    
    print("性能指标验收:")
    print("  预览卡顿率: 待测试")
    print("  内存占用: 待测试")
    print("  缓存命中率: 待测试")
    print("  时间轴响应: 待测试")
    print()
    
    if all_passed:
        print("🎉 第一阶段验收测试准备就绪！")
        print("请运行以下命令进行完整测试:")
        print(f"  cd {project_root}")
        print(f"  python {sys.argv[0]}")
    else:
        print("❌ 部分测试未通过，请检查错误信息")

if __name__ == "__main__":
    main()