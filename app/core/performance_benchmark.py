"""
性能测试框架 - Week 2核心组件
================================
提供性能基准测试、压力测试、内存监控、性能分析
目标：验证第一阶段性能指标达成，为后续优化提供数据支持
"""

import time
import psutil
import threading
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
import json
from collections import defaultdict

try:
    from PyQt6.QtCore import QObject, pyqtSignal
    PYQT_AVAILABLE = True
except ImportError:
    PYQT_AVAILABLE = False

from app.modules.utils.logger import logger

class TestMetric(Enum):
    """测试指标类型"""
    CPU_USAGE = "cpu_usage"
    MEMORY_USAGE = "memory_usage"
    DISK_IO = "disk_io"
    FRAME_RATE = "frame_rate"
    RENDER_TIME = "render_time"
    CACHE_HIT_RATE = "cache_hit_rate"
    TASK_EXECUTION_TIME = "task_execution_time"

class TestLevel(Enum):
    """测试级别"""
    QUICK = "quick"  # 快速测试（5分钟）
    NORMAL = "normal"  # 正常测试（30分钟）
    STRESS = "stress"  # 压力测试（1小时）
    LONG_RUNNING = "long_running"  # 长期测试（24小时）

@dataclass
class PerformanceConfig:
    """性能测试配置"""
    test_level: TestLevel = TestLevel.NORMAL
    sample_interval: float = 1.0  # 采样间隔（秒）
    max_samples: int = 10000  # 最大采样数
    enable_memory_monitoring: bool = True
    enable_cpu_monitoring: bool = True
    enable_disk_monitoring: bool = False
    auto_save_results: bool = True
    results_dir: str = "performance_tests"

@dataclass
class TestResult:
    """测试结果"""
    metric: TestMetric
    test_name: str
    value: float
    unit: str
    timestamp: float
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class PerformanceReport:
    """性能报告"""
    test_level: TestLevel
    start_time: float
    end_time: float
    duration: float
    results: List[TestResult] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)
    system_info: Dict[str, Any] = field(default_factory=dict)

class PerformanceBenchmark(QObject):
    """性能基准测试器"""
    
    # 信号
    test_started = pyqtSignal(str)
    test_progress = pyqtSignal(str, int, int)
    test_completed = pyqtSignal(object)
    test_failed = pyqtSignal(str, str)
    
    def __init__(self, config: Optional[PerformanceConfig] = None):
        super().__init__()
        self.config = config or PerformanceConfig()
        self._current_report: Optional[PerformanceReport] = None
        self._monitoring = False
        self._lock = threading.Lock()
        self._samples: Dict[TestMetric, List[float]] = defaultdict(list)
        self._sample_count = 0
        self._monitor_thread = None
        
        logger.info(f"性能基准测试器初始化: {self.config.test_level.name}")
    
    def start_benchmark(self, test_name: str, test_func: Callable, 
                    duration: Optional[float] = None) -> bool:
        """启动基准测试
        
        Args:
            test_name: 测试名称
            test_func: 测试函数
            duration: 测试时长（秒），None表示使用配置中的时长
            
        Returns:
            是否启动成功
        """
        if self._monitoring:
            logger.warning("性能测试已在运行")
            return False
        
        try:
            # 创建新的性能报告
            self._current_report = PerformanceReport(
                test_level=self.config.test_level,
                start_time=time.time(),
                end_time=0.0,
                duration=0.0,
                test_name=test_name
            )
            
            # 启动监控线程
            self._start_monitoring()
            
            # 执行测试
            self.test_started.emit(test_name)
            
            test_duration = duration or self._get_test_duration(self.config.test_level)
            end_time = time.time() + test_duration
            
            # 在独立线程中执行测试
            import threading
            test_thread = threading.Thread(
                target=self._run_test,
                args=(test_func, test_name, end_time),
                daemon=True
            )
            test_thread.start()
            
            logger.info(f"基准测试启动: {test_name}, 时长: {test_duration}秒")
            return True
            
        except Exception as e:
            logger.error(f"基准测试启动失败: {e}")
            self.test_failed.emit(test_name, str(e))
            return False
    
    def _run_test(self, test_func: Callable, test_name: str, end_time: float):
        """运行测试"""
        try:
            # 执行测试函数
            result = test_func()
            
            # 记录结果
            if self._current_report:
                self._current_report.end_time = time.time()
                self._current_report.duration = self._current_report.end_time - self._current_report.start_time
                
                # 添加结果到报告
                self._current_report.results.append(result)
                
                logger.info(f"测试完成: {test_name}, 结果: {result.value}{result.unit}")
        
        except Exception as e:
            logger.error(f"测试执行失败: {test_name}, 错误: {e}")
            if self._current_report:
                self._current_report.results.append(TestResult(
                    metric=TestMetric.TASK_EXECUTION_TIME,
                    test_name=test_name,
                    value=0.0,
                    unit="seconds",
                    timestamp=time.time(),
                    metadata={'error': str(e)}
                ))
    
    def _start_monitoring(self):
        """启动性能监控"""
        if self._monitoring:
            return
        
        self._monitoring = True
        self._samples.clear()
        self._sample_count = 0
        
        # 启动监控线程
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True
        )
        self._monitor_thread.start()
        
        logger.info("性能监控已启动")
    
    def stop_monitoring(self):
        """停止性能监控"""
        self._monitoring = False
        
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)
            self._monitor_thread = None
        
        logger.info("性能监控已停止")
    
    def _monitor_loop(self):
        """监控主循环"""
        while self._monitoring:
            try:
                # 采集系统指标
                metrics = self._collect_metrics()
                
                # 发送进度信号
                self._sample_count += 1
                progress = min(100, int(self._sample_count / self.config.max_samples * 100))
                self.test_progress.emit("系统监控", progress)
                
                # 检查是否达到最大采样数
                if self._sample_count >= self.config.max_samples:
                    logger.info(f"已收集{self._sample_count}个样本")
                    break
                
                # 采样间隔
                time.sleep(self.config.sample_interval)
                
            except Exception as e:
                logger.error(f"监控循环错误: {e}")
                break
    
    def _collect_metrics(self) -> Dict[str, float]:
        """采集系统性能指标"""
        metrics = {}
        
        # CPU使用率
        if self.config.enable_cpu_monitoring:
            metrics['cpu_percent'] = psutil.cpu_percent(interval=1)
        
        # 内存使用
        if self.config.enable_memory_monitoring:
            memory = psutil.virtual_memory()
            metrics['memory_mb'] = memory.used / (1024 * 1024)
            metrics['memory_percent'] = memory.percent
        
        # 磁盘IO
        if self.config.enable_disk_monitoring:
            disk = psutil.disk_io_counters()
            if disk:
                metrics['disk_read_mb'] = disk.read_bytes / (1024 * 1024)
                metrics['disk_write_mb'] = disk.write_bytes / (1024 * 1024)
        
        return metrics
    
    def add_custom_metric(self, metric: TestMetric, value: float, unit: str = "", 
                     metadata: Dict[str, Any] = None):
        """添加自定义指标"""
        if self._current_report:
            result = TestResult(
                metric=metric,
                test_name="custom",
                value=value,
                unit=unit,
                timestamp=time.time(),
                metadata=metadata or {}
            )
            self._current_report.results.append(result)
    
    def get_current_report(self) -> Optional[PerformanceReport]:
        """获取当前性能报告"""
        return self._current_report
    
    def finalize_report(self) -> PerformanceReport:
        """完成性能报告"""
        if not self._current_report:
            logger.warning("没有活跃的性能报告")
            return None
        
        # 停止监控
        self.stop_monitoring()
        
        # 计算总结
        self._current_report.end_time = time.time()
        self._current_report.duration = self._current_report.end_time - self._current_report.start_time
        
        # 生成总结
        summary = self._generate_summary()
        self._current_report.summary = summary
        
        # 保存报告
        if self.config.auto_save_results:
            self._save_report()
        
        self.test_completed.emit(self._current_report)
        
        logger.info(f"性能报告完成: {summary}")
        
        report = self._current_report
        self._current_report = None
        
        return report
    
    def _generate_summary(self) -> Dict[str, Any]:
        """生成性能总结"""
        summary = {
            'total_tests': len(self._current_report.results),
            'test_duration': f"{self._current_report.duration:.2f}秒",
            'avg_cpu': f"{self._get_avg_metric('cpu_percent'):.2f}%",
            'avg_memory': f"{self._get_avg_metric('memory_mb'):.2f}MB",
            'peak_memory': f"{self._get_max_metric('memory_mb'):.2f}MB",
            'performance_rating': self._calculate_performance_rating()
        }
        
        return summary
    
    def _get_avg_metric(self, metric_name: str) -> float:
        """获取指标平均值"""
        values = [r.value for r in self._current_report.results if r.metric == metric_name]
        if not values:
            return 0.0
        return sum(values) / len(values)
    
    def _get_max_metric(self, metric_name: str) -> float:
        """获取指标最大值"""
        values = [r.value for r in self._current_report.results if r.metric == metric_name]
        if not values:
            return 0.0
        return max(values)
    
    def _calculate_performance_rating(self) -> str:
        """计算性能评级"""
        avg_memory = self._get_avg_metric('memory_mb')
        avg_cpu = self._get_avg_metric('cpu_percent')
        
        # 性能评级标准
        if avg_memory < 200 and avg_cpu < 50:
            return "优秀"
        elif avg_memory < 300 and avg_cpu < 70:
            return "良好"
        elif avg_memory < 500 and avg_cpu < 85:
            return "中等"
        else:
            return "需要优化"
    
    def _save_report(self):
        """保存性能报告"""
        import os
        import json
        
        if not self._current_report:
            return
        
        # 创建结果目录
        os.makedirs(self.config.results_dir, exist_ok=True)
        
        # 生成文件名
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"performance_report_{timestamp}.json"
        filepath = os.path.join(self.config.results_dir, filename)
        
        # 保存报告
        report_data = {
            'test_level': self._current_report.test_level.value,
            'start_time': self._current_report.start_time,
            'end_time': self._current_report.end_time,
            'duration': self._current_report.duration,
            'test_name': self._current_report.test_name,
            'results': [r.__dict__ for r in self._current_report.results],
            'summary': self._current_report.summary,
            'system_info': self._current_report.system_info
        }
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(report_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"性能报告已保存: {filepath}")
    
    def _get_test_duration(self, test_level: TestLevel) -> float:
        """获取测试时长"""
        durations = {
            TestLevel.QUICK: 300,  # 5分钟
            TestLevel.NORMAL: 1800,  # 30分钟
            TestLevel.STRESS: 3600,  # 1小时
            TestLevel.LONG_RUNNING: 86400  # 24小时
        }
        return durations.get(test_level, 1800)

# 全局性能基准测试器实例
performance_benchmark = None

def get_performance_benchmark(config: Optional[PerformanceConfig] = None) -> PerformanceBenchmark:
    """获取性能基准测试器实例（单例模式）"""
    global performance_benchmark
    if performance_benchmark is None:
        performance_benchmark = PerformanceBenchmark(config)
    return performance_benchmark

def run_proxy_preview_test() -> bool:
    """运行代理预览性能测试"""
    benchmark = get_performance_benchmark()
    
    def test_func():
        from app.modules.render.proxy_preview import get_proxy_preview_renderer
        renderer = get_proxy_preview_renderer()
        
        # 模拟代理生成
        start_time = time.time()
        
        # 生成10个代理
        for i in range(10):
            proxy_path = renderer.generate_proxy(f"test_video_{i}.mp4")
            if proxy_path:
                benchmark.add_custom_metric(
                    TestMetric.RENDER_TIME,
                    time.time() - start_time,
                    "seconds",
                    {'proxy_index': i}
                )
        
        return True
    
    return benchmark.start_benchmark("代理预览测试", test_func, duration=60)

def run_cache_test() -> bool:
    """运行缓存性能测试"""
    benchmark = get_performance_benchmark()
    
    def test_func():
        from app.core.smart_cache import get_frame_cache, get_asset_cache
        
        frame_cache = get_frame_cache()
        asset_cache = get_asset_cache()
        
        # 测试缓存性能
        start_time = time.time()
        
        # 添加1000个帧到缓存
        for i in range(1000):
            frame_cache.add_frame(f"video_{i}", i, f"frame_data_{i}")
        
        cache_add_time = time.time() - start_time
        benchmark.add_custom_metric(
            TestMetric.TASK_EXECUTION_TIME,
            cache_add_time,
            "seconds",
            {'operation': 'cache_add_1000_frames'}
        )
        
        # 测试缓存命中率
        hits = 0
        misses = 0
        
        for i in range(100):
            frame = frame_cache.get_frame(f"video_{i}", i)
            if frame:
                hits += 1
            else:
                misses += 1
        
        cache_test_time = time.time() - start_time
        hit_rate = (hits / (hits + misses)) * 100 if (hits + misses) > 0 else 0
        
        benchmark.add_custom_metric(
            TestMetric.CACHE_HIT_RATE,
            hit_rate,
            "percent",
            {'hits': hits, 'misses': misses}
        )
        
        # 测试缓存清理
        cleanup_start = time.time()
        frame_cache.clear_video_frames(f"video_{500}")
        cleanup_time = time.time() - cleanup_start
        
        benchmark.add_custom_metric(
            TestMetric.TASK_EXECUTION_TIME,
            cleanup_time,
            "seconds",
            {'operation': 'cache_cleanup_500_frames'}
        )
        
        return True
    
    return benchmark.start_benchmark("缓存性能测试", test_func, duration=120)

def run_timeline_test() -> bool:
    """运行时间轴性能测试"""
    benchmark = get_performance_benchmark()
    
    def test_func():
        from app.core.virtual_timeline import get_virtual_timeline
        
        timeline = get_virtual_timeline()
        
        # 测试轨道操作性能
        start_time = time.time()
        
        # 添加100个轨道
        for i in range(100):
            timeline.add_track(f"track_{i}", f"测试轨道{i}", "video")
        
        track_add_time = time.time() - start_time
        benchmark.add_custom_metric(
            TestMetric.TASK_EXECUTION_TIME,
            track_add_time,
            "seconds",
            {'operation': 'add_100_tracks'}
        )
        
        # 测试片段操作性能
        for i in range(100):
            from app.core.virtual_timeline import VirtualClip
            clip = VirtualClip(
                id=f"clip_{i}",
                track_id="video_1",
                start_time=i * 1.0,
                end_time=i * 1.0 + 2.0,
                type='video'
            )
            timeline.add_clip("video_1", clip)
        
        clip_add_time = time.time() - start_time
        benchmark.add_custom_metric(
            TestMetric.TASK_EXECUTION_TIME,
            clip_add_time,
            "seconds",
            {'operation': 'add_100_clips'}
        )
        
        # 测试选择操作性能
        for i in range(50):
            timeline.select_clips([f"clip_{j}" for j in range(i*2, min(i*2 + 10, 100))])
        
        select_time = time.time() - start_time
        benchmark.add_custom_metric(
            TestMetric.TASK_EXECUTION_TIME,
            select_time,
            "seconds",
            {'operation': 'select_50_times'}
        )
        
        return True
    
    return benchmark.start_benchmark("时间轴性能测试", test_func, duration=60)