"""
增强日志系统
================
在现有日志系统基础上添加性能监控、结构化日志和日志分析功能

B4 收敛标记 (2026-05-31): 增强层 (PerformanceMonitor / StructuredLogger)
调用入口: from core.logging_enhanced import initialize_enhanced_logging
接线工作待 #C 任务
"""

import logging
import time
import json
import threading
from typing import Dict, Any, Optional, Callable, List
from dataclasses import dataclass, field
from datetime import datetime
from functools import wraps
from collections import defaultdict
from pathlib import Path
import traceback

from app.core.log_manager import log_manager, get_logger

logger = get_logger(__name__)


@dataclass
class PerformanceMetric:
    """性能指标"""
    function_name: str
    module_name: str
    execution_time: float
    timestamp: float
    success: bool
    error_message: Optional[str] = None
    args_count: int = 0
    kwargs_count: int = 0


@dataclass
class LogEntry:
    """日志条目"""
    timestamp: float
    level: str
    logger_name: str
    message: str
    module: str
    function: str
    line_number: int
    thread_name: str
    extra_data: Dict[str, Any] = field(default_factory=dict)


class PerformanceMonitor:
    """性能监控器"""
    
    def __init__(self, max_history_size: int = 10000):
        self._metrics: List[PerformanceMetric] = []
        self._max_history_size = max_history_size
        self._lock = threading.Lock()
        self._function_stats: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
            'total_calls': 0,
            'total_time': 0.0,
            'success_count': 0,
            'error_count': 0,
            'min_time': float('inf'),
            'max_time': 0.0
        })
        self._alert_callbacks: List[Callable] = []
        
        self._thresholds = {
            'warning_time': 1.0,
            'critical_time': 5.0,
            'error_rate_warning': 0.1,
            'error_rate_critical': 0.2
        }
    
    def record_metric(self, metric: PerformanceMetric):
        """记录性能指标"""
        with self._lock:
            self._metrics.append(metric)
            if len(self._metrics) > self._max_history_size:
                self._metrics.pop(0)
            
            # 更新函数统计
            key = f"{metric.module_name}.{metric.function_name}"
            stats = self._function_stats[key]
            stats['total_calls'] += 1
            stats['total_time'] += metric.execution_time
            stats['min_time'] = min(stats['min_time'], metric.execution_time)
            stats['max_time'] = max(stats['max_time'], metric.execution_time)
            
            if metric.success:
                stats['success_count'] += 1
            else:
                stats['error_count'] += 1
            
            # 检查告警条件
            self._check_alerts(metric, key, stats)
    
    def _check_alerts(self, metric: PerformanceMetric, key: str, stats: Dict[str, Any]):
        """检查性能告警"""
        # 执行时间告警
        if metric.execution_time > self._thresholds['critical_time']:
            self._trigger_alert('critical', f"函数 {key} 执行时间过长: {metric.execution_time:.2f}s")
        elif metric.execution_time > self._thresholds['warning_time']:
            self._trigger_alert('warning', f"函数 {key} 执行时间较长: {metric.execution_time:.2f}s")
        
        # 错误率告警
        if stats['total_calls'] > 10:
            error_rate = stats['error_count'] / stats['total_calls']
            if error_rate > self._thresholds['error_rate_critical']:
                self._trigger_alert('critical', f"函数 {key} 错误率过高: {error_rate:.2%}")
            elif error_rate > self._thresholds['error_rate_warning']:
                self._trigger_alert('warning', f"函数 {key} 错误率较高: {error_rate:.2%}")
    
    def _trigger_alert(self, level: str, message: str):
        """触发性能告警"""
        alert = {
            'level': level,
            'message': message,
            'timestamp': time.time()
        }
        
        logger.warning(f"性能告警 [{level}]: {message}")
        
        for callback in self._alert_callbacks:
            try:
                callback(alert)
            except Exception as e:
                logger.error(f"性能告警回调执行失败: {e}")
    
    def add_alert_callback(self, callback: Callable):
        """添加告警回调"""
        self._alert_callbacks.append(callback)
    
    def get_metrics(self, function_name: Optional[str] = None, 
                   module_name: Optional[str] = None,
                   limit: int = 100) -> List[PerformanceMetric]:
        """获取性能指标"""
        with self._lock:
            filtered = self._metrics
            
            if function_name:
                filtered = [m for m in filtered if m.function_name == function_name]
            if module_name:
                filtered = [m for m in filtered if m.module_name == module_name]
            
            return filtered[-limit:]
    
    def get_function_stats(self, function_name: str, module_name: str) -> Optional[Dict[str, Any]]:
        """获取函数统计信息"""
        key = f"{module_name}.{function_name}"
        with self._lock:
            if key not in self._function_stats:
                return None
            
            stats = self._function_stats[key].copy()
            if stats['total_calls'] > 0:
                stats['avg_time'] = stats['total_time'] / stats['total_calls']
                stats['error_rate'] = stats['error_count'] / stats['total_calls']
            else:
                stats['avg_time'] = 0.0
                stats['error_rate'] = 0.0
            
            return stats
    
    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """获取所有函数的统计信息"""
        with self._lock:
            result = {}
            for key, stats in self._function_stats.items():
                result[key] = stats.copy()
                if stats['total_calls'] > 0:
                    result[key]['avg_time'] = stats['total_time'] / stats['total_calls']
                    result[key]['error_rate'] = stats['error_count'] / stats['total_calls']
                else:
                    result[key]['avg_time'] = 0.0
                    result[key]['error_rate'] = 0.0
            
            return result
    
    def clear_metrics(self):
        """清空性能指标"""
        with self._lock:
            self._metrics.clear()
            self._function_stats.clear()


class StructuredLogger:
    """结构化日志记录器"""
    
    def __init__(self, base_logger: logging.Logger):
        self._base_logger = base_logger
        self._log_entries: List[LogEntry] = []
        self._max_entries = 1000
        self._lock = threading.Lock()
    
    def log(
        self,
        level: str,
        message: str,
        extra: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        """记录结构化日志"""
        # 获取调用栈信息
        frame = kwargs.get('frame') or traceback.extract_stack()[-2]
        
        log_entry = LogEntry(
            timestamp=time.time(),
            level=level,
            logger_name=self._base_logger.name,
            message=message,
            module=kwargs.get('module', frame.name),
            function=kwargs.get('function', frame.name),
            line_number=kwargs.get('line_number', frame.lineno),
            thread_name=threading.current_thread().name,
            extra_data=extra or {}
        )
        
        # 存储日志条目
        with self._lock:
            self._log_entries.append(log_entry)
            if len(self._log_entries) > self._max_entries:
                self._log_entries.pop(0)
        
        # 记录到基础日志
        log_func = getattr(self._base_logger, level.lower(), self._base_logger.info)
        log_func(message, extra=extra or {})
    
    def debug(self, message: str, **kwargs):
        self.log('DEBUG', message, **kwargs)
    
    def info(self, message: str, **kwargs):
        self.log('INFO', message, **kwargs)
    
    def warning(self, message: str, **kwargs):
        self.log('WARNING', message, **kwargs)
    
    def error(self, message: str, **kwargs):
        self.log('ERROR', message, **kwargs)
    
    def critical(self, message: str, **kwargs):
        self.log('CRITICAL', message, **kwargs)
    
    def get_entries(
        self,
        level: Optional[str] = None,
        module: Optional[str] = None,
        limit: int = 100
    ) -> List[LogEntry]:
        """获取日志条目"""
        with self._lock:
            filtered = self._log_entries
            
            if level:
                filtered = [e for e in filtered if e.level == level]
            if module:
                filtered = [e for e in filtered if e.module == module]
            
            return filtered[-limit:]
    
    def export_to_json(self, file_path: str):
        """导出日志到JSON文件"""
        with self._lock:
            entries_data = [
                {
                    'timestamp': e.timestamp,
                    'level': e.level,
                    'logger_name': e.logger_name,
                    'message': e.message,
                    'module': e.module,
                    'function': e.function,
                    'line_number': e.line_number,
                    'thread_name': e.thread_name,
                    'extra_data': e.extra_data
                }
                for e in self._log_entries
            ]
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(entries_data, f, ensure_ascii=False, indent=2)


class LogAnalyzer:
    """日志分析器"""
    
    def __init__(self, structured_logger: StructuredLogger):
        self._logger = structured_logger
    
    def analyze_errors(self, time_range: Optional[tuple] = None) -> Dict[str, Any]:
        """分析错误日志"""
        entries = self._logger.get_entries(level='ERROR')
        
        if time_range:
            start_time, end_time = time_range
            entries = [e for e in entries if start_time <= e.timestamp <= end_time]
        
        error_counts = defaultdict(int)
        error_modules = defaultdict(int)
        
        for entry in entries:
            error_counts[entry.message] += 1
            error_modules[entry.module] += 1
        
        return {
            'total_errors': len(entries),
            'unique_errors': len(error_counts),
            'most_common_errors': sorted(error_counts.items(), key=lambda x: x[1], reverse=True)[:10],
            'error_by_module': dict(error_modules),
            'time_range': time_range
        }
    
    def analyze_performance(self, performance_monitor: PerformanceMonitor) -> Dict[str, Any]:
        """分析性能数据"""
        all_stats = performance_monitor.get_all_stats()
        
        slow_functions = []
        high_error_functions = []
        
        for key, stats in all_stats.items():
            if stats['avg_time'] > 1.0:
                slow_functions.append({
                    'function': key,
                    'avg_time': stats['avg_time'],
                    'max_time': stats['max_time']
                })
            
            if stats['error_rate'] > 0.1:
                high_error_functions.append({
                    'function': key,
                    'error_rate': stats['error_rate'],
                    'total_calls': stats['total_calls']
                })
        
        return {
            'total_functions': len(all_stats),
            'slow_functions': sorted(slow_functions, key=lambda x: x['avg_time'], reverse=True)[:10],
            'high_error_functions': sorted(high_error_functions, key=lambda x: x['error_rate'], reverse=True)[:10]
        }
    
    def generate_report(self, performance_monitor: PerformanceMonitor) -> str:
        """生成分析报告"""
        error_analysis = self.analyze_errors()
        performance_analysis = self.analyze_performance(performance_monitor)
        
        report = []
        report.append("=" * 60)
        report.append("系统分析报告")
        report.append("=" * 60)
        report.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append("")
        
        # 错误分析
        report.append("错误分析:")
        report.append(f"  总错误数: {error_analysis['total_errors']}")
        report.append(f"  唯一错误数: {error_analysis['unique_errors']}")
        report.append("")
        
        if error_analysis['most_common_errors']:
            report.append("  最常见错误:")
            for error, count in error_analysis['most_common_errors'][:5]:
                report.append(f"    - {error}: {count}次")
            report.append("")
        
        # 性能分析
        report.append("性能分析:")
        report.append(f"  总函数数: {performance_analysis['total_functions']}")
        report.append("")
        
        if performance_analysis['slow_functions']:
            report.append("  慢函数 (平均执行时间>1s):")
            for func in performance_analysis['slow_functions'][:5]:
                report.append(f"    - {func['function']}: {func['avg_time']:.2f}s (最大: {func['max_time']:.2f}s)")
            report.append("")
        
        if performance_analysis['high_error_functions']:
            report.append("  高错误率函数 (错误率>10%):")
            for func in performance_analysis['high_error_functions'][:5]:
                report.append(f"    - {func['function']}: {func['error_rate']:.2%} ({func['total_calls']}次调用)")
            report.append("")
        
        report.append("=" * 60)
        
        return "\n".join(report)


def monitor_performance(threshold_warning: float = 1.0, threshold_critical: float = 5.0):
    """性能监控装饰器"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            success = True
            error_message = None
            
            try:
                result = func(*args, **kwargs)
                return result
            except Exception as e:
                success = False
                error_message = str(e)
                raise
            finally:
                execution_time = time.time() - start_time
                
                metric = PerformanceMetric(
                    function_name=func.__name__,
                    module_name=func.__module__,
                    execution_time=execution_time,
                    timestamp=time.time(),
                    success=success,
                    error_message=error_message,
                    args_count=len(args),
                    kwargs_count=len(kwargs)
                )
                
                # 获取全局性能监控器
                monitor = get_performance_monitor()
                if monitor:
                    monitor.record_metric(metric)
        
        return wrapper
    return decorator


# 全局实例
_performance_monitor: Optional[PerformanceMonitor] = None
_structured_logger: Optional[StructuredLogger] = None
_log_analyzer: Optional[LogAnalyzer] = None


def get_performance_monitor() -> Optional[PerformanceMonitor]:
    """获取全局性能监控器"""
    return _performance_monitor


def get_structured_logger() -> Optional[StructuredLogger]:
    """获取全局结构化日志记录器"""
    return _structured_logger


def get_log_analyzer() -> Optional[LogAnalyzer]:
    """获取全局日志分析器"""
    return _log_analyzer


def initialize_enhanced_logging(
    enable_performance_monitor: bool = True,
    enable_structured_logging: bool = True,
    performance_history_size: int = 10000
):
    """初始化增强日志系统
    
    Args:
        enable_performance_monitor: 是否启用性能监控
        enable_structured_logging: 是否启用结构化日志
        performance_history_size: 性能历史记录大小
    """
    global _performance_monitor, _structured_logger, _log_analyzer
    
    if enable_performance_monitor and _performance_monitor is None:
        _performance_monitor = PerformanceMonitor(max_history_size=performance_history_size)
        logger.info("性能监控器已初始化")
    
    if enable_structured_logging and _structured_logger is None:
        base_logger = get_logger('structured')
        _structured_logger = StructuredLogger(base_logger)
        logger.info("结构化日志记录器已初始化")
    
    if _log_analyzer is None and _structured_logger:
        _log_analyzer = LogAnalyzer(_structured_logger)
        logger.info("日志分析器已初始化")


def log_performance_summary():
    """记录性能摘要"""
    monitor = get_performance_monitor()
    if not monitor:
        return
    
    stats = monitor.get_all_stats()
    if not stats:
        logger.info("暂无性能数据")
        return
    
    summary = []
    summary.append("性能摘要:")
    summary.append(f"  监控函数数: {len(stats)}")
    
    total_calls = sum(s['total_calls'] for s in stats.values())
    total_time = sum(s['total_time'] for s in stats.values())
    total_errors = sum(s['error_count'] for s in stats.values())
    
    summary.append(f"  总调用次数: {total_calls}")
    summary.append(f"  总执行时间: {total_time:.2f}s")
    summary.append(f"  总错误次数: {total_errors}")
    
    if total_calls > 0:
        avg_time = total_time / total_calls
        error_rate = total_errors / total_calls
        summary.append(f"  平均执行时间: {avg_time:.4f}s")
        summary.append(f"  错误率: {error_rate:.2%}")
    
    logger.info("\n".join(summary))


def export_analysis_report(file_path: str):
    """导出分析报告"""
    analyzer = get_log_analyzer()
    monitor = get_performance_monitor()
    
    if not analyzer or not monitor:
        logger.warning("日志分析器或性能监控器未初始化")
        return
    
    report = analyzer.generate_report(monitor)
    
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(report)
    
    logger.info(f"分析报告已导出到: {file_path}")