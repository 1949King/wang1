"""
服务拆分核心模块
================
实现微服务化的核心基础设施
"""

import os
import logging
import threading
import time
import json
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
from abc import ABC, abstractmethod
from collections import defaultdict
from datetime import datetime
import uuid
import hashlib

from app.core.logging_enhanced import monitor_performance
from app.core.exceptions import ConfigurationError, ErrorCode

logger = logging.getLogger(__name__)


class ServiceType(Enum):
    """服务类型"""
    VIDEO_PROCESSING = "video_processing"
    RENDERING = "rendering"
    AI_ENGINE = "ai_engine"
    PROJECT_MANAGEMENT = "project_management"
    USER_MANAGEMENT = "user_management"
    CACHE = "cache"
    STORAGE = "storage"
    LOGGING = "logging"
    MONITORING = "monitoring"
    ALERTING = "alerting"
    PERMISSION = "permission"
    PLUGIN = "plugin"
    CONFIG = "config"


class ServiceStatus(Enum):
    """服务状态"""
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"
    DEGRADED = "degraded"
    MAINTENANCE = "maintenance"


@dataclass
class ServiceInstance:
    """服务实例"""
    instance_id: str
    service_type: ServiceType
    host: str
    port: int
    status: ServiceStatus
    created_at: float
    last_heartbeat: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'instance_id': self.instance_id,
            'service_type': self.service_type.value,
            'host': self.host,
            'port': self.port,
            'status': self.status.value,
            'created_at': self.created_at,
            'last_heartbeat': self.last_heartbeat,
            'metadata': self.metadata
        }


@dataclass
class ServiceHealth:
    """服务健康状态"""
    service_type: ServiceType
    healthy_instances: int
    total_instances: int
    error_rate: float
    avg_response_time: float
    last_check_time: float
    details: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'service_type': self.service_type.value,
            'healthy_instances': self.healthy_instances,
            'total_instances': self.total_instances,
            'error_rate': self.error_rate,
            'avg_response_time': self.avg_response_time,
            'last_check_time': self.last_check_time,
            'details': self.details
        }


class ServiceRegistry:
    """服务注册中心"""
    
    def __init__(self):
        self._services: Dict[str, ServiceInstance] = {}
        self._service_configs: Dict[str, Dict[str, Any]] = {}
        self._health_checks: Dict[str, ServiceHealth] = {}
        self._lock = threading.RLock()
        
        self._stats = {
            'total_services': 0,
            'active_services': 0,
            'total_instances': 0,
            'service_calls': defaultdict(int),
            'service_errors': defaultdict(int)
        }
    
    def register_service(self, service_type: ServiceType, 
                    host: str, port: int,
                    config: Optional[Dict[str, Any]] = None) -> str:
        """注册服务
        
        Args:
            service_type: 服务类型
            host: 服务主机
            port: 服务端口
            config: 服务配置
        
        Returns:
            服务实例ID
        """
        instance_id = f"{service_type.value}_{uuid.uuid4().hex}"
        
        instance = ServiceInstance(
            instance_id=instance_id,
            service_type=service_type,
            host=host,
            port=port,
            status=ServiceStatus.STARTING,
            created_at=time.time(),
            metadata=config or {}
        )
        
        with self._lock:
            self._services[instance_id] = instance
            self._service_configs[instance_id] = config or {}
            self._stats['total_services'] += 1
            self._stats['total_instances'] += 1
        
        logger.info(f"服务已注册: {service_type.value} @ {host}:{port}")
        return instance_id
    
    def unregister_service(self, instance_id: str) -> bool:
        """注销服务
        
        Args:
            instance_id: 服务实例ID
        
        Returns:
            是否注销成功
        """
        with self._lock:
            if instance_id not in self._services:
                logger.warning(f"服务实例不存在: {instance_id}")
                return False
            
            instance = self._services[instance_id]
            
            if instance.status == ServiceStatus.RUNNING:
                instance.status = ServiceStatus.STOPPING
                logger.info(f"服务停止中: {instance_id}")
            
            del self._services[instance_id]
            del self._service_configs[instance_id]
            self._stats['total_services'] -= 1
            self._stats['active_services'] -= 1
        
        logger.info(f"服务已注销: {instance_id}")
        return True
    
    def get_service_status(self, instance_id: str) -> Optional[ServiceInstance]:
        """获取服务状态"""
        with self._lock:
            return self._services.get(instance_id)
    
    def get_services_by_type(self, service_type: ServiceType) -> List[ServiceInstance]:
        """根据类型获取服务列表"""
        with self._lock:
            return [
                instance for instance in self._services.values()
                if instance.service_type == service_type
            ]
    
    def update_service_status(self, instance_id: str, 
                         status: ServiceStatus) -> bool:
        """更新服务状态
        
        Args:
            instance_id: 服务实例ID
            status: 新状态
        
        Returns:
            是否更新成功
        """
        with self._lock:
            if instance_id not in self._services:
                logger.warning(f"服务实例不存在: {instance_id}")
                return False
            
            self._services[instance_id].status = status
            self._services[instance_id].last_heartbeat = time.time()
            
            if status == ServiceStatus.RUNNING:
                self._stats['active_services'] += 1
            elif status == ServiceStatus.STOPPED:
                self._stats['active_services'] -= 1
        
        logger.info(f"服务状态已更新: {instance_id} -> {status.value}")
        return True
    
    def get_service_health(self, service_type: ServiceType) -> ServiceHealth:
        """获取服务健康状态"""
        instances = self.get_services_by_type(service_type)
        
        if not instances:
            return ServiceHealth(
                service_type=service_type,
                healthy_instances=0,
                total_instances=0,
                error_rate=0.0,
                avg_response_time=0.0,
                last_check_time=time.time(),
                details={}
            )
        
        healthy_count = sum(1 for instance in instances if instance.status == ServiceStatus.RUNNING)
        total_count = len(instances)
        
        # 计算错误率和响应时间
        service_calls = self._stats['service_calls'][service_type.value]
        service_errors = self._stats['service_errors'][service_type.value]
        
        error_rate = service_errors / service_calls if service_calls > 0 else 0.0
        avg_response_time = 0.0  # 简化版本
        
        return ServiceHealth(
            service_type=service_type,
            healthy_instances=healthy_count,
            total_instances=total_count,
            error_rate=error_rate,
            avg_response_time=avg_response_time,
            last_check_time=time.time(),
            details={
                'service_calls': service_calls,
                'service_errors': service_errors
            }
        )
    
    def record_service_call(self, instance_id: str, success: bool, 
                     response_time: float = 0.0):
        """记录服务调用"""
        instance = self.get_service_status(instance_id)
        
        if instance:
            service_type = instance.service_type
            self._stats['service_calls'][service_type.value] += 1
            
            if not success:
                self._stats['service_errors'][service_type.value] += 1
            
            instance.last_heartbeat = time.time()
        
        logger.debug(f"服务调用记录: {instance_id} - success: {success}")
    
    def get_all_services(self) -> List[ServiceInstance]:
        """获取所有服务"""
        with self._lock:
            return list(self._services.values())
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            return {
                'total_services': self._stats['total_services'],
                'active_services': self._stats['active_services'],
                'total_instances': self._stats['total_instances'],
                'service_calls': dict(self._stats['service_calls']),
                'service_errors': dict(self._stats['service_errors'])
            }


class ServiceDiscovery:
    """服务发现"""
    
    def __init__(self, registry: ServiceRegistry):
        self._registry = registry
        self._discovered_services: Dict[str, List[str]] = {}
        self._lock = threading.Lock()
    
    def discover_services(self, network_range: str = "192.168.1.0/24") -> Dict[str, List[str]]:
        """发现网络中的服务
        
        Args:
            network_range: 网络范围（CIDR格式）
        
        Returns:
            发现的服务列表
        """
        logger.info(f"开始服务发现: {network_range}")
        
        discovered = defaultdict(list)
        
        # 模拟服务发现（实际实现中应使用网络扫描）
        base_ip = network_range.split('/')[0]
        
        for i in range(1, 255):
            ip = f"{base_ip}.{i}"
            
            # 模拟发现常见服务端口
            discovered['video_processing'].append(f"{ip}:8001")
            discovered['rendering'].append(f"{ip}:8002")
            discovered['ai_engine'].append(f"{ip}:8003")
            discovered['project_management'].append(f"{ip}:8004")
            discovered['user_management'].append(f"{ip}:8005")
            discovered['cache'].append(f"{ip}:6379")
            discovered['storage'].append(f"{ip}:9000")
            discovered['logging'].append(f"{ip}:9200")
            discovered['monitoring'].append(f"{ip}:9090")
            discovered['alerting'].append(f"{ip}:9091")
            discovered['permission'].append(f"{ip}:9092")
            discovered['plugin'].append(f"{ip}:9093")
            discovered['config'].append(f"{ip}:9094")
        
        with self._lock:
            self._discovered_services = dict(discovered)
        
        logger.info(f"服务发现完成: 发现了 {len(discovered)} 个服务")
        return dict(discovered)
    
    def get_discovered_services(self) -> Dict[str, List[str]]:
        """获取已发现的服务"""
        with self._lock:
            return self._discovered_services.copy()


class ServiceLoadBalancer:
    """服务负载均衡器"""
    
    def __init__(self, registry: ServiceRegistry):
        self._registry = registry
        self._load_balancing_rules: Dict[str, List[str]] = {}
        self._current_instance: Optional[str] = None
        self._lock = threading.Lock()
        
        self._stats = {
            'total_requests': 0,
            'successful_requests': 0,
            'failed_requests': 0,
            'avg_response_time': 0.0
        }
    
    def register_service_instance(self, service_type: ServiceType, 
                          instance_id: str):
        """注册服务实例到负载均衡器"""
        self._load_balancing_rules[service_type.value].append(instance_id)
        logger.info(f"服务实例已注册到负载均衡器: {service_type.value} - {instance_id}")
    
    def get_next_instance(self, service_type: ServiceType) -> Optional[str]:
        """获取下一个服务实例（轮询）"""
        instances = self._load_balancing_rules.get(service_type.value, [])
        
        if not instances:
            return None
        
        # 简单轮询策略
        if self._current_instance is None:
            self._current_instance = instances[0]
        else:
            current_index = instances.index(self._current_instance) if self._current_instance in instances else 0
            next_index = (current_index + 1) % len(instances)
            self._current_instance = instances[next_index]
        
        return self._current_instance
    
    def record_request(self, success: bool, response_time: float = 0.0):
        """记录请求"""
        self._stats['total_requests'] += 1
        
        if success:
            self._stats['successful_requests'] += 1
        else:
            self._stats['failed_requests'] += 1
        
        # 更新平均响应时间
        total_requests = self._stats['total_requests']
        avg_response_time = self._stats['avg_response_time']
        
        self._stats['avg_response_time'] = (avg_response_time * (total_requests - 1) + response_time) / total_requests
        
        logger.debug(f"请求记录: success={success}, response_time={response_time}s")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            return self._stats.copy()


class ServiceOrchestrator:
    """服务编排器"""
    
    def __init__(self, registry: ServiceRegistry):
        self._registry = registry
        self._orchestration_rules: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        
        self._active_workflows: Dict[str, Dict[str, Any]] = {}
        self._workflow_history: List[Dict[str, Any]] = []
    
    def create_workflow(self, workflow_id: str, 
                   workflow_name: str,
                   services: List[str],
                   dependencies: Optional[List[str]] = None) -> str:
        """创建工作流
        
        Args:
            workflow_id: 工作流ID
            workflow_name: 工作流名称
            services: 涉及的服务列表
            dependencies: 依赖的工作流
        
        Returns:
            工作流ID
        """
        workflow = {
            'workflow_id': workflow_id,
            'workflow_name': workflow_name,
            'services': services,
            'dependencies': dependencies or [],
            'status': 'created',
            'created_at': time.time(),
            'config': {}
        }
        
        with self._lock:
            self._active_workflows[workflow_id] = workflow
        
        logger.info(f"工作流已创建: {workflow_name} ({workflow_id})")
        return workflow_id
    
    def execute_workflow(self, workflow_id: str, 
                   input_data: Dict[str, Any]) -> Dict[str, Any]:
        """执行工作流
        
        Args:
            workflow_id: 工作流ID
            input_data: 输入数据
        
        Returns:
            执行结果
        """
        with self._lock:
            if workflow_id not in self._active_workflows:
                return {
                    'success': False,
                    'error': 'Workflow not found',
                    'workflow_id': workflow_id
                }
            
            workflow = self._active_workflows[workflow_id]
            
            # 模拟工作流执行
            result = {
                'workflow_id': workflow_id,
                'status': 'completed',
                'started_at': time.time(),
                'completed_at': time.time(),
                'services_status': {
                    service: 'completed' for service in workflow['services']
                },
                'output': input_data
            }
            
            workflow['status'] = 'completed'
            self._workflow_history.append(result)
        
        logger.info(f"工作流已执行: {workflow_id}")
        return result
    
    def get_workflow_status(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """获取工作流状态"""
        with self._lock:
            return self._active_workflows.get(workflow_id)
    
    def get_active_workflows(self) -> List[Dict[str, Any]]:
        """获取活动工作流"""
        with self._lock:
            return list(self._active_workflows.values())
    
    def get_workflow_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """获取工作流历史"""
        with self._lock:
            return self._workflow_history[-limit:]


# 全局实例
_global_service_registry: Optional[ServiceRegistry] = None
_global_service_discovery: Optional[ServiceDiscovery] = None
_global_service_load_balancer: Optional[ServiceLoadBalancer] = None
_global_service_orchestrator: Optional[ServiceOrchestrator] = None


def get_service_registry() -> ServiceRegistry:
    """获取全局服务注册中心"""
    global _global_service_registry
    
    if _global_service_registry is None:
        _global_service_registry = ServiceRegistry()
    
    return _global_service_registry


def get_service_discovery() -> ServiceDiscovery:
    """获取全局服务发现"""
    global _global_service_discovery
    
    if _global_service_discovery is None:
        registry = get_service_registry()
        _global_service_discovery = ServiceDiscovery(registry)
    
    return _global_service_discovery


def get_service_load_balancer() -> ServiceLoadBalancer:
    """获取全局服务负载均衡器"""
    global _global_service_load_balancer
    
    if _global_service_load_balancer is None:
        registry = get_service_registry()
        _global_service_load_balancer = ServiceLoadBalancer(registry)
    
    return _global_service_load_balancer


def get_service_orchestrator() -> ServiceOrchestrator:
    """获取全局服务编排器"""
    global _global_service_orchestrator
    
    if _global_service_orchestrator is None:
        registry = get_service_registry()
        _global_service_orchestrator = ServiceOrchestrator(registry)
    
    return _global_service_orchestrator


def create_microservice(service_type: ServiceType, 
                   host: str = "localhost",
                   port: int = 8000,
                   config: Optional[Dict[str, Any]] = None) -> str:
    """创建微服务实例（便捷函数）"""
    registry = get_service_registry()
    return registry.register_service(service_type, host, port, config)


def discover_network_services(network_range: str = "192.168.1.0/24") -> Dict[str, List[str]]:
    """发现网络服务（便捷函数）"""
    discovery = get_service_discovery()
    return discovery.discover_services(network_range)