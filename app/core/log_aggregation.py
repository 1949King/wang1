"""
日志聚合系统
============
实现分布式日志收集和聚合功能
"""

import os
import logging
import threading
import time
import json
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
import re

from app.core.logging_enhanced import StructuredLogger, LogEntry
from app.core.exceptions import ConfigurationError, ErrorCode

logger = logging.getLogger(__name__)


class LogLevel(Enum):
    """日志级别"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class LogSource(Enum):
    """日志来源"""
    APPLICATION = "application"
    SYSTEM = "system"
    NETWORK = "network"
    DATABASE = "database"
    CACHE = "cache"
    GPU = "gpu"
    RENDER = "render"


@dataclass
class AggregatedLogEntry:
    """聚合日志条目"""
    timestamp: float
    level: LogLevel
    source: LogSource
    message: str
    module: str
    function: str
    line_number: int
    thread_name: str
    tags: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    correlation_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'timestamp': self.timestamp,
            'datetime': datetime.fromtimestamp(self.timestamp).isoformat(),
            'level': self.level.value,
            'source': self.source.value,
            'message': self.message,
            'module': self.module,
            'function': self.function,
            'line_number': self.line_number,
            'thread_name': self.thread_name,
            'tags': self.tags,
            'metadata': self.metadata,
            'correlation_id': self.correlation_id
        }


class LogAggregator:
    """日志聚合器"""
    
    def __init__(self, max_entries: int = 100000,
                 retention_days: int = 30):
        self.max_entries = max_entries
        self.retention_days = retention_days
        
        self._logs: deque = deque(maxlen=max_entries)
        self._indexed_logs: Dict[str, List[AggregatedLogEntry]] = defaultdict(list)
        self._lock = threading.RLock()
        
        self._log_filters: List[Callable[[AggregatedLogEntry], bool]] = []
        self._log_processors: List[Callable[[AggregatedLogEntry], None]] = []
        
        self._stats = {
            'total_logs': 0,
            'logs_by_level': defaultdict(int),
            'logs_by_source': defaultdict(int),
            'logs_by_module': defaultdict(int),
            'error_count': 0,
            'warning_count': 0
        }
        
        self._alert_rules: Dict[str, Dict[str, Any]] = {}
        self._alert_callbacks: List[Callable[[AggregatedLogEntry], None]] = []
    
    def add_log(self, entry: LogEntry, source: LogSource = LogSource.APPLICATION,
               correlation_id: Optional[str] = None):
        """添加日志条目
        
        Args:
            entry: 日志条目
            source: 日志来源
            correlation_id: 关联ID
        """
        # 应用过滤器
        for filter_func in self._log_filters:
            if not filter_func(entry):
                return
        
        # 创建聚合日志条目
        aggregated_entry = AggregatedLogEntry(
            timestamp=entry.timestamp,
            level=LogLevel(entry.level.upper()),
            source=source,
            message=entry.message,
            module=entry.module,
            function=entry.function,
            line_number=entry.line_number,
            thread_name=entry.thread_name,
            tags=entry.extra_data.copy(),
            metadata=entry.extra_data.copy(),
            correlation_id=correlation_id
        )
        
        with self._lock:
            # 添加到日志队列
            self._logs.append(aggregated_entry)
            
            # 添加到索引
            self._indexed_logs[entry.module].append(aggregated_entry)
            
            # 更新统计
            self._update_stats(aggregated_entry)
            
            # 检查告警
            self._check_log_alerts(aggregated_entry)
        
        # 应用处理器
        for processor in self._log_processors:
            try:
                processor(aggregated_entry)
            except Exception as e:
                logger.error(f"日志处理器执行失败: {e}")
    
    def _update_stats(self, entry: AggregatedLogEntry):
        """更新统计信息"""
        self._stats['total_logs'] += 1
        self._stats['logs_by_level'][entry.level] += 1
        self._stats['logs_by_source'][entry.source] += 1
        self._stats['logs_by_module'][entry.module] += 1
        
        if entry.level in [LogLevel.ERROR, LogLevel.CRITICAL]:
            self._stats['error_count'] += 1
        elif entry.level == LogLevel.WARNING:
            self._stats['warning_count'] += 1
    
    def _check_log_alerts(self, entry: AggregatedLogEntry):
        """检查日志告警"""
        for rule_id, rule in self._alert_rules.items():
            if not self._match_alert_rule(entry, rule):
                continue
            
            # 触发告警
            for callback in self._alert_callbacks:
                try:
                    callback(entry)
                except Exception as e:
                    logger.error(f"日志告警回调执行失败: {e}")
            
            logger.warning(f"触发日志告警: {rule_id} - {entry.message}")
    
    def _match_alert_rule(self, entry: AggregatedLogEntry, 
                         rule: Dict[str, Any]) -> bool:
        """匹配告警规则"""
        level_match = rule.get('level') is None or entry.level == LogLevel(rule['level'])
        source_match = rule.get('source') is None or entry.source == LogSource(rule['source'])
        pattern_match = rule.get('pattern') is None or re.search(rule['pattern'], entry.message)
        
        return level_match and source_match and pattern_match
    
    def add_filter(self, filter_func: Callable[[AggregatedLogEntry], bool]):
        """添加日志过滤器"""
        self._log_filters.append(filter_func)
    
    def add_processor(self, processor_func: Callable[[AggregatedLogEntry], None]):
        """添加日志处理器"""
        self._log_processors.append(processor_func)
    
    def add_alert_rule(self, rule_id: str, level: Optional[str] = None,
                     source: Optional[str] = None, pattern: Optional[str] = None):
        """添加告警规则
        
        Args:
            rule_id: 规则ID
            level: 日志级别
            source: 日志来源
            pattern: 消息模式
        """
        self._alert_rules[rule_id] = {
            'level': level,
            'source': source,
            'pattern': pattern
        }
        
        logger.info(f"添加日志告警规则: {rule_id}")
    
    def add_alert_callback(self, callback: Callable[[AggregatedLogEntry], None]):
        """添加告警回调"""
        self._alert_callbacks.append(callback)
    
    def query_logs(self, level: Optional[LogLevel] = None,
                   source: Optional[LogSource] = None,
                   module: Optional[str] = None,
                   start_time: Optional[float] = None,
                   end_time: Optional[float] = None,
                   limit: int = 1000) -> List[AggregatedLogEntry]:
        """查询日志
        
        Args:
            level: 日志级别
            source: 日志来源
            module: 模块名
            start_time: 开始时间
            end_time: 结束时间
            limit: 返回数量限制
        
        Returns:
            日志条目列表
        """
        with self._lock:
            filtered_logs = list(self._logs)
            
            # 应用过滤条件
            if level:
                filtered_logs = [log for log in filtered_logs if log.level == level]
            if source:
                filtered_logs = [log for log in filtered_logs if log.source == source]
            if module:
                filtered_logs = [log for log in filtered_logs if log.module == module]
            if start_time:
                filtered_logs = [log for log in filtered_logs if log.timestamp >= start_time]
            if end_time:
                filtered_logs = [log for log in filtered_logs if log.timestamp <= end_time]
            
            return filtered_logs[-limit:]
    
    def query_by_correlation(self, correlation_id: str) -> List[AggregatedLogEntry]:
        """根据关联ID查询日志
        
        Args:
            correlation_id: 关联ID
        
        Returns:
            相关日志列表
        """
        with self._lock:
            return [log for log in self._logs if log.correlation_id == correlation_id]
    
    def get_logs_by_module(self, module: str, 
                          limit: int = 100) -> List[AggregatedLogEntry]:
        """获取指定模块的日志"""
        with self._lock:
            return self._indexed_logs.get(module, [])[-limit:]
    
    def get_error_logs(self, limit: int = 100) -> List[AggregatedLogEntry]:
        """获取错误日志"""
        return self.query_logs(level=LogLevel.ERROR, limit=limit)
    
    def get_critical_logs(self, limit: int = 50) -> List[AggregatedLogEntry]:
        """获取严重错误日志"""
        return self.query_logs(level=LogLevel.CRITICAL, limit=limit)
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            return {
                'total_logs': self._stats['total_logs'],
                'logs_by_level': dict(self._stats['logs_by_level']),
                'logs_by_source': dict(self._stats['logs_by_source']),
                'logs_by_module': dict(self._stats['logs_by_module']),
                'error_count': self._stats['error_count'],
                'warning_count': self._stats['warning_count'],
                'error_rate': self._stats['error_count'] / max(self._stats['total_logs'], 1),
                'warning_rate': self._stats['warning_count'] / max(self._stats['total_logs'], 1)
            }
    
    def analyze_logs(self, time_window: int = 3600) -> Dict[str, Any]:
        """分析日志
        
        Args:
            time_window: 时间窗口（秒）
        
        Returns:
            分析结果
        """
        with self._lock:
            cutoff_time = time.time() - time_window
            recent_logs = [log for log in self._logs if log.timestamp >= cutoff_time]
            
            if not recent_logs:
                return {'status': 'no_data'}
            
            # 错误分析
            error_logs = [log for log in recent_logs 
                        if log.level in [LogLevel.ERROR, LogLevel.CRITICAL]]
            
            # 模块错误统计
            module_errors = defaultdict(int)
            for log in error_logs:
                module_errors[log.module] += 1
            
            # 错误趋势
            error_timeline = []
            for log in error_logs:
                error_timeline.append({
                    'timestamp': log.timestamp,
                    'module': log.module,
                    'message': log.message
                })
            
            # 常见错误模式
            error_patterns = defaultdict(int)
            for log in error_logs:
                # 提取错误模式
                pattern = self._extract_error_pattern(log.message)
                if pattern:
                    error_patterns[pattern] += 1
            
            return {
                'status': 'success',
                'time_window': time_window,
                'total_logs': len(recent_logs),
                'error_count': len(error_logs),
                'error_rate': len(error_logs) / len(recent_logs),
                'module_errors': dict(module_errors),
                'top_error_modules': sorted(
                    module_errors.items(),
                    key=lambda x: x[1],
                    reverse=True
                )[:10],
                'error_patterns': dict(error_patterns),
                'error_timeline': error_timeline
            }
    
    def _extract_error_pattern(self, message: str) -> Optional[str]:
        """提取错误模式"""
        # 常见错误模式
        patterns = [
            r'FileNotFoundError',
            r'PermissionError',
            r'ConnectionError',
            r'TimeoutError',
            r'ValueError',
            r'KeyError',
            r'AssertionError',
            r'RuntimeError',
            r'AttributeError'
        ]
        
        for pattern in patterns:
            if re.search(pattern, message):
                return pattern
        
        return None
    
    def export_logs(self, file_path: str, format: str = "json",
                   level: Optional[LogLevel] = None,
                   start_time: Optional[float] = None,
                   end_time: Optional[float] = None):
        """导出日志
        
        Args:
            file_path: 导出文件路径
            format: 导出格式
            level: 日志级别过滤
            start_time: 开始时间
            end_time: 结束时间
        """
        logs = self.query_logs(level=level, start_time=start_time, end_time=end_time)
        
        if format == "json":
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump([log.to_dict() for log in logs], f, ensure_ascii=False, indent=2)
        elif format == "csv":
            import csv
            with open(file_path, 'w', encoding='utf-8', newline='') as f:
                if logs:
                    writer = csv.DictWriter(f)
                    writer.writeheader()
                    writer.writerows([log.to_dict() for log in logs])
        else:
            raise ValueError(f"不支持的导出格式: {format}")
        
        logger.info(f"日志已导出: {file_path} ({len(logs)} 条)")
    
    def cleanup_old_logs(self):
        """清理旧日志"""
        cutoff_time = time.time() - (self.retention_days * 24 * 3600)
        
        with self._lock:
            original_count = len(self._logs)
            
            # 创建新队列，只保留新日志
            new_logs = deque(
                [log for log in self._logs if log.timestamp >= cutoff_time],
                maxlen=self.max_entries
            )
            
            self._logs = new_logs
            
            # 清理索引
            for module in list(self._indexed_logs.keys()):
                self._indexed_logs[module] = [
                    log for log in self._indexed_logs[module]
                    if log.timestamp >= cutoff_time
                ]
            
            removed_count = original_count - len(self._logs)
            logger.info(f"清理旧日志: {removed_count} 条")
    
    def clear_logs(self):
        """清空所有日志"""
        with self._lock:
            count = len(self._logs)
            self._logs.clear()
            self._indexed_logs.clear()
            self._stats = {
                'total_logs': 0,
                'logs_by_level': defaultdict(int),
                'logs_by_source': defaultdict(int),
                'logs_by_module': defaultdict(int),
                'error_count': 0,
                'warning_count': 0
            }
            
            logger.info(f"清空所有日志: {count} 条")


class DistributedLogCollector:
    """分布式日志收集器"""
    
    def __init__(self, aggregator: LogAggregator):
        self._aggregator = aggregator
        self._remote_endpoints: List[str] = []
        self._buffer: List[AggregatedLogEntry] = []
        self._buffer_size = 100
        self._lock = threading.Lock()
        self._running = False
        self._collector_thread: Optional[threading.Thread] = None
    
    def add_remote_endpoint(self, endpoint: str):
        """添加远程端点
        
        Args:
            endpoint: 远程端点URL
        """
        self._remote_endpoints.append(endpoint)
        logger.info(f"添加远程日志端点: {endpoint}")
    
    def start_collection(self, interval: int = 10):
        """开始收集日志
        
        Args:
            interval: 收集间隔（秒）
        """
        self._running = True
        self._collector_thread = threading.Thread(
            target=self._collection_loop,
            args=(interval,),
            daemon=True
        )
        self._collector_thread.start()
        
        logger.info(f"分布式日志收集已启动，间隔: {interval}秒")
    
    def stop_collection(self):
        """停止收集日志"""
        self._running = False
        
        if self._collector_thread and self._collector_thread.is_alive():
            self._collector_thread.join(timeout=30)
        
        # 发送剩余日志
        self._flush_buffer()
        
        logger.info("分布式日志收集已停止")
    
    def _collection_loop(self, interval: int):
        """收集循环"""
        while self._running:
            try:
                # 收集日志
                self._flush_buffer()
                
            except Exception as e:
                logger.error(f"日志收集异常: {e}")
            
            time.sleep(interval)
    
    def _flush_buffer(self):
        """刷新缓冲区"""
        with self._lock:
            if not self._buffer:
                return
            
            logs_to_send = self._buffer.copy()
            self._buffer.clear()
        
        # 发送到远程端点
        for endpoint in self._remote_endpoints:
            try:
                self._send_logs_to_endpoint(endpoint, logs_to_send)
            except Exception as e:
                logger.error(f"发送日志到端点失败: {endpoint} - {e}")
    
    def _send_logs_to_endpoint(self, endpoint: str, 
                             logs: List[AggregatedLogEntry]):
        """发送日志到端点"""
        import requests
        
        payload = {
            'timestamp': time.time(),
            'source': 'shortplayai',
            'logs': [log.to_dict() for log in logs]
        }
        
        response = requests.post(
            endpoint,
            json=payload,
            timeout=10
        )
        
        if response.status_code != 200:
            logger.warning(f"日志发送失败: {endpoint} - {response.status_code}")


# 全局实例
_global_log_aggregator: Optional[LogAggregator] = None
_global_distributed_collector: Optional[DistributedLogCollector] = None


def get_log_aggregator(max_entries: int = 100000,
                      retention_days: int = 30) -> LogAggregator:
    """获取全局日志聚合器"""
    global _global_log_aggregator
    
    if _global_log_aggregator is None:
        _global_log_aggregator = LogAggregator(max_entries, retention_days)
    
    return _global_log_aggregator


def get_distributed_log_collector(aggregator: Optional[LogAggregator] = None) -> DistributedLogCollector:
    """获取全局分布式日志收集器"""
    global _global_distributed_collector
    
    if _global_distributed_collector is None:
        if aggregator is None:
            aggregator = get_log_aggregator()
        _global_distributed_collector = DistributedLogCollector(aggregator)
    
    return _global_distributed_collector