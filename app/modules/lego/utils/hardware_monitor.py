"""
utils/hardware_monitor.py
=========================
B1 第一刀: 抽取 modules.py:1032-1102 HardwareDetector + PerformanceMonitor
最小侵入: 在 modules.py 顶部 `from ..utils.hardware_monitor import HardwareDetector, PerformanceMonitor, hardware_detector, hardware_config, performance_monitor`
"""
import time


import logging
logger = logging.getLogger("AI短剧编辑器.modules.lego.utils.hardware_monitor")

class HardwareDetector:
    """硬件探测器 (原 modules.py:1032-1070)"""
    def detect_hardware(self):
        try:
            import psutil
            cpu_count = psutil.cpu_count(logical=True)
            cpu_freq = psutil.cpu_freq().current if psutil.cpu_freq() else 0
            memory = psutil.virtual_memory()
            total_memory = memory.total // (1024 * 1024 * 1024)
            disk = psutil.disk_usage('/')
            total_disk = disk.total // (1024 * 1024 * 1024)
            return {
                "cpu_count": cpu_count,
                "cpu_freq": cpu_freq,
                "total_memory": total_memory,
                "total_disk": total_disk,
                "max_threads": min(cpu_count, 8),
                "max_batch_size": min(cpu_count * 2, 16),
                "cache_size": min(total_memory * 1024 * 1024 * 1024 // 4, 4 * 1024 * 1024 * 1024)
            }
        except Exception as e:
            logger.error(f'硬件检测失败: {e}')
            return {
                "cpu_count": 4, "cpu_freq": 2500, "total_memory": 8, "total_disk": 100,
                "max_threads": 4, "max_batch_size": 8, "cache_size": 2 * 1024 * 1024 * 1024
            }


class PerformanceMonitor:
    """性能监控 (原 modules.py:1072-1102)"""
    def __init__(self):
        self.start_time = time.time()
        self.metrics = {}

    def record_metrics(self):
        try:
            import psutil
            cpu_usage = psutil.cpu_percent()
            memory = psutil.virtual_memory()
            memory_usage = memory.percent
            disk = psutil.disk_usage('/')
            disk_usage = disk.percent
            self.metrics = {
                "cpu_usage": cpu_usage,
                "memory_usage": memory_usage,
                "disk_usage": disk_usage,
                "uptime": time.time() - self.start_time
            }
            logger.info(f'性能指标: CPU={cpu_usage}%, 内存={memory_usage}%, 磁盘={disk_usage}%')
            return self.metrics
        except Exception as e:
            logger.error(f'性能监控失败: {e}')
            return {}


# 模块级单例 (兼容原 modules.py:1104-1107 的全局对象)
hardware_detector = HardwareDetector()
hardware_config = hardware_detector.detect_hardware()
performance_monitor = PerformanceMonitor()
