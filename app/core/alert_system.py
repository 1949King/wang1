"""
告警机制配置模块
==================
实现灵活的告警配置和通知系统
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
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from app.core.logging_enhanced import monitor_performance
from app.core.exceptions import ConfigurationError, ErrorCode

logger = logging.getLogger(__name__)


class AlertChannel(Enum):
    """告警渠道"""
    EMAIL = "email"
    SMS = "sms"
    WEBHOOK = "webhook"
    SLACK = "slack"
    DISCORD = "discord"
    TELEGRAM = "telegram"
    SYSTEM = "system"


class AlertPriority(Enum):
    """告警优先级"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class AlertRule:
    """告警规则"""
    rule_id: str
    name: str
    condition: str
    threshold: float
    priority: AlertPriority
    enabled: bool = True
    cooldown_seconds: int = 300
    channels: List[AlertChannel] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    last_triggered: float = 0.0
    trigger_count: int = 0


@dataclass
class AlertNotification:
    """告警通知"""
    alert_id: str
    rule_id: str
    priority: AlertPriority
    title: str
    message: str
    timestamp: float
    channels: List[AlertChannel]
    metadata: Dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    sent_at: Optional[Dict[str, float]] = None
    acknowledged: bool = False
    acknowledged_by: Optional[str] = None
    acknowledged_at: Optional[float] = None


class AlertManager:
    """告警管理器"""
    
    def __init__(self):
        self._rules: Dict[str, AlertRule] = {}
        self._notifications: deque = deque(maxlen=1000)
        self._lock = threading.RLock()
        
        self._notification_handlers: Dict[AlertChannel, Callable] = {}
        self._alert_callbacks: List[Callable[[AlertNotification], None]] = []
        
        self._stats = {
            'total_alerts': 0,
            'alerts_by_priority': defaultdict(int),
            'alerts_by_channel': defaultdict(int),
            'acknowledged_alerts': 0,
            'unacknowledged_alerts': 0
        }
        
        self._config = {
            'enabled': True,
            'default_channels': [AlertChannel.SYSTEM],
            'cooldown_enabled': True,
            'deduplication_enabled': True,
            'deduplication_window': 60
        }
    
    def add_rule(self, rule: AlertRule) -> bool:
        """添加告警规则
        
        Args:
            rule: 告警规则
        
        Returns:
            是否添加成功
        """
        with self._lock:
            if rule.rule_id in self._rules:
                logger.warning(f"告警规则已存在: {rule.rule_id}")
                return False
            
            rule.created_at = time.time()
            self._rules[rule.rule_id] = rule
        
        logger.info(f"添加告警规则: {rule.rule_id} - {rule.name}")
        return True
    
    def remove_rule(self, rule_id: str) -> bool:
        """移除告警规则
        
        Args:
            rule_id: 规则ID
        
        Returns:
            是否移除成功
        """
        with self._lock:
            if rule_id not in self._rules:
                logger.warning(f"告警规则不存在: {rule_id}")
                return False
            
            del self._rules[rule_id]
        
        logger.info(f"移除告警规则: {rule_id}")
        return True
    
    def enable_rule(self, rule_id: str) -> bool:
        """启用告警规则"""
        with self._lock:
            if rule_id in self._rules:
                self._rules[rule_id].enabled = True
                logger.info(f"启用告警规则: {rule_id}")
                return True
        return False
    
    def disable_rule(self, rule_id: str) -> bool:
        """禁用告警规则"""
        with self._lock:
            if rule_id in self._rules:
                self._rules[rule_id].enabled = False
                logger.info(f"禁用告警规则: {rule_id}")
                return True
        return False
    
    def update_rule(self, rule_id: str, **kwargs) -> bool:
        """更新告警规则
        
        Args:
            rule_id: 规则ID
            **kwargs: 要更新的字段
        
        Returns:
            是否更新成功
        """
        with self._lock:
            if rule_id not in self._rules:
                logger.warning(f"告警规则不存在: {rule_id}")
                return False
            
            rule = self._rules[rule_id]
            for key, value in kwargs.items():
                if hasattr(rule, key):
                    setattr(rule, key, value)
        
        logger.info(f"更新告警规则: {rule_id}")
        return True
    
    def check_alerts(self, metrics: Dict[str, float]) -> List[AlertNotification]:
        """检查告警条件
        
        Args:
            metrics: 指标字典
        
        Returns:
            触发的告警列表
        """
        if not self._config['enabled']:
            return []
        
        triggered_alerts = []
        current_time = time.time()
        
        with self._lock:
            for rule_id, rule in self._rules.items():
                if not rule.enabled:
                    continue
                
                # 检查冷却时间
                if self._config['cooldown_enabled']:
                    if current_time - rule.last_triggered < rule.cooldown_seconds:
                        continue
                
                # 检查条件
                if self._evaluate_condition(rule, metrics):
                    # 创建告警通知
                    notification = AlertNotification(
                        alert_id=f"{rule_id}_{int(current_time)}",
                        rule_id=rule_id,
                        priority=rule.priority,
                        title=f"告警: {rule.name}",
                        message=f"规则 '{rule.name}' 触发: {rule.condition} {rule.threshold}",
                        timestamp=current_time,
                        channels=rule.channels or self._config['default_channels'],
                        metadata=rule.metadata.copy()
                    )
                    
                    # 更新规则统计
                    rule.last_triggered = current_time
                    rule.trigger_count += 1
                    
                    triggered_alerts.append(notification)
                    self._notifications.append(notification)
                    
                    # 更新统计
                    self._stats['total_alerts'] += 1
                    self._stats['alerts_by_priority'][rule.priority] += 1
                    
                    logger.warning(f"触发告警: {rule_id} - {notification.message}")
        
        # 去重
        if self._config['deduplication_enabled']:
            triggered_alerts = self._deduplicate_alerts(triggered_alerts)
        
        # 发送通知
        for alert in triggered_alerts:
            self._send_notification(alert)
        
        return triggered_alerts
    
    def _evaluate_condition(self, rule: AlertRule, 
                         metrics: Dict[str, float]) -> bool:
        """评估告警条件"""
        metric_name = rule.condition.split()[0]
        
        if metric_name not in metrics:
            return False
        
        metric_value = metrics[metric_name]
        condition = rule.condition
        
        if ">" in condition:
            return metric_value > rule.threshold
        elif ">=" in condition:
            return metric_value >= rule.threshold
        elif "<" in condition:
            return metric_value < rule.threshold
        elif "<=" in condition:
            return metric_value <= rule.threshold
        elif "==" in condition:
            return abs(metric_value - rule.threshold) < 0.001
        elif "!=" in condition:
            return abs(metric_value - rule.threshold) >= 0.001
        else:
            logger.warning(f"未知告警条件: {condition}")
            return False
    
    def _deduplicate_alerts(self, 
                           alerts: List[AlertNotification]) -> List[AlertNotification]:
        """告警去重"""
        dedup_window = self._config['deduplication_window']
        cutoff_time = time.time() - dedup_window
        
        # 过滤掉时间窗口内的重复告警
        filtered_alerts = []
        seen_rules = set()
        
        for alert in reversed(alerts):
            if alert.timestamp < cutoff_time:
                continue
            
            rule_key = f"{alert.rule_id}_{alert.priority}"
            if rule_key in seen_rules:
                continue
            
            seen_rules.add(rule_key)
            filtered_alerts.append(alert)
        
        return list(reversed(filtered_alerts))
    
    def _send_notification(self, alert: AlertNotification):
        """发送告警通知"""
        for channel in alert.channels:
            if channel in self._notification_handlers:
                try:
                    self._notification_handlers[channel](alert)
                    alert.sent_at = alert.sent_at or {}
                    alert.sent_at[channel.value] = time.time()
                    logger.info(f"告警通知已发送: {alert.alert_id} -> {channel.value}")
                except Exception as e:
                    logger.error(f"告警通知发送失败: {channel.value} - {e}")
                    alert.sent_at = alert.sent_at or {}
                    alert.sent_at[channel.value] = None
            else:
                logger.warning(f"告警渠道未配置: {channel.value}")
        
        # 调用回调
        for callback in self._alert_callbacks:
            try:
                callback(alert)
            except Exception as e:
                logger.error(f"告警回调执行失败: {e}")
    
    def register_notification_handler(self, channel: AlertChannel, 
                                handler: Callable[[AlertNotification], None]):
        """注册通知处理器
        
        Args:
            channel: 告警渠道
            handler: 处理函数
        """
        self._notification_handlers[channel] = handler
        logger.info(f"注册告警通知处理器: {channel.value}")
    
    def unregister_notification_handler(self, channel: AlertChannel):
        """注销通知处理器"""
        if channel in self._notification_handlers:
            del self._notification_handlers[channel]
            logger.info(f"注销告警通知处理器: {channel.value}")
    
    def add_alert_callback(self, callback: Callable[[AlertNotification], None]):
        """添加告警回调"""
        self._alert_callbacks.append(callback)
    
    def acknowledge_alert(self, alert_id: str, user: str) -> bool:
        """确认告警
        
        Args:
            alert_id: 告警ID
            user: 确认用户
        
        Returns:
            是否确认成功
        """
        with self._lock:
            for alert in self._notifications:
                if alert.alert_id == alert_id:
                    alert.acknowledged = True
                    alert.acknowledged_by = user
                    alert.acknowledged_at = time.time()
                    
                    self._stats['acknowledged_alerts'] += 1
                    logger.info(f"告警已确认: {alert_id} by {user}")
                    return True
        
        logger.warning(f"告警ID不存在: {alert_id}")
        return False
    
    def get_alerts(self, priority: Optional[AlertPriority] = None,
                   acknowledged: Optional[bool] = None,
                   limit: int = 100) -> List[AlertNotification]:
        """获取告警列表
        
        Args:
            priority: 优先级过滤
            acknowledged: 是否已确认过滤
            limit: 返回数量限制
        
        Returns:
            告警列表
        """
        with self._lock:
            alerts = list(self._notifications)
            
            if priority:
                alerts = [a for a in alerts if a.priority == priority]
            if acknowledged is not None:
                alerts = [a for a in alerts if a.acknowledged == acknowledged]
            
            return alerts[-limit:]
    
    def get_rules(self, enabled: Optional[bool] = None) -> List[AlertRule]:
        """获取告警规则列表"""
        with self._lock:
            rules = list(self._rules.values())
            
            if enabled is not None:
                rules = [r for r in rules if r.enabled == enabled]
            
            return rules
    
    def get_rule(self, rule_id: str) -> Optional[AlertRule]:
        """获取单个告警规则"""
        with self._lock:
            return self._rules.get(rule_id)
    
    def get_stats(self) -> Dict[str, Any]:
        """获取告警统计"""
        with self._lock:
            # 计算未确认告警
            unacknowledged = sum(
                1 for alert in self._notifications 
                if not alert.acknowledged
            )
            
            self._stats['unacknowledged_alerts'] = unacknowledged
            
            return {
                'total_alerts': self._stats['total_alerts'],
                'alerts_by_priority': dict(self._stats['alerts_by_priority']),
                'alerts_by_channel': dict(self._stats['alerts_by_channel']),
                'acknowledged_alerts': self._stats['acknowledged_alerts'],
                'unacknowledged_alerts': unacknowledged,
                'total_rules': len(self._rules),
                'enabled_rules': sum(1 for r in self._rules.values() if r.enabled)
            }
    
    def clear_old_alerts(self, older_than_days: int = 7):
        """清理旧告警"""
        cutoff_time = time.time() - (older_than_days * 24 * 3600)
        
        with self._lock:
            original_count = len(self._notifications)
            
            # 创建新队列，只保留新告警
            new_notifications = deque(
                [alert for alert in self._notifications 
                 if alert.timestamp >= cutoff_time],
                maxlen=1000
            )
            
            self._notifications = new_notifications
            
            removed_count = original_count - len(self._notifications)
            logger.info(f"清理旧告警: {removed_count} 条")
    
    def export_rules(self, file_path: str):
        """导出告警规则
        
        Args:
            file_path: 导出文件路径
        """
        with self._lock:
            rules_data = [
                {
                    'rule_id': rule.rule_id,
                    'name': rule.name,
                    'condition': rule.condition,
                    'threshold': rule.threshold,
                    'priority': rule.priority.value,
                    'enabled': rule.enabled,
                    'cooldown_seconds': rule.cooldown_seconds,
                    'channels': [c.value for c in rule.channels],
                    'metadata': rule.metadata,
                    'created_at': rule.created_at,
                    'last_triggered': rule.last_triggered,
                    'trigger_count': rule.trigger_count
                }
                for rule in self._rules.values()
            ]
            
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(rules_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"告警规则已导出: {file_path}")
    
    def import_rules(self, file_path: str) -> int:
        """导入告警规则
        
        Args:
            file_path: 导入文件路径
        
        Returns:
            导入的规则数量
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                rules_data = json.load(f)
            
            imported_count = 0
            for rule_data in rules_data:
                rule = AlertRule(
                    rule_id=rule_data['rule_id'],
                    name=rule_data['name'],
                    condition=rule_data['condition'],
                    threshold=rule_data['threshold'],
                    priority=AlertPriority(rule_data['priority']),
                    enabled=rule_data.get('enabled', True),
                    cooldown_seconds=rule_data.get('cooldown_seconds', 300),
                    channels=[AlertChannel(c) for c in rule_data.get('channels', [])],
                    metadata=rule_data.get('metadata', {}),
                    created_at=rule_data.get('created_at', time.time()),
                    last_triggered=rule_data.get('last_triggered', 0.0),
                    trigger_count=rule_data.get('trigger_count', 0)
                )
                
                self._rules[rule.rule_id] = rule
                imported_count += 1
            
            logger.info(f"告警规则已导入: {imported_count} 条")
            return imported_count
            
        except Exception as e:
            logger.error(f"告警规则导入失败: {e}")
            raise ConfigurationError(
                ErrorCode.INVALID_PARAMETER,
                f"告警规则导入失败: {str(e)}",
                details={'file_path': file_path}
            )


class EmailAlertHandler:
    """邮件告警处理器"""
    
    def __init__(self, smtp_server: str, smtp_port: int,
                 username: str, password: str,
                 from_email: str):
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.from_email = from_email
    
    def send_alert(self, alert: AlertNotification) -> bool:
        """发送邮件告警
        
        Args:
            alert: 告警通知
        
        Returns:
            是否发送成功
        """
        try:
            # 创建邮件内容
            msg = MIMEMultipart()
            msg['From'] = self.from_email
            msg['To'] = self._get_recipients(alert)
            msg['Subject'] = alert.title
            
            # 邮件正文
            body = f"""
            告警详情:
            
            优先级: {alert.priority.value}
            时间: {datetime.fromtimestamp(alert.timestamp).strftime('%Y-%m-%d %H:%M:%S')}
            消息: {alert.message}
            
            元数据:
            {json.dumps(alert.metadata, ensure_ascii=False, indent=2)}
            """
            
            msg.attach(MIMEText(body, 'plain'))
            
            # 发送邮件
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.username, self.password)
                server.send_message(msg)
            
            logger.info(f"邮件告警已发送: {alert.alert_id}")
            return True
            
        except Exception as e:
            logger.error(f"邮件告警发送失败: {e}")
            return False
    
    def _get_recipients(self, alert: AlertNotification) -> List[str]:
        """获取收件人列表"""
        # 从元数据中获取收件人
        recipients = alert.metadata.get('recipients', [])
        
        if not recipients:
            # 使用默认收件人
            recipients = alert.metadata.get('default_recipients', [])
        
        return recipients


class WebhookAlertHandler:
    """Webhook告警处理器"""
    
    def __init__(self, webhook_url: str, timeout: int = 10):
        self.webhook_url = webhook_url
        self.timeout = timeout
    
    def send_alert(self, alert: AlertNotification) -> bool:
        """发送Webhook告警
        
        Args:
            alert: 告警通知
        
        Returns:
            是否发送成功
        """
        try:
            import requests
            
            payload = {
                'alert_id': alert.alert_id,
                'rule_id': alert.rule_id,
                'priority': alert.priority.value,
                'title': alert.title,
                'message': alert.message,
                'timestamp': alert.timestamp,
                'metadata': alert.metadata
            }
            
            response = requests.post(
                self.webhook_url,
                json=payload,
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                logger.info(f"Webhook告警已发送: {alert.alert_id}")
                return True
            else:
                logger.warning(f"Webhook告警发送失败: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"Webhook告警发送失败: {e}")
            return False


# 全局实例
_global_alert_manager: Optional[AlertManager] = None


def get_alert_manager() -> AlertManager:
    """获取全局告警管理器"""
    global _global_alert_manager
    
    if _global_alert_manager is None:
        _global_alert_manager = AlertManager()
    
    return _global_alert_manager