import time
import os

class PerformanceMonitor:
    """性能监控类"""
    def __init__(self):
        self.start_time = time.time()
        self.memory_usage_history = []
        self.cpu_usage_history = []
        self.max_memory_usage = 0
    
    def record_metrics(self):
        """记录性能指标"""
        try:
            # 延迟导入psutil
            import psutil
            
            # 记录内存使用情况
            process = psutil.Process(os.getpid())
            memory_info = process.memory_info()
            memory_usage_mb = memory_info.rss / (1024 ** 2)
            self.memory_usage_history.append(memory_usage_mb)
            self.max_memory_usage = max(self.max_memory_usage, memory_usage_mb)
            
            # 记录CPU使用情况
            cpu_usage = psutil.cpu_percent(interval=0.1)
            self.cpu_usage_history.append(cpu_usage)
        except:
            pass
    
    def get_stats(self):
        """获取性能统计信息"""
        if not self.memory_usage_history:
            return {}
        
        return {
            "uptime_seconds": round(time.time() - self.start_time, 2),
            "max_memory_usage_mb": round(self.max_memory_usage, 2),
            "avg_memory_usage_mb": round(sum(self.memory_usage_history) / len(self.memory_usage_history), 2),
            "avg_cpu_usage_percent": round(sum(self.cpu_usage_history) / len(self.cpu_usage_history), 2) if self.cpu_usage_history else 0
        }

# 全局性能监控实例
performance_monitor = PerformanceMonitor()
