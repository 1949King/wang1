"""
Py+C++ 混合内核测试
====================
验证 C++ 视频引擎功能
"""

import os
import sys
import time
import unittest
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from app.core.video_processing.cpp_engine import (
    get_engine,
    is_cpp_engine_available,
    CppVideoEngine
)
from app.core.video_processing.cpp_engine.performance_optimizer import (
    get_optimizer,
    PerformanceOptimizer
)


class TestCppEngine(unittest.TestCase):
    """C++ 引擎测试"""
    
    @classmethod
    def setUpClass(cls):
        """测试前准备"""
        cls.engine_available = is_cpp_engine_available()
        if cls.engine_available:
            cls.engine = get_engine()
    
    def test_engine_availability(self):
        """测试引擎可用性"""
        print(f"\nC++ 引擎可用: {self.engine_available}")
        self.assertIsInstance(self.engine_available, bool)
    
    @unittest.skipUnless(is_cpp_engine_available(), "C++ 引擎不可用")
    def test_analyze_video(self):
        """测试视频分析"""
        # 使用测试视频
        test_video = "app/core/video_processing/cpp_engine/test_video.mp4"
        
        if os.path.exists(test_video):
            info = self.engine.analyze_video(test_video)
            self.assertIsNotNone(info)
            print(f"\n视频信息:")
            print(f"  分辨率: {info.width}x{info.height}")
            print(f"  帧率: {info.fps}")
            print(f"  时长: {info.duration}秒")
    
    @unittest.skipUnless(is_cpp_engine_available(), "C++ 引擎不可用")
    def test_gpu_detection(self):
        """测试 GPU 检测"""
        gpu_encoder = self.engine.get_gpu_encoder()
        print(f"\nGPU 编码器: {gpu_encoder}")
        self.assertIsInstance(gpu_encoder, str)
    
    def test_performance_optimizer(self):
        """测试性能优化器"""
        optimizer = get_optimizer()
        self.assertIsNotNone(optimizer)
        
        # 获取系统资源
        resources = optimizer.get_system_resources()
        print(f"\n系统资源:")
        print(f"  CPU 核心数: {resources.cpu_count}")
        print(f"  CPU 使用率: {resources.cpu_usage}%")
        print(f"  内存总量: {resources.memory_total:.0f} MB")
        print(f"  内存使用: {resources.memory_used:.0f} MB")
        print(f"  GPU 可用: {resources.gpu_available}")
        if resources.gpu_name:
            print(f"  GPU 名称: {resources.gpu_name}")
        
        # 获取最优配置
        config = optimizer.get_optimal_config()
        print(f"\n最优配置:")
        print(f"  线程数: {config.thread_count}")
        print(f"  GPU 启用: {config.gpu_enabled}")
        print(f"  GPU 编码器: {config.gpu_encoder}")
        print(f"  缓存大小: {config.cache_size_mb} MB")
        print(f"  批量大小: {config.batch_size}")
        print(f"  质量预设: {config.quality_preset}")
        
        # 获取性能报告
        report = optimizer.get_performance_report()
        print(f"\n性能报告:")
        print(f"  建议: {report['recommendations']}")


class TestPerformanceOptimizer(unittest.TestCase):
    """性能优化器测试"""
    
    def setUp(self):
        """测试前准备"""
        self.optimizer = get_optimizer()
    
    def test_optimize_for_export_4k(self):
        """测试 4K 导出优化"""
        config = self.optimizer.optimize_for_export(
            video_duration=60.0,
            resolution=(3840, 2160)
        )
        
        print(f"\n4K 导出配置:")
        print(f"  质量预设: {config.quality_preset}")
        print(f"  线程数: {config.thread_count}")
        print(f"  批量大小: {config.batch_size}")
        
        self.assertEqual(config.quality_preset, "medium")
    
    def test_optimize_for_export_1080p(self):
        """测试 1080p 导出优化"""
        config = self.optimizer.optimize_for_export(
            video_duration=30.0,
            resolution=(1920, 1080)
        )
        
        print(f"\n1080p 导出配置:")
        print(f"  质量预设: {config.quality_preset}")
        print(f"  线程数: {config.thread_count}")
        
        self.assertEqual(config.quality_preset, "fast")
    
    def test_estimate_processing_time(self):
        """测试处理时间估算"""
        config = self.optimizer.get_optimal_config()
        
        # 1080p 30 秒视频
        estimated_time = self.optimizer.estimate_processing_time(
            video_duration=30.0,
            resolution=(1920, 1080),
            config=config
        )
        
        print(f"\n处理时间估算:")
        print(f"  1080p 30 秒视频: {estimated_time:.1f} 秒")
        
        self.assertGreater(estimated_time, 0)


def run_tests():
    """运行测试"""
    print("=" * 60)
    print("Py+C++ 混合内核测试")
    print("=" * 60)
    
    # 创建测试套件
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # 添加测试
    suite.addTests(loader.loadTestsFromTestCase(TestCppEngine))
    suite.addTests(loader.loadTestsFromTestCase(TestPerformanceOptimizer))
    
    # 运行测试
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # 输出结果
    print("\n" + "=" * 60)
    print(f"测试结果: {result.testsRun} 个测试")
    print(f"成功: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"失败: {len(result.failures)}")
    print(f"错误: {len(result.errors)}")
    print("=" * 60)
    
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
