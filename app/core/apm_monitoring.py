"""
APM监控系统
============
实现应用性能监控（APM）功能
"""

import time
import threading
import logging
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict, deque
from datetime import datetime
import json

from app.core.logging_enhanced import monitor_performance
from app.core.exceptions import ConfigurationError, ErrorCode

logger = logging.getLogger(__name__)


class MetricType(Enum):
    """指标类型"""
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    TIMER = "timer"


class AlertSeverity(Enum):
    """告警严重程度"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class MetricData:
    """指标数据"""
    name: str
    value: float
    metric_type: MetricType
    timestamp: float
    tags: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Alert:
    """告警信息"""
    id: str
    severity: AlertSeverity
    metric_name: str
    condition: str
    current_value: float
    threshold: float
    message: str
    timestamp: float
    resolved: bool = False
    resolution_time: Optional[float] = None


@dataclass
class PerformanceTrace:
    """性能追踪"""
    trace_id: str
    operation: str
    start_time: float
    end_time: Optional[float] = None
    duration: Optional[float] = None
    status: str = "in_progress"
    metadata: Dict[str, Any] = field(default_factory=dict)
    spans: List['PerformanceTrace'] = field(default_factory=list)


class APMCollector:
    """APM数据收集器"""
    
    def __init__(self, max_metrics: int = 10000, max_traces: int = 1000):
        self.max_metrics = max_metrics
        self.max_traces = max_traces
        
        self._metrics: deque = deque(maxlen=max_metrics)
        self._traces: Dict[str, PerformanceTrace] = {}
        self._alerts: List[Alert] = []
        self._lock = threading.RLock()
        
        self._metric_aggregates: Dict[str, Dict[str, Any]] = {}
        self._alert_rules: Dict[str, Dict[str, Any]] = {}
        
        self._alert_callbacks: List[Callable[[Alert], None]] = []
        self._metric_callbacks: List[Callable[[MetricData], None]] = []
    
    def record_metric(self, name: str, value: float,
                   metric_type: MetricType = MetricType.GAUGE,
                   tags: Optional[Dict[str, str]] = None,
                   metadata: Optional[Dict[str, Any]] = None):
        """记录指标
        
        Args:
            name: 指标名称
            value: 指标值
            metric_type: 指标类型
            tags: 标签
            metadata: 元数据
        """
        metric = MetricData(
            name=name,
            value=value,
            metric_type=metric_type,
            timestamp=time.time(),
            tags=tags or {},
            metadata=metadata or {}
        )
        
        with self._lock:
            self._metrics.append(metric)
            
            # 更新聚合数据
            self._update_aggregates(metric)
            
            # 检查告警
            self._check_alerts(metric)
        
        # 调用回调
        for callback in self._metric_callbacks:
            try:
                callback(metric)
            except Exception as e:
                logger.error(f"指标回调执行失败: {e}")
        
        logger.debug(f"记录指标: {name} = {value}")
    
    def increment_counter(self, name: str, value: float = 1.0,
                      tags: Optional[Dict[str, str]] = None):
        """增加计数器
        
        Args:
            name: 计数器名称
            value: 增加值
            tags: 标签
        """
        self.record_metric(name, value, MetricType.COUNTER, tags)
    
    def set_gauge(self, name: str, value: float,
                 tags: Optional[Dict[str, str]] = None):
        """设置仪表值
        
        Args:
            name: 仪表名称
            value: 仪表值
            tags: 标签
        """
        self.record_metric(name, value, MetricType.GAUGE, tags)
    
    def record_timing(self, name: str, duration: float,
                   tags: Optional[Dict[str, str]] = None):
        """记录计时
        
        Args:
            name: 计时名称
            duration: 持续时间（秒）
            tags: 标签
        """
        self.record_metric(name, duration, MetricType.TIMER, tags)
    
    def start_trace(self, operation: str,
                  metadata: Optional[Dict[str, Any]] = None) -> str:
        """开始性能追踪
        
        Args:
            operation: 操作名称
            metadata: 元数据
        
        Returns:
            追踪ID
        """
        trace_id = f"{operation}_{time.time_ns()}"
        
        trace = PerformanceTrace(
            trace_id=trace_id,
            operation=operation,
            start_time=time.time(),
            metadata=metadata or {}
        )
        
        with self._lock:
            self._traces[trace_id] = trace
        
        logger.debug(f"开始追踪: {operation} ({trace_id})")
        return trace_id
    
    def end_trace(self, trace_id: str, status: str = "completed"):
        """结束性能追踪
        
        Args:
            trace_id: 追踪ID
            status: 状态
        """
        with self._lock:
            if trace_id in self._traces:
                trace = self._traces[trace_id]
                trace.end_time = time.time()
                trace.duration = trace.end_time - trace.start_time
                trace.status = status
                
                logger.debug(f"结束追踪: {trace.operation} ({trace_id}) - 耗时: {trace.duration:.3f}s")
            else:
                logger.warning(f"追踪ID不存在: {trace_id}")
    
    def add_span(self, parent_trace_id: str, operation: str,
                metadata: Optional[Dict[str, Any]] = None) -> str:
        """添加子追踪
        
        Args:
            parent_trace_id: 父追踪ID
            operation: 操作名称
            metadata: 元数据
        
        Returns:
            子追踪ID
        """
        span_id = f"{operation}_{time.time_ns()}"
        
        span = PerformanceTrace(
            trace_id=span_id,
            operation=operation,
            start_time=time.time(),
            metadata=metadata or {}
        )
        
        with self._lock:
            if parent_trace_id in self._traces:
                self._traces[parent_trace_id].spans.append(span)
                self._traces[span_id] = span
            else:
                logger.warning(f"父追踪ID不存在: {parent_trace_id}")
        
        return span_id
    
    def _update_aggregates(self, metric: MetricData):
        """更新聚合数据"""
        name = metric.name
        
        if name not in self._metric_aggregates:
            self._metric_aggregates[name] = {
                'count': 0,
                'sum': 0.0,
                'min': float('inf'),
                'max': float('-inf'),
                'values': deque(maxlen=100)
            }
        
        agg = self._metric_aggregates[name]
        agg['count'] += 1
        agg['sum'] += metric.value
        agg['min'] = min(agg['min'], metric.value)
        agg['max'] = max(agg['max'], metric.value)
        agg['values'].append(metric.value)
    
    def add_alert_rule(self, metric_name: str, condition: str,
                     threshold: float, severity: AlertSeverity):
        """添加告警规则
        
        Args:
            metric_name: 指标名称
            condition: 条件表达式
            threshold: 阈值
            severity: 严重程度
        """
        rule_id = f"{metric_name}_{condition}_{threshold}"
        
        self._alert_rules[rule_id] = {
            'metric_name': metric_name,
            'condition': condition,
            'threshold': threshold,
            'severity': severity
        }
        
        logger.info(f"添加告警规则: {rule_id}")
    
    def _check_alerts(self, metric: MetricData):
        """检查告警条件"""
        for rule_id, rule in self._alert_rules.items():
            if rule['metric_name'] != metric.name:
                continue
            
            # 评估条件
            triggered = self._evaluate_condition(
                rule['condition'],
                metric.value,
                rule['threshold']
            )
            
            if triggered:
                alert = Alert(
                    id=rule_id,
                    severity=rule['severity'],
                    metric_name=metric.name,
                    condition=rule['condition'],
                    current_value=metric.value,
                    threshold=rule['threshold'],
                    message=f"指标 {metric.name} 触发告警: {rule['condition']} {rule['threshold']}",
                    timestamp=time.time()
                )
                
                self._alerts.append(alert)
                
                # 调用告警回调
                for callback in self._alert_callbacks:
                    try:
                        callback(alert)
                    except Exception as e:
                        logger.error(f"告警回调执行失败: {e}")
                
                logger.warning(f"触发告警: {alert.message}")
    
    def _evaluate_condition(self, condition: str, 
                        value: float, threshold: float) -> bool:
        """评估告警条件"""
        if condition == ">":
            return value > threshold
        elif condition == ">=":
            return value >= threshold
        elif condition == "<":
            return value < threshold
        elif condition == "<=":
            return value <= threshold
        elif condition == "==":
            return abs(value - threshold) < 0.001
        elif condition == "!=":
            return abs(value - threshold) >= 0.001
        else:
            logger.warning(f"未知告警条件: {condition}")
            return False
    
    def add_alert_callback(self, callback: Callable[[Alert], None]):
        """添加告警回调"""
        self._alert_callbacks.append(callback)
    
    def add_metric_callback(self, callback: Callable[[MetricData], None]):
        """添加指标回调"""
        self._metric_callbacks.append(callback)
    
    def get_metrics(self, name: Optional[str] = None,
                   limit: int = 1000) -> List[MetricData]:
        """获取指标数据
        
        Args:
            name: 指标名称（可选）
            limit: 返回数量限制
        
        Returns:
            指标数据列表
        """
        with self._lock:
            metrics = list(self._metrics)
            
            if name:
                metrics = [m for m in metrics if m.name == name]
            
            return metrics[-limit:]
    
    def get_aggregates(self, name: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        """获取聚合数据"""
        with self._lock:
            if name:
                return {name: self._metric_aggregates.get(name, {})}
            return self._metric_aggregates.copy()
    
    def get_traces(self, operation: Optional[str] = None,
                  status: Optional[str] = None,
                  limit: int = 100) -> List[PerformanceTrace]:
        """获取性能追踪
        
        Args:
            operation: 操作名称（可选）
            status: 状态（可选）
            limit: 返回数量限制
        
        Returns:
            性能追踪列表
        """
        with self._lock:
            traces = list(self._traces.values())
            
            if operation:
                traces = [t for t in traces if t.operation == operation]
            if status:
                traces = [t for t in traces if t.status == status]
            
            return traces[-limit:]
    
    def get_alerts(self, severity: Optional[AlertSeverity] = None,
                   resolved: Optional[bool] = None,
                   limit: int = 100) -> List[Alert]:
        """获取告警信息
        
        Args:
            severity: 严重程度（可选）
            resolved: 是否已解决（可选）
            limit: 返回数量限制
        
        Returns:
            告警列表
        """
        with self._lock:
            alerts = self._alerts.copy()
            
            if severity:
                alerts = [a for a in alerts if a.severity == severity]
            if resolved is not None:
                alerts = [a for a in alerts if a.resolved == resolved]
            
            return alerts[-limit:]
    
    def resolve_alert(self, alert_id: str):
        """解决告警
        
        Args:
            alert_id: 告警ID
        """
        with self._lock:
            for alert in self._alerts:
                if alert.id == alert_id:
                    alert.resolved = True
                    alert.resolution_time = time.time()
                    logger.info(f"告警已解决: {alert_id}")
                    return
            
            logger.warning(f"告警ID不存在: {alert_id}")
    
    def clear_old_metrics(self, older_than_seconds: float = 3600):
        """清理旧指标数据
        
        Args:
            older_than_seconds: 超过此时间的指标将被清理
        """
        cutoff_time = time.time() - older_than_seconds
        
        with self._lock:
            original_count = len(self._metrics)
            self._metrics = deque(
                [m for m in self._metrics if m.timestamp > cutoff_time],
                maxlen=self.max_metrics
            )
            
            removed_count = original_count - len(self._metrics)
            logger.info(f"清理旧指标: {removed_count} 个")
    
    def clear_old_traces(self, older_than_seconds: float = 3600):
        """清理旧追踪数据
        
        Args:
            older_than_seconds: 超过此时间的追踪将被清理
        """
        cutoff_time = time.time() - older_than_seconds
        
        with self._lock:
            to_remove = [
                trace_id for trace_id, trace in self._traces.items()
                if trace.start_time < cutoff_time
            ]
            
            for trace_id in to_remove:
                del self._traces[trace_id]
            
            logger.info(f"清理旧追踪: {len(to_remove)} 个")
    
    def export_metrics(self, file_path: str, format: str = "json"):
        """导出指标数据
        
        Args:
            file_path: 导出文件路径
            format: 导出格式（json/csv）
        """
        with self._lock:
            metrics_data = [
                {
                    'name': m.name,
                    'value': m.value,
                    'type': m.metric_type.value,
                    'timestamp': m.timestamp,
                    'tags': m.tags,
                    'metadata': m.metadata
                }
                for m in self._metrics
            ]
            
            if format == "json":
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(metrics_data, f, ensure_ascii=False, indent=2)
            elif format == "csv":
                import csv
                with open(file_path, 'w', encoding='utf-8', newline='') as f:
                    if metrics_data:
                        writer = csv.DictWriter(f)
                        writer.writeheader()
                        writer.writerows(metrics_data)
            else:
                raise ValueError(f"不支持的导出格式: {format}")
        
        logger.info(f"指标数据已导出: {file_path}")
    
    def get_system_health(self) -> Dict[str, Any]:
        """获取系统健康状态"""
        with self._lock:
            # 计算关键指标
            recent_metrics = [m for m in self._metrics 
                           if time.time() - m.timestamp < 300]  # 最近5分钟
            
            if not recent_metrics:
                return {'status': 'no_data'}
            
            # 按指标分组
            metrics_by_name = defaultdict(list)
            for metric in recent_metrics:
                metrics_by_name[metric.name].append(metric)
            
            # 计算健康状态
            health_status = 'healthy'
            issues = []
            
            for name, metrics in metrics_by_name.items():
                if name in self._alert_rules:
                    rule = self._alert_rules[name]
                    latest_value = metrics[-1].value
                    
                    if self._evaluate_condition(
                        rule['condition'],
                        latest_value,
                        rule['threshold']
                    ):
                        health_status = 'degraded'
                        issues.append({
                            'metric': name,
                            'value': latest_value,
                            'threshold': rule['threshold'],
                            'condition': rule['condition']
                        })
            
            # 活跃追踪统计
            active_traces = [
                t for t in self._traces.values()
                if t.status == 'in_progress'
            ]
            
            # 未解决告警统计
            unresolved_alerts = [
                a for a in self._alerts
                if not a.resolved
            ]
            
            return {
                'status': health_status,
                'timestamp': time.time(),
                'total_metrics': len(recent_metrics),
                'active_traces': len(active_traces),
                'unresolved_alerts': len(unresolved_alerts),
                'issues': issues,
                'metrics_summary': {
                    name: {
                        'count': len(metrics),
                        'latest_value': metrics[-1].value if metrics else None,
                        'avg_value': sum(m.value for m in metrics) / len(metrics) if metrics else None
                    }
                    for name, metrics in metrics_by_name.items()
                }
            }


class APMReporter:
    """APM报告器"""
    
    def __init__(self, collector: APMCollector):
        self._collector = collector
        self._report_interval = 60  # 默认60秒
        self._report_callbacks: List[Callable[[Dict[str, Any]], None]] = []
        self._running = False
        self._report_thread: Optional[threading.Thread] = None
    
    def start_reporting(self, interval: int = 60):
        """开始定期报告
        
        Args:
            interval: 报告间隔（秒）
        """
        self._report_interval = interval
        self._running = True
        
        self._report_thread = threading.Thread(
            target=self._report_loop,
            daemon=True
        )
        self._report_thread.start()
        
        logger.info(f"APM报告已启动，间隔: {interval}秒")
    
    def stop_reporting(self):
        """停止定期报告"""
        self._running = False
        
        if self._report_thread and self._report_thread.is_alive():
            self._report_thread.join(timeout=10)
        
        logger.info("APM报告已停止")
    
    def _report_loop(self):
        """报告循环"""
        while self._running:
            try:
                # 生成报告
                report = self._generate_report()
                
                # 调用报告回调
                for callback in self._report_callbacks:
                    try:
                        callback(report)
                    except Exception as e:
                        logger.error(f"报告回调执行失败: {e}")
                
                # 清理旧数据
                self._collector.clear_old_metrics(older_than_seconds=3600)
                self._collector.clear_old_traces(older_than_seconds=3600)
                
            except Exception as e:
                logger.error(f"报告生成失败: {e}")
            
            # 等待下次报告
            time.sleep(self._report_interval)
    
    def _generate_report(self) -> Dict[str, Any]:
        """生成APM报告"""
        health = self._collector.get_system_health()
        aggregates = self._collector.get_aggregates()
        recent_alerts = self._collector.get_alerts(resolved=False, limit=10)
        
        return {
            'timestamp': time.time(),
            'datetime': datetime.now().isoformat(),
            'system_health': health,
            'metric_aggregates': aggregates,
            'recent_alerts': recent_alerts,
            'report_period': self._report_interval
        }
    
    def add_report_callback(self, callback: Callable[[Dict[str, Any]], None]):
        """添加报告回调"""
        self._report_callbacks.append(callback)
    
    def generate_manual_report(self) -> Dict[str, Any]:
        """手动生成报告"""
        return self._generate_report()


# 全局实例
_global_apm_collector: Optional[APMCollector] = None
_global_apm_reporter: Optional[APMReporter] = None


def get_apm_collector(max_metrics: int = 10000, 
                      max_traces: int = 1000) -> APMCollector:
    """获取全局APM收集器"""
    global _global_apm_collector
    
    if _global_apm_collector is None:
        _global_apm_collector = APMCollector(max_metrics, max_traces)
    
    return _global_apm_collector


def get_apm_reporter(collector: Optional[APMCollector] = None) -> APMReporter:
    """获取全局APM报告器"""
    global _global_apm_reporter
    
    if _global_apm_reporter is None:
        if collector is None:
            collector = get_apm_collector()
        _global_apm_reporter = APMReporter(collector)
    
    return _global_apm_reporter


def record_performance_metric(name: str, value: float,
                        tags: Optional[Dict[str, str]] = None):
    """记录性能指标（便捷函数）"""
    collector = get_apm_collector()
    collector.record_metric(name, value, tags=tags)


def start_performance_trace(operation: str,
                      metadata: Optional[Dict[str, Any]] = None) -> str:
    """开始性能追踪（便捷函数）"""
    collector = get_apm_collector()
    return collector.start_trace(operation, metadata)


def end_performance_trace(trace_id: str, status: str = "completed"):
    """结束性能追踪（便捷函数）"""
    collector = get_apm_collector()
    collector.end_trace(trace_id, status)